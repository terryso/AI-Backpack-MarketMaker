"""
Trade execution logic.

This module handles the execution of entry and close trades,
including position management and notifications.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from colorama import Fore, Style

from trading_config import (
    SYMBOL_TO_COIN,
    COIN_TO_SYMBOL,
    MAKER_FEE_RATE,
    TAKER_FEE_RATE,
    IS_LIVE_BACKEND,
    LIVE_MAX_LEVERAGE,
    LIVE_MAX_RISK_USD,
    LIVE_MAX_MARGIN_USD,
    BACKPACK_API_PUBLIC_KEY,
    BACKPACK_API_SECRET_SEED,
    BACKPACK_API_BASE_URL,
    BACKPACK_API_WINDOW_MS,
    TELEGRAM_SIGNALS_CHAT_ID,
)
from metrics import (
    calculate_pnl_for_price,
    format_leverage_display,
)
from execution_routing import (
    check_stop_loss_take_profit_for_positions as _check_sltp_for_positions,
    compute_entry_plan as _compute_entry_plan,
    compute_close_plan as _compute_close_plan,
    route_live_entry as _route_live_entry,
    route_live_close as _route_live_close,
)
from exchange_client import CloseResult, EntryResult
from notifications import (
    emit_close_console_log,
    emit_entry_console_log,
    send_close_signal_to_telegram,
    send_entry_signal_to_telegram,
)


class TradeExecutor:
    """Handles trade execution with injected dependencies."""
    
    def __init__(
        self,
        positions: Dict[str, Dict[str, Any]],
        get_balance: Callable[[], float],
        set_balance: Callable[[float], None],
        get_current_time: Callable,
        calculate_unrealized_pnl: Callable[[str, float], float],
        estimate_exit_fee: Callable[[Dict[str, Any], float], float],
        record_iteration_message: Callable[[str], None],
        log_trade: Callable[[str, str, Dict[str, Any]], None],
        log_ai_decision: Callable[[str, str, str, float], None],
        save_state: Callable[[], None],
        send_telegram_message: Callable,
        escape_markdown: Callable[[str], str],
        fetch_market_data: Callable[[str], Optional[Dict[str, Any]]],
        hyperliquid_trader: Any,
        get_binance_futures_exchange: Callable,
        trading_backend: str,
        binance_futures_live: bool,
        backpack_futures_live: bool,
    ):
        self.positions = positions
        self.get_balance = get_balance
        self.set_balance = set_balance
        self.get_current_time = get_current_time
        self.calculate_unrealized_pnl = calculate_unrealized_pnl
        self.estimate_exit_fee = estimate_exit_fee
        self.record_iteration_message = record_iteration_message
        self.log_trade = log_trade
        self.log_ai_decision = log_ai_decision
        self.save_state = save_state
        self.send_telegram_message = send_telegram_message
        self.escape_markdown = escape_markdown
        self.fetch_market_data = fetch_market_data
        self.hyperliquid_trader = hyperliquid_trader
        self.get_binance_futures_exchange = get_binance_futures_exchange
        self.trading_backend = trading_backend
        self.binance_futures_live = binance_futures_live
        self.backpack_futures_live = backpack_futures_live

    def execute_entry(self, coin: str, decision: Dict[str, Any], current_price: float) -> None:
        """Execute entry trade."""
        if coin in self.positions:
            logging.warning(f"{coin}: Already have position, skipping entry")
            return

        balance = self.get_balance()
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
            (self.trading_backend == "binance_futures" and self.binance_futures_live)
            or (self.trading_backend == "backpack_futures" and self.backpack_futures_live)
            or (self.trading_backend == "hyperliquid" and self.hyperliquid_trader.is_live)
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
                trading_backend=self.trading_backend,
                binance_futures_live=self.binance_futures_live,
                backpack_futures_live=self.backpack_futures_live,
                hyperliquid_is_live=self.hyperliquid_trader.is_live,
                get_binance_futures_exchange=self.get_binance_futures_exchange,
                backpack_api_public_key=BACKPACK_API_PUBLIC_KEY,
                backpack_api_secret_seed=BACKPACK_API_SECRET_SEED,
                backpack_api_base_url=BACKPACK_API_BASE_URL,
                backpack_api_window_ms=BACKPACK_API_WINDOW_MS,
                hyperliquid_trader=self.hyperliquid_trader,
            )
            if entry_result is None and live_backend is None:
                return

        # Open position
        self.positions[coin] = {
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
        }

        self.set_balance(balance - total_cost)

        entry_price = current_price
        target_price = profit_target_price
        stop_price = stop_loss_price

        pos = self.positions[coin]
        gross_at_target = calculate_pnl_for_price(pos, target_price)
        gross_at_stop = calculate_pnl_for_price(pos, stop_price)
        exit_fee_target = self.estimate_exit_fee(pos, target_price)
        exit_fee_stop = self.estimate_exit_fee(pos, stop_price)
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
        reason_text_for_signal = self.escape_markdown(reason_text)

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
            record_fn=self.record_iteration_message,
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
                timestamp=self.get_current_time().strftime('%Y-%m-%d %H:%M:%S UTC'),
                send_fn=lambda text, chat_id, parse_mode: self.send_telegram_message(
                    text, chat_id=chat_id, parse_mode=parse_mode,
                ),
                signals_chat_id=TELEGRAM_SIGNALS_CHAT_ID,
            )
        except Exception as exc:
            logging.debug("Failed to send ENTRY signal to Telegram (non-fatal): %s", exc)

        self.log_trade(coin, 'ENTRY', {
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
        self.save_state()

    def execute_close(self, coin: str, decision: Dict[str, Any], current_price: float) -> None:
        """Execute close trade."""
        if coin not in self.positions:
            logging.warning(f"{coin}: No position to close")
            return

        pos = self.positions[coin]
        pnl = self.calculate_unrealized_pnl(coin, current_price)

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
        reason_text_for_signal = self.escape_markdown(reason_text)
        fee_rate = close_plan.fee_rate
        exit_fee = close_plan.exit_fee
        total_fees = close_plan.total_fees
        net_pnl = close_plan.net_pnl

        close_result: Optional[CloseResult] = None
        if (
            (self.trading_backend == "binance_futures" and self.binance_futures_live)
            or (self.trading_backend == "backpack_futures" and self.backpack_futures_live)
            or (self.trading_backend == "hyperliquid" and self.hyperliquid_trader.is_live)
        ):
            close_result = _route_live_close(
                coin=coin,
                side=pos['side'],
                quantity=pos['quantity'],
                current_price=current_price,
                trading_backend=self.trading_backend,
                binance_futures_live=self.binance_futures_live,
                backpack_futures_live=self.backpack_futures_live,
                hyperliquid_is_live=self.hyperliquid_trader.is_live,
                get_binance_futures_exchange=self.get_binance_futures_exchange,
                backpack_api_public_key=BACKPACK_API_PUBLIC_KEY,
                backpack_api_secret_seed=BACKPACK_API_SECRET_SEED,
                backpack_api_base_url=BACKPACK_API_BASE_URL,
                backpack_api_window_ms=BACKPACK_API_WINDOW_MS,
                hyperliquid_trader=self.hyperliquid_trader,
                coin_to_symbol=COIN_TO_SYMBOL,
            )
            if close_result is None:
                return

        # Return margin and add net PnL (after fees)
        balance = self.get_balance()
        new_balance = balance + pos['margin'] + net_pnl
        self.set_balance(new_balance)

        emit_close_console_log(
            coin=coin,
            pos=pos,
            current_price=current_price,
            pnl=pnl,
            exit_fee=exit_fee,
            total_fees=total_fees,
            net_pnl=net_pnl,
            reason_text=reason_text,
            balance=new_balance,
            close_result=close_result,
            print_fn=print,
            record_fn=self.record_iteration_message,
        )

        self.log_trade(coin, 'CLOSE', {
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

        del self.positions[coin]
        self.save_state()

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
                balance=new_balance,
                reason_text_for_signal=reason_text_for_signal,
                timestamp=self.get_current_time().strftime('%Y-%m-%d %H:%M:%S UTC'),
                send_fn=lambda text, chat_id, parse_mode: self.send_telegram_message(
                    text, chat_id=chat_id, parse_mode=parse_mode,
                ),
                signals_chat_id=TELEGRAM_SIGNALS_CHAT_ID,
            )
        except Exception as exc:
            logging.debug("Failed to send CLOSE signal to Telegram (non-fatal): %s", exc)

    def process_hold_signal(self, coin: str, decision: Dict[str, Any], current_price: float) -> None:
        """Process a hold signal for an existing position."""
        if coin not in self.positions:
            return

        pos = self.positions[coin]
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

        gross_unrealized = self.calculate_unrealized_pnl(coin, current_price)
        estimated_exit_fee_now = self.estimate_exit_fee(pos, current_price)
        total_fees_now = fees_paid + estimated_exit_fee_now
        net_unrealized = gross_unrealized - total_fees_now

        gross_at_target = calculate_pnl_for_price(pos, target_price)
        exit_fee_target = self.estimate_exit_fee(pos, target_price)
        net_at_target = gross_at_target - (fees_paid + exit_fee_target)

        gross_at_stop = calculate_pnl_for_price(pos, stop_price)
        exit_fee_stop = self.estimate_exit_fee(pos, stop_price)
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
        self.record_iteration_message(line)
        line = f"  ├─ Size: {quantity:.4f} {coin} | Margin: ${margin_value:.2f}"
        print(line)
        self.record_iteration_message(line)
        line = f"  ├─ TP: ${target_price:.4f} | SL: ${stop_price:.4f}"
        print(line)
        self.record_iteration_message(line)
        line = (
            f"  ├─ PnL: {pnl_color}${net_display}{Style.RESET_ALL} "
            f"(Gross: {gross_color}${gross_display}{Style.RESET_ALL}, Fees: ${total_fees_now:.2f})"
        )
        print(line)
        self.record_iteration_message(line)
        line = (
            f"  ├─ PnL @ Target: ${gross_target_display} "
            f"(Net: ${net_target_display})"
        )
        print(line)
        self.record_iteration_message(line)
        line = (
            f"  ├─ PnL @ Stop: ${gross_stop_display} "
            f"(Net: ${net_stop_display})"
        )
        print(line)
        self.record_iteration_message(line)
        line = f"  ├─ Reward/Risk: {rr_display}"
        print(line)
        self.record_iteration_message(line)
        line = f"  └─ Reason: {reason_text}"
        print(line)
        self.record_iteration_message(line)

    def process_ai_decisions(self, decisions: Dict[str, Any]) -> None:
        """Handle AI decisions for each tracked coin."""
        for coin in SYMBOL_TO_COIN.values():
            if coin not in decisions:
                continue

            decision = decisions[coin]
            signal = decision.get("signal", "hold")

            self.log_ai_decision(
                coin,
                signal,
                decision.get("justification", ""),
                decision.get("confidence", 0),
            )

            symbol = COIN_TO_SYMBOL.get(coin)
            if not symbol:
                logging.debug("No symbol mapping found for coin %s", coin)
                continue

            data = self.fetch_market_data(symbol)
            if not data:
                continue

            current_price = data["price"]

            if signal == "entry":
                self.execute_entry(coin, decision, current_price)
            elif signal == "close":
                self.execute_close(coin, decision, current_price)
            elif signal == "hold":
                self.process_hold_signal(coin, decision, current_price)

    def check_stop_loss_take_profit(self) -> None:
        """Check and execute stop loss / take profit for all positions."""
        _check_sltp_for_positions(
            positions=self.positions,
            symbol_to_coin=SYMBOL_TO_COIN,
            fetch_market_data=self.fetch_market_data,
            execute_close=self.execute_close,
            hyperliquid_is_live=self.hyperliquid_trader.is_live,
        )
