from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

import csv
import json
import logging
import numpy as np
import pandas as pd


def load_equity_history_from_csv(state_csv: Path, equity_history: List[float]) -> None:
    """Populate the in-memory equity history list from a CSV file.

    This helper mirrors the behaviour of bot.load_equity_history but operates on
    an explicit CSV path and history list, so callers remain in control of
    global state.
    """
    equity_history.clear()
    if not state_csv.exists():
        return
    try:
        df = pd.read_csv(state_csv, usecols=["total_equity"])
    except ValueError:
        logging.warning(
            "%s missing 'total_equity' column; Sortino ratio unavailable until new data is logged.",
            state_csv,
        )
        return
    except Exception as exc:  # pragma: no cover - defensive logging only
        logging.warning("Unable to load historical equity data: %s", exc)
        return

    values = pd.to_numeric(df["total_equity"], errors="coerce").dropna()
    if not values.empty:
        equity_history.extend(float(v) for v in values.tolist())


def init_csv_files_for_paths(
    state_csv: Path,
    trades_csv: Path,
    decisions_csv: Path,
    messages_csv: Path,
    messages_recent_csv: Path,
    state_columns: Iterable[str],
) -> None:
    """Create CSV files with appropriate headers if they do not yet exist.

    This is a parameterised version of bot.init_csv_files that operates solely
    on paths and column definitions so it can be reused from different entry
    points (live bot, backtests, tools).
    """
    state_columns = list(state_columns)

    # Ensure portfolio_state has the expected schema.
    if not state_csv.exists():
        with open(state_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(state_columns)
    else:
        try:
            df = pd.read_csv(state_csv)
        except Exception as exc:  # pragma: no cover - defensive logging only
            logging.warning("Unable to load %s for schema check: %s", state_csv, exc)
        else:
            if list(df.columns) != state_columns:
                for column in state_columns:
                    if column not in df.columns:
                        df[column] = np.nan
                try:
                    df = df[state_columns]
                except KeyError:
                    # Fall back to writing header only if severe mismatch
                    df = pd.DataFrame(columns=state_columns)
                df.to_csv(state_csv, index=False)

    if not trades_csv.exists():
        with open(trades_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "coin",
                    "action",
                    "side",
                    "quantity",
                    "price",
                    "profit_target",
                    "stop_loss",
                    "leverage",
                    "confidence",
                    "pnl",
                    "balance_after",
                    "reason",
                ]
            )

    if not decisions_csv.exists():
        with open(decisions_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "coin",
                "signal",
                "reasoning",
                "confidence",
            ])

    if not messages_csv.exists():
        with open(messages_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "direction",
                "role",
                "content",
                "metadata",
            ])


def save_state_to_json(state_json: Path, payload: Dict[str, Any]) -> None:
    """Persist the given payload to the specified JSON file.

    This mirrors the file-writing and logging behaviour of bot.save_state while
    keeping the caller responsible for constructing the payload.
    """
    try:
        with open(state_json, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logging.error("Failed to save state to %s: %s", state_json, exc, exc_info=True)
