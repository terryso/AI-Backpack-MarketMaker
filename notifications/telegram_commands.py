"""
Telegram command receiving and parsing functionality.

This module handles receiving commands from Telegram Bot API via getUpdates
polling mechanism. It provides:
- TelegramCommand dataclass for structured command representation
- TelegramCommandHandler for polling and parsing commands
- Command handlers for /kill and /resume commands (Story 7.4.2)

This module is part of Epic 7.4: Telegram Command Integration.
Story 7.4.1: Implement Telegram command receiving mechanism.
Story 7.4.2: Implement /kill and /resume commands.
Story 7.4.5: Implement /help command and security validation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from core.risk_control import RiskControlState


@dataclass
class TelegramCommand:
    """Structured representation of a parsed Telegram command.
    
    Attributes:
        command: Command name without leading slash (e.g., "kill", "resume", "status").
        args: List of arguments split by whitespace (e.g., ["confirm"] for "/resume confirm").
        chat_id: Chat ID where the command was sent.
        message_id: Unique message ID within the chat.
        raw_text: Original message text including the command.
        raw_update: Complete update payload from Telegram API.
        user_id: Telegram user ID of the command sender (for permission control).
    """
    command: str
    args: List[str]
    chat_id: str
    message_id: int
    raw_text: str
    raw_update: Dict[str, Any] = field(default_factory=dict)
    user_id: str = ""


class TelegramCommandHandler:
    """Handler for receiving and parsing Telegram commands via getUpdates API.
    
    This class manages:
    - Polling Telegram Bot API for new updates
    - Filtering commands by allowed chat ID
    - Parsing command text into structured TelegramCommand objects
    - Tracking last_update_id to avoid duplicate processing
    
    Usage:
        handler = TelegramCommandHandler(
            bot_token="your_bot_token",
            allowed_chat_id="123456789",
        )
        commands = handler.poll_commands()
        for cmd in commands:
            print(f"Received command: /{cmd.command} {cmd.args}")
    """
    
    # API timeout for getUpdates (short polling, not long polling)
    DEFAULT_TIMEOUT = 5
    # Maximum number of updates to fetch per poll
    DEFAULT_LIMIT = 10
    
    def __init__(
        self,
        bot_token: str,
        allowed_chat_id: str,
        last_update_id: int = 0,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        """Initialize the command handler.
        
        Args:
            bot_token: Telegram Bot API token.
            allowed_chat_id: Only commands from this chat ID will be returned.
            last_update_id: Initial offset for getUpdates (0 = start from oldest).
            timeout: HTTP timeout for getUpdates request in seconds.
            limit: Maximum number of updates to fetch per poll.
        """
        self._bot_token = bot_token
        self._allowed_chat_id = str(allowed_chat_id).strip()
        self._last_update_id = last_update_id
        self._timeout = timeout
        self._limit = limit
    
    @property
    def last_update_id(self) -> int:
        """Current offset for getUpdates polling."""
        return self._last_update_id
    
    def poll_commands(self) -> List[TelegramCommand]:
        """Poll Telegram API for new commands.
        
        This method:
        1. Calls getUpdates with offset = last_update_id + 1
        2. Filters updates to only message type with text starting with /
        3. Filters by allowed_chat_id (logs WARNING for unauthorized chats)
        4. Parses command text into TelegramCommand objects
        5. Updates last_update_id to prevent duplicate processing
        
        Returns:
            List of parsed TelegramCommand objects from allowed chat.
            Empty list if no new commands, API error, or Telegram not configured.
        
        Note:
            Network errors and API failures are logged but do not raise exceptions.
            This ensures the main trading loop continues even if command polling fails.
        """
        if not self._bot_token or not self._allowed_chat_id:
            logging.debug(
                "Telegram command polling skipped: not configured "
                "(bot_token=%s, allowed_chat_id=%s)",
                "set" if self._bot_token else "missing",
                "set" if self._allowed_chat_id else "missing",
            )
            return []
        
        updates = self._fetch_updates()
        if updates is None:
            return []
        
        commands: List[TelegramCommand] = []
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                # Always update last_update_id to avoid reprocessing
                self._last_update_id = max(self._last_update_id, update_id)
            
            command = self._parse_update(update)
            if command is not None:
                commands.append(command)
        
        if commands:
            logging.debug(
                "Telegram commands polled: %d (last_update_id=%d)",
                len(commands),
                self._last_update_id,
            )
        
        return commands
    
    def _fetch_updates(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch updates from Telegram Bot API.
        
        Returns:
            List of update objects, or None if request failed.
        """
        url = f"https://api.telegram.org/bot{self._bot_token}/getUpdates"
        params: Dict[str, Any] = {
            "timeout": self._timeout,
            "limit": self._limit,
        }
        # Use offset = last_update_id + 1 to get only new updates
        if self._last_update_id > 0:
            params["offset"] = self._last_update_id + 1
        
        try:
            response = requests.get(url, params=params, timeout=self._timeout + 5)
            
            if response.status_code != 200:
                logging.warning(
                    "Failed to poll Telegram updates: HTTP %d | response=%s",
                    response.status_code,
                    response.text[:200] if response.text else "(empty)",
                )
                return None
            
            data = response.json()
            if not data.get("ok"):
                logging.warning(
                    "Telegram getUpdates returned ok=false: %s",
                    data.get("description", "unknown error"),
                )
                return None
            
            return data.get("result", [])
            
        except requests.exceptions.Timeout:
            logging.warning(
                "Telegram getUpdates request timed out after %ds",
                self._timeout + 5,
            )
            return None
        except requests.exceptions.RequestException as exc:
            logging.warning(
                "Telegram getUpdates request failed: %s",
                exc,
            )
            return None
        except ValueError as exc:
            # JSON decode error
            logging.warning(
                "Failed to parse Telegram getUpdates response: %s",
                exc,
            )
            return None
    
    def _parse_update(self, update: Dict[str, Any]) -> Optional[TelegramCommand]:
        """Parse a single update into a TelegramCommand.
        
        Args:
            update: Raw update object from Telegram API.
        
        Returns:
            TelegramCommand if update is a valid command from allowed chat,
            None otherwise.
        """
        update_id = update.get("update_id", "unknown")
        
        # Only process message type updates
        message = update.get("message")
        if not message:
            # Silently ignore non-message updates (callback_query, etc.)
            return None
        
        # Extract chat_id
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        
        # Check if from allowed chat
        if chat_id != self._allowed_chat_id:
            logging.warning(
                "Ignoring Telegram command from unauthorized chat: chat_id=%s | "
                "allowed_chat_id=%s | update_id=%s",
                chat_id,
                self._allowed_chat_id,
                update_id,
            )
            return None
        
        # Extract message text
        text = message.get("text", "")
        if not text:
            return None
        
        # Only process commands (text starting with /)
        text = text.strip()
        if not text.startswith("/"):
            return None
        
        # Parse command and arguments
        message_id = message.get("message_id", 0)
        command, args = self._parse_command_text(text)
        
        # Extract user_id from the 'from' field (sender information)
        from_user = message.get("from", {})
        user_id = str(from_user.get("id", ""))
        
        return TelegramCommand(
            command=command,
            args=args,
            chat_id=chat_id,
            message_id=message_id,
            raw_text=text,
            raw_update=update,
            user_id=user_id,
        )
    
    @staticmethod
    def _parse_command_text(text: str) -> tuple[str, List[str]]:
        """Parse command text into command name and arguments.
        
        Args:
            text: Message text starting with / (e.g., "/resume confirm").
        
        Returns:
            Tuple of (command_name, args_list).
            command_name is without leading slash.
            args_list may be empty.
        
        Examples:
            "/kill" -> ("kill", [])
            "/resume confirm" -> ("resume", ["confirm"])
            "/status" -> ("status", [])
            "/reset_daily" -> ("reset_daily", [])
        """
        # Remove leading slash and split by whitespace
        parts = text[1:].split()
        if not parts:
            return ("", [])
        
        # Handle @BotName suffix in commands (e.g., "/status@MyBot")
        command = parts[0]
        if "@" in command:
            command = command.split("@")[0]
        
        args = parts[1:] if len(parts) > 1 else []
        return (command, args)


