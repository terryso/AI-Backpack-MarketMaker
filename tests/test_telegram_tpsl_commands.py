"""
Tests for Telegram /sl, /tp, /tpsl command functionality.

Story 7.4.8: Implement /sl /tp /tpsl stop loss and take profit management commands.

Tests cover:
- AC1: /sl command format support (price, pct, shorthand modes)
- AC2: /tp command format support (price, pct, shorthand modes)
- AC3: /tpsl combined command with mode consistency check
- AC4: No position scenario handling
- AC5: Price reasonableness validation
- AC6: State update and user feedback
- AC7: Error handling and structured logging
- AC8: Unit tests for all scenarios
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from notifications.commands.base import TelegramCommand, CommandResult
from notifications.commands.tpsl import (
    handle_sl_command,
    handle_tp_command,
    handle_tpsl_command,
    get_positions_for_tpsl,
    _normalize_symbol,
    _parse_sl_args,
    _parse_tp_args,
    _parse_tpsl_args,
    _find_position_for_symbol,
    _calculate_target_price,
    _validate_sl_price,
    _validate_tp_price,
    _calculate_distance_pct,
    _parse_value_with_mode,
    PriceMode,
    TPSLParseResult,
    TPSLUpdateResult,
)


# ═══════════════════════════════════════════════════════════════════
# TEST FIXTURES
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_long_position() -> Dict[str, Dict[str, Any]]:
    """Sample long position for testing."""
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
    }


@pytest.fixture
def sample_short_position() -> Dict[str, Dict[str, Any]]:
    """Sample short position for testing."""
    return {
        "ETH": {
            "side": "short",
            "quantity": 5.0,
            "entry_price": 3000.0,
            "profit_target": 2700.0,
            "stop_loss": 3200.0,
            "leverage": 5.0,
            "margin": 3000.0,
        },
    }


@pytest.fixture
def sample_positions() -> Dict[str, Dict[str, Any]]:
    """Sample positions for testing."""
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
    }


@pytest.fixture
def sl_price_command() -> TelegramCommand:
    """Sample /sl BTC price 47000 command."""
    return TelegramCommand(
        command="sl",
        args=["BTC", "price", "47000"],
        chat_id="123456789",
        message_id=1,
        raw_text="/sl BTC price 47000",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def sl_pct_command() -> TelegramCommand:
    """Sample /sl BTC pct -5 command."""
    return TelegramCommand(
        command="sl",
        args=["BTC", "pct", "-5"],
        chat_id="123456789",
        message_id=2,
        raw_text="/sl BTC pct -5",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def sl_shorthand_price_command() -> TelegramCommand:
    """Sample /sl BTC 47000 command (shorthand price mode)."""
    return TelegramCommand(
        command="sl",
        args=["BTC", "47000"],
        chat_id="123456789",
        message_id=3,
        raw_text="/sl BTC 47000",
        raw_update={},
        user_id="111222333",
    )


@pytest.fixture
def sl_shorthand_pct_command() -> TelegramCommand:
    """Sample /sl BTC -5% command (shorthand percentage mode)."""
    return TelegramCommand(
        command="sl",
        args=["BTC", "-5%"],
        chat_id="123456789",
        message_id=4,
        raw_text="/sl BTC -5%",
        raw_update={},
        user_id="111222333",
    )


# ═══════════════════════════════════════════════════════════════════
# AC1: /sl COMMAND FORMAT TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSymbolNormalization:
    """Tests for symbol normalization."""
    
    def test_normalize_simple_symbol(self):
        """Test normalizing simple symbol like BTC."""
        assert _normalize_symbol("BTC") == "BTC"
        assert _normalize_symbol("btc") == "BTC"
        assert _normalize_symbol("Btc") == "BTC"
    
    def test_normalize_symbol_with_usdt_suffix(self):
        """Test normalizing symbol with USDT suffix."""
        assert _normalize_symbol("BTCUSDT") == "BTC"
        assert _normalize_symbol("btcusdt") == "BTC"
        assert _normalize_symbol("ETHUSDT") == "ETH"
    
    def test_normalize_symbol_with_usdc_suffix(self):
        """Test normalizing symbol with USDC suffix."""
        assert _normalize_symbol("BTCUSDC") == "BTC"
        assert _normalize_symbol("ETHUSDC") == "ETH"
    
    def test_normalize_backpack_format(self):
        """Test normalizing Backpack format like BTC_USDC_PERP."""
        assert _normalize_symbol("BTC_USDC_PERP") == "BTC"
        assert _normalize_symbol("ETH_USDC_PERP") == "ETH"
    
    def test_normalize_empty_symbol(self):
        """Test normalizing empty symbol."""
        assert _normalize_symbol("") == ""
        assert _normalize_symbol("  ") == ""


class TestParseValueWithMode:
    """Tests for value parsing with mode detection."""
    
    def test_parse_price_value(self):
        """Test parsing price value without % suffix."""
        value, mode, error = _parse_value_with_mode("50000")
        assert value == 50000.0
        assert mode == PriceMode.PRICE
        assert error is None
    
    def test_parse_percentage_value(self):
        """Test parsing percentage value with % suffix."""
        value, mode, error = _parse_value_with_mode("5%")
        assert value == 5.0
        assert mode == PriceMode.PERCENTAGE
        assert error is None
    
    def test_parse_negative_percentage(self):
        """Test parsing negative percentage."""
        value, mode, error = _parse_value_with_mode("-5%")
        assert value == -5.0
        assert mode == PriceMode.PERCENTAGE
        assert error is None
    
    def test_parse_decimal_value(self):
        """Test parsing decimal value."""
        value, mode, error = _parse_value_with_mode("50000.50")
        assert value == 50000.50
        assert mode == PriceMode.PRICE
        assert error is None
    
    def test_parse_invalid_value(self):
        """Test parsing invalid value."""
        value, mode, error = _parse_value_with_mode("abc")
        assert value is None
        assert error is not None


class TestParseSLArgs:
    """Tests for /sl command argument parsing (AC1)."""
    
    def test_parse_no_args_returns_error(self):
        """Test parsing with no arguments returns error."""
        result = _parse_sl_args([])
        assert result.error is not None
        assert "请指定" in result.error
    
    def test_parse_symbol_only_returns_error(self):
        """Test parsing symbol only returns error (missing value)."""
        result = _parse_sl_args(["BTC"])
        assert result.error is not None
        assert "请指定止损价格" in result.error
    
    def test_parse_price_mode(self):
        """Test parsing /sl SYMBOL price VALUE."""
        result = _parse_sl_args(["BTC", "price", "47000"])
        assert result.symbol == "BTC"
        assert result.sl_value == 47000.0
        assert result.sl_mode == PriceMode.PRICE
        assert result.error is None
    
    def test_parse_pct_mode(self):
        """Test parsing /sl SYMBOL pct VALUE."""
        result = _parse_sl_args(["BTC", "pct", "-5"])
        assert result.symbol == "BTC"
        assert result.sl_value == -5.0
        assert result.sl_mode == PriceMode.PERCENTAGE
        assert result.error is None
    
    def test_parse_shorthand_price(self):
        """Test parsing /sl SYMBOL VALUE (price mode)."""
        result = _parse_sl_args(["BTC", "47000"])
        assert result.symbol == "BTC"
        assert result.sl_value == 47000.0
        assert result.sl_mode == PriceMode.PRICE
        assert result.error is None
    
    def test_parse_shorthand_percentage(self):
        """Test parsing /sl SYMBOL VALUE% (percentage mode)."""
        result = _parse_sl_args(["BTC", "-5%"])
        assert result.symbol == "BTC"
        assert result.sl_value == -5.0
        assert result.sl_mode == PriceMode.PERCENTAGE
        assert result.error is None
    
    def test_parse_extra_args_returns_error(self):
        """Test parsing with extra arguments returns error."""
        result = _parse_sl_args(["BTC", "47000", "extra"])
        assert result.error is not None
        assert "参数过多" in result.error


# ═══════════════════════════════════════════════════════════════════
# AC2: /tp COMMAND FORMAT TESTS
# ═══════════════════════════════════════════════════════════════════

class TestParseTPArgs:
    """Tests for /tp command argument parsing (AC2)."""
    
    def test_parse_no_args_returns_error(self):
        """Test parsing with no arguments returns error."""
        result = _parse_tp_args([])
        assert result.error is not None
        assert "请指定" in result.error
    
    def test_parse_symbol_only_returns_error(self):
        """Test parsing symbol only returns error (missing value)."""
        result = _parse_tp_args(["BTC"])
        assert result.error is not None
        assert "请指定止盈价格" in result.error
    
    def test_parse_price_mode(self):
        """Test parsing /tp SYMBOL price VALUE."""
        result = _parse_tp_args(["BTC", "price", "55000"])
        assert result.symbol == "BTC"
        assert result.tp_value == 55000.0
        assert result.tp_mode == PriceMode.PRICE
        assert result.error is None
    
    def test_parse_pct_mode(self):
        """Test parsing /tp SYMBOL pct VALUE."""
        result = _parse_tp_args(["BTC", "pct", "10"])
        assert result.symbol == "BTC"
        assert result.tp_value == 10.0
        assert result.tp_mode == PriceMode.PERCENTAGE
        assert result.error is None
    
    def test_parse_shorthand_price(self):
        """Test parsing /tp SYMBOL VALUE (price mode)."""
        result = _parse_tp_args(["BTC", "55000"])
        assert result.symbol == "BTC"
        assert result.tp_value == 55000.0
        assert result.tp_mode == PriceMode.PRICE
        assert result.error is None
    
    def test_parse_shorthand_percentage(self):
        """Test parsing /tp SYMBOL VALUE% (percentage mode)."""
        result = _parse_tp_args(["BTC", "10%"])
        assert result.symbol == "BTC"
        assert result.tp_value == 10.0
        assert result.tp_mode == PriceMode.PERCENTAGE
        assert result.error is None


# ═══════════════════════════════════════════════════════════════════
# AC3: /tpsl COMBINED COMMAND TESTS
# ═══════════════════════════════════════════════════════════════════

class TestParseTPSLArgs:
    """Tests for /tpsl command argument parsing (AC3)."""
    
    def test_parse_no_args_returns_error(self):
        """Test parsing with no arguments returns error."""
        result = _parse_tpsl_args([])
        assert result.error is not None
        assert "请指定" in result.error
    
    def test_parse_missing_tp_returns_error(self):
        """Test parsing with missing TP value returns error."""
        result = _parse_tpsl_args(["BTC", "47000"])
        assert result.error is not None
        assert "请同时指定" in result.error
    
    def test_parse_price_mode_both(self):
        """Test parsing /tpsl SYMBOL SL_PRICE TP_PRICE."""
        result = _parse_tpsl_args(["BTC", "47000", "55000"])
        assert result.symbol == "BTC"
        assert result.sl_value == 47000.0
        assert result.sl_mode == PriceMode.PRICE
        assert result.tp_value == 55000.0
        assert result.tp_mode == PriceMode.PRICE
        assert result.error is None
    
    def test_parse_pct_mode_both(self):
        """Test parsing /tpsl SYMBOL SL_PCT TP_PCT."""
        result = _parse_tpsl_args(["BTC", "-5%", "10%"])
        assert result.symbol == "BTC"
        assert result.sl_value == -5.0
        assert result.sl_mode == PriceMode.PERCENTAGE
        assert result.tp_value == 10.0
        assert result.tp_mode == PriceMode.PERCENTAGE
        assert result.error is None
    
    def test_parse_mixed_mode_returns_error(self):
        """Test parsing with mixed modes returns error (AC3)."""
        result = _parse_tpsl_args(["BTC", "47000", "10%"])
        assert result.error is not None
        assert "相同模式" in result.error
    
    def test_parse_mixed_mode_reverse_returns_error(self):
        """Test parsing with mixed modes (reverse) returns error."""
        result = _parse_tpsl_args(["BTC", "-5%", "55000"])
        assert result.error is not None
        assert "相同模式" in result.error
    
    def test_parse_extra_args_returns_error(self):
        """Test parsing with extra arguments returns error."""
        result = _parse_tpsl_args(["BTC", "47000", "55000", "extra"])
        assert result.error is not None
        assert "参数过多" in result.error


# ═══════════════════════════════════════════════════════════════════
# AC4: NO POSITION SCENARIO TESTS
# ═══════════════════════════════════════════════════════════════════

class TestNoPositionScenario:
    """Tests for no position scenario (AC4)."""
    
    def test_sl_no_position_returns_success_with_message(self):
        """Test /sl with no position returns success with clear message."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions={},  # No positions
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "SL_NO_POSITION"
        assert "无" in result.message
    
    def test_tp_no_position_returns_success_with_message(self):
        """Test /tp with no position returns success with clear message."""
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "55000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp BTC 55000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions={},  # No positions
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "TP_NO_POSITION"
        assert "无" in result.message
    
    def test_tpsl_no_position_returns_success_with_message(self):
        """Test /tpsl with no position returns success with clear message."""
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "47000", "55000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl BTC 47000 55000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tpsl_command(
            cmd,
            positions={},  # No positions
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "TPSL_NO_POSITION"
        assert "无" in result.message


