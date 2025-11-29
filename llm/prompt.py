"""LLM prompt building for trading decisions.

This module provides functions for constructing prompts that are sent
to the LLM for trading decision generation.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import numpy as np
import pandas as pd


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
