"""
Tests for Telegram /config command handlers.

This module tests the /config list, /config get, and /config set commands
implemented in Story 8.2, plus permission control and audit logging from Story 8.3.

Test coverage:
- Story 8.2 AC1: /config list returns 4 whitelisted config keys with current values
- Story 8.2 AC2: /config get <KEY> returns current value and valid range/enum
- Story 8.2 AC3: /config set <KEY> <VALUE> updates config and returns old/new values
- Story 8.3 AC1: Admin user ID configuration and loading
- Story 8.3 AC2: /config set permission control (admin-only)
- Story 8.3 AC3: Audit logging for successful /config set calls
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import patch, MagicMock

from notifications.telegram_commands import (
    TelegramCommand,
    CommandResult,
    handle_config_command,
    handle_config_list_command,
    handle_config_get_command,
    handle_config_set_command,
    CONFIG_KEY_DESCRIPTIONS,
    CONFIG_KEYS_FOR_TELEGRAM,
    _get_config_value_info,
    _check_admin_permission,
    _log_config_audit,
)
from config.runtime_overrides import (
    reset_runtime_overrides,
    get_runtime_override,
    get_override_whitelist,
    VALID_TRADING_BACKENDS,
    VALID_MARKET_DATA_BACKENDS,
    VALID_INTERVALS,
)


@pytest.fixture(autouse=True)
def reset_overrides():
    """Reset runtime overrides before and after each test."""
    reset_runtime_overrides()
    yield
    reset_runtime_overrides()


def _make_config_command(args: list[str], user_id: str = "123456789") -> TelegramCommand:
    """Create a TelegramCommand for /config with given args and user_id."""
    return TelegramCommand(
        command="config",
        args=args,
        chat_id="123456789",
        message_id=1,
        raw_text=f"/config {' '.join(args)}".strip(),
        raw_update={},
        user_id=user_id,
    )


class TestConfigListCommand:
    """Tests for /config list subcommand (AC1)."""

    def test_config_list_returns_all_whitelist_keys(self):
        """AC1: /config list should return all 4 whitelisted config keys."""
        cmd = _make_config_command(["list"])
        result = handle_config_list_command(cmd)

        assert result.success is True
        assert result.action == "CONFIG_LIST"
        assert result.state_changed is False

        # Check that all exposed keys are mentioned in the message
        for key in CONFIG_KEYS_FOR_TELEGRAM:
            assert key in result.message or key.replace("_", "\\_") in result.message

    def test_config_list_shows_current_values(self):
        """AC1: /config list should show current effective values."""
        cmd = _make_config_command(["list"])
        result = handle_config_list_command(cmd)

        # Should contain value indicators
        assert "可配置项列表" in result.message
        assert "使用" in result.message

    def test_config_list_via_main_handler(self):
        """Test /config list via the main handle_config_command."""
        cmd = _make_config_command(["list"])
        result = handle_config_command(cmd)

        assert result.success is True
        assert result.action == "CONFIG_LIST"


class TestConfigGetCommand:
    """Tests for /config get <KEY> subcommand (AC2)."""

    def test_config_get_valid_key_trading_backend(self):
        """AC2: /config get TRADING_BACKEND returns current value and valid options."""
        cmd = _make_config_command(["get", "TRADING_BACKEND"])
        result = handle_config_get_command(cmd, "TRADING_BACKEND")

        # 当前版本不再通过 /config 暴露 backend 相关配置，应视为无效 key
        assert result.success is False
        assert result.action == "CONFIG_GET_INVALID_KEY"

    def test_config_get_valid_key_market_data_backend(self):
        """AC2: /config get MARKET_DATA_BACKEND returns current value and valid options."""
        cmd = _make_config_command(["get", "MARKET_DATA_BACKEND"])
        result = handle_config_get_command(cmd, "MARKET_DATA_BACKEND")

        # 当前版本不再通过 /config 暴露 backend 相关配置，应视为无效 key
        assert result.success is False
        assert result.action == "CONFIG_GET_INVALID_KEY"

    def test_config_get_valid_key_interval(self):
        """AC2: /config get TRADEBOT_INTERVAL returns current value and valid options."""
        cmd = _make_config_command(["get", "TRADEBOT_INTERVAL"])
        result = handle_config_get_command(cmd, "TRADEBOT_INTERVAL")

        assert result.success is True
        assert result.action == "CONFIG_GET"
        # Should mention some valid intervals
        assert "可选值" in result.message or "15m" in result.message or "1h" in result.message

    def test_config_get_valid_key_temperature(self):
        """AC2: /config get TRADEBOT_LLM_TEMPERATURE returns current value and range."""
        cmd = _make_config_command(["get", "TRADEBOT_LLM_TEMPERATURE"])
        result = handle_config_get_command(cmd, "TRADEBOT_LLM_TEMPERATURE")

        assert result.success is True
        assert result.action == "CONFIG_GET"
        # Should mention range
        assert "范围" in result.message or "0" in result.message

    def test_config_get_invalid_key_returns_error(self):
        """AC2: /config get with invalid key returns error and lists supported keys."""
        cmd = _make_config_command(["get", "INVALID_KEY"])
        result = handle_config_get_command(cmd, "INVALID_KEY")

        assert result.success is False
        assert result.action == "CONFIG_GET_INVALID_KEY"
        assert "无效" in result.message or "Invalid" in result.message
        # Should list supported keys (interval & temperature)
        assert "TRADEBOT_INTERVAL" in result.message or "TRADEBOT\\_INTERVAL" in result.message

    def test_config_get_case_insensitive(self):
        """AC2: /config get should be case-insensitive for key names."""
        cmd = _make_config_command(["get", "tradebot_interval"])
        result = handle_config_get_command(cmd, "tradebot_interval")

        assert result.success is True
        assert result.action == "CONFIG_GET"

    def test_config_get_missing_key_via_main_handler(self):
        """Test /config get without key via main handler."""
        cmd = _make_config_command(["get"])
        result = handle_config_command(cmd)

        assert result.success is False
        assert result.action == "CONFIG_GET_MISSING_KEY"
        assert "缺少参数" in result.message


class TestConfigSetCommand:
    """Tests for /config set <KEY> <VALUE> subcommand (Story 8.2 AC3).
    
    Note: These tests mock the admin user ID to allow config set operations.
    Permission control tests are in TestConfigSetPermissionControl.
    """

    def test_config_set_valid_trading_backend(self):
        """AC3: /config set TRADING_BACKEND with valid value updates config."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "hyperliquid"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADING_BACKEND", "hyperliquid")

        # Backend key 不再可通过 /config set 修改，应当返回 INVALID_KEY
        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_KEY"

    def test_config_set_valid_market_data_backend(self):
        """AC3: /config set MARKET_DATA_BACKEND with valid value updates config."""
        cmd = _make_config_command(["set", "MARKET_DATA_BACKEND", "backpack"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "MARKET_DATA_BACKEND", "backpack")

        # Backend key 不再可通过 /config set 修改，应当返回 INVALID_KEY
        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_KEY"

    def test_config_set_valid_interval(self):
        """AC3: /config set TRADEBOT_INTERVAL with valid value updates config."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")

        assert result.success is True
        assert result.state_changed is True
        assert get_runtime_override("TRADEBOT_INTERVAL") == "5m"

    def test_config_set_valid_temperature(self):
        """AC3: /config set TRADEBOT_LLM_TEMPERATURE with valid value updates config."""
        cmd = _make_config_command(["set", "TRADEBOT_LLM_TEMPERATURE", "0.5"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_LLM_TEMPERATURE", "0.5")

        assert result.success is True
        assert result.state_changed is True
        assert get_runtime_override("TRADEBOT_LLM_TEMPERATURE") == 0.5

    def test_config_set_invalid_key_returns_error(self):
        """AC3: /config set with invalid key returns error."""
        cmd = _make_config_command(["set", "INVALID_KEY", "value"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "INVALID_KEY", "value")

        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_KEY"
        assert "无效" in result.message

    def test_config_set_invalid_trading_backend_value(self):
        """AC3: /config set TRADING_BACKEND with invalid value returns error."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "invalid_backend"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADING_BACKEND", "invalid_backend")

        # Backend key 本身在 /config 中无效，应直接走 INVALID_KEY
        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_KEY"

    def test_config_set_invalid_interval_value(self):
        """AC3: /config set TRADEBOT_INTERVAL with invalid value returns error."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "invalid"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "invalid")

        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_VALUE"

    def test_config_set_temperature_out_of_range(self):
        """AC3: /config set TRADEBOT_LLM_TEMPERATURE out of range returns error."""
        cmd = _make_config_command(["set", "TRADEBOT_LLM_TEMPERATURE", "5.0"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_LLM_TEMPERATURE", "5.0")

        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_VALUE"
        # Should mention valid range
        assert "范围" in result.message or "0" in result.message

    def test_config_set_temperature_invalid_format(self):
        """AC3: /config set TRADEBOT_LLM_TEMPERATURE with non-numeric value returns error."""
        cmd = _make_config_command(["set", "TRADEBOT_LLM_TEMPERATURE", "not_a_number"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_LLM_TEMPERATURE", "not_a_number")

        assert result.success is False
        assert result.action == "CONFIG_SET_INVALID_VALUE"

    def test_config_set_case_insensitive_key(self):
        """AC3: /config set should be case-insensitive for key names."""
        cmd = _make_config_command(["set", "tradebot_interval", "5m"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "tradebot_interval", "5m")

        assert result.success is True
        assert get_runtime_override("TRADEBOT_INTERVAL") == "5m"

    def test_config_set_missing_key_via_main_handler(self):
        """Test /config set without key via main handler."""
        cmd = _make_config_command(["set"])
        result = handle_config_command(cmd)

        assert result.success is False
        assert result.action == "CONFIG_SET_MISSING_KEY"

    def test_config_set_missing_value_via_main_handler(self):
        """Test /config set with key but no value via main handler."""
        cmd = _make_config_command(["set", "TRADING_BACKEND"])
        result = handle_config_command(cmd)

        assert result.success is False
        assert result.action == "CONFIG_SET_MISSING_VALUE"


class TestConfigMainHandler:
    """Tests for the main /config command handler."""

    def test_config_no_subcommand_shows_help(self):
        """Test /config without subcommand shows usage help."""
        cmd = _make_config_command([])
        result = handle_config_command(cmd)

        assert result.success is True
        assert result.action == "CONFIG_HELP"
        assert "list" in result.message
        assert "get" in result.message
        assert "set" in result.message

    def test_config_unknown_subcommand_returns_error(self):
        """Test /config with unknown subcommand returns error."""
        cmd = _make_config_command(["unknown"])
        result = handle_config_command(cmd)

        assert result.success is False
        assert result.action == "CONFIG_UNKNOWN_SUBCOMMAND"
        assert "未知子命令" in result.message

    def test_config_list_dispatches_correctly(self):
        """Test /config list dispatches to list handler."""
        cmd = _make_config_command(["list"])
        result = handle_config_command(cmd)

        assert result.action == "CONFIG_LIST"

    def test_config_get_dispatches_correctly(self):
        """Test /config get KEY dispatches to get handler."""
        cmd = _make_config_command(["get", "TRADEBOT_INTERVAL"])
        result = handle_config_command(cmd)

        assert result.action == "CONFIG_GET"

    def test_config_set_dispatches_correctly(self):
        """Test /config set KEY VALUE dispatches to set handler."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_command(cmd)

        assert result.action == "CONFIG_SET"