# ═══════════════════════════════════════════════════════════════════
# AC5: PRICE REASONABLENESS VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestCalculateTargetPrice:
    """Tests for target price calculation."""
    
    def test_price_mode_returns_value_directly(self):
        """Test price mode returns value directly."""
        result = _calculate_target_price(50000.0, 47000.0, PriceMode.PRICE)
        assert result == 47000.0
    
    def test_pct_mode_positive(self):
        """Test percentage mode with positive value."""
        # 50000 * (1 + 10/100) = 55000 (base price = entry price)
        result = _calculate_target_price(50000.0, 10.0, PriceMode.PERCENTAGE)
        assert result == pytest.approx(55000.0, rel=1e-9)
    
    def test_pct_mode_negative(self):
        """Test percentage mode with negative value."""
        # 50000 * (1 + (-5)/100) = 47500 (base price = entry price)
        result = _calculate_target_price(50000.0, -5.0, PriceMode.PERCENTAGE)
        assert result == 47500.0

    def test_pct_mode_uses_entry_price_as_base(self):
        """Percentage mode should use entry price as base, not current price.

        This test documents the intended semantics: when entry price and
        current price diverge, the percentage is applied to entry price
        (base_price argument), while current price is only used for
        reasonableness validation elsewhere.
        """
        # If entry price is 40000 and we set +10%, target should be 44000
        result = _calculate_target_price(40000.0, 10.0, PriceMode.PERCENTAGE)
        assert result == pytest.approx(44000.0, rel=1e-9)


