#!/usr/bin/env python3
"""
DeepSeek Multi-Asset Paper Trading Bot (Simplified)

This is the main entry point for the trading bot. The bot uses LLM for trading decisions
and supports multiple exchanges (Binance, Hyperliquid, Backpack).

Refactored Architecture:
- strategy/: Technical indicators and market snapshots
- llm/: LLM prompt building and response parsing  
- display/: Message formatting for Telegram
- exchange/: Exchange client abstractions and implementations
- execution/: Trade execution and routing logic
- utils/: Common utilities
"""
from __future__ import annotations

import threading
import time
import logging
import math
from typing import Any, Dict, List, Optional

import pandas as pd
from colorama import Fore
import requests

# ───────────────────────── LOGGING SETUP ─────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

# ───────────────────────── CONFIGURATION ─────────────────────────
import config.settings as _config_settings
from config.settings import (
    LLM_API_KEY, LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_MAX_TOKENS,
    LLM_THINKING_PARAM, LLM_API_BASE_URL, LLM_API_TYPE,
    TRADING_RULES_PROMPT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    START_CAPITAL, CHECK_INTERVAL, INTERVAL, SYMBOLS,
    SYMBOL_TO_COIN, COIN_TO_SYMBOL, TAKER_FEE_RATE, MAKER_FEE_RATE,
    STATE_CSV, STATE_JSON, TRADES_CSV, DECISIONS_CSV,
    MESSAGES_CSV, MESSAGES_RECENT_CSV, MAX_RECENT_MESSAGES, STATE_COLUMNS,
    log_system_prompt_info, BACKPACK_API_BASE_URL, MARKET_DATA_BACKEND,
    EMA_LEN, RSI_LEN, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    OPENROUTER_API_KEY, SYSTEM_PROMPT_SOURCE, describe_system_prompt_source,
    DEFAULT_TRADING_RULES_PROMPT, DEFAULT_LLM_MODEL,
    TRADING_BACKEND, BINANCE_FUTURES_LIVE, BACKPACK_FUTURES_LIVE,
    RISK_CONTROL_ENABLED, DAILY_LOSS_LIMIT_ENABLED, DAILY_LOSS_LIMIT_PCT,
    RISK_FREE_RATE,
    get_effective_tradebot_loop_enabled,
    BACKPACK_API_PUBLIC_KEY, BACKPACK_API_SECRET_SEED, BACKPACK_API_WINDOW_MS,
)
from config import get_effective_coin_universe, resolve_symbol_for_coin


def refresh_llm_configuration_from_env() -> None:
    """Reload LLM settings from environment."""
    global LLM_API_KEY, LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_MAX_TOKENS
    global LLM_THINKING_PARAM, LLM_API_BASE_URL, LLM_API_TYPE
    global TRADING_RULES_PROMPT, OPENROUTER_API_KEY, SYSTEM_PROMPT_SOURCE
    # Sync module-level OPENROUTER_API_KEY to config.settings before refresh
    _config_settings.OPENROUTER_API_KEY = OPENROUTER_API_KEY
    _config_settings.refresh_llm_configuration_from_env()
    # Read updated values from config.settings
    LLM_API_KEY = _config_settings.LLM_API_KEY
    LLM_MODEL_NAME = _config_settings.LLM_MODEL_NAME
    LLM_TEMPERATURE = _config_settings.LLM_TEMPERATURE
    LLM_MAX_TOKENS = _config_settings.LLM_MAX_TOKENS
    LLM_THINKING_PARAM = _config_settings.LLM_THINKING_PARAM
    LLM_API_BASE_URL = _config_settings.LLM_API_BASE_URL
    LLM_API_TYPE = _config_settings.LLM_API_TYPE
    TRADING_RULES_PROMPT = _config_settings.TRADING_RULES_PROMPT
    OPENROUTER_API_KEY = _config_settings.OPENROUTER_API_KEY
    SYSTEM_PROMPT_SOURCE = _config_settings.SYSTEM_PROMPT_SOURCE

def get_effective_interval() -> str:
    """Get the effective interval from environment or config."""
    return _config_settings.get_effective_interval()

def get_effective_check_interval() -> int:
    """Get the effective check interval from environment or config."""
    return _config_settings.get_effective_check_interval()

def get_effective_llm_temperature() -> float:
    """Get the effective LLM temperature from environment or config."""
    return _config_settings.get_effective_llm_temperature()

def get_effective_tradebot_loop_enabled() -> bool:
    """Get the effective tradebot loop enabled from environment or config."""
    return _config_settings.get_effective_tradebot_loop_enabled()

# ───────────────────────── STATE MANAGEMENT ─────────────────────────
import core.state as _core_state
from core.state import (
    get_balance, get_positions, get_current_time, get_bot_start_time,
    get_iteration_messages, get_equity_history, get_iteration_counter,
    increment_iteration_counter, clear_iteration_messages, reset_state,
    set_last_btc_price, get_last_btc_price, escape_markdown,
    increment_invocation_count,
    load_state as _core_load_state,
    save_state as _core_save_state,
    risk_control_state as _risk_control_state,
)
from core.risk_control import check_risk_limits, update_daily_baseline

# Module-level state references (for test compatibility)
positions = _core_state.positions
balance = _core_state.balance
equity_history = _core_state.equity_history
iteration_counter = _core_state.iteration_counter

# ───────────────────────── EXCHANGE CLIENTS ─────────────────────────
from exchange.factory import (
    get_binance_client, get_binance_futures_exchange, get_hyperliquid_trader,
)
from exchange.market_data import BinanceMarketDataClient, BackpackMarketDataClient
from exchange.backpack import BackpackFuturesExchangeClient

hyperliquid_trader = get_hyperliquid_trader()
_market_data_client = None
_telegram_command_handler: Optional[TelegramCommandHandler] = None

# ───────────────────────── STATE I/O ─────────────────────────
from core.persistence import (
    load_state_from_json, save_state_to_json, init_csv_files_for_paths,
)

