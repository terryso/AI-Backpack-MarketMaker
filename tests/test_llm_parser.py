"""Tests for llm/parser.py module."""
import json
import pytest

from llm.parser import recover_partial_decisions, parse_llm_json_decisions, _extract_signals_from_text


class TestRecoverPartialDecisions:
    """Tests for recover_partial_decisions function."""

    def test_recovers_complete_json(self):
        """Should recover decisions from complete JSON."""
        json_str = '{"BTC": {"signal": "entry", "side": "long"}, "ETH": {"signal": "hold"}}'
        result = recover_partial_decisions(json_str, ["BTC", "ETH"])
        
        assert result is not None
        decisions, missing = result
        assert "BTC" in decisions
        assert "ETH" in decisions
        assert decisions["BTC"]["signal"] == "entry"
        assert decisions["ETH"]["signal"] == "hold"
        assert missing == []

    def test_recovers_truncated_json(self):
        """Should recover partial decisions from truncated JSON."""
        # JSON truncated after BTC decision
        json_str = '{"BTC": {"signal": "entry", "side": "long"}, "ETH": {"signal": "ho'
        result = recover_partial_decisions(json_str, ["BTC", "ETH"])
        
        assert result is not None
        decisions, missing = result
        assert "BTC" in decisions
        assert decisions["BTC"]["signal"] == "entry"
        # ETH should be in missing and get default hold
        assert "ETH" in missing
        assert decisions["ETH"]["signal"] == "hold"

    def test_returns_none_when_no_recovery(self):
        """Should return None when no decisions can be recovered."""
        json_str = "completely invalid json without any coin markers"
        result = recover_partial_decisions(json_str, ["BTC", "ETH"])
        assert result is None

    def test_handles_missing_coins(self):
        """Should handle coins not present in JSON."""
        json_str = '{"BTC": {"signal": "entry"}}'
        result = recover_partial_decisions(json_str, ["BTC", "ETH", "SOL"])
        
        assert result is not None
        decisions, missing = result
        assert "BTC" in decisions
        assert "ETH" in missing
        assert "SOL" in missing
        # Missing coins should get default hold
        assert decisions["ETH"]["signal"] == "hold"
        assert decisions["SOL"]["signal"] == "hold"

    def test_handles_nested_objects(self):
        """Should handle nested JSON objects correctly."""
        json_str = '{"BTC": {"signal": "entry", "details": {"reason": "bullish"}}}'
        result = recover_partial_decisions(json_str, ["BTC"])
        
        assert result is not None
        decisions, missing = result
        assert decisions["BTC"]["signal"] == "entry"
        assert decisions["BTC"]["details"]["reason"] == "bullish"

    def test_handles_escaped_strings(self):
        """Should handle escaped strings in JSON."""
        json_str = '{"BTC": {"signal": "entry", "justification": "Price \\"broke out\\""}}'
        result = recover_partial_decisions(json_str, ["BTC"])
        
        assert result is not None
        decisions, _ = result
        assert "broke out" in decisions["BTC"]["justification"]

    def test_default_hold_has_zero_confidence(self):
        """Default hold decisions should have zero confidence."""
        json_str = '{"BTC": {"signal": "entry"}}'
        result = recover_partial_decisions(json_str, ["BTC", "ETH"])
        
        assert result is not None
        decisions, _ = result
        assert decisions["ETH"]["confidence"] == 0.0

    def test_removes_duplicate_missing_coins(self):
        """Should not have duplicate entries in missing list."""
        json_str = '{"BTC": {"signal": "entry"}}'
        result = recover_partial_decisions(json_str, ["BTC", "ETH", "ETH"])
        
        assert result is not None
        _, missing = result
        # ETH should appear only once
        assert missing.count("ETH") == 1


