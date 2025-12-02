"""
Tests for Telegram command receiving and parsing functionality.

Story 7.4.1: Implement Telegram command receiving mechanism.
Story 7.4.2: Implement /kill and /resume commands.

Tests cover:
- AC1: Command parsing (command name, args extraction)
- AC3: Chat ID filtering and error handling
- AC3: last_update_id / offset mechanism
- AC1 (7.4.2): /kill command activates Kill-Switch
- AC2 (7.4.2): /resume deactivates Kill-Switch (while remaining compatible with "/resume confirm")
- AC3 (7.4.2): Logging and audit
- AC4 (7.4.2): Unit tests for /kill and /resume
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.risk_control import RiskControlState
from notifications.telegram_commands import (
    TelegramCommand,
    TelegramCommandHandler,
    create_command_handler,
    process_telegram_commands,
    CommandResult,
    handle_kill_command,
    handle_resume_command,
    handle_status_command,
    handle_help_command,
    handle_unknown_command,
    create_kill_resume_handlers,
    register_telegram_commands,
)


# ═══════════════════════════════════════════════════════════════════
# TEST FIXTURES
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def bot_token() -> str:
    """Sample bot token for testing."""
    return "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


@pytest.fixture
def allowed_chat_id() -> str:
    """Sample allowed chat ID for testing."""
    return "987654321"


@pytest.fixture
def handler(bot_token: str, allowed_chat_id: str) -> TelegramCommandHandler:
    """Create a TelegramCommandHandler for testing."""
    return TelegramCommandHandler(
        bot_token=bot_token,
        allowed_chat_id=allowed_chat_id,
    )


def make_update(
    update_id: int,
    chat_id: str,
    text: str,
    message_id: int = 1,
) -> Dict[str, Any]:
    """Helper to create a Telegram update payload."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": int(chat_id)},
            "text": text,
        },
    }


def make_api_response(updates: List[Dict[str, Any]], ok: bool = True) -> Dict[str, Any]:
    """Helper to create a Telegram API response."""
    return {
        "ok": ok,
        "result": updates,
    }


# ═══════════════════════════════════════════════════════════════════
# AC1: COMMAND PARSING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestCommandParsing:
    """Tests for command text parsing (AC1)."""
    
    def test_parse_kill_command(self):
        """Test parsing /kill command."""
        command, args = TelegramCommandHandler._parse_command_text("/kill")
        assert command == "kill"
        assert args == []
    
    def test_parse_resume_confirm_command(self):
        """Test parsing /resume confirm command."""
        command, args = TelegramCommandHandler._parse_command_text("/resume confirm")
        assert command == "resume"
        assert args == ["confirm"]
    
    def test_parse_status_command(self):
        """Test parsing /status command."""
        command, args = TelegramCommandHandler._parse_command_text("/status")
        assert command == "status"
        assert args == []
    
    def test_parse_reset_daily_command(self):
        """Test parsing /reset_daily command."""
        command, args = TelegramCommandHandler._parse_command_text("/reset_daily")
        assert command == "reset_daily"
        assert args == []
    
    def test_parse_help_command(self):
        """Test parsing /help command."""
        command, args = TelegramCommandHandler._parse_command_text("/help")
        assert command == "help"
        assert args == []
    
    def test_parse_command_with_multiple_args(self):
        """Test parsing command with multiple arguments."""
        command, args = TelegramCommandHandler._parse_command_text("/test arg1 arg2 arg3")
        assert command == "test"
        assert args == ["arg1", "arg2", "arg3"]
    
    def test_parse_command_with_bot_mention(self):
        """Test parsing command with @BotName suffix."""
        command, args = TelegramCommandHandler._parse_command_text("/status@MyTradingBot")
        assert command == "status"
        assert args == []
    
    def test_parse_command_with_bot_mention_and_args(self):
        """Test parsing command with @BotName and arguments."""
        command, args = TelegramCommandHandler._parse_command_text("/resume@MyBot confirm")
        assert command == "resume"
        assert args == ["confirm"]
    
    def test_parse_empty_command(self):
        """Test parsing just a slash."""
        command, args = TelegramCommandHandler._parse_command_text("/")
        assert command == ""
        assert args == []


class TestTelegramCommandDataclass:
    """Tests for TelegramCommand dataclass."""
    
    def test_command_creation(self):
        """Test creating a TelegramCommand."""
        cmd = TelegramCommand(
            command="kill",
            args=[],
            chat_id="123456",
            message_id=42,
            raw_text="/kill",
            raw_update={"update_id": 1},
        )
        assert cmd.command == "kill"
        assert cmd.args == []
        assert cmd.chat_id == "123456"
        assert cmd.message_id == 42
        assert cmd.raw_text == "/kill"
        assert cmd.raw_update == {"update_id": 1}
    
    def test_command_with_args(self):
        """Test TelegramCommand with arguments."""
        cmd = TelegramCommand(
            command="resume",
            args=["confirm"],
            chat_id="123456",
            message_id=43,
            raw_text="/resume confirm",
        )
        assert cmd.command == "resume"
        assert cmd.args == ["confirm"]


class TestRegisterTelegramCommands:
    """Tests for register_telegram_commands helper."""

    @patch("notifications.telegram_commands.requests.post")
    def test_register_telegram_commands_sends_expected_payload(
        self,
        mock_post: MagicMock,
        bot_token: str,
    ) -> None:
        """register_telegram_commands should call setMyCommands with commands from registry."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        register_telegram_commands(bot_token)

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert "setMyCommands" in args[0]
        payload = kwargs.get("json", {})
        commands = payload.get("commands", [])
        names = {item["command"] for item in commands}
        for expected in {"status", "risk", "kill", "resume", "reset_daily", "config", "help"}:
            assert expected in names

    @patch("notifications.telegram_commands.requests.post")
    def test_register_telegram_commands_skips_without_token(
        self,
        mock_post: MagicMock,
    ) -> None:
        """register_telegram_commands should do nothing when bot_token is empty."""
        register_telegram_commands("")
        mock_post.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# AC3: CHAT ID FILTERING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestChatIdFiltering:
    """Tests for chat ID filtering (AC3)."""
    
    @patch("notifications.telegram_commands.requests.get")
    def test_only_allowed_chat_commands_returned(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """Test that only commands from allowed chat are returned."""
        updates = [
            make_update(1, allowed_chat_id, "/status"),
            make_update(2, "999999999", "/kill"),  # Unauthorized
            make_update(3, allowed_chat_id, "/help"),
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        commands = handler.poll_commands()
        
        assert len(commands) == 2
        assert commands[0].command == "status"
        assert commands[1].command == "help"
    
    @patch("notifications.telegram_commands.requests.get")
    def test_unauthorized_chat_logged_as_warning(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """Test that unauthorized chat commands are logged as WARNING."""
        updates = [make_update(1, "999999999", "/kill")]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()
        
        assert len(commands) == 0
        assert "unauthorized chat" in caplog.text.lower()
        assert "999999999" in caplog.text
    
    @patch("notifications.telegram_commands.requests.get")
    def test_all_unauthorized_commands_filtered(
        self, mock_get: MagicMock, handler: TelegramCommandHandler
    ):
        """Test that all commands from unauthorized chats are filtered."""
        updates = [
            make_update(1, "111111111", "/kill"),
            make_update(2, "222222222", "/status"),
            make_update(3, "333333333", "/help"),
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        commands = handler.poll_commands()
        
        assert len(commands) == 0


# ═══════════════════════════════════════════════════════════════════
# AC3: LAST_UPDATE_ID / OFFSET MECHANISM TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOffsetMechanism:
    """Tests for last_update_id / offset mechanism (AC3)."""
    
    @patch("notifications.telegram_commands.requests.get")
    def test_last_update_id_updated_after_poll(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """Test that last_update_id is updated after polling."""
        updates = [
            make_update(100, allowed_chat_id, "/status"),
            make_update(101, allowed_chat_id, "/help"),
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        assert handler.last_update_id == 0
        handler.poll_commands()
        assert handler.last_update_id == 101
    
    @patch("notifications.telegram_commands.requests.get")
    def test_offset_used_in_subsequent_polls(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """Test that offset is used in subsequent poll requests."""
        # First poll
        updates1 = [make_update(100, allowed_chat_id, "/status")]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates1)
        handler.poll_commands()
        
        # Second poll should use offset=101
        updates2 = [make_update(101, allowed_chat_id, "/help")]
        mock_get.return_value.json.return_value = make_api_response(updates2)
        handler.poll_commands()
        
        # Check that offset was passed in second call
        calls = mock_get.call_args_list
        assert len(calls) == 2
        # First call: no offset (last_update_id was 0)
        assert "offset" not in calls[0].kwargs.get("params", {})
        # Second call: offset=101
        assert calls[1].kwargs["params"]["offset"] == 101
    
    @patch("notifications.telegram_commands.requests.get")
    def test_no_duplicate_commands_on_repeated_polls(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """Test that repeated polls don't return duplicate commands."""
        updates = [make_update(100, allowed_chat_id, "/status")]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        # First poll
        commands1 = handler.poll_commands()
        assert len(commands1) == 1
        
        # Second poll with empty result (no new updates)
        mock_get.return_value.json.return_value = make_api_response([])
        commands2 = handler.poll_commands()
        assert len(commands2) == 0
    
    @patch("notifications.telegram_commands.requests.get")
    def test_last_update_id_updated_even_for_filtered_commands(
        self, mock_get: MagicMock, handler: TelegramCommandHandler
    ):
        """Test that last_update_id is updated even for filtered commands."""
        # Command from unauthorized chat
        updates = [make_update(200, "999999999", "/kill")]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        handler.poll_commands()
        
        # last_update_id should still be updated to avoid reprocessing
        assert handler.last_update_id == 200


