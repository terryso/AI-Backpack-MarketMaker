"""
Telegram notification functionality.

This module handles sending notifications to Telegram including
trade signals and error messages.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from display.formatters import (
    build_entry_signal_message as _build_entry_signal_message,
    build_close_signal_message as _build_close_signal_message,
)


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes so Telegram receives plain text."""
    return ANSI_ESCAPE_RE.sub("", text)


def escape_markdown(text: str) -> str:
    """Escape characters that have special meaning in Telegram Markdown."""
    if not text:
        return text
    specials = r"_*[]()~`>#+-=|{}.!\\"
    return "".join(f"\\{char}" if char in specials else char for char in text)


def send_telegram_message(
    *,
    bot_token: str,
    default_chat_id: str,
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: Optional[str] = "Markdown",
) -> None:
    """Send a notification message to Telegram if credentials are configured.

    If `chat_id` is provided it will be used; otherwise `default_chat_id` is used.
    This allows sending different message types to a dedicated signals group.
    """
    effective_chat = (chat_id or default_chat_id or "").strip()
    if not bot_token or not effective_chat:
        return

    try:
        payload: Dict[str, Any] = {
            "chat_id": effective_chat,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            return

        response_text_lower = response.text.lower()
        logging.warning(
            "Telegram notification failed (%s): %s",
            response.status_code,
            response.text,
        )
        if (
            response.status_code == 400
            and "can't parse entities" in response_text_lower
            and parse_mode
        ):
            fallback_payload: Dict[str, Any] = {
                "chat_id": effective_chat,
                "text": strip_ansi_codes(text),
            }
            try:
                fallback_response = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=fallback_payload,
                    timeout=10,
                )
                if fallback_response.status_code != 200:
                    logging.warning(
                        "Telegram fallback notification failed (%s): %s",
                        fallback_response.status_code,
                        fallback_response.text,
                    )
            except Exception as fallback_exc:  # pragma: no cover - defensive logging only
                logging.error("Fallback Telegram message failed: %s", fallback_exc)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logging.error("Error sending Telegram message: %s", exc)


def send_entry_signal_to_telegram(
    *,
    coin: str,
    side: str,
    leverage_display: str,
    entry_price: float,
    quantity: float,
    margin_required: float,
    risk_usd: float,
    profit_target_price: float,
    stop_loss_price: float,
    gross_at_target: float,
    gross_at_stop: float,
    rr_display: str,
    entry_fee: float,
    confidence: float,
    reason_text_for_signal: str,
    liquidity: str,
    timestamp: str,
    send_fn: Callable[[str, Optional[str], Optional[str]], None],
    signals_chat_id: Optional[str],
) -> None:
    """Build and send the rich ENTRY Telegram signal.

    This helper centralises the use of strategy_core.build_entry_signal_message and
    the low-level Telegram sender, so callers only need to provide numeric
    values and metadata.
    """
    signal_text = _build_entry_signal_message(
        coin=coin,
        side=side,
        leverage_display=leverage_display,
        entry_price=entry_price,
        quantity=quantity,
        margin_required=margin_required,
        risk_usd=risk_usd,
        profit_target_price=profit_target_price,
        stop_loss_price=stop_loss_price,
        gross_at_target=gross_at_target,
        gross_at_stop=gross_at_stop,
        rr_display=rr_display,
        entry_fee=entry_fee,
        confidence=confidence,
        reason_text_for_signal=reason_text_for_signal,
        liquidity=liquidity,
        timestamp=timestamp,
    )
    send_fn(signal_text, signals_chat_id, "Markdown")


def send_close_signal_to_telegram(
    *,
    coin: str,
    side: str,
    quantity: float,
    entry_price: float,
    current_price: float,
    pnl: float,
    total_fees: float,
    net_pnl: float,
    margin: float,
    balance: float,
    reason_text_for_signal: str,
    timestamp: str,
    send_fn: Callable[[str, Optional[str], Optional[str]], None],
    signals_chat_id: Optional[str],
) -> None:
    """Build and send the rich CLOSE Telegram signal."""
    close_text = _build_close_signal_message(
        coin=coin,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        current_price=current_price,
        pnl=pnl,
        total_fees=total_fees,
        net_pnl=net_pnl,
        margin=margin,
        balance=balance,
        reason_text_for_signal=reason_text_for_signal,
        timestamp=timestamp,
    )
    send_fn(close_text, signals_chat_id, "Markdown")


