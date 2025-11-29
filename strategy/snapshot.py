"""Market snapshot building for prompt composition.

This module provides functions for assembling rich market data snapshots
that are used in LLM prompt construction.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from strategy.indicators import round_series


def build_market_snapshot(
    symbol: str,
    coin: str,
    df_execution: pd.DataFrame,
    df_structure: pd.DataFrame,
    df_trend: pd.DataFrame,
    open_interest_values: List[float],
    funding_rates: List[float],
) -> Dict[str, Any]:
    """Assemble a rich market snapshot dictionary for prompt composition.

    This helper operates purely on data frames and numeric series without
    performing any I/O or logging.
    
    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT").
        coin: Coin name (e.g., "BTC").
        df_execution: DataFrame with execution timeframe data.
        df_structure: DataFrame with structure timeframe data.
        df_trend: DataFrame with trend timeframe data.
        open_interest_values: List of open interest values.
        funding_rates: List of funding rate values.
        
    Returns:
        Dictionary containing the market snapshot data.
    """
    funding_latest = funding_rates[-1] if funding_rates else 0.0

    price = float(df_execution["close"].iloc[-1])

    exec_tail = df_execution.tail(10)
    struct_tail = df_structure.tail(10)
    trend_tail = df_trend.tail(10)

    open_interest_latest = open_interest_values[-1] if open_interest_values else None
    open_interest_average = float(np.mean(open_interest_values)) if open_interest_values else None

    snapshot: Dict[str, Any] = {
        "symbol": symbol,
        "coin": coin,
        "price": price,
        "execution": {
            "ema20": float(df_execution["ema20"].iloc[-1]),
            "rsi14": float(df_execution["rsi14"].iloc[-1]),
            "macd": float(df_execution["macd"].iloc[-1]),
            "macd_signal": float(df_execution["macd_signal"].iloc[-1]),
            "series": {
                "mid_prices": round_series(exec_tail["mid_price"], 3),
                "ema20": round_series(exec_tail["ema20"], 3),
                "macd": round_series(exec_tail["macd"], 3),
                "rsi14": round_series(exec_tail["rsi14"], 3),
            },
        },
        "structure": {
            "ema20": float(df_structure["ema20"].iloc[-1]),
            "ema50": float(df_structure["ema50"].iloc[-1]),
            "rsi14": float(df_structure["rsi14"].iloc[-1]),
            "macd": float(df_structure["macd"].iloc[-1]),
            "macd_signal": float(df_structure["macd_signal"].iloc[-1]),
            "swing_high": float(df_structure["swing_high"].iloc[-1]),
            "swing_low": float(df_structure["swing_low"].iloc[-1]),
            "volume_ratio": float(df_structure["volume_ratio"].iloc[-1]),
            "series": {
                "close": round_series(struct_tail["close"], 3),
                "ema20": round_series(struct_tail["ema20"], 3),
                "ema50": round_series(struct_tail["ema50"], 3),
                "rsi14": round_series(struct_tail["rsi14"], 3),
                "macd": round_series(struct_tail["macd"], 3),
                "swing_high": round_series(struct_tail["swing_high"], 3),
                "swing_low": round_series(struct_tail["swing_low"], 3),
            },
        },
        "trend": {
            "ema20": float(df_trend["ema20"].iloc[-1]),
            "ema50": float(df_trend["ema50"].iloc[-1]),
            "ema200": float(df_trend["ema200"].iloc[-1]),
            "rsi14": float(df_trend["rsi14"].iloc[-1]),
            "macd": float(df_trend["macd"].iloc[-1]),
            "macd_signal": float(df_trend["macd_signal"].iloc[-1]),
            "macd_histogram": float(df_trend["macd_histogram"].iloc[-1]),
            "atr": float(df_trend["atr"].iloc[-1]),
            "current_volume": float(df_trend["volume"].iloc[-1]),
            "average_volume": float(df_trend["volume"].mean()),
            "series": {
                "close": round_series(trend_tail["close"], 3),
                "ema20": round_series(trend_tail["ema20"], 3),
                "ema50": round_series(trend_tail["ema50"], 3),
                "macd": round_series(trend_tail["macd"], 3),
                "rsi14": round_series(trend_tail["rsi14"], 3),
            },
        },
        "funding_rate": funding_latest,
        "funding_rates": funding_rates,
        "open_interest": {
            "latest": open_interest_latest,
            "average": open_interest_average,
        },
    }

    return snapshot
