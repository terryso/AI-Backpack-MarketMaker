"""Unit tests for Kill-Switch notification functionality.

Covers:
- Message building for activation and deactivation notifications (AC1, AC2, AC3)
- Notification sending with Telegram configuration (AC1, AC2)
- Skipping notifications when Telegram is not configured (AC3)
- Idempotency - no duplicate notifications on repeated calls (AC1, AC2)
- Integration with activate_kill_switch and deactivate_kill_switch (AC4)
"""

import logging
from unittest import TestCase, mock
from datetime import datetime, timezone

from notifications.telegram import (
    build_kill_switch_activated_message,
    build_kill_switch_deactivated_message,
    notify_kill_switch_activated,
    notify_kill_switch_deactivated,
    create_kill_switch_notify_callbacks,
    escape_markdown,
)
from core.risk_control import (
    RiskControlState,
    activate_kill_switch,
    deactivate_kill_switch,
    apply_kill_switch_env_override,
)


class KillSwitchActivatedMessageTests(TestCase):
    """Tests for build_kill_switch_activated_message function."""

    def test_message_contains_required_fields(self) -> None:
        """Activation message should contain reason, time, positions count, and resume hint."""
        message = build_kill_switch_activated_message(
            reason="env:KILL_SWITCH",
            triggered_at="2025-11-30T12:34:56+00:00",
            positions_count=3,
        )

        # Check required fields are present
        self.assertIn("Kill\\-Switch 已激活", message)
        self.assertIn("2025-11-30T12:34:56+00:00", message)
        self.assertIn("3 个", message)
        self.assertIn("/resume", message)

    def test_message_formats_env_reason(self) -> None:
        """Activation message should format env:KILL_SWITCH reason correctly."""
        message = build_kill_switch_activated_message(
            reason="env:KILL_SWITCH",
            triggered_at="2025-11-30T12:00:00+00:00",
            positions_count=0,
        )

        self.assertIn("环境变量", message)
        # Note: KILL_SWITCH=true is escaped for MarkdownV2
        self.assertIn("KILL", message)
        self.assertIn("true", message)

    def test_message_formats_manual_reason(self) -> None:
        """Activation message should format runtime:manual reason correctly."""
        message = build_kill_switch_activated_message(
            reason="runtime:manual",
            triggered_at="2025-11-30T12:00:00+00:00",
            positions_count=1,
        )

        self.assertIn("手动触发", message)

    def test_message_formats_daily_loss_reason(self) -> None:
        """Activation message should format daily_loss_limit reason correctly."""
        message = build_kill_switch_activated_message(
            reason="daily_loss_limit",
            triggered_at="2025-11-30T12:00:00+00:00",
            positions_count=2,
        )

        self.assertIn("每日亏损限制", message)

    def test_message_formats_unknown_reason(self) -> None:
        """Activation message should pass through unknown reasons."""
        message = build_kill_switch_activated_message(
            reason="custom:reason",
            triggered_at="2025-11-30T12:00:00+00:00",
            positions_count=0,
        )

        self.assertIn("custom:reason", message)

    def test_message_uses_markdown_formatting(self) -> None:
        """Activation message should use Markdown formatting."""
        message = build_kill_switch_activated_message(
            reason="runtime:manual",
            triggered_at="2025-11-30T12:00:00+00:00",
            positions_count=0,
        )

        # Check for Markdown bold markers (escaped for MarkdownV2)
        self.assertIn("*", message)
        # Check for emoji
        self.assertIn("🚨", message)