# ──────────────────────── KILL-SWITCH NOTIFICATIONS ────────────────────────


def build_kill_switch_activated_message(
    *,
    reason: str,
    triggered_at: str,
    positions_count: int,
) -> str:
    """Build the Telegram message for Kill-Switch activation.

    Args:
        reason: The reason for Kill-Switch activation (e.g., "env:KILL_SWITCH",
            "runtime:manual", "daily_loss_limit").
        triggered_at: ISO 8601 UTC timestamp when Kill-Switch was triggered.
        positions_count: Current number of open positions.

    Returns:
        Formatted Markdown message string for Telegram.
    """
    # Map reason codes to human-readable descriptions
    reason_display = _format_kill_switch_reason(reason)

    message = (
        f"🚨 *Kill\\-Switch 已激活*\n\n"
        f"*触发原因:* {escape_markdown(reason_display)}\n"
        f"*触发时间:* `{triggered_at}`\n"
        f"*当前持仓:* {positions_count} 个\n\n"
        f"⚠️ 新开仓信号已被阻止，现有持仓的止损/止盈仍正常执行。\n\n"
        f"💡 恢复交易请使用: `/resume`"
    )
    return message


def build_kill_switch_deactivated_message(
    *,
    deactivated_at: str,
    reason: str,
) -> str:
    """Build the Telegram message for Kill-Switch deactivation.

    Args:
        deactivated_at: ISO 8601 UTC timestamp when Kill-Switch was deactivated.
        reason: The reason for deactivation (e.g., "runtime:resume",
            "telegram:/resume", "env:KILL_SWITCH").

    Returns:
        Formatted Markdown message string for Telegram.
    """
    reason_display = _format_kill_switch_deactivation_reason(reason)

    message = (
        f"✅ *Kill\\-Switch 已解除*\n\n"
        f"*解除时间:* `{deactivated_at}`\n"
        f"*解除原因:* {escape_markdown(reason_display)}\n\n"
        f"📈 交易功能已恢复正常，新开仓信号将被正常处理。"
    )
    return message


def _format_kill_switch_reason(reason: str) -> str:
    """Convert reason code to human-readable description for activation."""
    reason_map = {
        "env:KILL_SWITCH": "环境变量 KILL_SWITCH=true",
        "runtime:manual": "手动触发",
        "daily_loss_limit": "每日亏损限制",
        "telegram:/kill": "Telegram 命令 /kill",
    }
    return reason_map.get(reason, reason)


def _format_kill_switch_deactivation_reason(reason: str) -> str:
    """Convert reason code to human-readable description for deactivation."""
    reason_map = {
        "env:KILL_SWITCH": "环境变量 KILL_SWITCH=false",
        "runtime:resume": "运行时恢复",
        "telegram:/resume": "Telegram 命令 /resume",
        "daily_reset": "每日亏损限制手动重置",
    }
    return reason_map.get(reason, reason)