def create_command_handler(
    bot_token: str,
    chat_id: str,
    last_update_id: int = 0,
) -> Optional[TelegramCommandHandler]:
    """Factory function to create a TelegramCommandHandler if configured.
    
    Args:
        bot_token: Telegram Bot API token.
        chat_id: Allowed chat ID for command filtering.
        last_update_id: Initial offset for getUpdates.
    
    Returns:
        TelegramCommandHandler instance if both bot_token and chat_id are set,
        None otherwise.
    """
    if not bot_token or not chat_id:
        return None
    return TelegramCommandHandler(
        bot_token=bot_token,
        allowed_chat_id=chat_id,
        last_update_id=last_update_id,
    )


def process_telegram_commands(
    commands: List[TelegramCommand],
    *,
    command_handlers: Optional[Dict[str, Callable[[TelegramCommand], None]]] = None,
) -> None:
    """Process a list of Telegram commands.
    
    This is a neutral dispatch entry point for command processing.
    Commands are dispatched to their registered handlers. Unknown commands
    are handled by the "__unknown__" handler if registered, otherwise logged.
    
    Args:
        commands: List of TelegramCommand objects to process.
        command_handlers: Optional dict mapping command names to handler functions.
            If not provided, commands are only logged.
            Special key "__unknown__" can be used for unknown command fallback.
    
    Note:
        All exceptions are caught and logged to prevent command processing
        from interrupting the main trading loop (AC3).
    """
    if not commands:
        return
    
    for cmd in commands:
        try:
            if command_handlers and cmd.command in command_handlers:
                command_handlers[cmd.command](cmd)
            elif command_handlers and "__unknown__" in command_handlers:
                # Use unknown handler for unrecognized commands (Story 7.4.5)
                command_handlers["__unknown__"](cmd)
            else:
                # Log unhandled commands at DEBUG level when no unknown handler
                logging.debug(
                    "Telegram command received (no handler): /%s %s | chat_id=%s",
                    cmd.command,
                    " ".join(cmd.args) if cmd.args else "",
                    cmd.chat_id,
                )
        except Exception as exc:
            # Catch all exceptions to prevent interrupting main loop (AC3)
            logging.error(
                "Error processing Telegram command /%s: %s",
                cmd.command,
                exc,
            )


# ═══════════════════════════════════════════════════════════════════
# HELP MESSAGE AND COMMAND REGISTRY (Story 7.4.5)
# ═══════════════════════════════════════════════════════════════════

# Command registry for help message generation
# Each entry: (command, description)
# This allows easy extension when new commands are added
COMMAND_REGISTRY: list[tuple[str, str]] = [
    ("/status", "查看 Bot 资金与盈利状态"),
    ("/risk", "查看风控配置与状态"),
    ("/kill", "激活 Kill\\-Switch，暂停所有新开仓"),
    ("/resume confirm", "解除 Kill\\-Switch（需二次确认）"),
    ("/reset\\_daily", "手动重置每日亏损基准"),
    ("/config list", "列出可配置项及当前值"),
    ("/config get KEY", "查看指定配置项详情"),
    ("/config set KEY VALUE", "修改运行时配置"),
    ("/help", "显示此帮助信息"),
]


def _build_help_message(risk_control_enabled: bool = True) -> str:
    """Build the help message from command registry.
    
    Args:
        risk_control_enabled: Whether risk control is enabled.
    
    Returns:
        MarkdownV2 formatted help message.
    """
    lines = ["📖 *可用命令列表*\n"]
    
    for cmd, desc in COMMAND_REGISTRY:
        lines.append(f"• `{cmd}` \\- {desc}")
    
    if not risk_control_enabled:
        lines.append("\n⚠️ _风控系统当前未启用_")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# COMMAND RESULT DATACLASS (Story 7.4.2)
# ═══════════════════════════════════════════════════════════════════


@dataclass
class CommandResult:
    """Result of processing a Telegram command.
    
    Attributes:
        success: Whether the command was processed successfully.
        message: Response message to send back to the user.
        state_changed: Whether the risk control state was modified.
        action: Action type for audit logging (e.g., "KILL_SWITCH_ACTIVATED").
    """
    success: bool
    message: str
    state_changed: bool = False
    action: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# KILL AND RESUME COMMAND HANDLERS (Story 7.4.2)
# ═══════════════════════════════════════════════════════════════════