# ───────────────────────── NOTIFICATIONS ─────────────────────────
from notifications.logging import (
    log_ai_message as _log_ai_message,
    notify_error as _notify_error,
)
from notifications.telegram import (
    send_telegram_message as _send_telegram_message,
    create_daily_loss_limit_notify_callback,
)
from notifications.telegram_commands import (
    TelegramCommandHandler,
    create_command_handler,
    process_telegram_commands,
    create_kill_resume_handlers,
    register_telegram_commands,
)
from notifications.commands.positions import parse_live_positions
from core.trading_loop import log_risk_control_event

# ───────────────────────── METRICS ─────────────────────────
from core.metrics import (
    calculate_unrealized_pnl_for_position,
    calculate_net_unrealized_pnl_for_position,
    estimate_exit_fee_for_position,
    calculate_total_margin_for_positions,
    calculate_sortino_ratio,
    calculate_pnl_for_price,
    format_leverage_display,
)

# ───────────────────────── INDICATORS ─────────────────────────
from strategy.indicators import (
    calculate_rsi_series, add_indicator_columns, calculate_atr_series,
    calculate_indicators as _calculate_indicators, round_series,
)


def calculate_indicators(df: pd.DataFrame) -> pd.Series:
    """Calculate indicators with default parameters (for test compatibility)."""
    return _calculate_indicators(df, EMA_LEN, RSI_LEN, MACD_FAST, MACD_SLOW, MACD_SIGNAL)

# ───────────────────────── PROMPT & LLM ─────────────────────────
from llm.prompt import (
    fetch_market_data as _fetch_market_data,
    format_prompt_for_deepseek as _format_prompt,
    collect_prompt_market_data as _collect_prompt_market_data,
)
from llm.client import call_deepseek_api
from llm.parser import parse_llm_json_decisions, recover_partial_decisions

# For test compatibility - expose internal helpers
from llm.client import _recover_partial_decisions, _log_llm_decisions


def collect_prompt_market_data(symbol: str):
    """Wrapper for test compatibility - uses get_market_data_client."""
    return _collect_prompt_market_data(symbol, get_market_data_client)

# Interval mapping for test compatibility
_INTERVAL_TO_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}

# ───────────────────────── EXECUTION ─────────────────────────
from execution.executor import TradeExecutor
from execution.routing import check_stop_loss_take_profit_for_positions, route_live_close
from exchange.base import CloseResult

# ───────────────────────── DISPLAY ─────────────────────────
from display.portfolio import (
    log_portfolio_state as _log_portfolio_state,
    display_portfolio_summary as _display_portfolio_summary,
)

# ───────────────────────── TRADING LOOP (for test compatibility) ─────────────────────────
from core.trading_loop import (
    log_trade, log_ai_decision, record_iteration_message, sleep_with_countdown,
    execute_entry as _tl_execute_entry, execute_close as _tl_execute_close,
    check_stop_loss_take_profit as _tl_check_sltp,
)


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def _set_balance(new_balance: float) -> None:
    """Set the balance."""
    global balance
    balance = new_balance
    _core_state.balance = new_balance


def get_market_data_client():
    """Get or initialize market data client."""
    global _market_data_client
    if _market_data_client is not None:
        return _market_data_client
    
    if MARKET_DATA_BACKEND == "binance":
        client = get_binance_client()
        if client:
            _market_data_client = BinanceMarketDataClient(client)
    elif MARKET_DATA_BACKEND == "backpack":
        _market_data_client = BackpackMarketDataClient(BACKPACK_API_BASE_URL)
    return _market_data_client


# ───────────────────────── LIVE ACCOUNT SNAPSHOT ─────────────────────────
# Cached Backpack client for account queries (separate from trading client)
_backpack_account_client: Optional[BackpackFuturesExchangeClient] = None


def _get_backpack_account_client() -> Optional[BackpackFuturesExchangeClient]:
    """Get or initialize Backpack client for account queries."""
    global _backpack_account_client
    if _backpack_account_client is not None:
        return _backpack_account_client

    if not BACKPACK_API_PUBLIC_KEY or not BACKPACK_API_SECRET_SEED:
        logging.debug("Backpack account client not available: missing API credentials")
        return None

    try:
        _backpack_account_client = BackpackFuturesExchangeClient(
            api_public_key=BACKPACK_API_PUBLIC_KEY,
            api_secret_seed=BACKPACK_API_SECRET_SEED,
            base_url=BACKPACK_API_BASE_URL,
            window_ms=BACKPACK_API_WINDOW_MS,
        )
        logging.info("Backpack account client initialized for /balance queries")
    except Exception as exc:
        logging.warning("Failed to initialize Backpack account client: %s", exc)
        _backpack_account_client = None

    return _backpack_account_client


def get_live_account_snapshot() -> Optional[Dict[str, Any]]:
    """Get live account snapshot from the configured exchange.

    This function checks the current TRADING_BACKEND and fetches real-time
    account data from the appropriate exchange API.

    Returns:
        Dictionary with unified account snapshot:
        - balance: Available balance
        - total_equity: Total account equity
        - total_margin: Margin in use
        - positions_count: Number of open positions
        Returns None if:
        - No live backend is configured
        - API credentials are missing
        - API call fails
    """
    # Binance Futures
    if TRADING_BACKEND == "binance_futures" and BINANCE_FUTURES_LIVE:
        return _get_binance_futures_snapshot()

    # Backpack Futures
    if TRADING_BACKEND == "backpack_futures" and BACKPACK_FUTURES_LIVE:
        return _get_backpack_futures_snapshot()

    # No live backend configured, return None to use local portfolio view
    return None


