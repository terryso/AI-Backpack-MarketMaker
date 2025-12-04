"""
Runtime configuration overrides layer.

This module provides a centralized container for runtime configuration overrides
that take precedence over environment variables. Overrides are stored in-memory
and do not persist to .env files.

Supported keys (whitelist):
- TRADING_BACKEND: Trading execution backend (paper, hyperliquid, binance_futures, backpack_futures)
- MARKET_DATA_BACKEND: Market data source (binance, backpack)
- TRADEBOT_INTERVAL: Trading loop interval (1m, 5m, 15m, 30m, 1h, etc.)
- TRADEBOT_LLM_TEMPERATURE: LLM sampling temperature (0.0 - 2.0)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# ───────────────────────── WHITELIST KEYS ─────────────────────────
# Only these keys can be overridden at runtime via Telegram /config commands
OVERRIDE_WHITELIST: Set[str] = frozenset({
    "TRADING_BACKEND",
    "MARKET_DATA_BACKEND",
    "TRADEBOT_INTERVAL",
    "TRADEBOT_LLM_TEMPERATURE",
    "TRADEBOT_LOOP_ENABLED",
    "DEFAULT_TP_PCT",
    "DEFAULT_SL_PCT",
})

# Valid values for enum-like keys
VALID_TRADING_BACKENDS: Set[str] = frozenset({
    "paper", "hyperliquid", "binance_futures", "backpack_futures"
})
VALID_MARKET_DATA_BACKENDS: Set[str] = frozenset({
    "binance", "backpack"
})
VALID_INTERVALS: Set[str] = frozenset({
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"
})

# Temperature range
LLM_TEMPERATURE_MIN = 0.0
LLM_TEMPERATURE_MAX = 2.0


class RuntimeOverrides:
    """
    Centralized container for runtime configuration overrides.
    
    This class manages in-memory overrides that take precedence over
    environment variables. It is designed to be used as a singleton
    instance within the config module.
    
    Thread Safety Note:
        This implementation uses a simple dict and is NOT thread-safe.
        For multi-threaded usage, consider adding locking mechanisms.
    """
    
    def __init__(self) -> None:
        """Initialize an empty overrides container."""
        self._overrides: Dict[str, Any] = {}
    
    def set_override(self, key: str, value: Any) -> bool:
        """
        Set a runtime override for the given key.
        
        Args:
            key: Configuration key (must be in OVERRIDE_WHITELIST)
            value: New value to set
            
        Returns:
            True if the override was set successfully, False otherwise
            
        Note:
            This method validates the key against the whitelist but does NOT
            validate the value. Value validation should be done by the caller
            or by the configuration loading functions.
        """
        if key not in OVERRIDE_WHITELIST:
            logger.warning(
                "Attempted to set override for non-whitelisted key '%s'; ignoring.",
                key
            )
            return False
        
        old_value = self._overrides.get(key)
        self._overrides[key] = value
        logger.info(
            "Runtime override set: %s = %r (was: %r)",
            key, value, old_value
        )
        return True
    
    def get_override(self, key: str) -> Optional[Any]:
        """
        Get the current override value for a key.
        
        Args:
            key: Configuration key to look up
            
        Returns:
            The override value if set, None otherwise
        """
        return self._overrides.get(key)
    
    def has_override(self, key: str) -> bool:
        """
        Check if an override exists for the given key.
        
        Args:
            key: Configuration key to check
            
        Returns:
            True if an override is set, False otherwise
        """
        return key in self._overrides
    
    def clear_override(self, key: str) -> bool:
        """
        Remove an override for the given key.
        
        Args:
            key: Configuration key to clear
            
        Returns:
            True if an override was removed, False if none existed
        """
        if key in self._overrides:
            old_value = self._overrides.pop(key)
            logger.info(
                "Runtime override cleared: %s (was: %r)",
                key, old_value
            )
            return True
        return False
    
    def clear_all(self) -> int:
        """
        Remove all overrides.
        
        Returns:
            Number of overrides that were cleared
        """
        count = len(self._overrides)
        if count > 0:
            logger.info("Clearing all %d runtime overrides", count)
            self._overrides.clear()
        return count
    
    def get_all_overrides(self) -> Dict[str, Any]:
        """
        Get a copy of all current overrides.
        
        Returns:
            Dictionary of all current override key-value pairs
        """
        return dict(self._overrides)
    
    def __len__(self) -> int:
        """Return the number of active overrides."""
        return len(self._overrides)
    
    def __repr__(self) -> str:
        """Return a string representation of the overrides."""
        return f"RuntimeOverrides({self._overrides})"


# ───────────────────────── SINGLETON INSTANCE ─────────────────────────
# Global singleton instance for use throughout the application
_runtime_overrides: RuntimeOverrides = RuntimeOverrides()


def get_runtime_overrides() -> RuntimeOverrides:
    """
    Get the global RuntimeOverrides singleton instance.
    
    Returns:
        The global RuntimeOverrides instance
    """
    return _runtime_overrides


def reset_runtime_overrides() -> None:
    """
    Reset the global RuntimeOverrides instance.
    
    This is primarily intended for testing purposes to ensure
    a clean state between tests.
    """
    global _runtime_overrides
    _runtime_overrides = RuntimeOverrides()


# ───────────────────────── VALIDATION HELPERS ─────────────────────────
def validate_override_value(key: str, value: Any) -> tuple[bool, Optional[str]]:
    """
    Validate a value for a given override key.
    
    Args:
        key: Configuration key
        value: Value to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if the value is valid
        - error_message: Description of the validation error, or None if valid
    """
    if key not in OVERRIDE_WHITELIST:
        return False, f"Key '{key}' is not in the override whitelist"
    
    if key == "TRADING_BACKEND":
        str_value = str(value).strip().lower()
        if str_value not in VALID_TRADING_BACKENDS:
            return False, (
                f"Invalid TRADING_BACKEND '{value}'; "
                f"must be one of: {', '.join(sorted(VALID_TRADING_BACKENDS))}"
            )
        return True, None
    
    if key == "MARKET_DATA_BACKEND":
        str_value = str(value).strip().lower()
        if str_value not in VALID_MARKET_DATA_BACKENDS:
            return False, (
                f"Invalid MARKET_DATA_BACKEND '{value}'; "
                f"must be one of: {', '.join(sorted(VALID_MARKET_DATA_BACKENDS))}"
            )
        return True, None
    
    if key == "TRADEBOT_INTERVAL":
        str_value = str(value).strip().lower()
        if str_value not in VALID_INTERVALS:
            return False, (
                f"Invalid TRADEBOT_INTERVAL '{value}'; "
                f"must be one of: {', '.join(sorted(VALID_INTERVALS, key=_interval_sort_key))}"
            )
        return True, None
    
    if key == "TRADEBOT_LLM_TEMPERATURE":
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return False, f"Invalid TRADEBOT_LLM_TEMPERATURE '{value}'; must be a number"
        
        if float_value < LLM_TEMPERATURE_MIN or float_value > LLM_TEMPERATURE_MAX:
            return False, (
                f"TRADEBOT_LLM_TEMPERATURE {float_value} out of range "
                f"[{LLM_TEMPERATURE_MIN}, {LLM_TEMPERATURE_MAX}]"
            )
        return True, None
    
    if key == "DEFAULT_TP_PCT":
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return False, f"Invalid DEFAULT_TP_PCT '{value}'; must be a number"
        if float_value < 0.0 or float_value > 100.0:
            return False, "DEFAULT_TP_PCT out of range [0, 100]"
        return True, None
    
    if key == "DEFAULT_SL_PCT":
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            return False, f"Invalid DEFAULT_SL_PCT '{value}'; must be a number"
        if float_value < 0.0 or float_value > 100.0:
            return False, "DEFAULT_SL_PCT out of range [0, 100]"
        return True, None
    
    if key == "LIVE_TRADING_ENABLED":
        # Accept common boolean-like representations
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True, None
        if normalized in {"0", "false", "no", "off"}:
            return True, None
        return False, f"Invalid LIVE_TRADING_ENABLED '{value}'; must be a boolean (true/false)"
    
    # Default: accept any value for unknown keys (shouldn't reach here due to whitelist check)
    return True, None


def _interval_sort_key(interval: str) -> int:
    """Sort key for intervals to order them by duration."""
    _INTERVAL_TO_SECONDS = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
        "12h": 43200, "1d": 86400,
    }
    return _INTERVAL_TO_SECONDS.get(interval, 0)


# ───────────────────────── PUBLIC API ─────────────────────────
def set_runtime_override(key: str, value: Any, validate: bool = True) -> tuple[bool, Optional[str]]:
    """
    Set a runtime override with optional validation.
    
    This is the primary API for external modules (e.g., Telegram commands)
    to modify runtime configuration.
    
    Args:
        key: Configuration key (must be in OVERRIDE_WHITELIST)
        value: New value to set
        validate: Whether to validate the value before setting (default: True)
        
    Returns:
        Tuple of (success, error_message)
        - success: True if the override was set successfully
        - error_message: Description of the error, or None if successful
    """
    if validate:
        is_valid, error_msg = validate_override_value(key, value)
        if not is_valid:
            logger.warning("Validation failed for %s=%r: %s", key, value, error_msg)
            return False, error_msg
    
    success = _runtime_overrides.set_override(key, value)
    if not success:
        return False, f"Key '{key}' is not in the override whitelist"
    return True, None


def get_runtime_override(key: str) -> Optional[Any]:
    """
    Get the current runtime override value for a key.
    
    Args:
        key: Configuration key to look up
        
    Returns:
        The override value if set, None otherwise
    """
    return _runtime_overrides.get_override(key)


def clear_runtime_override(key: str) -> bool:
    """
    Clear a runtime override for the given key.
    
    Args:
        key: Configuration key to clear
        
    Returns:
        True if an override was removed, False if none existed
    """
    return _runtime_overrides.clear_override(key)


def get_all_runtime_overrides() -> Dict[str, Any]:
    """
    Get a copy of all current runtime overrides.
    
    Returns:
        Dictionary of all current override key-value pairs
    """
    return _runtime_overrides.get_all_overrides()


def get_override_whitelist() -> Set[str]:
    """
    Get the set of keys that can be overridden at runtime.
    
    Returns:
        Frozen set of whitelisted configuration keys
    """
    return OVERRIDE_WHITELIST