class TestValidateSLPrice:
    """Tests for stop loss price validation (AC5)."""
    
    def test_long_sl_below_current_is_valid(self):
        """Test long position SL below current price is valid."""
        is_valid, error = _validate_sl_price(47000.0, 50000.0, "long")
        assert is_valid is True
        assert error is None
    
    def test_long_sl_above_current_is_invalid(self):
        """Test long position SL above current price is invalid."""
        is_valid, error = _validate_sl_price(52000.0, 50000.0, "long")
        assert is_valid is False
        assert error is not None
        assert "多仓止损价" in error
    
    def test_short_sl_above_current_is_valid(self):
        """Test short position SL above current price is valid."""
        is_valid, error = _validate_sl_price(3200.0, 3000.0, "short")
        assert is_valid is True
        assert error is None
    
    def test_short_sl_below_current_is_invalid(self):
        """Test short position SL below current price is invalid."""
        is_valid, error = _validate_sl_price(2800.0, 3000.0, "short")
        assert is_valid is False
        assert error is not None
        assert "空仓止损价" in error
    
    def test_sl_zero_price_is_invalid(self):
        """Test SL with zero price is invalid."""
        is_valid, error = _validate_sl_price(0.0, 50000.0, "long")
        assert is_valid is False
        assert error is not None


