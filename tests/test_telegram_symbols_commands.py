"""
Tests for Telegram /symbols command handlers.

This module tests the /symbols list, /symbols add, and /symbols remove commands
implemented in Story 9.2.

Test coverage:
- Story 9.2 AC1: /symbols list 展示当前 Universe
- Story 9.2 AC2: /symbols add 成功路径
- Story 9.2 AC3: 非管理员 & 校验失败路径
- Story 9.2 AC4: /symbols remove 不触发强制平仓
- Story 9.2 AC6: 最小测试覆盖与安全回归
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import patch, MagicMock

from notifications.telegram_commands import (
    TelegramCommand,
    CommandResult,
    handle_symbols_command,
    handle_symbols_list_command,
    handle_symbols_add_command,
    handle_symbols_remove_command,
    _normalize_symbol,
    _check_symbols_admin_permission,
    _log_symbols_audit,
)
from config.universe import (
    get_effective_symbol_universe,
    set_symbol_universe,
    clear_symbol_universe_override,
    validate_symbol_for_universe,
)
from config.settings import SYMBOLS, SYMBOL_TO_COIN


@pytest.fixture(autouse=True)
def reset_universe():
    """Reset Universe override before and after each test."""
    clear_symbol_universe_override()
    yield
    clear_symbol_universe_override()


def _make_symbols_command(args: list[str], user_id: str = "123456789") -> TelegramCommand:
    """Create a TelegramCommand for /symbols with given args and user_id."""
    return TelegramCommand(
        command="symbols",
        args=args,
        chat_id="123456789",
        message_id=1,
        raw_text=f"/symbols {' '.join(args)}".strip(),
        raw_update={},
        user_id=user_id,
    )


# ═══════════════════════════════════════════════════════════════════
# Story 9.2 AC1: /symbols list Tests
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsListCommand:
    """Tests for /symbols list subcommand (AC1)."""

    def test_symbols_list_shows_default_universe(self):
        """AC1: /symbols list should show default Universe when no override."""
        cmd = _make_symbols_command(["list"])
        result = handle_symbols_list_command(cmd)

        assert result.success is True
        assert result.action == "SYMBOLS_LIST"
        assert result.state_changed is False

        # Should show default symbols
        for symbol in SYMBOLS:
            assert symbol in result.message or symbol.replace("_", "\\_") in result.message

    def test_symbols_list_shows_overridden_universe(self):
        """AC1: /symbols list should show overridden Universe."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["list"])
        result = handle_symbols_list_command(cmd)

        assert result.success is True
        assert "ETHUSDT" in result.message
        assert "BTCUSDT" in result.message
        # Should show count
        assert "2" in result.message

    def test_symbols_list_shows_empty_universe_warning(self):
        """AC1: /symbols list should show warning when Universe is empty."""
        set_symbol_universe([])

        cmd = _make_symbols_command(["list"])
        result = handle_symbols_list_command(cmd)

        assert result.success is True
        assert "为空" in result.message or "empty" in result.message.lower()
        assert "不会开启任何新交易" in result.message

    def test_symbols_list_sorts_alphabetically(self):
        """AC1: /symbols list should sort symbols alphabetically."""
        set_symbol_universe(["SOLUSDT", "BTCUSDT", "ETHUSDT"])

        cmd = _make_symbols_command(["list"])
        result = handle_symbols_list_command(cmd)

        assert result.success is True
        # Check that BTCUSDT appears before ETHUSDT in the message
        btc_pos = result.message.find("BTCUSDT")
        eth_pos = result.message.find("ETHUSDT")
        sol_pos = result.message.find("SOLUSDT")
        assert btc_pos < eth_pos < sol_pos

    def test_symbols_list_via_main_handler(self):
        """Test /symbols list via the main handle_symbols_command."""
        cmd = _make_symbols_command(["list"])
        result = handle_symbols_command(cmd)

        assert result.success is True
        assert result.action == "SYMBOLS_LIST"


