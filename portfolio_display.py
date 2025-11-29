"""
Portfolio display and logging.

This module handles the display and logging of portfolio state,
including summary display and CSV logging.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from colorama import Fore, Style

from trading_config import (
    START_CAPITAL,
    STATE_CSV,
    CHECK_INTERVAL,
    RISK_FREE_RATE,
)
from trading_loop import calculate_sortino_ratio
from state_io import append_portfolio_state_row as _append_portfolio_state_row


def log_portfolio_state(
    positions: Dict[str, Dict[str, Any]],
    balance: float,
    calculate_total_equity: Callable[[], float],
    calculate_total_margin: Callable[[], float],
    get_btc_benchmark_price: Callable[[], Optional[float]],
    get_current_time: Callable,
) -> None:
    """Log current portfolio state to CSV."""
    total_equity = calculate_total_equity()
    total_return = ((total_equity - START_CAPITAL) / START_CAPITAL) * 100
    total_margin = calculate_total_margin()
    net_unrealized = total_equity - balance - total_margin

    position_details = "; ".join([
        f"{coin}:{pos['side']}:{pos['quantity']:.4f}@{pos['entry_price']:.4f}"
        for coin, pos in positions.items()
    ]) if positions else "No positions"

    btc_price = get_btc_benchmark_price()
    btc_price_str = f"{btc_price:.2f}" if btc_price is not None else ""

    timestamp = get_current_time().isoformat()
    _append_portfolio_state_row(
        STATE_CSV,
        timestamp,
        f"{balance:.2f}",
        f"{total_equity:.2f}",
        f"{total_return:.2f}",
        len(positions),
        position_details,
        f"{total_margin:.2f}",
        f"{net_unrealized:.2f}",
        btc_price_str,
    )


def display_portfolio_summary(
    positions: Dict[str, Dict[str, Any]],
    balance: float,
    equity_history: List[float],
    calculate_total_equity: Callable[[], float],
    calculate_total_margin: Callable[[], float],
    register_equity_snapshot: Callable[[float], None],
    record_iteration_message: Callable[[str], None],
) -> None:
    """Display the portfolio summary at the end of an iteration."""
    total_equity = calculate_total_equity()
    total_return = ((total_equity - START_CAPITAL) / START_CAPITAL) * 100
    equity_color = Fore.GREEN if total_return >= 0 else Fore.RED
    total_margin = calculate_total_margin()
    net_unrealized_total = total_equity - balance - total_margin
    net_color = Fore.GREEN if net_unrealized_total >= 0 else Fore.RED
    register_equity_snapshot(total_equity)
    sortino_ratio = calculate_sortino_ratio(
        equity_history,
        CHECK_INTERVAL,
        RISK_FREE_RATE,
    )

    line = f"\n{Fore.YELLOW}{'─'*20}"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.YELLOW}PORTFOLIO SUMMARY"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.YELLOW}{'─'*20}"
    print(line)
    record_iteration_message(line)
    line = f"Available Balance: ${balance:.2f}"
    print(line)
    record_iteration_message(line)
    if total_margin > 0:
        line = f"Margin Allocated: ${total_margin:.2f}"
        print(line)
        record_iteration_message(line)
    line = f"Total Equity: {equity_color}${total_equity:.2f} ({total_return:+.2f}%){Style.RESET_ALL}"
    print(line)
    record_iteration_message(line)
    line = f"Unrealized PnL: {net_color}${net_unrealized_total:.2f}{Style.RESET_ALL}"
    print(line)
    record_iteration_message(line)
    if sortino_ratio is not None:
        sortino_color = Fore.GREEN if sortino_ratio >= 0 else Fore.RED
        line = f"Sortino Ratio: {sortino_color}{sortino_ratio:+.2f}{Style.RESET_ALL}"
    else:
        line = "Sortino Ratio: N/A (need more data)"
    print(line)
    record_iteration_message(line)
    line = f"Open Positions: {len(positions)}"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.YELLOW}{'─'*20}\n"
    print(line)
    record_iteration_message(line)
