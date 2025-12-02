"""
Tests for runtime configuration overrides layer.

This module tests the RuntimeOverrides container and the effective config getters
that implement the priority: runtime override > env > default.
"""
import os
import unittest
from unittest import mock

from config.runtime_overrides import (
    RuntimeOverrides,
    get_runtime_overrides,
    reset_runtime_overrides,
    set_runtime_override,
    get_runtime_override,
    clear_runtime_override,
    get_all_runtime_overrides,
    get_override_whitelist,
    validate_override_value,
    OVERRIDE_WHITELIST,
    VALID_TRADING_BACKENDS,
    VALID_MARKET_DATA_BACKENDS,
    VALID_INTERVALS,
    LLM_TEMPERATURE_MIN,
    LLM_TEMPERATURE_MAX,
)
from config.settings import (
    get_effective_trading_backend,
    get_effective_market_data_backend,
    get_effective_interval,
    get_effective_check_interval,
    get_effective_llm_temperature,
    EARLY_ENV_WARNINGS,
)


class RuntimeOverridesContainerTests(unittest.TestCase):
    """Tests for the RuntimeOverrides container class."""

    def setUp(self) -> None:
        """Reset overrides before each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def tearDown(self) -> None:
        """Clean up after each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def test_initial_state_is_empty(self) -> None:
        """New RuntimeOverrides instance should have no overrides."""
        overrides = RuntimeOverrides()
        self.assertEqual(len(overrides), 0)
        self.assertEqual(overrides.get_all_overrides(), {})

    def test_set_override_for_whitelisted_key(self) -> None:
        """Setting override for whitelisted key should succeed."""
        overrides = get_runtime_overrides()
        
        result = overrides.set_override("TRADING_BACKEND", "hyperliquid")
        
        self.assertTrue(result)
        self.assertEqual(overrides.get_override("TRADING_BACKEND"), "hyperliquid")
        self.assertTrue(overrides.has_override("TRADING_BACKEND"))

    def test_set_override_for_non_whitelisted_key_fails(self) -> None:
        """Setting override for non-whitelisted key should fail."""
        overrides = get_runtime_overrides()
        
        result = overrides.set_override("UNKNOWN_KEY", "value")
        
        self.assertFalse(result)
        self.assertIsNone(overrides.get_override("UNKNOWN_KEY"))
        self.assertFalse(overrides.has_override("UNKNOWN_KEY"))

    def test_get_override_returns_none_for_unset_key(self) -> None:
        """Getting unset override should return None."""
        overrides = get_runtime_overrides()
        
        self.assertIsNone(overrides.get_override("TRADING_BACKEND"))

    def test_clear_override_removes_existing(self) -> None:
        """Clearing an existing override should remove it."""
        overrides = get_runtime_overrides()
        overrides.set_override("TRADING_BACKEND", "hyperliquid")
        
        result = overrides.clear_override("TRADING_BACKEND")
        
        self.assertTrue(result)
        self.assertIsNone(overrides.get_override("TRADING_BACKEND"))

    def test_clear_override_returns_false_for_nonexistent(self) -> None:
        """Clearing a non-existent override should return False."""
        overrides = get_runtime_overrides()
        
        result = overrides.clear_override("TRADING_BACKEND")
        
        self.assertFalse(result)

    def test_clear_all_removes_all_overrides(self) -> None:
        """clear_all should remove all overrides."""
        overrides = get_runtime_overrides()
        overrides.set_override("TRADING_BACKEND", "hyperliquid")
        overrides.set_override("MARKET_DATA_BACKEND", "backpack")
        
        count = overrides.clear_all()
        
        self.assertEqual(count, 2)
        self.assertEqual(len(overrides), 0)

    def test_get_all_overrides_returns_copy(self) -> None:
        """get_all_overrides should return a copy, not the internal dict."""
        overrides = get_runtime_overrides()
        overrides.set_override("TRADING_BACKEND", "hyperliquid")
        
        all_overrides = overrides.get_all_overrides()
        all_overrides["TRADING_BACKEND"] = "modified"
        
        # Original should be unchanged
        self.assertEqual(overrides.get_override("TRADING_BACKEND"), "hyperliquid")