def handle_kill_command(
    cmd: TelegramCommand,
    state: "RiskControlState",
    *,
    activate_fn: Optional[Callable[["RiskControlState", str, int], "RiskControlState"]] = None,
    positions_count: int = 0,
) -> CommandResult:
    """Handle the /kill command to activate Kill-Switch.
    
    This function activates Kill-Switch via the risk control API and returns
    a result with the response message.
    
    Args:
        cmd: The TelegramCommand object for /kill.
        state: The current RiskControlState to modify.
        activate_fn: Optional function to activate Kill-Switch. If None, uses
            the default activate_kill_switch from core.risk_control.
        positions_count: Current number of open positions for notification.
    
    Returns:
        CommandResult with success status and response message.
    
    References:
        - AC1: /kill 命令激活 Kill-Switch
        - AC3: 日志与审计
    """
    from core.risk_control import activate_kill_switch
    
    reason = "Manual trigger via Telegram"
    triggered_at = datetime.now(timezone.utc)
    
    # Log command receipt (AC3)
    logging.info(
        "Telegram /kill command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )
    
    # Check if already active
    if state.kill_switch_active:
        message = (
            "⚠️ *Kill\\-Switch 已处于激活状态*\n\n"
            f"*当前原因:* {_escape_markdown(state.kill_switch_reason or 'unknown')}\n"
            f"*激活时间:* `{state.kill_switch_triggered_at}`\n\n"
            "无需重复激活。"
        )
        logging.info(
            "Telegram /kill: Kill-Switch already active, reason=%s",
            state.kill_switch_reason,
        )
        return CommandResult(
            success=True,
            message=message,
            state_changed=False,
            action=None,
        )
    
    # Activate Kill-Switch
    if activate_fn is not None:
        new_state = activate_fn(state, reason, positions_count)
    else:
        new_state = activate_kill_switch(
            state,
            reason=reason,
            triggered_at=triggered_at,
            positions_count=positions_count,
        )
    
    # Copy state changes back to the mutable state object
    state.kill_switch_active = new_state.kill_switch_active
    state.kill_switch_reason = new_state.kill_switch_reason
    state.kill_switch_triggered_at = new_state.kill_switch_triggered_at
    
    # Build response message
    message = (
        "🚨 *Kill\\-Switch 已激活*\n\n"
        f"*触发原因:* {_escape_markdown(reason)}\n"
        f"*触发时间:* `{state.kill_switch_triggered_at}`\n"
        f"*当前持仓:* {positions_count} 个\n\n"
        "⚠️ 新开仓信号已被阻止，现有持仓的止损/止盈仍正常执行。\n\n"
        "💡 恢复交易请使用: `/resume confirm`"
    )
    
    # Log state change (AC3)
    logging.warning(
        "Telegram /kill: Kill-Switch activated | chat_id=%s | reason=%s | "
        "positions_count=%d | triggered_at=%s",
        cmd.chat_id,
        reason,
        positions_count,
        state.kill_switch_triggered_at,
    )
    
    return CommandResult(
        success=True,
        message=message,
        state_changed=True,
        action="KILL_SWITCH_ACTIVATED",
    )


def handle_resume_command(
    cmd: TelegramCommand,
    state: "RiskControlState",
    *,
    deactivate_fn: Optional[Callable[["RiskControlState", str], "RiskControlState"]] = None,
    force: bool = False,
) -> CommandResult:
    """Handle the /resume command to deactivate Kill-Switch.
    
    This function implements the two-step confirmation mechanism:
    - /resume without 'confirm' returns a prompt asking for confirmation
    - /resume confirm actually deactivates Kill-Switch (if allowed)
    
    Args:
        cmd: The TelegramCommand object for /resume.
        state: The current RiskControlState to modify.
        deactivate_fn: Optional function to deactivate Kill-Switch. If None, uses
            the default deactivate_kill_switch from core.risk_control.
        force: If True, force deactivation even if daily_loss_triggered is True.
    
    Returns:
        CommandResult with success status and response message.
    
    References:
        - AC2: /resume 与 /resume confirm 的二次确认机制
        - AC3: 日志与审计
    """
    from core.risk_control import deactivate_kill_switch
    
    # Log command receipt (AC3)
    logging.info(
        "Telegram /resume command received: chat_id=%s, message_id=%d, args=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
    )
    
    # Check if Kill-Switch is not active
    if not state.kill_switch_active:
        message = (
            "ℹ️ *Kill\\-Switch 当前未激活*\n\n"
            "交易功能正常运行中，无需恢复。"
        )
        logging.info(
            "Telegram /resume: Kill-Switch not active, no action needed"
        )
        return CommandResult(
            success=True,
            message=message,
            state_changed=False,
            action=None,
        )
    
    # Check for 'confirm' argument
    has_confirm = len(cmd.args) > 0 and cmd.args[0].lower() == "confirm"
    
    if not has_confirm:
        # Return prompt for confirmation (AC2)
        message = (
            "⚠️ *确认解除 Kill\\-Switch*\n\n"
            f"*当前状态:* Kill\\-Switch 激活中\n"
            f"*激活原因:* {_escape_markdown(state.kill_switch_reason or 'unknown')}\n"
            f"*激活时间:* `{state.kill_switch_triggered_at}`\n\n"
            "🔐 解除 Kill\\-Switch 将恢复新开仓信号处理。\n\n"
            "请发送 `/resume confirm` 确认解除。"
        )
        logging.info(
            "Telegram /resume: confirmation required, state unchanged | "
            "chat_id=%s | current_reason=%s",
            cmd.chat_id,
            state.kill_switch_reason,
        )
        return CommandResult(
            success=True,
            message=message,
            state_changed=False,
            action="RESUME_PENDING_CONFIRM",
        )
    
    # Check if daily loss triggered and force is not set
    if state.daily_loss_triggered and not force:
        message = (
            "❌ *无法解除 Kill\\-Switch*\n\n"
            "*原因:* 每日亏损限制仍在生效\n"
            f"*当日亏损:* `{state.daily_loss_pct:.2f}%`\n\n"
            "💡 如需强制恢复，请使用 `/reset_daily` 重置每日亏损限制后再试。"
        )
        logging.warning(
            "Telegram /resume confirm: blocked by daily_loss_triggered | "
            "chat_id=%s | daily_loss_pct=%.2f%%",
            cmd.chat_id,
            state.daily_loss_pct,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="RESUME_BLOCKED_DAILY_LOSS",
        )
    
    # Deactivate Kill-Switch
    reason = "telegram:/resume"
    if deactivate_fn is not None:
        new_state = deactivate_fn(state, reason)
    else:
        new_state = deactivate_kill_switch(
            state,
            reason=reason,
        )
    
    # Copy state changes back to the mutable state object
    state.kill_switch_active = new_state.kill_switch_active
    state.kill_switch_reason = new_state.kill_switch_reason
    
    deactivated_at = datetime.now(timezone.utc).isoformat()
    
    # Build response message
    message = (
        "✅ *Kill\\-Switch 已解除*\n\n"
        f"*解除时间:* `{deactivated_at}`\n"
        f"*解除原因:* Telegram 命令 /resume confirm\n\n"
        "📈 交易功能已恢复正常，新开仓信号将被正常处理。"
    )
    
    # Log state change (AC3)
    logging.info(
        "Telegram /resume confirm: Kill-Switch deactivated | chat_id=%s | "
        "reason=%s | deactivated_at=%s",
        cmd.chat_id,
        reason,
        deactivated_at,
    )
    
    return CommandResult(
        success=True,
        message=message,
        state_changed=True,
        action="KILL_SWITCH_DEACTIVATED",
    )


def _escape_markdown(text: str) -> str:
    """Escape characters that have special meaning in Telegram MarkdownV2.
    
    Args:
        text: The text to escape.
    
    Returns:
        Escaped text safe for MarkdownV2.
    """
    if not text:
        return text
    specials = r"_*[]()~`>#+-=|{}.!\\"
    return "".join(f"\\{char}" if char in specials else char for char in text)


def handle_status_command(
    cmd: TelegramCommand,
    *,
    balance: float,
    total_equity: Optional[float],
    total_margin: float,
    positions_count: int,
    start_capital: float,
    sortino_ratio: Optional[float],
    kill_switch_active: bool = False,
) -> CommandResult:
    """Handle the /status command to show Bot profit/loss status.
    
    This command displays the current financial status of the bot,
    similar to the PORTFOLIO SUMMARY shown in the terminal.
    
    Args:
        cmd: The TelegramCommand object for /status.
        balance: Current available balance.
        total_equity: Current total equity.
        total_margin: Total margin allocated to positions.
        positions_count: Number of open positions.
        start_capital: Starting capital for return calculation.
        sortino_ratio: Current Sortino ratio (or None if unavailable).
        kill_switch_active: Whether Kill-Switch is active (for status indicator).
    
    Returns:
        CommandResult with success status and response message.
    """
    logging.info(
        "Telegram /status command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )

    # Calculate return percentage
    if total_equity is None or total_equity != total_equity:
        equity_display = "N/A"
        return_pct_display = "N/A"
        unrealized_pnl_display = "N/A"
    else:
        equity_display = f"${total_equity:,.2f}"
        if start_capital > 0:
            return_pct = ((total_equity - start_capital) / start_capital) * 100
            return_pct_display = f"{return_pct:+.2f}%"
        else:
            return_pct_display = "N/A"
        # Unrealized PnL = Total Equity - Balance - Margin
        unrealized_pnl = total_equity - balance - total_margin
        unrealized_pnl_display = f"${unrealized_pnl:+,.2f}"

    # Sortino ratio display
    if sortino_ratio is not None:
        sortino_display = f"{sortino_ratio:+.2f}"
    else:
        sortino_display = "N/A"

    # Trading status indicator
    if kill_switch_active:
        trading_status = "🔴 已暂停"
    else:
        trading_status = "🟢 正常"

    message = (
        "📊 *Bot 状态*\n\n"
        f"*交易状态:* {trading_status}\n"
        f"*可用余额:* `${balance:,.2f}`\n"
    )
    
    if total_margin > 0:
        message += f"*已用保证金:* `${total_margin:,.2f}`\n"
    
    message += (
        f"*总权益:* `{equity_display} ({return_pct_display})`\n"
        f"*未实现盈亏:* `{unrealized_pnl_display}`\n"
        f"*Sortino Ratio:* `{sortino_display}`\n"
        f"*持仓数量:* {positions_count}"
    )

    logging.info(
        "Telegram /status snapshot | chat_id=%s | balance=%.2f | equity=%s | "
        "positions=%d | sortino=%s",
        cmd.chat_id,
        balance,
        equity_display,
        positions_count,
        sortino_display,
    )

    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="BOT_STATUS",
    )


def handle_risk_command(
    cmd: TelegramCommand,
    state: "RiskControlState",
    *,
    total_equity: Optional[float],
    positions_count: int,
    risk_control_enabled: bool,
    daily_loss_limit_enabled: bool,
    daily_loss_limit_pct: float,
) -> CommandResult:
    """Handle the /risk command to show risk control status.
    
    This command displays the current risk control configuration and state,
    including Kill-Switch status and daily loss limit information.
    
    Args:
        cmd: The TelegramCommand object for /risk.
        state: The current RiskControlState.
        total_equity: Current total equity.
        positions_count: Number of open positions.
        risk_control_enabled: Whether risk control is enabled.
        daily_loss_limit_enabled: Whether daily loss limit is enabled.
        daily_loss_limit_pct: Daily loss limit percentage threshold.
    
    Returns:
        CommandResult with success status and response message.
    """
    logging.info(
        "Telegram /risk command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )

    if not risk_control_enabled:
        message = (
            "🛡 *风控状态*\n\n"
            "⚠️ 风控系统未启用。\n"
            "请检查 `RISK_CONTROL_ENABLED` 配置。"
        )
        return CommandResult(
            success=True,
            message=message,
            state_changed=False,
            action=None,
        )

    kill_active = state.kill_switch_active
    daily_loss_pct = state.daily_loss_pct
    daily_triggered = state.daily_loss_triggered
    daily_start_equity = state.daily_start_equity

    if total_equity is None or total_equity != total_equity:
        equity_display = "N/A"
    else:
        equity_display = f"${total_equity:,.2f}"

    if daily_start_equity is None or daily_start_equity <= 0:
        start_equity_display = "N/A"
    else:
        start_equity_display = f"${daily_start_equity:,.2f}"

    kill_status = "🟢 已关闭"
    if kill_active:
        kill_status = "🔴 已激活"

    risk_flags = []
    if kill_active:
        risk_flags.append("🔴 Kill\\-Switch 已激活")
    if daily_triggered:
        risk_flags.append("⚠️ 日亏限制已触发")

    flags_line = "".join(f"\n{flag}" for flag in risk_flags) if risk_flags else ""

    loss_pct_display = f"{daily_loss_pct:.2f}%"
    limit_pct_display = f"\\-{daily_loss_limit_pct:.2f}%" if daily_loss_limit_enabled else "已关闭"

    reason = state.kill_switch_reason or "无"
    triggered_at = state.kill_switch_triggered_at or "N/A"

    message = (
        "🛡 *风控状态*\n\n"
        f"*Kill\\-Switch:* {kill_status}\n"
        f"*触发原因:* {_escape_markdown(reason)}\n"
        f"*触发时间:* `{triggered_at}`\n\n"
        f"*当日亏损:* `{loss_pct_display}`\n"
        f"*亏损阈值:* `{limit_pct_display}`\n"
        f"*今日起始权益:* `{start_equity_display}`\n"
        f"*当前权益:* `{equity_display}`\n\n"
        f"*风控开关:* {'✅ 启用' if risk_control_enabled else '❌ 关闭'}\n"
        f"*每日亏损限制:* {'✅ 启用' if daily_loss_limit_enabled else '❌ 关闭'}"
        f"{flags_line}"
    )

    logging.info(
        "Telegram /risk snapshot | chat_id=%s | kill_switch_active=%s | "
        "daily_loss_pct=%.2f | daily_loss_triggered=%s | equity=%s | positions=%d",
        cmd.chat_id,
        kill_active,
        daily_loss_pct,
        daily_triggered,
        equity_display,
        positions_count,
    )

    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="RISK_CONTROL_STATUS",
    )


def handle_reset_daily_command(
    cmd: TelegramCommand,
    state: "RiskControlState",
    *,
    total_equity: Optional[float],
    risk_control_enabled: bool,
    reset_fn: Optional[Callable[["RiskControlState", float, str], "RiskControlState"]] = None,
) -> CommandResult:
    """Handle the /reset_daily command to manually reset daily loss baseline.

    This function resets the daily loss baseline to the current equity, allowing
    users to start a new risk window after reviewing a large drawdown day.

    IMPORTANT: This command does NOT automatically deactivate Kill-Switch.
    Users must explicitly call /resume confirm after /reset_daily to resume
    trading. This design prevents accidental resumption after large losses.

    Args:
        cmd: The TelegramCommand object for /reset_daily.
        state: The current RiskControlState to modify.
        total_equity: Current total account equity for the new baseline.
        risk_control_enabled: Whether risk control is globally enabled.
        reset_fn: Optional function to reset daily baseline. If None, uses
            the default reset_daily_baseline from core.risk_control.

    Returns:
        CommandResult with success status and response message.

    References:
        - AC1: /reset_daily 正确重置每日亏损基准
        - AC2: 与 Kill-Switch / 每日亏损限制的协同行为
        - AC3: 用户反馈与文案
        - AC4: 安全性、健壮性与审计
    """
    from core.risk_control import reset_daily_baseline

    # Log command receipt (AC4)
    logging.info(
        "Telegram /reset_daily command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )

    # Check if risk control is enabled (AC3 - degradation)
    if not risk_control_enabled:
        message = (
            "⚠️ *无法重置每日基准*\n\n"
            "风控系统未启用，无法执行此操作。\n"
            "请检查 `RISK_CONTROL_ENABLED` 配置。"
        )
        logging.warning(
            "Telegram /reset_daily: risk control not enabled | chat_id=%s",
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action=None,
        )

    # Check if equity is available (AC3 - degradation)
    if total_equity is None or total_equity != total_equity:  # NaN check
        message = (
            "⚠️ *无法重置每日基准*\n\n"
            "当前权益数据不可用，无法执行此操作。\n"
            "请稍后重试。"
        )
        logging.warning(
            "Telegram /reset_daily: equity unavailable | chat_id=%s | equity=%s",
            cmd.chat_id,
            total_equity,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action=None,
        )

    # Capture old values for response message
    old_daily_start_equity = state.daily_start_equity
    old_daily_loss_pct = state.daily_loss_pct
    old_daily_loss_triggered = state.daily_loss_triggered
    kill_switch_active = state.kill_switch_active

    # Reset daily baseline
    reason = "telegram:/reset_daily"
    if reset_fn is not None:
        new_state = reset_fn(state, total_equity, reason)
    else:
        new_state = reset_daily_baseline(
            state,
            total_equity,
            reason=reason,
        )

    # Copy state changes back to the mutable state object
    state.daily_start_equity = new_state.daily_start_equity
    state.daily_start_date = new_state.daily_start_date
    state.daily_loss_pct = new_state.daily_loss_pct
    state.daily_loss_triggered = new_state.daily_loss_triggered

    # Build response message (AC3)
    equity_display = f"${total_equity:,.2f}"
    old_equity_display = (
        f"${old_daily_start_equity:,.2f}"
        if old_daily_start_equity is not None
        else "N/A"
    )

    # Determine next step guidance based on Kill-Switch status
    if kill_switch_active:
        next_step = (
            "\n\n⚠️ *Kill\\-Switch 仍处于激活状态*\n"
            "如需恢复交易，请发送 `/resume confirm`"
        )
    else:
        next_step = "\n\n✅ 交易功能正常运行中。"

    message = (
        "🧮 *每日亏损基准已重置*\n\n"
        f"*新起始权益:* `{equity_display}`\n"
        f"*原起始权益:* `{old_equity_display}`\n"
        f"*当前亏损:* `0\\.00%`\n"
        f"*原亏损:* `{old_daily_loss_pct:.2f}%`\n"
        f"*日亏触发标志:* `{old_daily_loss_triggered}` → `False`"
        f"{next_step}"
    )

    # Log state change (AC4)
    logging.info(
        "Telegram /reset_daily: daily baseline reset | chat_id=%s | "
        "old_equity=%s | new_equity=%.2f | old_loss_pct=%.2f%% | "
        "old_triggered=%s | kill_switch_active=%s",
        cmd.chat_id,
        old_equity_display,
        total_equity,
        old_daily_loss_pct,
        old_daily_loss_triggered,
        kill_switch_active,
    )

    return CommandResult(
        success=True,
        message=message,
        state_changed=True,
        action="DAILY_BASELINE_RESET",
    )


# ═══════════════════════════════════════════════════════════════════
# HELP AND UNKNOWN COMMAND HANDLERS (Story 7.4.5)
# ═══════════════════════════════════════════════════════════════════


def handle_help_command(
    cmd: TelegramCommand,
    *,
    risk_control_enabled: bool = True,
) -> CommandResult:
    """Handle the /help command to display available commands.

    This function returns a structured help message listing all available
    Telegram commands with their descriptions.

    Args:
        cmd: The TelegramCommand object for /help.
        risk_control_enabled: Whether risk control is globally enabled.

    Returns:
        CommandResult with success status and help message.

    References:
        - AC1: /help 返回完整且可扩展的命令帮助列表
    """
    # Log command receipt
    logging.info(
        "Telegram /help command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )

    message = _build_help_message(risk_control_enabled=risk_control_enabled)

    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="HELP_DISPLAYED",
    )


def handle_unknown_command(
    cmd: TelegramCommand,
    *,
    risk_control_enabled: bool = True,
) -> CommandResult:
    """Handle unknown commands by returning help information.

    This function provides a fallback for unrecognized commands, returning
    a friendly message with the available command list.

    Args:
        cmd: The TelegramCommand object for the unknown command.
        risk_control_enabled: Whether risk control is globally enabled.

    Returns:
        CommandResult with success status and unknown command message.

    References:
        - AC3: 未知命令统一回退到帮助信息
    """
    # Log unknown command
    logging.info(
        "Telegram unknown command received: /%s | chat_id=%s, message_id=%d",
        cmd.command,
        cmd.chat_id,
        cmd.message_id,
    )

    help_content = _build_help_message(risk_control_enabled=risk_control_enabled)
    message = (
        f"❓ *未知命令:* `/{_escape_markdown(cmd.command)}`\n\n"
        f"{help_content}"
    )

    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="UNKNOWN_COMMAND",
    )


# ═══════════════════════════════════════════════════════════════════
# CONFIG COMMAND HANDLERS (Story 8.2)
# ═══════════════════════════════════════════════════════════════════

# Config key descriptions for user-friendly output
CONFIG_KEY_DESCRIPTIONS: dict[str, str] = {
    "TRADING_BACKEND": "交易执行后端",
    "MARKET_DATA_BACKEND": "行情数据源",
    "TRADEBOT_INTERVAL": "交易循环间隔",
    "TRADEBOT_LLM_TEMPERATURE": "LLM 采样温度",
    "TRADEBOT_LOOP_ENABLED": "主循环总开关 (false=暂停 bot, true=恢复运行)",
}

# Config keys actually exposed via /config list|get|set.
# 当前版本支持对 interval、LLM temperature 与 TRADEBOT_LOOP_ENABLED 进行运行时调整，
# backend 两个 key 仍然由 .env + 重启决定。
CONFIG_KEYS_FOR_TELEGRAM: tuple[str, ...] = (
    "TRADEBOT_INTERVAL",
    "TRADEBOT_LLM_TEMPERATURE",
    "TRADEBOT_LOOP_ENABLED",
)


def _get_config_value_info(key: str) -> tuple[str, str]:
    """Get the current effective value and valid range/enum description for a config key.
    
    Args:
        key: Configuration key name.
        
    Returns:
        Tuple of (current_value_str, valid_values_description).
    """
    from config.settings import (
        get_effective_trading_backend,
        get_effective_market_data_backend,
        get_effective_interval,
        get_effective_llm_temperature,
        get_effective_tradebot_loop_enabled,
    )
    from config.runtime_overrides import (
        VALID_TRADING_BACKENDS,
        VALID_MARKET_DATA_BACKENDS,
        VALID_INTERVALS,
        LLM_TEMPERATURE_MIN,
        LLM_TEMPERATURE_MAX,
        _interval_sort_key,
    )
    
    if key == "TRADING_BACKEND":
        current = get_effective_trading_backend()
        valid = ", ".join(sorted(VALID_TRADING_BACKENDS))
        return current, f"可选值: {valid}"
    
    if key == "MARKET_DATA_BACKEND":
        current = get_effective_market_data_backend()
        valid = ", ".join(sorted(VALID_MARKET_DATA_BACKENDS))
        return current, f"可选值: {valid}"
    
    if key == "TRADEBOT_INTERVAL":
        current = get_effective_interval()
        valid = ", ".join(sorted(VALID_INTERVALS, key=_interval_sort_key))
        return current, f"可选值: {valid}"
    
    if key == "TRADEBOT_LLM_TEMPERATURE":
        current = str(get_effective_llm_temperature())
        return current, f"范围: {LLM_TEMPERATURE_MIN} - {LLM_TEMPERATURE_MAX}"
    
    if key == "TRADEBOT_LOOP_ENABLED":
        current = "true" if get_effective_tradebot_loop_enabled() else "false"
        return current, "可选值: true, false (仅影响当前进程的主循环，不修改 .env)"
    
    return "N/A", "未知配置项"


def handle_config_list_command(cmd: TelegramCommand) -> CommandResult:
    """Handle the /config list subcommand to list all configurable keys.
    
    This function returns a list of all whitelisted configuration keys
    with their current effective values.
    
    Args:
        cmd: The TelegramCommand object for /config list.
        
    Returns:
        CommandResult with success status and config list message.
        
    References:
        - AC1: /config list 返回 4 个白名单配置项及其当前生效值
    """
    from config.runtime_overrides import get_override_whitelist
    
    logging.info(
        "Telegram /config list command received: chat_id=%s, message_id=%d",
        cmd.chat_id,
        cmd.message_id,
    )
    
    lines = ["⚙️ *可配置项列表*\n"]
    
    # Only expose a curated subset of runtime-configurable keys to Telegram.
    for key in CONFIG_KEYS_FOR_TELEGRAM:
        current_value, _ = _get_config_value_info(key)
        description = CONFIG_KEY_DESCRIPTIONS.get(key, key)
        # Escape special characters for MarkdownV2
        escaped_key = _escape_markdown(key)
        escaped_value = _escape_markdown(current_value)
        lines.append(f"• `{escaped_key}`")
        lines.append(f"  {_escape_markdown(description)}: `{escaped_value}`")
    
    lines.append("\n💡 使用 `/config get KEY` 查看详情")
    lines.append("💡 使用 `/config set KEY VALUE` 修改配置")
    
    message = "\n".join(lines)
    
    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="CONFIG_LIST",
    )