def _get_binance_futures_snapshot() -> Optional[Dict[str, Any]]:
    """Get account snapshot from Binance Futures API.

    Uses the python-binance Client.futures_account() method to fetch:
    - totalWalletBalance: Wallet balance (available funds)
    - totalMarginBalance: Total margin balance (equity)
    - positions: List of positions for margin calculation
    """
    client = get_binance_client()
    if client is None:
        logging.warning("Binance client not available for account snapshot")
        return None

    try:
        account = client.futures_account()
    except Exception as exc:
        logging.warning("Failed to fetch Binance futures account: %s", exc)
        return None

    if not isinstance(account, dict):
        logging.warning("Binance futures_account returned unexpected type: %r", type(account))
        return None

    try:
        # totalWalletBalance: wallet balance (deposited funds)
        # totalMarginBalance: total margin balance including unrealized PnL
        # availableBalance: available for new positions
        wallet_balance = float(account.get("totalWalletBalance", 0) or 0)
        margin_balance = float(account.get("totalMarginBalance", 0) or 0)
        available_balance = float(account.get("availableBalance", 0) or 0)

        # Calculate margin in use and count positions
        total_margin = 0.0
        positions_count = 0
        positions_list = account.get("positions", [])
        if isinstance(positions_list, list):
            for pos in positions_list:
                if not isinstance(pos, dict):
                    continue
                try:
                    pos_amt = float(pos.get("positionAmt", 0) or 0)
                except (TypeError, ValueError):
                    pos_amt = 0.0
                if pos_amt != 0:
                    positions_count += 1
                    # Use initialMargin or isolatedMargin for margin calculation
                    try:
                        initial_margin = float(pos.get("initialMargin", 0) or 0)
                        isolated_margin = float(pos.get("isolatedMargin", 0) or 0)
                        total_margin += max(initial_margin, isolated_margin)
                    except (TypeError, ValueError):
                        pass

        return {
            "balance": available_balance,
            "total_equity": margin_balance,
            "total_margin": total_margin,
            "positions_count": positions_count,
        }
    except (TypeError, ValueError) as exc:
        logging.warning("Failed to parse Binance account data: %s", exc)
        return None


def _get_backpack_futures_snapshot() -> Optional[Dict[str, Any]]:
    """Get account snapshot from Backpack Futures API.

    Uses BackpackFuturesExchangeClient.get_account_snapshot() which calls:
    - collateralQuery: For netEquity, netEquityAvailable, netEquityLocked
    - positionQuery: For positions count
    """
    client = _get_backpack_account_client()
    if client is None:
        return None

    try:
        return client.get_account_snapshot()
    except Exception as exc:
        logging.warning("Failed to get Backpack account snapshot: %s", exc)
        return None


def get_telegram_command_handler() -> Optional[TelegramCommandHandler]:
    """Get or initialize Telegram command handler.
    
    Returns:
        TelegramCommandHandler instance if Telegram is configured, None otherwise.
        The handler is created once and reused to preserve last_update_id state.
    """
    global _telegram_command_handler
    if _telegram_command_handler is not None:
        return _telegram_command_handler
    
    _telegram_command_handler = create_command_handler(
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
    )
    return _telegram_command_handler


def poll_telegram_commands() -> None:
    """Poll and process Telegram commands.
    
    This function is called at the beginning of each iteration to check for
    new Telegram commands. Commands are parsed and passed to process_telegram_commands
    for handling.
    
    Story 7.4.1 implements the polling infrastructure.
    Story 7.4.2 adds /kill and /resume command handlers.
    Stories 7.4.3-7.4.5 will add /status, /reset_daily, /help handlers.
    
    Error handling:
        - If Telegram is not configured, silently returns
        - Network/API errors are logged but do not interrupt the main loop
        - Command handler errors are logged but do not interrupt the main loop
    """
    handler = get_telegram_command_handler()
    if handler is None:
        return
    
    try:
        commands = handler.poll_commands()
        if commands:
            logging.info(
                "Telegram commands received: %d command(s)",
                len(commands),
            )
            # Create command handlers for Telegram commands
            command_handlers = create_kill_resume_handlers(
                state=_core_state.risk_control_state,
                positions_count_fn=lambda: len(positions),
                positions_snapshot_fn=lambda: positions,
                record_event_fn=log_risk_control_event,
                bot_token=TELEGRAM_BOT_TOKEN,
                chat_id=TELEGRAM_CHAT_ID,
                total_equity_fn=calculate_total_equity,
                balance_fn=lambda: balance,
                total_margin_fn=calculate_total_margin,
                start_capital=START_CAPITAL,
                sortino_ratio_fn=lambda: calculate_sortino_ratio(
                    equity_history,
                    get_effective_check_interval(),
                    RISK_FREE_RATE,
                ),
                risk_control_enabled=RISK_CONTROL_ENABLED,
                daily_loss_limit_enabled=DAILY_LOSS_LIMIT_ENABLED,
                daily_loss_limit_pct=DAILY_LOSS_LIMIT_PCT,
                account_snapshot_fn=get_live_account_snapshot,
                execute_close_fn=execute_telegram_close,
                update_tpsl_fn=update_telegram_tpsl,
                get_current_price_fn=get_current_price_for_coin,
            )
            # Process commands with handlers
            process_telegram_commands(commands, command_handlers=command_handlers)
    except Exception as exc:
        # Defensive: ensure command polling never breaks the main loop
        logging.error(
            "Unexpected error in Telegram command polling: %s",
            exc,
        )


# ───────────────────────── TELEGRAM COMMAND THREAD ─────────────────────────
# Polling interval for the dedicated Telegram command thread (in seconds).
# This is independent of the main trading loop's CHECK_INTERVAL.
TELEGRAM_COMMAND_POLL_INTERVAL = 3


