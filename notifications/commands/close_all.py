"""
Handler for /close_all command to close all or directional positions.

This module implements the /close_all command for batch position closing
via Telegram. It supports:
- Preview mode: /close_all, /close_all long, /close_all short
- Confirm mode: /close_all confirm, /close_all long confirm, /close_all short confirm

Part of Epic 7.4: Telegram Command Integration (Story 7.4.7).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from notifications.commands.base import (
    TelegramCommand,
    CommandResult,
    escape_markdown,
    trim_decimal,
)


# ═══════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CloseAllParseResult:
    """Result of parsing /close_all command arguments.
    
    Attributes:
        direction: Direction scope - "all", "long", or "short".
        with_confirm: Whether the confirm flag was provided.
        error: Error message if parsing failed, None otherwise.
    """
    direction: str  # "all", "long", "short"
    with_confirm: bool
    error: Optional[str]


@dataclass
class PositionSummary:
    """Summary of positions for a specific direction.
    
    Attributes:
        count: Number of positions.
        notional: Total notional value in USD.
        symbols: List of symbol names.
    """
    count: int
    notional: float
    symbols: List[str]


@dataclass
class CloseAllPreview:
    """Preview result for /close_all command.
    
    Attributes:
        long_summary: Summary of long positions.
        short_summary: Summary of short positions.
        total_count: Total number of positions to close.
        total_notional: Total notional value to close.
    """
    long_summary: PositionSummary
    short_summary: PositionSummary
    total_count: int
    total_notional: float


@dataclass
class SingleCloseResult:
    """Result of closing a single position.
    
    Attributes:
        symbol: Symbol that was closed.
        side: Position side ("long" or "short").
        quantity: Quantity that was closed.
        notional: Notional value that was closed.
        success: Whether the close was successful.
        error: Error message if failed, None otherwise.
    """
    symbol: str
    side: str
    quantity: float
    notional: float
    success: bool
    error: Optional[str]


@dataclass
class CloseAllExecutionResult:
    """Result of executing /close_all confirm command.
    
    Attributes:
        successful: List of successfully closed positions.
        failed: List of failed position closes.
        total_success_count: Number of successful closes.
        total_success_notional: Total notional of successful closes.
        total_failed_count: Number of failed closes.
    """
    successful: List[SingleCloseResult]
    failed: List[SingleCloseResult]
    total_success_count: int
    total_success_notional: float
    total_failed_count: int


# ═══════════════════════════════════════════════════════════════════
# ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════════

def _parse_close_all_args(args: List[str]) -> CloseAllParseResult:
    """Parse /close_all command arguments.
    
    Supported formats:
    - /close_all                    -> direction="all", with_confirm=False
    - /close_all confirm            -> direction="all", with_confirm=True
    - /close_all long               -> direction="long", with_confirm=False
    - /close_all long confirm       -> direction="long", with_confirm=True
    - /close_all short              -> direction="short", with_confirm=False
    - /close_all short confirm      -> direction="short", with_confirm=True
    
    Args:
        args: List of command arguments.
        
    Returns:
        CloseAllParseResult with parsed values or error.
    """
    if not args:
        # No args = close all directions, preview mode
        return CloseAllParseResult(direction="all", with_confirm=False, error=None)
    
    # Normalize args to lowercase
    normalized = [arg.strip().lower() for arg in args]
    
    # Check for invalid patterns
    valid_directions = {"long", "short"}
    valid_keywords = {"long", "short", "confirm"}
    
    for arg in normalized:
        if arg not in valid_keywords:
            return CloseAllParseResult(
                direction="all",
                with_confirm=False,
                error=f"无效的参数 '{arg}'。支持的格式：\n"
                      f"• /close_all [long|short] [confirm]\n"
                      f"• 示例: /close_all, /close_all long, /close_all confirm",
            )
    
    # Parse direction and confirm
    direction = "all"
    with_confirm = False
    
    # Check for duplicate keywords
    if normalized.count("confirm") > 1:
        return CloseAllParseResult(
            direction="all",
            with_confirm=False,
            error="参数错误：'confirm' 重复出现",
        )
    
    direction_count = sum(1 for arg in normalized if arg in valid_directions)
    if direction_count > 1:
        return CloseAllParseResult(
            direction="all",
            with_confirm=False,
            error="参数错误：只能指定一个方向 (long 或 short)",
        )
    
    # Extract direction
    for arg in normalized:
        if arg in valid_directions:
            direction = arg
            break
    
    # Extract confirm
    with_confirm = "confirm" in normalized
    
    # Validate argument order: direction should come before confirm
    if with_confirm and direction != "all":
        dir_idx = normalized.index(direction)
        confirm_idx = normalized.index("confirm")
        if confirm_idx < dir_idx:
            return CloseAllParseResult(
                direction="all",
                with_confirm=False,
                error="参数顺序错误：方向应在 confirm 之前。\n"
                      f"正确格式: /close_all {direction} confirm",
            )
    
    return CloseAllParseResult(direction=direction, with_confirm=with_confirm, error=None)


# ═══════════════════════════════════════════════════════════════════
# POSITION FILTERING AND SUMMARY
# ═══════════════════════════════════════════════════════════════════

def _filter_positions_by_direction(
    positions: Dict[str, Dict[str, Any]],
    direction: str,
) -> Dict[str, Dict[str, Any]]:
    """Filter positions by direction scope.
    
    Args:
        positions: Dict of all positions keyed by symbol.
        direction: Direction scope - "all", "long", or "short".
        
    Returns:
        Filtered dict of positions matching the direction.
    """
    if direction == "all":
        return positions
    
    filtered: Dict[str, Dict[str, Any]] = {}
    for symbol, pos in positions.items():
        side = str(pos.get("side", "")).lower()
        if side == direction:
            filtered[symbol] = pos
    
    return filtered


def _calculate_position_notional(position: Dict[str, Any]) -> float:
    """Calculate notional value for a position.
    
    Args:
        position: Position data dict.
        
    Returns:
        Notional value in USD.
    """
    try:
        quantity = abs(float(position.get("quantity", 0) or 0))
    except (TypeError, ValueError):
        quantity = 0.0
    
    try:
        entry_price = float(position.get("entry_price", 0) or 0)
    except (TypeError, ValueError):
        entry_price = 0.0
    
    if quantity <= 0 or entry_price <= 0:
        return 0.0
    
    return quantity * entry_price


def _build_position_summary(
    positions: Dict[str, Dict[str, Any]],
    direction: str,
) -> PositionSummary:
    """Build summary for positions of a specific direction.
    
    Args:
        positions: Dict of all positions keyed by symbol.
        direction: Direction to summarize - "long" or "short".
        
    Returns:
        PositionSummary for the specified direction.
    """
    count = 0
    notional = 0.0
    symbols: List[str] = []
    
    for symbol, pos in positions.items():
        side = str(pos.get("side", "")).lower()
        if side == direction:
            count += 1
            notional += _calculate_position_notional(pos)
            symbols.append(symbol)
    
    return PositionSummary(count=count, notional=notional, symbols=sorted(symbols))


def _build_close_all_preview(
    positions: Dict[str, Dict[str, Any]],
    direction: str,
) -> CloseAllPreview:
    """Build preview for /close_all command.
    
    Args:
        positions: Dict of all positions keyed by symbol.
        direction: Direction scope - "all", "long", or "short".
        
    Returns:
        CloseAllPreview with summaries for the command scope.
    """
    long_summary = _build_position_summary(positions, "long")
    short_summary = _build_position_summary(positions, "short")
    
    if direction == "all":
        total_count = long_summary.count + short_summary.count
        total_notional = long_summary.notional + short_summary.notional
    elif direction == "long":
        total_count = long_summary.count
        total_notional = long_summary.notional
    else:  # short
        total_count = short_summary.count
        total_notional = short_summary.notional
    
    return CloseAllPreview(
        long_summary=long_summary,
        short_summary=short_summary,
        total_count=total_count,
        total_notional=total_notional,
    )


# ═══════════════════════════════════════════════════════════════════
# PREVIEW MESSAGE BUILDING
# ═══════════════════════════════════════════════════════════════════

def _build_preview_message(
    preview: CloseAllPreview,
    direction: str,
    kill_switch_active: bool = False,
    daily_loss_triggered: bool = False,
) -> str:
    """Build preview message for /close_all command.
    
    Args:
        preview: CloseAllPreview with position summaries.
        direction: Direction scope - "all", "long", or "short".
        kill_switch_active: Whether Kill-Switch is currently active.
        daily_loss_triggered: Whether daily loss limit is triggered.
        
    Returns:
        Formatted preview message.
    """
    lines: List[str] = []
    
    # Header
    if direction == "all":
        lines.append("📊 全平预览 (所有方向)")
    elif direction == "long":
        lines.append("📊 全平预览 (仅多头)")
    else:
        lines.append("📊 全平预览 (仅空头)")
    
    lines.append("")
    
    # Position summary
    if direction == "all" or direction == "long":
        if preview.long_summary.count > 0:
            symbols_str = ", ".join(preview.long_summary.symbols[:5])
            if len(preview.long_summary.symbols) > 5:
                symbols_str += f" 等 {len(preview.long_summary.symbols)} 个"
            lines.append(
                f"📈 多头: {preview.long_summary.count} 个持仓, "
                f"${preview.long_summary.notional:,.2f}"
            )
            lines.append(f"   品种: {symbols_str}")
        elif direction == "long":
            lines.append("📈 多头: 无持仓")
    
    if direction == "all" or direction == "short":
        if preview.short_summary.count > 0:
            symbols_str = ", ".join(preview.short_summary.symbols[:5])
            if len(preview.short_summary.symbols) > 5:
                symbols_str += f" 等 {len(preview.short_summary.symbols)} 个"
            lines.append(
                f"📉 空头: {preview.short_summary.count} 个持仓, "
                f"${preview.short_summary.notional:,.2f}"
            )
            lines.append(f"   品种: {symbols_str}")
        elif direction == "short":
            lines.append("📉 空头: 无持仓")
    
    lines.append("")
    lines.append(
        f"📋 合计: {preview.total_count} 个持仓, "
        f"${preview.total_notional:,.2f}"
    )
    
    # Risk control status reminder
    if kill_switch_active or daily_loss_triggered:
        lines.append("")
        if kill_switch_active:
            lines.append("⚠️ Kill-Switch 已激活，当前仅允许平仓/减仓操作")
        if daily_loss_triggered:
            lines.append("⚠️ 每日亏损限制已触发，当前仅允许平仓/减仓操作")
    
    # Confirm instruction
    lines.append("")
    lines.append("─" * 30)
    lines.append("确认执行请输入:")
    
    if direction == "all":
        lines.append("  /close_all confirm")
    elif direction == "long":
        lines.append("  /close_all long confirm")
    else:
        lines.append("  /close_all short confirm")
    
    # AC6: Standard workflow hint for extreme market conditions
    lines.append("")
    lines.append("💡 极端行情推荐流程:")
    lines.append("  /kill → /close_all（预览）→ /close_all confirm")
    
    return "\n".join(lines)


def _build_no_positions_message(direction: str) -> str:
    """Build message for no positions scenario.
    
    Args:
        direction: Direction scope - "all", "long", or "short".
        
    Returns:
        Formatted no positions message.
    """
    if direction == "all":
        scope = "任何"
    elif direction == "long":
        scope = "多头"
    else:
        scope = "空头"
    
    return (
        f"📂 当前无{scope}持仓\n\n"
        f"提示: 使用 /positions 查看当前持仓列表。"
    )


# ═══════════════════════════════════════════════════════════════════
# EXECUTION LOGIC
# ═══════════════════════════════════════════════════════════════════

def _execute_close_all(
    positions: Dict[str, Dict[str, Any]],
    direction: str,
    execute_close_fn: Callable[[str, str, float], Any],
) -> CloseAllExecutionResult:
    """Execute batch close for all positions in scope.
    
    Args:
        positions: Dict of positions to close keyed by symbol.
        direction: Direction scope - "all", "long", or "short".
        execute_close_fn: Function to execute single position close.
            Signature: execute_close_fn(coin, side, quantity) -> result.
            
    Returns:
        CloseAllExecutionResult with success and failure details.
    """
    # Log the batch close operation start with scope
    logging.info(
        "TELEGRAM_CLOSE_ALL: starting batch close | scope=%s | total_positions=%d",
        direction,
        len(positions),
    )
    
    filtered = _filter_positions_by_direction(positions, direction)
    
    successful: List[SingleCloseResult] = []
    failed: List[SingleCloseResult] = []
    
    for symbol, pos in filtered.items():
        side = str(pos.get("side", "")).lower()
        
        try:
            quantity = abs(float(pos.get("quantity", 0) or 0))
        except (TypeError, ValueError):
            quantity = 0.0
        
        notional = _calculate_position_notional(pos)
        
        if quantity <= 0:
            logging.warning(
                "TELEGRAM_CLOSE_ALL: skipping %s with zero quantity",
                symbol,
            )
            continue
        
        # Execute close
        try:
            result = execute_close_fn(symbol, side, quantity)
            
            if result is None:
                # Routing/setup failure
                close_result = SingleCloseResult(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    notional=notional,
                    success=False,
                    error="无法连接交易所或获取市场数据",
                )
                failed.append(close_result)
                logging.error(
                    "TELEGRAM_CLOSE_ALL: execution returned None | symbol=%s | "
                    "side=%s | quantity=%s | notional=%.2f | scope=%s",
                    symbol,
                    side,
                    quantity,
                    notional,
                    direction,
                )
            elif hasattr(result, 'success') and not result.success:
                # Exchange rejection
                errors = getattr(result, 'errors', [])
                error_msg = "; ".join(errors) if errors else "交易所拒绝"
                close_result = SingleCloseResult(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    notional=notional,
                    success=False,
                    error=error_msg,
                )
                failed.append(close_result)
                logging.error(
                    "TELEGRAM_CLOSE_ALL: execution failed | symbol=%s | "
                    "side=%s | quantity=%s | notional=%.2f | scope=%s | error=%s",
                    symbol,
                    side,
                    quantity,
                    notional,
                    direction,
                    error_msg,
                )
            else:
                # Success
                close_result = SingleCloseResult(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    notional=notional,
                    success=True,
                    error=None,
                )
                successful.append(close_result)
                logging.info(
                    "TELEGRAM_CLOSE_ALL: execution success | symbol=%s | "
                    "side=%s | quantity=%s | notional=%.2f | scope=%s",
                    symbol,
                    side,
                    quantity,
                    notional,
                    direction,
                )
                
        except Exception as exc:
            close_result = SingleCloseResult(
                symbol=symbol,
                side=side,
                quantity=quantity,
                notional=notional,
                success=False,
                error=str(exc),
            )
            failed.append(close_result)
            logging.error(
                "TELEGRAM_CLOSE_ALL: execution error | symbol=%s | "
                "side=%s | quantity=%s | notional=%.2f | scope=%s | error=%s",
                symbol,
                side,
                quantity,
                notional,
                direction,
                exc,
            )
    
    total_success_notional = sum(r.notional for r in successful)
    
    return CloseAllExecutionResult(
        successful=successful,
        failed=failed,
        total_success_count=len(successful),
        total_success_notional=total_success_notional,
        total_failed_count=len(failed),
    )


def _build_execution_message(
    result: CloseAllExecutionResult,
    direction: str,
) -> str:
    """Build execution result message.
    
    Args:
        result: CloseAllExecutionResult with execution details.
        direction: Direction scope - "all", "long", or "short".
        
    Returns:
        Formatted execution result message.
    """
    lines: List[str] = []
    
    total_count = result.total_success_count + result.total_failed_count
    
    # Determine overall status
    if result.total_failed_count == 0:
        # All success
        if direction == "all":
            lines.append("✅ 全平完成 (所有方向)")
        elif direction == "long":
            lines.append("✅ 全平完成 (多头)")
        else:
            lines.append("✅ 全平完成 (空头)")
    elif result.total_success_count == 0:
        # All failed
        lines.append("❌ 全平失败")
    else:
        # Partial success
        lines.append("⚠️ 部分平仓完成")
    
    lines.append("")
    
    # Success summary
    if result.total_success_count > 0:
        lines.append(
            f"✅ 成功: {result.total_success_count} 个持仓, "
            f"${result.total_success_notional:,.2f}"
        )
        # List successful symbols (up to 5)
        success_symbols = [r.symbol for r in result.successful[:5]]
        if len(result.successful) > 5:
            lines.append(f"   品种: {', '.join(success_symbols)} 等")
        else:
            lines.append(f"   品种: {', '.join(success_symbols)}")
    
    # Failure summary
    if result.total_failed_count > 0:
        failed_notional = sum(r.notional for r in result.failed)
        lines.append(
            f"❌ 失败: {result.total_failed_count} 个持仓, "
            f"${failed_notional:,.2f}"
        )
        # List failed symbols with errors (up to 3)
        for i, fail in enumerate(result.failed[:3]):
            error_short = fail.error[:30] + "..." if fail.error and len(fail.error) > 30 else fail.error
            lines.append(f"   • {fail.symbol}: {error_short}")
        if len(result.failed) > 3:
            lines.append(f"   ... 其余 {len(result.failed) - 3} 个失败详见日志")
    
    # Next steps for failures
    if result.total_failed_count > 0:
        lines.append("")
        lines.append("提示: 可使用 /positions 查看剩余持仓，")
        lines.append("或使用 /close SYMBOL 单独平仓失败的品种。")
    
    return "\n".join(lines)


def _build_no_positions_confirm_message(direction: str) -> str:
    """Build message when no positions found during confirm phase.
    
    Args:
        direction: Direction scope - "all", "long", or "short".
        
    Returns:
        Formatted message.
    """
    if direction == "all":
        scope = "任何"
    elif direction == "long":
        scope = "多头"
    else:
        scope = "空头"
    
    return (
        f"📂 当前无{scope}持仓，未执行平仓操作\n\n"
        f"可能原因: 持仓已通过其它路径平仓（如止损/止盈触发）。\n"
        f"提示: 使用 /positions 查看当前持仓状态。"
    )


# ═══════════════════════════════════════════════════════════════════
# MAIN HANDLER
# ═══════════════════════════════════════════════════════════════════

def handle_close_all_command(
    cmd: TelegramCommand,
    *,
    positions: Dict[str, Dict[str, Any]],
    execute_close_fn: Optional[Callable[[str, str, float], Any]] = None,
    kill_switch_active: bool = False,
    daily_loss_triggered: bool = False,
) -> CommandResult:
    """Handle the /close_all command for batch position closing.
    
    This command supports two modes:
    1. Preview mode (no confirm): Shows summary of positions to be closed
    2. Confirm mode (with confirm): Executes the batch close
    
    Supported formats:
    - /close_all                    - Preview all positions
    - /close_all long               - Preview long positions only
    - /close_all short              - Preview short positions only
    - /close_all confirm            - Close all positions
    - /close_all long confirm       - Close long positions only
    - /close_all short confirm      - Close short positions only
    
    Args:
        cmd: The TelegramCommand object.
        positions: Dict of current positions keyed by coin symbol.
        execute_close_fn: Optional callback to execute position close.
            Signature: execute_close_fn(coin, side, quantity) -> CloseResult or None.
            In production, this MUST be provided. When omitted, confirm mode
            runs in dry-run mode for testing only (returns success without
            actually closing positions).
        kill_switch_active: Whether Kill-Switch is currently active.
        daily_loss_triggered: Whether daily loss limit is triggered.
    
    Returns:
        CommandResult with success status and message.
    """
    logging.info(
        "Telegram /close_all command received: chat_id=%s, message_id=%d, args=%s",
        cmd.chat_id,
        cmd.message_id,
        cmd.args,
    )
    
    # Parse arguments
    parse_result = _parse_close_all_args(cmd.args)
    if parse_result.error:
        logging.warning(
            "Telegram /close_all command parse error: %s | args=%s | chat_id=%s",
            parse_result.error,
            cmd.args,
            cmd.chat_id,
        )
        return CommandResult(
            success=False,
            message=escape_markdown(f"❌ {parse_result.error}"),
            state_changed=False,
            action="CLOSE_ALL_PARSE_ERROR",
        )
    
    direction = parse_result.direction
    with_confirm = parse_result.with_confirm
    
    logging.info(
        "Telegram /close_all parsed: direction=%s, with_confirm=%s, chat_id=%s",
        direction,
        with_confirm,
        cmd.chat_id,
    )
    
    if not with_confirm:
        # ═══════════════════════════════════════════════════════════════
        # PREVIEW MODE
        # ═══════════════════════════════════════════════════════════════
        preview = _build_close_all_preview(positions, direction)
        
        if preview.total_count == 0:
            message = _build_no_positions_message(direction)
            logging.info(
                "Telegram /close_all preview: no positions | direction=%s | chat_id=%s",
                direction,
                cmd.chat_id,
            )
            return CommandResult(
                success=True,
                message=escape_markdown(message),
                state_changed=False,
                action="CLOSE_ALL_NO_POSITIONS",
            )
        
        message = _build_preview_message(
            preview,
            direction,
            kill_switch_active=kill_switch_active,
            daily_loss_triggered=daily_loss_triggered,
        )
        
        logging.info(
            "Telegram /close_all preview: direction=%s | total_count=%d | "
            "total_notional=%.2f | chat_id=%s",
            direction,
            preview.total_count,
            preview.total_notional,
            cmd.chat_id,
        )
        
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=False,
            action="CLOSE_ALL_PREVIEW",
        )
    
    # ═══════════════════════════════════════════════════════════════
    # CONFIRM MODE
    # ═══════════════════════════════════════════════════════════════
    
    # Re-fetch positions for confirm (handled by caller, but we filter here)
    filtered = _filter_positions_by_direction(positions, direction)
    
    if not filtered:
        message = _build_no_positions_confirm_message(direction)
        logging.info(
            "Telegram /close_all confirm: no positions | direction=%s | chat_id=%s",
            direction,
            cmd.chat_id,
        )
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=False,
            action="CLOSE_ALL_NO_POSITIONS_CONFIRM",
        )
    
    if execute_close_fn is None:
        # Dry-run mode (for testing)
        logging.info(
            "Telegram /close_all confirm (dry-run): direction=%s | "
            "positions_count=%d | chat_id=%s",
            direction,
            len(filtered),
            cmd.chat_id,
        )
        
        # Build a simulated success result
        preview = _build_close_all_preview(positions, direction)
        message = (
            f"✅ 全平完成 (dry-run)\n\n"
            f"已平仓: {preview.total_count} 个持仓, "
            f"${preview.total_notional:,.2f}"
        )
        return CommandResult(
            success=True,
            message=escape_markdown(message),
            state_changed=True,
            action="CLOSE_ALL_EXECUTED",
        )
    
    # Execute batch close
    exec_result = _execute_close_all(positions, direction, execute_close_fn)
    
    # Build result message
    message = _build_execution_message(exec_result, direction)
    
    # Determine overall success
    if exec_result.total_failed_count == 0 and exec_result.total_success_count > 0:
        action = "CLOSE_ALL_EXECUTED"
        success = True
    elif exec_result.total_success_count == 0:
        action = "CLOSE_ALL_FAILED"
        success = False
    else:
        action = "CLOSE_ALL_PARTIAL"
        success = True  # Partial success is still considered success
    
    state_changed = exec_result.total_success_count > 0
    
    logging.info(
        "Telegram /close_all confirm result: direction=%s | success_count=%d | "
        "failed_count=%d | success_notional=%.2f | chat_id=%s",
        direction,
        exec_result.total_success_count,
        exec_result.total_failed_count,
        exec_result.total_success_notional,
        cmd.chat_id,
    )
    
    return CommandResult(
        success=success,
        message=escape_markdown(message),
        state_changed=state_changed,
        action=action,
    )
