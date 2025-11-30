"""
State persistence utilities.

This module handles all file I/O operations for state persistence,
including CSV and JSON file operations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

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
    tmp_path = state_json.with_suffix(".tmp")

    try:
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2)

        tmp_path.replace(state_json)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logging.error(
            "Failed to save state to %s atomically: %s",
            state_json,
            exc,
            exc_info=True,
        )

        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:  # pragma: no cover - defensive logging only
            logging.error(
                "Failed to clean up temporary state file %s after error",
                tmp_path,
                exc_info=True,
            )


def load_state_from_json(
    state_json: Path,
    start_capital: float,
    taker_fee_rate: float,
) -> Tuple[float, Dict[str, Dict[str, Any]], int]:
    """Load persisted balance, positions, and iteration counter from JSON.

    Mirrors the normalisation logic of bot.load_state but operates purely on
    explicit arguments and returns derived values instead of mutating globals.
    """
    with open(state_json, "r") as f:
        data = json.load(f)

    balance = float(data.get("balance", start_capital))
    try:
        iteration_counter = int(data.get("iteration", 0))
    except (TypeError, ValueError):
        iteration_counter = 0

    loaded_positions = data.get("positions", {})
    restored_positions: Dict[str, Dict[str, Any]] = {}
    if isinstance(loaded_positions, dict):
        for coin, pos in loaded_positions.items():
            if not isinstance(pos, dict):
                continue

            fees_paid_raw = pos.get("fees_paid", pos.get("entry_fee", 0.0))
            if fees_paid_raw is None:
                fees_paid_value = 0.0
            else:
                try:
                    fees_paid_value = float(fees_paid_raw)
                except (TypeError, ValueError):
                    fees_paid_value = 0.0

            fee_rate_raw = pos.get("fee_rate", taker_fee_rate)
            try:
                fee_rate_value = float(fee_rate_raw)
            except (TypeError, ValueError):
                fee_rate_value = taker_fee_rate

            restored_positions[coin] = {
                "side": pos.get("side", "long"),
                "quantity": float(pos.get("quantity", 0.0)),
                "entry_price": float(pos.get("entry_price", 0.0)),
                "profit_target": float(pos.get("profit_target", 0.0)),
                "stop_loss": float(pos.get("stop_loss", 0.0)),
                "leverage": float(pos.get("leverage", 1)),
                "confidence": float(pos.get("confidence", 0.0)),
                "invalidation_condition": pos.get("invalidation_condition", ""),
                "margin": float(pos.get("margin", 0.0)),
                "fees_paid": fees_paid_value,
                "fee_rate": fee_rate_value,
                "liquidity": pos.get("liquidity", "taker"),
                "entry_justification": pos.get("entry_justification", ""),
                "last_justification": pos.get(
                    "last_justification",
                    pos.get("entry_justification", ""),
                ),
                "live_backend": pos.get("live_backend"),
                "entry_oid": pos.get("entry_oid", -1),
                "tp_oid": pos.get("tp_oid", -1),
                "sl_oid": pos.get("sl_oid", -1),
                "close_oid": pos.get("close_oid", -1),
            }

    return balance, restored_positions, iteration_counter


def append_portfolio_state_row(
    state_csv: Path,
    timestamp_iso: str,
    total_balance: str,
    total_equity: str,
    total_return_pct: str,
    num_positions: int,
    position_details: str,
    total_margin: str,
    net_unrealized_pnl: str,
    btc_price: str,
) -> None:
    """Append a single portfolio state row to the CSV.

    This mirrors the row layout defined by STATE_COLUMNS in bot.py so callers
    stay responsible for computing values while state_io owns the file I/O.
    """
    try:
        with open(state_csv, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    timestamp_iso,
                    total_balance,
                    total_equity,
                    total_return_pct,
                    num_positions,
                    position_details,
                    total_margin,
                    net_unrealized_pnl,
                    btc_price,
                ]
            )
    except Exception as exc:  # pragma: no cover - defensive logging only
        logging.error("Failed to append portfolio state row to %s: %s", state_csv, exc, exc_info=True)


def append_trade_row(
    trades_csv: Path,
    timestamp_iso: str,
    coin: str,
    action: str,
    side: str,
    quantity: Any,
    price: Any,
    profit_target: Any,
    stop_loss: Any,
    leverage: Any,
    confidence: Any,
    pnl: Any,
    balance_after: Any,
    reason: str,
) -> None:
    """Append a trade execution row to the trade history CSV."""
    try:
        with open(trades_csv, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    timestamp_iso,
                    coin,
                    action,
                    side,
                    quantity,
                    price,
                    profit_target,
                    stop_loss,
                    leverage,
                    confidence,
                    pnl,
                    balance_after,
                    reason,
                ]
            )
    except Exception as exc:  # pragma: no cover - defensive logging only
        logging.error("Failed to append trade row to %s: %s", trades_csv, exc, exc_info=True)
