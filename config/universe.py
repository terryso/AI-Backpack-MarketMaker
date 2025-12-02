"""Configurable Symbol Universe Abstraction.

This module provides a centralized abstraction for managing the set of
tradable symbols (the "Universe") in Paper/Live modes.

Design Constraints (Story 9.1):
------------------------------
1. **Subset-only filtering**: The Universe override can only select a subset
   of symbols defined in `config.settings.SYMBOL_TO_COIN`. Unknown symbols
   are silently ignored with a WARNING log. To add truly new symbols, they
   must first be added to `SYMBOL_TO_COIN` in settings.py.

5. **Empty Universe behavior**: If the override results in an empty list
   (all symbols invalid or explicitly empty), the Universe becomes empty and
   NO new trades will be initiated. This is intentional for safety - an empty
   or all-invalid configuration should NOT silently fall back to the full
   default Universe.

2. **In-memory only**: The override is stored in a module-level variable and
   is NOT persisted. Restarting the bot will reset the Universe to the
   default `config.settings.SYMBOLS`. Persistence may be added in Story 9.2/9.3.

3. **Thread-safety**: Simple pointer assignment is used. For CPython this is
   atomic, but no explicit locking is provided. If concurrent writes are
   needed (e.g., from Telegram command threads), callers should serialize
   access or a lock should be added here.

4. **Position safety**: Shrinking the Universe does NOT automatically close
   existing positions. Positions outside the current Universe will still be
   managed by SL/TP logic, but LLM decisions for those coins will be skipped.
   Callers should check for orphaned positions when modifying the Universe.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .settings import SYMBOLS, SYMBOL_TO_COIN, get_effective_market_data_backend

SymbolUniverse = List[str]

# Module-level override; None means use default SYMBOLS from settings.
# NOTE: This is in-memory only and will be lost on process restart.
_UNIVERSE_OVERRIDE: Optional[SymbolUniverse] = None


def _normalize_symbols(symbols: List[str]) -> SymbolUniverse:
    normalized: SymbolUniverse = []
    seen = set()
    for raw in symbols:
        if not raw:
            continue
        sym = str(raw).strip().upper()
        if not sym:
            continue
        if sym not in SYMBOL_TO_COIN:
            logging.warning("Ignoring unknown symbol in universe override: %s", sym)
            continue
        if sym in seen:
            continue
        seen.add(sym)
        normalized.append(sym)
    return normalized


def set_symbol_universe(symbols: List[str]) -> None:
    """Set a runtime Universe override.
    
    Args:
        symbols: List of symbol strings to use as the new Universe.
            Unknown symbols are filtered out with a WARNING log.
    
    Note:
        If the resulting list is empty (all symbols invalid or empty input),
        the Universe becomes empty and NO new trades will be initiated.
        This is safer than silently falling back to the full default Universe.
        Use `clear_symbol_universe_override()` to explicitly restore defaults.
    """
    global _UNIVERSE_OVERRIDE
    override = _normalize_symbols(symbols)
    # Keep empty list as valid override (means "trade nothing")
    # Only None means "use default SYMBOLS"
    _UNIVERSE_OVERRIDE = override


def clear_symbol_universe_override() -> None:
    global _UNIVERSE_OVERRIDE
    _UNIVERSE_OVERRIDE = None


def get_effective_symbol_universe() -> SymbolUniverse:
    if _UNIVERSE_OVERRIDE is not None:
        return list(_UNIVERSE_OVERRIDE)
    return list(SYMBOLS)


def get_effective_coin_universe() -> List[str]:
    symbols = get_effective_symbol_universe()
    coins: List[str] = []
    seen = set()
    for symbol in symbols:
        coin = SYMBOL_TO_COIN.get(symbol)
        if not coin or coin in seen:
            continue
        seen.add(coin)
        coins.append(coin)
    return coins


def validate_symbol_for_universe(symbol: str) -> Tuple[bool, str]:
    """Validate if a symbol is valid for the current MARKET_DATA_BACKEND.

    This function centralizes symbol validation logic used by higher-level
    components such as Telegram /symbols commands (Story 9.2) and will be
    extended by Story 9.3 to perform backend\-aware checks.

    Current behavior (minimal, Story 9.2):
    \- Treats SYMBOL_TO_COIN as the source of truth for known symbols.
    \- Returns False for any symbol not present in SYMBOL_TO_COIN, with an
      error message that includes the active MARKET_DATA_BACKEND.

    Args:
        symbol: Normalized symbol to validate (e.g., "BTCUSDT").

    Returns:
        Tuple of (is_valid, error_message).
        is_valid is True if the symbol is valid.
        error_message contains the reason if invalid.
    """
    normalized = str(symbol).strip().upper()
    if not normalized:
        backend = get_effective_market_data_backend()
        return False, f"Symbol '{symbol}' 为空或无效 (backend: {backend})"

    if normalized not in SYMBOL_TO_COIN:
        backend = get_effective_market_data_backend()
        return False, f"Symbol '{normalized}' 不在已知交易对列表中 (backend: {backend})"

    return True, ""