class KillSwitchDeactivatedMessageTests(TestCase):
    """Tests for build_kill_switch_deactivated_message function."""

    def test_message_contains_required_fields(self) -> None:
        """Deactivation message should contain time and reason."""
        message = build_kill_switch_deactivated_message(
            deactivated_at="2025-11-30T14:00:00+00:00",
            reason="runtime:resume",
        )

        self.assertIn("Kill\\-Switch 已解除", message)
        self.assertIn("2025-11-30T14:00:00+00:00", message)

    def test_message_formats_resume_reason(self) -> None:
        """Deactivation message should format runtime:resume reason correctly."""
        message = build_kill_switch_deactivated_message(
            deactivated_at="2025-11-30T14:00:00+00:00",
            reason="runtime:resume",
        )

        self.assertIn("运行时恢复", message)

    def test_message_formats_telegram_reason(self) -> None:
        """Deactivation message should format telegram:/resume reason correctly."""
        message = build_kill_switch_deactivated_message(
            deactivated_at="2025-11-30T14:00:00+00:00",
            reason="telegram:/resume",
        )

        self.assertIn("/resume", message)

    def test_message_formats_env_reason(self) -> None:
        """Deactivation message should format env:KILL_SWITCH reason correctly."""
        message = build_kill_switch_deactivated_message(
            deactivated_at="2025-11-30T14:00:00+00:00",
            reason="env:KILL_SWITCH",
        )

        self.assertIn("环境变量", message)
        # Note: KILL_SWITCH=false is escaped for MarkdownV2
        self.assertIn("KILL", message)
        self.assertIn("false", message)

    def test_message_uses_markdown_formatting(self) -> None:
        """Deactivation message should use Markdown formatting."""
        message = build_kill_switch_deactivated_message(
            deactivated_at="2025-11-30T14:00:00+00:00",
            reason="runtime:resume",
        )

        # Check for Markdown bold markers
        self.assertIn("*", message)
        # Check for emoji
        self.assertIn("✅", message)


class NotifyKillSwitchActivatedTests(TestCase):
    """Tests for notify_kill_switch_activated function."""

    def test_sends_notification_when_configured(self) -> None:
        """Should send notification when bot_token and chat_id are configured."""
        mock_send = mock.MagicMock()

        result = notify_kill_switch_activated(
            reason="runtime:manual",
            triggered_at="2025-11-30T12:00:00+00:00",
            positions_count=2,
            bot_token="test-token",
            chat_id="test-chat-id",
            send_fn=mock_send,
        )

        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs["bot_token"], "test-token")
        self.assertEqual(call_kwargs["default_chat_id"], "test-chat-id")
        self.assertEqual(call_kwargs["parse_mode"], "MarkdownV2")
        self.assertIn("Kill\\-Switch 已激活", call_kwargs["text"])

    def test_skips_notification_when_token_missing(self) -> None:
        """Should skip notification and log when bot_token is missing."""
        mock_send = mock.MagicMock()

        with self.assertLogs(level=logging.INFO) as cm:
            result = notify_kill_switch_activated(
                reason="runtime:manual",
                triggered_at="2025-11-30T12:00:00+00:00",
                positions_count=0,
                bot_token="",
                chat_id="test-chat-id",
                send_fn=mock_send,
            )

        self.assertFalse(result)
        mock_send.assert_not_called()
        self.assertTrue(
            any("Telegram not configured" in msg for msg in cm.output),
            f"Expected log about missing config, got: {cm.output}",
        )

    def test_skips_notification_when_chat_id_missing(self) -> None:
        """Should skip notification and log when chat_id is missing."""
        mock_send = mock.MagicMock()

        with self.assertLogs(level=logging.INFO) as cm:
            result = notify_kill_switch_activated(
                reason="runtime:manual",
                triggered_at="2025-11-30T12:00:00+00:00",
                positions_count=0,
                bot_token="test-token",
                chat_id="",
                send_fn=mock_send,
            )

        self.assertFalse(result)
        mock_send.assert_not_called()
        self.assertTrue(
            any("Telegram not configured" in msg for msg in cm.output),
            f"Expected log about missing config, got: {cm.output}",
        )

    def test_logs_successful_notification(self) -> None:
        """Should log when notification is sent successfully."""
        mock_send = mock.MagicMock()

        with self.assertLogs(level=logging.INFO) as cm:
            notify_kill_switch_activated(
                reason="daily_loss_limit",
                triggered_at="2025-11-30T12:00:00+00:00",
                positions_count=5,
                bot_token="test-token",
                chat_id="test-chat-id",
                send_fn=mock_send,
            )

        self.assertTrue(
            any("notification sent" in msg and "daily_loss_limit" in msg for msg in cm.output),
            f"Expected log about sent notification, got: {cm.output}",
        )


