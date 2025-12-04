"""
Handler for /sl, /tp, /tpsl commands to manage stop loss and take profit.

This module implements the /sl, /tp, and /tpsl commands for managing
stop loss and take profit prices via Telegram. It supports:
- /sl SYMBOL price VALUE - Set stop loss using absolute price
- /sl SYMBOL pct VALUE - Set stop loss using percentage from *entry price*
- /sl SYMBOL VALUE - Shorthand (% suffix = percentage, otherwise price)
- /tp SYMBOL price VALUE - Set take profit using absolute price
- /tp SYMBOL pct VALUE - Set take profit using percentage from *entry price*
- /tp SYMBOL VALUE - Shorthand (% suffix = percentage, otherwise price)
- /tpsl SYMBOL SL_VALUE TP_VALUE - Set both SL and TP atomically

Part of Epic 7.4: Telegram Command Integration (Story 7.4.8).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from notifications.commands.base import (
    TelegramCommand,
    CommandResult,
    escape_markdown,
    trim_decimal,
)
from notifications.commands.positions import parse_live_positions
from config.settings import (
    get_effective_default_tp_pct,
    get_effective_default_sl_pct,
)


class PriceMode(Enum):
    """Mode for specifying price values."""
    PRICE = "price"
    PERCENTAGE = "pct"


@dataclass
class TPSLParseResult:
    """Result of parsing /sl, /tp, or /tpsl command arguments."""
    symbol: Optional[str] = None
    sl_value: Optional[float] = None
    sl_mode: Optional[PriceMode] = None
    tp_value: Optional[float] = None
    tp_mode: Optional[PriceMode] = None
    error: Optional[str] = None


@dataclass
class TPSLUpdateResult:
    """Result of TP/SL update operation."""
    success: bool
    old_sl: Optional[float] = None
    new_sl: Optional[float] = None
    old_tp: Optional[float] = None
    new_tp: Optional[float] = None
    sl_distance_pct: Optional[float] = None
    tp_distance_pct: Optional[float] = None
    error: Optional[str] = None


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to uppercase without suffix.
    
    Args:
        symbol: Raw symbol input (e.g., "btc", "BTCUSDT", "BTC_USDC_PERP").
        
    Returns:
        Normalized symbol (e.g., "BTC").
    """
    if not symbol:
        return ""
    
    upper = symbol.strip().upper()
    
    # Remove common suffixes
    for suffix in ("_USDC_PERP", "_USDT_PERP", "USDT", "USDC", "USD"):
        if upper.endswith(suffix):
            upper = upper[:-len(suffix)]
            break
    
    # Handle underscore-separated formats (e.g., "BTC_USDC")
    if "_" in upper:
        upper = upper.split("_")[0]
    
    return upper


def _parse_value_with_mode(value_str: str) -> Tuple[Optional[float], Optional[PriceMode], Optional[str]]:
    """Parse a value string and determine its mode.
    
    Args:
        value_str: Value string, possibly ending with '%'.
        
    Returns:
        Tuple of (value, mode, error).
    """
    value_str = value_str.strip()
    if not value_str:
        return None, None, "值不能为空"
    
    # Check for percentage suffix
    if value_str.endswith("%"):
        mode = PriceMode.PERCENTAGE
        value_str = value_str[:-1].strip()
    else:
        mode = PriceMode.PRICE
    
    try:
        value = float(value_str)
    except ValueError:
        return None, None, f"无效的数值 '{value_str}'"
    
    return value, mode, None


def _parse_sl_args(args: List[str]) -> TPSLParseResult:
    """Parse /sl command arguments.
    
    Supported formats:
    - /sl SYMBOL price VALUE
    - /sl SYMBOL pct VALUE
    - /sl SYMBOL VALUE (shorthand: % suffix = pct, otherwise price)
    
    Args:
        args: List of command arguments.
        
    Returns:
        TPSLParseResult with parsed values or error.
    """
    if not args:
        return TPSLParseResult(error="请指定品种和止损价格，例如: /sl BTC 48000 或 /sl BTC -5%")
    
    symbol = _normalize_symbol(args[0])
    if not symbol:
        return TPSLParseResult(error="无效的品种名称")
    
    if len(args) < 2:
        return TPSLParseResult(error="请指定止损价格，例如: /sl BTC 48000 或 /sl BTC -5%")
    
    # Check for explicit mode keyword
    second_arg = args[1].strip().lower()
    
    if second_arg == "price":
        if len(args) < 3:
            return TPSLParseResult(error="请指定止损价格，例如: /sl BTC price 48000")
        value, _, error = _parse_value_with_mode(args[2])
        if error:
            return TPSLParseResult(error=error)
        return TPSLParseResult(symbol=symbol, sl_value=value, sl_mode=PriceMode.PRICE)
    
    if second_arg == "pct":
        if len(args) < 3:
            return TPSLParseResult(error="请指定止损百分比，例如: /sl BTC pct -5")
        value, _, error = _parse_value_with_mode(args[2])
        if error:
            return TPSLParseResult(error=error)
        return TPSLParseResult(symbol=symbol, sl_value=value, sl_mode=PriceMode.PERCENTAGE)
    
    # Shorthand mode: determine from value format
    value, mode, error = _parse_value_with_mode(args[1])
    if error:
        return TPSLParseResult(error=error)
    
    # Check for extra arguments
    if len(args) > 2:
        return TPSLParseResult(error="参数过多，请使用: /sl SYMBOL VALUE 或 /sl SYMBOL price/pct VALUE")
    
    return TPSLParseResult(symbol=symbol, sl_value=value, sl_mode=mode)


