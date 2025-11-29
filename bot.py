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

import time
import logging
import math
from typing import Any, Dict, List, Optional

import pandas as pd
from colorama import Fore
import requests

# ───────────────────────── CONFIGURATION ─────────────────────────
import trading_config as _trading_config
from trading_config import (
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
    refresh_llm_configuration_from_env as _refresh_llm_config,
    DEFAULT_TRADING_RULES_PROMPT,
)
from trading_config import (
    TRADING_BACKEND, BINANCE_FUTURES_LIVE, BACKPACK_FUTURES_LIVE,
)
from bot_config import DEFAULT_LLM_MODEL


def refresh_llm_configuration_from_env() -> None:
    """Reload LLM settings from environment."""
    global LLM_API_KEY, LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_MAX_TOKENS
    global LLM_THINKING_PARAM, LLM_API_BASE_URL, LLM_API_TYPE
    global TRADING_RULES_PROMPT, OPENROUTER_API_KEY
    # Sync module-level OPENROUTER_API_KEY to trading_config before refresh
    _trading_config.OPENROUTER_API_KEY = OPENROUTER_API_KEY
    _refresh_llm_config()
    LLM_API_KEY = _trading_config.LLM_API_KEY
    LLM_MODEL_NAME = _trading_config.LLM_MODEL_NAME
    LLM_TEMPERATURE = _trading_config.LLM_TEMPERATURE
    LLM_MAX_TOKENS = _trading_config.LLM_MAX_TOKENS
    LLM_THINKING_PARAM = _trading_config.LLM_THINKING_PARAM
    LLM_API_BASE_URL = _trading_config.LLM_API_BASE_URL
    LLM_API_TYPE = _trading_config.LLM_API_TYPE
    TRADING_RULES_PROMPT = _trading_config.TRADING_RULES_PROMPT
    OPENROUTER_API_KEY = _trading_config.OPENROUTER_API_KEY

# ───────────────────────── STATE MANAGEMENT ─────────────────────────
import trading_state
from trading_state import (
    get_balance, get_positions, get_current_time, get_bot_start_time,
    get_iteration_messages, get_equity_history, get_iteration_counter,
    increment_iteration_counter, clear_iteration_messages, reset_state,
    set_last_btc_price, get_last_btc_price, escape_markdown,
    increment_invocation_count,
)

# Module-level state references (for test compatibility)
positions = trading_state.positions
balance = trading_state.balance
equity_history = trading_state.equity_history
iteration_counter = trading_state.iteration_counter

# ───────────────────────── EXCHANGE CLIENTS ─────────────────────────
from exchange.factory import (
    get_binance_client, get_binance_futures_exchange, get_hyperliquid_trader,
)
from market_data import BinanceMarketDataClient, BackpackMarketDataClient

hyperliquid_trader = get_hyperliquid_trader()
_market_data_client = None

# ───────────────────────── STATE I/O ─────────────────────────
from state_io import (
    load_state_from_json, save_state_to_json, init_csv_files_for_paths,
)

# ───────────────────────── NOTIFICATIONS ─────────────────────────
from notifications import (
    log_ai_message as _log_ai_message,
    send_telegram_message as _send_telegram_message,
    notify_error as _notify_error,
)

# ───────────────────────── METRICS ─────────────────────────
from metrics import (
    calculate_unrealized_pnl_for_position,
    calculate_net_unrealized_pnl_for_position,
    estimate_exit_fee_for_position,
    calculate_total_margin_for_positions,
)

# ───────────────────────── INDICATORS (for test compatibility) ─────────────────────────
from trading_loop import (
    calculate_rsi_series, add_indicator_columns, calculate_atr_series,
    calculate_indicators, round_series, calculate_pnl_for_price,
    format_leverage_display, calculate_sortino_ratio,
)

# ───────────────────────── PROMPT & LLM ─────────────────────────
from prompt_builder import (
    fetch_market_data as _fetch_market_data,
    format_prompt_for_deepseek as _format_prompt,
)
from llm_client import _recover_partial_decisions, _log_llm_decisions
from llm.parser import parse_llm_json_decisions

# ───────────────────────── EXECUTION ─────────────────────────
from execution.executor import TradeExecutor
from execution.routing import check_stop_loss_take_profit_for_positions

# ───────────────────────── DISPLAY ─────────────────────────
from portfolio_display import (
    log_portfolio_state as _log_portfolio_state,
    display_portfolio_summary as _display_portfolio_summary,
)
from trading_loop import (
    log_trade, log_ai_decision, record_iteration_message, sleep_with_countdown,
)


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def _set_balance(new_balance: float) -> None:
    """Set the balance."""
    global balance
    balance = new_balance
    trading_state.balance = new_balance


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