def _telegram_command_loop() -> None:
    """Background thread loop for polling Telegram commands.
    
    This thread runs independently of the main trading loop, polling for
    Telegram commands at a shorter interval (TELEGRAM_COMMAND_POLL_INTERVAL).
    This allows commands like /status, /kill, /resume to be processed
    within seconds, regardless of the main trading loop's CHECK_INTERVAL.
    
    The thread shares state with the main loop (risk_control_state, positions,
    balance) since it runs in the same process. All state modifications are
    done through the same functions used by the main loop.
    
    Error handling:
        - All exceptions are caught and logged to prevent thread termination
        - Network/API errors are logged but the thread continues running
        - The thread is a daemon thread, so it will exit when the main process exits
    """
    logging.info(
        "Telegram command thread started (poll interval: %ds)",
        TELEGRAM_COMMAND_POLL_INTERVAL,
    )
    
    handler = get_telegram_command_handler()
    if handler is None:
        logging.info("Telegram command thread exiting: not configured")
        return
    
    while True:
        try:
            commands = handler.poll_commands()
            if commands:
                logging.info(
                    "Telegram commands received: %d command(s)",
                    len(commands),
                )
                # Create command handlers with current state
                command_handlers = create_kill_resume_handlers(
                    state=_core_state.risk_control_state,
                    positions_count_fn=lambda: len(positions),
                    positions_snapshot_fn=lambda: positions,
                    record_event_fn=log_risk_control_event,
                    bot_token=TELEGRAM_BOT_TOKEN,
                    chat_id=TELEGRAM_CHAT_ID,
                    total_equity_fn=calculate_total_equity,
                    balance_fn=lambda: balance,
                    total_margin_fn=calculate_total_margin,
                    start_capital=START_CAPITAL,
                    sortino_ratio_fn=lambda: calculate_sortino_ratio(
                        equity_history,
                        get_effective_check_interval(),
                        RISK_FREE_RATE,
                    ),
                    risk_control_enabled=RISK_CONTROL_ENABLED,
                    daily_loss_limit_enabled=DAILY_LOSS_LIMIT_ENABLED,
                    daily_loss_limit_pct=DAILY_LOSS_LIMIT_PCT,
                    account_snapshot_fn=get_live_account_snapshot,
                    execute_close_fn=execute_telegram_close,
                    update_tpsl_fn=update_telegram_tpsl,
                    get_current_price_fn=get_current_price_for_coin,
                )
                # Process commands with handlers
                process_telegram_commands(commands, command_handlers=command_handlers)
                # Save state after command processing to persist any changes
                save_state()
        except Exception as exc:
            # Catch all exceptions to prevent thread termination
            logging.error(
                "Error in Telegram command thread: %s",
                exc,
            )
        
        time.sleep(TELEGRAM_COMMAND_POLL_INTERVAL)