class TestValidateTPPrice:
    """Tests for take profit price validation (AC5)."""
    
    def test_long_tp_above_current_is_valid(self):
        """Test long position TP above current price is valid."""
        is_valid, error = _validate_tp_price(55000.0, 50000.0, "long")
        assert is_valid is True
        assert error is None
    
    def test_long_tp_below_current_is_invalid(self):
        """Test long position TP below current price is invalid."""
        is_valid, error = _validate_tp_price(48000.0, 50000.0, "long")
        assert is_valid is False
        assert error is not None
        assert "多仓止盈价" in error
    
    def test_short_tp_below_current_is_valid(self):
        """Test short position TP below current price is valid."""
        is_valid, error = _validate_tp_price(2700.0, 3000.0, "short")
        assert is_valid is True
        assert error is None
    
    def test_short_tp_above_current_is_invalid(self):
        """Test short position TP above current price is invalid."""
        is_valid, error = _validate_tp_price(3200.0, 3000.0, "short")
        assert is_valid is False
        assert error is not None
        assert "空仓止盈价" in error
    
    def test_tp_zero_price_is_invalid(self):
        """Test TP with zero price is invalid."""
        is_valid, error = _validate_tp_price(0.0, 50000.0, "long")
        assert is_valid is False
        assert error is not None


class TestCalculateDistancePct:
    """Tests for distance percentage calculation."""
    
    def test_positive_distance(self):
        """Test positive distance (target above current)."""
        result = _calculate_distance_pct(55000.0, 50000.0)
        assert result == pytest.approx(10.0, rel=0.01)
    
    def test_negative_distance(self):
        """Test negative distance (target below current)."""
        result = _calculate_distance_pct(47500.0, 50000.0)
        assert result == pytest.approx(-5.0, rel=0.01)
    
    def test_zero_current_price(self):
        """Test with zero current price returns 0."""
        result = _calculate_distance_pct(50000.0, 0.0)
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════
# AC6: STATE UPDATE AND USER FEEDBACK TESTS
# ═══════════════════════════════════════════════════════════════════