def handle_config_get_command(cmd: TelegramCommand, key: str) -> CommandResult:
    """Handle the /config get <KEY> subcommand to get a specific config value.
    
    Args:
        cmd: The TelegramCommand object for /config get.
        key: The configuration key to retrieve.
        
    Returns:
        CommandResult with success status and config value message.
        
    References:
        - AC2: /config get <KEY> 返回当前值和合法取值范围/枚举说明
    """
    logging.info(
        "Telegram /config get command received: chat_id=%s, message_id=%d, key=%s",
        cmd.chat_id,
        cmd.message_id,
        key,
    )
    
    # Normalize key to uppercase for comparison
    normalized_key = key.strip().upper()
    
    # Only a subset of keys are exposed via Telegram /config get.
    if normalized_key not in CONFIG_KEYS_FOR_TELEGRAM:
        # Return error with list of supported keys
        supported_keys = ", ".join(
            f"`{_escape_markdown(k)}`" for k in CONFIG_KEYS_FOR_TELEGRAM
        )
        message = (
            f"❌ *无效的配置项:* `{_escape_markdown(key)}`\n\n"
            f"支持的配置项:\n{supported_keys}"
        )
        logging.warning(
            "Telegram /config get: invalid key '%s' | chat_id=%s",
            key,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="CONFIG_GET_INVALID_KEY",
        )
    
    current_value, valid_range = _get_config_value_info(normalized_key)
    description = CONFIG_KEY_DESCRIPTIONS.get(normalized_key, normalized_key)
    
    message = (
        f"⚙️ *配置项详情*\n\n"
        f"*名称:* `{_escape_markdown(normalized_key)}`\n"
        f"*说明:* {_escape_markdown(description)}\n"
        f"*当前值:* `{_escape_markdown(current_value)}`\n"
        f"*{_escape_markdown(valid_range)}*"
    )
    
    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="CONFIG_GET",
    )