class TestConfigValueInfo:
    """Tests for _get_config_value_info helper function."""

    def test_get_config_value_info_trading_backend(self):
        """Test _get_config_value_info for TRADING_BACKEND."""
        current, valid_range = _get_config_value_info("TRADING_BACKEND")

        assert current in VALID_TRADING_BACKENDS
        assert "可选值" in valid_range
        for backend in VALID_TRADING_BACKENDS:
            assert backend in valid_range

    def test_get_config_value_info_market_data_backend(self):
        """Test _get_config_value_info for MARKET_DATA_BACKEND."""
        current, valid_range = _get_config_value_info("MARKET_DATA_BACKEND")

        assert current in VALID_MARKET_DATA_BACKENDS
        assert "可选值" in valid_range

    def test_get_config_value_info_interval(self):
        """Test _get_config_value_info for TRADEBOT_INTERVAL."""
        current, valid_range = _get_config_value_info("TRADEBOT_INTERVAL")

        assert current in VALID_INTERVALS
        assert "可选值" in valid_range

    def test_get_config_value_info_temperature(self):
        """Test _get_config_value_info for TRADEBOT_LLM_TEMPERATURE."""
        current, valid_range = _get_config_value_info("TRADEBOT_LLM_TEMPERATURE")

        # Should be a valid float string
        float(current)
        assert "范围" in valid_range
        assert "0" in valid_range
        assert "2" in valid_range

    def test_get_config_value_info_unknown_key(self):
        """Test _get_config_value_info for unknown key."""
        current, valid_range = _get_config_value_info("UNKNOWN_KEY")

        assert current == "N/A"
        assert "未知" in valid_range


