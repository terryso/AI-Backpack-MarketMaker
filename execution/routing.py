"""Trade routing and planning logic.

This module provides functions for computing entry/close plans and
routing live trades to the appropriate exchange backends.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import logging

from exchange.base import CloseResult, EntryResult
from exchange.factory import get_exchange_client


@dataclass
class EntryPlan:
    """Computed entry plan with position sizing and fees."""
    side: str
    leverage: float
    stop_loss_price: float
    profit_target_price: float
    risk_usd: float
    quantity: float
    position_value: float
    margin_required: float
    liquidity: str
    fee_rate: float
    entry_fee: float
    total_cost: float
    raw_reason: str


def compute_entry_plan(
    *,
    coin: str,
    decision: Dict[str, Any],
    current_price: float,
    balance: float,
    is_live_backend: bool,
    live_max_leverage: float,
    live_max_risk_usd: float,
    live_max_margin_usd: float,
    maker_fee_rate: float,
    taker_fee_rate: float,
) -> Optional[EntryPlan]:
    """Compute position sizing, margin, and fee parameters for an entry.

    This helper mirrors the risk and sizing logic from bot.execute_entry but
    operates purely on provided arguments so it can be reused from different
    entry points without depending on bot module globals.
    """
    side = str(decision.get("side", "long")).lower()
    raw_reason = str(decision.get("justification", "")).strip()
    reason_text_compact = " ".join(raw_reason.split()) if raw_reason else ""
    if reason_text_compact:
        contradictory_phrases = (
            "no entry",
            "no long entry",
            "no short entry",
            "do not enter",
            "avoid entry",
            "skip entry",
        )
        reason_lower = reason_text_compact.lower()
        if any(phrase in reason_lower for phrase in contradictory_phrases):
            logging.warning(
                "%s: Skipping entry because AI justification contradicts signal (%s)",
                coin,
                reason_text_compact,
            )
            return None

    leverage_raw = decision.get("leverage", 10)
    try:
        leverage = float(leverage_raw)
        if leverage <= 0:
            leverage = 1.0
    except (TypeError, ValueError):
        logging.warning("%s: Invalid leverage '%s'; defaulting to 1x", coin, leverage_raw)
        leverage = 1.0

    risk_usd_raw = decision.get("risk_usd", balance * 0.01)
    try:
        risk_usd = float(risk_usd_raw)
    except (TypeError, ValueError):
        logging.warning(
            "%s: Invalid risk_usd '%s'; defaulting to 1%% of balance.",
            coin,
            risk_usd_raw,
        )
        risk_usd = balance * 0.01

    if is_live_backend:
        if live_max_leverage > 0 and leverage > live_max_leverage:
            leverage = live_max_leverage
        if live_max_risk_usd > 0 and risk_usd > live_max_risk_usd:
            risk_usd = live_max_risk_usd

    try:
        stop_loss_price = float(decision["stop_loss"])
        profit_target_price = float(decision["profit_target"])
    except (KeyError, TypeError, ValueError):
        logging.warning("%s: Invalid stop loss or profit target in decision; skipping entry.", coin)
        return None

    if stop_loss_price <= 0 or profit_target_price <= 0:
        logging.warning(
            "%s: Non-positive stop loss (%s) or profit target (%s); skipping entry.",
            coin,
            stop_loss_price,
            profit_target_price,
        )
        return None

    if side == "long":
        if stop_loss_price >= current_price:
            logging.warning(
                "%s: Stop loss %s not below current price %s for long; skipping entry.",
                coin,
                stop_loss_price,
                current_price,
            )
            return None
        if profit_target_price <= current_price:
            logging.warning(
                "%s: Profit target %s not above current price %s for long; skipping entry.",
                coin,
                profit_target_price,
                current_price,
            )
            return None
    elif side == "short":
        if stop_loss_price <= current_price:
            logging.warning(
                "%s: Stop loss %s not above current price %s for short; skipping entry.",
                coin,
                stop_loss_price,
                current_price,
            )
            return None
        if profit_target_price >= current_price:
            logging.warning(
                "%s: Profit target %s not below current price %s for short; skipping entry.",
                coin,
                profit_target_price,
                current_price,
            )
            return None

    stop_distance = abs(current_price - stop_loss_price)
    if stop_distance == 0:
        logging.warning("%s: Invalid stop loss, skipping", coin)
        return None

    quantity = risk_usd / stop_distance
    position_value = quantity * current_price
    margin_required = position_value / leverage if leverage else position_value

    if (
        is_live_backend
        and live_max_margin_usd > 0
        and margin_required > live_max_margin_usd
    ):
        logging.info(
            "%s: Margin %.2f exceeds live margin cap %.2f; scaling position down.",
            coin,
            margin_required,
            live_max_margin_usd,
        )
        margin_required = live_max_margin_usd
        position_value = margin_required * leverage
        quantity = position_value / current_price
        effective_risk_usd = quantity * stop_distance
        if effective_risk_usd < risk_usd:
            risk_usd = effective_risk_usd

    liquidity = str(decision.get("liquidity", "taker")).lower()
    fee_rate = decision.get("fee_rate")
    if fee_rate is not None:
        try:
            fee_rate = float(fee_rate)
        except (TypeError, ValueError):
            logging.warning(
                "%s: Invalid fee_rate provided (%s); defaulting to backend schedule.",
                coin,
                fee_rate,
            )
            fee_rate = None
    if fee_rate is None:
        fee_rate = maker_fee_rate if liquidity == "maker" else taker_fee_rate

    entry_fee = position_value * fee_rate
    total_cost = margin_required + entry_fee
    if total_cost > balance:
        logging.warning(
            "%s: Insufficient balance $%.2f for margin $%.2f and fees $%.2f",
            coin,
            balance,
            margin_required,
            entry_fee,
        )
        return None

    return EntryPlan(
        side=side,
        leverage=leverage,
        stop_loss_price=stop_loss_price,
        profit_target_price=profit_target_price,
        risk_usd=risk_usd,
        quantity=quantity,
        position_value=position_value,
        margin_required=margin_required,
        liquidity=liquidity,
        fee_rate=fee_rate,
        entry_fee=entry_fee,
        total_cost=total_cost,
        raw_reason=raw_reason,
    )


@dataclass
class ClosePlan:
    """Computed close plan with PnL and fee breakdown."""
    raw_reason: str
    reason_text: str
    pnl: float
    fee_rate: float
    exit_fee: float
    total_fees: float
    net_pnl: float


def compute_close_plan(
    *,
    coin: str,
    decision: Dict[str, Any],
    current_price: float,
    position: Dict[str, Any],
    pnl: float,
    default_fee_rate: float,
) -> ClosePlan:
    """Compute realized PnL and fee breakdown for a close operation.

    This helper mirrors the PnL and fee logic from bot.execute_close but
    operates solely on the provided position mapping and numeric inputs so it
    can be reused from different entry points.
    """
    raw_reason = str(decision.get("justification", "")).strip()
    base_reason = raw_reason or position.get("last_justification") or "AI close signal"
    reason_text = " ".join(base_reason.split())

    fee_rate = position.get("fee_rate", default_fee_rate)
    exit_fee = position["quantity"] * current_price * fee_rate
    total_fees = position.get("fees_paid", 0.0) + exit_fee
    net_pnl = pnl - total_fees

    return ClosePlan(
        raw_reason=raw_reason,
        reason_text=reason_text,
        pnl=pnl,
        fee_rate=fee_rate,
        exit_fee=exit_fee,
        total_fees=total_fees,
        net_pnl=net_pnl,
    )


def route_live_entry(
    *,
    coin: str,
    side: str,
    quantity: float,
    current_price: float,
    stop_loss_price: float,
    profit_target_price: float,
    leverage: float,
    liquidity: str,
    trading_backend: str,
    binance_futures_live: bool,
    backpack_futures_live: bool,
    hyperliquid_is_live: bool,
    get_binance_futures_exchange: Callable[[], Optional[Any]],
    backpack_api_public_key: str,
    backpack_api_secret_seed: str,
    backpack_api_base_url: str,
    backpack_api_window_ms: int,
    hyperliquid_trader: Any,
) -> Tuple[Optional[EntryResult], Optional[str]]:
    """Route a live entry to the appropriate backend and return (result, backend).

    This helper mirrors the live-execution branching logic from bot.execute_entry
    while concentrating it in a single place.
    """
    entry_result: Optional[EntryResult] = None
    live_backend: Optional[str] = None
    backend = (trading_backend or "").lower()

    if backend == "binance_futures" and binance_futures_live:
        exchange = get_binance_futures_exchange()
        if not exchange:
            logging.error(
                "Binance futures live trading enabled but client initialization failed; aborting entry.",
            )
            return None, None
        try:
            client = get_exchange_client("binance_futures", exchange=exchange)
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Failed to construct BinanceFuturesExchangeClient: %s", coin, exc)
            return None, None
        entry_result = client.place_entry(
            coin=coin,
            side=side,
            size=quantity,
            entry_price=current_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=profit_target_price,
            leverage=leverage,
            liquidity=liquidity,
        )
    elif backend == "backpack_futures" and backpack_futures_live:
        if not backpack_api_public_key or not backpack_api_secret_seed:
            logging.error(
                "Backpack futures live trading enabled but API keys are missing; aborting entry.",
            )
            return None, None
        try:
            client = get_exchange_client(
                "backpack_futures",
                api_public_key=backpack_api_public_key,
                api_secret_seed=backpack_api_secret_seed,
                base_url=backpack_api_base_url,
                window_ms=backpack_api_window_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Failed to construct BackpackFuturesExchangeClient: %s", coin, exc)
            return None, None
        entry_result = client.place_entry(
            coin=coin,
            side=side,
            size=quantity,
            entry_price=current_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=profit_target_price,
            leverage=leverage,
            liquidity=liquidity,
        )
    elif hyperliquid_is_live:
        try:
            client = get_exchange_client("hyperliquid", trader=hyperliquid_trader)
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Failed to construct HyperliquidExchangeClient: %s", coin, exc)
            logging.error("%s: Hyperliquid live trading will be skipped; proceeding in paper mode.", coin)
            return None, None
        entry_result = client.place_entry(
            coin=coin,
            side=side,
            size=quantity,
            entry_price=current_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=profit_target_price,
            leverage=leverage,
            liquidity=liquidity,
        )

    if entry_result is None:
        return None, None

    if not entry_result.success:
        joined_errors = "; ".join(entry_result.errors) if entry_result.errors else str(entry_result.raw)
        logging.error("%s: %s live entry failed: %s", coin, entry_result.backend, joined_errors)
        return None, None

    live_backend = entry_result.backend
    return entry_result, live_backend


def route_live_close(
    *,
    coin: str,
    side: str,
    quantity: float,
    current_price: float,
    trading_backend: str,
    binance_futures_live: bool,
    backpack_futures_live: bool,
    hyperliquid_is_live: bool,
    get_binance_futures_exchange: Callable[[], Optional[Any]],
    backpack_api_public_key: str,
    backpack_api_secret_seed: str,
    backpack_api_base_url: str,
    backpack_api_window_ms: int,
    hyperliquid_trader: Any,
    coin_to_symbol: Dict[str, str],
) -> Optional[CloseResult]:
    """Route a live close to the appropriate backend and return CloseResult.

    Mirrors the branching logic originally implemented in bot.execute_close.
    """
    close_result: Optional[CloseResult] = None
    backend = (trading_backend or "").lower()

    if backend == "binance_futures" and binance_futures_live:
        exchange = get_binance_futures_exchange()
        if not exchange:
            logging.error(
                "Binance futures live trading enabled but client initialization failed; position remains open.",
            )
            return None
        symbol = coin_to_symbol.get(coin)
        if not symbol:
            logging.error("%s: No Binance symbol mapping found; position remains open.", coin)
            return None
        try:
            client = get_exchange_client("binance_futures", exchange=exchange)
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Failed to construct BinanceFuturesExchangeClient for close: %s", coin, exc)
            return None
        close_result = client.close_position(
            coin=coin,
            side=side,
            size=quantity,
            fallback_price=current_price,
            symbol=symbol,
        )
    elif backend == "backpack_futures" and backpack_futures_live:
        if not backpack_api_public_key or not backpack_api_secret_seed:
            logging.error(
                "Backpack futures live trading enabled but API keys are missing; position remains open.",
            )
            return None
        try:
            client = get_exchange_client(
                "backpack_futures",
                api_public_key=backpack_api_public_key,
                api_secret_seed=backpack_api_secret_seed,
                base_url=backpack_api_base_url,
                window_ms=backpack_api_window_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Failed to construct BackpackFuturesExchangeClient for close: %s", coin, exc)
            return None
        close_result = client.close_position(
            coin=coin,
            side=side,
            size=quantity,
            fallback_price=current_price,
        )
    elif hyperliquid_is_live:
        try:
            client = get_exchange_client("hyperliquid", trader=hyperliquid_trader)
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Failed to construct HyperliquidExchangeClient for close: %s", coin, exc)
            logging.error("%s: Hyperliquid live close will be skipped; position remains open in paper state.", coin)
            return None
        close_result = client.close_position(
            coin=coin,
            side=side,
            size=quantity,
            fallback_price=current_price,
        )

    if close_result is None:
        return None

    if not close_result.success:
        joined_errors = "; ".join(close_result.errors) if close_result.errors else str(close_result.raw)
        logging.error("%s: %s live close failed; position remains open. %s", coin, close_result.backend, joined_errors)
        return None

    return close_result


def check_stop_loss_take_profit_for_positions(
    positions: Dict[str, Dict[str, Any]],
    symbol_to_coin: Dict[str, str],
    fetch_market_data: Callable[[str], Dict[str, Any]],
    execute_close: Callable[[str, Dict[str, Any], float], None],
    hyperliquid_is_live: bool,
) -> None:
    """Check and execute stop loss / take profit for all positions.

    This helper mirrors the behaviour of bot.check_stop_loss_take_profit but
    operates on explicit arguments so it can be reused from different entry
    points (live bot, backtests, tools) without depending on bot globals.
    """
    if hyperliquid_is_live:
        return

    for coin in list(positions.keys()):
        symbol = next((s for s, c in symbol_to_coin.items() if c == coin), None)
        if not symbol:
            logging.debug(
                "No symbol mapping found for coin %s when checking stop loss / take profit",
                coin,
            )
            continue

        data = fetch_market_data(symbol)
        if not data:
            continue

        pos = positions[coin]
        current_price = float(data.get("price", pos["entry_price"]))
        candle_high = data.get("high")
        candle_low = data.get("low")

        exit_reason = None
        exit_price = current_price

        if pos["side"] == "long":
            if candle_low is not None and candle_low <= pos["stop_loss"]:
                exit_reason = "Stop loss hit"
                exit_price = pos["stop_loss"]
            elif candle_high is not None and candle_high >= pos["profit_target"]:
                exit_reason = "Take profit hit"
                exit_price = pos["profit_target"]
        else:  # short
            if candle_high is not None and candle_high >= pos["stop_loss"]:
                exit_reason = "Stop loss hit"
                exit_price = pos["stop_loss"]
            elif candle_low is not None and candle_low <= pos["profit_target"]:
                exit_reason = "Take profit hit"
                exit_price = pos["profit_target"]

        if exit_reason is None:
            continue

        execute_close(coin, {"justification": exit_reason}, exit_price)