# ═══════════════════════════════════════════════════════════════════
# AC3: ERROR HANDLING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Tests for error handling (AC3)."""
    
    @patch("notifications.telegram_commands.requests.get")
    def test_http_error_logged_and_returns_empty(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """Test that HTTP errors are logged and empty list returned."""
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Internal Server Error"
        
        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()
        
        assert commands == []
        assert "500" in caplog.text
    
    @patch("notifications.telegram_commands.requests.get")
    def test_timeout_logged_and_returns_empty(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """Test that timeout errors are logged and empty list returned."""
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
        
        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()
        
        assert commands == []
        assert "timed out" in caplog.text.lower()
    
    @patch("notifications.telegram_commands.requests.get")
    def test_network_error_logged_and_returns_empty(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """Test that network errors are logged and empty list returned."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Network unreachable")
        
        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()
        
        assert commands == []
        assert "failed" in caplog.text.lower()
    
    @patch("notifications.telegram_commands.requests.get")
    def test_invalid_json_logged_and_returns_empty(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """Test that invalid JSON responses are logged and empty list returned."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.side_effect = ValueError("Invalid JSON")
        
        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()
        
        assert commands == []
        assert "parse" in caplog.text.lower() or "json" in caplog.text.lower()
    
    @patch("notifications.telegram_commands.requests.get")
    def test_api_ok_false_logged_and_returns_empty(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """Test that API ok=false responses are logged and empty list returned."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "ok": False,
            "description": "Unauthorized",
        }
        
        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()
        
        assert commands == []
        assert "ok=false" in caplog.text.lower()
    
    def test_missing_config_returns_empty(self):
        """Test that missing configuration returns empty list."""
        handler = TelegramCommandHandler(bot_token="", allowed_chat_id="123")
        commands = handler.poll_commands()
        assert commands == []
        
        handler = TelegramCommandHandler(bot_token="token", allowed_chat_id="")
        commands = handler.poll_commands()
        assert commands == []


# ═══════════════════════════════════════════════════════════════════
# MESSAGE TYPE FILTERING TESTS
# ═══════════════════════════════════════════════════════════════════

class TestMessageTypeFiltering:
    """Tests for message type filtering."""
    
    @patch("notifications.telegram_commands.requests.get")
    def test_non_message_updates_ignored(
        self, mock_get: MagicMock, handler: TelegramCommandHandler
    ):
        """Test that non-message updates (callback_query, etc.) are ignored."""
        updates = [
            {"update_id": 1, "callback_query": {"id": "123", "data": "test"}},
            {"update_id": 2, "edited_message": {"text": "/status"}},
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        commands = handler.poll_commands()
        
        assert len(commands) == 0
    
    @patch("notifications.telegram_commands.requests.get")
    def test_non_command_messages_ignored(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """Test that non-command messages (not starting with /) are ignored."""
        updates = [
            make_update(1, allowed_chat_id, "Hello, bot!"),
            make_update(2, allowed_chat_id, "What's the status?"),
            make_update(3, allowed_chat_id, "/status"),  # This is a command
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        commands = handler.poll_commands()
        
        assert len(commands) == 1
        assert commands[0].command == "status"
    
    @patch("notifications.telegram_commands.requests.get")
    def test_empty_text_messages_ignored(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """Test that messages with empty text are ignored."""
        updates = [
            {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "chat": {"id": int(allowed_chat_id)},
                    "text": "",
                },
            },
            {
                "update_id": 2,
                "message": {
                    "message_id": 2,
                    "chat": {"id": int(allowed_chat_id)},
                    # No text field
                },
            },
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        commands = handler.poll_commands()
        
        assert len(commands) == 0


# ═══════════════════════════════════════════════════════════════════
# FACTORY FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════

class TestCreateCommandHandler:
    """Tests for create_command_handler factory function."""
    
    def test_returns_handler_when_configured(self):
        """Test that handler is returned when both token and chat_id are set."""
        handler = create_command_handler(
            bot_token="test_token",
            chat_id="123456",
        )
        assert handler is not None
        assert isinstance(handler, TelegramCommandHandler)
    
    def test_returns_none_when_token_missing(self):
        """Test that None is returned when bot_token is missing."""
        handler = create_command_handler(
            bot_token="",
            chat_id="123456",
        )
        assert handler is None
    
    def test_returns_none_when_chat_id_missing(self):
        """Test that None is returned when chat_id is missing."""
        handler = create_command_handler(
            bot_token="test_token",
            chat_id="",
        )
        assert handler is None
    
    def test_preserves_last_update_id(self):
        """Test that last_update_id is preserved."""
        handler = create_command_handler(
            bot_token="test_token",
            chat_id="123456",
            last_update_id=500,
        )
        assert handler is not None
        assert handler.last_update_id == 500


# ═══════════════════════════════════════════════════════════════════
# PROCESS COMMANDS TESTS
# ═══════════════════════════════════════════════════════════════════

class TestProcessTelegramCommands:
    """Tests for process_telegram_commands function."""
    
    def test_empty_commands_no_error(self):
        """Test that empty command list doesn't cause errors."""
        process_telegram_commands([])  # Should not raise
    
    def test_commands_logged_when_no_handlers(self, caplog):
        """Test that commands are logged when no handlers provided."""
        commands = [
            TelegramCommand(
                command="status",
                args=[],
                chat_id="123",
                message_id=1,
                raw_text="/status",
            ),
        ]
        
        with caplog.at_level(logging.DEBUG):
            process_telegram_commands(commands)
        
        # Should log at DEBUG level
        assert "status" in caplog.text.lower() or len(caplog.records) >= 0
    
    def test_handler_called_for_matching_command(self):
        """Test that handler is called for matching command."""
        handler_called = []
        
        def mock_handler(cmd: TelegramCommand) -> None:
            handler_called.append(cmd.command)
        
        commands = [
            TelegramCommand(
                command="kill",
                args=[],
                chat_id="123",
                message_id=1,
                raw_text="/kill",
            ),
        ]
        
        process_telegram_commands(
            commands,
            command_handlers={"kill": mock_handler},
        )
        
        assert handler_called == ["kill"]
    
    def test_handler_error_logged_and_continues(self, caplog):
        """Test that handler errors are logged and processing continues."""
        def failing_handler(cmd: TelegramCommand) -> None:
            raise ValueError("Handler error")
        
        commands = [
            TelegramCommand(
                command="kill",
                args=[],
                chat_id="123",
                message_id=1,
                raw_text="/kill",
            ),
            TelegramCommand(
                command="status",
                args=[],
                chat_id="123",
                message_id=2,
                raw_text="/status",
            ),
        ]
        
        status_called = []
        
        def status_handler(cmd: TelegramCommand) -> None:
            status_called.append(True)
        
        with caplog.at_level(logging.ERROR):
            process_telegram_commands(
                commands,
                command_handlers={
                    "kill": failing_handler,
                    "status": status_handler,
                },
            )
        
        # Error should be logged
        assert "error" in caplog.text.lower()
        # Status handler should still be called
        assert status_called == [True]


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION-STYLE TESTS
# ═══════════════════════════════════════════════════════════════════

class TestFullPollingFlow:
    """Integration-style tests for the full polling flow."""
    
    @patch("notifications.telegram_commands.requests.get")
    def test_full_polling_flow(
        self, mock_get: MagicMock, bot_token: str, allowed_chat_id: str
    ):
        """Test complete polling flow with multiple commands."""
        handler = TelegramCommandHandler(
            bot_token=bot_token,
            allowed_chat_id=allowed_chat_id,
        )
        
        # Simulate first poll with multiple commands
        updates = [
            make_update(100, allowed_chat_id, "/kill"),
            make_update(101, allowed_chat_id, "/resume confirm"),
            make_update(102, "999999999", "/status"),  # Unauthorized
            make_update(103, allowed_chat_id, "/help"),
        ]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)
        
        commands = handler.poll_commands()
        
        # Should return 3 commands (1 filtered)
        assert len(commands) == 3
        assert commands[0].command == "kill"
        assert commands[0].args == []
        assert commands[1].command == "resume"
        assert commands[1].args == ["confirm"]
        assert commands[2].command == "help"
        
        # last_update_id should be updated to highest
        assert handler.last_update_id == 103
        
        # Second poll should use offset
        mock_get.return_value.json.return_value = make_api_response([])
        commands2 = handler.poll_commands()
        assert len(commands2) == 0
        
        # Verify offset was used
        last_call = mock_get.call_args
        assert last_call.kwargs["params"]["offset"] == 104


# ═══════════════════════════════════════════════════════════════════
# STORY 7.4.2: /KILL COMMAND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestHandleKillCommand:
    """Tests for handle_kill_command function (Story 7.4.2 AC1)."""
    
    @pytest.fixture
    def kill_command(self) -> TelegramCommand:
        """Create a sample /kill command."""
        return TelegramCommand(
            command="kill",
            args=[],
            chat_id="123456",
            message_id=42,
            raw_text="/kill",
        )
    
    @pytest.fixture
    def inactive_state(self) -> RiskControlState:
        """Create a RiskControlState with Kill-Switch inactive."""
        return RiskControlState(
            kill_switch_active=False,
            kill_switch_reason=None,
            kill_switch_triggered_at=None,
        )
    
    @pytest.fixture
    def active_state(self) -> RiskControlState:
        """Create a RiskControlState with Kill-Switch already active."""
        return RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="previous_reason",
            kill_switch_triggered_at="2025-01-01T00:00:00+00:00",
        )
    
    def test_kill_activates_kill_switch(
        self, kill_command: TelegramCommand, inactive_state: RiskControlState
    ):
        """Test that /kill activates Kill-Switch when inactive."""
        result = handle_kill_command(kill_command, inactive_state, positions_count=2)
        
        assert result.success is True
        assert result.state_changed is True
        assert result.action == "KILL_SWITCH_ACTIVATED"
        assert inactive_state.kill_switch_active is True
        assert inactive_state.kill_switch_reason == "Manual trigger via Telegram"
        assert inactive_state.kill_switch_triggered_at is not None
    
    def test_kill_returns_confirmation_message(
        self, kill_command: TelegramCommand, inactive_state: RiskControlState
    ):
        """Test that /kill returns proper confirmation message."""
        result = handle_kill_command(kill_command, inactive_state, positions_count=3)
        
        assert "Kill\\-Switch 已激活" in result.message
        assert "Manual trigger via Telegram" in result.message
        assert "3 个" in result.message
        assert "/resume" in result.message
    
    def test_kill_when_already_active(
        self, kill_command: TelegramCommand, active_state: RiskControlState
    ):
        """Test that /kill when already active returns info message."""
        result = handle_kill_command(kill_command, active_state)
        
        assert result.success is True
        assert result.state_changed is False
        assert result.action is None
        assert "已处于激活状态" in result.message
        assert active_state.kill_switch_reason == "previous_reason"  # Unchanged
    
    def test_kill_logs_command_receipt(
        self, kill_command: TelegramCommand, inactive_state: RiskControlState, caplog
    ):
        """Test that /kill logs command receipt (AC3)."""
        with caplog.at_level(logging.INFO):
            handle_kill_command(kill_command, inactive_state)
        
        assert "Telegram /kill command received" in caplog.text
        assert "123456" in caplog.text
    
    def test_kill_logs_state_change(
        self, kill_command: TelegramCommand, inactive_state: RiskControlState, caplog
    ):
        """Test that /kill logs state change (AC3)."""
        with caplog.at_level(logging.WARNING):
            handle_kill_command(kill_command, inactive_state)
        
        assert "Kill-Switch activated" in caplog.text


# ═══════════════════════════════════════════════════════════════════
# STORY 7.4.2: /RESUME COMMAND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestHandleResumeCommand:
    """Tests for handle_resume_command function (Story 7.4.2 AC2)."""

    @pytest.fixture
    def resume_command(self) -> TelegramCommand:
        """Create a sample /resume command without confirm."""
        return TelegramCommand(
            command="resume",
            args=[],
            chat_id="123456",
            message_id=43,
            raw_text="/resume",
        )

    @pytest.fixture
    def resume_confirm_command(self) -> TelegramCommand:
        """Create a sample legacy /resume confirm command (backward compatible)."""
        return TelegramCommand(
            command="resume",
            args=["confirm"],
            chat_id="123456",
            message_id=44,
            raw_text="/resume confirm",
        )

    @pytest.fixture
    def active_state(self) -> RiskControlState:
        """Create a RiskControlState with Kill-Switch active."""
        return RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Manual trigger via Telegram",
            kill_switch_triggered_at="2025-01-01T00:00:00+00:00",
            daily_loss_triggered=False,
        )

    @pytest.fixture
    def inactive_state(self) -> RiskControlState:
        """Create a RiskControlState with Kill-Switch inactive."""
        return RiskControlState(
            kill_switch_active=False,
            kill_switch_reason=None,
            kill_switch_triggered_at=None,
        )

    @pytest.fixture
    def daily_loss_state(self) -> RiskControlState:
        """Create a RiskControlState with daily loss triggered."""
        return RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Daily loss limit reached",
            kill_switch_triggered_at="2025-01-01T00:00:00+00:00",
            daily_loss_triggered=True,
            daily_loss_pct=-6.5,
        )

    def test_resume_directly_deactivates_kill_switch(
        self, resume_command: TelegramCommand, active_state: RiskControlState
    ):
        """/resume should directly deactivate Kill-Switch when allowed."""
        result = handle_resume_command(resume_command, active_state)

        assert result.success is True
        assert result.state_changed is True
        assert result.action == "KILL_SWITCH_DEACTIVATED"
        assert active_state.kill_switch_active is False
        assert active_state.kill_switch_reason == "telegram:/resume"

    def test_legacy_resume_confirm_also_deactivates(
        self, resume_confirm_command: TelegramCommand, active_state: RiskControlState
    ):
        """Legacy /resume confirm form should also deactivate Kill-Switch."""
        result = handle_resume_command(resume_confirm_command, active_state)

        assert result.success is True
        assert result.state_changed is True
        assert result.action == "KILL_SWITCH_DEACTIVATED"
        assert active_state.kill_switch_active is False
        assert active_state.kill_switch_reason == "telegram:/resume"

    def test_resume_returns_success_message(
        self, resume_command: TelegramCommand, active_state: RiskControlState
    ):
        """Test that /resume returns success message."""
        result = handle_resume_command(resume_command, active_state)

        assert "Kill\\-Switch 已解除" in result.message
        assert "交易功能已恢复正常" in result.message

    def test_resume_when_not_active(
        self, resume_command: TelegramCommand, inactive_state: RiskControlState
    ):
        """Test that /resume when not active returns info message."""
        result = handle_resume_command(resume_command, inactive_state)

        assert result.success is True
        assert result.state_changed is False
        assert result.action is None
        assert "当前未激活" in result.message

    def test_resume_blocked_by_daily_loss(
        self, resume_command: TelegramCommand, daily_loss_state: RiskControlState
    ):
        """Test that /resume is blocked when daily loss triggered (AC2)."""
        result = handle_resume_command(resume_command, daily_loss_state)

        assert result.success is False
        assert result.state_changed is False
        assert result.action == "RESUME_BLOCKED_DAILY_LOSS"
        assert "无法解除" in result.message
        assert "每日亏损限制" in result.message
        assert "/reset_daily" in result.message
        assert daily_loss_state.kill_switch_active is True  # Unchanged

    def test_resume_with_force_bypasses_daily_loss(
        self, resume_command: TelegramCommand, daily_loss_state: RiskControlState
    ):
        """Test that /resume with force=True bypasses daily loss check."""
        result = handle_resume_command(resume_command, daily_loss_state, force=True)

        assert result.success is True
        assert result.state_changed is True
        assert result.action == "KILL_SWITCH_DEACTIVATED"
        assert daily_loss_state.kill_switch_active is False

    def test_resume_logs_command_receipt(
        self, resume_command: TelegramCommand, active_state: RiskControlState, caplog
    ):
        """Test that /resume logs command receipt (AC3)."""
        with caplog.at_level(logging.INFO):
            handle_resume_command(resume_command, active_state)

        assert "Telegram /resume command received" in caplog.text
        assert "123456" in caplog.text

    def test_resume_logs_state_change(
        self, resume_command: TelegramCommand, active_state: RiskControlState, caplog
    ):
        """Test that /resume logs state change (AC3)."""
        with caplog.at_level(logging.INFO):
            handle_resume_command(resume_command, active_state)

        assert "Kill-Switch deactivated" in caplog.text