class TestConfigKeyDescriptions:
    """Tests for CONFIG_KEY_DESCRIPTIONS constant."""

    def test_all_whitelist_keys_have_descriptions(self):
        """All whitelisted keys should have descriptions."""
        whitelist = get_override_whitelist()
        for key in whitelist:
            assert key in CONFIG_KEY_DESCRIPTIONS
            assert len(CONFIG_KEY_DESCRIPTIONS[key]) > 0


class TestConfigSetUsesRuntimeOverridesAPI:
    """Tests to verify /config set uses runtime overrides public API."""

    def test_config_set_uses_runtime_overrides_api(self):
        """AC3: /config set should use runtime overrides API, not os.environ directly."""
        # Verify by checking that the override is set via the API
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")

        assert result.success is True
        # The override should be accessible via the runtime overrides API
        override = get_runtime_override("TRADEBOT_INTERVAL")
        assert override == "5m"

    def test_config_set_does_not_modify_os_environ(self):
        """AC3: /config set should not directly modify os.environ."""
        import os

        original_env = os.environ.get("TRADEBOT_INTERVAL")

        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")

        assert result.success is True
        # os.environ should not be changed
        assert os.environ.get("TRADEBOT_INTERVAL") == original_env


class TestConfigCommandIntegration:
    """Integration tests for /config command flow."""

    def test_full_config_workflow(self):
        """Test a complete workflow: list -> get -> set -> get."""
        with patch("config.settings.get_telegram_admin_user_id", return_value="123456789"):
            # 1. List all configs
            list_cmd = _make_config_command(["list"])
            list_result = handle_config_command(list_cmd)
            assert list_result.success is True

            # 2. Get a specific config
            get_cmd = _make_config_command(["get", "TRADEBOT_INTERVAL"])
            get_result = handle_config_command(get_cmd)
            assert get_result.success is True
            original_interval = None
            # Extract current value (it's in the message)

            # 3. Set a new value
            set_cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "30m"])
            set_result = handle_config_command(set_cmd)
            assert set_result.success is True
            assert set_result.state_changed is True

            # 4. Verify the change via get
            get_cmd2 = _make_config_command(["get", "TRADEBOT_INTERVAL"])
            get_result2 = handle_config_command(get_cmd2)
            assert get_result2.success is True
            assert "30m" in get_result2.message

    def test_config_set_shows_old_and_new_values(self):
        """Test that /config set response includes both old and new values."""
        # First set to a known value
        cmd1 = _make_config_command(["set", "TRADEBOT_INTERVAL", "15m"])
        with patch("config.settings.get_telegram_admin_user_id", return_value="123456789"):
            handle_config_command(cmd1)

            # Then change it
            cmd2 = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"])
            result = handle_config_command(cmd2)

        assert result.success is True
        # Should show both old (15m) and new (5m) values
        assert "15m" in result.message
        assert "5m" in result.message


