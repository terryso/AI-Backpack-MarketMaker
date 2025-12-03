"""
Tests for Telegram /close_all command functionality.

Story 7.4.7: Implement /close_all batch position close command.

Tests cover:
- AC1: Command format support (/close_all, /close_all long, /close_all short)
- AC2: Preview mode behavior (no confirm)
- AC3: Confirm mode with reduce-only batch close
- AC4: No positions scenario handling
- AC5: Error and partial failure handling
- AC6: Works during Kill-Switch / daily loss limit activation
- AC7: Unit tests for all scenarios
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from notifications.commands.base import TelegramCommand, CommandResult
from notifications.commands.close_all import (
    handle_close_all_command,
    _parse_close_all_args,
    _filter_positions_by_direction,
    _build_position_summary,
    _build_close_all_preview,
    _calculate_position_notional,
    _execute_close_all,
    CloseAllParseResult,
    PositionSummary,
    CloseAllPreview,
    SingleCloseResult,
    CloseAllExecutionResult,
)


# ═══════════════════════════════════════════════════════════════════
# TEST FIXTURES
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_positions() -> Dict[str, Dict[str, Any]]:
    """Sample positions for testing with mixed directions."""
    return {
        "BTC": {
            "side": "long",
            "quantity": 0.5,
            "entry_price": 50000.0,
            "profit_target": 55000.0,
            "stop_loss": 48000.0,
            "leverage": 10.0,
            "margin": 2500.0,
        },
        "ETH": {
            "side": "short",
            "quantity": 5.0,
            "entry_price": 3000.0,
            "profit_target": 2700.0,
            "stop_loss": 3200.0,
            "leverage": 5.0,
            "margin": 3000.0,
        },
        "SOL": {
            "side": "long",
            "quantity": 100.0,
            "entry_price": 100.0,
            "profit_target": 120.0,
            "stop_loss": 90.0,
            "leverage": 5.0,
            "margin": 2000.0,
        },
        "DOGE": {
            "side": "short",
            "quantity": 10000.0,
            "entry_price": 0.1,
            "profit_target": 0.08,
            "stop_loss": 0.12,
            "leverage": 3.0,
            "margin": 333.33,
        },
    }


@pytest.fixture
def long_only_positions() -> Dict[str, Dict[str, Any]]:
    """Positions with only long direction."""
    return {
        "BTC": {
            "side": "long",
            "quantity": 0.5,
            "entry_price": 50000.0,
        },
        "ETH": {
            "side": "long",
            "quantity": 5.0,
            "entry_price": 3000.0,
        },
    }


@pytest.fixture
def short_only_positions() -> Dict[str, Dict[str, Any]]:
    """Positions with only short direction."""
    return {
        "BTC": {
            "side": "short",
            "quantity": 0.5,
            "entry_price": 50000.0,
        },
        "ETH": {
            "side": "short",
            "quantity": 5.0,
            "entry_price": 3000.0,
        },
    }


@pytest.fixture
def close_all_command() -> TelegramCommand:
    """Sample /close_all command (preview all)."""
    return TelegramCommand(
        command="close_all",
        args=[],
        chat_id="123456789",
        message_id=1,
        raw_text="/close_all",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def close_all_long_command() -> TelegramCommand:
    """Sample /close_all long command (preview long only)."""
    return TelegramCommand(
        command="close_all",
        args=["long"],
        chat_id="123456789",
        message_id=2,
        raw_text="/close_all long",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def close_all_short_command() -> TelegramCommand:
    """Sample /close_all short command (preview short only)."""
    return TelegramCommand(
        command="close_all",
        args=["short"],
        chat_id="123456789",
        message_id=3,
        raw_text="/close_all short",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def close_all_confirm_command() -> TelegramCommand:
    """Sample /close_all confirm command (execute all)."""
    return TelegramCommand(
        command="close_all",
        args=["confirm"],
        chat_id="123456789",
        message_id=4,
        raw_text="/close_all confirm",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def close_all_long_confirm_command() -> TelegramCommand:
    """Sample /close_all long confirm command (execute long only)."""
    return TelegramCommand(
        command="close_all",
        args=["long", "confirm"],
        chat_id="123456789",
        message_id=5,
        raw_text="/close_all long confirm",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def close_all_short_confirm_command() -> TelegramCommand:
    """Sample /close_all short confirm command (execute short only)."""
    return TelegramCommand(
        command="close_all",
        args=["short", "confirm"],
        chat_id="123456789",
        message_id=6,
        raw_text="/close_all short confirm",
        raw_update={},
        user_id="111222333",
    )


# ═══════════════════════════════════════════════════════════════════
# AC1: COMMAND FORMAT TESTS
# ═══════════════════════════════════════════════════════════════════

class TestParseCloseAllArgs:
    """Tests for /close_all command argument parsing (AC1)."""
    
    def test_parse_no_args_returns_all_preview(self):
        """Test parsing with no arguments returns all directions, preview mode."""
        result = _parse_close_all_args([])
        assert result.direction == "all"
        assert result.with_confirm is False
        assert result.error is None
    
    def test_parse_confirm_only_returns_all_confirm(self):
        """Test parsing 'confirm' only returns all directions, confirm mode."""
        result = _parse_close_all_args(["confirm"])
        assert result.direction == "all"
        assert result.with_confirm is True
        assert result.error is None
    
    def test_parse_long_returns_long_preview(self):
        """Test parsing 'long' returns long direction, preview mode."""
        result = _parse_close_all_args(["long"])
        assert result.direction == "long"
        assert result.with_confirm is False
        assert result.error is None
    
    def test_parse_short_returns_short_preview(self):
        """Test parsing 'short' returns short direction, preview mode."""
        result = _parse_close_all_args(["short"])
        assert result.direction == "short"
        assert result.with_confirm is False
        assert result.error is None
    
    def test_parse_long_confirm_returns_long_confirm(self):
        """Test parsing 'long confirm' returns long direction, confirm mode."""
        result = _parse_close_all_args(["long", "confirm"])
        assert result.direction == "long"
        assert result.with_confirm is True
        assert result.error is None
    
    def test_parse_short_confirm_returns_short_confirm(self):
        """Test parsing 'short confirm' returns short direction, confirm mode."""
        result = _parse_close_all_args(["short", "confirm"])
        assert result.direction == "short"
        assert result.with_confirm is True
        assert result.error is None
    
    def test_parse_invalid_arg_returns_error(self):
        """Test parsing invalid argument returns error."""
        result = _parse_close_all_args(["foo"])
        assert result.error is not None
        assert "无效的参数" in result.error
    
    def test_parse_duplicate_confirm_returns_error(self):
        """Test parsing duplicate 'confirm' returns error."""
        result = _parse_close_all_args(["confirm", "confirm"])
        assert result.error is not None
        assert "重复" in result.error
    
    def test_parse_multiple_directions_returns_error(self):
        """Test parsing multiple directions returns error."""
        result = _parse_close_all_args(["long", "short"])
        assert result.error is not None
        assert "只能指定一个方向" in result.error
    
    def test_parse_wrong_order_returns_error(self):
        """Test parsing wrong order (confirm before direction) returns error."""
        result = _parse_close_all_args(["confirm", "long"])
        assert result.error is not None
        assert "顺序错误" in result.error
    
    def test_parse_case_insensitive(self):
        """Test parsing is case insensitive."""
        result = _parse_close_all_args(["LONG", "CONFIRM"])
        assert result.direction == "long"
        assert result.with_confirm is True
        assert result.error is None


# ═══════════════════════════════════════════════════════════════════
# AC2: PREVIEW MODE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestPreviewMode:
    """Tests for preview mode behavior (AC2)."""
    
    def test_preview_all_shows_summary(
        self, close_all_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all shows summary of all positions."""
        result = handle_close_all_command(
            close_all_command,
            positions=sample_positions,
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_PREVIEW"
        # Should show both long and short summaries
        assert "多头" in result.message
        assert "空头" in result.message
        # Should show confirm instruction
        assert "confirm" in result.message.lower()
    
    def test_preview_long_shows_long_only(
        self, close_all_long_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all long shows only long positions."""
        result = handle_close_all_command(
            close_all_long_command,
            positions=sample_positions,
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_PREVIEW"
        assert "多头" in result.message
        # Confirm instruction should be for long
        assert "long confirm" in result.message.lower()
    
    def test_preview_short_shows_short_only(
        self, close_all_short_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all short shows only short positions."""
        result = handle_close_all_command(
            close_all_short_command,
            positions=sample_positions,
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_PREVIEW"
        assert "空头" in result.message
        # Confirm instruction should be for short
        assert "short confirm" in result.message.lower()
    
    def test_preview_shows_notional_breakdown(
        self, close_all_command: TelegramCommand, sample_positions: Dict
    ):
        """Test preview shows notional breakdown by direction."""
        result = handle_close_all_command(
            close_all_command,
            positions=sample_positions,
            execute_close_fn=None,
        )
        
        assert result.success is True
        # Should contain dollar amounts
        assert "$" in result.message
    
    def test_preview_does_not_execute(
        self, close_all_command: TelegramCommand, sample_positions: Dict
    ):
        """Test preview mode does not call execute_close_fn."""
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            return MagicMock(success=True)
        
        result = handle_close_all_command(
            close_all_command,
            positions=sample_positions,
            execute_close_fn=track_execute,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert len(executed) == 0  # Should not execute anything


# ═══════════════════════════════════════════════════════════════════
# AC3: CONFIRM MODE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestConfirmMode:
    """Tests for confirm mode with batch close execution (AC3)."""
    
    def test_confirm_all_executes_all_positions(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all confirm executes close for all positions."""
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.errors = []
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=track_execute,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "CLOSE_ALL_EXECUTED"
        assert len(executed) == 4  # All 4 positions
    
    def test_confirm_long_executes_long_only(
        self, close_all_long_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all long confirm executes only long positions."""
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.errors = []
            return mock_result
        
        result = handle_close_all_command(
            close_all_long_confirm_command,
            positions=sample_positions,
            execute_close_fn=track_execute,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert len(executed) == 2  # Only BTC and SOL (long)
        assert all(side == "long" for _, side, _ in executed)
    
    def test_confirm_short_executes_short_only(
        self, close_all_short_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all short confirm executes only short positions."""
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.errors = []
            return mock_result
        
        result = handle_close_all_command(
            close_all_short_confirm_command,
            positions=sample_positions,
            execute_close_fn=track_execute,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert len(executed) == 2  # Only ETH and DOGE (short)
        assert all(side == "short" for _, side, _ in executed)
    
    def test_confirm_uses_fresh_positions(
        self, close_all_confirm_command: TelegramCommand
    ):
        """Test confirm mode uses fresh positions snapshot."""
        # This is implicitly tested by passing positions to the handler
        # The handler should use the positions passed to it, not cached data
        positions = {
            "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0},
        }
        
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=positions,
            execute_close_fn=track_execute,
        )
        
        assert result.success is True
        assert len(executed) == 1
        assert executed[0][0] == "BTC"


# ═══════════════════════════════════════════════════════════════════
# AC4: NO POSITIONS SCENARIO TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNoPositionsScenario:
    """Tests for no positions scenario (AC4)."""
    
    def test_preview_no_positions_returns_message(
        self, close_all_command: TelegramCommand
    ):
        """Test preview with no positions returns appropriate message."""
        result = handle_close_all_command(
            close_all_command,
            positions={},
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_NO_POSITIONS"
        assert "无" in result.message
        assert "/positions" in result.message.lower()
    
    def test_preview_no_long_positions_returns_message(
        self, close_all_long_command: TelegramCommand, short_only_positions: Dict
    ):
        """Test preview long with no long positions returns message."""
        result = handle_close_all_command(
            close_all_long_command,
            positions=short_only_positions,
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_NO_POSITIONS"
    
    def test_preview_no_short_positions_returns_message(
        self, close_all_short_command: TelegramCommand, long_only_positions: Dict
    ):
        """Test preview short with no short positions returns message."""
        result = handle_close_all_command(
            close_all_short_command,
            positions=long_only_positions,
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_NO_POSITIONS"
    
    def test_confirm_no_positions_returns_message(
        self, close_all_confirm_command: TelegramCommand
    ):
        """Test confirm with no positions returns appropriate message."""
        result = handle_close_all_command(
            close_all_confirm_command,
            positions={},
            execute_close_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_NO_POSITIONS_CONFIRM"
        assert "无" in result.message
        # Should mention possible reason
        assert "可能" in result.message or "其它" in result.message


# ═══════════════════════════════════════════════════════════════════
# AC5: ERROR AND PARTIAL FAILURE HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Tests for error and partial failure handling (AC5)."""
    
    def test_parse_error_returns_failure(self):
        """Test parse error returns failure with message."""
        cmd = TelegramCommand(
            command="close_all",
            args=["invalid_arg"],
            chat_id="123456789",
            message_id=1,
            raw_text="/close_all invalid_arg",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_close_all_command(
            cmd,
            positions={},
            execute_close_fn=None,
        )
        
        assert result.success is False
        assert result.action == "CLOSE_ALL_PARSE_ERROR"
    
    def test_partial_failure_continues_execution(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test partial failure continues execution for other symbols."""
        call_count = [0]
        def partial_fail_execute(coin, side, qty):
            call_count[0] += 1
            mock_result = MagicMock()
            # Fail for BTC, succeed for others
            if coin == "BTC":
                mock_result.success = False
                mock_result.errors = ["Insufficient balance"]
            else:
                mock_result.success = True
                mock_result.errors = []
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=partial_fail_execute,
        )
        
        # Should still be considered success (partial)
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "CLOSE_ALL_PARTIAL"
        # Should have called execute for all 4 positions
        assert call_count[0] == 4
        # Message should indicate partial failure
        assert "部分" in result.message or "失败" in result.message
    
    def test_all_failures_returns_failure(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test all failures returns failure status."""
        def all_fail_execute(coin, side, qty):
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.errors = ["Exchange error"]
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=all_fail_execute,
        )
        
        assert result.success is False
        assert result.state_changed is False
        assert result.action == "CLOSE_ALL_FAILED"
    
    def test_execution_exception_is_caught(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test execution exception is caught and logged."""
        call_count = [0]
        def exception_execute(coin, side, qty):
            call_count[0] += 1
            if coin == "BTC":
                raise Exception("Network error")
            mock_result = MagicMock()
            mock_result.success = True
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=exception_execute,
        )
        
        # Should continue with other positions
        assert call_count[0] == 4
        # Should be partial success
        assert result.success is True
        assert result.action == "CLOSE_ALL_PARTIAL"
    
    def test_execution_returns_none_is_handled(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test execution returning None is handled as failure."""
        def none_execute(coin, side, qty):
            if coin == "BTC":
                return None  # Routing failure
            mock_result = MagicMock()
            mock_result.success = True
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=none_execute,
        )
        
        # Should be partial success
        assert result.success is True
        assert result.action == "CLOSE_ALL_PARTIAL"
    
    def test_failure_message_shows_error_samples(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test failure message shows sample errors."""
        def fail_with_error(coin, side, qty):
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.errors = [f"Error for {coin}"]
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=fail_with_error,
        )
        
        # Should show some error details
        assert "Error" in result.message or "错误" in result.message


# ═══════════════════════════════════════════════════════════════════
# AC6: KILL-SWITCH / DAILY LOSS LIMIT INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestKillSwitchIntegration:
    """Tests for Kill-Switch integration (AC6)."""
    
    def test_close_all_works_during_kill_switch(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all works when Kill-Switch is active."""
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=track_execute,
            kill_switch_active=True,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert len(executed) == 4
    
    def test_close_all_works_during_daily_loss_limit(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test /close_all works when daily loss limit is triggered."""
        executed = []
        def track_execute(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            return mock_result
        
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=track_execute,
            daily_loss_triggered=True,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert len(executed) == 4
    
    def test_preview_shows_kill_switch_warning(
        self, close_all_command: TelegramCommand, sample_positions: Dict
    ):
        """Test preview shows Kill-Switch warning when active."""
        result = handle_close_all_command(
            close_all_command,
            positions=sample_positions,
            execute_close_fn=None,
            kill_switch_active=True,
        )
        
        assert result.success is True
        assert "Kill" in result.message or "kill" in result.message.lower()
    
    def test_preview_shows_daily_loss_warning(
        self, close_all_command: TelegramCommand, sample_positions: Dict
    ):
        """Test preview shows daily loss warning when triggered."""
        result = handle_close_all_command(
            close_all_command,
            positions=sample_positions,
            execute_close_fn=None,
            daily_loss_triggered=True,
        )
        
        assert result.success is True
        assert "亏损" in result.message or "限制" in result.message


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestFilterPositionsByDirection:
    """Tests for position filtering by direction."""
    
    def test_filter_all_returns_all(self, sample_positions: Dict):
        """Test filtering with 'all' returns all positions."""
        filtered = _filter_positions_by_direction(sample_positions, "all")
        assert len(filtered) == 4
    
    def test_filter_long_returns_long_only(self, sample_positions: Dict):
        """Test filtering with 'long' returns only long positions."""
        filtered = _filter_positions_by_direction(sample_positions, "long")
        assert len(filtered) == 2
        assert all(pos["side"] == "long" for pos in filtered.values())
    
    def test_filter_short_returns_short_only(self, sample_positions: Dict):
        """Test filtering with 'short' returns only short positions."""
        filtered = _filter_positions_by_direction(sample_positions, "short")
        assert len(filtered) == 2
        assert all(pos["side"] == "short" for pos in filtered.values())
    
    def test_filter_empty_positions(self):
        """Test filtering empty positions returns empty."""
        filtered = _filter_positions_by_direction({}, "all")
        assert len(filtered) == 0


class TestCalculatePositionNotional:
    """Tests for position notional calculation."""
    
    def test_calculate_notional_basic(self):
        """Test basic notional calculation."""
        position = {"quantity": 1.0, "entry_price": 50000.0}
        notional = _calculate_position_notional(position)
        assert notional == 50000.0
    
    def test_calculate_notional_fractional(self):
        """Test notional calculation with fractional quantity."""
        position = {"quantity": 0.5, "entry_price": 50000.0}
        notional = _calculate_position_notional(position)
        assert notional == 25000.0
    
    def test_calculate_notional_zero_quantity(self):
        """Test notional calculation with zero quantity."""
        position = {"quantity": 0.0, "entry_price": 50000.0}
        notional = _calculate_position_notional(position)
        assert notional == 0.0
    
    def test_calculate_notional_missing_fields(self):
        """Test notional calculation with missing fields."""
        position = {}
        notional = _calculate_position_notional(position)
        assert notional == 0.0


class TestBuildPositionSummary:
    """Tests for position summary building."""
    
    def test_build_long_summary(self, sample_positions: Dict):
        """Test building summary for long positions."""
        summary = _build_position_summary(sample_positions, "long")
        assert summary.count == 2
        assert summary.notional > 0
        assert "BTC" in summary.symbols
        assert "SOL" in summary.symbols
    
    def test_build_short_summary(self, sample_positions: Dict):
        """Test building summary for short positions."""
        summary = _build_position_summary(sample_positions, "short")
        assert summary.count == 2
        assert summary.notional > 0
        assert "ETH" in summary.symbols
        assert "DOGE" in summary.symbols
    
    def test_build_summary_empty(self):
        """Test building summary for empty positions."""
        summary = _build_position_summary({}, "long")
        assert summary.count == 0
        assert summary.notional == 0.0
        assert len(summary.symbols) == 0


class TestBuildCloseAllPreview:
    """Tests for close all preview building."""
    
    def test_build_preview_all(self, sample_positions: Dict):
        """Test building preview for all directions."""
        preview = _build_close_all_preview(sample_positions, "all")
        assert preview.total_count == 4
        assert preview.long_summary.count == 2
        assert preview.short_summary.count == 2
    
    def test_build_preview_long(self, sample_positions: Dict):
        """Test building preview for long only."""
        preview = _build_close_all_preview(sample_positions, "long")
        assert preview.total_count == 2
        assert preview.total_notional == preview.long_summary.notional
    
    def test_build_preview_short(self, sample_positions: Dict):
        """Test building preview for short only."""
        preview = _build_close_all_preview(sample_positions, "short")
        assert preview.total_count == 2
        assert preview.total_notional == preview.short_summary.notional


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: HANDLER WIRING
# ═══════════════════════════════════════════════════════════════════

class TestCloseAllHandlerIntegration:
    """Integration tests for /close_all command handler wiring."""
    
    def test_close_all_handler_wiring_in_create_kill_resume_handlers(self):
        """Test that close_all_handler is correctly wired in create_kill_resume_handlers."""
        from core.risk_control import RiskControlState
        from notifications.commands.handlers import create_kill_resume_handlers
        
        state = RiskControlState()
        
        # Track execute_close_fn calls
        executed = []
        def mock_execute_close(coin, side, qty):
            executed.append((coin, side, qty))
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.errors = []
            return mock_result
        
        # Create handlers with execute_close_fn
        handlers = create_kill_resume_handlers(
            state=state,
            positions_snapshot_fn=lambda: {
                "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0},
                "ETH": {"side": "short", "quantity": 5.0, "entry_price": 3000.0},
            },
            account_snapshot_fn=None,
            execute_close_fn=mock_execute_close,
            bot_token="test_token",
            chat_id="123456",
        )
        
        # Verify close_all handler exists
        assert "close_all" in handlers
        
        # Create a close_all confirm command
        cmd = TelegramCommand(
            command="close_all",
            args=["confirm"],
            chat_id="123456",
            message_id=1,
            raw_text="/close_all confirm",
            raw_update={},
            user_id="111222333",
        )
        
        # Execute handler (should call execute_close_fn for all positions)
        handlers["close_all"](cmd)
        
        # Verify execute_close_fn was called for both positions
        assert len(executed) == 2
        symbols = {coin for coin, _, _ in executed}
        assert "BTC" in symbols
        assert "ETH" in symbols
    
    def test_close_all_handler_passes_risk_state(self):
        """Test that close_all handler passes kill_switch_active state."""
        from core.risk_control import RiskControlState
        from notifications.commands.handlers import create_kill_resume_handlers
        
        state = RiskControlState()
        state.kill_switch_active = True
        
        sent_messages = []
        def mock_send_fn(text, parse_mode):
            sent_messages.append(text)
        
        handlers = create_kill_resume_handlers(
            state=state,
            positions_snapshot_fn=lambda: {
                "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0},
            },
            account_snapshot_fn=None,
            execute_close_fn=None,
            send_fn=mock_send_fn,
            bot_token="test_token",
            chat_id="123456",
        )
        
        # Create a preview command
        cmd = TelegramCommand(
            command="close_all",
            args=[],
            chat_id="123456",
            message_id=1,
            raw_text="/close_all",
            raw_update={},
            user_id="111222333",
        )
        
        handlers["close_all"](cmd)
        
        # Verify Kill-Switch warning is shown
        assert len(sent_messages) == 1
        assert "Kill" in sent_messages[0] or "kill" in sent_messages[0].lower()


# ═══════════════════════════════════════════════════════════════════
# DRY-RUN MODE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestDryRunMode:
    """Tests for dry-run mode (no execute_close_fn)."""
    
    def test_confirm_without_execute_fn_returns_dry_run(
        self, close_all_confirm_command: TelegramCommand, sample_positions: Dict
    ):
        """Test confirm without execute_close_fn returns dry-run result."""
        result = handle_close_all_command(
            close_all_confirm_command,
            positions=sample_positions,
            execute_close_fn=None,  # No execute function
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "CLOSE_ALL_EXECUTED"
        assert "dry" in result.message.lower() or "完成" in result.message
