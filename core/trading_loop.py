"""
Trading loop and iteration logic.

This module contains the main trading loop, iteration processing,
and portfolio management functions.
"""
from __future__ import annotations

import csv
import time
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from colorama import Fore, Style

from config.settings import (
    SYMBOLS,
    SYMBOL_TO_COIN,
    COIN_TO_SYMBOL,
    INTERVAL,
    CHECK_INTERVAL,
    START_CAPITAL,
    RISK_FREE_RATE,
    EMA_LEN,
    RSI_LEN,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    MAKER_FEE_RATE,
    TAKER_FEE_RATE,
    IS_LIVE_BACKEND,
    LIVE_MAX_LEVERAGE,
    LIVE_MAX_RISK_USD,
    LIVE_MAX_MARGIN_USD,
    TRADING_BACKEND,
    BINANCE_FUTURES_LIVE,
    BACKPACK_FUTURES_LIVE,
    BACKPACK_API_PUBLIC_KEY,
    BACKPACK_API_SECRET_SEED,
    BACKPACK_API_BASE_URL,
    BACKPACK_API_WINDOW_MS,
    TELEGRAM_SIGNALS_CHAT_ID,
    STATE_CSV,
    TRADES_CSV,
    DECISIONS_CSV,
)
from core.state import (
    get_balance,
    set_balance,
    update_balance,
    get_positions,
    set_position,
    remove_position,
    get_current_time,
    get_bot_start_time,
    increment_invocation_count,
    get_iteration_messages,
    register_equity_snapshot,
    get_equity_history,
    save_state,
    escape_markdown,
)
from core.persistence import (
    append_portfolio_state_row as _append_portfolio_state_row,
    append_trade_row as _append_trade_row,
)
from core.metrics import (
    calculate_sortino_ratio as _metrics_calculate_sortino_ratio,
    calculate_pnl_for_price as _metrics_calculate_pnl_for_price,
    calculate_unrealized_pnl_for_position as _metrics_unrealized_pnl_for_pos,
    calculate_net_unrealized_pnl_for_position as _metrics_net_unrealized_pnl_for_pos,
    estimate_exit_fee_for_position as _metrics_estimate_exit_fee_for_pos,
    calculate_total_margin_for_positions as _metrics_total_margin_for_positions,
    format_leverage_display as _metrics_format_leverage_display,
)
from strategy.indicators import (
    calculate_rsi_series as _strategy_calculate_rsi_series,
    add_indicator_columns as _strategy_add_indicator_columns,
    calculate_atr_series as _strategy_calculate_atr_series,
    calculate_indicators as _strategy_calculate_indicators,
    round_series as _strategy_round_series,
)
from strategy.snapshot import build_market_snapshot as _strategy_build_market_snapshot
from llm.prompt import build_trading_prompt as _strategy_build_trading_prompt
from execution.routing import (
    check_stop_loss_take_profit_for_positions as _check_sltp_for_positions,
    compute_entry_plan as _compute_entry_plan,
    compute_close_plan as _compute_close_plan,
    route_live_entry as _route_live_entry,
    route_live_close as _route_live_close,
)
from exchange.base import CloseResult, EntryResult
from notifications.logging import (
    emit_close_console_log,
    emit_entry_console_log,
    record_iteration_message as _notifications_record_iteration_message,
)
from notifications.telegram import (
    send_close_signal_to_telegram,
    send_entry_signal_to_telegram,
)


# ───────────────────────── INDICATORS ───────────────────────
def calculate_rsi_series(close: pd.Series, period: int) -> pd.Series:
    """Return RSI series for specified period using Wilder's smoothing."""
    return _strategy_calculate_rsi_series(close, period)


def add_indicator_columns(
    df: pd.DataFrame,
    ema_lengths: Iterable[int] = (EMA_LEN,),
    rsi_periods: Iterable[int] = (RSI_LEN,),
    macd_params: Iterable[int] = (MACD_FAST, MACD_SLOW, MACD_SIGNAL),
) -> pd.DataFrame:
    """Return copy of df with EMA, RSI, and MACD columns added."""
    return _strategy_add_indicator_columns(df, ema_lengths, rsi_periods, macd_params)