# ═══════════════════════════════════════════════════════════════════
# Story 9.2 AC2: /symbols add Success Path Tests
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsAddCommand:
    """Tests for /symbols add subcommand (AC2)."""

    def test_symbols_add_success_path(self):
        """AC2: /symbols add should add valid symbol when admin."""
        # Start with a subset
        set_symbol_universe(["ETHUSDT"])

        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is True
        assert result.action == "SYMBOLS_ADD"
        assert result.state_changed is True

        # Verify symbol was added
        universe = get_effective_symbol_universe()
        assert "BTCUSDT" in universe
        assert "ETHUSDT" in universe

    def test_symbols_add_normalizes_input(self):
        """AC2: /symbols add should normalize symbol input (uppercase, trim)."""
        set_symbol_universe(["ETHUSDT"])

        cmd = _make_symbols_command(["add", "  btcusdt  "], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "  btcusdt  ")

        assert result.success is True
        universe = get_effective_symbol_universe()
        assert "BTCUSDT" in universe

    def test_symbols_add_already_exists(self):
        """AC2: /symbols add should handle symbol already in Universe."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is True
        assert result.action == "SYMBOLS_ADD_ALREADY_EXISTS"
        assert result.state_changed is False
        assert "已存在" in result.message

    def test_symbols_add_shows_old_and_new_count(self):
        """AC2: /symbols add should show old and new Universe counts."""
        set_symbol_universe(["ETHUSDT"])

        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is True
        assert "1" in result.message  # old count
        assert "2" in result.message  # new count

    def test_symbols_add_via_main_handler(self):
        """Test /symbols add via the main handle_symbols_command."""
        set_symbol_universe(["ETHUSDT"])

        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_command(cmd)

        assert result.success is True
        assert result.action == "SYMBOLS_ADD"


# ═══════════════════════════════════════════════════════════════════
# Story 9.2 AC3: Permission Denied & Validation Failure Tests
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsAddPermissionControl:
    """Tests for /symbols add permission control (AC3)."""

    def test_symbols_add_denied_for_non_admin(self):
        """AC3: /symbols add should be denied for non-admin users."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="user456")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is False
        assert result.action == "SYMBOLS_ADD_PERMISSION_DENIED"
        assert result.state_changed is False
        assert "无权限" in result.message

    def test_symbols_add_denied_when_admin_not_configured(self):
        """AC3: /symbols add should be denied when admin is not configured."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="user456")

        with patch("config.settings.get_telegram_admin_user_id", return_value=""):
            result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is False
        assert result.action == "SYMBOLS_ADD_PERMISSION_DENIED"
        assert "TELEGRAM_ADMIN_USER_ID" in result.message

    def test_symbols_add_permission_denied_suggests_list(self):
        """AC3: Permission denied message should suggest /symbols list."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="user456")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert "/symbols list" in result.message