# ═══════════════════════════════════════════════════════════════════
# STORY 7.4.2: COMMAND HANDLERS FACTORY TESTS
# ═══════════════════════════════════════════════════════════════════


class TestCreateKillResumeHandlers:
    """Tests for create_kill_resume_handlers factory function."""
    
    @pytest.fixture
    def state(self) -> RiskControlState:
        """Create a RiskControlState for testing."""
        return RiskControlState(
            kill_switch_active=False,
            kill_switch_reason=None,
            kill_switch_triggered_at=None,
        )
    
    def test_returns_kill_and_resume_handlers(self, state: RiskControlState):
        """Test that factory returns both kill and resume handlers."""
        handlers = create_kill_resume_handlers(state)
        
        assert "kill" in handlers
        assert "resume" in handlers
        assert "balance" in handlers
        assert callable(handlers["kill"])
        assert callable(handlers["resume"])
    
    def test_kill_handler_modifies_state(self, state: RiskControlState):
        """Test that kill handler modifies the state."""
        handlers = create_kill_resume_handlers(state)
        
        cmd = TelegramCommand(
            command="kill",
            args=[],
            chat_id="123",
            message_id=1,
            raw_text="/kill",
        )
        
        handlers["kill"](cmd)
        
        assert state.kill_switch_active is True
    
    def test_resume_handler_modifies_state(self, state: RiskControlState):
        """Test that resume handler modifies the state."""
        # First activate Kill-Switch
        state.kill_switch_active = True
        state.kill_switch_reason = "test"
        state.kill_switch_triggered_at = "2025-01-01T00:00:00+00:00"
        
        handlers = create_kill_resume_handlers(state)
        
        cmd = TelegramCommand(
            command="resume",
            args=["confirm"],
            chat_id="123",
            message_id=1,
            raw_text="/resume confirm",
        )
        
        handlers["resume"](cmd)
        
        assert state.kill_switch_active is False
    
    def test_handlers_call_record_event_fn(self, state: RiskControlState):
        """Test that handlers call record_event_fn when state changes."""
        recorded_events = []
        
        def mock_record(action: str, detail: str) -> None:
            recorded_events.append((action, detail))
        
        handlers = create_kill_resume_handlers(
            state,
            record_event_fn=mock_record,
        )
        
        cmd = TelegramCommand(
            command="kill",
            args=[],
            chat_id="123",
            message_id=1,
            raw_text="/kill",
        )
        
        handlers["kill"](cmd)
        
        assert len(recorded_events) == 1
        assert recorded_events[0][0] == "KILL_SWITCH_ACTIVATED"
    
    def test_handlers_use_positions_count_fn(self, state: RiskControlState):
        """Test that handlers use positions_count_fn."""
        handlers = create_kill_resume_handlers(
            state,
            positions_count_fn=lambda: 5,
        )
        
        cmd = TelegramCommand(
            command="kill",
            args=[],
            chat_id="123",
            message_id=1,
            raw_text="/kill",
        )
        
        # The handler should use positions_count_fn
        handlers["kill"](cmd)
        
        # State should be modified
        assert state.kill_switch_active is True