def calculate_atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Return Average True Range series for the provided period."""
    return _strategy_calculate_atr_series(df, period)


def calculate_indicators(df: pd.DataFrame) -> pd.Series:
    """Calculate technical indicators and return the latest row."""
    return _strategy_calculate_indicators(
        df,
        EMA_LEN,
        RSI_LEN,
        MACD_FAST,
        MACD_SLOW,
        MACD_SIGNAL,
    )


def round_series(values: Iterable[Any], precision: int) -> List[float]:
    """Round numeric iterable to the given precision, skipping NaNs."""
    return _strategy_round_series(values, precision)


# ───────────────────────── POSITION MANAGEMENT ──────────────────
def calculate_unrealized_pnl(coin: str, current_price: float) -> float:
    """Calculate unrealized PnL for a position."""
    positions = get_positions()
    if coin not in positions:
        return 0.0
    pos = positions[coin]
    return _metrics_unrealized_pnl_for_pos(pos, current_price)


def calculate_net_unrealized_pnl(coin: str, current_price: float) -> float:
    """Calculate unrealized PnL after subtracting fees already paid."""
    positions = get_positions()
    pos = positions.get(coin)
    if not pos:
        return 0.0
    return _metrics_net_unrealized_pnl_for_pos(pos, current_price)


def calculate_pnl_for_price(pos: Dict[str, Any], target_price: float) -> float:
    """Return gross PnL for a hypothetical exit price."""
    return _metrics_calculate_pnl_for_price(pos, target_price)


def estimate_exit_fee(pos: Dict[str, Any], exit_price: float) -> float:
    """Estimate taker/maker fee required to exit the position at the given price."""
    return _metrics_estimate_exit_fee_for_pos(pos, exit_price, TAKER_FEE_RATE)


def format_leverage_display(leverage: Any) -> str:
    return _metrics_format_leverage_display(leverage)


def calculate_total_margin() -> float:
    """Return sum of margin allocated across all open positions."""
    positions = get_positions()
    return _metrics_total_margin_for_positions(positions.values())


def calculate_total_equity(fetch_market_data_fn: Callable) -> float:
    """Calculate total equity (balance + unrealized PnL)."""
    positions = get_positions()
    balance = get_balance()
    total = balance + calculate_total_margin()

    for coin in positions:
        symbol = next((s for s, c in SYMBOL_TO_COIN.items() if c == coin), None)
        if not symbol:
            continue
        data = fetch_market_data_fn(symbol)
        if data:
            total += calculate_unrealized_pnl(coin, data['price'])

    return total


def calculate_sortino_ratio(
    equity_values: Iterable[float],
    period_seconds: float,
    risk_free_rate: float = 0.0,
) -> Optional[float]:
    """Compute the annualized Sortino ratio from equity snapshots."""
    return _metrics_calculate_sortino_ratio(
        equity_values,
        period_seconds,
        risk_free_rate,
    )


# ───────────────────────── LOGGING ──────────────────────
def log_portfolio_state(
    fetch_market_data_fn: Callable,
    get_btc_benchmark_price_fn: Callable,
) -> None:
    """Log current portfolio state."""
    positions = get_positions()
    balance = get_balance()
    total_equity = calculate_total_equity(fetch_market_data_fn)
    total_return = ((total_equity - START_CAPITAL) / START_CAPITAL) * 100
    total_margin = calculate_total_margin()
    net_unrealized = total_equity - balance - total_margin

    position_details = "; ".join([
        f"{coin}:{pos['side']}:{pos['quantity']:.4f}@{pos['entry_price']:.4f}"
        for coin, pos in positions.items()
    ]) if positions else "No positions"

    btc_price = get_btc_benchmark_price_fn()
    btc_price_str = f"{btc_price:.2f}" if btc_price is not None else ""

    timestamp = get_current_time().isoformat()
    _append_portfolio_state_row(
        STATE_CSV,
        timestamp,
        f"{balance:.2f}",
        f"{total_equity:.2f}",
        f"{total_return:.2f}",
        len(positions),
        position_details,
        f"{total_margin:.2f}",
        f"{net_unrealized:.2f}",
        btc_price_str,
    )


def log_trade(coin: str, action: str, details: Dict[str, Any]) -> None:
    """Log trade execution."""
    timestamp = get_current_time().isoformat()
    balance = get_balance()
    _append_trade_row(
        TRADES_CSV,
        timestamp,
        coin,
        action,
        str(details.get('side', '')),
        details.get('quantity', 0),
        details.get('price', 0),
        details.get('profit_target', 0),
        details.get('stop_loss', 0),
        details.get('leverage', 1),
        details.get('confidence', 0),
        details.get('pnl', 0),
        balance,
        str(details.get('reason', '')),
    )


def log_ai_decision(coin: str, signal: str, reasoning: str, confidence: float) -> None:
    """Log AI decision."""
    with open(DECISIONS_CSV, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            get_current_time().isoformat(),
            coin,
            signal,
            reasoning,
            confidence
        ])


def record_iteration_message(text: str) -> None:
    """Record console output for this iteration to share via Telegram."""
    messages = get_iteration_messages()
    _notifications_record_iteration_message(messages, text)


# ───────────────────────── TRADE EXECUTION ──────────────────
def execute_entry(
    coin: str,
    decision: Dict[str, Any],
    current_price: float,
    hyperliquid_trader: Any,
    get_binance_futures_exchange: Callable,
    send_telegram_message_fn: Callable,
) -> None:
    """Execute entry trade."""
    positions = get_positions()
    balance = get_balance()

    if coin in positions:
        logging.warning(f"{coin}: Already have position, skipping entry")
        return

    plan = _compute_entry_plan(
        coin=coin,
        decision=decision,
        current_price=current_price,
        balance=balance,
        is_live_backend=IS_LIVE_BACKEND,
        live_max_leverage=LIVE_MAX_LEVERAGE,
        live_max_risk_usd=LIVE_MAX_RISK_USD,
        live_max_margin_usd=LIVE_MAX_MARGIN_USD,
        maker_fee_rate=MAKER_FEE_RATE,
        taker_fee_rate=TAKER_FEE_RATE,
    )
    if plan is None:
        return

    side = plan.side
    stop_loss_price = plan.stop_loss_price
    profit_target_price = plan.profit_target_price
    risk_usd = plan.risk_usd
    quantity = plan.quantity
    position_value = plan.position_value
    margin_required = plan.margin_required
    liquidity = plan.liquidity
    fee_rate = plan.fee_rate
    entry_fee = plan.entry_fee
    total_cost = plan.total_cost
    raw_reason = plan.raw_reason
    leverage = plan.leverage
    leverage_display = format_leverage_display(leverage)

    entry_result: Optional[EntryResult] = None
    live_backend: Optional[str] = None
    if (
        (TRADING_BACKEND == "binance_futures" and BINANCE_FUTURES_LIVE)
        or (TRADING_BACKEND == "backpack_futures" and BACKPACK_FUTURES_LIVE)
        or (TRADING_BACKEND == "hyperliquid" and hyperliquid_trader.is_live)
    ):
        entry_result, live_backend = _route_live_entry(
            coin=coin,
            side=side,
            quantity=quantity,
            current_price=current_price,
            stop_loss_price=stop_loss_price,
            profit_target_price=profit_target_price,
            leverage=leverage,
            liquidity=liquidity,
            trading_backend=TRADING_BACKEND,
            binance_futures_live=BINANCE_FUTURES_LIVE,
            backpack_futures_live=BACKPACK_FUTURES_LIVE,
            hyperliquid_is_live=hyperliquid_trader.is_live,
            get_binance_futures_exchange=get_binance_futures_exchange,
            backpack_api_public_key=BACKPACK_API_PUBLIC_KEY,
            backpack_api_secret_seed=BACKPACK_API_SECRET_SEED,
            backpack_api_base_url=BACKPACK_API_BASE_URL,
            backpack_api_window_ms=BACKPACK_API_WINDOW_MS,
            hyperliquid_trader=hyperliquid_trader,
        )
        if entry_result is None and live_backend is None:
            return

    # Open position
    set_position(coin, {
        'side': side,
        'quantity': quantity,
        'entry_price': current_price,
        'profit_target': profit_target_price,
        'stop_loss': stop_loss_price,
        'leverage': leverage,
        'confidence': decision.get('confidence', 0),
        'invalidation_condition': decision.get('invalidation_condition', ''),
        'margin': margin_required,
        'fees_paid': entry_fee,
        'fee_rate': fee_rate,
        'liquidity': liquidity,
        'risk_usd': risk_usd,
        'wait_for_fill': decision.get('wait_for_fill', False),
        'live_backend': live_backend,
        'entry_oid': entry_result.entry_oid if entry_result else -1,
        'tp_oid': entry_result.tp_oid if entry_result else -1,
        'sl_oid': entry_result.sl_oid if entry_result else -1,
        'entry_justification': raw_reason,
        'last_justification': raw_reason,
    })

    update_balance(-total_cost)

    entry_price = current_price
    target_price = profit_target_price
    stop_price = stop_loss_price

    pos = get_positions()[coin]
    gross_at_target = calculate_pnl_for_price(pos, target_price)
    gross_at_stop = calculate_pnl_for_price(pos, stop_price)
    exit_fee_target = estimate_exit_fee(pos, target_price)
    exit_fee_stop = estimate_exit_fee(pos, stop_price)
    net_at_target = gross_at_target - (entry_fee + exit_fee_target)
    net_at_stop = gross_at_stop - (entry_fee + exit_fee_stop)

    expected_reward = max(gross_at_target, 0.0)
    expected_risk = max(-gross_at_stop, 0.0)
    if expected_risk > 0:
        rr_value = expected_reward / expected_risk if expected_reward > 0 else 0.0
        rr_display = f"{rr_value:.2f}:1"
    else:
        rr_display = "n/a"

    reason_text = raw_reason or "No justification provided."
    reason_text = " ".join(reason_text.split())
    reason_text_for_signal = escape_markdown(reason_text)

    emit_entry_console_log(
        coin=coin,
        side=side,
        leverage_display=leverage_display,
        entry_price=entry_price,
        quantity=quantity,
        margin_required=margin_required,
        risk_usd=risk_usd,
        liquidity=liquidity,
        target_price=target_price,
        stop_price=stop_price,
        gross_at_target=gross_at_target,
        net_at_target=net_at_target,
        gross_at_stop=gross_at_stop,
        net_at_stop=net_at_stop,
        entry_fee=entry_fee,
        fee_rate=fee_rate,
        rr_display=rr_display,
        confidence=decision.get('confidence', 0),
        raw_reason=raw_reason,
        entry_result=entry_result,
        print_fn=print,
        record_fn=record_iteration_message,
    )

    try:
        send_entry_signal_to_telegram(
            coin=coin,
            side=side,
            leverage_display=leverage_display,
            entry_price=entry_price,
            quantity=quantity,
            margin_required=margin_required,
            risk_usd=risk_usd,
            profit_target_price=profit_target_price,
            stop_loss_price=stop_loss_price,
            gross_at_target=gross_at_target,
            gross_at_stop=gross_at_stop,
            rr_display=rr_display,
            entry_fee=entry_fee,
            confidence=decision.get('confidence', 0),
            reason_text_for_signal=reason_text_for_signal,
            liquidity=liquidity,
            timestamp=get_current_time().strftime('%Y-%m-%d %H:%M:%S UTC'),
            send_fn=lambda text, chat_id, parse_mode: send_telegram_message_fn(
                text,
                chat_id=chat_id,
                parse_mode=parse_mode,
            ),
            signals_chat_id=TELEGRAM_SIGNALS_CHAT_ID,
        )
    except Exception as exc:
        logging.debug("Failed to send ENTRY signal to Telegram (non-fatal): %s", exc)

    log_trade(coin, 'ENTRY', {
        'side': side,
        'quantity': quantity,
        'price': current_price,
        'profit_target': decision['profit_target'],
        'stop_loss': decision['stop_loss'],
        'leverage': leverage,
        'confidence': decision.get('confidence', 0),
        'pnl': 0,
        'reason': f"{reason_text or 'AI entry signal'} | Fees: ${entry_fee:.2f}"
    })
    save_state()


def execute_close(
    coin: str,
    decision: Dict[str, Any],
    current_price: float,
    hyperliquid_trader: Any,
    get_binance_futures_exchange: Callable,
    send_telegram_message_fn: Callable,
) -> None:
    """Execute close trade."""
    positions = get_positions()

    if coin not in positions:
        logging.warning(f"{coin}: No position to close")
        return

    pos = positions[coin]
    pnl = calculate_unrealized_pnl(coin, current_price)

    close_plan = _compute_close_plan(
        coin=coin,
        decision=decision,
        current_price=current_price,
        position=pos,
        pnl=pnl,
        default_fee_rate=TAKER_FEE_RATE,
    )
    raw_reason = close_plan.raw_reason
    reason_text = close_plan.reason_text
    reason_text_for_signal = escape_markdown(reason_text)
    fee_rate = close_plan.fee_rate
    exit_fee = close_plan.exit_fee
    total_fees = close_plan.total_fees
    net_pnl = close_plan.net_pnl

    close_result: Optional[CloseResult] = None
    if (
        (TRADING_BACKEND == "binance_futures" and BINANCE_FUTURES_LIVE)
        or (TRADING_BACKEND == "backpack_futures" and BACKPACK_FUTURES_LIVE)
        or (TRADING_BACKEND == "hyperliquid" and hyperliquid_trader.is_live)
    ):
        close_result = _route_live_close(
            coin=coin,
            side=pos['side'],
            quantity=pos['quantity'],
            current_price=current_price,
            trading_backend=TRADING_BACKEND,
            binance_futures_live=BINANCE_FUTURES_LIVE,
            backpack_futures_live=BACKPACK_FUTURES_LIVE,
            hyperliquid_is_live=hyperliquid_trader.is_live,
            get_binance_futures_exchange=get_binance_futures_exchange,
            backpack_api_public_key=BACKPACK_API_PUBLIC_KEY,
            backpack_api_secret_seed=BACKPACK_API_SECRET_SEED,
            backpack_api_base_url=BACKPACK_API_BASE_URL,
            backpack_api_window_ms=BACKPACK_API_WINDOW_MS,
            hyperliquid_trader=hyperliquid_trader,
            coin_to_symbol=COIN_TO_SYMBOL,
        )
        if close_result is None:
            return

    # Return margin and add net PnL (after fees)
    update_balance(pos['margin'] + net_pnl)

    emit_close_console_log(
        coin=coin,
        pos=pos,
        current_price=current_price,
        pnl=pnl,
        exit_fee=exit_fee,
        total_fees=total_fees,
        net_pnl=net_pnl,
        reason_text=reason_text,
        balance=get_balance(),
        close_result=close_result,
        print_fn=print,
        record_fn=record_iteration_message,
    )

    log_trade(coin, 'CLOSE', {
        'side': pos['side'],
        'quantity': pos['quantity'],
        'price': current_price,
        'profit_target': 0,
        'stop_loss': 0,
        'leverage': pos['leverage'],
        'confidence': 0,
        'pnl': net_pnl,
        'reason': (
            f"{reason_text} | "
            f"Gross: ${pnl:.2f} | Fees: ${total_fees:.2f}"
        )
    })

    remove_position(coin)
    save_state()

    try:
        send_close_signal_to_telegram(
            coin=coin,
            side=pos['side'],
            quantity=pos['quantity'],
            entry_price=pos['entry_price'],
            current_price=current_price,
            pnl=pnl,
            total_fees=total_fees,
            net_pnl=net_pnl,
            margin=pos['margin'],
            balance=get_balance(),
            reason_text_for_signal=reason_text_for_signal,
            timestamp=get_current_time().strftime('%Y-%m-%d %H:%M:%S UTC'),
            send_fn=lambda text, chat_id, parse_mode: send_telegram_message_fn(
                text,
                chat_id=chat_id,
                parse_mode=parse_mode,
            ),
            signals_chat_id=TELEGRAM_SIGNALS_CHAT_ID,
        )
    except Exception as exc:
        logging.debug("Failed to send CLOSE signal to Telegram (non-fatal): %s", exc)


def process_ai_decisions(
    decisions: Dict[str, Any],
    fetch_market_data_fn: Callable,
    hyperliquid_trader: Any,
    get_binance_futures_exchange: Callable,
    send_telegram_message_fn: Callable,
) -> None:
    """Handle AI decisions for each tracked coin."""
    positions = get_positions()

    for coin in SYMBOL_TO_COIN.values():
        if coin not in decisions:
            continue

        decision = decisions[coin]
        signal = decision.get("signal", "hold")

        log_ai_decision(
            coin,
            signal,
            decision.get("justification", ""),
            decision.get("confidence", 0),
        )

        symbol = COIN_TO_SYMBOL.get(coin)
        if not symbol:
            logging.debug("No symbol mapping found for coin %s", coin)
            continue

        data = fetch_market_data_fn(symbol)
        if not data:
            continue

        current_price = data["price"]

        if signal == "entry":
            execute_entry(
                coin, decision, current_price,
                hyperliquid_trader, get_binance_futures_exchange,
                send_telegram_message_fn,
            )
        elif signal == "close":
            execute_close(
                coin, decision, current_price,
                hyperliquid_trader, get_binance_futures_exchange,
                send_telegram_message_fn,
            )
        elif signal == "hold":
            _process_hold_signal(coin, decision, current_price)


def _process_hold_signal(coin: str, decision: Dict[str, Any], current_price: float) -> None:
    """Process a hold signal for an existing position."""
    positions = get_positions()
    if coin not in positions:
        return

    pos = positions[coin]
    raw_reason = str(decision.get("justification", "")).strip()
    if raw_reason:
        reason_text = " ".join(raw_reason.split())
        pos["last_justification"] = reason_text
    else:
        existing_reason = str(pos.get("last_justification", "")).strip()
        reason_text = existing_reason or "No justification provided."
        if not existing_reason:
            pos["last_justification"] = reason_text

    try:
        quantity = float(pos.get("quantity", 0.0))
    except (TypeError, ValueError):
        quantity = 0.0
    try:
        fees_paid = float(pos.get("fees_paid", 0.0))
    except (TypeError, ValueError):
        fees_paid = 0.0
    try:
        entry_price = float(pos.get("entry_price", 0.0))
    except (TypeError, ValueError):
        entry_price = 0.0
    try:
        target_price = float(pos.get("profit_target", entry_price))
    except (TypeError, ValueError):
        target_price = entry_price
    try:
        stop_price = float(pos.get("stop_loss", entry_price))
    except (TypeError, ValueError):
        stop_price = entry_price
    leverage_display = format_leverage_display(pos.get("leverage", 1.0))
    try:
        margin_value = float(pos.get("margin", 0.0))
    except (TypeError, ValueError):
        margin_value = 0.0
    try:
        risk_value = float(pos.get("risk_usd", 0.0))
    except (TypeError, ValueError):
        risk_value = 0.0

    gross_unrealized = calculate_unrealized_pnl(coin, current_price)
    estimated_exit_fee_now = estimate_exit_fee(pos, current_price)
    total_fees_now = fees_paid + estimated_exit_fee_now
    net_unrealized = gross_unrealized - total_fees_now

    gross_at_target = calculate_pnl_for_price(pos, target_price)
    exit_fee_target = estimate_exit_fee(pos, target_price)
    net_at_target = gross_at_target - (fees_paid + exit_fee_target)

    gross_at_stop = calculate_pnl_for_price(pos, stop_price)
    exit_fee_stop = estimate_exit_fee(pos, stop_price)
    net_at_stop = gross_at_stop - (fees_paid + exit_fee_stop)

    expected_reward = max(gross_at_target, 0.0)
    expected_risk = max(-gross_at_stop, 0.0)
    if expected_risk > 0:
        rr_value = expected_reward / expected_risk if expected_reward > 0 else 0.0
        rr_display = f"{rr_value:.2f}:1"
    else:
        rr_display = "n/a"

    pnl_color = Fore.GREEN if net_unrealized >= 0 else Fore.RED
    gross_color = Fore.GREEN if gross_unrealized >= 0 else Fore.RED
    net_display = f"{net_unrealized:+.2f}"
    gross_display = f"{gross_unrealized:+.2f}"
    gross_target_display = f"{gross_at_target:+.2f}"
    gross_stop_display = f"{gross_at_stop:+.2f}"
    net_target_display = f"{net_at_target:+.2f}"
    net_stop_display = f"{net_at_stop:+.2f}"

    line = f"{Fore.BLUE}[HOLD] {coin} {pos['side'].upper()} {leverage_display}"
    print(line)
    record_iteration_message(line)
    line = f"  ├─ Size: {quantity:.4f} {coin} | Margin: ${margin_value:.2f}"
    print(line)
    record_iteration_message(line)
    line = f"  ├─ TP: ${target_price:.4f} | SL: ${stop_price:.4f}"
    print(line)
    record_iteration_message(line)
    line = (
        f"  ├─ PnL: {pnl_color}${net_display}{Style.RESET_ALL} "
        f"(Gross: {gross_color}${gross_display}{Style.RESET_ALL}, Fees: ${total_fees_now:.2f})"
    )
    print(line)
    record_iteration_message(line)
    line = (
        f"  ├─ PnL @ Target: ${gross_target_display} "
        f"(Net: ${net_target_display})"
    )
    print(line)
    record_iteration_message(line)
    line = (
        f"  ├─ PnL @ Stop: ${gross_stop_display} "
        f"(Net: ${net_stop_display})"
    )
    print(line)
    record_iteration_message(line)
    line = f"  ├─ Reward/Risk: {rr_display}"
    print(line)
    record_iteration_message(line)
    line = f"  └─ Reason: {reason_text}"
    print(line)
    record_iteration_message(line)


def check_stop_loss_take_profit(
    fetch_market_data_fn: Callable,
    execute_close_fn: Callable,
    hyperliquid_is_live: bool,
) -> None:
    """Check and execute stop loss / take profit for all positions using intrabar extremes."""
    positions = get_positions()
    _check_sltp_for_positions(
        positions=positions,
        symbol_to_coin=SYMBOL_TO_COIN,
        fetch_market_data=fetch_market_data_fn,
        execute_close=execute_close_fn,
        hyperliquid_is_live=hyperliquid_is_live,
    )


def sleep_with_countdown(total_seconds: int) -> None:
    """Sleep with a simple terminal countdown on a single line."""
    try:
        remaining = int(total_seconds)
        if remaining <= 0:
            return
        while remaining > 0:
            print(
                f"\rWaiting for next check in {remaining} seconds... ",
                end="",
                flush=True,
            )
            time.sleep(1)
            remaining -= 1
        print("\rWaiting for next check in 0 seconds...           ")
    except KeyboardInterrupt:
        print()
        raise


def display_portfolio_summary(
    fetch_market_data_fn: Callable,
) -> None:
    """Display the portfolio summary at the end of an iteration."""
    positions = get_positions()
    balance = get_balance()
    total_equity = calculate_total_equity(fetch_market_data_fn)
    total_return = ((total_equity - START_CAPITAL) / START_CAPITAL) * 100
    equity_color = Fore.GREEN if total_return >= 0 else Fore.RED
    total_margin = calculate_total_margin()
    net_unrealized_total = total_equity - balance - total_margin
    net_color = Fore.GREEN if net_unrealized_total >= 0 else Fore.RED
    register_equity_snapshot(total_equity)
    sortino_ratio = calculate_sortino_ratio(
        get_equity_history(),
        CHECK_INTERVAL,
        RISK_FREE_RATE,
    )

    line = f"\n{Fore.YELLOW}{'─'*20}"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.YELLOW}PORTFOLIO SUMMARY"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.YELLOW}{'─'*20}"
    print(line)
    record_iteration_message(line)
    line = f"Available Balance: ${balance:.2f}"
    print(line)
    record_iteration_message(line)
    if total_margin > 0:
        line = f"Margin Allocated: ${total_margin:.2f}"
        print(line)
        record_iteration_message(line)
    line = f"Total Equity: {equity_color}${total_equity:.2f} ({total_return:+.2f}%){Style.RESET_ALL}"
    print(line)
    record_iteration_message(line)
    line = f"Unrealized PnL: {net_color}${net_unrealized_total:.2f}{Style.RESET_ALL}"
    print(line)
    record_iteration_message(line)
    if sortino_ratio is not None:
        sortino_color = Fore.GREEN if sortino_ratio >= 0 else Fore.RED
        line = f"Sortino Ratio: {sortino_color}{sortino_ratio:+.2f}{Style.RESET_ALL}"
    else:
        line = "Sortino Ratio: N/A (need more data)"
    print(line)
    record_iteration_message(line)
    line = f"Open Positions: {len(positions)}"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.YELLOW}{'─'*20}\n"
    print(line)
    record_iteration_message(line)
