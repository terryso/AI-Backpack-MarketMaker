"""
Handlers for /config command and subcommands.
"""
from __future__ import annotations

import logging

from notifications.commands.base import (
    TelegramCommand,
    CommandResult,
    escape_markdown,
    check_admin_permission,
    log_config_audit,
)


# Config key descriptions for user-friendly output
CONFIG_KEY_DESCRIPTIONS: dict[str, str] = {
    "TRADING_BACKEND": "交易执行后端",
    "MARKET_DATA_BACKEND": "行情数据源",
    "TRADEBOT_INTERVAL": "交易循环间隔",
    "TRADEBOT_LLM_TEMPERATURE": "LLM 采样温度",
    "TRADEBOT_LOOP_ENABLED": "主循环总开关 (false=暂停 bot, true=恢复运行)",
    "DEFAULT_TP_PCT": "默认止盈百分比 (基于入场价)",
    "DEFAULT_SL_PCT": "默认止损百分比 (基于入场价)",
}

# Config keys actually exposed via /config list|get|set.
# 当前版本支持对 interval、LLM temperature、TRADEBOT_LOOP_ENABLED 以及 TP/SL 默认百分比进行运行时调整，
# backend 两个 key 仍然由 .env + 重启决定。
CONFIG_KEYS_FOR_TELEGRAM: tuple[str, ...] = (
    "TRADEBOT_INTERVAL",
    "TRADEBOT_LLM_TEMPERATURE",
    "TRADEBOT_LOOP_ENABLED",
    "DEFAULT_TP_PCT",
    "DEFAULT_SL_PCT",
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
        get_effective_default_tp_pct,
        get_effective_default_sl_pct,
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
    
    if key == "DEFAULT_TP_PCT":
        current = str(get_effective_default_tp_pct())
        return current, "范围: 0.0 - 100.0 (百分比, 基于入场价)"
    
    if key == "DEFAULT_SL_PCT":
        current = str(get_effective_default_sl_pct())
        return current, "范围: 0.0 - 100.0 (百分比, 基于入场价)"
    
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
        escaped_key = escape_markdown(key)
        escaped_value = escape_markdown(current_value)
        lines.append(f"• `{escaped_key}`")
        lines.append(f"  {escape_markdown(description)}: `{escaped_value}`")
    
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
            f"`{escape_markdown(k)}`" for k in CONFIG_KEYS_FOR_TELEGRAM
        )
        message = (
            f"❌ *无效的配置项:* `{escape_markdown(key)}`\n\n"
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
        f"*名称:* `{escape_markdown(normalized_key)}`\n"
        f"*说明:* {escape_markdown(description)}\n"
        f"*当前值:* `{escape_markdown(current_value)}`\n"
        f"*{escape_markdown(valid_range)}*"
    )
    
    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="CONFIG_GET",
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
    )
    from config.settings import (
        get_effective_trading_backend,
        get_effective_market_data_backend,
        get_effective_interval,
        get_effective_llm_temperature,
        get_effective_tradebot_loop_enabled,
        get_effective_default_tp_pct,
        get_effective_default_sl_pct,
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
    is_admin, admin_user_id = check_admin_permission(cmd)
    
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
            f"`{escape_markdown(k)}`" for k in CONFIG_KEYS_FOR_TELEGRAM
        )
        message = (
            f"❌ *无效的配置项:* `{escape_markdown(key)}`\n\n"
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
    elif normalized_key == "DEFAULT_TP_PCT":
        old_value = str(get_effective_default_tp_pct())
    elif normalized_key == "DEFAULT_SL_PCT":
        old_value = str(get_effective_default_sl_pct())
    else:
        old_value = "N/A"
    
    # Validate the value
    is_valid, error_msg = validate_override_value(normalized_key, value)
    
    if not is_valid:
        _, valid_range = _get_config_value_info(normalized_key)
        message = (
            f"❌ *无效的配置值*\n\n"
            f"*配置项:* `{escape_markdown(normalized_key)}`\n"
            f"*输入值:* `{escape_markdown(value)}`\n"
            f"*错误:* {escape_markdown(error_msg or '未知错误')}\n\n"
            f"*{escape_markdown(valid_range)}*"
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
    elif normalized_key in ("DEFAULT_TP_PCT", "DEFAULT_SL_PCT"):
        normalized_value = float(value)
    else:
        normalized_value = value
    
    success, set_error = set_runtime_override(normalized_key, normalized_value, validate=False)
    
    if not success:
        message = (
            f"❌ *配置更新失败*\n\n"
            f"*配置项:* `{escape_markdown(normalized_key)}`\n"
            f"*错误:* {escape_markdown(set_error or '未知错误')}"
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
        f"*配置项:* `{escape_markdown(normalized_key)}`\n"
        f"*说明:* {escape_markdown(description)}\n"
        f"*原值:* `{escape_markdown(old_value)}`\n"
        f"*新值:* `{escape_markdown(new_value)}`"
    )
    
    # ─────────────────────────────────────────────────────────────────
    # Audit Log (AC3): Write structured audit log for successful changes
    # ─────────────────────────────────────────────────────────────────
    log_config_audit(
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
        f"❌ *未知子命令:* `{escape_markdown(subcommand)}`\n\n"
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