class NotifyKillSwitchDeactivatedTests(TestCase):
    """Tests for notify_kill_switch_deactivated function."""

    def test_sends_notification_when_configured(self) -> None:
        """Should send notification when bot_token and chat_id are configured."""
        mock_send = mock.MagicMock()

        result = notify_kill_switch_deactivated(
            deactivated_at="2025-11-30T14:00:00+00:00",
            reason="telegram:/resume",
            bot_token="test-token",
            chat_id="test-chat-id",
            send_fn=mock_send,
        )

        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs["bot_token"], "test-token")
        self.assertEqual(call_kwargs["default_chat_id"], "test-chat-id")
        self.assertEqual(call_kwargs["parse_mode"], "MarkdownV2")
        self.assertIn("Kill\\-Switch 已解除", call_kwargs["text"])

    def test_skips_notification_when_not_configured(self) -> None:
        """Should skip notification when Telegram is not configured."""
        mock_send = mock.MagicMock()

        with self.assertLogs(level=logging.INFO) as cm:
            result = notify_kill_switch_deactivated(
                deactivated_at="2025-11-30T14:00:00+00:00",
                reason="runtime:resume",
                bot_token="",
                chat_id="",
                send_fn=mock_send,
            )

        self.assertFalse(result)
        mock_send.assert_not_called()
        self.assertTrue(
            any("Telegram not configured" in msg for msg in cm.output),
            f"Expected log about missing config, got: {cm.output}",
        )


class CreateKillSwitchNotifyCallbacksTests(TestCase):
    """Tests for create_kill_switch_notify_callbacks factory function."""

    def test_returns_none_when_not_configured(self) -> None:
        """Should return (None, None) when Telegram is not configured."""
        activate_fn, deactivate_fn = create_kill_switch_notify_callbacks(
            bot_token="",
            chat_id="test-chat-id",
        )
        self.assertIsNone(activate_fn)
        self.assertIsNone(deactivate_fn)

        activate_fn, deactivate_fn = create_kill_switch_notify_callbacks(
            bot_token="test-token",
            chat_id="",
        )
        self.assertIsNone(activate_fn)
        self.assertIsNone(deactivate_fn)

    def test_returns_callable_when_configured(self) -> None:
        """Should return callable functions when Telegram is configured."""
        activate_fn, deactivate_fn = create_kill_switch_notify_callbacks(
            bot_token="test-token",
            chat_id="test-chat-id",
        )

        self.assertIsNotNone(activate_fn)
        self.assertIsNotNone(deactivate_fn)
        self.assertTrue(callable(activate_fn))
        self.assertTrue(callable(deactivate_fn))

    def test_activate_callback_calls_notify_function(self) -> None:
        """Activate callback should call notify_kill_switch_activated."""
        mock_send = mock.MagicMock()
        activate_fn, _ = create_kill_switch_notify_callbacks(
            bot_token="test-token",
            chat_id="test-chat-id",
            send_fn=mock_send,
        )

        activate_fn("runtime:manual", "2025-11-30T12:00:00+00:00", 3)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs["bot_token"], "test-token")
        self.assertIn("Kill\\-Switch 已激活", call_kwargs["text"])

    def test_deactivate_callback_calls_notify_function(self) -> None:
        """Deactivate callback should call notify_kill_switch_deactivated."""
        mock_send = mock.MagicMock()
        _, deactivate_fn = create_kill_switch_notify_callbacks(
            bot_token="test-token",
            chat_id="test-chat-id",
            send_fn=mock_send,
        )

        deactivate_fn("2025-11-30T14:00:00+00:00", "runtime:resume")

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        self.assertEqual(call_kwargs["bot_token"], "test-token")
        self.assertIn("Kill\\-Switch 已解除", call_kwargs["text"])


