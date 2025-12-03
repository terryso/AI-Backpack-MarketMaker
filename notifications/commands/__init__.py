"""
Telegram command handlers module.

This package provides modular command handlers for the Telegram bot.
Each command is implemented in its own module for better maintainability.

Usage:
    from notifications.commands import (
        TelegramCommand,
        TelegramCommandHandler,
        CommandResult,
        create_command_handler,
        process_telegram_commands,
        create_kill_resume_handlers,
    )
"""

from notifications.commands.base import (
    TelegramCommand,
    TelegramCommandHandler,
    CommandResult,
    create_command_handler,
    process_telegram_commands,
    escape_markdown,
    trim_decimal,
    COMMAND_REGISTRY,
    build_help_message,
    register_telegram_commands,
    check_admin_permission,
)

from notifications.commands.handlers import create_kill_resume_handlers

# Command handlers
from notifications.commands.kill import handle_kill_command
from notifications.commands.resume import handle_resume_command
from notifications.commands.status import handle_status_command
from notifications.commands.balance import handle_balance_command
from notifications.commands.positions import handle_positions_command
from notifications.commands.risk import handle_risk_command
from notifications.commands.reset_daily import handle_reset_daily_command
from notifications.commands.help import handle_help_command, handle_unknown_command
from notifications.commands.config import (
    handle_config_command,
    handle_config_list_command,
    handle_config_get_command,
    handle_config_set_command,
    CONFIG_KEY_DESCRIPTIONS,
    CONFIG_KEYS_FOR_TELEGRAM,
)
from notifications.commands.symbols import (
    handle_symbols_command,
    handle_symbols_list_command,
    handle_symbols_add_command,
    handle_symbols_remove_command,
)
from notifications.commands.audit import handle_audit_command
from notifications.commands.close import (
    handle_close_command,
    get_positions_for_close,
)
from notifications.commands.close_all import (
    handle_close_all_command,
)
from notifications.commands.tpsl import (
    handle_sl_command,
    handle_tp_command,
    handle_tpsl_command,
    get_positions_for_tpsl,
    TPSLParseResult,
    TPSLUpdateResult,
    PriceMode,
)

__all__ = [
    # Core classes
    "TelegramCommand",
    "TelegramCommandHandler",
    "CommandResult",
    # Factory functions
    "create_command_handler",
    "process_telegram_commands",
    "create_kill_resume_handlers",
    # Utilities
    "escape_markdown",
    "trim_decimal",
    "COMMAND_REGISTRY",
    "build_help_message",
    "register_telegram_commands",
    "check_admin_permission",
    # Command handlers
    "handle_kill_command",
    "handle_resume_command",
    "handle_status_command",
    "handle_balance_command",
    "handle_positions_command",
    "handle_risk_command",
    "handle_reset_daily_command",
    "handle_help_command",
    "handle_unknown_command",
    "handle_config_command",
    "handle_config_list_command",
    "handle_config_get_command",
    "handle_config_set_command",
    "handle_symbols_command",
    "handle_symbols_list_command",
    "handle_symbols_add_command",
    "handle_symbols_remove_command",
    "handle_audit_command",
    "handle_close_command",
    "get_positions_for_close",
    "handle_close_all_command",
    # TP/SL command handlers
    "handle_sl_command",
    "handle_tp_command",
    "handle_tpsl_command",
    "get_positions_for_tpsl",
    "TPSLParseResult",
    "TPSLUpdateResult",
    "PriceMode",
    # Config constants
    "CONFIG_KEY_DESCRIPTIONS",
    "CONFIG_KEYS_FOR_TELEGRAM",
]