class ValidationHelperTests(unittest.TestCase):
    """Tests for the validate_override_value function."""

    def test_validate_trading_backend_valid_values(self) -> None:
        """Valid TRADING_BACKEND values should pass validation."""
        for backend in VALID_TRADING_BACKENDS:
            is_valid, error = validate_override_value("TRADING_BACKEND", backend)
            self.assertTrue(is_valid, f"Expected {backend} to be valid")
            self.assertIsNone(error)

    def test_validate_trading_backend_invalid_value(self) -> None:
        """Invalid TRADING_BACKEND value should fail validation."""
        is_valid, error = validate_override_value("TRADING_BACKEND", "invalid_backend")
        
        self.assertFalse(is_valid)
        self.assertIn("Invalid TRADING_BACKEND", error)

    def test_validate_market_data_backend_valid_values(self) -> None:
        """Valid MARKET_DATA_BACKEND values should pass validation."""
        for backend in VALID_MARKET_DATA_BACKENDS:
            is_valid, error = validate_override_value("MARKET_DATA_BACKEND", backend)
            self.assertTrue(is_valid, f"Expected {backend} to be valid")
            self.assertIsNone(error)

    def test_validate_market_data_backend_invalid_value(self) -> None:
        """Invalid MARKET_DATA_BACKEND value should fail validation."""
        is_valid, error = validate_override_value("MARKET_DATA_BACKEND", "invalid")
        
        self.assertFalse(is_valid)
        self.assertIn("Invalid MARKET_DATA_BACKEND", error)

    def test_validate_interval_valid_values(self) -> None:
        """Valid TRADEBOT_INTERVAL values should pass validation."""
        for interval in VALID_INTERVALS:
            is_valid, error = validate_override_value("TRADEBOT_INTERVAL", interval)
            self.assertTrue(is_valid, f"Expected {interval} to be valid")
            self.assertIsNone(error)

    def test_validate_interval_invalid_value(self) -> None:
        """Invalid TRADEBOT_INTERVAL value should fail validation."""
        is_valid, error = validate_override_value("TRADEBOT_INTERVAL", "99h")
        
        self.assertFalse(is_valid)
        self.assertIn("Invalid TRADEBOT_INTERVAL", error)

    def test_validate_temperature_valid_values(self) -> None:
        """Valid TRADEBOT_LLM_TEMPERATURE values should pass validation."""
        valid_temps = [0.0, 0.5, 1.0, 1.5, 2.0]
        for temp in valid_temps:
            is_valid, error = validate_override_value("TRADEBOT_LLM_TEMPERATURE", temp)
            self.assertTrue(is_valid, f"Expected {temp} to be valid")
            self.assertIsNone(error)

    def test_validate_temperature_out_of_range(self) -> None:
        """Out-of-range TRADEBOT_LLM_TEMPERATURE should fail validation."""
        is_valid, error = validate_override_value("TRADEBOT_LLM_TEMPERATURE", 3.0)
        
        self.assertFalse(is_valid)
        self.assertIn("out of range", error)

    def test_validate_temperature_invalid_type(self) -> None:
        """Non-numeric TRADEBOT_LLM_TEMPERATURE should fail validation."""
        is_valid, error = validate_override_value("TRADEBOT_LLM_TEMPERATURE", "not_a_number")
        
        self.assertFalse(is_valid)
        self.assertIn("must be a number", error)

    def test_validate_non_whitelisted_key(self) -> None:
        """Non-whitelisted key should fail validation."""
        is_valid, error = validate_override_value("UNKNOWN_KEY", "value")
        
        self.assertFalse(is_valid)
        self.assertIn("not in the override whitelist", error)