def _check_admin_permission(cmd: TelegramCommand) -> tuple[bool, str]:
    """Check if the command sender is an authorized admin.
    
    Args:
        cmd: The TelegramCommand object containing user_id.
        
    Returns:
        Tuple of (is_admin, admin_user_id).
        is_admin is True if the sender is authorized.
        admin_user_id is the configured admin ID (for logging).
    """
    from config.settings import get_telegram_admin_user_id
    
    admin_user_id = get_telegram_admin_user_id()
    
    # If no admin is configured, deny all modifications (secure default)
    if not admin_user_id:
        return False, ""
    
    # Check if sender matches admin
    sender_user_id = cmd.user_id.strip()
    if not sender_user_id:
        return False, admin_user_id
    
    return sender_user_id == admin_user_id, admin_user_id


def _log_config_audit(
    *,
    user_id: str,
    key: str,
    old_value: str,
    new_value: str,
    success: bool,
    chat_id: str,
) -> None:
    """Write structured audit log for config changes.
    
    This function logs configuration changes in a structured format
    for security auditing and compliance purposes.
    
    Args:
        user_id: Telegram user ID of the requester.
        key: Configuration key being modified.
        old_value: Previous value before change.
        new_value: New value after change.
        success: Whether the change was successful.
        chat_id: Chat ID where the command was received.
        
    Note:
        - Uses WARNING level for successful changes (security-relevant events)
        - Avoids logging sensitive values (API keys, secrets)
        - Format is compatible with existing logging infrastructure
    """
    from datetime import datetime, timezone
    
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Audit log for successful config changes (AC3)
    # Using WARNING level as this is a security-relevant event
    logging.warning(
        "CONFIG_AUDIT | timestamp=%s | user_id=%s | chat_id=%s | key=%s | "
        "old_value=%s | new_value=%s | success=%s",
        timestamp,
        user_id,
        chat_id,
        key,
        old_value,
        new_value,
        success,
    )


