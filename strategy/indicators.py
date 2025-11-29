"""Technical indicator calculations.

This module provides functions for calculating common technical indicators
used in trading strategies, including RSI, EMA, MACD, and ATR.
"""
from __future__ import annotations

from typing import Any, Iterable, List

import numpy as np
import pandas as pd


def calculate_rsi_series(close: pd.Series, period: int) -> pd.Series:
    """Return RSI series for specified period using Wilder's smoothing.
    
    Args:
        close: Series of closing prices.
        period: RSI calculation period.
        
    Returns:
        Series of RSI values.
    """
    delta = close.astype(float).diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    alpha = 1 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def add_indicator_columns(
    df: pd.DataFrame,
    ema_lengths: Iterable[int] = (20,),
    rsi_periods: Iterable[int] = (14,),
    macd_params: Iterable[int] = (12, 26, 9),
) -> pd.DataFrame:
    """Return copy of df with EMA, RSI, and MACD columns added.
    
    Args:
        df: DataFrame with 'close' column.
        ema_lengths: EMA periods to calculate.
        rsi_periods: RSI periods to calculate.
        macd_params: Tuple of (fast, slow, signal) periods for MACD.
        
    Returns:
        DataFrame with indicator columns added.
    """
    ema_lengths = tuple(dict.fromkeys(ema_lengths))
    rsi_periods = tuple(dict.fromkeys(rsi_periods))
    fast, slow, signal = macd_params

    result = df.copy()
    close = result["close"]

    for span in ema_lengths:
        result[f"ema{span}"] = close.ewm(span=span, adjust=False).mean()

    for period in rsi_periods:
        result[f"rsi{period}"] = calculate_rsi_series(close, period)

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    result["macd"] = macd_line
    result["macd_signal"] = macd_line.ewm(span=signal, adjust=False).mean()

    return result


def calculate_atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Return Average True Range series for the provided period.
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns.
        period: ATR calculation period.
        
    Returns:
        Series of ATR values.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr_components = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    true_range = tr_components.max(axis=1)
    alpha = 1 / period
    return true_range.ewm(alpha=alpha, adjust=False).mean()


def calculate_indicators(
    df: pd.DataFrame,
    ema_len: int,
    rsi_len: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
) -> pd.Series:
    """Calculate technical indicators and return the latest row.
    
    Args:
        df: DataFrame with OHLCV data.
        ema_len: EMA period.
        rsi_len: RSI period.
        macd_fast: MACD fast period.
        macd_slow: MACD slow period.
        macd_signal: MACD signal period.
        
    Returns:
        Series containing the latest indicator values.
    """
    enriched = add_indicator_columns(
        df,
        ema_lengths=(ema_len,),
        rsi_periods=(rsi_len,),
        macd_params=(macd_fast, macd_slow, macd_signal),
    )
    enriched["rsi"] = enriched[f"rsi{rsi_len}"]
    return enriched.iloc[-1]


def round_series(values: Iterable[Any], precision: int) -> List[float]:
    """Round numeric iterable to the given precision, skipping NaNs.
    
    Args:
        values: Iterable of numeric values.
        precision: Number of decimal places.
        
    Returns:
        List of rounded float values.
    """
    rounded: List[float] = []
    for value in values:
        try:
            if pd.isna(value):
                continue
        except TypeError:
            # Non-numeric/NA sentinel types fall back to ValueError later
            pass
        try:
            rounded.append(round(float(value), precision))
        except (TypeError, ValueError):
            continue
    return rounded