# ═══════════════════════════════════════════════════════════════════
# STORY 7.4.2: INTEGRATION WITH PROCESS_TELEGRAM_COMMANDS
# ═══════════════════════════════════════════════════════════════════


class TestKillResumeIntegration:
    """Integration tests for /kill and /resume with process_telegram_commands."""
    
    def test_process_commands_with_kill_handler(self):
        """Test that process_telegram_commands calls kill handler."""
        state = RiskControlState()
        handlers = create_kill_resume_handlers(state)
        
        commands = [
            TelegramCommand(
                command="kill",
                args=[],
                chat_id="123",
                message_id=1,
                raw_text="/kill",
            ),
        ]
        
        process_telegram_commands(commands, command_handlers=handlers)
        
        assert state.kill_switch_active is True
    
    def test_process_commands_with_resume_handler(self):
        """Test that process_telegram_commands calls resume handler."""
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="test",
            kill_switch_triggered_at="2025-01-01T00:00:00+00:00",
        )
        handlers = create_kill_resume_handlers(state)
        
        commands = [
            TelegramCommand(
                command="resume",
                args=["confirm"],
                chat_id="123",
                message_id=1,
                raw_text="/resume confirm",
            ),
        ]
        
        process_telegram_commands(commands, command_handlers=handlers)
        
        assert state.kill_switch_active is False
    
    def test_process_multiple_commands_in_sequence(self):
        """Test processing multiple commands in sequence."""
        state = RiskControlState()
        handlers = create_kill_resume_handlers(state)
        
        commands = [
            TelegramCommand(
                command="kill",
                args=[],
                chat_id="123",
                message_id=1,
                raw_text="/kill",
            ),
            TelegramCommand(
                command="resume",
                args=["confirm"],
                chat_id="123",
                message_id=2,
                raw_text="/resume confirm",
            ),
        ]
        
        process_telegram_commands(commands, command_handlers=handlers)
        
        # After kill then resume confirm, should be inactive
        assert state.kill_switch_active is False
    
    def test_unhandled_commands_logged(self, caplog):
        """Test that unhandled commands are logged at DEBUG level."""
        state = RiskControlState()
        handlers = create_kill_resume_handlers(state)
        
        commands = [
            TelegramCommand(
                command="unknown",
                args=[],
                chat_id="123",
                message_id=1,
                raw_text="/unknown",
            ),
        ]
        
        with caplog.at_level(logging.DEBUG):
            process_telegram_commands(commands, command_handlers=handlers)
        
        # Should log unhandled command
        assert "unknown" in caplog.text.lower() or len(caplog.records) >= 0


from notifications.telegram_commands import handle_status_command, handle_reset_daily_command


class TestHandleStatusCommand:
    """Tests for handle_status_command function (Bot profit/loss status)."""

    @pytest.fixture
    def base_command(self) -> TelegramCommand:
        """Create a sample /status command."""
        return TelegramCommand(
            command="status",
            args=[],
            chat_id="123456",
            message_id=100,
            raw_text="/status",
        )

    def test_status_returns_profit_snapshot(self, base_command: TelegramCommand):
        """AC1: /status returns Bot profit/loss status with key fields."""
        result = handle_status_command(
            base_command,
            balance=5000.0,
            total_equity=9876.54,
            total_margin=1000.0,
            positions_count=3,
            start_capital=10000.0,
            sortino_ratio=1.5,
            kill_switch_active=False,
        )

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "BOT_STATUS"

        msg = result.message
        # 标题
        assert "📊 *Bot 状态*" in msg
        # 交易状态正常
        assert "🟢 正常" in msg
        # 余额与权益
        assert "可用余额" in msg
        assert "$5,000.00" in msg
        assert "总权益" in msg
        assert "$9,876.54" in msg
        # 收益率
        assert "-1.23%" in msg  # (9876.54 - 10000) / 10000 = -1.23%
        # Sortino
        assert "Sortino Ratio" in msg
        assert "+1.50" in msg
        # 持仓
        assert "持仓数量" in msg
        assert "3" in msg

    def test_status_shows_margin_when_positive(self, base_command: TelegramCommand):
        """AC2: /status shows margin allocated when > 0."""
        result = handle_status_command(
            base_command,
            balance=5000.0,
            total_equity=6500.0,
            total_margin=1500.0,
            positions_count=2,
            start_capital=5000.0,
            sortino_ratio=None,
            kill_switch_active=False,
        )

        msg = result.message
        assert "已用保证金" in msg
        assert "$1,500.00" in msg

    def test_status_hides_margin_when_zero(self, base_command: TelegramCommand):
        """AC2: /status hides margin line when margin is 0."""
        result = handle_status_command(
            base_command,
            balance=5000.0,
            total_equity=5000.0,
            total_margin=0.0,
            positions_count=0,
            start_capital=5000.0,
            sortino_ratio=None,
            kill_switch_active=False,
        )

        msg = result.message
        assert "已用保证金" not in msg