class KillSwitchNotificationIntegrationTests(TestCase):
    """Integration tests for Kill-Switch notifications with state changes."""

    def test_activate_kill_switch_calls_notify_fn_on_state_change(self) -> None:
        """activate_kill_switch should call notify_fn when state changes from inactive to active."""
        mock_notify = mock.MagicMock()
        state = RiskControlState(kill_switch_active=False)

        new_state = activate_kill_switch(
            state,
            reason="runtime:manual",
            positions_count=2,
            notify_fn=mock_notify,
        )

        self.assertTrue(new_state.kill_switch_active)
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[0]
        self.assertEqual(call_args[0], "runtime:manual")  # reason
        self.assertIsNotNone(call_args[1])  # triggered_at
        self.assertEqual(call_args[2], 2)  # positions_count

    def test_activate_kill_switch_does_not_call_notify_fn_when_already_active(self) -> None:
        """activate_kill_switch should not call notify_fn when already active (idempotency)."""
        mock_notify = mock.MagicMock()
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="previous:reason",
        )

        new_state = activate_kill_switch(
            state,
            reason="runtime:manual",
            positions_count=2,
            notify_fn=mock_notify,
        )

        self.assertTrue(new_state.kill_switch_active)
        mock_notify.assert_not_called()

    def test_deactivate_kill_switch_calls_notify_fn_on_state_change(self) -> None:
        """deactivate_kill_switch should call notify_fn when state changes from active to inactive."""
        mock_notify = mock.MagicMock()
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="runtime:manual",
        )

        new_state = deactivate_kill_switch(
            state,
            reason="telegram:/resume",
            notify_fn=mock_notify,
        )

        self.assertFalse(new_state.kill_switch_active)
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[0]
        self.assertIsNotNone(call_args[0])  # deactivated_at
        self.assertEqual(call_args[1], "telegram:/resume")  # reason

    def test_deactivate_kill_switch_does_not_call_notify_fn_when_already_inactive(self) -> None:
        """deactivate_kill_switch should not call notify_fn when already inactive (idempotency)."""
        mock_notify = mock.MagicMock()
        state = RiskControlState(kill_switch_active=False)

        new_state = deactivate_kill_switch(
            state,
            reason="runtime:resume",
            notify_fn=mock_notify,
        )

        self.assertFalse(new_state.kill_switch_active)
        mock_notify.assert_not_called()

    def test_activate_kill_switch_logs_state_change(self) -> None:
        """activate_kill_switch should log state change with structured fields."""
        state = RiskControlState(kill_switch_active=False)

        with self.assertLogs(level=logging.WARNING) as cm:
            activate_kill_switch(
                state,
                reason="daily_loss_limit",
                positions_count=3,
            )

        self.assertTrue(
            any(
                "old_state=inactive" in msg
                and "new_state=active" in msg
                and "daily_loss_limit" in msg
                and "positions_count=3" in msg
                for msg in cm.output
            ),
            f"Expected structured log with state change details, got: {cm.output}",
        )

    def test_deactivate_kill_switch_logs_state_change(self) -> None:
        """deactivate_kill_switch should log state change with structured fields."""
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="runtime:manual",
        )

        with self.assertLogs(level=logging.INFO) as cm:
            deactivate_kill_switch(
                state,
                reason="telegram:/resume",
            )

        self.assertTrue(
            any(
                "old_state=active" in msg
                and "new_state=inactive" in msg
                and "telegram:/resume" in msg
                for msg in cm.output
            ),
            f"Expected structured log with state change details, got: {cm.output}",
        )

    def test_notify_fn_exception_does_not_propagate(self) -> None:
        """Exceptions in notify_fn should be caught and logged, not propagated."""
        def failing_notify(*args):
            raise RuntimeError("Telegram API error")

        state = RiskControlState(kill_switch_active=False)

        with self.assertLogs(level=logging.ERROR) as cm:
            # Should not raise
            new_state = activate_kill_switch(
                state,
                reason="runtime:manual",
                notify_fn=failing_notify,
            )

        self.assertTrue(new_state.kill_switch_active)
        self.assertTrue(
            any("Failed to send Kill-Switch activation notification" in msg for msg in cm.output),
            f"Expected error log about notification failure, got: {cm.output}",
        )