# ═══════════════════════════════════════════════════════════════════
# Story 8.3: Permission Control Tests (AC1, AC2)
# ═══════════════════════════════════════════════════════════════════


class TestAdminUserIdConfiguration:
    """Tests for admin user ID configuration (Story 8.3 AC1)."""

    def test_get_telegram_admin_user_id_returns_configured_value(self):
        """AC1: get_telegram_admin_user_id should return configured admin ID."""
        from config.settings import get_telegram_admin_user_id
        
        with patch("config.settings.TELEGRAM_ADMIN_USER_ID", "admin123"):
            result = get_telegram_admin_user_id()
            assert result == "admin123"

    def test_get_telegram_admin_user_id_returns_empty_when_not_configured(self):
        """AC1: get_telegram_admin_user_id should return empty string when not set."""
        from config.settings import get_telegram_admin_user_id
        
        with patch("config.settings.TELEGRAM_ADMIN_USER_ID", ""):
            result = get_telegram_admin_user_id()
            assert result == ""

    def test_get_telegram_admin_user_id_strips_whitespace(self):
        """AC1: get_telegram_admin_user_id should strip whitespace."""
        from config.settings import get_telegram_admin_user_id
        
        with patch("config.settings.TELEGRAM_ADMIN_USER_ID", "  admin123  "):
            result = get_telegram_admin_user_id()
            assert result == "admin123"