def notify_kill_switch_activated(
    *,
    reason: str,
    triggered_at: str,
    positions_count: int,
    bot_token: str,
    chat_id: str,
    send_fn: Optional[Callable[..., None]] = None,
) -> bool:
    """Send Kill-Switch activation notification to Telegram.

    This function handles the complete notification flow including:
    - Checking if Telegram is configured
    - Building the message
    - Sending via the provided send function or default

    Args:
        reason: The reason for Kill-Switch activation.
        triggered_at: ISO 8601 UTC timestamp when Kill-Switch was triggered.
        positions_count: Current number of open positions.
        bot_token: Telegram bot token.
        chat_id: Telegram chat ID.
        send_fn: Optional custom send function for testing. If None, uses
            send_telegram_message.

    Returns:
        True if notification was sent (or attempted), False if skipped due to
        missing configuration.
    """
    if not bot_token or not chat_id:
        logging.info(
            "Kill-Switch activation notification skipped: Telegram not configured "
            "(bot_token=%s, chat_id=%s)",
            "set" if bot_token else "missing",
            "set" if chat_id else "missing",
        )
        return False

    message = build_kill_switch_activated_message(
        reason=reason,
        triggered_at=triggered_at,
        positions_count=positions_count,
    )

    if send_fn is not None:
        send_fn(
            bot_token=bot_token,
            default_chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )
    else:
        send_telegram_message(
            bot_token=bot_token,
            default_chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )

    logging.info(
        "Kill-Switch activation notification sent: reason=%s, positions_count=%d",
        reason,
        positions_count,
    )
    return True


def notify_kill_switch_deactivated(
    *,
    deactivated_at: str,
    reason: str,
    bot_token: str,
    chat_id: str,
    send_fn: Optional[Callable[..., None]] = None,
) -> bool:
    """Send Kill-Switch deactivation notification to Telegram.

    This function handles the complete notification flow including:
    - Checking if Telegram is configured
    - Building the message
    - Sending via the provided send function or default

    Args:
        deactivated_at: ISO 8601 UTC timestamp when Kill-Switch was deactivated.
        reason: The reason for deactivation.
        bot_token: Telegram bot token.
        chat_id: Telegram chat ID.
        send_fn: Optional custom send function for testing. If None, uses
            send_telegram_message.

    Returns:
        True if notification was sent (or attempted), False if skipped due to
        missing configuration.
    """
    if not bot_token or not chat_id:
        logging.info(
            "Kill-Switch deactivation notification skipped: Telegram not configured "
            "(bot_token=%s, chat_id=%s)",
            "set" if bot_token else "missing",
            "set" if chat_id else "missing",
        )
        return False

    message = build_kill_switch_deactivated_message(
        deactivated_at=deactivated_at,
        reason=reason,
    )

    if send_fn is not None:
        send_fn(
            bot_token=bot_token,
            default_chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )
    else:
        send_telegram_message(
            bot_token=bot_token,
            default_chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )

    logging.info(
        "Kill-Switch deactivation notification sent: reason=%s",
        reason,
    )
    return True


# ──────────────────────── DAILY LOSS LIMIT NOTIFICATIONS ────────────────────────


def build_daily_loss_limit_triggered_message(
    *,
    loss_pct: float,
    limit_pct: float,
    daily_start_equity: float,
    current_equity: float,
) -> str:
    """Build the Telegram message for daily loss limit trigger.

    This function is the integration point for Story 7.3.4 to customize
    the notification message format.

    Args:
        loss_pct: Current daily loss percentage (negative value, e.g., -6.2).
        limit_pct: Configured daily loss limit threshold (positive value, e.g., 5.0).
        daily_start_equity: Starting equity for the current day.
        current_equity: Current total equity.

    Returns:
        Formatted Markdown message string for Telegram.
    """
    loss_amount = daily_start_equity - current_equity

    message = (
        f"⚠️ *每日亏损限制已触发*\n\n"
        f"*当日亏损:* `{loss_pct:.2f}%`\n"
        f"*亏损阈值:* `\\-{limit_pct:.2f}%`\n"
        f"*今日起始权益:* `${daily_start_equity:,.2f}`\n"
        f"*当前权益:* `${current_equity:,.2f}`\n"
        f"*亏损金额:* `${loss_amount:,.2f}`\n\n"
        f"🚨 Kill\\-Switch 已自动激活，新开仓信号已被阻止。\n\n"
        f"💡 恢复交易请使用: `/resume`\n"
        f"📊 查看状态请使用: `/status`"
    )
    return message