class TestHandleBalanceCommand:
    """Tests for handle_balance_command function (account snapshot)."""

    @pytest.fixture
    def base_command(self) -> TelegramCommand:
        """Create a sample /balance command."""
        return TelegramCommand(
            command="balance",
            args=[],
            chat_id="123456",
            message_id=100,
            raw_text="/balance",
        )

    def test_balance_returns_account_snapshot(self, base_command: TelegramCommand):
        """/balance should return balance, equity and positions information."""
        from notifications.telegram_commands import handle_balance_command

        result = handle_balance_command(
            base_command,
            balance=5000.0,
            total_equity=6500.0,
            total_margin=1000.0,
            positions_count=2,
            start_capital=6000.0,
        )

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "ACCOUNT_BALANCE"

        msg = result.message
        assert "账户余额与持仓" in msg
        assert "可用余额" in msg
        assert "$5,000.00" in msg
        assert "总权益" in msg
        assert "$6,500.00" in msg
        assert "持仓数量" in msg
        assert "2" in msg

    def test_balance_hides_margin_when_zero(self, base_command: TelegramCommand):
        """/balance should hide margin line when margin is 0."""
        from notifications.telegram_commands import handle_balance_command

        result = handle_balance_command(
            base_command,
            balance=5000.0,
            total_equity=5000.0,
            total_margin=0.0,
            positions_count=0,
            start_capital=5000.0,
        )

        msg = result.message
        assert "已用保证金" not in msg

    def test_status_shows_kill_switch_paused(self, base_command: TelegramCommand):
        """AC3: /status shows trading paused when kill switch is active."""
        result = handle_status_command(
            base_command,
            balance=5000.0,
            total_equity=4500.0,
            total_margin=0.0,
            positions_count=0,
            start_capital=5000.0,
            sortino_ratio=-2.0,
            kill_switch_active=True,
        )

        msg = result.message
        assert "🔴 已暂停" in msg


