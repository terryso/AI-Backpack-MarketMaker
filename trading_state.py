"""
Trading state management.

This module manages the global trading state including balance, positions,
equity history, and time providers.
"""
from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from trading_config import (
    START_CAPITAL,
    STATE_JSON,
    STATE_CSV,
    TAKER_FEE_RATE,
)
from state_io import (
    load_equity_history_from_csv as _load_equity_history_from_csv,
    save_state_to_json as _save_state_to_json,
    load_state_from_json as _load_state_from_json,
)

# ──────────────────────── GLOBAL STATE ─────────────────────
balance: float = START_CAPITAL
positions: Dict[str, Dict[str, Any]] = {}  # coin -> position info
trade_history: List[Dict[str, Any]] = []
invocation_count: int = 0
iteration_counter: int = 0
equity_history: List[float] = []
current_iteration_messages: List[str] = []
last_btc_price: Optional[float] = None

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


# ──────────────────────── TIME PROVIDER ─────────────────────
def _default_time_provider() -> datetime:
    """Return current UTC time; overridable for testing/backtests."""
    return datetime.now(timezone.utc)


_current_time_provider: Callable[[], datetime] = _default_time_provider


def get_current_time() -> datetime:
    """Return the current time from the active provider."""
    return _current_time_provider()


def set_time_provider(provider: Optional[Callable[[], datetime]]) -> None:
    """Override the time provider; pass None to restore wall-clock time."""
    global _current_time_provider
    _current_time_provider = provider or _default_time_provider


BOT_START_TIME = get_current_time()


# ──────────────────────── STATE MANAGEMENT ─────────────────────
def load_state() -> None:
    """Load persisted balance and positions if available."""
    global balance, positions, iteration_counter

    if not STATE_JSON.exists():
        logging.info("No existing state file found; starting fresh.")
        return

    try:
        new_balance, new_positions, new_iteration = _load_state_from_json(
            STATE_JSON,
            START_CAPITAL,
            TAKER_FEE_RATE,
        )
        balance = new_balance
        positions = new_positions
        iteration_counter = new_iteration
        logging.info(
            "Loaded state from %s (balance: %.2f, positions: %d)",
            STATE_JSON,
            balance,
            len(positions),
        )
    except Exception as e:
        logging.error("Failed to load state from %s: %s", STATE_JSON, e, exc_info=True)
        balance = START_CAPITAL
        positions = {}


def save_state() -> None:
    """Persist current balance, open positions, and iteration counter."""
    payload = {
        "balance": balance,
        "positions": positions,
        "iteration": iteration_counter,
        "updated_at": get_current_time().isoformat(),
    }
    _save_state_to_json(STATE_JSON, payload)


def reset_state(initial_balance: Optional[float] = None) -> None:
    """Reset in-memory trading state to start a fresh run."""
    global balance, positions, trade_history, iteration_counter
    global equity_history, invocation_count, current_iteration_messages, BOT_START_TIME
    balance = float(initial_balance) if initial_balance is not None else START_CAPITAL
    positions = {}
    trade_history = []
    iteration_counter = 0
    invocation_count = 0
    equity_history.clear()
    current_iteration_messages = []
    BOT_START_TIME = get_current_time()


def load_equity_history() -> None:
    """Populate the in-memory equity history for performance calculations."""
    _load_equity_history_from_csv(STATE_CSV, equity_history)


def register_equity_snapshot(total_equity: float) -> None:
    """Append the latest equity to the history if it is a finite value."""
    if total_equity is None:
        return
    if isinstance(total_equity, (int, float, np.floating)) and np.isfinite(total_equity):
        equity_history.append(float(total_equity))


def update_balance(delta: float) -> None:
    """Update the global balance by the given delta."""
    global balance
    balance += delta


def set_balance(new_balance: float) -> None:
    """Set the global balance to a specific value."""
    global balance
    balance = new_balance


def get_balance() -> float:
    """Return the current balance."""
    return balance


def get_positions() -> Dict[str, Dict[str, Any]]:
    """Return the current positions dictionary."""
    return positions


def set_position(coin: str, position_data: Dict[str, Any]) -> None:
    """Set or update a position for a coin."""
    positions[coin] = position_data


def remove_position(coin: str) -> None:
    """Remove a position for a coin."""
    if coin in positions:
        del positions[coin]


def increment_invocation_count() -> int:
    """Increment and return the invocation count."""
    global invocation_count
    invocation_count += 1
    return invocation_count


def get_invocation_count() -> int:
    """Return the current invocation count."""
    return invocation_count


def increment_iteration_counter() -> int:
    """Increment and return the iteration counter."""
    global iteration_counter
    iteration_counter += 1
    return iteration_counter


def get_iteration_counter() -> int:
    """Return the current iteration counter."""
    return iteration_counter


def clear_iteration_messages() -> None:
    """Clear the current iteration messages."""
    global current_iteration_messages
    current_iteration_messages = []


def get_iteration_messages() -> List[str]:
    """Return the current iteration messages."""
    return current_iteration_messages


def get_equity_history() -> List[float]:
    """Return the equity history list."""
    return equity_history


def get_bot_start_time() -> datetime:
    """Return the bot start time."""
    return BOT_START_TIME


def set_last_btc_price(price: Optional[float]) -> None:
    """Set the last BTC price."""
    global last_btc_price
    last_btc_price = price


def get_last_btc_price() -> Optional[float]:
    """Return the last BTC price."""
    return last_btc_price


# ──────────────────────── UTILITY FUNCTIONS ─────────────────────
def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes so Telegram receives plain text."""
    return ANSI_ESCAPE_RE.sub("", text)


def escape_markdown(text: str) -> str:
    """Escape characters that have special meaning in Telegram Markdown."""
    if not text:
        return text
    specials = r"_*[]()~`>#+-=|{}.!\\"
    return "".join(f"\\{char}" if char in specials else char for char in text)