def _parse_tp_args(args: List[str]) -> TPSLParseResult:
    """Parse /tp command arguments.
    
    Supported formats:
    - /tp SYMBOL price VALUE
    - /tp SYMBOL pct VALUE
    - /tp SYMBOL VALUE (shorthand: % suffix = pct, otherwise price)
    
    Args:
        args: List of command arguments.
        
    Returns:
        TPSLParseResult with parsed values or error.
    """
    if not args:
        return TPSLParseResult(error="请指定品种和止盈价格，例如: /tp BTC 55000 或 /tp BTC 10%")
    
    symbol = _normalize_symbol(args[0])
    if not symbol:
        return TPSLParseResult(error="无效的品种名称")
    
    if len(args) < 2:
        return TPSLParseResult(error="请指定止盈价格，例如: /tp BTC 55000 或 /tp BTC 10%")
    
    # Check for explicit mode keyword
    second_arg = args[1].strip().lower()
    
    if second_arg == "price":
        if len(args) < 3:
            return TPSLParseResult(error="请指定止盈价格，例如: /tp BTC price 55000")
        value, _, error = _parse_value_with_mode(args[2])
        if error:
            return TPSLParseResult(error=error)
        return TPSLParseResult(symbol=symbol, tp_value=value, tp_mode=PriceMode.PRICE)
    
    if second_arg == "pct":
        if len(args) < 3:
            return TPSLParseResult(error="请指定止盈百分比，例如: /tp BTC pct 10")
        value, _, error = _parse_value_with_mode(args[2])
        if error:
            return TPSLParseResult(error=error)
        return TPSLParseResult(symbol=symbol, tp_value=value, tp_mode=PriceMode.PERCENTAGE)
    
    # Shorthand mode: determine from value format
    value, mode, error = _parse_value_with_mode(args[1])
    if error:
        return TPSLParseResult(error=error)
    
    # Check for extra arguments
    if len(args) > 2:
        return TPSLParseResult(error="参数过多，请使用: /tp SYMBOL VALUE 或 /tp SYMBOL price/pct VALUE")
    
    return TPSLParseResult(symbol=symbol, tp_value=value, tp_mode=mode)


def _parse_tpsl_args(args: List[str]) -> TPSLParseResult:
    """Parse /tpsl command arguments.
    
    Supported format:
    - /tpsl SYMBOL SL_VALUE TP_VALUE
    
    Both values must use the same mode (both price or both percentage).
    
    Args:
        args: List of command arguments.
        
    Returns:
        TPSLParseResult with parsed values or error.
    """
    if not args:
        return TPSLParseResult(error="请指定品种、止损和止盈，例如: /tpsl BTC 48000 55000 或 /tpsl BTC -5% 10%")
    
    symbol = _normalize_symbol(args[0])
    if not symbol:
        return TPSLParseResult(error="无效的品种名称")
    
    if len(args) < 3:
        return TPSLParseResult(error="请同时指定止损和止盈，例如: /tpsl BTC 48000 55000 或 /tpsl BTC -5% 10%")
    
    if len(args) > 3:
        return TPSLParseResult(error="参数过多，请使用: /tpsl SYMBOL SL_VALUE TP_VALUE")
    
    # Parse SL value
    sl_value, sl_mode, sl_error = _parse_value_with_mode(args[1])
    if sl_error:
        return TPSLParseResult(error=f"止损值无效: {sl_error}")
    
    # Parse TP value
    tp_value, tp_mode, tp_error = _parse_value_with_mode(args[2])
    if tp_error:
        return TPSLParseResult(error=f"止盈值无效: {tp_error}")
    
    # Check mode consistency (AC3)
    if sl_mode != tp_mode:
        return TPSLParseResult(
            error="止损和止盈必须使用相同模式（都用价格或都用百分比），"
                  "例如: /tpsl BTC 48000 55000 或 /tpsl BTC -5% 10%"
        )
    
    return TPSLParseResult(
        symbol=symbol,
        sl_value=sl_value,
        sl_mode=sl_mode,
        tp_value=tp_value,
        tp_mode=tp_mode,
    )