def handle_config_set_command(
    cmd: TelegramCommand,
    key: str,
    value: str,
) -> CommandResult:
    """Handle the /config set <KEY> <VALUE> subcommand to set a config value.
    
    This function implements admin-only permission control (AC2) and
    structured audit logging (AC3) for configuration changes.
    
    Args:
        cmd: The TelegramCommand object for /config set.
        key: The configuration key to set.
        value: The new value to set.
        
    Returns:
        CommandResult with success status and result message.
        
    References:
        - Story 8.3 AC2: /config set 仅在请求方 user_id 匹配管理员配置时才会执行
        - Story 8.3 AC3: 每次成功的 /config set 调用都会写入审计日志
    """
    from config.runtime_overrides import (
        validate_override_value,
        set_runtime_override,
        get_runtime_override,
    )
    from config.settings import (
        get_effective_trading_backend,
        get_effective_market_data_backend,
        get_effective_interval,
        get_effective_llm_temperature,
        get_effective_tradebot_loop_enabled,
    )
    
    logging.info(
        "Telegram /config set command received: chat_id=%s, message_id=%d, "
        "user_id=%s, key=%s, value=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.user_id,
        key,
        value,
    )
    
    # ─────────────────────────────────────────────────────────────────
    # Permission Check (AC2): Only admin can execute /config set
    # ─────────────────────────────────────────────────────────────────
    is_admin, admin_user_id = _check_admin_permission(cmd)
    
    if not is_admin:
        # Log unauthorized attempt
        logging.warning(
            "Telegram /config set: permission denied | user_id=%s | "
            "admin_user_id=%s | chat_id=%s | key=%s",
            cmd.user_id,
            admin_user_id if admin_user_id else "(not configured)",
            cmd.chat_id,
            key,
        )
        
        # Return user-friendly error message (AC2)
        if not admin_user_id:
            message = (
                "🔒 *无权限修改配置*\n\n"
                "管理员 User ID 未配置，所有配置修改请求已被拒绝。\n\n"
                "💡 请在 `.env` 中设置 `TELEGRAM_ADMIN_USER_ID` 后重启 Bot。\n"
                "📖 您仍可使用 `/config list` 和 `/config get` 查看配置。"
            )
        else:
            message = (
                "🔒 *无权限修改配置*\n\n"
                "您没有权限执行此操作，只能查看配置。\n\n"
                "📖 您可以使用 `/config list` 和 `/config get` 查看配置。"
            )
        
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="CONFIG_SET_PERMISSION_DENIED",
        )
    # Normalize key to uppercase for comparison
    normalized_key = key.strip().upper()
    
    # Only a subset of keys are exposed via Telegram /config set.
    if normalized_key not in CONFIG_KEYS_FOR_TELEGRAM:
        # Return error with list of supported keys
        supported_keys = ", ".join(
            f"`{_escape_markdown(k)}`" for k in CONFIG_KEYS_FOR_TELEGRAM
        )
        message = (
            f"❌ *无效的配置项:* `{_escape_markdown(key)}`\n\n"
            f"支持的配置项:\n{supported_keys}"
        )
        logging.warning(
            "Telegram /config set: invalid key '%s' | chat_id=%s",
            key,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="CONFIG_SET_INVALID_KEY",
        )
    
    # Get old value before setting
    if normalized_key == "TRADING_BACKEND":
        old_value = get_effective_trading_backend()
    elif normalized_key == "MARKET_DATA_BACKEND":
        old_value = get_effective_market_data_backend()
    elif normalized_key == "TRADEBOT_INTERVAL":
        old_value = get_effective_interval()
    elif normalized_key == "TRADEBOT_LLM_TEMPERATURE":
        old_value = str(get_effective_llm_temperature())
    elif normalized_key == "TRADEBOT_LOOP_ENABLED":
        old_value = "true" if get_effective_tradebot_loop_enabled() else "false"
    else:
        old_value = "N/A"
    
    # Validate the value
    is_valid, error_msg = validate_override_value(normalized_key, value)
    
    if not is_valid:
        _, valid_range = _get_config_value_info(normalized_key)
        message = (
            f"❌ *无效的配置值*\n\n"
            f"*配置项:* `{_escape_markdown(normalized_key)}`\n"
            f"*输入值:* `{_escape_markdown(value)}`\n"
            f"*错误:* {_escape_markdown(error_msg or '未知错误')}\n\n"
            f"*{_escape_markdown(valid_range)}*"
        )
        logging.warning(
            "Telegram /config set: invalid value '%s' for key '%s' | chat_id=%s | error=%s",
            value,
            normalized_key,
            cmd.chat_id,
            error_msg,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="CONFIG_SET_INVALID_VALUE",
        )
    
    # Set the runtime override
    # Normalize value for enum-like keys
    if normalized_key in ("TRADING_BACKEND", "MARKET_DATA_BACKEND", "TRADEBOT_INTERVAL"):
        normalized_value = value.strip().lower()
    elif normalized_key == "TRADEBOT_LLM_TEMPERATURE":
        normalized_value = float(value)
    elif normalized_key == "TRADEBOT_LOOP_ENABLED":
        normalized_value = value.strip().lower()
    else:
        normalized_value = value
    
    success, set_error = set_runtime_override(normalized_key, normalized_value, validate=False)
    
    if not success:
        message = (
            f"❌ *配置更新失败*\n\n"
            f"*配置项:* `{_escape_markdown(normalized_key)}`\n"
            f"*错误:* {_escape_markdown(set_error or '未知错误')}"
        )
        logging.error(
            "Telegram /config set: failed to set override | key=%s | value=%s | error=%s",
            normalized_key,
            value,
            set_error,
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="CONFIG_SET_FAILED",
        )
    
    # Get new effective value
    new_value, _ = _get_config_value_info(normalized_key)
    description = CONFIG_KEY_DESCRIPTIONS.get(normalized_key, normalized_key)
    
    message = (
        f"✅ *配置已更新*\n\n"
        f"*配置项:* `{_escape_markdown(normalized_key)}`\n"
        f"*说明:* {_escape_markdown(description)}\n"
        f"*原值:* `{_escape_markdown(old_value)}`\n"
        f"*新值:* `{_escape_markdown(new_value)}`"
    )
    
    # ─────────────────────────────────────────────────────────────────
    # Audit Log (AC3): Write structured audit log for successful changes
    # ─────────────────────────────────────────────────────────────────
    _log_config_audit(
        user_id=cmd.user_id,
        key=normalized_key,
        old_value=old_value,
        new_value=new_value,
        success=True,
        chat_id=cmd.chat_id,
    )
    
    logging.info(
        "Telegram /config set: override updated | chat_id=%s | key=%s | old=%s | new=%s",
        cmd.chat_id,
        normalized_key,
        old_value,
        new_value,
    )
    
    return CommandResult(
        success=True,
        message=message,
        state_changed=True,
        action="CONFIG_SET",
    )