def notify_daily_loss_limit_triggered(
    *,
    loss_pct: float,
    limit_pct: float,
    daily_start_equity: float,
    current_equity: float,
    bot_token: str,
    chat_id: str,
    send_fn: Optional[Callable[..., None]] = None,
) -> bool:
    """Send daily loss limit trigger notification to Telegram.

    This is the integration point for Story 7.3.4. The function handles
    the complete notification flow including:
    - Checking if Telegram is configured
    - Building the message
    - Sending via the provided send function or default

    Args:
        loss_pct: Current daily loss percentage (negative value).
        limit_pct: Configured daily loss limit threshold (positive value).
        daily_start_equity: Starting equity for the current day.
        current_equity: Current total equity.
        bot_token: Telegram bot token.
        chat_id: Telegram chat ID.
        send_fn: Optional custom send function for testing.

    Returns:
        True if notification was sent (or attempted), False if skipped due to
        missing configuration.
    """
    if not bot_token or not chat_id:
        logging.info(
            "Daily loss limit notification skipped: Telegram not configured "
            "(bot_token=%s, chat_id=%s)",
            "set" if bot_token else "missing",
            "set" if chat_id else "missing",
        )
        return False

    message = build_daily_loss_limit_triggered_message(
        loss_pct=loss_pct,
        limit_pct=limit_pct,
        daily_start_equity=daily_start_equity,
        current_equity=current_equity,
    )

    if send_fn is not None:
        send_fn(
            bot_token=bot_token,
            default_chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )
    else:
        send_telegram_message(
            bot_token=bot_token,
            default_chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )

    logging.info(
        "Daily loss limit notification sent: loss_pct=%.2f%%, limit_pct=%.2f%%",
        loss_pct,
        limit_pct,
    )
    return True


def create_daily_loss_limit_notify_callback(
    bot_token: str,
    chat_id: str,
    send_fn: Optional[Callable[..., None]] = None,
) -> Optional[Callable[[float, float, float, float], None]]:
    """Create notification callback for daily loss limit trigger.

    This factory function creates a properly configured callback that can be
    passed to check_daily_loss_limit function.

    Args:
        bot_token: Telegram bot token.
        chat_id: Telegram chat ID.
        send_fn: Optional custom send function for testing.

    Returns:
        A callback function or None if Telegram is not configured.
    """
    if not bot_token or not chat_id:
        return None

    def notify(
        loss_pct: float,
        limit_pct: float,
        daily_start_equity: float,
        current_equity: float,
    ) -> None:
        notify_daily_loss_limit_triggered(
            loss_pct=loss_pct,
            limit_pct=limit_pct,
            daily_start_equity=daily_start_equity,
            current_equity=current_equity,
            bot_token=bot_token,
            chat_id=chat_id,
            send_fn=send_fn,
        )

    return notify


def create_kill_switch_notify_callbacks(
    bot_token: str,
    chat_id: str,
    send_fn: Optional[Callable[..., None]] = None,
) -> Tuple[
    Optional[Callable[[str, str, int], None]],
    Optional[Callable[[str, str], None]],
]:
    """Create notification callbacks for Kill-Switch state changes.

    This factory function creates properly configured callbacks that can be
    passed to activate_kill_switch and deactivate_kill_switch functions.

    Args:
        bot_token: Telegram bot token.
        chat_id: Telegram chat ID.
        send_fn: Optional custom send function for testing.

    Returns:
        A tuple of (activate_notify_fn, deactivate_notify_fn). Both will be
        None if Telegram is not configured (missing bot_token or chat_id).
    """
    if not bot_token or not chat_id:
        return None, None

    def activate_notify(reason: str, triggered_at: str, positions_count: int) -> None:
        notify_kill_switch_activated(
            reason=reason,
            triggered_at=triggered_at,
            positions_count=positions_count,
            bot_token=bot_token,
            chat_id=chat_id,
            send_fn=send_fn,
        )

    def deactivate_notify(deactivated_at: str, reason: str) -> None:
        notify_kill_switch_deactivated(
            deactivated_at=deactivated_at,
            reason=reason,
            bot_token=bot_token,
            chat_id=chat_id,
            send_fn=send_fn,
        )

    return activate_notify, deactivate_notify