class TestCheckAdminPermission:
    """Tests for _check_admin_permission helper function."""

    def test_check_admin_permission_returns_true_for_admin(self):
        """Admin user should be granted permission."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "paper"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            is_admin, admin_id = _check_admin_permission(cmd)
        
        assert is_admin is True
        assert admin_id == "admin123"

    def test_check_admin_permission_returns_false_for_non_admin(self):
        """Non-admin user should be denied permission."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "paper"], user_id="user456")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            is_admin, admin_id = _check_admin_permission(cmd)
        
        assert is_admin is False
        assert admin_id == "admin123"

    def test_check_admin_permission_returns_false_when_not_configured(self):
        """Permission should be denied when admin is not configured (secure default)."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "paper"], user_id="user456")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value=""):
            is_admin, admin_id = _check_admin_permission(cmd)
        
        assert is_admin is False
        assert admin_id == ""

    def test_check_admin_permission_returns_false_for_empty_user_id(self):
        """Permission should be denied when user_id is empty."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "paper"], user_id="")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            is_admin, admin_id = _check_admin_permission(cmd)
        
        assert is_admin is False
        assert admin_id == "admin123"


class TestConfigSetPermissionControl:
    """Tests for /config set permission control (Story 8.3 AC2)."""

    def test_config_set_allowed_for_admin_user(self):
        """AC2: /config set should succeed when user is admin."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")
        
        assert result.success is True
        assert result.action == "CONFIG_SET"
        assert result.state_changed is True
        assert get_runtime_override("TRADEBOT_INTERVAL") == "5m"

    def test_config_set_denied_for_non_admin_user(self):
        """AC2: /config set should be denied for non-admin users."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "hyperliquid"], user_id="user456")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADING_BACKEND", "hyperliquid")
        
        assert result.success is False
        assert result.action == "CONFIG_SET_PERMISSION_DENIED"
        assert result.state_changed is False
        # Config should NOT be changed
        assert get_runtime_override("TRADING_BACKEND") is None
        # Message should indicate permission denied
        assert "无权限" in result.message or "权限" in result.message

    def test_config_set_denied_when_admin_not_configured(self):
        """AC2: /config set should be denied when admin is not configured."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "hyperliquid"], user_id="user456")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value=""):
            result = handle_config_set_command(cmd, "TRADING_BACKEND", "hyperliquid")
        
        assert result.success is False
        assert result.action == "CONFIG_SET_PERMISSION_DENIED"
        assert result.state_changed is False
        # Config should NOT be changed
        assert get_runtime_override("TRADING_BACKEND") is None
        # Message should mention configuration needed
        assert "TELEGRAM_ADMIN_USER_ID" in result.message or "未配置" in result.message

    def test_config_set_permission_denied_message_suggests_read_commands(self):
        """AC2: Permission denied message should suggest using read-only commands."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="user456")
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")
        
        assert result.success is False
        # Message should suggest list/get commands
        assert "/config list" in result.message or "/config get" in result.message

    def test_config_list_allowed_for_any_user(self):
        """AC2: /config list should work for any user (read-only)."""
        cmd = _make_config_command(["list"], user_id="any_user")
        result = handle_config_list_command(cmd)
        
        assert result.success is True
        assert result.action == "CONFIG_LIST"

    def test_config_get_allowed_for_any_user(self):
        """AC2: /config get should work for any user (read-only)."""
        cmd = _make_config_command(["get", "TRADEBOT_INTERVAL"], user_id="any_user")
        result = handle_config_get_command(cmd, "TRADEBOT_INTERVAL")
        
        assert result.success is True
        assert result.action == "CONFIG_GET"

    def test_config_get_allowed_for_any_user_llm_temperature(self):
        """AC2: /config get should work for any user (read-only)."""
        cmd = _make_config_command(["get", "TRADEBOT_LLM_TEMPERATURE"], user_id="any_user")
        result = handle_config_get_command(cmd, "TRADEBOT_LLM_TEMPERATURE")
        
        assert result.success is True
        assert result.action == "CONFIG_GET"

    def test_config_get_invalid_key_trading_backend(self):
        """AC2: /config get should fail for invalid key."""
        cmd = _make_config_command(["get", "TRADING_BACKEND"], user_id="any_user")
        result = handle_config_get_command(cmd, "TRADING_BACKEND")
        