class TestParseLlmJsonDecisions:
    """Tests for parse_llm_json_decisions function."""

    @pytest.fixture
    def mock_notify_error(self):
        """Create a mock notify_error function."""
        calls = []
        def _notify(msg, metadata=None, log_error=True):
            calls.append({"msg": msg, "metadata": metadata, "log_error": log_error})
        _notify.calls = calls
        return _notify

    @pytest.fixture
    def mock_log_decisions(self):
        """Create a mock log_llm_decisions function."""
        calls = []
        def _log(decisions):
            calls.append(decisions)
        _log.calls = calls
        return _log

    @pytest.fixture
    def mock_recover(self):
        """Create a mock recover_partial_decisions function."""
        def _recover(json_str):
            return recover_partial_decisions(json_str, ["BTC", "ETH"])
        return _recover

    def test_parses_valid_json(self, mock_notify_error, mock_log_decisions, mock_recover):
        """Should parse valid JSON content."""
        content = '{"BTC": {"signal": "entry"}, "ETH": {"signal": "hold"}}'
        result = parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="stop",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover,
        )
        
        assert result is not None
        assert result["BTC"]["signal"] == "entry"
        assert result["ETH"]["signal"] == "hold"
        assert len(mock_log_decisions.calls) == 1

    def test_extracts_json_from_text(self, mock_notify_error, mock_log_decisions, mock_recover):
        """Should extract JSON from surrounding text."""
        content = 'Here is my analysis:\n{"BTC": {"signal": "entry"}}\nEnd of response.'
        result = parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="stop",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover,
        )
        
        assert result is not None
        assert result["BTC"]["signal"] == "entry"

    def test_handles_no_json(self, mock_notify_error, mock_log_decisions, mock_recover):
        """Should return None when no JSON found and no extractable signals."""
        content = "This response has no JSON at all"
        result = parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="stop",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover,
        )
        
        assert result is None
        # No error notification for non-JSON responses (just warning logged)
        assert len(mock_notify_error.calls) == 0

    def test_recovers_malformed_json(self, mock_notify_error, mock_log_decisions, mock_recover):
        """Should attempt recovery on malformed JSON."""
        # Valid BTC object but truncated ETH
        content = '{"BTC": {"signal": "entry"}, "ETH": {"signal": "ho'
        result = parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="length",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover,
        )
        
        assert result is not None
        assert result["BTC"]["signal"] == "entry"
        # ETH should be recovered with default hold
        assert result["ETH"]["signal"] == "hold"

    def test_notifies_on_recovery(self, mock_notify_error, mock_log_decisions, mock_recover):
        """Should notify when recovery is performed."""
        content = '{"BTC": {"signal": "entry"}, "ETH": {"signal": "ho'
        parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="length",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover,
        )
        
        assert len(mock_notify_error.calls) == 1
        assert "truncated" in mock_notify_error.calls[0]["msg"].lower()

    def test_notifies_decode_failure(self, mock_notify_error, mock_log_decisions):
        """Should notify on complete decode failure."""
        content = '{invalid json that cannot be recovered at all}'
        
        def mock_recover_fail(json_str):
            return None
        
        result = parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="stop",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover_fail,
        )
        
        assert result is None
        assert len(mock_notify_error.calls) == 1
        assert "decode failed" in mock_notify_error.calls[0]["msg"].lower()

    def test_includes_metadata_in_error(self, mock_notify_error, mock_log_decisions):
        """Should include metadata in error notifications for decode failures."""
        # Use malformed JSON that triggers decode error notification
        content = '{invalid json that cannot be recovered}'
        
        def mock_recover_fail(json_str):
            return None
        
        parse_llm_json_decisions(
            content,
            response_id="test-123",
            status_code=200,
            finish_reason="stop",
            notify_error=mock_notify_error,
            log_llm_decisions=mock_log_decisions,
            recover_partial_decisions=mock_recover_fail,
        )
        
        assert len(mock_notify_error.calls) == 1
        metadata = mock_notify_error.calls[0]["metadata"]
        assert metadata["response_id"] == "test-123"
        assert metadata["status_code"] == 200
        assert metadata["finish_reason"] == "stop"


class TestExtractSignalsFromText:
    """Tests for _extract_signals_from_text function."""

    def test_extracts_hold_signal(self):
        """Should extract hold signals from text."""
        content = "Based on my analysis, BTC: hold for now."
        result = _extract_signals_from_text(content)
        
        assert result is not None
        assert "BTC" in result
        assert result["BTC"]["signal"] == "hold"

    def test_extracts_entry_long_signal(self):
        """Should extract entry long signals."""
        content = "ETH looks bullish. ETH: entry long with target 4000."
        result = _extract_signals_from_text(content)
        
        assert result is not None
        assert "ETH" in result
        assert result["ETH"]["signal"] == "entry"
        assert result["ETH"]["side"] == "long"

    def test_extracts_entry_short_signal(self):
        """Should extract entry short signals."""
        content = "SOL is bearish. SOL: short position recommended."
        result = _extract_signals_from_text(content)
        
        assert result is not None
        assert "SOL" in result
        assert result["SOL"]["signal"] == "entry"
        assert result["SOL"]["side"] == "short"

    def test_extracts_close_signal(self):
        """Should extract close signals."""
        content = "Time to exit. BTC - close the position."
        result = _extract_signals_from_text(content)
        
        assert result is not None
        assert "BTC" in result
        assert result["BTC"]["signal"] == "close"

    def test_extracts_multiple_signals(self):
        """Should extract multiple signals from text."""
        content = "BTC: hold, ETH: long, SOL close position"
        result = _extract_signals_from_text(content)
        
        assert result is not None
        assert "BTC" in result
        assert result["BTC"]["signal"] == "hold"
        assert "ETH" in result
        assert result["ETH"]["signal"] == "entry"
        assert "SOL" in result
        assert result["SOL"]["signal"] == "close"

    def test_returns_none_for_no_signals(self):
        """Should return None when no signals found."""
        content = "The market is volatile today. No clear direction."
        result = _extract_signals_from_text(content)
        
        assert result is None

    def test_case_insensitive(self):
        """Should be case insensitive."""
        content = "btc HOLD, eth LONG"
        result = _extract_signals_from_text(content)
        
        assert result is not None
        assert "BTC" in result
        assert "ETH" in result