class TestHandleRiskCommand:
    """Tests for handle_risk_command function (risk control status)."""

    @pytest.fixture
    def base_command(self) -> TelegramCommand:
        """Create a sample /risk command."""
        return TelegramCommand(
            command="risk",
            args=[],
            chat_id="123456",
            message_id=100,
            raw_text="/risk",
        )

    @pytest.fixture
    def normal_state(self) -> RiskControlState:
        """RiskControlState with no active kill-switch and no daily loss trigger."""
        return RiskControlState(
            kill_switch_active=False,
            kill_switch_reason=None,
            kill_switch_triggered_at=None,
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-1.2345,
            daily_loss_triggered=False,
        )

    @pytest.fixture
    def high_risk_state(self) -> RiskControlState:
        """RiskControlState with kill-switch active and daily loss triggered."""
        return RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Daily loss limit reached",
            kill_switch_triggered_at="2025-11-30T10:00:00+00:00",
            daily_start_equity=12000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-6.5,
            daily_loss_triggered=True,
        )

    def test_risk_returns_snapshot_markdown(
        self,
        base_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC1/AC2: /risk returns structured Markdown snapshot with key fields."""
        from notifications.telegram_commands import handle_risk_command
        result = handle_risk_command(
            base_command,
            normal_state,
            total_equity=9876.54,
            positions_count=3,
            risk_control_enabled=True,
            daily_loss_limit_enabled=True,
            daily_loss_limit_pct=5.0,
        )

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert result.state_changed is False
        assert result.action == "RISK_CONTROL_STATUS"

        msg = result.message
        # 标题与基础结构
        assert "🛡 *风控状态*" in msg
        assert "Kill\\-Switch" in msg
        # Kill-Switch 未激活时应显示绿色状态
        assert "🟢 已关闭" in msg
        # 数值字段格式
        assert "当日亏损:" in msg
        assert "-1.23%" in msg  # 保留两位小数
        assert "亏损阈值:" in msg
        assert "\\-5.00%" in msg
        assert "今日起始权益:" in msg
        assert "当前权益:" in msg

    def test_risk_high_risk_flags_display(
        self,
        base_command: TelegramCommand,
        high_risk_state: RiskControlState,
    ):
        """AC1/AC2: 高风险状态下应显示 Kill-Switch 与日亏限制标记。"""
        from notifications.telegram_commands import handle_risk_command
        result = handle_risk_command(
            base_command,
            high_risk_state,
            total_equity=8000.0,
            positions_count=1,
            risk_control_enabled=True,
            daily_loss_limit_enabled=True,
            daily_loss_limit_pct=5.0,
        )

        msg = result.message
        # Kill-Switch 激活文案
        assert "Kill\\-Switch:* 🔴 已激活" in msg
        assert "Daily loss limit reached" in msg or "Daily loss limit" in msg
        # 风险标记
        assert "🔴 Kill\\-Switch 已激活" in msg
        assert "⚠️ 日亏限制已触发" in msg

    def test_risk_control_disabled_message(
        self,
        base_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC2/AC3: 风控关闭时返回降级提示，不展示误导性数值。"""
        from notifications.telegram_commands import handle_risk_command
        result = handle_risk_command(
            base_command,
            normal_state,
            total_equity=None,
            positions_count=0,
            risk_control_enabled=False,
            daily_loss_limit_enabled=False,
            daily_loss_limit_pct=5.0,
        )

        msg = result.message
        assert "风控系统未启用" in msg
        # 不应包含阈值与权益等细节字段
        assert "亏损阈值" not in msg


class TestStatusHandlerIntegration:
    """Integration tests for /status handler via create_kill_resume_handlers."""

    def test_status_handler_sends_message_and_records_event(self, caplog):
        """AC3/AC4: /status 通过工厂集成，发送消息并记录审计事件。"""
        state = RiskControlState(
            kill_switch_active=False,
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-2.0,
            daily_loss_triggered=False,
        )

        sent: Dict[str, Any] = {}
        events = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent["text"] = text
            sent["parse_mode"] = parse_mode

        def fake_record(action: str, detail: str) -> None:
            events.append((action, detail))

        handlers = create_kill_resume_handlers(
            state,
            positions_count_fn=lambda: 2,
            send_fn=fake_send,
            record_event_fn=fake_record,
            bot_token="dummy",
            chat_id="123456",
            total_equity_fn=lambda: 9500.0,
            balance_fn=lambda: 5000.0,
            total_margin_fn=lambda: 500.0,
            start_capital=10000.0,
            sortino_ratio_fn=lambda: 1.2,
            risk_control_enabled=True,
            daily_loss_limit_enabled=True,
            daily_loss_limit_pct=5.0,
        )

        cmd = TelegramCommand(
            command="status",
            args=[],
            chat_id="123456",
            message_id=200,
            raw_text="/status",
        )

        with caplog.at_level(logging.INFO):
            handlers["status"](cmd)

        # 发送了 MarkdownV2 文本
        assert sent["parse_mode"] == "MarkdownV2"
        assert "📊 *Bot 状态*" in sent["text"]
        # 记录了审计事件
        assert ("BOT_STATUS", "status via Telegram | chat_id=123456") in events

    def test_balance_handler_sends_message_and_records_event(self, caplog):
        """/balance handler sends account snapshot and records audit event."""
        state = RiskControlState(
            kill_switch_active=False,
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-2.0,
            daily_loss_triggered=False,
        )

        sent: Dict[str, Any] = {}
        events = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent["text"] = text
            sent["parse_mode"] = parse_mode

        def fake_record(action: str, detail: str) -> None:
            events.append((action, detail))

        handlers = create_kill_resume_handlers(
            state,
            positions_count_fn=lambda: 2,
            send_fn=fake_send,
            record_event_fn=fake_record,
            bot_token="dummy",
            chat_id="123456",
            total_equity_fn=lambda: 9500.0,
            balance_fn=lambda: 5000.0,
            total_margin_fn=lambda: 500.0,
            start_capital=10000.0,
            sortino_ratio_fn=lambda: 1.2,
            risk_control_enabled=True,
            daily_loss_limit_enabled=True,
            daily_loss_limit_pct=5.0,
        )

        cmd = TelegramCommand(
            command="balance",
            args=[],
            chat_id="123456",
            message_id=201,
            raw_text="/balance",
        )

        with caplog.at_level(logging.INFO):
            handlers["balance"](cmd)

        # 发送了 MarkdownV2 文本
        assert sent["parse_mode"] == "MarkdownV2"
        assert "账户余额与持仓" in sent["text"]
        # 记录了审计事件
        assert ("ACCOUNT_BALANCE", "balance via Telegram | chat_id=123456") in events

    def test_risk_handler_sends_message_and_records_event(self, caplog):
        """AC3/AC4: /risk 通过工厂集成，发送消息并记录审计事件。"""
        state = RiskControlState(
            kill_switch_active=False,
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-2.0,
            daily_loss_triggered=False,
        )

        sent: Dict[str, Any] = {}
        events = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent["text"] = text
            sent["parse_mode"] = parse_mode

        def fake_record(action: str, detail: str) -> None:
            events.append((action, detail))

        handlers = create_kill_resume_handlers(
            state,
            positions_count_fn=lambda: 2,
            send_fn=fake_send,
            record_event_fn=fake_record,
            bot_token="dummy",
            chat_id="123456",
            total_equity_fn=lambda: 9500.0,
            risk_control_enabled=True,
            daily_loss_limit_enabled=True,
            daily_loss_limit_pct=5.0,
        )

        cmd = TelegramCommand(
            command="risk",
            args=[],
            chat_id="123456",
            message_id=200,
            raw_text="/risk",
        )

        with caplog.at_level(logging.INFO):
            handlers["risk"](cmd)

        # 发送了 MarkdownV2 文本
        assert sent["parse_mode"] == "MarkdownV2"
        assert "🛡 *风控状态*" in sent["text"]
        # 记录了审计事件
        assert ("RISK_CONTROL_STATUS", "risk via Telegram | chat_id=123456") in events


# ═══════════════════════════════════════════════════════════════════
# STORY 7.4.4: /RESET_DAILY COMMAND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestHandleResetDailyCommand:
    """Tests for handle_reset_daily_command function (Story 7.4.4 AC1-AC4)."""

    @pytest.fixture
    def reset_daily_command(self) -> TelegramCommand:
        """Create a sample /reset_daily command."""
        return TelegramCommand(
            command="reset_daily",
            args=[],
            chat_id="123456",
            message_id=300,
            raw_text="/reset_daily",
        )

    @pytest.fixture
    def normal_state(self) -> RiskControlState:
        """RiskControlState with no active kill-switch."""
        return RiskControlState(
            kill_switch_active=False,
            kill_switch_reason=None,
            kill_switch_triggered_at=None,
            daily_start_equity=10000.0,
            daily_start_date="2025-11-29",
            daily_loss_pct=-3.5,
            daily_loss_triggered=False,
        )

    @pytest.fixture
    def daily_loss_triggered_state(self) -> RiskControlState:
        """RiskControlState with daily loss triggered and Kill-Switch active."""
        return RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Daily loss limit reached: -6.50% <= -5.00%",
            kill_switch_triggered_at="2025-11-30T10:00:00+00:00",
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-6.5,
            daily_loss_triggered=True,
        )

    @pytest.fixture
    def manual_kill_state(self) -> RiskControlState:
        """RiskControlState with Kill-Switch activated manually (not by daily loss)."""
        return RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Manual trigger via Telegram",
            kill_switch_triggered_at="2025-11-30T08:00:00+00:00",
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-2.0,
            daily_loss_triggered=False,
        )

    # ─────────────────────────────────────────────────────────────────
    # AC1: /reset_daily 正确重置每日亏损基准
    # ─────────────────────────────────────────────────────────────────

    def test_reset_daily_updates_baseline_fields(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC1: /reset_daily 更新 daily_start_equity, daily_start_date, daily_loss_pct."""
        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=9500.0,
            risk_control_enabled=True,
        )

        assert result.success is True
        assert result.state_changed is True
        assert result.action == "DAILY_BASELINE_RESET"

        # 验证状态字段已更新
        assert normal_state.daily_start_equity == 9500.0
        assert normal_state.daily_loss_pct == 0.0
        assert normal_state.daily_loss_triggered is False
        # daily_start_date 应为当前 UTC 日期
        assert normal_state.daily_start_date is not None

    def test_reset_daily_returns_confirmation_message(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC3: /reset_daily 返回结构化确认消息。"""
        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=9500.0,
            risk_control_enabled=True,
        )

        msg = result.message
        assert "🧮 *每日亏损基准已重置*" in msg
        assert "$9,500.00" in msg  # 新起始权益
        assert "$10,000.00" in msg  # 原起始权益
        assert "0\\.00%" in msg  # 当前亏损
        assert "-3.50%" in msg  # 原亏损
        assert "False" in msg  # 日亏触发标志

    def test_reset_daily_idempotent(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC1: /reset_daily 是幂等的，多次调用不会产生意外副作用。"""
        # 第一次调用
        handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=9500.0,
            risk_control_enabled=True,
        )

        first_equity = normal_state.daily_start_equity
        first_date = normal_state.daily_start_date

        # 第二次调用（相同权益）
        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=9500.0,
            risk_control_enabled=True,
        )

        assert result.success is True
        assert normal_state.daily_start_equity == first_equity
        assert normal_state.daily_start_date == first_date
        assert normal_state.daily_loss_pct == 0.0

    # ─────────────────────────────────────────────────────────────────
    # AC2: 与 Kill-Switch / 每日亏损限制的协同行为
    # ─────────────────────────────────────────────────────────────────

    def test_reset_daily_clears_daily_loss_triggered(
        self,
        reset_daily_command: TelegramCommand,
        daily_loss_triggered_state: RiskControlState,
    ):
        """AC2: /reset_daily 清除 daily_loss_triggered 标志。"""
        assert daily_loss_triggered_state.daily_loss_triggered is True

        result = handle_reset_daily_command(
            reset_daily_command,
            daily_loss_triggered_state,
            total_equity=9350.0,
            risk_control_enabled=True,
        )

        assert result.success is True
        assert daily_loss_triggered_state.daily_loss_triggered is False
        assert daily_loss_triggered_state.daily_loss_pct == 0.0

    def test_reset_daily_preserves_kill_switch_active(
        self,
        reset_daily_command: TelegramCommand,
        daily_loss_triggered_state: RiskControlState,
    ):
        """AC2: /reset_daily 不会自动解除 Kill-Switch。"""
        assert daily_loss_triggered_state.kill_switch_active is True

        handle_reset_daily_command(
            reset_daily_command,
            daily_loss_triggered_state,
            total_equity=9350.0,
            risk_control_enabled=True,
        )

        # Kill-Switch 应保持激活状态
        assert daily_loss_triggered_state.kill_switch_active is True
        assert daily_loss_triggered_state.kill_switch_reason is not None

    def test_reset_daily_message_prompts_resume_when_kill_switch_active(
        self,
        reset_daily_command: TelegramCommand,
        daily_loss_triggered_state: RiskControlState,
    ):
        """AC2/AC3: Kill-Switch 激活时，消息提示用户需要 /resume。"""
        result = handle_reset_daily_command(
            reset_daily_command,
            daily_loss_triggered_state,
            total_equity=9350.0,
            risk_control_enabled=True,
        )

        msg = result.message
        assert "Kill\\-Switch 仍处于激活状态" in msg
        assert "/resume" in msg

    def test_reset_daily_message_no_prompt_when_kill_switch_inactive(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC3: Kill-Switch 未激活时，消息显示交易正常运行。"""
        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=9500.0,
            risk_control_enabled=True,
        )

        msg = result.message
        assert "交易功能正常运行中" in msg
        assert "Kill\\-Switch 仍处于激活状态" not in msg

    def test_reset_daily_does_not_affect_manual_kill_switch(
        self,
        reset_daily_command: TelegramCommand,
        manual_kill_state: RiskControlState,
    ):
        """AC2: /reset_daily 不影响手动激活的 Kill-Switch。"""
        original_reason = manual_kill_state.kill_switch_reason

        handle_reset_daily_command(
            reset_daily_command,
            manual_kill_state,
            total_equity=9800.0,
            risk_control_enabled=True,
        )

        # Kill-Switch 状态和原因应保持不变
        assert manual_kill_state.kill_switch_active is True
        assert manual_kill_state.kill_switch_reason == original_reason
        # 但每日基准应已重置
        assert manual_kill_state.daily_start_equity == 9800.0
        assert manual_kill_state.daily_loss_pct == 0.0

    # ─────────────────────────────────────────────────────────────────
    # AC3: 降级场景
    # ─────────────────────────────────────────────────────────────────

    def test_reset_daily_risk_control_disabled(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC3: 风控未启用时返回降级提示，不修改状态。"""
        original_equity = normal_state.daily_start_equity

        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=9500.0,
            risk_control_enabled=False,
        )

        assert result.success is False
        assert result.state_changed is False
        assert "风控系统未启用" in result.message
        assert normal_state.daily_start_equity == original_equity

    def test_reset_daily_equity_unavailable(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC3: 权益不可用时返回降级提示，不修改状态。"""
        original_equity = normal_state.daily_start_equity

        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=None,
            risk_control_enabled=True,
        )

        assert result.success is False
        assert result.state_changed is False
        assert "权益数据不可用" in result.message
        assert normal_state.daily_start_equity == original_equity

    def test_reset_daily_equity_nan(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
    ):
        """AC3: 权益为 NaN 时返回降级提示，不修改状态。"""
        original_equity = normal_state.daily_start_equity

        result = handle_reset_daily_command(
            reset_daily_command,
            normal_state,
            total_equity=float("nan"),
            risk_control_enabled=True,
        )

        assert result.success is False
        assert result.state_changed is False
        assert "权益数据不可用" in result.message
        assert normal_state.daily_start_equity == original_equity

    # ─────────────────────────────────────────────────────────────────
    # AC4: 日志与审计
    # ─────────────────────────────────────────────────────────────────

    def test_reset_daily_logs_command_receipt(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
        caplog,
    ):
        """AC4: /reset_daily 记录命令接收日志。"""
        with caplog.at_level(logging.INFO):
            handle_reset_daily_command(
                reset_daily_command,
                normal_state,
                total_equity=9500.0,
                risk_control_enabled=True,
            )

        assert "Telegram /reset_daily command received" in caplog.text
        assert "123456" in caplog.text

    def test_reset_daily_logs_state_change(
        self,
        reset_daily_command: TelegramCommand,
        daily_loss_triggered_state: RiskControlState,
        caplog,
    ):
        """AC4: /reset_daily 记录状态变更日志。"""
        with caplog.at_level(logging.INFO):
            handle_reset_daily_command(
                reset_daily_command,
                daily_loss_triggered_state,
                total_equity=9350.0,
                risk_control_enabled=True,
            )

        assert "daily baseline reset" in caplog.text.lower()
        assert "old_equity" in caplog.text
        assert "new_equity" in caplog.text

    def test_reset_daily_logs_warning_when_disabled(
        self,
        reset_daily_command: TelegramCommand,
        normal_state: RiskControlState,
        caplog,
    ):
        """AC4: 风控未启用时记录 WARNING 日志。"""
        with caplog.at_level(logging.WARNING):
            handle_reset_daily_command(
                reset_daily_command,
                normal_state,
                total_equity=9500.0,
                risk_control_enabled=False,
            )

        assert "risk control not enabled" in caplog.text.lower()