class PublicAPITests(unittest.TestCase):
    """Tests for the public API functions."""

    def setUp(self) -> None:
        """Reset overrides before each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def tearDown(self) -> None:
        """Clean up after each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def test_set_runtime_override_with_validation(self) -> None:
        """set_runtime_override should validate by default."""
        success, error = set_runtime_override("TRADING_BACKEND", "invalid_backend")
        
        self.assertFalse(success)
        self.assertIn("Invalid TRADING_BACKEND", error)
        self.assertIsNone(get_runtime_override("TRADING_BACKEND"))

    def test_set_runtime_override_valid_value(self) -> None:
        """set_runtime_override should succeed with valid value."""
        success, error = set_runtime_override("TRADING_BACKEND", "hyperliquid")
        
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(get_runtime_override("TRADING_BACKEND"), "hyperliquid")

    def test_set_runtime_override_without_validation(self) -> None:
        """set_runtime_override with validate=False should skip validation."""
        success, error = set_runtime_override(
            "TRADING_BACKEND", "any_value", validate=False
        )
        
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(get_runtime_override("TRADING_BACKEND"), "any_value")

    def test_get_override_whitelist(self) -> None:
        """get_override_whitelist should return the expected keys."""
        whitelist = get_override_whitelist()
        
        self.assertEqual(whitelist, OVERRIDE_WHITELIST)
        self.assertIn("TRADING_BACKEND", whitelist)
        self.assertIn("MARKET_DATA_BACKEND", whitelist)
        self.assertIn("TRADEBOT_INTERVAL", whitelist)
        self.assertIn("TRADEBOT_LLM_TEMPERATURE", whitelist)
        self.assertIn("TRADEBOT_LOOP_ENABLED", whitelist)

    def test_get_all_runtime_overrides(self) -> None:
        """get_all_runtime_overrides should return all set overrides."""
        set_runtime_override("TRADING_BACKEND", "hyperliquid")
        set_runtime_override("TRADEBOT_INTERVAL", "1h")
        
        all_overrides = get_all_runtime_overrides()
        
        self.assertEqual(len(all_overrides), 2)
        self.assertEqual(all_overrides["TRADING_BACKEND"], "hyperliquid")
        self.assertEqual(all_overrides["TRADEBOT_INTERVAL"], "1h")

    def test_clear_runtime_override(self) -> None:
        """clear_runtime_override should remove the override."""
        set_runtime_override("TRADING_BACKEND", "hyperliquid")
        
        result = clear_runtime_override("TRADING_BACKEND")
        
        self.assertTrue(result)
        self.assertIsNone(get_runtime_override("TRADING_BACKEND"))


class EffectiveConfigGetterTests(unittest.TestCase):
    """Tests for the effective config getter functions."""

    def setUp(self) -> None:
        """Reset overrides before each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def tearDown(self) -> None:
        """Clean up after each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def test_get_effective_trading_backend_with_override(self) -> None:
        """Override should take precedence over env/default."""
        set_runtime_override("TRADING_BACKEND", "hyperliquid")
        
        result = get_effective_trading_backend()
        
        self.assertEqual(result, "hyperliquid")

    def test_get_effective_trading_backend_without_override(self) -> None:
        """Without override, should return env/default value."""
        # No override set, should return the module-level TRADING_BACKEND
        result = get_effective_trading_backend()
        
        # Result should be one of the valid backends
        self.assertIn(result, VALID_TRADING_BACKENDS)

    def test_get_effective_trading_backend_invalid_override_falls_back(self) -> None:
        """Invalid override should fall back to env/default."""
        # Set invalid override (bypassing validation)
        set_runtime_override("TRADING_BACKEND", "invalid", validate=False)
        
        result = get_effective_trading_backend()
        
        # Should fall back to env/default, not the invalid override
        self.assertIn(result, VALID_TRADING_BACKENDS)
        self.assertNotEqual(result, "invalid")

    def test_get_effective_market_data_backend_with_override(self) -> None:
        """Override should take precedence over env/default."""
        set_runtime_override("MARKET_DATA_BACKEND", "backpack")
        
        result = get_effective_market_data_backend()
        
        self.assertEqual(result, "backpack")

    def test_get_effective_market_data_backend_without_override(self) -> None:
        """Without override, should return env/default value."""
        result = get_effective_market_data_backend()
        
        self.assertIn(result, VALID_MARKET_DATA_BACKENDS)

    def test_get_effective_interval_with_override(self) -> None:
        """Override should take precedence over env/default."""
        set_runtime_override("TRADEBOT_INTERVAL", "1h")
        
        result = get_effective_interval()
        
        self.assertEqual(result, "1h")

    def test_get_effective_interval_without_override(self) -> None:
        """Without override, should return env/default value."""
        result = get_effective_interval()
        
        self.assertIn(result, VALID_INTERVALS)

    def test_get_effective_check_interval_with_override(self) -> None:
        """Check interval should be derived from effective interval."""
        set_runtime_override("TRADEBOT_INTERVAL", "1h")
        
        result = get_effective_check_interval()
        
        self.assertEqual(result, 3600)  # 1h = 3600 seconds

    def test_get_effective_llm_temperature_with_override(self) -> None:
        """Override should take precedence over env/default."""
        set_runtime_override("TRADEBOT_LLM_TEMPERATURE", 1.5)
        
        result = get_effective_llm_temperature()
        
        self.assertEqual(result, 1.5)

    def test_get_effective_llm_temperature_without_override(self) -> None:
        """Without override, should return env/default value."""
        result = get_effective_llm_temperature()
        
        # Should be within valid range
        self.assertGreaterEqual(result, LLM_TEMPERATURE_MIN)
        self.assertLessEqual(result, LLM_TEMPERATURE_MAX)

    def test_get_effective_llm_temperature_invalid_override_falls_back(self) -> None:
        """Invalid override should fall back to env/default."""
        # Set invalid override (bypassing validation)
        set_runtime_override("TRADEBOT_LLM_TEMPERATURE", "not_a_number", validate=False)
        
        result = get_effective_llm_temperature()
        
        # Should fall back to env/default
        self.assertGreaterEqual(result, LLM_TEMPERATURE_MIN)
        self.assertLessEqual(result, LLM_TEMPERATURE_MAX)

    def test_get_effective_llm_temperature_out_of_range_falls_back(self) -> None:
        """Out-of-range override should fall back to env/default."""
        # Set out-of-range override (bypassing validation)
        set_runtime_override("TRADEBOT_LLM_TEMPERATURE", 5.0, validate=False)
        
        result = get_effective_llm_temperature()
        
        # Should fall back to env/default
        self.assertGreaterEqual(result, LLM_TEMPERATURE_MIN)
        self.assertLessEqual(result, LLM_TEMPERATURE_MAX)