class TestSLCommandSuccess:
    """Tests for successful /sl command execution (AC6)."""
    
    def test_sl_price_mode_success(self, sample_long_position: Dict):
        """Test /sl with price mode succeeds."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "TELEGRAM_SL_UPDATE"
        assert "47" in result.message  # Contains new SL price
        assert "BTC" in result.message
    
    def test_sl_pct_mode_success(self, sample_long_position: Dict):
        """Test /sl with percentage mode succeeds when current price is available."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "-5%"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC -5%",
            raw_update={},
            user_id="111222333",
        )
        
        # Percentage mode requires current price
        def mock_get_price(coin: str) -> float:
            return 50000.0  # Current price
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=mock_get_price,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "TELEGRAM_SL_UPDATE"
    
    def test_sl_pct_mode_no_price_returns_error(self, sample_long_position: Dict):
        """Test /sl with percentage mode fails when no current price available."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "-5%"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC -5%",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,  # No price function
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "SL_NO_PRICE_FOR_PCT"
        assert "百分比模式" in result.message
    
    def test_sl_message_includes_old_value(self, sample_long_position: Dict):
        """Test /sl success message includes old SL value."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert "原止损" in result.message  # Contains old SL info


class TestTPCommandSuccess:
    """Tests for successful /tp command execution (AC6)."""
    
    def test_tp_price_mode_success(self, sample_long_position: Dict):
        """Test /tp with price mode succeeds."""
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "60000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp BTC 60000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "TELEGRAM_TP_UPDATE"
        assert "60" in result.message  # Contains new TP price
        assert "BTC" in result.message
    
    def test_tp_pct_mode_success(self, sample_long_position: Dict):
        """Test /tp with percentage mode succeeds when current price is available."""
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "10%"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp BTC 10%",
            raw_update={},
            user_id="111222333",
        )
        
        # Percentage mode requires current price
        def mock_get_price(coin: str) -> float:
            return 50000.0  # Current price
        
        result = handle_tp_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=mock_get_price,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "TELEGRAM_TP_UPDATE"
    
    def test_tp_pct_mode_no_price_returns_error(self, sample_long_position: Dict):
        """Test /tp with percentage mode fails when no current price available."""
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "10%"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp BTC 10%",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,  # No price function
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "TP_NO_PRICE_FOR_PCT"
        assert "百分比模式" in result.message


class TestTPSLCommandSuccess:
    """Tests for successful /tpsl command execution (AC6)."""
    
    def test_tpsl_price_mode_success(self, sample_long_position: Dict):
        """Test /tpsl with price mode succeeds."""
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "47000", "60000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl BTC 47000 60000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tpsl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "TELEGRAM_TPSL_UPDATE"
        assert "47" in result.message  # Contains new SL price
        assert "60" in result.message  # Contains new TP price
    
    def test_tpsl_pct_mode_success(self, sample_long_position: Dict):
        """Test /tpsl with percentage mode succeeds when current price is available."""
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "-5%", "10%"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl BTC -5% 10%",
            raw_update={},
            user_id="111222333",
        )
        
        # Percentage mode requires current price
        def mock_get_price(coin: str) -> float:
            return 50000.0  # Current price
        
        result = handle_tpsl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=mock_get_price,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "TELEGRAM_TPSL_UPDATE"
    
    def test_tpsl_pct_mode_no_price_returns_error(self, sample_long_position: Dict):
        """Test /tpsl with percentage mode fails when no current price available."""
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "-5%", "10%"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl BTC -5% 10%",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tpsl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,  # No price function
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "TPSL_NO_PRICE_FOR_PCT"
        assert "百分比模式" in result.message


