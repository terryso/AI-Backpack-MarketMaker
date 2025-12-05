"""
CLI entry point for llm-trader.

Usage:
    python -m cli.main <command> [args...]
    
Or if installed as console script:
    llm-trader <command> [args...]

This CLI reuses the same command handlers as the Telegram bot,
ensuring consistent behavior across both interfaces.
"""
from __future__ import annotations

import logging
import sys
from typing import List, Optional

import click

from cli.context import build_cli_context, save_risk_control_state, CLIContext
from cli.output import print_result, print_error, strip_markdown
from notifications.commands.base import TelegramCommand, CommandResult
from notifications.commands.audit import DEFAULT_EXCHANGE, SUPPORTED_EXCHANGES


# Configure logging for CLI
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)


def _make_cmd(command: str, args: Optional[List[str]] = None) -> TelegramCommand:
    """Create a TelegramCommand for CLI usage.
    
    Args:
        command: Command name (without leading slash).
        args: Command arguments.
        
    Returns:
        TelegramCommand configured for CLI context.
    """
    return TelegramCommand(
        command=command,
        args=args or [],
        chat_id="CLI",
        message_id=0,
        raw_text=f"/{command} {' '.join(args or [])}".strip(),
        raw_update={},
        user_id="CLI",
    )


def _handle_result(result: CommandResult, ctx: Optional[CLIContext] = None) -> None:
    """Handle command result: print output and save state if changed.
    
    Args:
        result: CommandResult from command handler.
        ctx: CLI context for saving state changes.
    """
    print_result(result.message, result.success)
    
    if result.state_changed and ctx is not None:
        save_risk_control_state(ctx)


# ═══════════════════════════════════════════════════════════════════
# CLI GROUP AND COMMANDS
# ═══════════════════════════════════════════════════════════════════

