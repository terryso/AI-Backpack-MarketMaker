"""LLM prompt building for trading decisions.

This module provides functions for constructing prompts that are sent
to the LLM for trading decision generation.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from config.settings import (
    SYMBOLS,
    SYMBOL_TO_COIN,
    INTERVAL,
    START_CAPITAL,
    EMA_LEN,
    RSI_LEN,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
)
from strategy.snapshot import build_market_snapshot as _strategy_build_market_snapshot
from strategy.indicators import (
    add_indicator_columns,
    calculate_atr_series,
    calculate_indicators,
)


def build_trading_prompt(context: Dict[str, Any]) -> str:
    """Render the full trading prompt text from a precomputed context.

    This function contains the string-assembly logic for LLM prompts,
    operating purely on a context dictionary to avoid depending on
    module globals.
    
    Args:
        context: Dictionary containing:
            - minutes_running: int
            - now_iso: str
            - invocation_count: int
            - interval: str
            - market_snapshots: Dict[str, Dict[str, Any]]
            - account: Dict[str, Any]
            - positions: List[Dict[str, Any]]
            
    Returns:
        Formatted prompt string for the LLM.
    """
    minutes_running: int = context["minutes_running"]
    now_iso: str = context["now_iso"]
    invocation_count: int = context["invocation_count"]
    interval: str = context["interval"]
    market_snapshots: Dict[str, Dict[str, Any]] = context["market_snapshots"]
    account: Dict[str, Any] = context["account"]
    positions: List[Dict[str, Any]] = context["positions"]

    total_return = float(account.get("total_return", 0.0))
    balance = float(account.get("balance", 0.0))
    total_margin = float(account.get("total_margin", 0.0))
    net_unrealized_total = float(account.get("net_unrealized_total", 0.0))
    total_equity = float(account.get("total_equity", 0.0))

    def fmt(value: Any, digits: int = 3) -> str:
        if value is None:
            return "N/A"
        try:
            if pd.isna(value):
                return "N/A"
        except TypeError:
            pass
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "N/A"

    def fmt_rate(value: Any) -> str:
        if value is None:
            return "N/A"
        try:
            if pd.isna(value):
                return "N/A"
        except TypeError:
            pass
        try:
            return f"{float(value):.6g}"
        except (TypeError, ValueError):
            return "N/A"

    prompt_lines: List[str] = []
    prompt_lines.append(
        f"It has been {minutes_running} minutes since you started trading. "
        f"The current time is {now_iso} and you've been invoked {invocation_count} times. "
        "Below, we are providing you with a variety of state data, price data, and predictive signals so you can discover alpha. "
        "Below that is your current account information, value, performance, positions, etc."
    )
    prompt_lines.append("ALL PRICE OR SIGNAL SERIES BELOW ARE ORDERED OLDEST → NEWEST.")
    prompt_lines.append(
        f"Timeframe note: Execution uses {interval} candles, Structure uses 1h candles, Trend uses 4h candles."
    )
    prompt_lines.append("-" * 80)
    prompt_lines.append("CURRENT MARKET STATE FOR ALL COINS (Multi-Timeframe Analysis)")

    for coin, data in market_snapshots.items():
        execution = data["execution"]
        structure = data["structure"]
        trend = data["trend"]
        open_interest = data["open_interest"]
        funding_rates = data.get("funding_rates", [])
        funding_avg_str = (
            fmt_rate(float(np.mean(funding_rates))) if funding_rates else "N/A"
        )

        prompt_lines.append(f"\n{coin} MARKET SNAPSHOT")
        prompt_lines.append(f"Current Price: {fmt(data['price'], 3)}")
        prompt_lines.append(
            f"Open Interest (latest/avg): {fmt(open_interest.get('latest'), 2)} / {fmt(open_interest.get('average'), 2)}"
        )
        prompt_lines.append(
            f"Funding Rate (latest/avg): {fmt_rate(data['funding_rate'])} / {funding_avg_str}"
        )

        prompt_lines.append("\n  4H TREND TIMEFRAME:")
        prompt_lines.append(
            "    EMA Alignment: "
            f"EMA20={fmt(trend['ema20'], 3)}, "
            f"EMA50={fmt(trend['ema50'], 3)}, "
            f"EMA200={fmt(trend['ema200'], 3)}"
        )
        ema_trend = (
            "BULLISH"
            if trend["ema20"] > trend["ema50"]
            else "BEARISH"
            if trend["ema20"] < trend["ema50"]
            else "NEUTRAL"
        )
        prompt_lines.append(f"    Trend Classification: {ema_trend}")
        prompt_lines.append(
            f"    MACD: {fmt(trend['macd'], 3)}, "
            f"Signal: {fmt(trend['macd_signal'], 3)}, "
            f"Histogram: {fmt(trend['macd_histogram'], 3)}"
        )
        prompt_lines.append(f"    RSI14: {fmt(trend['rsi14'], 2)}")
        prompt_lines.append(f"    ATR (for stop placement): {fmt(trend['atr'], 3)}")
        prompt_lines.append(
            f"    Volume: Current {fmt(trend['current_volume'], 2)}, "
            f"Average {fmt(trend['average_volume'], 2)}"
        )
        prompt_lines.append(
            f"    4H Series (last 10): Close={json.dumps(trend['series']['close'])}"
        )
        prompt_lines.append(
            "                         "
            f"EMA20={json.dumps(trend['series']['ema20'])}, "
            f"EMA50={json.dumps(trend['series']['ema50'])}"
        )
        prompt_lines.append(
            "                         "
            f"MACD={json.dumps(trend['series']['macd'])}, "
            f"RSI14={json.dumps(trend['series']['rsi14'])}"
        )

        prompt_lines.append("\n  1H STRUCTURE TIMEFRAME:")
        prompt_lines.append(
            f"    EMA20: {fmt(structure['ema20'], 3)}, EMA50: {fmt(structure['ema50'], 3)}"
        )
        struct_position = (
            "above" if data["price"] > structure["ema20"] else "below"
        )
        prompt_lines.append(f"    Price relative to 1H EMA20: {struct_position}")
        prompt_lines.append(
            f"    Swing High: {fmt(structure['swing_high'], 3)}, "
            f"Swing Low: {fmt(structure['swing_low'], 3)}"
        )
        prompt_lines.append(f"    RSI14: {fmt(structure['rsi14'], 2)}")
        prompt_lines.append(
            f"    MACD: {fmt(structure['macd'], 3)}, "
            f"Signal: {fmt(structure['macd_signal'], 3)}"
        )
        prompt_lines.append(
            f"    Volume Ratio: {fmt(structure['volume_ratio'], 2)}x (>1.5 = volume spike)"
        )
        prompt_lines.append(
            f"    1H Series (last 10): Close={json.dumps(structure['series']['close'])}"
        )
        prompt_lines.append(
            "                         "
            f"EMA20={json.dumps(structure['series']['ema20'])}, "
            f"EMA50={json.dumps(structure['series']['ema50'])}"
        )
        prompt_lines.append(
            "                         "
            f"Swing High={json.dumps(structure['series']['swing_high'])}, "
            f"Swing Low={json.dumps(structure['series']['swing_low'])}"
        )
        prompt_lines.append(
            "                         "
            f"RSI14={json.dumps(structure['series']['rsi14'])}"
        )

        prompt_lines.append(f"\n  {interval.upper()} EXECUTION TIMEFRAME:")
        prompt_lines.append(
            "    EMA20: "
            f"{fmt(execution['ema20'], 3)} "
            f"(Price {'above' if data['price'] > execution['ema20'] else 'below'} EMA20)"
        )
        prompt_lines.append(
            f"    MACD: {fmt(execution['macd'], 3)}, "
            f"Signal: {fmt(execution['macd_signal'], 3)}"
        )
        if execution["macd"] > execution["macd_signal"]:
            macd_direction = "bullish"
        elif execution["macd"] < execution["macd_signal"]:
            macd_direction = "bearish"
        else:
            macd_direction = "neutral"
        prompt_lines.append(f"    MACD Crossover: {macd_direction}")
        prompt_lines.append(f"    RSI14: {fmt(execution['rsi14'], 2)}")
        rsi_zone = (
            "oversold (<35)"
            if execution["rsi14"] < 35
            else "overbought (>65)"
            if execution["rsi14"] > 65
            else "neutral"
        )
        prompt_lines.append(f"    RSI Zone: {rsi_zone}")
        prompt_lines.append(
            f"    {interval.upper()} Series (last 10): Mid-Price={json.dumps(execution['series']['mid_prices'])}"
        )
        prompt_lines.append(
            f"                          EMA20={json.dumps(execution['series']['ema20'])}"
        )
        prompt_lines.append(
            f"                          MACD={json.dumps(execution['series']['macd'])}"
        )
        prompt_lines.append(
            f"                          RSI14={json.dumps(execution['series']['rsi14'])}"
        )

        prompt_lines.append("\n  MARKET SENTIMENT:")
        prompt_lines.append(
            "    Open Interest: "
            f"Latest={fmt(open_interest.get('latest'), 2)}, "
            f"Average={fmt(open_interest.get('average'), 2)}"
        )
        prompt_lines.append(
            "    Funding Rate: "
            f"Latest={fmt_rate(data['funding_rate'])}, "
            f"Average={funding_avg_str}"
        )
        prompt_lines.append("-" * 80)

    prompt_lines.append("ACCOUNT INFORMATION AND PERFORMANCE")
    prompt_lines.append(f"- Total Return (%): {fmt(total_return, 2)}")
    prompt_lines.append(f"- Available Cash: {fmt(balance, 2)}")
    prompt_lines.append(f"- Margin Allocated: {fmt(total_margin, 2)}")
    prompt_lines.append(f"- Unrealized PnL: {fmt(net_unrealized_total, 2)}")
    prompt_lines.append(f"- Current Account Value: {fmt(total_equity, 2)}")
    prompt_lines.append("Open positions and performance details:")

    for payload in positions:
        symbol = payload["symbol"]
        prompt_lines.append(f"{symbol} position data: {json.dumps(payload)}")

    sharpe_ratio = 0.0
    prompt_lines.append(f"Sharpe Ratio: {fmt(sharpe_ratio, 3)}")

    prompt_lines.append(
        """
INSTRUCTIONS:
For each coin, provide a trading decision in JSON format. You can either:
1. "hold" - Keep current position (if you have one)
2. "entry" - Open a new position (if you don't have one)
3. "close" - Close current position

Return ONLY a valid JSON object with this structure:
{
  "ETH": {
    "signal": "hold|entry|close",
    "side": "long|short",  // only for entry
    "quantity": 0.0,
    "profit_target": 0.0,
    "stop_loss": 0.0,
    "leverage": 10,
    "confidence": 0.75,
    "risk_usd": 500.0,
    "invalidation_condition": "If price closes below X on a 15-minute candle",
    "justification": "Reason for entry/close/hold"
  }
}

IMPORTANT:
- Only suggest entries if you see strong opportunities
- Use proper risk management
- Provide clear invalidation conditions
- Return ONLY valid JSON, no other text
""".strip()
    )

    return "\n".join(prompt_lines)


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

        last = calculate_indicators(df, EMA_LEN, RSI_LEN, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
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

    return build_trading_prompt(context)