class ApplyKillSwitchEnvOverrideNotificationTests(TestCase):
    """Tests for notification integration in apply_kill_switch_env_override."""

    def test_env_override_activation_calls_notify_fn(self) -> None:
        """apply_kill_switch_env_override should call activate_notify_fn when activating."""
        mock_activate = mock.MagicMock()
        mock_deactivate = mock.MagicMock()
        state = RiskControlState(kill_switch_active=False)

        new_state, overridden = apply_kill_switch_env_override(
            state,
            kill_switch_env="true",
            positions_count=5,
            activate_notify_fn=mock_activate,
            deactivate_notify_fn=mock_deactivate,
        )

        self.assertTrue(new_state.kill_switch_active)
        self.assertTrue(overridden)
        mock_activate.assert_called_once()
        mock_deactivate.assert_not_called()

    def test_env_override_deactivation_calls_notify_fn(self) -> None:
        """apply_kill_switch_env_override should call deactivate_notify_fn when deactivating."""
        mock_activate = mock.MagicMock()
        mock_deactivate = mock.MagicMock()
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="runtime:manual",
        )

        new_state, overridden = apply_kill_switch_env_override(
            state,
            kill_switch_env="false",
            positions_count=0,
            activate_notify_fn=mock_activate,
            deactivate_notify_fn=mock_deactivate,
        )

        self.assertFalse(new_state.kill_switch_active)
        self.assertTrue(overridden)
        mock_activate.assert_not_called()
        mock_deactivate.assert_called_once()

    def test_env_not_set_does_not_call_notify_fn(self) -> None:
        """apply_kill_switch_env_override should not call notify_fn when env is not set."""
        mock_activate = mock.MagicMock()
        mock_deactivate = mock.MagicMock()
        state = RiskControlState(kill_switch_active=True)

        # Mock os.environ to ensure KILL_SWITCH is not set (isolate from .env)
        import os
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("KILL_SWITCH", None)
            new_state, overridden = apply_kill_switch_env_override(
                state,
                kill_switch_env=None,
                positions_count=0,
                activate_notify_fn=mock_activate,
                deactivate_notify_fn=mock_deactivate,
            )

        self.assertTrue(new_state.kill_switch_active)
        self.assertFalse(overridden)
        mock_activate.assert_not_called()
        mock_deactivate.assert_not_called()

    def test_no_state_change_does_not_call_notify_fn(self) -> None:
        """apply_kill_switch_env_override should not call notify_fn when state doesn't change."""
        mock_activate = mock.MagicMock()
        mock_deactivate = mock.MagicMock()

        # Already active, env says true - no change
        state = RiskControlState(
            kill_switch_active=True,
            kill_switch_reason="env:KILL_SWITCH",
        )

        new_state, overridden = apply_kill_switch_env_override(
            state,
            kill_switch_env="true",
            positions_count=0,
            activate_notify_fn=mock_activate,
            deactivate_notify_fn=mock_deactivate,
        )

        self.assertTrue(new_state.kill_switch_active)
        self.assertFalse(overridden)
        mock_activate.assert_not_called()
        mock_deactivate.assert_not_called()

        # Already inactive, env says false - no change
        state = RiskControlState(kill_switch_active=False)

        new_state, overridden = apply_kill_switch_env_override(
            state,
            kill_switch_env="false",
            positions_count=0,
            activate_notify_fn=mock_activate,
            deactivate_notify_fn=mock_deactivate,
        )

        self.assertFalse(new_state.kill_switch_active)
        self.assertFalse(overridden)
        mock_activate.assert_not_called()
        mock_deactivate.assert_not_called()