def _find_position_for_symbol(
    symbol: str,
    positions: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Find position matching the given symbol.
    
    Args:
        symbol: Normalized symbol to find.
        positions: Dict of positions keyed by coin.
        
    Returns:
        Tuple of (matched_key, position_data) or (None, None) if not found.
    """
    if not positions:
        return None, None
    
    # Direct match
    if symbol in positions:
        return symbol, positions[symbol]
    
    # Case-insensitive match
    symbol_upper = symbol.upper()
    for key, pos in positions.items():
        if key.upper() == symbol_upper:
            return key, pos
    
    return None, None


def _calculate_target_price(
    base_price: float,
    value: float,
    mode: PriceMode,
) -> float:
    """Calculate target price from value and mode.
    
    For percentage mode: new_price = base_price * (1 + value / 100)
    For price mode: new_price = value
    
    Args:
        base_price: Base price for percentage calculations. In the current
            implementation this is the *entry price* of the position when
            using percentage mode.
        value: Value to apply.
        mode: Price mode (PRICE or PERCENTAGE).
        
    Returns:
        Calculated target price.
    """
    if mode == PriceMode.PRICE:
        return value
    else:
        # Percentage mode: new_price = base_price * (1 + value / 100)
        return base_price * (1 + value / 100)


def _validate_sl_price(
    sl_price: float,
    current_price: float,
    side: str,
) -> Tuple[bool, Optional[str]]:
    """Validate stop loss price against position direction.
    
    For long positions: SL should be below current price.
    For short positions: SL should be above current price.
    
    Args:
        sl_price: Proposed stop loss price.
        current_price: Current market price.
        side: Position side ("long" or "short").
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if sl_price <= 0:
        return False, "止损价格必须大于 0"
    
    if current_price <= 0:
        return False, "无法获取当前价格"
    
    side_lower = side.lower()
    
    if side_lower == "long":
        if sl_price >= current_price:
            distance_pct = ((sl_price - current_price) / current_price) * 100
            return False, (
                f"多仓止损价 ${sl_price:,.2f} 不应高于当前价 ${current_price:,.2f} "
                f"(+{distance_pct:.2f}%)，请检查输入"
            )
    elif side_lower == "short":
        if sl_price <= current_price:
            distance_pct = ((current_price - sl_price) / current_price) * 100
            return False, (
                f"空仓止损价 ${sl_price:,.2f} 不应低于当前价 ${current_price:,.2f} "
                f"(-{distance_pct:.2f}%)，请检查输入"
            )
    
    return True, None


def _validate_tp_price(
    tp_price: float,
    current_price: float,
    side: str,
) -> Tuple[bool, Optional[str]]:
    """Validate take profit price against position direction.
    
    For long positions: TP should be above current price.
    For short positions: TP should be below current price.
    
    Args:
        tp_price: Proposed take profit price.
        current_price: Current market price.
        side: Position side ("long" or "short").
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if tp_price <= 0:
        return False, "止盈价格必须大于 0"
    
    if current_price <= 0:
        return False, "无法获取当前价格"
    
    side_lower = side.lower()
    
    if side_lower == "long":
        if tp_price <= current_price:
            distance_pct = ((current_price - tp_price) / current_price) * 100
            return False, (
                f"多仓止盈价 ${tp_price:,.2f} 不应低于当前价 ${current_price:,.2f} "
                f"(-{distance_pct:.2f}%)，请检查输入"
            )
    elif side_lower == "short":
        if tp_price >= current_price:
            distance_pct = ((tp_price - current_price) / current_price) * 100
            return False, (
                f"空仓止盈价 ${tp_price:,.2f} 不应高于当前价 ${current_price:,.2f} "
                f"(+{distance_pct:.2f}%)，请检查输入"
            )
    
    return True, None


def _calculate_distance_pct(target_price: float, current_price: float) -> float:
    """Calculate percentage distance from current price.
    
    Args:
        target_price: Target price (SL or TP).
        current_price: Current market price.
        
    Returns:
        Percentage distance (positive if above, negative if below).
    """
    if current_price <= 0:
        return 0.0
    return ((target_price - current_price) / current_price) * 100


def handle_sl_command(
    cmd: TelegramCommand,
    *,
    positions: Dict[str, Dict[str, Any]],
    get_current_price_fn: Optional[Callable[[str], Optional[float]]] = None,
    update_tpsl_fn: Optional[Callable[[str, Optional[float], Optional[float]], TPSLUpdateResult]] = None,
) -> CommandResult:
    """Handle the /sl command for setting stop loss.
    
    This command supports:
    - /sl SYMBOL price VALUE - Set SL using absolute price
    - /sl SYMBOL pct VALUE - Set SL using percentage from current price
    - /sl SYMBOL VALUE - Shorthand (% suffix = percentage, otherwise price)
    
    Args:
        cmd: The TelegramCommand object.
        positions: Dict of current positions keyed by coin symbol.
        get_current_price_fn: Optional function to get current price for a symbol.
        update_tpsl_fn: Optional callback to update TP/SL in state.
            Signature: update_tpsl_fn(coin, new_sl, new_tp) -> TPSLUpdateResult.
    
    Returns:
        CommandResult with success status and message.
    """
    logging.info(
        "Telegram /sl command received: chat_id=%s, message_id=%d, args=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
    )
    
    # Apply default SL percentage when only symbol is provided
    args_for_parse = list(cmd.args)
    if len(args_for_parse) == 1:
        symbol_arg = args_for_parse[0]
        default_sl_pct = get_effective_default_sl_pct()
        args_for_parse = [symbol_arg, f"-{default_sl_pct}%"]
        logging.info(
            "Telegram /sl command: using default SL pct %.4f%% for symbol %s",
            default_sl_pct,
            symbol_arg,
        )
    
    # Parse arguments
    parsed = _parse_sl_args(args_for_parse)
    if parsed.error:
        logging.warning(
            "Telegram /sl command parse error: %s | args=%s | chat_id=%s",
            parsed.error,
            cmd.args,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {parsed.error}"),
            state_changed=False,
            action="SL_PARSE_ERROR",
        )
    
    symbol = parsed.symbol
    sl_value = parsed.sl_value
    sl_mode = parsed.sl_mode
    
    # Find position
    matched_key, position = _find_position_for_symbol(symbol, positions)
    if position is None:
        logging.info(
            "Telegram /sl command: no position for %s | chat_id=%s",
            symbol,
            cmd.chat_id,
        )
        message = (
            f"📂 当前无 {symbol} 持仓，无法设置止损。\n\n"
            f"提示: 使用 /positions 查看当前持仓列表。"
        )
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=False,
            action="SL_NO_POSITION",
        )
    
    # Get position details
    side = str(position.get("side", "")).lower()
    old_sl = position.get("stop_loss") or 0.0
    old_tp = position.get("profit_target") or 0.0
    entry_price = float(position.get("entry_price", 0) or 0)
    
    # Get current price - required for percentage mode, optional for price mode
    current_price: Optional[float] = None
    if get_current_price_fn is not None:
        try:
            current_price = get_current_price_fn(matched_key)
        except Exception as exc:
            logging.warning("Failed to get current price for %s: %s", matched_key, exc)
            current_price = None
    
    # For percentage mode, current price is required
    if sl_mode == PriceMode.PERCENTAGE:
        if current_price is None or current_price <= 0:
            logging.warning(
                "Telegram /sl command: percentage mode requires current price | "
                "symbol=%s | chat_id=%s",
                matched_key,
                cmd.chat_id,
            )
            return CommandResult(
                success=False,
                message=escape_markdown(
                    f"❌ 百分比模式需要当前价格，但无法获取 {matched_key} 当前价格。\n\n"
                    f"提示: 请使用绝对价格模式，例如: /sl {matched_key} price 48000"
                ),
                state_changed=False,
                action="SL_NO_PRICE_FOR_PCT",
            )
    
    # For price mode, fall back to entry price if no current price available
    if current_price is None or current_price <= 0:
        current_price = entry_price
    
    if current_price <= 0:
        logging.warning(
            "Telegram /sl command: no current price for %s | chat_id=%s",
            matched_key,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ 无法获取 {matched_key} 当前价格，请稍后重试。"),
            state_changed=False,
            action="SL_NO_PRICE",
        )
    
    # Calculate target SL price (percentage mode uses entry price as base)
    base_price_for_sl = entry_price if sl_mode == PriceMode.PERCENTAGE else current_price
    new_sl = _calculate_target_price(base_price_for_sl, sl_value, sl_mode)
    
    # Validate SL price
    is_valid, error = _validate_sl_price(new_sl, current_price, side)
    if not is_valid:
        logging.warning(
            "Telegram /sl command validation failed: %s | symbol=%s | side=%s | "
            "current_price=%.4f | target_sl=%.4f | chat_id=%s",
            error,
            matched_key,
            side,
            current_price,
            new_sl,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {error}"),
            state_changed=False,
            action="SL_VALIDATION_FAILED",
        )
    
    # Calculate distance percentage
    sl_distance_pct = _calculate_distance_pct(new_sl, current_price)
    
    # Update TP/SL if callback provided
    if update_tpsl_fn is not None:
        try:
            result = update_tpsl_fn(matched_key, new_sl, None)
            if not result.success:
                logging.error(
                    "Telegram /sl command update failed: %s | symbol=%s | chat_id=%s",
                    result.error,
                    matched_key,
                    cmd.chat_id,
                )
                return CommandResult(
                    success=False,
                    message=escape_markdown(f"❌ 止损更新失败: {result.error or '未知错误'}"),
                    state_changed=False,
                    action="SL_UPDATE_FAILED",
                )
        except Exception as exc:
            logging.error(
                "Telegram /sl command update error: %s | symbol=%s | chat_id=%s",
                exc,
                matched_key,
                cmd.chat_id,
            )
            return CommandResult(
                success=False,
                message=escape_markdown(f"❌ 止损更新出错: {str(exc)}"),
                state_changed=False,
                action="SL_UPDATE_ERROR",
            )
    
    # Build success message
    side_display = "多" if side == "long" else "空" if side == "short" else side.upper()
    
    lines: List[str] = []
    lines.append(f"✅ {matched_key} 止损已更新")
    lines.append("")
    lines.append(f"方向: {side_display}")
    lines.append(f"当前价: ${current_price:,.4f}")
    lines.append(f"新止损: ${new_sl:,.4f} ({sl_distance_pct:+.2f}%)")
    if old_sl and old_sl > 0:
        old_distance_pct = _calculate_distance_pct(old_sl, current_price)
        lines.append(f"原止损: ${old_sl:,.4f} ({old_distance_pct:+.2f}%)")
    
    logging.info(
        "Telegram /sl command success: symbol=%s | side=%s | old_sl=%.4f | "
        "new_sl=%.4f | distance_pct=%.2f | chat_id=%s",
        matched_key,
        side,
        old_sl or 0,
        new_sl,
        sl_distance_pct,
        cmd.chat_id,
    )
    
    return CommandResult(
        success=True,
        message=escape_markdown("\n".join(lines)),
        state_changed=True,
        action="TELEGRAM_SL_UPDATE",
    )


def handle_tp_command(
    cmd: TelegramCommand,
    *,
    positions: Dict[str, Dict[str, Any]],
    get_current_price_fn: Optional[Callable[[str], Optional[float]]] = None,
    update_tpsl_fn: Optional[Callable[[str, Optional[float], Optional[float]], TPSLUpdateResult]] = None,
) -> CommandResult:
    """Handle the /tp command for setting take profit.
    
    This command supports:
    - /tp SYMBOL price VALUE - Set TP using absolute price
    - /tp SYMBOL pct VALUE - Set TP using percentage from current price
    - /tp SYMBOL VALUE - Shorthand (% suffix = percentage, otherwise price)
    
    Args:
        cmd: The TelegramCommand object.
        positions: Dict of current positions keyed by coin symbol.
        get_current_price_fn: Optional function to get current price for a symbol.
        update_tpsl_fn: Optional callback to update TP/SL in state.
            Signature: update_tpsl_fn(coin, new_sl, new_tp) -> TPSLUpdateResult.
    
    Returns:
        CommandResult with success status and message.
    """
    logging.info(
        "Telegram /tp command received: chat_id=%s, message_id=%d, args=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
    )
    
    # Apply default TP percentage when only symbol is provided
    args_for_parse = list(cmd.args)
    if len(args_for_parse) == 1:
        symbol_arg = args_for_parse[0]
        default_tp_pct = get_effective_default_tp_pct()
        args_for_parse = [symbol_arg, f"{default_tp_pct}%"]
        logging.info(
            "Telegram /tp command: using default TP pct %.4f%% for symbol %s",
            default_tp_pct,
            symbol_arg,
        )
    
    # Parse arguments
    parsed = _parse_tp_args(args_for_parse)
    if parsed.error:
        logging.warning(
            "Telegram /tp command parse error: %s | args=%s | chat_id=%s",
            parsed.error,
            cmd.args,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {parsed.error}"),
            state_changed=False,
            action="TP_PARSE_ERROR",
        )
    
    symbol = parsed.symbol
    tp_value = parsed.tp_value
    tp_mode = parsed.tp_mode
    
    # Find position
    matched_key, position = _find_position_for_symbol(symbol, positions)
    if position is None:
        logging.info(
            "Telegram /tp command: no position for %s | chat_id=%s",
            symbol,
            cmd.chat_id,
        )
        message = (
            f"📂 当前无 {symbol} 持仓，无法设置止盈。\n\n"
            f"提示: 使用 /positions 查看当前持仓列表。"
        )
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=False,
            action="TP_NO_POSITION",
        )
    
    # Get position details
    side = str(position.get("side", "")).lower()
    old_sl = position.get("stop_loss") or 0.0
    old_tp = position.get("profit_target") or 0.0
    entry_price = float(position.get("entry_price", 0) or 0)
    
    # Get current price - required for percentage mode, optional for price mode
    current_price: Optional[float] = None
    if get_current_price_fn is not None:
        try:
            current_price = get_current_price_fn(matched_key)
        except Exception as exc:
            logging.warning("Failed to get current price for %s: %s", matched_key, exc)
            current_price = None
    
    # For percentage mode, current price is required
    if tp_mode == PriceMode.PERCENTAGE:
        if current_price is None or current_price <= 0:
            logging.warning(
                "Telegram /tp command: percentage mode requires current price | "
                "symbol=%s | chat_id=%s",
                matched_key,
                cmd.chat_id,
            )
            return CommandResult(
                success=False,
                message=escape_markdown(
                    f"❌ 百分比模式需要当前价格，但无法获取 {matched_key} 当前价格。\n\n"
                    f"提示: 请使用绝对价格模式，例如: /tp {matched_key} price 55000"
                ),
                state_changed=False,
                action="TP_NO_PRICE_FOR_PCT",
            )
    
    # For price mode, fall back to entry price if no current price available
    if current_price is None or current_price <= 0:
        current_price = entry_price
    
    if current_price <= 0:
        logging.warning(
            "Telegram /tp command: no current price for %s | chat_id=%s",
            matched_key,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ 无法获取 {matched_key} 当前价格，请稍后重试。"),
            state_changed=False,
            action="TP_NO_PRICE",
        )
    
    # Calculate target TP price (percentage mode uses entry price as base)
    base_price_for_tp = entry_price if tp_mode == PriceMode.PERCENTAGE else current_price
    new_tp = _calculate_target_price(base_price_for_tp, tp_value, tp_mode)
    
    # Validate TP price
    is_valid, error = _validate_tp_price(new_tp, current_price, side)
    if not is_valid:
        logging.warning(
            "Telegram /tp command validation failed: %s | symbol=%s | side=%s | "
            "current_price=%.4f | target_tp=%.4f | chat_id=%s",
            error,
            matched_key,
            side,
            current_price,
            new_tp,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {error}"),
            state_changed=False,
            action="TP_VALIDATION_FAILED",
        )
    
    # Calculate distance percentage
    tp_distance_pct = _calculate_distance_pct(new_tp, current_price)
    
    # Update TP/SL if callback provided
    if update_tpsl_fn is not None:
        try:
            result = update_tpsl_fn(matched_key, None, new_tp)
            if not result.success:
                logging.error(
                    "Telegram /tp command update failed: %s | symbol=%s | chat_id=%s",
                    result.error,
                    matched_key,
                    cmd.chat_id,
                )
                return CommandResult(
                    success=False,
                    message=escape_markdown(f"❌ 止盈更新失败: {result.error or '未知错误'}"),
                    state_changed=False,
                    action="TP_UPDATE_FAILED",
                )
        except Exception as exc:
            logging.error(
                "Telegram /tp command update error: %s | symbol=%s | chat_id=%s",
                exc,
                matched_key,
                cmd.chat_id,
            )
            return CommandResult(
                success=False,
                message=escape_markdown(f"❌ 止盈更新出错: {str(exc)}"),
                state_changed=False,
                action="TP_UPDATE_ERROR",
            )
    
    # Build success message
    side_display = "多" if side == "long" else "空" if side == "short" else side.upper()
    
    lines: List[str] = []
    lines.append(f"✅ {matched_key} 止盈已更新")
    lines.append("")
    lines.append(f"方向: {side_display}")
    lines.append(f"当前价: ${current_price:,.4f}")
    lines.append(f"新止盈: ${new_tp:,.4f} ({tp_distance_pct:+.2f}%)")
    if old_tp and old_tp > 0:
        old_distance_pct = _calculate_distance_pct(old_tp, current_price)
        lines.append(f"原止盈: ${old_tp:,.4f} ({old_distance_pct:+.2f}%)")
    
    logging.info(
        "Telegram /tp command success: symbol=%s | side=%s | old_tp=%.4f | "
        "new_tp=%.4f | distance_pct=%.2f | chat_id=%s",
        matched_key,
        side,
        old_tp or 0,
        new_tp,
        tp_distance_pct,
        cmd.chat_id,
    )
    
    return CommandResult(
        success=True,
        message=escape_markdown("\n".join(lines)),
        state_changed=True,
        action="TELEGRAM_TP_UPDATE",
    )


def handle_tpsl_command(
    cmd: TelegramCommand,
    *,
    positions: Dict[str, Dict[str, Any]],
    get_current_price_fn: Optional[Callable[[str], Optional[float]]] = None,
    update_tpsl_fn: Optional[Callable[[str, Optional[float], Optional[float]], TPSLUpdateResult]] = None,
) -> CommandResult:
    """Handle the /tpsl command for setting both stop loss and take profit.
    
    This command supports:
    - /tpsl SYMBOL SL_VALUE TP_VALUE
    
    Both values must use the same mode (both price or both percentage).
    
    Args:
        cmd: The TelegramCommand object.
        positions: Dict of current positions keyed by coin symbol.
        get_current_price_fn: Optional function to get current price for a symbol.
        update_tpsl_fn: Optional callback to update TP/SL in state.
            Signature: update_tpsl_fn(coin, new_sl, new_tp) -> TPSLUpdateResult.
    
    Returns:
        CommandResult with success status and message.
    """
    logging.info(
        "Telegram /tpsl command received: chat_id=%s, message_id=%d, args=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
    )
    
    # Apply default TP/SL percentages when only symbol is provided
    args_for_parse = list(cmd.args)
    if len(args_for_parse) == 1:
        symbol_arg = args_for_parse[0]
        default_sl_pct = get_effective_default_sl_pct()
        default_tp_pct = get_effective_default_tp_pct()
        args_for_parse = [
            symbol_arg,
            f"-{default_sl_pct}%",
            f"{default_tp_pct}%",
        ]
        logging.info(
            "Telegram /tpsl command: using default SL/TP pct %.4f%%/%.4f%% for symbol %s",
            default_sl_pct,
            default_tp_pct,
            symbol_arg,
        )
    
    # Parse arguments
    parsed = _parse_tpsl_args(args_for_parse)
    if parsed.error:
        logging.warning(
            "Telegram /tpsl command parse error: %s | args=%s | chat_id=%s",
            parsed.error,
            cmd.args,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {parsed.error}"),
            state_changed=False,
            action="TPSL_PARSE_ERROR",
        )
    
    symbol = parsed.symbol
    sl_value = parsed.sl_value
    sl_mode = parsed.sl_mode
    tp_value = parsed.tp_value
    tp_mode = parsed.tp_mode
    
    # Find position
    matched_key, position = _find_position_for_symbol(symbol, positions)
    if position is None:
        logging.info(
            "Telegram /tpsl command: no position for %s | chat_id=%s",
            symbol,
            cmd.chat_id,
        )
        message = (
            f"📂 当前无 {symbol} 持仓，无法设置 TP/SL。\n\n"
            f"提示: 使用 /positions 查看当前持仓列表。"
        )
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=False,
            action="TPSL_NO_POSITION",
        )
    
    # Get position details
    side = str(position.get("side", "")).lower()
    old_sl = position.get("stop_loss") or 0.0
    old_tp = position.get("profit_target") or 0.0
    entry_price = float(position.get("entry_price", 0) or 0)
    
    # Get current price - required for percentage mode, optional for price mode
    current_price: Optional[float] = None
    if get_current_price_fn is not None:
        try:
            current_price = get_current_price_fn(matched_key)
        except Exception as exc:
            logging.warning("Failed to get current price for %s: %s", matched_key, exc)
            current_price = None
    
    # For percentage mode, current price is required
    if sl_mode == PriceMode.PERCENTAGE or tp_mode == PriceMode.PERCENTAGE:
        if current_price is None or current_price <= 0:
            logging.warning(
                "Telegram /tpsl command: percentage mode requires current price | "
                "symbol=%s | chat_id=%s",
                matched_key,
                cmd.chat_id,
            )
            return CommandResult(
                success=False,
                message=escape_markdown(
                    f"❌ 百分比模式需要当前价格，但无法获取 {matched_key} 当前价格。\n\n"
                    f"提示: 请使用绝对价格模式，例如: /tpsl {matched_key} 48000 55000"
                ),
                state_changed=False,
                action="TPSL_NO_PRICE_FOR_PCT",
            )
    
    # For price mode, fall back to entry price if no current price available
    if current_price is None or current_price <= 0:
        current_price = entry_price
    
    if current_price <= 0:
        logging.warning(
            "Telegram /tpsl command: no current price for %s | chat_id=%s",
            matched_key,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ 无法获取 {matched_key} 当前价格，请稍后重试。"),
            state_changed=False,
            action="TPSL_NO_PRICE",
        )
    
    # Calculate target prices (percentage mode uses entry price as base)
    base_price_for_tpsl = entry_price if sl_mode == PriceMode.PERCENTAGE else current_price
    new_sl = _calculate_target_price(base_price_for_tpsl, sl_value, sl_mode)
    new_tp = _calculate_target_price(base_price_for_tpsl, tp_value, tp_mode)
    
    # Validate SL price
    sl_valid, sl_error = _validate_sl_price(new_sl, current_price, side)
    if not sl_valid:
        logging.warning(
            "Telegram /tpsl command SL validation failed: %s | symbol=%s | side=%s | "
            "current_price=%.4f | target_sl=%.4f | chat_id=%s",
            sl_error,
            matched_key,
            side,
            current_price,
            new_sl,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {sl_error}"),
            state_changed=False,
            action="TPSL_SL_VALIDATION_FAILED",
        )
    
    # Validate TP price
    tp_valid, tp_error = _validate_tp_price(new_tp, current_price, side)
    if not tp_valid:
        logging.warning(
            "Telegram /tpsl command TP validation failed: %s | symbol=%s | side=%s | "
            "current_price=%.4f | target_tp=%.4f | chat_id=%s",
            tp_error,
            matched_key,
            side,
            current_price,
            new_tp,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {tp_error}"),
            state_changed=False,
            action="TPSL_TP_VALIDATION_FAILED",
        )
    
    # Calculate distance percentages
    sl_distance_pct = _calculate_distance_pct(new_sl, current_price)
    tp_distance_pct = _calculate_distance_pct(new_tp, current_price)
    
    # Update TP/SL atomically if callback provided
    if update_tpsl_fn is not None:
        try:
            result = update_tpsl_fn(matched_key, new_sl, new_tp)
            if not result.success:
                logging.error(
                    "Telegram /tpsl command update failed: %s | symbol=%s | chat_id=%s",
                    result.error,
                    matched_key,
                    cmd.chat_id,
                )
                return CommandResult(
                    success=False,
                    message=escape_markdown(f"❌ TP/SL 更新失败: {result.error or '未知错误'}"),
                    state_changed=False,
                    action="TPSL_UPDATE_FAILED",
                )
        except Exception as exc:
            logging.error(
                "Telegram /tpsl command update error: %s | symbol=%s | chat_id=%s",
                exc,
                matched_key,
                cmd.chat_id,
            )
            return CommandResult(
                success=False,
                message=escape_markdown(f"❌ TP/SL 更新出错: {str(exc)}"),
                state_changed=False,
                action="TPSL_UPDATE_ERROR",
            )
    
    # Build success message
    side_display = "多" if side == "long" else "空" if side == "short" else side.upper()
    
    lines: List[str] = []
    lines.append(f"✅ {matched_key} TP/SL 已更新")
    lines.append("")
    lines.append(f"方向: {side_display}")
    lines.append(f"当前价: ${current_price:,.4f}")
    lines.append("")
    lines.append(f"新止损: ${new_sl:,.4f} ({sl_distance_pct:+.2f}%)")
    if old_sl and old_sl > 0:
        old_sl_distance_pct = _calculate_distance_pct(old_sl, current_price)
        lines.append(f"原止损: ${old_sl:,.4f} ({old_sl_distance_pct:+.2f}%)")
    lines.append("")
    lines.append(f"新止盈: ${new_tp:,.4f} ({tp_distance_pct:+.2f}%)")
    if old_tp and old_tp > 0:
        old_tp_distance_pct = _calculate_distance_pct(old_tp, current_price)
        lines.append(f"原止盈: ${old_tp:,.4f} ({old_tp_distance_pct:+.2f}%)")
    
    logging.info(
        "Telegram /tpsl command success: symbol=%s | side=%s | old_sl=%.4f | "
        "new_sl=%.4f | sl_distance_pct=%.2f | old_tp=%.4f | new_tp=%.4f | "
        "tp_distance_pct=%.2f | chat_id=%s",
        matched_key,
        side,
        old_sl or 0,
        new_sl,
        sl_distance_pct,
        old_tp or 0,
        new_tp,
        tp_distance_pct,
        cmd.chat_id,
    )
    
    return CommandResult(
        success=True,
        message=escape_markdown("\n".join(lines)),
        state_changed=True,
        action="TELEGRAM_TPSL_UPDATE",
    )


def get_positions_for_tpsl(
    account_snapshot_fn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
    positions_snapshot_fn: Optional[Callable[[], Dict[str, Dict[str, Any]]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Get positions for TP/SL commands, prioritizing live exchange data.
    
    This function is similar to get_positions_for_close but is specifically
    designed for the /sl, /tp, /tpsl command context.
    
    Args:
        account_snapshot_fn: Function to get live exchange account snapshot.
        positions_snapshot_fn: Function to get local portfolio positions.
        
    Returns:
        Dict mapping coin symbol to position data.
    """
    positions: Dict[str, Dict[str, Any]] = {}
    
    # 1) Try live exchange snapshot first
    if account_snapshot_fn is not None:
        try:
            snapshot = account_snapshot_fn()
        except Exception as exc:
            logging.warning("Failed to get live account snapshot for TP/SL: %s", exc)
            snapshot = None
        
        if isinstance(snapshot, dict):
            raw_positions = snapshot.get("positions")
            if isinstance(raw_positions, list):
                positions = parse_live_positions(raw_positions)
    
    # 2) Fall back to local portfolio if no live data
    if not positions and positions_snapshot_fn is not None:
        try:
            local_snapshot = positions_snapshot_fn()
        except Exception as exc:
            logging.error("Error calling positions_snapshot_fn for TP/SL: %s", exc)
            local_snapshot = None
        if isinstance(local_snapshot, dict):
            positions = local_snapshot
    
    return positions
