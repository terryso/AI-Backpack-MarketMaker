"""
Handler for /audit command to show account balance audit.

This module provides a unified audit command that supports multiple exchanges
via the AuditProvider interface.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Union

import ccxt

from config.settings import get_effective_trading_backend
from exchange.base import AuditData, AuditProvider
from notifications.commands.base import TelegramCommand, CommandResult, escape_markdown


# 支持的交易所列表（未来可以逐步补齐对应 AuditProvider 实现）
SUPPORTED_EXCHANGES = ["backpack", "binance", "hyperliquid"]

# 交易所显示名称映射
EXCHANGE_DISPLAY_NAMES: Dict[str, str] = {
    "backpack": "Backpack",
    "binance": "Binance",
    "hyperliquid": "Hyperliquid",
}


_AUDIT_EXCHANGE_BY_TRADING_BACKEND: Dict[str, str] = {
    "backpack_futures": "backpack",
    "binance_futures": "binance",
    "hyperliquid": "hyperliquid",
}


def _resolve_default_exchange() -> str:
    """根据 TRADING_BACKEND 推断 audit 默认交易所。

    - backpack_futures -> backpack
    - binance_futures  -> binance
    - hyperliquid      -> hyperliquid
    - 其他/未知值       -> fallback 到 backpack
    """
    try:
        backend = get_effective_trading_backend()
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to resolve TRADING_BACKEND for audit: %s", exc)
        return "backpack"

    exchange = _AUDIT_EXCHANGE_BY_TRADING_BACKEND.get(backend)
    if not exchange:
        return "backpack"
    return exchange


DEFAULT_EXCHANGE = _resolve_default_exchange()


def _format_decimal(value: Decimal, *, places: int = 4) -> str:
    """Format a Decimal value with trailing zeros removed."""
    quantized = value.quantize(Decimal(10) ** -places)
    text = format(quantized, "f")
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _get_audit_provider(exchange: str) -> AuditProvider:
    """获取指定交易所的 AuditProvider 实例。
    
    Args:
        exchange: 交易所名称 (如 "backpack")。
        
    Returns:
        实现 AuditProvider 接口的交易所客户端。
        
    Raises:
        ValueError: 如果交易所未配置或不支持。
    """
    exchange_lower = exchange.lower().strip()
    
    if exchange_lower == "backpack":
        from exchange.backpack import BackpackFuturesExchangeClient
        
        api_public_key = os.getenv("BACKPACK_API_PUBLIC_KEY", "").strip()
        api_secret_seed = os.getenv("BACKPACK_API_SECRET_SEED", "").strip()
        
        if not api_public_key or not api_secret_seed:
            raise ValueError(
                "Backpack API 未配置。请在 .env 中设置 "
                "BACKPACK_API_PUBLIC_KEY 和 BACKPACK_API_SECRET_SEED"
            )
        
        base_url = os.getenv("BACKPACK_API_BASE_URL") or "https://api.backpack.exchange"
        window_raw = os.getenv("BACKPACK_API_WINDOW_MS") or "5000"
        try:
            window_ms = int(window_raw)
        except (TypeError, ValueError):
            window_ms = 5000
        
        return BackpackFuturesExchangeClient(
            api_public_key=api_public_key,
            api_secret_seed=api_secret_seed,
            base_url=base_url,
            window_ms=window_ms,
        )

    if exchange_lower == "binance":
        from exchange.binance import BinanceFuturesExchangeClient

        api_key = os.getenv("BN_API_KEY", "").strip()
        api_secret = os.getenv("BN_SECRET", "").strip()

        if not api_key or not api_secret:
            raise ValueError(
                "Binance API 未配置。请在 .env 中设置 "
                "BN_API_KEY 和 BN_SECRET"
            )

        try:
            exchange = ccxt.binanceusdm(
                {
                    "apiKey": api_key,
                    "secret": api_secret,
                    "enableRateLimit": True,
                }
            )
            # 对于 audit 功能，我们只需要 income history，不强依赖市场元数据。
            # 某些账户在调用 load_markets() 时可能因为权限或网络问题报错，
            # 这里将其降级为 warning，避免直接导致 audit 功能不可用。
            try:
                exchange.load_markets()
            except Exception as exc:  # noqa: BLE001
                logging.warning(
                    "Binance load_markets failed for audit; continuing without markets: %s",
                    exc,
                )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"初始化 Binance Futures 客户端失败: {exc}") from exc

        return BinanceFuturesExchangeClient(exchange)
    
    raise ValueError(f"交易所 '{exchange}' 不支持 audit 功能")


def format_audit_message(
    audit_data: AuditData,
    *,
    start_utc: datetime,
    end_utc: datetime,
    local_tz: Any,
) -> str:
    """将 AuditData 格式化为 Telegram 消息。
    
    Args:
        audit_data: 审计数据。
        start_utc: 开始时间 (UTC)。
        end_utc: 结束时间 (UTC)。
        local_tz: 本地时区。
        
    Returns:
        格式化的 Telegram 消息 (MarkdownV2)。
    """
    # 获取交易所显示名称
    exchange_name = EXCHANGE_DISPLAY_NAMES.get(
        audit_data.backend.replace("_futures", ""),
        audit_data.backend,
    )
    
    # 构建消息
    start_local = start_utc.astimezone(local_tz)
    end_local = end_utc.astimezone(local_tz)
    
    start_str = start_local.strftime('%Y-%m-%d %H:%M').replace('-', '\\-')
    end_str = end_local.strftime('%H:%M')
    
    lines = [
        f"📊 *{escape_markdown(exchange_name)} 资金变动分析*\n",
        f"*时间范围:* `{start_str}` \\- `{end_str}`\n",
    ]
    
    # 资金费
    lines.append("*\\[资金费\\]*")
    lines.append(f"  合计: `{escape_markdown(_format_decimal(audit_data.funding_total))} USDC`")
    if audit_data.funding_by_symbol:
        for symbol, qty in sorted(audit_data.funding_by_symbol.items()):
            lines.append(f"  • {escape_markdown(symbol)}: `{escape_markdown(_format_decimal(qty))}`")
    lines.append("")
    
    # 结算/手续费/PnL
    lines.append("*\\[结算/手续费/PnL\\]*")
    lines.append(f"  合计: `{escape_markdown(_format_decimal(audit_data.settlement_total))} USDC`")
    if audit_data.settlement_by_source:
        for source, qty in sorted(audit_data.settlement_by_source.items()):
            lines.append(f"  • {escape_markdown(source)}: `{escape_markdown(_format_decimal(qty))}`")
    lines.append("")
    
    # 充值/提现
    if audit_data.deposit_total != 0 or audit_data.withdrawal_total != 0:
        lines.append("*\\[充值/提现\\]*")
        if audit_data.deposit_total != 0:
            lines.append(f"  充值: `{escape_markdown(_format_decimal(audit_data.deposit_total))}`")
        if audit_data.withdrawal_total != 0:
            lines.append(f"  提现: `{escape_markdown(_format_decimal(audit_data.withdrawal_total))}`")
        lines.append("")
    
    # 净变动
    lines.append("*\\[综合估算\\]*")
    lines.append(f"  净变动: `{escape_markdown(_format_decimal(audit_data.net_change))} USDC`")
    
    return "\n".join(lines)


def _parse_time_arg(value: str, local_tz: timezone) -> Optional[datetime]:
    """Parse a time argument from user input.
    
    Supports formats:
    - HH:MM (today's time)
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM
    - YYYY-MM-DDTHH:MM
    """
    text = value.strip()
    if not text:
        return None

    # Try HH:MM format (today's time)
    if len(text) <= 5 and ":" in text:
        try:
            parts = text.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            now = datetime.now(tz=local_tz)
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return dt.astimezone(timezone.utc)
        except (ValueError, IndexError):
            pass

    # Try ISO format
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc)


def _get_default_time_range(local_tz: timezone) -> tuple[datetime, datetime]:
    """Get default time range: today 00:00 to now."""
    now_local = datetime.now(tz=local_tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc), now_local.astimezone(timezone.utc)


def handle_audit_command(
    cmd: TelegramCommand,
    exchange: Optional[str] = None,
) -> CommandResult:
    """Handle the /audit command to show account balance audit.
    
    Usage:
        /audit              - 查看今天 00:00 到当前时间的资金变动
        /audit HH:MM        - 查看今天 HH:MM 到当前时间的资金变动
        /audit START END    - 查看指定时间范围的资金变动
    
    Args:
        cmd: The TelegramCommand object for /audit.
        exchange: 交易所名称 (默认 "backpack")。
        
    Returns:
        CommandResult with success status and audit message.
    """
    # 如果调用方未显式指定，则根据 TRADING_BACKEND 推断默认交易所
    if not exchange:
        exchange = _resolve_default_exchange()

    logging.info(
        "Telegram /audit command received: chat_id=%s, message_id=%d, args=%s, exchange=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
        exchange,
    )

    # Get local timezone
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc

    # Parse time arguments
    if not cmd.args:
        # Default: today 00:00 to now
        start_utc, end_utc = _get_default_time_range(local_tz)
    elif len(cmd.args) == 1:
        # Single arg: start time, end = now
        start_utc = _parse_time_arg(cmd.args[0], local_tz)
        if start_utc is None:
            message = (
                f"❌ *无效的时间格式:* `{escape_markdown(cmd.args[0])}`\n\n"
                "支持的格式:\n"
                "• `HH:MM` \\- 今天的时间\n"
                "• `YYYY\\-MM\\-DD` \\- 日期\n"
                "• `YYYY\\-MM\\-DD HH:MM` \\- 日期时间"
            )
            return CommandResult(
                success=False,
                message=message,
                state_changed=False,
                action="AUDIT_INVALID_TIME",
            )
        end_utc = datetime.now(tz=timezone.utc)
    else:
        # Two args: start and end time
        start_utc = _parse_time_arg(cmd.args[0], local_tz)
        end_utc = _parse_time_arg(cmd.args[1], local_tz)
        if start_utc is None or end_utc is None:
            message = (
                "❌ *无效的时间格式*\n\n"
                "用法: `/audit [START] [END]`\n\n"
                "支持的格式:\n"
                "• `HH:MM` \\- 今天的时间\n"
                "• `YYYY\\-MM\\-DD` \\- 日期\n"
                "• `YYYY\\-MM\\-DD HH:MM` \\- 日期时间"
            )
            return CommandResult(
                success=False,
                message=message,
                state_changed=False,
                action="AUDIT_INVALID_TIME",
            )

    if end_utc <= start_utc:
        message = "❌ *结束时间必须晚于开始时间*"
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="AUDIT_INVALID_RANGE",
        )

    # Get audit provider for the specified exchange
    try:
        provider = _get_audit_provider(exchange)
    except ValueError as exc:
        exchange_name = EXCHANGE_DISPLAY_NAMES.get(exchange, exchange)
        message = (
            f"❌ *{escape_markdown(exchange_name)} API 未配置*\n\n"
            f"错误: `{escape_markdown(str(exc))}`"
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="AUDIT_NOT_CONFIGURED",
        )
    except Exception as exc:
        logging.error("Failed to create audit provider for %s: %s", exchange, exc)
        exchange_name = EXCHANGE_DISPLAY_NAMES.get(exchange, exchange)
        message = (
            f"❌ *{escape_markdown(exchange_name)} 客户端初始化失败*\n\n"
            f"错误: `{escape_markdown(str(exc))}`"
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="AUDIT_CLIENT_ERROR",
        )

    # Fetch and format audit data
    try:
        audit_data = provider.fetch_audit_data(start_utc, end_utc)
        message = format_audit_message(
            audit_data,
            start_utc=start_utc,
            end_utc=end_utc,
            local_tz=local_tz,
        )
    except Exception as exc:
        logging.error("Failed to fetch/analyze audit data for %s: %s", exchange, exc)
        exchange_name = EXCHANGE_DISPLAY_NAMES.get(exchange, exchange)
        message = (
            f"❌ *获取 {escape_markdown(exchange_name)} 审计数据失败*\n\n"
            f"错误: `{escape_markdown(str(exc))}`"
        )
        return CommandResult(
            success=False,
            message=message,
            state_changed=False,
            action="AUDIT_FETCH_ERROR",
        )

    logging.info(
        "Telegram /audit completed | chat_id=%s | exchange=%s | start=%s | end=%s",
        cmd.chat_id,
        exchange,
        start_utc.isoformat(),
        end_utc.isoformat(),
    )

    return CommandResult(
        success=True,
        message=message,
        state_changed=False,
        action="AUDIT_COMPLETED",
    )
