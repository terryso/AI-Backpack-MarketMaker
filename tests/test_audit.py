"""Tests for audit command and AuditProvider interface."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from exchange.base import AuditData, AuditProvider
from notifications.commands.audit import (
    DEFAULT_EXCHANGE,
    EXCHANGE_DISPLAY_NAMES,
    SUPPORTED_EXCHANGES,
    _format_decimal,
    _get_audit_provider,
    _get_default_time_range,
    _parse_time_arg,
    format_audit_message,
    handle_audit_command,
)
from notifications.commands.base import TelegramCommand


class TestAuditData:
    """Tests for AuditData dataclass."""

    def test_creates_audit_data_with_defaults(self):
        """Should create AuditData with default values."""
        data = AuditData(backend="test_exchange")
        
        assert data.backend == "test_exchange"
        assert data.funding_total == Decimal("0")
        assert data.funding_by_symbol == {}
        assert data.settlement_total == Decimal("0")
        assert data.settlement_by_source == {}
        assert data.deposit_total == Decimal("0")
        assert data.withdrawal_total == Decimal("0")
        assert data.raw is None

    def test_creates_audit_data_with_values(self):
        """Should create AuditData with provided values."""
        data = AuditData(
            backend="backpack_futures",
            funding_total=Decimal("0.1238"),
            funding_by_symbol={"BTC_USDC_PERP": Decimal("0.0264")},
            settlement_total=Decimal("-25.0114"),
            settlement_by_source={"TradingFees": Decimal("-16.6288")},
            deposit_total=Decimal("100"),
            withdrawal_total=Decimal("-50"),
        )
        
        assert data.backend == "backpack_futures"
        assert data.funding_total == Decimal("0.1238")
        assert data.funding_by_symbol["BTC_USDC_PERP"] == Decimal("0.0264")
        assert data.settlement_total == Decimal("-25.0114")
        assert data.deposit_total == Decimal("100")
        assert data.withdrawal_total == Decimal("-50")

    def test_net_change_calculation(self):
        """Should calculate net change correctly."""
        data = AuditData(
            backend="test",
            funding_total=Decimal("10"),
            settlement_total=Decimal("-5"),
            deposit_total=Decimal("100"),
            withdrawal_total=Decimal("-20"),
        )
        
        expected = Decimal("10") + Decimal("-5") + Decimal("100") + Decimal("-20")
        assert data.net_change == expected
        assert data.net_change == Decimal("85")


class TestAuditProviderProtocol:
    """Tests for AuditProvider protocol."""

    def test_protocol_is_runtime_checkable(self):
        """AuditProvider should be runtime checkable."""
        class MockAuditProvider:
            def fetch_audit_data(self, start_utc: datetime, end_utc: datetime) -> AuditData:
                return AuditData(backend="mock")
        
        mock_provider = MockAuditProvider()
        assert isinstance(mock_provider, AuditProvider)

    def test_non_conforming_class_fails_check(self):
        """Non-conforming class should fail isinstance check."""
        class NotAnAuditProvider:
            def some_other_method(self):
                pass
        
        not_provider = NotAnAuditProvider()
        assert not isinstance(not_provider, AuditProvider)


class TestFormatDecimal:
    """Tests for _format_decimal helper."""

    def test_formats_positive_decimal(self):
        """Should format positive decimal correctly."""
        assert _format_decimal(Decimal("0.1238")) == "0.1238"

    def test_formats_negative_decimal(self):
        """Should format negative decimal correctly."""
        assert _format_decimal(Decimal("-25.0114")) == "-25.0114"

    def test_removes_trailing_zeros(self):
        """Should remove trailing zeros."""
        assert _format_decimal(Decimal("10.5000")) == "10.5"
        assert _format_decimal(Decimal("100.0000")) == "100"

    def test_formats_zero(self):
        """Should format zero correctly."""
        assert _format_decimal(Decimal("0")) == "0"

    def test_respects_places_parameter(self):
        """Should respect places parameter."""
        assert _format_decimal(Decimal("1.23456789"), places=2) == "1.23"


class TestParseTimeArg:
    """Tests for _parse_time_arg helper."""

    def test_parses_hhmm_format(self):
        """Should parse HH:MM format as today's time."""
        local_tz = timezone.utc
        result = _parse_time_arg("09:30", local_tz)
        
        assert result is not None
        assert result.hour == 9
        assert result.minute == 30

    def test_parses_iso_date(self):
        """Should parse YYYY-MM-DD format."""
        local_tz = timezone.utc
        result = _parse_time_arg("2025-12-05", local_tz)
        
        assert result is not None
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 5

    def test_parses_iso_datetime(self):
        """Should parse YYYY-MM-DD HH:MM format."""
        local_tz = timezone.utc
        result = _parse_time_arg("2025-12-05 14:30", local_tz)
        
        assert result is not None
        assert result.year == 2025
        assert result.hour == 14
        assert result.minute == 30

    def test_returns_none_for_invalid_format(self):
        """Should return None for invalid format."""
        local_tz = timezone.utc
        result = _parse_time_arg("invalid", local_tz)
        
        assert result is None


class TestGetDefaultTimeRange:
    """Tests for _get_default_time_range helper."""

    def test_returns_today_range(self):
        """Should return today 00:00 to now."""
        local_tz = timezone.utc
        start, end = _get_default_time_range(local_tz)
        
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0
        assert end > start


