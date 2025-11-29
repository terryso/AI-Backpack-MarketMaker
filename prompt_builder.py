"""
Prompt building for LLM trading decisions.

This module handles the construction of prompts for the LLM,
including market data collection and context formatting.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from trading_config import (
    SYMBOLS,
    SYMBOL_TO_COIN,
    INTERVAL,
    START_CAPITAL,
)
from strategy_core import (
    build_market_snapshot as _strategy_build_market_snapshot,
    build_trading_prompt as _strategy_build_trading_prompt,
)
from trading_loop import (
    add_indicator_columns,
    calculate_atr_series,
    calculate_indicators,
)


def fetch_market_data(
    symbol: str,
    get_market_data_client: Callable[[], Any],
    interval: str = INTERVAL,
) -> Optional[Dict[str, Any]]:
    """Fetch current market data for a symbol."""
    market_client = get_market_data_client()
    if not market_client:
        logging.warning("Skipping market data fetch for %s: market data client unavailable.", symbol)
        return None

    try:
        klines = market_client.get_klines(symbol=symbol, interval=interval, limit=50)
        if not klines:
            logging.warning("Skipping market data fetch for %s: no klines returned.", symbol)
            return None

        df = pd.DataFrame(
            klines,
            columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
            ],
        )
        df["close"] = df["close"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["open"] = df["open"].astype(float)

        last = calculate_indicators(df)
        latest_bar = df.iloc[-1]

        funding_rates = market_client.get_funding_rate_history(symbol=symbol, limit=1)
        funding_rate = float(funding_rates[-1]) if funding_rates else 0.0

        return {
            "symbol": symbol,
            "price": float(latest_bar["close"]),
            "high": float(latest_bar["high"]),
            "low": float(latest_bar["low"]),
            "ema20": last["ema20"],
            "rsi": last["rsi"],
            "macd": last["macd"],
            "macd_signal": last["macd_signal"],
            "funding_rate": funding_rate,
        }
    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {e}")
        return None


def collect_prompt_market_data(
    symbol: str,
    get_market_data_client: Callable[[], Any],
    interval: str = INTERVAL,
) -> Optional[Dict[str, Any]]:
    """Return rich market snapshot for prompt composition."""
    market_client = get_market_data_client()
    if not market_client:
        return None

    try:
        execution_klines = market_client.get_klines(symbol=symbol, interval=interval, limit=200)
        df_execution = pd.DataFrame(
            execution_klines,
            columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
            ],
        )
        if df_execution.empty:
            return None

        numeric_cols = ["open", "high", "low", "close", "volume"]
        df_execution[numeric_cols] = df_execution[numeric_cols].astype(float)
        df_execution["mid_price"] = (df_execution["high"] + df_execution["low"]) / 2
        df_execution = add_indicator_columns(df_execution)

        structure_klines = market_client.get_klines(symbol=symbol, interval="1h", limit=100)
        df_structure = pd.DataFrame(
            structure_klines,
            columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
            ],
        )
        if df_structure.empty:
            return None
        df_structure[numeric_cols] = df_structure[numeric_cols].astype(float)
        df_structure = add_indicator_columns(df_structure, ema_lengths=(20, 50))
        df_structure["swing_high"] = df_structure["high"].rolling(window=5, center=True).max()
        df_structure["swing_low"] = df_structure["low"].rolling(window=5, center=True).min()
        df_structure["volume_sma"] = df_structure["volume"].rolling(window=20).mean()
        df_structure["volume_ratio"] = df_structure["volume"] / df_structure["volume_sma"].replace(0, np.nan)

        trend_klines = market_client.get_klines(symbol=symbol, interval="4h", limit=100)
        df_trend = pd.DataFrame(
            trend_klines,
            columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
            ],
        )
        if df_trend.empty:
            return None
        df_trend[numeric_cols] = df_trend[numeric_cols].astype(float)
        df_trend = add_indicator_columns(df_trend, ema_lengths=(20, 50, 200))
        df_trend["macd_histogram"] = df_trend["macd"] - df_trend["macd_signal"]
        df_trend["atr"] = calculate_atr_series(df_trend, 14)

        open_interest_values = market_client.get_open_interest_history(symbol=symbol, limit=30)
        funding_rates = market_client.get_funding_rate_history(symbol=symbol, limit=30)

        return _strategy_build_market_snapshot(
            symbol=symbol,
            coin=SYMBOL_TO_COIN[symbol],
            df_execution=df_execution,
            df_structure=df_structure,
            df_trend=df_trend,
            open_interest_values=open_interest_values,
            funding_rates=funding_rates,
        )
    except Exception as exc:
        logging.error("Failed to build market snapshot for %s: %s", symbol, exc, exc_info=True)
        return None


def build_position_payloads(
    positions: Dict[str, Dict[str, Any]],
    market_snapshots: Dict[str, Dict[str, Any]],
    calculate_unrealized_pnl: Callable[[str, float], float],
) -> List[Dict[str, Any]]:
    """Build position payloads for the prompt context."""
    position_payloads = []
    for coin, pos in positions.items():
        current_price = market_snapshots.get(coin, {}).get("price", pos["entry_price"])
        quantity = pos["quantity"]
        gross_unrealized = calculate_unrealized_pnl(coin, current_price)
        leverage = pos.get("leverage", 1) or 1
        if pos["side"] == "long":
            liquidation_price = pos["entry_price"] * max(0.0, 1 - 1 / leverage)
        else:
            liquidation_price = pos["entry_price"] * (1 + 1 / leverage)
        notional_value = quantity * current_price
        position_payloads.append({
            "symbol": coin,
            "side": pos["side"],
            "quantity": quantity,
            "entry_price": pos["entry_price"],
            "current_price": current_price,
            "liquidation_price": liquidation_price,
            "unrealized_pnl": gross_unrealized,
            "leverage": pos.get("leverage", 1),
            "exit_plan": {
                "profit_target": pos.get("profit_target"),
                "stop_loss": pos.get("stop_loss"),
                "invalidation_condition": pos.get("invalidation_condition"),
            },
            "confidence": pos.get("confidence", 0.0),
            "risk_usd": pos.get("risk_usd"),
            "sl_oid": pos.get("sl_oid", -1),
            "tp_oid": pos.get("tp_oid", -1),
            "wait_for_fill": pos.get("wait_for_fill", False),
            "entry_oid": pos.get("entry_oid", -1),
            "live_backend": pos.get("live_backend"),
            "notional_usd": notional_value,
        })
    return position_payloads


def format_prompt_for_deepseek(
    get_market_data_client: Callable[[], Any],
    get_positions: Callable[[], Dict[str, Dict[str, Any]]],
    get_balance: Callable[[], float],
    get_current_time: Callable,
    get_bot_start_time: Callable,
    increment_invocation_count: Callable[[], int],
    calculate_total_margin: Callable[[], float],
    calculate_unrealized_pnl: Callable[[str, float], float],
    interval: str = INTERVAL,
) -> str:
    """Compose a rich prompt resembling the original DeepSeek in-context format."""
    invocation_count = increment_invocation_count()
    now = get_current_time()
    bot_start_time = get_bot_start_time()
    minutes_running = int((now - bot_start_time).total_seconds() // 60)
    positions = get_positions()
    balance = get_balance()

    market_snapshots: Dict[str, Dict[str, Any]] = {}
    for symbol in SYMBOLS:
        snapshot = collect_prompt_market_data(symbol, get_market_data_client, interval)
        if snapshot:
            market_snapshots[snapshot["coin"]] = snapshot

    total_margin = calculate_total_margin()
    total_equity = balance + total_margin
    for coin, pos in positions.items():
        current_price = market_snapshots.get(coin, {}).get("price", pos["entry_price"])
        total_equity += calculate_unrealized_pnl(coin, current_price)

    total_return = ((total_equity - START_CAPITAL) / START_CAPITAL) * 100 if START_CAPITAL else 0.0
    net_unrealized_total = total_equity - balance - total_margin

    position_payloads = build_position_payloads(
        positions, market_snapshots, calculate_unrealized_pnl
    )

    context = {
        "minutes_running": minutes_running,
        "now_iso": now.isoformat(),
        "invocation_count": invocation_count,
        "interval": interval,
        "market_snapshots": market_snapshots,
        "account": {
            "total_return": total_return,
            "balance": balance,
            "total_margin": total_margin,
            "net_unrealized_total": net_unrealized_total,
            "total_equity": total_equity,
        },
        "positions": position_payloads,
    }

    return _strategy_build_trading_prompt(context)
