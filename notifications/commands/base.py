"""
Base classes and utilities for Telegram command handling.

This module contains shared types, dataclasses, and utility functions
used across all command handlers.
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
# HELP MESSAGE AND COMMAND REGISTRY
# ═══════════════════════════════════════════════════════════════════

# Command registry for help message generation
# Each entry: (command, description)
# This allows easy extension when new commands are added
COMMAND_REGISTRY: list[tuple[str, str]] = [
    ("/status", "查看 Bot 资金与盈利状态"),
    ("/balance", "查看当前账户余额与持仓概要"),
    ("/positions", "查看当前所有持仓详情"),
    ("/close SYMBOL", "全平指定品种持仓"),
    ("/close SYMBOL AMOUNT", "部分平仓（AMOUNT 为百分比 0\\-100）"),
    ("/close\\_all", "一键全平所有持仓（需二次确认）"),
    ("/close\\_all long", "一键全平多头持仓（需二次确认）"),
    ("/close\\_all short", "一键全平空头持仓（需二次确认）"),
    ("/sl SYMBOL VALUE", "设置止损（价格或百分比如 \\-5%）"),
    ("/tp SYMBOL VALUE", "设置止盈（价格或百分比如 10%）"),
    ("/tpsl SYMBOL SL TP", "同时设置止损和止盈"),
    ("/risk", "查看风控配置与状态"),
    ("/kill", "激活 Kill\\-Switch，暂停所有新开仓"),
    ("/resume", "解除 Kill\\-Switch 并恢复新开仓"),
    ("/reset\\_daily", "手动重置每日亏损基准"),
    ("/config list", "列出可配置项及当前值"),
    ("/config get KEY", "查看指定配置项详情"),
    ("/config set KEY VALUE", "修改运行时配置"),
    ("/symbols list", "查看当前交易 Universe"),
    ("/symbols add SYMBOL", "添加交易对到 Universe（管理员）"),
    ("/symbols remove SYMBOL", "从 Universe 移除交易对（管理员）"),
    ("/audit", "查看 Backpack 账户资金变动分析"),
    ("/help", "显示此帮助信息"),
]


def build_help_message(risk_control_enabled: bool = True) -> str:
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


def register_telegram_commands(bot_token: str) -> None:
    """Register bot commands with Telegram using the setMyCommands API."""
    if not bot_token:
        return
    commands_map: Dict[str, str] = {}
    for cmd, desc in COMMAND_REGISTRY:
        raw = cmd.split()[0].replace("\\", "")
        if not raw.startswith("/"):
            continue
        raw = raw[1:]
        if "@" in raw:
            raw = raw.split("@")[0]
        name = raw.lower()
        if not name or name in commands_map:
            continue
        description = desc.replace("\\", "")
        commands_map[name] = description
    if not commands_map:
        return
    url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    payload: Dict[str, Any] = {
        "commands": [
            {"command": name, "description": description}
            for name, description in commands_map.items()
        ],
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logging.warning(
                "Failed to set Telegram bot commands: HTTP %d | response=%s",
                response.status_code,
                response.text[:200] if response.text else "(empty)",
            )
            return
        data = response.json()
        if not data.get("ok", False):
            logging.warning(
                "Telegram setMyCommands returned ok=false: %s",
                data.get("description", "unknown error"),
            )
    except requests.exceptions.Timeout:
        logging.warning("Telegram setMyCommands request timed out")
    except requests.exceptions.RequestException as exc:
        logging.warning("Telegram setMyCommands request failed: %s", exc)
    except ValueError as exc:
        logging.warning("Failed to parse Telegram setMyCommands response: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════


def escape_markdown(text: str) -> str:
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


def trim_decimal(value: float, *, max_decimals: int = 4) -> str:
    """Format a decimal value, trimming trailing zeros.
    
    Args:
        value: The float value to format.
        max_decimals: Maximum number of decimal places.
    
    Returns:
        Formatted string with trailing zeros removed.
    """
    s = f"{value:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def check_admin_permission(cmd: TelegramCommand) -> tuple[bool, str]:
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


def log_config_audit(
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