def handle_config_command(cmd: TelegramCommand) -> CommandResult:
    """Handle the /config command with subcommands list/get/set.
    
    This is the main entry point for /config command processing.
    It dispatches to the appropriate subcommand handler based on arguments.
    
    Args:
        cmd: The TelegramCommand object for /config.
        
    Returns:
        CommandResult with success status and response message.
        
    References:
        - Story 8.2: Telegram /config 命令接口
    """
    logging.info(
        "Telegram /config command received: chat_id=%s, message_id=%d, args=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
    )
    
    # Parse subcommand
    if not cmd.args:
        # No subcommand - show usage help
        message = (
            "⚙️ */config 命令用法*\n\n"
            "• `/config list` \\- 列出所有可配置项\n"
            "• `/config get KEY` \\- 查看指定配置项\n"
            "• `/config set KEY VALUE` \\- 修改配置项\n\n"
            "💡 示例:\n"
            "`/config get TRADEBOT_INTERVAL`\n"
            "`/config set TRADEBOT_INTERVAL 5m`"
        )
        return CommandResult(
            success=True,
            message=message,
            state_changed=False,
            action="CONFIG_HELP",
        )
    
    subcommand = cmd.args[0].lower()
    
    if subcommand == "list":
        return handle_config_list_command(cmd)
    
    if subcommand == "get":
        if len(cmd.args) < 2:
            message = (
                "❌ *缺少参数*\n\n"
                "用法: `/config get KEY`\n\n"
                "💡 使用 `/config list` 查看可用配置项"
            )
            return CommandResult(
                success=False,
                message=message,
                state_changed=False,
                action="CONFIG_GET_MISSING_KEY",
            )
        key = cmd.args[1]
        return handle_config_get_command(cmd, key)
    
    if subcommand == "set":
        if len(cmd.args) < 2:
            message = (
                "❌ *缺少参数*\n\n"
                "用法: `/config set KEY VALUE`\n\n"
                "💡 使用 `/config list` 查看可用配置项"
            )
            return CommandResult(
                success=False,
                message=message,
                state_changed=False,
                action="CONFIG_SET_MISSING_KEY",
            )
        if len(cmd.args) < 3:
            message = (
                "❌ *缺少参数*\n\n"
                "用法: `/config set KEY VALUE`\n\n"
                "💡 使用 `/config get KEY` 查看合法取值"
            )
            return CommandResult(
                success=False,
                message=message,
                state_changed=False,
                action="CONFIG_SET_MISSING_VALUE",
            )
        key = cmd.args[1]
        # Join remaining args as value (in case value has spaces, though unlikely)
        value = " ".join(cmd.args[2:])
        return handle_config_set_command(cmd, key, value)
    
    # Unknown subcommand
    message = (
        f"❌ *未知子命令:* `{_escape_markdown(subcommand)}`\n\n"
        "可用子命令:\n"
        "• `list` \\- 列出所有可配置项\n"
        "• `get KEY` \\- 查看指定配置项\n"
        "• `set KEY VALUE` \\- 修改配置项"
    )
    logging.warning(
        "Telegram /config: unknown subcommand '%s' | chat_id=%s",
        subcommand,
        cmd.chat_id,
    )
    return CommandResult(
        success=False,
        message=message,
        state_changed=False,
        action="CONFIG_UNKNOWN_SUBCOMMAND",
    )


