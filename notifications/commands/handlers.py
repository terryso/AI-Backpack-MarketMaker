"""
Factory function to create command handlers for Telegram bot.

This module provides the create_kill_resume_handlers function that creates
properly configured handlers for all Telegram commands.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from notifications.commands.base import TelegramCommand, CommandResult

if TYPE_CHECKING:
    from core.risk_control import RiskControlState


def create_kill_resume_handlers(
    state: "RiskControlState",
    *,
    positions_count_fn: Optional[Callable[[], int]] = None,
    positions_snapshot_fn: Optional[Callable[[], Dict[str, Dict[str, Any]]]] = None,
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
    account_snapshot_fn: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
    execute_close_fn: Optional[Callable[[str, str, float], Any]] = None,
    update_tpsl_fn: Optional[Callable[[str, Optional[float], Optional[float]], Any]] = None,
    get_current_price_fn: Optional[Callable[[str], Optional[float]]] = None,
) -> Dict[str, Callable[[TelegramCommand], None]]:
    """Create command handlers for Telegram commands.
    
    This factory function creates properly configured handlers that can be
    passed to process_telegram_commands.
    
    Args:
        state: The RiskControlState instance to modify.
        positions_count_fn: Optional function to get current positions count.
        positions_snapshot_fn: Optional function to get positions snapshot dict.
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
        account_snapshot_fn: Optional function to get live exchange account snapshot.
            When provided and returns a valid dict, /balance will use this data
            instead of the local portfolio view. Expected keys:
            - balance: Available balance
            - total_equity: Total account equity
            - total_margin: Margin in use
            - positions_count: Number of open positions
        execute_close_fn: Optional function to execute position close.
            Signature: execute_close_fn(coin, side, quantity) -> CloseResult or None.
            Used by /close command to execute partial or full position closes.
        update_tpsl_fn: Optional function to update TP/SL for a position.
            Signature: update_tpsl_fn(coin, new_sl, new_tp) -> TPSLUpdateResult.
            Used by /sl, /tp, /tpsl commands to update stop loss and take profit.
        get_current_price_fn: Optional function to get current price for a coin.
            Signature: get_current_price_fn(coin) -> float or None.
            Used by /sl, /tp, /tpsl commands for percentage-based calculations.
    
    Returns:
        Dict mapping command names to handler functions.
    """
    from notifications.telegram import send_telegram_message
    from notifications.commands.kill import handle_kill_command
    from notifications.commands.resume import handle_resume_command
    from notifications.commands.status import handle_status_command
    from notifications.commands.balance import handle_balance_command
    from notifications.commands.positions import handle_positions_command, get_positions_from_snapshot
    from notifications.commands.risk import handle_risk_command
    from notifications.commands.reset_daily import handle_reset_daily_command
    from notifications.commands.help import handle_help_command, handle_unknown_command
    from notifications.commands.config import handle_config_command
    from notifications.commands.symbols import handle_symbols_command
    from notifications.commands.audit import handle_audit_command
    from notifications.commands.close import handle_close_command, get_positions_for_close
    from notifications.commands.close_all import handle_close_all_command
    from notifications.commands.tpsl import (
        handle_sl_command,
        handle_tp_command,
        handle_tpsl_command,
        get_positions_for_tpsl,
        TPSLUpdateResult,
    )
    
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
            if result.action == "RESUME_BLOCKED_DAILY_LOSS":
                detail = f"Resume blocked by daily loss limit | chat_id={cmd.chat_id}"
            elif result.action == "KILL_SWITCH_DEACTIVATED":
                detail = f"Kill-Switch deactivated via Telegram /resume | chat_id={cmd.chat_id}"

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

    def balance_handler(cmd: TelegramCommand) -> None:
        """Handler for /balance command (account snapshot).
        
        Prioritizes live exchange account data when account_snapshot_fn is
        provided and returns valid data. Falls back to local portfolio view
        when live data is unavailable.
        """
        try:
            # Try to get live account snapshot first
            snapshot = None
            if account_snapshot_fn is not None:
                try:
                    snapshot = account_snapshot_fn()
                except Exception as snap_exc:
                    logging.warning(
                        "Failed to get live account snapshot: %s", snap_exc
                    )
                    snapshot = None

            if snapshot is not None and isinstance(snapshot, dict):
                # Use live exchange data
                current_balance = float(snapshot.get("balance", 0.0))
                total_equity = snapshot.get("total_equity")
                if total_equity is not None:
                    total_equity = float(total_equity)
                current_margin = float(snapshot.get("total_margin", 0.0))
                positions_count = int(snapshot.get("positions_count", 0))
                logging.debug(
                    "Using live account snapshot for /balance: "
                    "balance=%.2f, equity=%s, margin=%.2f, positions=%d",
                    current_balance,
                    total_equity,
                    current_margin,
                    positions_count,
                )
            else:
                # Fallback to local portfolio view
                positions_count = positions_count_fn() if positions_count_fn else 0
                total_equity = total_equity_fn() if total_equity_fn is not None else None
                current_balance = balance_fn() if balance_fn is not None else 0.0
                current_margin = total_margin_fn() if total_margin_fn is not None else 0.0
                logging.debug(
                    "Using local portfolio view for /balance (no live snapshot)"
                )

            result = handle_balance_command(
                cmd,
                balance=current_balance,
                total_equity=total_equity,
                total_margin=current_margin,
                positions_count=positions_count,
                start_capital=start_capital,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /balance command: %s", exc)
            fallback = "⚠️ *暂时无法获取账户余额，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"balance via Telegram | chat_id={cmd.chat_id}"
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

    def positions_handler(cmd: TelegramCommand) -> None:
        """Handler for /positions command (open positions snapshot)."""
        try:
            current_positions = get_positions_from_snapshot(
                account_snapshot_fn=account_snapshot_fn,
                positions_snapshot_fn=positions_snapshot_fn,
            )
            result = handle_positions_command(
                cmd,
                positions=current_positions,
                get_current_price_fn=get_current_price_fn,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /positions command: %s", exc)
            fallback = "⚠️ *暂时无法获取持仓信息，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"positions via Telegram | chat_id={cmd.chat_id}"
            _record_event(result.action, detail)
    
    handlers: Dict[str, Callable[[TelegramCommand], None]] = {
        "kill": kill_handler,
        "resume": resume_handler,
    }

    handlers["status"] = status_handler
    handlers["balance"] = balance_handler
    handlers["risk"] = risk_handler
    handlers["positions"] = positions_handler

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

    def symbols_handler(cmd: TelegramCommand) -> None:
        """Handler for /symbols command."""
        try:
            result = handle_symbols_command(cmd)
        except Exception as exc:
            logging.error("Error processing Telegram /symbols command: %s", exc)
            fallback = "⚠️ *Symbol 命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"symbols via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Universe updated via Telegram /symbols | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["symbols"] = symbols_handler

    def audit_handler(cmd: TelegramCommand) -> None:
        """Handler for /audit command."""
        try:
            result = handle_audit_command(cmd)
        except Exception as exc:
            logging.error("Error processing Telegram /audit command: %s", exc)
            fallback = "⚠️ *审计命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"audit via Telegram | chat_id={cmd.chat_id}"
            _record_event(result.action, detail)

    handlers["audit"] = audit_handler

    def close_handler(cmd: TelegramCommand) -> None:
        """Handler for /close command (partial or full position close)."""
        try:
            # Get current positions from live exchange or local portfolio
            current_positions = get_positions_for_close(
                account_snapshot_fn=account_snapshot_fn,
                positions_snapshot_fn=positions_snapshot_fn,
            )
            result = handle_close_command(
                cmd,
                positions=current_positions,
                execute_close_fn=execute_close_fn,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /close command: %s", exc)
            fallback = "⚠️ *平仓命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"close via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Position closed via Telegram /close | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["close"] = close_handler

    def close_all_handler(cmd: TelegramCommand) -> None:
        """Handler for /close_all command (batch position close)."""
        try:
            # Get current positions from live exchange or local portfolio
            current_positions = get_positions_for_close(
                account_snapshot_fn=account_snapshot_fn,
                positions_snapshot_fn=positions_snapshot_fn,
            )
            result = handle_close_all_command(
                cmd,
                positions=current_positions,
                execute_close_fn=execute_close_fn,
                kill_switch_active=state.kill_switch_active,
                daily_loss_triggered=state.daily_loss_triggered,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /close_all command: %s", exc)
            fallback = "⚠️ *全平命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"close_all via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Batch position close via Telegram /close_all | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["close_all"] = close_all_handler

    def sl_handler(cmd: TelegramCommand) -> None:
        """Handler for /sl command (set stop loss)."""
        try:
            # Get current positions from live exchange or local portfolio
            current_positions = get_positions_for_tpsl(
                account_snapshot_fn=account_snapshot_fn,
                positions_snapshot_fn=positions_snapshot_fn,
            )
            result = handle_sl_command(
                cmd,
                positions=current_positions,
                get_current_price_fn=get_current_price_fn,
                update_tpsl_fn=update_tpsl_fn,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /sl command: %s", exc)
            fallback = "⚠️ *止损命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"sl via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Stop loss updated via Telegram /sl | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["sl"] = sl_handler

    def tp_handler(cmd: TelegramCommand) -> None:
        """Handler for /tp command (set take profit)."""
        try:
            # Get current positions from live exchange or local portfolio
            current_positions = get_positions_for_tpsl(
                account_snapshot_fn=account_snapshot_fn,
                positions_snapshot_fn=positions_snapshot_fn,
            )
            result = handle_tp_command(
                cmd,
                positions=current_positions,
                get_current_price_fn=get_current_price_fn,
                update_tpsl_fn=update_tpsl_fn,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /tp command: %s", exc)
            fallback = "⚠️ *止盈命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"tp via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"Take profit updated via Telegram /tp | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["tp"] = tp_handler

    def tpsl_handler(cmd: TelegramCommand) -> None:
        """Handler for /tpsl command (set both stop loss and take profit)."""
        try:
            # Get current positions from live exchange or local portfolio
            current_positions = get_positions_for_tpsl(
                account_snapshot_fn=account_snapshot_fn,
                positions_snapshot_fn=positions_snapshot_fn,
            )
            result = handle_tpsl_command(
                cmd,
                positions=current_positions,
                get_current_price_fn=get_current_price_fn,
                update_tpsl_fn=update_tpsl_fn,
            )
        except Exception as exc:
            logging.error("Error processing Telegram /tpsl command: %s", exc)
            fallback = "⚠️ *TP/SL 命令处理出错，请稍后重试。*"
            _send_response(fallback, cmd.chat_id)
            return

        _send_response(result.message, cmd.chat_id)

        if result.action:
            detail = f"tpsl via Telegram | chat_id={cmd.chat_id}"
            if result.state_changed:
                detail = (
                    f"TP/SL updated via Telegram /tpsl | "
                    f"chat_id={cmd.chat_id}"
                )
            _record_event(result.action, detail)

    handlers["tpsl"] = tpsl_handler

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