def fetch_market_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch current market data for a symbol."""
    interval = get_effective_interval()
    return _fetch_market_data(symbol, get_market_data_client, interval)


def load_state() -> None:
    """Load persisted balance, positions, and risk control state.
    
    Uses core.state.load_state() as the unified entry point to ensure
    all state (including risk_control) is loaded consistently.
    """
    global balance, iteration_counter
    _core_load_state()
    # Sync module-level references with core.state
    balance = _core_state.balance
    positions.clear()
    positions.update(_core_state.positions)
    iteration_counter = _core_state.iteration_counter


def load_equity_history() -> None:
    """Load equity history from CSV."""
    equity_history.clear()
    if not STATE_CSV.exists():
        return
    try:
        df = pd.read_csv(STATE_CSV)
        if "total_equity" in df.columns:
            values = pd.to_numeric(df["total_equity"], errors="coerce").dropna().tolist()
            equity_history.extend(values)
    except Exception as e:
        logging.warning("Failed to load equity history: %s", e)


def save_state() -> None:
    """Persist current state including risk control.
    
    Uses core.state.save_state() as the unified entry point to ensure
    all state (including risk_control) is saved consistently.
    """
    # Sync module-level state to core.state before saving
    _core_state.balance = balance
    _core_state.positions.clear()
    _core_state.positions.update(positions)
    _core_state.iteration_counter = iteration_counter
    _core_save_state()


def log_ai_message(direction: str, role: str, content: str, metadata: Optional[Dict] = None) -> None:
    """Log AI messages."""
    _log_ai_message(
        messages_csv=MESSAGES_CSV,
        messages_recent_csv=MESSAGES_RECENT_CSV,
        max_recent_messages=MAX_RECENT_MESSAGES,
        now_iso=get_current_time().isoformat(),
        direction=direction,
        role=role,
        content=content,
        metadata=metadata,
    )


def send_telegram_message(text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = "Markdown") -> None:
    """Send Telegram notification."""
    _send_telegram_message(
        bot_token=TELEGRAM_BOT_TOKEN,
        default_chat_id=TELEGRAM_CHAT_ID,
        text=text,
        chat_id=chat_id,
        parse_mode=parse_mode,
    )


def notify_error(message: str, metadata: Optional[Dict] = None, *, log_error: bool = True) -> None:
    """Log error and notify via Telegram."""
    _notify_error(
        message=message,
        metadata=metadata,
        log_error=log_error,
        log_ai_message_fn=log_ai_message,
        send_telegram_message_fn=send_telegram_message,
    )


def calculate_unrealized_pnl(coin: str, current_price: float) -> float:
    """Calculate unrealized PnL for a position."""
    if coin not in positions:
        return 0.0
    return calculate_unrealized_pnl_for_position(positions[coin], current_price)


def calculate_net_unrealized_pnl(coin: str, current_price: float) -> float:
    """Calculate net unrealized PnL after fees."""
    if coin not in positions:
        return 0.0
    return calculate_net_unrealized_pnl_for_position(positions[coin], current_price)


def estimate_exit_fee(pos: Dict[str, Any], exit_price: float) -> float:
    """Estimate exit fee."""
    return estimate_exit_fee_for_position(pos, exit_price, TAKER_FEE_RATE)


def calculate_total_margin() -> float:
    """Calculate total margin across all positions."""
    return calculate_total_margin_for_positions(positions.values())


def calculate_total_equity() -> float:
    """Calculate total equity."""
    total = balance + calculate_total_margin()
    for coin in positions:
        symbol = resolve_symbol_for_coin(coin)
        if symbol:
            data = fetch_market_data(symbol)
            if data:
                total += calculate_unrealized_pnl(coin, data['price'])
    return total


def register_equity_snapshot(total_equity: float) -> None:
    """Append equity to history if finite."""
    if total_equity is not None and math.isfinite(total_equity):
        equity_history.append(total_equity)


# ═══════════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════════

def _get_executor() -> TradeExecutor:
    """Create trade executor."""
    return TradeExecutor(
        positions=positions,
        get_balance=lambda: balance,
        set_balance=_set_balance,
        get_current_time=get_current_time,
        calculate_unrealized_pnl=calculate_unrealized_pnl,
        estimate_exit_fee=estimate_exit_fee,
        record_iteration_message=record_iteration_message,
        log_trade=log_trade,
        log_ai_decision=log_ai_decision,
        save_state=save_state,
        send_telegram_message=send_telegram_message,
        escape_markdown=escape_markdown,
        fetch_market_data=fetch_market_data,
        hyperliquid_trader=hyperliquid_trader,
        get_binance_futures_exchange=get_binance_futures_exchange,
        trading_backend=TRADING_BACKEND,
        binance_futures_live=BINANCE_FUTURES_LIVE,
        backpack_futures_live=BACKPACK_FUTURES_LIVE,
        is_kill_switch_active=lambda: _core_state.risk_control_state.kill_switch_active,
    )


def execute_entry(coin: str, decision: Dict, current_price: float) -> None:
    _get_executor().execute_entry(coin, decision, current_price)


def execute_close(coin: str, decision: Dict, current_price: float) -> None:
    _get_executor().execute_close(coin, decision, current_price)


def execute_telegram_close(coin: str, side: str, quantity: float) -> Optional[CloseResult]:
    """Execute a position close from Telegram /close command.
    
    This function is specifically designed for the Telegram /close command,
    which allows partial or full position closing via user command.
    
    Unlike execute_close() which is used by the trading loop and requires
    a decision dict, this function directly executes a close with the
    specified quantity.
    
    Args:
        coin: Coin symbol (e.g., "BTC", "ETH").
        side: Position side ("long" or "short").
        quantity: Quantity to close (absolute value).
        
    Returns:
        CloseResult on success (both paper and live modes),
        None if execution failed (no symbol mapping, market data unavailable, etc.).
        
    Note:
        This function is allowed to execute even when Kill-Switch is active,
        as closing positions reduces risk exposure (AC6).
        
        On success, this function updates local positions and balance state
        to keep paper/live state consistent.
    """
    global balance
    
    # Get current price for the coin
    symbol = resolve_symbol_for_coin(coin)
    if not symbol:
        logging.warning(
            "Telegram /close: no symbol mapping for coin %s",
            coin,
        )
        return None
    
    data = fetch_market_data(symbol)
    if not data:
        logging.warning(
            "Telegram /close: failed to fetch market data for %s",
            symbol,
        )
        return None
    
    current_price = data.get("price", 0.0)
    if current_price <= 0:
        logging.warning(
            "Telegram /close: invalid price for %s: %s",
            symbol,
            current_price,
        )
        return None
    
    # Check if live trading is enabled
    is_live = (
        (TRADING_BACKEND == "binance_futures" and BINANCE_FUTURES_LIVE)
        or (TRADING_BACKEND == "backpack_futures" and BACKPACK_FUTURES_LIVE)
        or (TRADING_BACKEND == "hyperliquid" and hyperliquid_trader.is_live)
    )
    
    close_result: Optional[CloseResult] = None
    
    if not is_live:
        # Paper trading mode - simulate close locally
        logging.info(
            "Telegram /close (paper): coin=%s | side=%s | quantity=%s | price=%s",
            coin,
            side,
            quantity,
            current_price,
        )
        close_result = CloseResult(
            success=True,
            backend="paper",
            errors=[],
            close_oid=None,
            raw=None,
            extra={"reason": "paper trading mode"},
        )
    else:
        # Live trading - route to exchange
        logging.info(
            "Telegram /close (live): coin=%s | side=%s | quantity=%s | price=%s | backend=%s",
            coin,
            side,
            quantity,
            current_price,
            TRADING_BACKEND,
        )
        
        close_result = route_live_close(
            coin=coin,
            side=side,
            quantity=quantity,
            current_price=current_price,
            trading_backend=TRADING_BACKEND,
            binance_futures_live=BINANCE_FUTURES_LIVE,
            backpack_futures_live=BACKPACK_FUTURES_LIVE,
            hyperliquid_is_live=hyperliquid_trader.is_live,
            get_binance_futures_exchange=get_binance_futures_exchange,
            backpack_api_public_key=BACKPACK_API_PUBLIC_KEY,
            backpack_api_secret_seed=BACKPACK_API_SECRET_SEED,
            backpack_api_base_url=BACKPACK_API_BASE_URL,
            backpack_api_window_ms=BACKPACK_API_WINDOW_MS,
            hyperliquid_trader=hyperliquid_trader,
            coin_to_symbol=COIN_TO_SYMBOL,
        )
        
        if close_result is None:
            return None
    
    # Update local state on successful close
    if close_result is not None and close_result.success:
        _update_local_state_after_close(coin, quantity, current_price)
    
    return close_result


def update_telegram_tpsl(
    coin: str,
    new_sl: Optional[float],
    new_tp: Optional[float],
) -> "TPSLUpdateResult":
    """Update stop loss and/or take profit for a position via Telegram command.
    
    This function updates the local positions state with new SL/TP values.
    It is designed for the Telegram /sl, /tp, /tpsl commands.
    
    Args:
        coin: Coin symbol (e.g., "BTC", "ETH").
        new_sl: New stop loss price, or None to keep existing.
        new_tp: New take profit price, or None to keep existing.
        
    Returns:
        TPSLUpdateResult with success status and old/new values.
    """
    from notifications.commands.tpsl import TPSLUpdateResult
    
    # Try to sync local positions with live exchange snapshot if coin is missing
    if coin not in positions:
        try:
            snapshot = get_live_account_snapshot()
        except Exception as exc:
            logging.warning(
                "update_telegram_tpsl: failed to get live snapshot for %s: %s",
                coin,
                exc,
            )
            snapshot = None
        
        if isinstance(snapshot, dict):
            raw_positions = snapshot.get("positions")
            if isinstance(raw_positions, list):
                live_positions = parse_live_positions(raw_positions)
                live_pos = live_positions.get(coin)
                if live_pos:
                    positions[coin] = live_pos
                    _core_state.positions[coin] = live_pos
    
    if coin not in positions:
        return TPSLUpdateResult(
            success=False,
            error=f"无 {coin} 持仓",
        )
    
    pos = positions[coin]
    old_sl = float(pos.get("stop_loss", 0) or 0)
    old_tp = float(pos.get("profit_target", 0) or 0)
    
    # Update SL if provided
    if new_sl is not None:
        positions[coin]["stop_loss"] = new_sl
        _core_state.positions[coin]["stop_loss"] = new_sl
    
    # Update TP if provided
    if new_tp is not None:
        positions[coin]["profit_target"] = new_tp
        _core_state.positions[coin]["profit_target"] = new_tp
    
    # Persist state
    save_state()
    
    logging.info(
        "Telegram TP/SL update: coin=%s | old_sl=%.4f | new_sl=%s | "
        "old_tp=%.4f | new_tp=%s",
        coin,
        old_sl,
        new_sl if new_sl is not None else "unchanged",
        old_tp,
        new_tp if new_tp is not None else "unchanged",
    )
    
    return TPSLUpdateResult(
        success=True,
        old_sl=old_sl if old_sl > 0 else None,
        new_sl=new_sl,
        old_tp=old_tp if old_tp > 0 else None,
        new_tp=new_tp,
    )


def get_current_price_for_coin(coin: str) -> Optional[float]:
    """Get current market price for a coin.
    
    This function is used by Telegram /sl, /tp, /tpsl commands to get
    the current price for percentage-based calculations.
    
    Args:
        coin: Coin symbol (e.g., "BTC", "ETH").
        
    Returns:
        Current price if available, None otherwise.
    """
    symbol = resolve_symbol_for_coin(coin)
    if not symbol:
        logging.debug("get_current_price_for_coin: no symbol mapping for %s", coin)
        return None
    
    data = fetch_market_data(symbol)
    if not data:
        logging.debug("get_current_price_for_coin: no market data for %s", symbol)
        return None
    
    price = data.get("price")
    if price is None or price <= 0:
        logging.debug("get_current_price_for_coin: invalid price for %s: %s", symbol, price)
        return None
    
    return float(price)


def _update_local_state_after_close(coin: str, closed_quantity: float, current_price: float) -> None:
    """Update local positions and balance after a successful Telegram /close.
    
    This helper ensures paper and live state remain consistent after
    a manual close via Telegram command.
    
    Args:
        coin: Coin symbol that was closed.
        closed_quantity: Quantity that was closed.
        current_price: Price at which the close was executed.
    """
    global balance
    
    if coin not in positions:
        logging.debug(
            "Telegram /close: coin %s not in local positions, skipping state update",
            coin,
        )
        return
    
    pos = positions[coin]
    total_quantity = abs(float(pos.get("quantity", 0) or 0))
    
    if total_quantity <= 0:
        # Position already empty, just remove it
        del positions[coin]
        save_state()
        return
    
    # Calculate PnL for the closed portion
    entry_price = float(pos.get("entry_price", 0) or 0)
    pos_side = str(pos.get("side", "")).lower()
    
    if pos_side == "long":
        pnl_per_unit = current_price - entry_price
    elif pos_side == "short":
        pnl_per_unit = entry_price - current_price
    else:
        pnl_per_unit = 0.0
    
    closed_pnl = pnl_per_unit * closed_quantity
    
    # Calculate proportional margin and fees to return
    margin = float(pos.get("margin", 0) or 0)
    fees_paid = float(pos.get("fees_paid", 0) or 0)
    fee_rate = float(pos.get("fee_rate", TAKER_FEE_RATE) or TAKER_FEE_RATE)
    
    close_ratio = min(closed_quantity / total_quantity, 1.0)
    margin_returned = margin * close_ratio
    fees_returned = fees_paid * close_ratio
    
    # Estimate exit fee
    exit_fee = closed_quantity * current_price * fee_rate
    
    # Net PnL after fees
    net_pnl = closed_pnl - exit_fee
    
    # Update balance
    balance_delta = margin_returned + net_pnl
    balance += balance_delta
    _core_state.balance = balance
    
    logging.info(
        "Telegram /close state update: coin=%s | closed_qty=%s | pnl=%.2f | "
        "exit_fee=%.2f | net_pnl=%.2f | margin_returned=%.2f | new_balance=%.2f",
        coin,
        closed_quantity,
        closed_pnl,
        exit_fee,
        net_pnl,
        margin_returned,
        balance,
    )
    
    remaining_quantity = total_quantity - closed_quantity
    
    if remaining_quantity <= 0.0001:  # Effectively zero (handle floating point)
        # Full close - remove position
        del positions[coin]
        logging.info("Telegram /close: position %s fully closed and removed", coin)
    else:
        # Partial close - update position
        positions[coin]["quantity"] = remaining_quantity
        positions[coin]["margin"] = margin - margin_returned
        positions[coin]["fees_paid"] = fees_paid - fees_returned
        logging.info(
            "Telegram /close: position %s partially closed, remaining_qty=%s",
            coin,
            remaining_quantity,
        )
    
    # Persist state
    save_state()


def process_ai_decisions(
    decisions: Dict[str, Any],
    *,
    allow_entry: bool = True,
    kill_switch_active: bool = False,
    kill_switch_reason: Optional[str] = None,
) -> None:
    """Process AI decisions for all coins.
    
    Args:
        decisions: Dictionary of AI decisions keyed by coin.
        allow_entry: If False, entry signals are blocked (Kill-Switch active or
            other risk control condition). Close and hold signals are still
            processed normally.
        kill_switch_active: Whether Kill-Switch is currently active (for logging).
        kill_switch_reason: The reason for Kill-Switch activation (for logging).
    """
    executor = _get_executor()
    coin_universe = get_effective_coin_universe()
    
    # Warn about positions outside current Universe (orphaned positions)
    # These will still be managed by SL/TP but won't receive LLM decisions
    orphaned_coins = set(positions.keys()) - set(coin_universe)
    if orphaned_coins:
        logging.warning(
            "Positions exist outside current Universe and will not receive LLM decisions: %s. "
            "These positions are still managed by SL/TP logic.",
            sorted(orphaned_coins),
        )
    
    for coin in coin_universe:
        if coin not in decisions:
            continue
        decision = decisions[coin]
        signal = decision.get("signal", "hold")
        log_ai_decision(coin, signal, decision.get("justification", ""), decision.get("confidence", 0))
        
        symbol = resolve_symbol_for_coin(coin)
        if not symbol:
            continue
        data = fetch_market_data(symbol)
        if not data:
            continue
        
        price = data["price"]
        if signal == "entry":
            if allow_entry:
                execute_entry(coin, decision, price)
            else:
                # Risk control blocking entry - determine reason for logging
                if kill_switch_active:
                    block_reason = f"Kill-Switch active ({kill_switch_reason or 'unknown'})"
                else:
                    block_reason = "Risk control (allow_entry=False)"
                
                # AC3: Structured log with required fields
                logging.warning(
                    "Risk control: entry blocked | coin=%s | signal=%s | allow_entry=%s | "
                    "kill_switch_active=%s | reason=%s | price=%.4f | confidence=%d",
                    coin,
                    signal,
                    allow_entry,
                    kill_switch_active,
                    block_reason,
                    price,
                    decision.get("confidence", 0),
                )
                
                # AC4: Record blocked entry to ai_decisions.csv for audit trail
                # Using signal="blocked" with reason in justification field
                blocked_justification = (
                    f"RISK_CONTROL_BLOCKED: {block_reason} | "
                    f"Original: {decision.get('justification', 'N/A')}"
                )
                log_ai_decision(
                    coin,
                    "blocked",
                    blocked_justification,
                    decision.get("confidence", 0),
                )
        elif signal == "close":
            execute_close(coin, decision, price)
        elif signal == "hold":
            executor.process_hold_signal(coin, decision, price)


def check_stop_loss_take_profit() -> None:
    """Check SL/TP for all positions."""
    check_stop_loss_take_profit_for_positions(
        positions, SYMBOL_TO_COIN, fetch_market_data,
        execute_close, hyperliquid_trader.is_live,
    )


# ═══════════════════════════════════════════════════════════════════
# LLM API
# ═══════════════════════════════════════════════════════════════════

def call_deepseek_api(prompt: str) -> Optional[Dict[str, Any]]:
    """Call LLM API."""
    if not LLM_API_KEY:
        logging.error("No LLM API key configured.")
        return None
    
    try:
        temperature = get_effective_llm_temperature()
        metadata = {
            "model": LLM_MODEL_NAME,
            "temperature": temperature,
            "max_tokens": LLM_MAX_TOKENS,
        }
        log_ai_message("sent", "system", TRADING_RULES_PROMPT, metadata)
        log_ai_message("sent", "user", prompt, metadata)
        
        payload = {
            "model": LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": TRADING_RULES_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": LLM_MAX_TOKENS,
        }
        if LLM_THINKING_PARAM is not None:
            payload["thinking"] = LLM_THINKING_PARAM
        
        headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
        if (LLM_API_TYPE or "openrouter").lower() == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/crypto-trading-bot"
        
        response = requests.post(LLM_API_BASE_URL, headers=headers, json=payload, timeout=90)
        
        if response.status_code != 200:
            notify_error(f"LLM API error: {response.status_code}")
            return None
        
        result = response.json()
        choices = result.get("choices", [])
        if not choices:
            notify_error("LLM API returned no choices")
            return None
        
        content = choices[0].get("message", {}).get("content", "")
        finish_reason = choices[0].get("finish_reason")
        log_ai_message("received", "assistant", content, {"finish_reason": finish_reason})
        
        return parse_llm_json_decisions(
            content, response_id=result.get("id"), status_code=response.status_code,
            finish_reason=finish_reason, notify_error=notify_error,
            log_llm_decisions=_log_llm_decisions, recover_partial_decisions=_recover_partial_decisions,
        )
    except Exception as e:
        logging.exception("Error calling LLM API")
        notify_error(f"LLM API error: {e}", log_error=False)
        return None


def format_prompt_for_deepseek() -> str:
    """Build LLM prompt."""
    return _format_prompt(
        get_market_data_client=get_market_data_client,
        get_positions=lambda: positions,
        get_balance=lambda: balance,
        get_current_time=get_current_time,
        get_bot_start_time=get_bot_start_time,
        increment_invocation_count=increment_invocation_count,
        calculate_total_margin=lambda: calculate_total_margin_for_positions(positions.values()),
        calculate_unrealized_pnl=calculate_unrealized_pnl,
        interval=get_effective_interval(),
    )


# ═══════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    """Main trading loop."""
    logging.info("Initializing Trading Bot...")
    init_csv_files_for_paths(STATE_CSV, TRADES_CSV, DECISIONS_CSV, MESSAGES_CSV, MESSAGES_RECENT_CSV, STATE_COLUMNS)
    
    # Load equity history
    if STATE_CSV.exists():
        try:
            df = pd.read_csv(STATE_CSV)
            if "total_equity" in df.columns:
                equity_history.extend(pd.to_numeric(df["total_equity"], errors="coerce").dropna().tolist())
        except Exception:
            pass
    
    load_state()
    
    if not LLM_API_KEY:
        logging.error("No LLM API key configured; expected LLM_API_KEY or OPENROUTER_API_KEY in environment.")
        return
    
    logging.info(f"Starting capital: ${START_CAPITAL:.2f}")
    monitoring_coins = get_effective_coin_universe()
    logging.info(f"Monitoring: {', '.join(monitoring_coins)}")
    
    # Log trading backend status
    if hyperliquid_trader.is_live:
        logging.warning(
            "Hyperliquid LIVE trading enabled. Orders will be sent to mainnet using wallet %s.",
            hyperliquid_trader.masked_wallet,
        )
    else:
        logging.info("Hyperliquid live trading disabled; running in paper mode only.")
    
    if TRADING_BACKEND == "binance_futures":
        if BINANCE_FUTURES_LIVE:
            logging.warning(
                "Binance futures LIVE trading enabled; orders will be sent to Binance USDT-margined futures.",
            )
        else:
            logging.warning(
                "TRADING_BACKEND=binance_futures but BINANCE_FUTURES_LIVE is not true; running in paper mode only.",
            )
    
    if TRADING_BACKEND == "backpack_futures":
        if BACKPACK_FUTURES_LIVE:
            logging.warning(
                "Backpack futures LIVE trading enabled; orders will be sent to Backpack USDC perpetual futures.",
            )
        else:
            logging.warning(
                "TRADING_BACKEND=backpack_futures but BACKPACK_FUTURES_LIVE is not true; running in paper mode only.",
            )
    
    # Log Telegram status
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        logging.info("Telegram notifications enabled (chat: %s).", TELEGRAM_CHAT_ID)
        register_telegram_commands(TELEGRAM_BOT_TOKEN)
    else:
        logging.info("Telegram notifications disabled; missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
    
    log_system_prompt_info("System prompt selected")
    logging.info("LLM model configured: %s", LLM_MODEL_NAME)
    logging.info("Market data backend: %s", MARKET_DATA_BACKEND)
    
    # Log risk control configuration and state
    logging.info(
        "Risk control config: enabled=%s, daily_loss_limit_enabled=%s, daily_loss_limit_pct=%.1f%%",
        RISK_CONTROL_ENABLED,
        DAILY_LOSS_LIMIT_ENABLED,
        DAILY_LOSS_LIMIT_PCT,
    )
    logging.info(
        "Risk control state loaded: kill_switch_active=%s, daily_loss_pct=%.2f%%",
        _core_state.risk_control_state.kill_switch_active,
        _core_state.risk_control_state.daily_loss_pct,
    )
    
    # Start dedicated Telegram command polling thread
    # This thread polls for commands every TELEGRAM_COMMAND_POLL_INTERVAL seconds,
    # independent of the main trading loop's CHECK_INTERVAL.
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        telegram_thread = threading.Thread(
            target=_telegram_command_loop,
            name="TelegramCommandThread",
            daemon=True,  # Thread will exit when main process exits
        )
        telegram_thread.start()
        logging.info("Telegram command thread started (poll interval: %ds)", TELEGRAM_COMMAND_POLL_INTERVAL)
    
    while True:
        try:
            _run_iteration()
        except KeyboardInterrupt:
            print("\n\nShutting down...")
            save_state()
            break
        except Exception as e:
            logging.error(f"Error: {e}", exc_info=True)
            save_state()
            time.sleep(60)


def _run_iteration() -> None:
    """Run single iteration."""
    global iteration_counter
    iteration = increment_iteration_counter()
    # Keep bot.iteration_counter in sync with core.state.iteration_counter
    iteration_counter = iteration
    clear_iteration_messages()
    
    # Global loop switch: when disabled, skip trading logic and just sleep.
    if not get_effective_tradebot_loop_enabled():
        check_interval = get_effective_check_interval()
        logging.info(
            "TRADEBOT_LOOP_ENABLED is false; bot loop paused. Sleeping %ss before next check.",
            check_interval,
        )
        sleep_with_countdown(check_interval)
        return
    
    # Capture current check interval for early retry logic (e.g., Binance client unavailable)
    initial_check_interval = get_effective_check_interval()
    
    # Only require Binance client when using Binance as market data backend.
    # For Backpack 或其他后端，不强制依赖 Binance。
    if MARKET_DATA_BACKEND == "binance":
        if not get_binance_client():
            logging.warning("Binance client unavailable; retrying...")
            time.sleep(min(initial_check_interval, 60))
            return
    
    # Header
    print(f"\n{Fore.CYAN}{'='*20}")
    print(f"{Fore.CYAN}Iteration {iteration} - {get_current_time().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Fore.CYAN}{'='*20}\n")
    
    # Note: Telegram command polling is now handled by a dedicated background thread
    # (_telegram_command_loop) which polls every TELEGRAM_COMMAND_POLL_INTERVAL seconds.
    # This allows commands to be processed within seconds, independent of CHECK_INTERVAL.
    
    # Risk control check (before market data and LLM calls)
    # Returns False if Kill-Switch is active (entry trades should be blocked)
    total_equity = calculate_total_equity()

    if RISK_CONTROL_ENABLED:
        update_daily_baseline(
            _core_state.risk_control_state,
            current_equity=total_equity,
        )

    # Create notification callback for daily loss limit (if Telegram configured)
    daily_loss_notify_fn = create_daily_loss_limit_notify_callback(
        bot_token=TELEGRAM_BOT_TOKEN,
        chat_id=TELEGRAM_CHAT_ID,
    )

    allow_entry = check_risk_limits(
        risk_control_state=_core_state.risk_control_state,
        total_equity=total_equity,
        iteration_time=get_current_time(),
        risk_control_enabled=RISK_CONTROL_ENABLED,
        daily_loss_limit_enabled=DAILY_LOSS_LIMIT_ENABLED,
        daily_loss_limit_pct=DAILY_LOSS_LIMIT_PCT,
        positions_count=len(positions),
        notify_daily_loss_fn=daily_loss_notify_fn,
        record_event_fn=log_risk_control_event,
    )
    
    # SL/TP checks always run, even when Kill-Switch is active (AC3)
    check_stop_loss_take_profit()
    
    # Get AI decisions
    logging.info("Requesting trading decisions...")
    decisions = call_deepseek_api(format_prompt_for_deepseek())
    if decisions:
        process_ai_decisions(
            decisions,
            allow_entry=allow_entry,
            kill_switch_active=_core_state.risk_control_state.kill_switch_active,
            kill_switch_reason=_core_state.risk_control_state.kill_switch_reason,
        )
    
    # Display summary (terminal only, no Telegram push)
    # Users can query status via /status command instead
    _display_portfolio_summary(
        positions, balance, equity_history, calculate_total_equity,
        lambda: calculate_total_margin_for_positions(positions.values()),
        lambda eq: equity_history.append(eq) if eq and math.isfinite(eq) else None,
        lambda msg: None,  # Don't record for Telegram push
    )
    
    # Log and save
    _log_portfolio_state(
        positions,
        balance,
        calculate_total_equity,
        lambda: calculate_total_margin_for_positions(positions.values()),
        lambda: fetch_market_data("BTCUSDT").get("price") if fetch_market_data("BTCUSDT") else None,
        get_current_time,
    )
    save_state()
    
    # Re-read effective check interval at the end of the iteration so that
    # any /config set TRADEBOT_INTERVAL changes applied during this iteration
    # are reflected immediately in the next sleep duration.
    check_interval = get_effective_check_interval()
    logging.info(f"Waiting {check_interval}s...")
    sleep_with_countdown(check_interval)


if __name__ == "__main__":
    main()