def fetch_market_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch current market data for a symbol."""
    return _fetch_market_data(symbol, get_market_data_client, INTERVAL)


def load_state() -> None:
    """Load persisted balance and positions."""
    global balance, iteration_counter
    if not STATE_JSON.exists():
        return
    try:
        new_balance, new_positions, new_iteration = load_state_from_json(
            STATE_JSON, START_CAPITAL, TAKER_FEE_RATE,
        )
        balance = new_balance
        positions.clear()
        positions.update(new_positions)
        iteration_counter = new_iteration
        trading_state.balance = balance
        trading_state.iteration_counter = new_iteration
    except Exception as e:
        logging.error("Failed to load state: %s", e)


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
    """Persist current state."""
    # Sync module-level iteration_counter to trading_state before saving
    trading_state.iteration_counter = iteration_counter
    save_state_to_json(STATE_JSON, {
        "balance": balance,
        "positions": positions,
        "iteration": iteration_counter,
        "updated_at": get_current_time().isoformat(),
    })


def log_ai_message(direction: str, role: str, content: str, metadata: Optional[Dict] = None) -> None:
    """Log AI messages."""
    _log_ai_message(
        MESSAGES_CSV, MESSAGES_RECENT_CSV, MAX_RECENT_MESSAGES,
        get_current_time().isoformat(), direction, role, content, metadata,
    )


def send_telegram_message(text: str, chat_id: Optional[str] = None, parse_mode: Optional[str] = "Markdown") -> None:
    """Send Telegram notification."""
    _send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, text, chat_id, parse_mode)


def notify_error(message: str, metadata: Optional[Dict] = None, *, log_error: bool = True) -> None:
    """Log error and notify via Telegram."""
    _notify_error(message, metadata, log_error, log_ai_message, send_telegram_message)


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
        symbol = next((s for s, c in SYMBOL_TO_COIN.items() if c == coin), None)
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
    )


def execute_entry(coin: str, decision: Dict, current_price: float) -> None:
    _get_executor().execute_entry(coin, decision, current_price)


def execute_close(coin: str, decision: Dict, current_price: float) -> None:
    _get_executor().execute_close(coin, decision, current_price)


def process_ai_decisions(decisions: Dict[str, Any]) -> None:
    """Process AI decisions for all coins."""
    executor = _get_executor()
    for coin in SYMBOL_TO_COIN.values():
        if coin not in decisions:
            continue
        decision = decisions[coin]
        signal = decision.get("signal", "hold")
        log_ai_decision(coin, signal, decision.get("justification", ""), decision.get("confidence", 0))
        
        symbol = COIN_TO_SYMBOL.get(coin)
        if not symbol:
            continue
        data = fetch_market_data(symbol)
        if not data:
            continue
        
        price = data["price"]
        if signal == "entry":
            executor.execute_entry(coin, decision, price)
        elif signal == "close":
            executor.execute_close(coin, decision, price)
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
        log_ai_message("sent", "system", TRADING_RULES_PROMPT, {"model": LLM_MODEL_NAME})
        log_ai_message("sent", "user", prompt)
        
        payload = {
            "model": LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": TRADING_RULES_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": LLM_TEMPERATURE,
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
        interval=INTERVAL,
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
        logging.error("No LLM API key configured.")
        return
    
    logging.info(f"Starting capital: ${START_CAPITAL:.2f}")
    logging.info(f"Monitoring: {', '.join(SYMBOL_TO_COIN.values())}")
    log_system_prompt_info("System prompt selected")
    
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
    iteration = increment_iteration_counter()
    clear_iteration_messages()
    
    if not get_binance_client():
        logging.warning("Binance client unavailable; retrying...")
        time.sleep(min(CHECK_INTERVAL, 60))
        return
    
    # Header
    print(f"\n{Fore.CYAN}{'='*20}")
    print(f"{Fore.CYAN}Iteration {iteration} - {get_current_time().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Fore.CYAN}{'='*20}\n")
    
    check_stop_loss_take_profit()
    
    # Get AI decisions
    logging.info("Requesting trading decisions...")
    decisions = call_deepseek_api(format_prompt_for_deepseek())
    if decisions:
        process_ai_decisions(decisions)
    
    # Display summary
    _display_portfolio_summary(
        positions, balance, equity_history, calculate_total_equity,
        lambda: calculate_total_margin_for_positions(positions.values()),
        lambda eq: equity_history.append(eq) if eq and math.isfinite(eq) else None,
        record_iteration_message,
    )
    
    # Send to Telegram
    messages = get_iteration_messages()
    if messages:
        send_telegram_message("\n".join(messages), parse_mode=None)
    
    # Log and save
    _log_portfolio_state(
        positions, balance, calculate_total_equity,
        lambda: calculate_total_margin_for_positions(positions.values()),
        lambda: fetch_market_data("BTCUSDT").get("price") if fetch_market_data("BTCUSDT") else None,
        get_current_time,
    )
    save_state()
    
    logging.info(f"Waiting {CHECK_INTERVAL}s...")
    sleep_with_countdown(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