@click.group()
@click.option('-v', '--verbose', is_flag=True, help='启用详细日志输出')
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """LLM Trader CLI - 本地命令行控制工具
    
    复用 Telegram Bot 的命令逻辑，提供本地快速操作。
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Build context lazily on first command that needs it
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose


def get_context(ctx: click.Context) -> CLIContext:
    """Get or build CLI context."""
    if 'cli_context' not in ctx.obj:
        ctx.obj['cli_context'] = build_cli_context()
    return ctx.obj['cli_context']


# ─────────────────────────────────────────────────────────────────
# STATUS / BALANCE / POSITIONS
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """查看 Bot 资金与盈利状态"""
    from notifications.commands.status import handle_status_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("status")
    
    result = handle_status_command(
        cmd,
        balance=cli_ctx.balance_fn(),
        total_equity=cli_ctx.total_equity_fn(),
        total_margin=cli_ctx.total_margin_fn(),
        positions_count=cli_ctx.positions_count_fn(),
        start_capital=cli_ctx.start_capital,
        sortino_ratio=cli_ctx.sortino_ratio_fn() if cli_ctx.sortino_ratio_fn else None,
        kill_switch_active=cli_ctx.risk_control_state.kill_switch_active,
    )
    _handle_result(result)


@cli.command()
@click.pass_context
def balance(ctx: click.Context) -> None:
    """查看当前账户余额与持仓概要"""
    from notifications.commands.balance import handle_balance_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("balance")
    
    result = handle_balance_command(
        cmd,
        balance=cli_ctx.balance_fn(),
        total_equity=cli_ctx.total_equity_fn(),
        total_margin=cli_ctx.total_margin_fn(),
        positions_count=cli_ctx.positions_count_fn(),
        start_capital=cli_ctx.start_capital,
    )
    _handle_result(result)


@cli.command()
@click.pass_context
def positions(ctx: click.Context) -> None:
    """查看当前所有持仓详情"""
    from notifications.commands.positions import handle_positions_command, get_positions_from_snapshot
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("positions")
    
    current_positions = get_positions_from_snapshot(
        account_snapshot_fn=cli_ctx.account_snapshot_fn,
        positions_snapshot_fn=cli_ctx.positions_snapshot_fn,
    )
    
    result = handle_positions_command(
        cmd,
        positions=current_positions,
        get_current_price_fn=cli_ctx.get_current_price_fn,
    )
    _handle_result(result)


# ─────────────────────────────────────────────────────────────────
# KILL / RESUME / RISK
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def kill(ctx: click.Context) -> None:
    """激活 Kill-Switch，暂停所有新开仓"""
    from notifications.commands.kill import handle_kill_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("kill")
    
    result = handle_kill_command(
        cmd,
        cli_ctx.risk_control_state,
        positions_count=cli_ctx.positions_count_fn(),
    )
    _handle_result(result, cli_ctx)


@cli.command()
@click.pass_context
def resume(ctx: click.Context) -> None:
    """解除 Kill-Switch 并恢复新开仓"""
    from notifications.commands.resume import handle_resume_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("resume")
    
    result = handle_resume_command(cmd, cli_ctx.risk_control_state)
    _handle_result(result, cli_ctx)


@cli.command()
@click.pass_context
def risk(ctx: click.Context) -> None:
    """查看风控配置与状态"""
    from notifications.commands.risk import handle_risk_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("risk")
    
    result = handle_risk_command(
        cmd,
        cli_ctx.risk_control_state,
        total_equity=cli_ctx.total_equity_fn(),
        positions_count=cli_ctx.positions_count_fn(),
        risk_control_enabled=cli_ctx.risk_control_enabled,
        daily_loss_limit_enabled=cli_ctx.daily_loss_limit_enabled,
        daily_loss_limit_pct=cli_ctx.daily_loss_limit_pct,
    )
    _handle_result(result)


@cli.command("reset-daily")
@click.pass_context
def reset_daily(ctx: click.Context) -> None:
    """手动重置每日亏损基准"""
    from notifications.commands.reset_daily import handle_reset_daily_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("reset_daily")
    
    result = handle_reset_daily_command(
        cmd,
        cli_ctx.risk_control_state,
        total_equity=cli_ctx.total_equity_fn(),
        risk_control_enabled=cli_ctx.risk_control_enabled,
    )
    _handle_result(result, cli_ctx)


# ─────────────────────────────────────────────────────────────────
# CLOSE / CLOSE-ALL
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('symbol')
@click.argument('amount', required=False, default=None)
@click.pass_context
def close(ctx: click.Context, symbol: str, amount: Optional[str]) -> None:
    """平仓指定品种
    
    SYMBOL: 交易对名称 (如 BTC, BTCUSDT)
    
    AMOUNT: 平仓比例 (0-100) 或 'all' 表示全平，不指定则全平
    
    示例:
        llm-trader close BTC        # 全平 BTC
        llm-trader close BTC 50     # 平仓 50%
        llm-trader close BTC all    # 全平
    """
    from notifications.commands.close import handle_close_command, get_positions_for_close
    
    cli_ctx = get_context(ctx)
    args = [symbol]
    if amount is not None:
        args.append(amount)
    cmd = _make_cmd("close", args)
    
    current_positions = get_positions_for_close(
        account_snapshot_fn=cli_ctx.account_snapshot_fn,
        positions_snapshot_fn=cli_ctx.positions_snapshot_fn,
    )
    
    result = handle_close_command(
        cmd,
        positions=current_positions,
        execute_close_fn=cli_ctx.execute_close_fn,
    )
    _handle_result(result, cli_ctx)


@cli.command("close-all")
@click.argument('direction', required=False, default=None)
@click.option('--confirm', is_flag=True, help='跳过确认直接执行')
@click.pass_context
def close_all(ctx: click.Context, direction: Optional[str], confirm: bool) -> None:
    """一键全平所有持仓
    
    DIRECTION: 可选，'long' 只平多头，'short' 只平空头，不指定则全平
    
    示例:
        llm-trader close-all              # 全平所有
        llm-trader close-all long         # 只平多头
        llm-trader close-all short        # 只平空头
        llm-trader close-all --confirm    # 跳过确认
    """
    from notifications.commands.close_all import handle_close_all_command
    from notifications.commands.close import get_positions_for_close
    
    cli_ctx = get_context(ctx)
    args = []
    if direction:
        args.append(direction)
    if confirm:
        args.append("confirm")
    cmd = _make_cmd("close_all", args)
    
    current_positions = get_positions_for_close(
        account_snapshot_fn=cli_ctx.account_snapshot_fn,
        positions_snapshot_fn=cli_ctx.positions_snapshot_fn,
    )
    
    result = handle_close_all_command(
        cmd,
        positions=current_positions,
        execute_close_fn=cli_ctx.execute_close_fn,
        kill_switch_active=cli_ctx.risk_control_state.kill_switch_active,
        daily_loss_triggered=cli_ctx.risk_control_state.daily_loss_triggered,
    )
    _handle_result(result, cli_ctx)


# ─────────────────────────────────────────────────────────────────
# SL / TP / TPSL
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('symbol')
@click.argument('value')
@click.pass_context
def sl(ctx: click.Context, symbol: str, value: str) -> None:
    """设置止损
    
    SYMBOL: 交易对名称
    
    VALUE: 止损价格或百分比 (如 95000 或 -5%)
    
    示例:
        llm-trader sl BTC 95000    # 设置止损价格
        llm-trader sl BTC -5%      # 设置止损百分比
    """
    from notifications.commands.tpsl import handle_sl_command, get_positions_for_tpsl
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("sl", [symbol, value])
    
    current_positions = get_positions_for_tpsl(
        account_snapshot_fn=cli_ctx.account_snapshot_fn,
        positions_snapshot_fn=cli_ctx.positions_snapshot_fn,
    )
    
    result = handle_sl_command(
        cmd,
        positions=current_positions,
        get_current_price_fn=cli_ctx.get_current_price_fn,
        update_tpsl_fn=cli_ctx.update_tpsl_fn,
    )
    _handle_result(result, cli_ctx)


@cli.command()
@click.argument('symbol')
@click.argument('value')
@click.pass_context
def tp(ctx: click.Context, symbol: str, value: str) -> None:
    """设置止盈
    
    SYMBOL: 交易对名称
    
    VALUE: 止盈价格或百分比 (如 105000 或 10%)
    
    示例:
        llm-trader tp BTC 105000   # 设置止盈价格
        llm-trader tp BTC 10%      # 设置止盈百分比
    """
    from notifications.commands.tpsl import handle_tp_command, get_positions_for_tpsl
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("tp", [symbol, value])
    
    current_positions = get_positions_for_tpsl(
        account_snapshot_fn=cli_ctx.account_snapshot_fn,
        positions_snapshot_fn=cli_ctx.positions_snapshot_fn,
    )
    
    result = handle_tp_command(
        cmd,
        positions=current_positions,
        get_current_price_fn=cli_ctx.get_current_price_fn,
        update_tpsl_fn=cli_ctx.update_tpsl_fn,
    )
    _handle_result(result, cli_ctx)


@cli.command()
@click.argument('symbol')
@click.argument('sl_value')
@click.argument('tp_value')
@click.pass_context
def tpsl(ctx: click.Context, symbol: str, sl_value: str, tp_value: str) -> None:
    """同时设置止损和止盈
    
    SYMBOL: 交易对名称
    
    SL_VALUE: 止损价格或百分比
    
    TP_VALUE: 止盈价格或百分比
    
    示例:
        llm-trader tpsl BTC 95000 105000    # 设置价格
        llm-trader tpsl BTC -5% 10%         # 设置百分比
    """
    from notifications.commands.tpsl import handle_tpsl_command, get_positions_for_tpsl
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("tpsl", [symbol, sl_value, tp_value])
    
    current_positions = get_positions_for_tpsl(
        account_snapshot_fn=cli_ctx.account_snapshot_fn,
        positions_snapshot_fn=cli_ctx.positions_snapshot_fn,
    )
    
    result = handle_tpsl_command(
        cmd,
        positions=current_positions,
        get_current_price_fn=cli_ctx.get_current_price_fn,
        update_tpsl_fn=cli_ctx.update_tpsl_fn,
    )
    _handle_result(result, cli_ctx)


# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────

@cli.group()
def config() -> None:
    """配置管理命令"""
    pass


@config.command("list")
@click.pass_context
def config_list(ctx: click.Context) -> None:
    """列出可配置项及当前值"""
    from notifications.commands.config import handle_config_list_command
    
    cmd = _make_cmd("config", ["list"])
    result = handle_config_list_command(cmd)
    _handle_result(result)


@config.command("get")
@click.argument('key')
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """查看指定配置项详情
    
    KEY: 配置项名称
    """
    from notifications.commands.config import handle_config_get_command
    
    cmd = _make_cmd("config", ["get", key])
    result = handle_config_get_command(cmd, key)
    _handle_result(result)


@config.command("set")
@click.argument('key')
@click.argument('value')
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """修改运行时配置
    
    KEY: 配置项名称
    
    VALUE: 新值
    
    示例:
        llm-trader config set TRADEBOT_INTERVAL 5m
        llm-trader config set TRADEBOT_LOOP_ENABLED false
    """
    from notifications.commands.config import handle_config_set_command
    
    cmd = _make_cmd("config", ["set", key, value])
    result = handle_config_set_command(cmd, key, value)
    _handle_result(result)


# ─────────────────────────────────────────────────────────────────
# SYMBOLS
# ─────────────────────────────────────────────────────────────────

@cli.group()
def symbols() -> None:
    """交易对 Universe 管理"""
    pass


@symbols.command("list")
@click.pass_context
def symbols_list(ctx: click.Context) -> None:
    """查看当前交易 Universe"""
    from notifications.commands.symbols import handle_symbols_list_command
    
    cmd = _make_cmd("symbols", ["list"])
    result = handle_symbols_list_command(cmd)
    _handle_result(result)


@symbols.command("add")
@click.argument('symbol')
@click.pass_context
def symbols_add(ctx: click.Context, symbol: str) -> None:
    """添加交易对到 Universe
    
    SYMBOL: 交易对名称 (如 BTCUSDT)
    """
    from notifications.commands.symbols import handle_symbols_add_command
    
    cmd = _make_cmd("symbols", ["add", symbol])
    result = handle_symbols_add_command(cmd, symbol)
    _handle_result(result)


@symbols.command("remove")
@click.argument('symbol')
@click.pass_context
def symbols_remove(ctx: click.Context, symbol: str) -> None:
    """从 Universe 移除交易对
    
    SYMBOL: 交易对名称
    """
    from notifications.commands.symbols import handle_symbols_remove_command
    
    cmd = _make_cmd("symbols", ["remove", symbol])
    result = handle_symbols_remove_command(cmd, symbol)
    _handle_result(result)


# ─────────────────────────────────────────────────────────────────
# AUDIT / HELP
# ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('start_time', required=False, default=None)
@click.argument('end_time', required=False, default=None)
@click.option(
    '--exchange', '-e',
    default=DEFAULT_EXCHANGE,
    type=click.Choice(SUPPORTED_EXCHANGES, case_sensitive=False),
    help='交易所名称 (默认: 根据 TRADING_BACKEND 自动推断)',
)
@click.pass_context
def audit(
    ctx: click.Context,
    start_time: Optional[str],
    end_time: Optional[str],
    exchange: str,
) -> None:
    """查看账户资金变动分析
    
    START_TIME: 开始时间 (可选，默认今天 00:00)
    
    END_TIME: 结束时间 (可选，默认当前时间)
    
    时间格式:
        HH:MM           - 今天的时间
        YYYY-MM-DD      - 日期
        YYYY-MM-DD HH:MM - 日期时间
    
    示例:
        llm-trader audit                        # 今天 00:00 到现在 (Backpack)
        llm-trader audit 09:00                  # 今天 09:00 到现在
        llm-trader audit 09:00 18:00            # 今天 09:00 到 18:00
        llm-trader audit --exchange backpack    # 指定交易所
    """
    from notifications.commands.audit import handle_audit_command
    
    args = []
    if start_time:
        args.append(start_time)
    if end_time:
        args.append(end_time)
    
    cmd = _make_cmd("audit", args)
    result = handle_audit_command(cmd, exchange=exchange)
    _handle_result(result)


@cli.command("help")
@click.pass_context
def help_cmd(ctx: click.Context) -> None:
    """显示帮助信息"""
    from notifications.commands.help import handle_help_command
    
    cli_ctx = get_context(ctx)
    cmd = _make_cmd("help")
    
    result = handle_help_command(
        cmd,
        risk_control_enabled=cli_ctx.risk_control_enabled,
    )
    _handle_result(result)


# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    """Main entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