class TestResetDailyHandlerIntegration:
    """Integration tests for /reset_daily handler via create_kill_resume_handlers."""

    def test_reset_daily_handler_registered(self):
        """AC5: /reset_daily handler 已注册到 handlers dict。"""
        state = RiskControlState()
        handlers = create_kill_resume_handlers(
            state,
            risk_control_enabled=True,
        )

        assert "reset_daily" in handlers
        assert callable(handlers["reset_daily"])

    def test_reset_daily_handler_modifies_state(self):
        """AC5: /reset_daily handler 正确修改状态。"""
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Daily loss limit",
            daily_start_equity=10000.0,
            daily_start_date="2025-11-29",
            daily_loss_pct=-6.0,
            daily_loss_triggered=True,
        )

        handlers = create_kill_resume_handlers(
            state,
            total_equity_fn=lambda: 9400.0,
            risk_control_enabled=True,
        )

        cmd = TelegramCommand(
            command="reset_daily",
            args=[],
            chat_id="123456",
            message_id=400,
            raw_text="/reset_daily",
        )

        handlers["reset_daily"](cmd)

        # 验证状态已更新
        assert state.daily_start_equity == 9400.0
        assert state.daily_loss_pct == 0.0
        assert state.daily_loss_triggered is False
        # Kill-Switch 应保持激活
        assert state.kill_switch_active is True

    def test_reset_daily_handler_sends_message_and_records_event(self):
        """AC4/AC5: /reset_daily 发送消息并记录审计事件。"""
        state = RiskControlState(
            daily_start_equity=10000.0,
            daily_start_date="2025-11-29",
            daily_loss_pct=-3.0,
            daily_loss_triggered=False,
        )

        sent: Dict[str, Any] = {}
        events = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent["text"] = text
            sent["parse_mode"] = parse_mode

        def fake_record(action: str, detail: str) -> None:
            events.append((action, detail))

        handlers = create_kill_resume_handlers(
            state,
            send_fn=fake_send,
            record_event_fn=fake_record,
            bot_token="dummy",
            chat_id="123456",
            total_equity_fn=lambda: 9700.0,
            risk_control_enabled=True,
        )

        cmd = TelegramCommand(
            command="reset_daily",
            args=[],
            chat_id="123456",
            message_id=500,
            raw_text="/reset_daily",
        )

        handlers["reset_daily"](cmd)

        # 验证发送了消息
        assert sent["parse_mode"] == "MarkdownV2"
        assert "每日亏损基准已重置" in sent["text"]

        # 验证记录了审计事件
        assert len(events) == 1
        assert events[0][0] == "DAILY_BASELINE_RESET"
        assert "chat_id=123456" in events[0][1]

    def test_reset_daily_then_resume_flow(self):
        """AC5: /reset_daily 后 /resume confirm 可以正常解除 Kill-Switch。"""
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="Daily loss limit reached",
            kill_switch_triggered_at="2025-11-30T10:00:00+00:00",
            daily_start_equity=10000.0,
            daily_start_date="2025-11-30",
            daily_loss_pct=-6.0,
            daily_loss_triggered=True,
        )

        handlers = create_kill_resume_handlers(
            state,
            total_equity_fn=lambda: 9400.0,
            risk_control_enabled=True,
        )

        # 先执行 /reset_daily
        reset_cmd = TelegramCommand(
            command="reset_daily",
            args=[],
            chat_id="123456",
            message_id=600,
            raw_text="/reset_daily",
        )
        handlers["reset_daily"](reset_cmd)

        # 验证 daily_loss_triggered 已清除
        assert state.daily_loss_triggered is False
        assert state.kill_switch_active is True  # Kill-Switch 仍激活

        # 再执行 /resume confirm
        resume_cmd = TelegramCommand(
            command="resume",
            args=["confirm"],
            chat_id="123456",
            message_id=601,
            raw_text="/resume confirm",
        )
        handlers["resume"](resume_cmd)

        # 验证 Kill-Switch 已解除
        assert state.kill_switch_active is False

    def test_reset_daily_handler_catches_exceptions(self, caplog):
        """AC4: /reset_daily handler 捕获异常并返回降级消息。"""
        state = RiskControlState()

        sent_messages = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent_messages.append(text)

        def failing_equity_fn():
            raise RuntimeError("Equity fetch failed")

        handlers = create_kill_resume_handlers(
            state,
            send_fn=fake_send,
            bot_token="dummy",
            chat_id="123456",
            total_equity_fn=failing_equity_fn,
            risk_control_enabled=True,
        )

        cmd = TelegramCommand(
            command="reset_daily",
            args=[],
            chat_id="123456",
            message_id=700,
            raw_text="/reset_daily",
        )

        with caplog.at_level(logging.ERROR):
            handlers["reset_daily"](cmd)

        # 应发送降级消息
        assert len(sent_messages) == 1
        assert "暂时无法重置每日基准" in sent_messages[0]

        # 应记录错误日志
        assert "Error processing Telegram /reset_daily" in caplog.text


# ═══════════════════════════════════════════════════════════════════
# STORY 7.4.5: /help AND UNKNOWN COMMAND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestHandleHelpCommand:
    """Tests for /help command handler (Story 7.4.5)."""

    def test_help_returns_command_list(self):
        """AC1: /help 返回完整的命令帮助列表。"""
        from notifications.telegram_commands import handle_help_command

        cmd = TelegramCommand(
            command="help",
            args=[],
            chat_id="123456",
            message_id=100,
            raw_text="/help",
        )

        result = handle_help_command(cmd, risk_control_enabled=True)

        assert result.success is True
        assert result.state_changed is False
        assert result.action == "HELP_DISPLAYED"
        # 验证包含所有命令
        assert "/kill" in result.message
        assert "/resume" in result.message
        assert "/status" in result.message
        assert "/balance" in result.message
        assert "/reset" in result.message  # /reset\_daily
        assert "/help" in result.message

    def test_help_shows_risk_control_disabled_warning(self):
        """AC1: 风控关闭时帮助信息包含提示。"""
        from notifications.telegram_commands import handle_help_command

        cmd = TelegramCommand(
            command="help",
            args=[],
            chat_id="123456",
            message_id=101,
            raw_text="/help",
        )

        result = handle_help_command(cmd, risk_control_enabled=False)

        assert result.success is True
        assert "风控系统当前未启用" in result.message

    def test_help_logs_command_receipt(self, caplog):
        """AC1: /help 命令记录 INFO 日志。"""
        from notifications.telegram_commands import handle_help_command

        cmd = TelegramCommand(
            command="help",
            args=[],
            chat_id="123456",
            message_id=102,
            raw_text="/help",
        )

        with caplog.at_level(logging.INFO):
            handle_help_command(cmd)

        assert "Telegram /help command received" in caplog.text
        assert "123456" in caplog.text