# ═══════════════════════════════════════════════════════════════════
# Story 8.3: Audit Logging Tests (AC3)
# ═══════════════════════════════════════════════════════════════════


class TestConfigAuditLogging:
    """Tests for /config set audit logging (Story 8.3 AC3)."""

    def test_audit_log_written_on_successful_config_set(self, caplog):
        """AC3: Successful /config set should write audit log."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")
        
        assert result.success is True
        
        # Check that audit log was written
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) >= 1
        
        audit_message = audit_logs[0].message
        assert "user_id=admin123" in audit_message
        assert "key=TRADEBOT_INTERVAL" in audit_message
        assert "new_value=5m" in audit_message
        assert "success=True" in audit_message

    def test_audit_log_contains_timestamp(self, caplog):
        """AC3: Audit log should contain timestamp."""
        cmd = _make_config_command(["set", "TRADEBOT_INTERVAL", "5m"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")
        
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) >= 1
        
        audit_message = audit_logs[0].message
        assert "timestamp=" in audit_message

    def test_audit_log_contains_old_and_new_values(self, caplog):
        """AC3: Audit log should contain both old and new values."""
        # First set to a known value
        cmd1 = _make_config_command(["set", "TRADEBOT_INTERVAL", "15m"], user_id="admin123")
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            handle_config_set_command(cmd1, "TRADEBOT_INTERVAL", "15m")
        
        # Clear logs and change value
        caplog.clear()
        cmd2 = _make_config_command(["set", "TRADEBOT_INTERVAL", "30m"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                handle_config_set_command(cmd2, "TRADEBOT_INTERVAL", "30m")
        
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) >= 1
        
        audit_message = audit_logs[0].message
        assert "old_value=15m" in audit_message
        assert "new_value=30m" in audit_message

    def test_audit_log_contains_chat_id(self, caplog):
        """AC3: Audit log should contain chat_id."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "paper"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                handle_config_set_command(cmd, "TRADEBOT_INTERVAL", "5m")
        
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) >= 1
        
        audit_message = audit_logs[0].message
        assert "chat_id=123456789" in audit_message

    def test_no_audit_log_on_permission_denied(self, caplog):
        """AC3: No audit log should be written when permission is denied."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "hyperliquid"], user_id="user456")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_config_set_command(cmd, "TRADING_BACKEND", "hyperliquid")
        
        assert result.success is False
        
        # Should NOT have CONFIG_AUDIT log (only permission denied warning)
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) == 0

    def test_no_audit_log_on_invalid_key(self, caplog):
        """AC3: No audit log should be written for invalid key."""
        cmd = _make_config_command(["set", "INVALID_KEY", "value"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_config_set_command(cmd, "INVALID_KEY", "value")
        
        assert result.success is False
        
        # Should NOT have CONFIG_AUDIT log
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) == 0

    def test_no_audit_log_on_invalid_value(self, caplog):
        """AC3: No audit log should be written for invalid value."""
        cmd = _make_config_command(["set", "TRADING_BACKEND", "invalid_backend"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_config_set_command(cmd, "TRADEBOT_LLM_TEMPERATURE", "invalid")
        
        assert result.success is False
        
        # Should NOT have CONFIG_AUDIT log
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) == 0


class TestLogConfigAuditHelper:
    """Tests for _log_config_audit helper function."""

    def test_log_config_audit_writes_warning_level(self, caplog):
        """Audit log should be written at WARNING level."""
        with caplog.at_level(logging.WARNING):
            _log_config_audit(
                user_id="test_user",
                key="TEST_KEY",
                old_value="old",
                new_value="new",
                success=True,
                chat_id="12345",
            )
        
        assert len(caplog.records) >= 1
        assert caplog.records[0].levelno == logging.WARNING

    def test_log_config_audit_format(self, caplog):
        """Audit log should follow expected format."""
        with caplog.at_level(logging.WARNING):
            _log_config_audit(
                user_id="user123",
                key="TRADING_BACKEND",
                old_value="paper",
                new_value="hyperliquid",
                success=True,
                chat_id="chat456",
            )
        
        message = caplog.records[0].message
        assert "CONFIG_AUDIT" in message
        assert "user_id=user123" in message
        assert "chat_id=chat456" in message
        assert "key=TRADING_BACKEND" in message
        assert "old_value=paper" in message
        assert "new_value=hyperliquid" in message
        assert "success=True" in message


# ═══════════════════════════════════════════════════════════════════
# Story 8.3: Integration Tests
# ═══════════════════════════════════════════════════════════════════


class TestConfigPermissionIntegration:
    """Integration tests for permission control with runtime overrides."""

    def test_full_admin_workflow(self, caplog):
        """Test complete admin workflow: set config and verify audit log."""
        # Admin sets config
        cmd = _make_config_command(["set", "TRADEBOT_LLM_TEMPERATURE", "0.5"], user_id="admin123")
        
        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_config_set_command(cmd, "TRADEBOT_LLM_TEMPERATURE", "0.5")
        
        # Verify success
        assert result.success is True
        assert result.state_changed is True
        assert get_runtime_override("TRADEBOT_LLM_TEMPERATURE") == 0.5
        
        # Verify audit log
        audit_logs = [r for r in caplog.records if "CONFIG_AUDIT" in r.message]
        assert len(audit_logs) >= 1

    def test_non_admin_cannot_modify_config(self):
        """Test that non-admin user cannot modify any config."""
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            # Try to modify each whitelisted key
            for key in get_override_whitelist():
                cmd = _make_config_command(["set", key, "test_value"], user_id="non_admin")
                result = handle_config_set_command(cmd, key, "test_value")
                
                assert result.success is False
                assert result.action == "CONFIG_SET_PERMISSION_DENIED"

    def test_admin_can_modify_all_whitelisted_keys(self):
        """Test that admin can modify all whitelisted config keys."""
        test_values = {
            "TRADING_BACKEND": "paper",
            "MARKET_DATA_BACKEND": "binance",
            "TRADEBOT_INTERVAL": "5m",
            "TRADEBOT_LLM_TEMPERATURE": "0.5",
            "TRADEBOT_LOOP_ENABLED": "false",
        }
        
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            for key, value in test_values.items():
                cmd = _make_config_command(["set", key, value], user_id="admin123")
                result = handle_config_set_command(cmd, key, value)
                
                if key in ("TRADEBOT_INTERVAL", "TRADEBOT_LLM_TEMPERATURE", "TRADEBOT_LOOP_ENABLED"):
                    # Interval、LLM temperature 和 TRADEBOT_LOOP_ENABLED 应当可以通过 /config set 成功修改
                    assert result.success is True, f"Failed to set {key}"
                    assert result.action == "CONFIG_SET"
                else:
                    # backend 两个 key 当前版本不再通过 /config set 暴露
                    assert result.success is False
                    assert result.action == "CONFIG_SET_INVALID_KEY"