class TestSymbolsAddValidation:
    """Tests for /symbols add validation (AC3)."""

    def test_symbols_add_invalid_symbol_rejected(self):
        """AC3: /symbols add should reject invalid symbols."""
        cmd = _make_symbols_command(["add", "INVALIDUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_add_command(cmd, "INVALIDUSDT")

        assert result.success is False
        assert result.action == "SYMBOLS_ADD_INVALID_SYMBOL"
        assert "无效" in result.message or "不在" in result.message

    def test_symbols_add_missing_symbol_parameter(self):
        """AC3: /symbols add without symbol should return error."""
        cmd = _make_symbols_command(["add"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_command(cmd)

        assert result.success is False
        assert result.action == "SYMBOLS_ADD_MISSING_SYMBOL"
        assert "缺少参数" in result.message


# ═══════════════════════════════════════════════════════════════════
# Story 9.2 AC4: /symbols remove Tests
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsRemoveCommand:
    """Tests for /symbols remove subcommand (AC4)."""

    def test_symbols_remove_success_path(self):
        """AC4: /symbols remove should remove symbol when admin."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT", "SOLUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_remove_command(cmd, "BTCUSDT")

        assert result.success is True
        assert result.action == "SYMBOLS_REMOVE"
        assert result.state_changed is True

        # Verify symbol was removed
        universe = get_effective_symbol_universe()
        assert "BTCUSDT" not in universe
        assert "ETHUSDT" in universe
        assert "SOLUSDT" in universe

    def test_symbols_remove_not_found(self):
        """AC4: /symbols remove should handle symbol not in Universe."""
        set_symbol_universe(["ETHUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_remove_command(cmd, "BTCUSDT")

        assert result.success is True
        assert result.action == "SYMBOLS_REMOVE_NOT_FOUND"
        assert result.state_changed is False
        assert "不在" in result.message

    def test_symbols_remove_message_warns_about_positions(self):
        """AC4: /symbols remove message should warn about existing positions."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_remove_command(cmd, "BTCUSDT")

        assert result.success is True
        # Should mention that positions are not force-closed
        assert "不会触发强制平仓" in result.message or "SL/TP" in result.message

    def test_symbols_remove_denied_for_non_admin(self):
        """AC4: /symbols remove should be denied for non-admin users."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="user456")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_remove_command(cmd, "BTCUSDT")

        assert result.success is False
        assert result.action == "SYMBOLS_REMOVE_PERMISSION_DENIED"
        assert result.state_changed is False

        # Verify symbol was NOT removed
        universe = get_effective_symbol_universe()
        assert "BTCUSDT" in universe

    def test_symbols_remove_normalizes_input(self):
        """AC4: /symbols remove should normalize symbol input."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["remove", "  btcusdt  "], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_remove_command(cmd, "  btcusdt  ")

        assert result.success is True
        universe = get_effective_symbol_universe()
        assert "BTCUSDT" not in universe

    def test_symbols_remove_via_main_handler(self):
        """Test /symbols remove via the main handle_symbols_command."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_command(cmd)

        assert result.success is True
        assert result.action == "SYMBOLS_REMOVE"


# ═══════════════════════════════════════════════════════════════════
# Main Handler Tests
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsMainHandler:
    """Tests for the main /symbols command handler."""

    def test_symbols_no_subcommand_shows_help(self):
        """Test /symbols without subcommand shows usage help."""
        cmd = _make_symbols_command([])
        result = handle_symbols_command(cmd)

        assert result.success is True
        assert result.action == "SYMBOLS_HELP"
        assert "list" in result.message
        assert "add" in result.message
        assert "remove" in result.message

    def test_symbols_unknown_subcommand_returns_error(self):
        """Test /symbols with unknown subcommand returns error."""
        cmd = _make_symbols_command(["unknown"])
        result = handle_symbols_command(cmd)

        assert result.success is False
        assert result.action == "SYMBOLS_UNKNOWN_SUBCOMMAND"
        assert "未知子命令" in result.message

    def test_symbols_list_dispatches_correctly(self):
        """Test /symbols list dispatches to list handler."""
        cmd = _make_symbols_command(["list"])
        result = handle_symbols_command(cmd)

        assert result.action == "SYMBOLS_LIST"

    def test_symbols_add_dispatches_correctly(self):
        """Test /symbols add SYMBOL dispatches to add handler."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_command(cmd)

        # Will be SYMBOLS_ADD or SYMBOLS_ADD_ALREADY_EXISTS depending on current state
        assert "SYMBOLS_ADD" in result.action

    def test_symbols_remove_dispatches_correctly(self):
        """Test /symbols remove SYMBOL dispatches to remove handler."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            result = handle_symbols_command(cmd)

        assert result.action == "SYMBOLS_REMOVE"


# ═══════════════════════════════════════════════════════════════════
# Helper Function Tests
# ═══════════════════════════════════════════════════════════════════


class TestNormalizeSymbol:
    """Tests for _normalize_symbol helper function."""

    def test_normalize_symbol_uppercase(self):
        """Test symbol normalization to uppercase."""
        assert _normalize_symbol("btcusdt") == "BTCUSDT"
        assert _normalize_symbol("BtcUsdt") == "BTCUSDT"
        assert _normalize_symbol("BTCUSDT") == "BTCUSDT"

    def test_normalize_symbol_strips_whitespace(self):
        """Test symbol normalization strips whitespace."""
        assert _normalize_symbol("  BTCUSDT  ") == "BTCUSDT"
        assert _normalize_symbol("\tBTCUSDT\n") == "BTCUSDT"

    def test_normalize_symbol_empty_string(self):
        """Test symbol normalization with empty string."""
        assert _normalize_symbol("") == ""
        assert _normalize_symbol("   ") == ""


class TestValidateSymbolForUniverse:
    """Tests for validate_symbol_for_universe function."""

    def test_validate_known_symbol_returns_true(self):
        """Test validation returns True for known symbols."""
        for symbol in SYMBOL_TO_COIN.keys():
            is_valid, error = validate_symbol_for_universe(symbol)
            assert is_valid is True
            assert error == ""

    def test_validate_unknown_symbol_returns_false(self):
        """Test validation returns False for unknown symbols."""
        is_valid, error = validate_symbol_for_universe("UNKNOWNUSDT")
        assert is_valid is False
        assert "不在已知交易对列表中" in error


class TestCheckSymbolsAdminPermission:
    """Tests for _check_symbols_admin_permission function."""

    def test_check_permission_returns_true_for_admin(self):
        """Admin user should be granted permission."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            is_admin, admin_id = _check_symbols_admin_permission(cmd)

        assert is_admin is True
        assert admin_id == "admin123"

    def test_check_permission_returns_false_for_non_admin(self):
        """Non-admin user should be denied permission."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="user456")

        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            is_admin, admin_id = _check_symbols_admin_permission(cmd)

        assert is_admin is False
        assert admin_id == "admin123"


# ═══════════════════════════════════════════════════════════════════
# Audit Logging Tests
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsAuditLogging:
    """Tests for /symbols audit logging."""

    def test_audit_log_written_on_successful_add(self, caplog):
        """Successful /symbols add should write audit log."""
        set_symbol_universe(["ETHUSDT"])

        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")

        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is True

        # Check that audit log was written
        audit_logs = [r for r in caplog.records if "SYMBOLS_AUDIT" in r.message]
        assert len(audit_logs) >= 1

        audit_message = audit_logs[0].message
        assert "action=ADD" in audit_message
        assert "symbol=BTCUSDT" in audit_message
        assert "user_id=admin123" in audit_message

    def test_audit_log_written_on_successful_remove(self, caplog):
        """Successful /symbols remove should write audit log."""
        set_symbol_universe(["ETHUSDT", "BTCUSDT"])

        cmd = _make_symbols_command(["remove", "BTCUSDT"], user_id="admin123")

        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_symbols_remove_command(cmd, "BTCUSDT")

        assert result.success is True

        # Check that audit log was written
        audit_logs = [r for r in caplog.records if "SYMBOLS_AUDIT" in r.message]
        assert len(audit_logs) >= 1

        audit_message = audit_logs[0].message
        assert "action=REMOVE" in audit_message
        assert "symbol=BTCUSDT" in audit_message

    def test_no_audit_log_on_permission_denied(self, caplog):
        """No audit log should be written when permission is denied."""
        cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="user456")

        with caplog.at_level(logging.WARNING):
            with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
                result = handle_symbols_add_command(cmd, "BTCUSDT")

        assert result.success is False

        # Should NOT have SYMBOLS_AUDIT log
        audit_logs = [r for r in caplog.records if "SYMBOLS_AUDIT" in r.message]
        assert len(audit_logs) == 0


# ═══════════════════════════════════════════════════════════════════
# Integration Tests with Universe API
# ═══════════════════════════════════════════════════════════════════


class TestSymbolsUniverseIntegration:
    """Integration tests verifying /symbols commands work with Universe API."""

    def test_full_workflow_add_list_remove(self):
        """Test a complete workflow: list -> add -> list -> remove -> list."""
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            # Start with default Universe
            clear_symbol_universe_override()

            # 1. List default Universe
            list_cmd = _make_symbols_command(["list"])
            list_result = handle_symbols_command(list_cmd)
            assert list_result.success is True
            initial_count = len(get_effective_symbol_universe())

            # 2. Set to a smaller Universe for testing
            set_symbol_universe(["ETHUSDT"])

            # 3. Add a symbol
            add_cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")
            add_result = handle_symbols_command(add_cmd)
            assert add_result.success is True
            assert add_result.state_changed is True

            # 4. Verify via list
            list_cmd2 = _make_symbols_command(["list"])
            list_result2 = handle_symbols_command(list_cmd2)
            assert "BTCUSDT" in list_result2.message
            assert "ETHUSDT" in list_result2.message

            # 5. Remove a symbol
            remove_cmd = _make_symbols_command(["remove", "ETHUSDT"], user_id="admin123")
            remove_result = handle_symbols_command(remove_cmd)
            assert remove_result.success is True
            assert remove_result.state_changed is True

            # 6. Verify via list
            list_cmd3 = _make_symbols_command(["list"])
            list_result3 = handle_symbols_command(list_cmd3)
            assert "BTCUSDT" in list_result3.message
            assert "ETHUSDT" not in list_result3.message

    def test_symbols_list_allowed_for_any_user(self):
        """AC1: /symbols list should work for any user (read-only)."""
        cmd = _make_symbols_command(["list"], user_id="any_user")
        result = handle_symbols_list_command(cmd)

        assert result.success is True
        assert result.action == "SYMBOLS_LIST"

    def test_universe_changes_persist_across_commands(self):
        """Universe changes should persist across multiple commands."""
        with patch("config.settings.get_telegram_admin_user_id", return_value="admin123"):
            set_symbol_universe(["ETHUSDT"])

            # Add BTCUSDT
            add_cmd = _make_symbols_command(["add", "BTCUSDT"], user_id="admin123")
            handle_symbols_command(add_cmd)

            # Verify directly via Universe API
            universe = get_effective_symbol_universe()
            assert "BTCUSDT" in universe
            assert "ETHUSDT" in universe
            assert len(universe) == 2

            # Add SOLUSDT
            add_cmd2 = _make_symbols_command(["add", "SOLUSDT"], user_id="admin123")
            handle_symbols_command(add_cmd2)

            # Verify
            universe2 = get_effective_symbol_universe()
            assert len(universe2) == 3
            assert "SOLUSDT" in universe2