def create_kill_resume_handlers(
    state: "RiskControlState",
    *,
    positions_count_fn: Optional[Callable[[], int]] = None,
    send_fn: Optional[Callable[[str, str], None]] = None,
    record_event_fn: Optional[Callable[[str, str], None]] = None,
    bot_token: str = "",
    chat_id: str = "",
    total_equity_fn: Optional[Callable[[], Optional[float]]] = None,
    balance_fn: Optional[Callable[[], float]] = None,
    total_margin_fn: Optional[Callable[[], float]] = None,
    start_capital: float = 0.0,
    sortino_ratio_fn: Optional[Callable[[], Optional[float]]] = None,
    risk_control_enabled: bool = True,
    daily_loss_limit_enabled: bool = True,
    daily_loss_limit_pct: float = 5.0,
) -> Dict[str, Callable[[TelegramCommand], None]]:
    """Create command handlers for Telegram commands.
    
    This factory function creates properly configured handlers that can be
    passed to process_telegram_commands.
    
    Args:
        state: The RiskControlState instance to modify.
        positions_count_fn: Optional function to get current positions count.
        send_fn: Optional function to send Telegram messages.
            Signature: send_fn(text, parse_mode).
        record_event_fn: Optional function to record audit events.
            Signature: record_event_fn(action, detail).
        bot_token: Telegram bot token for sending responses.
        chat_id: Telegram chat ID for sending responses.
        total_equity_fn: Function to get current total equity.
        balance_fn: Function to get current available balance.
        total_margin_fn: Function to get total margin allocated.
        start_capital: Starting capital for return calculation.
        sortino_ratio_fn: Function to get current Sortino ratio.
        risk_control_enabled: Whether risk control is enabled.
        daily_loss_limit_enabled: Whether daily loss limit is enabled.
        daily_loss_limit_pct: Daily loss limit percentage threshold.
    
    Returns:
        Dict mapping command names to handler functions.
    """
    from notifications.telegram import send_telegram_message
    
    def _send_response(text: str, target_chat_id: str) -> None:
        """Send response message to Telegram."""
        if not bot_token or not target_chat_id:
            logging.debug(
                "Telegram response not sent: missing bot_token or chat_id"
            )
            return
        
        if send_fn is not None:
            try:
                send_fn(text, "MarkdownV2")
            except Exception as e:
                logging.error("Failed to send Telegram response: %s", e)
        else:
            try:
                send_telegram_message(
                    bot_token=bot_token,
                    default_chat_id=target_chat_id,
                    text=text,
                    parse_mode="MarkdownV2",
                )
            except Exception as e:
                logging.error("Failed to send Telegram response: %s", e)
    
    def _record_event(action: str, detail: str) -> None:
        """Record audit event."""
        if record_event_fn is not None:
            try:
                record_event_fn(action, detail)
            except Exception as e:
                logging.error("Failed to record audit event: %s", e)
    
    def kill_handler(cmd: TelegramCommand) -> None:
        """Handler for /kill command."""
        positions = positions_count_fn() if positions_count_fn else 0
        result = handle_kill_command(
            cmd,
            state,
            positions_count=positions,
        )
        
        # Send response
        _send_response(result.message, cmd.chat_id)
        
        # Record audit event if state changed
        if result.state_changed and result.action:
            _record_event(
                result.action,
                f"Kill-Switch activated via Telegram /kill | chat_id={cmd.chat_id}",
            )
    
    def resume_handler(cmd: TelegramCommand) -> None:
        """Handler for /resume command."""
        result = handle_resume_command(cmd, state)
        
        # Send response
        _send_response(result.message, cmd.chat_id)
        
        # Record audit event if state changed or action taken
        if result.action:
            detail = f"Telegram /resume | chat_id={cmd.chat_id}"
            if result.action == "RESUME_PENDING_CONFIRM":
                detail = f"Resume requested, confirmation pending | chat_id={cmd.chat_id}"
            elif result.action == "RESUME_BLOCKED_DAILY_LOSS":
                detail = f"Resume blocked by daily loss limit | chat_id={cmd.chat_id}"
            elif result.action == "KILL_SWITCH_DEACTIVATED":
                detail = f"Kill-Switch deactivated via Telegram /resume confirm | chat_id={cmd.chat_id}"
            
            _record_event(result.action, detail)
    
    def status_handler(cmd: TelegramCommand) -> None:
        """Handler for /status command (Bot profit/loss status)."""
        try:
            positions_count = positions_count_fn() if positions_count_fn else 0
            total_equity = total_equity_fn() if total_equity_fn is not None else None
            current_balance = balance_fn() if balance_fn is not None else 0.0
            current_margin = total_margin_fn() if total_margin_fn is not None else 0.0
            sortino = sortino_ratio_fn() if sortino_ratio_fn is not None else None
            result = handle_status_command(
                cmd,
                balance=current_balance,
                total_equity=total_equity,
                total_margin=current_margin,
                positions_count=positions_count,
                start_capital=start_capital,
                sortino_ratio=sortino,
                kill_switch_active=state.kill_switch_active,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /status command: %s", exc)
            fallback = "⚠️ *暂时无法获取 Bot 状态，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"status via Telegram | chat_id={cmd.chat_id}"
            _record_event(result.action, detail)

    def risk_handler(cmd: TelegramCommand) -> None:
        """Handler for /risk command (risk control status)."""
        try:
            positions_count = positions_count_fn() if positions_count_fn else 0
            total_equity = total_equity_fn() if total_equity_fn is not None else None
            result = handle_risk_command(
                cmd,
                state,
                total_equity=total_equity,
                positions_count=positions_count,
                risk_control_enabled=risk_control_enabled,
                daily_loss_limit_enabled=daily_loss_limit_enabled,
                daily_loss_limit_pct=daily_loss_limit_pct,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /risk command: %s", exc)
            fallback = "⚠️ *暂时无法获取风控状态，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"risk via Telegram | chat_id={cmd.chat_id}"
            _record_event(result.action, detail)
    
    handlers: Dict[str, Callable[[TelegramCommand], None]] = {
        "kill": kill_handler,
        "resume": resume_handler,
    }

    handlers["status"] = status_handler
    handlers["risk"] = risk_handler

    def reset_daily_handler(cmd: TelegramCommand) -> None:
        """Handler for /reset_daily command."""
        try:
            total_equity = total_equity_fn() if total_equity_fn is not None else None
            result = handle_reset_daily_command(
                cmd,
                state,
                total_equity=total_equity,
                risk_control_enabled=risk_control_enabled,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /reset_daily command: %s", exc)
            fallback = "⚠️ *暂时无法重置每日基准，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"reset_daily via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Daily baseline reset via Telegram /reset_daily | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["reset_daily"] = reset_daily_handler

    def config_handler(cmd: TelegramCommand) -> None:
        """Handler for /config command."""
        try:
            result = handle_config_command(cmd)
        except Exception as exc:
            logging.error("Error processing Telegram /config command: %s", exc)
            fallback = "⚠️ *配置命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"config via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Config updated via Telegram /config | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["config"] = config_handler

    def help_handler(cmd: TelegramCommand) -> None:
        """Handler for /help command."""
        try:
            result = handle_help_command(
                cmd,
                risk_control_enabled=risk_control_enabled,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /help command: %s", exc)
            fallback = "⚠️ *暂时无法获取帮助信息，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

    handlers["help"] = help_handler

    def unknown_handler(cmd: TelegramCommand) -> None:
        """Handler for unknown commands."""
        try:
            result = handle_unknown_command(
                cmd,
                risk_control_enabled=risk_control_enabled,
            )
        except Exception as exc:
            logging.error("Error processing Telegram unknown command: %s", exc)
            fallback = "⚠️ *命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

    # Store unknown handler for use in process_telegram_commands
    handlers["__unknown__"] = unknown_handler

    return handlers