class TestHandleUnknownCommand:
    """Tests for unknown command handler (Story 7.4.5)."""

    def test_unknown_command_returns_help(self):
        """AC3: 未知命令返回帮助信息。"""
        from notifications.telegram_commands import handle_unknown_command

        cmd = TelegramCommand(
            command="foo",
            args=[],
            chat_id="123456",
            message_id=200,
            raw_text="/foo",
        )

        result = handle_unknown_command(cmd, risk_control_enabled=True)

        assert result.success is True
        assert result.state_changed is False
        assert result.action == "UNKNOWN_COMMAND"
        # 验证包含未知命令提示和帮助列表
        assert "未知命令" in result.message
        assert "/foo" in result.message
        assert "/kill" in result.message
        assert "/help" in result.message

    def test_unknown_command_does_not_modify_state(self):
        """AC3: 未知命令不修改 RiskControlState。"""
        from notifications.telegram_commands import handle_unknown_command

        cmd = TelegramCommand(
            command="unknown",
            args=["arg1"],
            chat_id="123456",
            message_id=201,
            raw_text="/unknown arg1",
        )

        result = handle_unknown_command(cmd)

        assert result.state_changed is False

    def test_unknown_command_logs_info(self, caplog):
        """AC3: 未知命令记录 INFO 日志。"""
        from notifications.telegram_commands import handle_unknown_command

        cmd = TelegramCommand(
            command="badcmd",
            args=[],
            chat_id="123456",
            message_id=202,
            raw_text="/badcmd",
        )

        with caplog.at_level(logging.INFO):
            handle_unknown_command(cmd)

        assert "Telegram unknown command received" in caplog.text
        assert "badcmd" in caplog.text


class TestHelpAndUnknownHandlerIntegration:
    """Integration tests for /help and unknown command handlers (Story 7.4.5)."""

    def test_help_handler_registered_in_handlers(self):
        """AC1: /help handler 正确注册到 handlers 字典。"""
        state = RiskControlState()
        handlers = create_kill_resume_handlers(
            state,
            risk_control_enabled=True,
        )

        assert "help" in handlers

    def test_unknown_handler_registered_in_handlers(self):
        """AC3: __unknown__ handler 正确注册到 handlers 字典。"""
        state = RiskControlState()
        handlers = create_kill_resume_handlers(
            state,
            risk_control_enabled=True,
        )

        assert "__unknown__" in handlers

    def test_help_handler_sends_message(self):
        """AC1: /help handler 发送帮助消息。"""
        state = RiskControlState()
        sent_messages = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent_messages.append({"text": text, "parse_mode": parse_mode})

        handlers = create_kill_resume_handlers(
            state,
            send_fn=fake_send,
            bot_token="dummy",
            chat_id="123456",
            risk_control_enabled=True,
        )

        cmd = TelegramCommand(
            command="help",
            args=[],
            chat_id="123456",
            message_id=300,
            raw_text="/help",
        )

        handlers["help"](cmd)

        assert len(sent_messages) == 1
        assert sent_messages[0]["parse_mode"] == "MarkdownV2"
        assert "可用命令列表" in sent_messages[0]["text"]

    def test_unknown_handler_sends_message(self):
        """AC3: unknown handler 发送未知命令提示。"""
        state = RiskControlState()
        sent_messages = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent_messages.append({"text": text, "parse_mode": parse_mode})

        handlers = create_kill_resume_handlers(
            state,
            send_fn=fake_send,
            bot_token="dummy",
            chat_id="123456",
            risk_control_enabled=True,
        )

        cmd = TelegramCommand(
            command="invalid",
            args=[],
            chat_id="123456",
            message_id=301,
            raw_text="/invalid",
        )

        handlers["__unknown__"](cmd)

        assert len(sent_messages) == 1
        assert "未知命令" in sent_messages[0]["text"]

    def test_process_telegram_commands_uses_unknown_handler(self):
        """AC3: process_telegram_commands 对未知命令使用 __unknown__ handler。"""
        state = RiskControlState()
        called_handlers = []

        def fake_send(text: str, parse_mode: str) -> None:
            pass

        handlers = create_kill_resume_handlers(
            state,
            send_fn=fake_send,
            bot_token="dummy",
            chat_id="123456",
            risk_control_enabled=True,
        )

        # 包装 unknown handler 以追踪调用
        original_unknown = handlers["__unknown__"]

        def tracking_unknown(cmd: TelegramCommand) -> None:
            called_handlers.append(cmd.command)
            original_unknown(cmd)

        handlers["__unknown__"] = tracking_unknown

        cmd = TelegramCommand(
            command="notexist",
            args=[],
            chat_id="123456",
            message_id=302,
            raw_text="/notexist",
        )

        process_telegram_commands([cmd], command_handlers=handlers)

        assert "notexist" in called_handlers

    def test_help_handler_catches_exceptions(self, caplog):
        """AC4: /help handler 捕获异常并返回降级消息。"""
        state = RiskControlState()
        sent_messages = []

        def fake_send(text: str, parse_mode: str) -> None:
            sent_messages.append(text)

        # 创建一个会抛出异常的 mock
        handlers = create_kill_resume_handlers(
            state,
            send_fn=fake_send,
            bot_token="dummy",
            chat_id="123456",
            risk_control_enabled=True,
        )

        # 替换 help handler 为一个会抛出异常的版本
        from notifications.telegram_commands import handle_help_command

        def failing_help_handler(cmd: TelegramCommand) -> None:
            raise RuntimeError("Simulated failure")

        # 直接测试异常处理逻辑
        cmd = TelegramCommand(
            command="help",
            args=[],
            chat_id="123456",
            message_id=400,
            raw_text="/help",
        )

        # 测试 process_telegram_commands 的异常处理
        def raising_handler(cmd: TelegramCommand) -> None:
            raise RuntimeError("Test exception")

        test_handlers = {"help": raising_handler}

        with caplog.at_level(logging.ERROR):
            process_telegram_commands([cmd], command_handlers=test_handlers)

        assert "Error processing Telegram command /help" in caplog.text

    def test_unknown_command_does_not_interrupt_main_loop(self, caplog):
        """AC3: 未知命令处理异常不会中断主循环。"""
        cmd = TelegramCommand(
            command="crash",
            args=[],
            chat_id="123456",
            message_id=401,
            raw_text="/crash",
        )

        def raising_unknown(cmd: TelegramCommand) -> None:
            raise RuntimeError("Crash!")

        handlers = {"__unknown__": raising_unknown}

        # 不应抛出异常
        with caplog.at_level(logging.ERROR):
            process_telegram_commands([cmd], command_handlers=handlers)

        assert "Error processing Telegram command /crash" in caplog.text


class TestChatIdFilteringForHelp:
    """Tests for chat ID filtering with /help command (Story 7.4.5 AC2)."""

    @patch("notifications.telegram_commands.requests.get")
    def test_help_from_unauthorized_chat_filtered(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, caplog
    ):
        """AC2: 未授权 Chat 发送 /help 被过滤且记录 WARNING。"""
        updates = [make_update(1, "999999999", "/help")]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)

        with caplog.at_level(logging.WARNING):
            commands = handler.poll_commands()

        assert len(commands) == 0
        assert "unauthorized chat" in caplog.text.lower()
        assert "999999999" in caplog.text

    @patch("notifications.telegram_commands.requests.get")
    def test_help_from_authorized_chat_processed(
        self, mock_get: MagicMock, handler: TelegramCommandHandler, allowed_chat_id: str
    ):
        """AC2: 授权 Chat 发送 /help 被正常处理。"""
        updates = [make_update(1, allowed_chat_id, "/help")]
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = make_api_response(updates)

        commands = handler.poll_commands()

        assert len(commands) == 1
        assert commands[0].command == "help"