class WhitelistKeyTests(unittest.TestCase):
    """Tests for each whitelisted key's behavior."""

    def setUp(self) -> None:
        """Reset overrides before each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def tearDown(self) -> None:
        """Clean up after each test."""
        reset_runtime_overrides()
        EARLY_ENV_WARNINGS.clear()

    def test_trading_backend_all_valid_values(self) -> None:
        """All valid TRADING_BACKEND values should work."""
        for backend in ["paper", "hyperliquid", "binance_futures", "backpack_futures"]:
            reset_runtime_overrides()
            set_runtime_override("TRADING_BACKEND", backend)
            self.assertEqual(get_effective_trading_backend(), backend)

    def test_market_data_backend_all_valid_values(self) -> None:
        """All valid MARKET_DATA_BACKEND values should work."""
        for backend in ["binance", "backpack"]:
            reset_runtime_overrides()
            set_runtime_override("MARKET_DATA_BACKEND", backend)
            self.assertEqual(get_effective_market_data_backend(), backend)

    def test_interval_all_valid_values(self) -> None:
        """All valid TRADEBOT_INTERVAL values should work."""
        intervals = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]
        for interval in intervals:
            reset_runtime_overrides()
            set_runtime_override("TRADEBOT_INTERVAL", interval)
            self.assertEqual(get_effective_interval(), interval)

    def test_temperature_boundary_values(self) -> None:
        """Temperature boundary values should work."""
        # Minimum
        set_runtime_override("TRADEBOT_LLM_TEMPERATURE", 0.0)
        self.assertEqual(get_effective_llm_temperature(), 0.0)
        
        # Maximum
        reset_runtime_overrides()
        set_runtime_override("TRADEBOT_LLM_TEMPERATURE", 2.0)
        self.assertEqual(get_effective_llm_temperature(), 2.0)


class ResetAndSingletonTests(unittest.TestCase):
    """Tests for reset functionality and singleton behavior."""

    def setUp(self) -> None:
        """Reset overrides before each test."""
        reset_runtime_overrides()

    def tearDown(self) -> None:
        """Clean up after each test."""
        reset_runtime_overrides()

    def test_reset_clears_all_overrides(self) -> None:
        """reset_runtime_overrides should clear all overrides."""
        set_runtime_override("TRADING_BACKEND", "hyperliquid")
        set_runtime_override("TRADEBOT_INTERVAL", "1h")
        
        reset_runtime_overrides()
        
        self.assertIsNone(get_runtime_override("TRADING_BACKEND"))
        self.assertIsNone(get_runtime_override("TRADEBOT_INTERVAL"))
        self.assertEqual(get_all_runtime_overrides(), {})

    def test_get_runtime_overrides_returns_same_instance(self) -> None:
        """get_runtime_overrides should return the same singleton instance."""
        instance1 = get_runtime_overrides()
        instance2 = get_runtime_overrides()
        
        self.assertIs(instance1, instance2)

    def test_reset_creates_new_instance(self) -> None:
        """reset_runtime_overrides should create a new instance."""
        instance1 = get_runtime_overrides()
        reset_runtime_overrides()
        instance2 = get_runtime_overrides()
        
        self.assertIsNot(instance1, instance2)


if __name__ == "__main__":
    unittest.main()