# ═══════════════════════════════════════════════════════════════════
# AC7: ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Tests for error handling (AC7)."""
    
    def test_sl_parse_error_returns_failure(self):
        """Test /sl parse error returns failure with message."""
        cmd = TelegramCommand(
            command="sl",
            args=[],  # Missing symbol
            chat_id="123456789",
            message_id=1,
            raw_text="/sl",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions={},
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "SL_PARSE_ERROR"
    
    def test_tp_parse_error_returns_failure(self):
        """Test /tp parse error returns failure with message."""
        cmd = TelegramCommand(
            command="tp",
            args=[],  # Missing symbol
            chat_id="123456789",
            message_id=1,
            raw_text="/tp",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions={},
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "TP_PARSE_ERROR"
    
    def test_tpsl_parse_error_returns_failure(self):
        """Test /tpsl parse error returns failure with message."""
        cmd = TelegramCommand(
            command="tpsl",
            args=[],  # Missing symbol
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tpsl_command(
            cmd,
            positions={},
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "TPSL_PARSE_ERROR"
    
    def test_sl_validation_error_returns_failure(self, sample_long_position: Dict):
        """Test /sl validation error returns failure."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "52000"],  # SL above current price for long
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 52000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "SL_VALIDATION_FAILED"
    
    def test_tp_validation_error_returns_failure(self, sample_long_position: Dict):
        """Test /tp validation error returns failure."""
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "48000"],  # TP below current price for long
            chat_id="123456789",
            message_id=1,
            raw_text="/tp BTC 48000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "TP_VALIDATION_FAILED"
    
    def test_update_callback_failure_returns_failure(self, sample_long_position: Dict):
        """Test update callback failure returns failure."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        def failing_update(coin, sl, tp):
            return TPSLUpdateResult(success=False, error="Database error")
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=failing_update,
        )
        
        assert result.success is False
        assert result.action == "SL_UPDATE_FAILED"
    
    def test_update_callback_exception_returns_failure(self, sample_long_position: Dict):
        """Test update callback exception returns failure."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        def throwing_update(coin, sl, tp):
            raise Exception("Network error")
        
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=throwing_update,
        )
        
        assert result.success is False
        assert result.action == "SL_UPDATE_ERROR"


# ═══════════════════════════════════════════════════════════════════
# SHORT POSITION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestShortPositionCommands:
    """Tests for commands on short positions."""
    
    def test_sl_short_position_above_current(self, sample_short_position: Dict):
        """Test /sl on short position with SL above current price."""
        cmd = TelegramCommand(
            command="sl",
            args=["ETH", "3200"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl ETH 3200",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=sample_short_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
    
    def test_sl_short_position_below_current_fails(self, sample_short_position: Dict):
        """Test /sl on short position with SL below current price fails."""
        cmd = TelegramCommand(
            command="sl",
            args=["ETH", "2800"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl ETH 2800",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=sample_short_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "SL_VALIDATION_FAILED"
    
    def test_tp_short_position_below_current(self, sample_short_position: Dict):
        """Test /tp on short position with TP below current price."""
        cmd = TelegramCommand(
            command="tp",
            args=["ETH", "2700"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp ETH 2700",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions=sample_short_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
    
    def test_tp_short_position_above_current_fails(self, sample_short_position: Dict):
        """Test /tp on short position with TP above current price fails."""
        cmd = TelegramCommand(
            command="tp",
            args=["ETH", "3200"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp ETH 3200",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions=sample_short_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is False
        assert result.action == "TP_VALIDATION_FAILED"


# ═══════════════════════════════════════════════════════════════════
# KILL-SWITCH / DAILY LOSS LIMIT INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestKillSwitchIntegration:
    """Tests for Kill-Switch integration (AC8).
    
    /sl, /tp, /tpsl commands should work even when Kill-Switch is active,
    as they only modify TP/SL levels and don't increase risk exposure.
    """
    
    def test_sl_works_during_kill_switch(self, sample_long_position: Dict):
        """Test /sl works when Kill-Switch is active."""
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        # The /sl command itself doesn't check Kill-Switch status
        # because it's designed to work during Kill-Switch
        result = handle_sl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
    
    def test_tp_works_during_kill_switch(self, sample_long_position: Dict):
        """Test /tp works when Kill-Switch is active."""
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "60000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tp BTC 60000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tp_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True
    
    def test_tpsl_works_during_kill_switch(self, sample_long_position: Dict):
        """Test /tpsl works when Kill-Switch is active."""
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "47000", "60000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl BTC 47000 60000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tpsl_command(
            cmd,
            positions=sample_long_position,
            get_current_price_fn=None,
            update_tpsl_fn=None,
        )
        
        assert result.success is True
        assert result.state_changed is True


# ═══════════════════════════════════════════════════════════════════
# GET POSITIONS FOR TPSL TESTS
# ═══════════════════════════════════════════════════════════════════

class TestGetPositionsForTPSL:
    """Tests for get_positions_for_tpsl function."""
    
    def test_get_positions_from_local_snapshot(self):
        """Test getting positions from local snapshot."""
        local_positions = {
            "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0},
        }
        
        positions = get_positions_for_tpsl(
            account_snapshot_fn=None,
            positions_snapshot_fn=lambda: local_positions,
        )
        
        assert "BTC" in positions
        assert positions["BTC"]["side"] == "long"
    
    def test_get_positions_prefers_live_snapshot(self):
        """Test that live snapshot is preferred over local."""
        local_positions = {
            "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0},
        }
        
        live_snapshot = {
            "positions": [
                {
                    "symbol": "ETH_USDC_PERP",
                    "netQuantity": "5.0",
                    "entryPrice": "3000.0",
                },
            ],
        }
        
        positions = get_positions_for_tpsl(
            account_snapshot_fn=lambda: live_snapshot,
            positions_snapshot_fn=lambda: local_positions,
        )
        
        # Should have ETH from live snapshot, not BTC from local
        assert "ETH" in positions
        assert "BTC" not in positions
    
    def test_get_positions_falls_back_to_local_on_error(self):
        """Test fallback to local when live snapshot fails."""
        local_positions = {
            "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0},
        }
        
        def failing_snapshot():
            raise Exception("API error")
        
        positions = get_positions_for_tpsl(
            account_snapshot_fn=failing_snapshot,
            positions_snapshot_fn=lambda: local_positions,
        )
        
        assert "BTC" in positions


# ═══════════════════════════════════════════════════════════════════
# POSITION FINDING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestFindPosition:
    """Tests for position finding logic."""
    
    def test_find_position_direct_match(self, sample_positions: Dict):
        """Test finding position with direct match."""
        key, pos = _find_position_for_symbol("BTC", sample_positions)
        assert key == "BTC"
        assert pos is not None
        assert pos["side"] == "long"
    
    def test_find_position_case_insensitive(self, sample_positions: Dict):
        """Test finding position case-insensitively."""
        key, pos = _find_position_for_symbol("btc", sample_positions)
        assert key == "BTC"
        assert pos is not None
    
    def test_find_position_not_found(self, sample_positions: Dict):
        """Test finding position that doesn't exist."""
        key, pos = _find_position_for_symbol("XRP", sample_positions)
        assert key is None
        assert pos is None
    
    def test_find_position_empty_positions(self):
        """Test finding position in empty positions dict."""
        key, pos = _find_position_for_symbol("BTC", {})
        assert key is None
        assert pos is None


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: HANDLER WIRING
# ═══════════════════════════════════════════════════════════════════

class TestTPSLHandlerIntegration:
    """Integration tests for TP/SL command handler wiring."""
    
    def test_sl_handler_wiring_in_create_kill_resume_handlers(self):
        """Test that sl_handler is correctly wired in create_kill_resume_handlers."""
        from core.risk_control import RiskControlState
        from notifications.commands.handlers import create_kill_resume_handlers
        
        state = RiskControlState()
        
        handlers = create_kill_resume_handlers(
            state=state,
            positions_snapshot_fn=lambda: {
                "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0}
            },
            account_snapshot_fn=None,
            bot_token="test_token",
            chat_id="123456",
        )
        
        # Verify sl, tp, tpsl handlers exist
        assert "sl" in handlers
        assert "tp" in handlers
        assert "tpsl" in handlers
    
    def test_sl_handler_executes_successfully(self):
        """Test that sl_handler executes successfully."""
        from core.risk_control import RiskControlState
        from notifications.commands.handlers import create_kill_resume_handlers
        
        state = RiskControlState()
        
        sent_messages = []
        def mock_send_fn(text, parse_mode):
            sent_messages.append(text)
        
        handlers = create_kill_resume_handlers(
            state=state,
            positions_snapshot_fn=lambda: {
                "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0}
            },
            account_snapshot_fn=None,
            send_fn=mock_send_fn,
            bot_token="test_token",
            chat_id="123456",
        )
        
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        handlers["sl"](cmd)
        
        # Verify message was sent
        assert len(sent_messages) == 1
        assert "BTC" in sent_messages[0]
    
    def test_tp_handler_executes_successfully(self):
        """Test that tp_handler executes successfully."""
        from core.risk_control import RiskControlState
        from notifications.commands.handlers import create_kill_resume_handlers
        
        state = RiskControlState()
        
        sent_messages = []
        def mock_send_fn(text, parse_mode):
            sent_messages.append(text)
        
        handlers = create_kill_resume_handlers(
            state=state,
            positions_snapshot_fn=lambda: {
                "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0}
            },
            account_snapshot_fn=None,
            send_fn=mock_send_fn,
            bot_token="test_token",
            chat_id="123456",
        )
        
        cmd = TelegramCommand(
            command="tp",
            args=["BTC", "60000"],
            chat_id="123456",
            message_id=1,
            raw_text="/tp BTC 60000",
            raw_update={},
            user_id="111222333",
        )
        
        handlers["tp"](cmd)
        
        # Verify message was sent
        assert len(sent_messages) == 1
        assert "BTC" in sent_messages[0]
    
    def test_tpsl_handler_executes_successfully(self):
        """Test that tpsl_handler executes successfully."""
        from core.risk_control import RiskControlState
        from notifications.commands.handlers import create_kill_resume_handlers
        
        state = RiskControlState()
        
        sent_messages = []
        def mock_send_fn(text, parse_mode):
            sent_messages.append(text)
        
        handlers = create_kill_resume_handlers(
            state=state,
            positions_snapshot_fn=lambda: {
                "BTC": {"side": "long", "quantity": 1.0, "entry_price": 50000.0}
            },
            account_snapshot_fn=None,
            send_fn=mock_send_fn,
            bot_token="test_token",
            chat_id="123456",
        )
        
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "47000", "60000"],
            chat_id="123456",
            message_id=1,
            raw_text="/tpsl BTC 47000 60000",
            raw_update={},
            user_id="111222333",
        )
        
        handlers["tpsl"](cmd)
        
        # Verify message was sent
        assert len(sent_messages) == 1
        assert "BTC" in sent_messages[0]
    
    def test_update_tpsl_fn_actually_updates_state(self):
        """Test that update_tpsl_fn callback actually updates position state (AC6)."""
        from notifications.commands.tpsl import TPSLUpdateResult
        
        # Track state updates
        updated_positions = {}
        
        def mock_update_tpsl(coin: str, new_sl: Optional[float], new_tp: Optional[float]) -> TPSLUpdateResult:
            """Mock update function that tracks calls."""
            updated_positions[coin] = {"new_sl": new_sl, "new_tp": new_tp}
            return TPSLUpdateResult(
                success=True,
                old_sl=48000.0,
                new_sl=new_sl,
                old_tp=55000.0,
                new_tp=new_tp,
            )
        
        positions = {
            "BTC": {
                "side": "long",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "stop_loss": 48000.0,
                "profit_target": 55000.0,
            }
        }
        
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=positions,
            get_current_price_fn=None,
            update_tpsl_fn=mock_update_tpsl,
        )
        
        # Verify success
        assert result.success is True
        assert result.state_changed is True
        
        # Verify update_tpsl_fn was called with correct values
        assert "BTC" in updated_positions
        assert updated_positions["BTC"]["new_sl"] == 47000.0
        assert updated_positions["BTC"]["new_tp"] is None  # Only SL was updated
    
    def test_update_tpsl_fn_updates_both_sl_and_tp(self):
        """Test that /tpsl command updates both SL and TP via callback."""
        from notifications.commands.tpsl import TPSLUpdateResult
        
        updated_positions = {}
        
        def mock_update_tpsl(coin: str, new_sl: Optional[float], new_tp: Optional[float]) -> TPSLUpdateResult:
            updated_positions[coin] = {"new_sl": new_sl, "new_tp": new_tp}
            return TPSLUpdateResult(success=True)
        
        positions = {
            "BTC": {
                "side": "long",
                "quantity": 0.5,
                "entry_price": 50000.0,
                "stop_loss": 48000.0,
                "profit_target": 55000.0,
            }
        }
        
        cmd = TelegramCommand(
            command="tpsl",
            args=["BTC", "46000", "60000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/tpsl BTC 46000 60000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_tpsl_command(
            cmd,
            positions=positions,
            get_current_price_fn=None,
            update_tpsl_fn=mock_update_tpsl,
        )
        
        assert result.success is True
        assert "BTC" in updated_positions
        assert updated_positions["BTC"]["new_sl"] == 46000.0
        assert updated_positions["BTC"]["new_tp"] == 60000.0
    
    def test_update_tpsl_fn_failure_returns_error(self):
        """Test that update_tpsl_fn failure returns error to user."""
        from notifications.commands.tpsl import TPSLUpdateResult
        
        def mock_update_tpsl_fail(coin: str, new_sl: Optional[float], new_tp: Optional[float]) -> TPSLUpdateResult:
            return TPSLUpdateResult(success=False, error="Database connection failed")
        
        positions = {
            "BTC": {
                "side": "long",
                "quantity": 0.5,
                "entry_price": 50000.0,
            }
        }
        
        cmd = TelegramCommand(
            command="sl",
            args=["BTC", "47000"],
            chat_id="123456789",
            message_id=1,
            raw_text="/sl BTC 47000",
            raw_update={},
            user_id="111222333",
        )
        
        result = handle_sl_command(
            cmd,
            positions=positions,
            get_current_price_fn=None,
            update_tpsl_fn=mock_update_tpsl_fail,
        )
        
        assert result.success is False
        assert result.state_changed is False
        assert "Database connection failed" in result.message
