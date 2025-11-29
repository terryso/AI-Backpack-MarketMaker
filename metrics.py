from __future__ import annotations

from typing import Iterable, Optional

import numpy as np


# Annualized baseline for Sortino ratio calculations
DEFAULT_RISK_FREE_RATE: float = 0.0


def calculate_sortino_ratio(
    equity_values: Iterable[float],
    period_seconds: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> Optional[float]:
    """Compute the annualized Sortino ratio from equity snapshots.

    Args:
        equity_values: Sequence of equity values in chronological order.
        period_seconds: Average period between snapshots (used to annualize).
        risk_free_rate: Annualized risk-free rate (decimal form).
    """
    values = [
        float(v)
        for v in equity_values
        if isinstance(v, (int, float, np.floating)) and np.isfinite(v)
    ]
    if len(values) < 2:
        return None

    returns = np.diff(values) / np.array(values[:-1], dtype=float)
    returns = returns[np.isfinite(returns)]
    if returns.size == 0:
        return None

    # Require a valid positive period; callers (bot/backtest) already pass
    # meaningful intervals, so this primarily guards against bad inputs.
    if not period_seconds or period_seconds <= 0:
        return None
    period_seconds = float(period_seconds)

    periods_per_year = (365 * 24 * 60 * 60) / period_seconds
    if not np.isfinite(periods_per_year) or periods_per_year <= 0:
        return None

    per_period_rf = risk_free_rate / periods_per_year
    excess_return = returns.mean() - per_period_rf
    if not np.isfinite(excess_return):
        return None

    downside_diff = np.minimum(returns - per_period_rf, 0.0)
    downside_squared = downside_diff ** 2
    downside_deviation = np.sqrt(np.mean(downside_squared))
    if downside_deviation <= 0 or not np.isfinite(downside_deviation):
        return None

    sortino = (excess_return / downside_deviation) * np.sqrt(periods_per_year)
    if not np.isfinite(sortino):
        return None
    return float(sortino)