class TestFormatAuditMessage:
    """Tests for format_audit_message function."""

    def test_formats_basic_audit_data(self):
        """Should format basic audit data correctly."""
        data = AuditData(
            backend="backpack_futures",
            funding_total=Decimal("0.1238"),
            funding_by_symbol={"BTC_USDC_PERP": Decimal("0.0264")},
            settlement_total=Decimal("-25.0114"),
            settlement_by_source={"TradingFees": Decimal("-16.6288")},
        )
        
        start_utc = datetime(2025, 12, 5, 0, 0, tzinfo=timezone.utc)
        end_utc = datetime(2025, 12, 5, 18, 21, tzinfo=timezone.utc)
        
        message = format_audit_message(
            data,
            start_utc=start_utc,
            end_utc=end_utc,
            local_tz=timezone.utc,
        )
        
        assert "Backpack" in message
        assert "资金变动分析" in message
        assert "资金费" in message
        assert "结算" in message

    def test_includes_exchange_name(self):
        """Should include exchange display name."""
        data = AuditData(backend="backpack_futures")
        
        message = format_audit_message(
            data,
            start_utc=datetime.now(tz=timezone.utc),
            end_utc=datetime.now(tz=timezone.utc),
            local_tz=timezone.utc,
        )
        
        assert "Backpack" in message


class TestGetAuditProvider:
    """Tests for _get_audit_provider function."""

    @patch.dict("os.environ", {
        "BACKPACK_API_PUBLIC_KEY": "test_key",
        "BACKPACK_API_SECRET_SEED": "dGVzdF9zZWVkX3RoYXRfaXNfMzJfYnl0ZXNfbG9uZw==",  # base64 encoded 32-byte seed
    })
    def test_raises_for_invalid_backpack_seed(self):
        """Should raise for invalid Backpack API seed."""
        # The seed is valid base64 but not a valid ED25519 seed
        with pytest.raises(ValueError):
            _get_audit_provider("backpack")

    @patch.dict("os.environ", {
        "BACKPACK_API_PUBLIC_KEY": "",
        "BACKPACK_API_SECRET_SEED": "",
    })
    def test_raises_for_unconfigured_backpack(self):
        """Should raise ValueError for unconfigured Backpack."""
        with pytest.raises(ValueError, match="Backpack API 未配置"):
            _get_audit_provider("backpack")

    def test_raises_for_unsupported_exchange(self):
        """Should raise ValueError for unsupported exchange."""
        with pytest.raises(ValueError, match="不支持 audit 功能"):
            _get_audit_provider("unknown_exchange")


class TestHandleAuditCommand:
    """Tests for handle_audit_command function."""

    def _make_cmd(self, args: list[str] | None = None) -> TelegramCommand:
        """Create a TelegramCommand for testing."""
        return TelegramCommand(
            command="audit",
            args=args or [],
            chat_id="123",
            message_id=1,
            raw_text="/audit",
        )

    @patch.dict("os.environ", {
        "BACKPACK_API_PUBLIC_KEY": "",
        "BACKPACK_API_SECRET_SEED": "",
    })
    def test_returns_error_for_unconfigured_exchange(self):
        """Should return error when exchange is not configured."""
        cmd = self._make_cmd()
        result = handle_audit_command(cmd, exchange="backpack")
        
        assert result.success is False
        assert "未配置" in result.message

    def test_returns_error_for_invalid_time_format(self):
        """Should return error for invalid time format."""
        cmd = self._make_cmd(["invalid_time"])
        result = handle_audit_command(cmd)
        
        assert result.success is False
        assert "无效的时间格式" in result.message

    def test_returns_error_for_invalid_time_range(self):
        """Should return error when end time is before start time."""
        cmd = self._make_cmd(["18:00", "09:00"])
        result = handle_audit_command(cmd)
        
        assert result.success is False
        assert "结束时间必须晚于开始时间" in result.message

    @patch("notifications.commands.audit._get_audit_provider")
    def test_calls_provider_fetch_audit_data(self, mock_get_provider):
        """Should call provider.fetch_audit_data with correct arguments."""
        mock_provider = MagicMock()
        mock_provider.fetch_audit_data.return_value = AuditData(backend="backpack_futures")
        mock_get_provider.return_value = mock_provider
        
        cmd = self._make_cmd()
        result = handle_audit_command(cmd, exchange="backpack")
        
        assert result.success is True
        mock_provider.fetch_audit_data.assert_called_once()

    @patch("notifications.commands.audit._get_audit_provider")
    def test_handles_provider_exception(self, mock_get_provider):
        """Should handle exception from provider gracefully."""
        mock_provider = MagicMock()
        mock_provider.fetch_audit_data.side_effect = Exception("API error")
        mock_get_provider.return_value = mock_provider
        
        cmd = self._make_cmd()
        result = handle_audit_command(cmd, exchange="backpack")
        
        assert result.success is False
        assert "审计数据失败" in result.message


class TestConstants:
    """Tests for module constants."""

    def test_supported_exchanges_includes_backpack(self):
        """SUPPORTED_EXCHANGES should include backpack."""
        assert "backpack" in SUPPORTED_EXCHANGES

    def test_default_exchange_is_supported(self):
        """DEFAULT_EXCHANGE should be one of SUPPORTED_EXCHANGES."""
        assert DEFAULT_EXCHANGE in SUPPORTED_EXCHANGES

    def test_exchange_display_names_has_backpack(self):
        """EXCHANGE_DISPLAY_NAMES should have backpack."""
        assert "backpack" in EXCHANGE_DISPLAY_NAMES
        assert EXCHANGE_DISPLAY_NAMES["backpack"] == "Backpack"
