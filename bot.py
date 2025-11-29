#!/usr/bin/env python3
"""
DeepSeek Multi-Asset Paper Trading Bot

This is the main entry point for the trading bot. The bot uses LLM for trading decisions
and supports multiple exchanges (Binance, Hyperliquid, Backpack).

Architecture:
- trading_config.py: Configuration and constants
- trading_state.py: Global state management
- exchange_clients.py: Exchange client initialization
- prompt_builder.py: LLM prompt construction
- trade_execution.py: Trade execution logic
- portfolio_display.py: Portfolio display and logging
- llm_client.py: LLM API interactions
- strategy_core.py: Market analysis and prompt building
- execution_routing.py: Order execution routing
- market_data.py: Market data fetching
- notifications.py: Telegram and console notifications
- metrics.py: Performance calculations
- state_io.py: State persistence
"""
from __future__ import annotations

import time
import logging
import math
from typing import Any, Dict, List, Optional

import pandas as pd
from colorama import Fore, Style, init as colorama_init

import requests  # For backward compatibility with tests that patch bot.requests

# ───────────────────────── CONFIGURATION ─────────────────────────
import trading_config as _trading_config
from trading_config import (
    dotenv_loaded,
    DOTENV_PATH,
    LLM_API_KEY,
    LLM_MODEL_NAME,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_THINKING_PARAM,
    LLM_API_BASE_URL,
    LLM_API_TYPE,
    TRADING_RULES_PROMPT,
    SYSTEM_PROMPT_SOURCE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    START_CAPITAL,
    CHECK_INTERVAL,
    INTERVAL,
    SYMBOLS,
    SYMBOL_TO_COIN,
    COIN_TO_SYMBOL,
    TRADING_BACKEND as _TRADING_BACKEND,
    BINANCE_FUTURES_LIVE as _BINANCE_FUTURES_LIVE,
    BACKPACK_FUTURES_LIVE,
    HYPERLIQUID_LIVE_TRADING,
    HYPERLIQUID_WALLET_ADDRESS,
    HYPERLIQUID_PRIVATE_KEY,
    API_KEY,
    API_SECRET,
    OPENROUTER_API_KEY,
    BACKPACK_API_BASE_URL,
    MARKET_DATA_BACKEND,
    EMA_LEN,
    RSI_LEN,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    TAKER_FEE_RATE,
    MAKER_FEE_RATE,
    STATE_CSV,
    STATE_JSON,
    TRADES_CSV,
    DECISIONS_CSV,
    MESSAGES_CSV,
    MESSAGES_RECENT_CSV,
    MAX_RECENT_MESSAGES,
    STATE_COLUMNS,
    log_system_prompt_info,
    refresh_llm_configuration_from_env as _refresh_llm_configuration_from_env,
    _INTERVAL_TO_SECONDS,
    describe_system_prompt_source,
    DEFAULT_TRADING_RULES_PROMPT,
)
from bot_config import emit_early_env_warnings, DEFAULT_LLM_MODEL

# Mutable config variables that tests may modify
TRADING_BACKEND = _TRADING_BACKEND
BINANCE_FUTURES_LIVE = _BINANCE_FUTURES_LIVE


def refresh_llm_configuration_from_env() -> None:
    """Reload LLM-related runtime settings from environment variables."""
    global LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_THINKING_PARAM
    global TRADING_RULES_PROMPT, LLM_API_BASE_URL, LLM_API_KEY, LLM_API_TYPE, OPENROUTER_API_KEY
    import trading_config
    trading_config.OPENROUTER_API_KEY = OPENROUTER_API_KEY
    _refresh_llm_configuration_from_env()
    LLM_MODEL_NAME = trading_config.LLM_MODEL_NAME
    LLM_TEMPERATURE = trading_config.LLM_TEMPERATURE
    LLM_MAX_TOKENS = trading_config.LLM_MAX_TOKENS
    LLM_THINKING_PARAM = trading_config.LLM_THINKING_PARAM
    TRADING_RULES_PROMPT = trading_config.TRADING_RULES_PROMPT
    LLM_API_BASE_URL = trading_config.LLM_API_BASE_URL
    LLM_API_KEY = trading_config.LLM_API_KEY
    LLM_API_TYPE = trading_config.LLM_API_TYPE
    OPENROUTER_API_KEY = trading_config.OPENROUTER_API_KEY


# ───────────────────────── STATE MANAGEMENT ─────────────────────────
import trading_state as _trading_state
from trading_state import (
    get_balance,
    get_positions,
    get_current_time,
    get_bot_start_time,
    get_iteration_messages,
    get_equity_history,
    get_iteration_counter,
    increment_iteration_counter as _increment_iteration_counter,
    clear_iteration_messages,
    reset_state,
    set_time_provider,
    set_last_btc_price,
    get_last_btc_price,
    strip_ansi_codes,
    escape_markdown,
    increment_invocation_count,
    get_invocation_count,
)

# Module-level state for backward compatibility with tests
positions: Dict[str, Dict[str, Any]] = _trading_state.positions
balance: float = _trading_state.balance
equity_history: List[float] = _trading_state.equity_history
iteration_counter: int = _trading_state.iteration_counter
invocation_count: int = _trading_state.invocation_count


def load_state() -> None:
    """Load persisted balance and positions if available."""
    global balance, iteration_counter
    from state_io import load_state_from_json as _load_state_from_json

    if not STATE_JSON.exists():
        logging.info("No existing state file found; starting fresh.")
        return

    try:
        new_balance, new_positions, new_iteration = _load_state_from_json(
            STATE_JSON, START_CAPITAL, TAKER_FEE_RATE,
        )
        balance = new_balance
        positions.clear()
        positions.update(new_positions)
        iteration_counter = new_iteration
        _trading_state.balance = balance
        _trading_state.iteration_counter = iteration_counter
        logging.info("Loaded state from %s (balance: %.2f, positions: %d)",
                     STATE_JSON, balance, len(positions))
    except Exception as e:
        logging.error("Failed to load state from %s: %s", STATE_JSON, e, exc_info=True)
        balance = START_CAPITAL
        _trading_state.balance = balance
        positions.clear()


def save_state() -> None:
    """Persist current balance, open positions, and iteration counter."""
    from state_io import save_state_to_json as _save_state_to_json
    payload = {
        "balance": balance,
        "positions": positions,
        "iteration": iteration_counter,
        "updated_at": get_current_time().isoformat(),
    }
    _save_state_to_json(STATE_JSON, payload)


def load_equity_history() -> None:
    """Populate the in-memory equity history for performance calculations."""
    equity_history.clear()
    if not STATE_CSV.exists():
        return
    try:
        df = pd.read_csv(STATE_CSV)
        if "total_equity" in df.columns:
            values = pd.to_numeric(df["total_equity"], errors="coerce").dropna().tolist()
            equity_history.extend(values)
    except Exception as e:
        logging.warning("Failed to load equity history from %s: %s", STATE_CSV, e)


def register_equity_snapshot(total_equity: float) -> None:
    """Append the latest equity to the history if it is a finite value."""
    if total_equity is None or not math.isfinite(total_equity):
        return
    equity_history.append(total_equity)


def increment_iteration_counter() -> int:
    """Increment and return the iteration counter."""
    global iteration_counter
    result = _increment_iteration_counter()
    iteration_counter = _trading_state.iteration_counter
    return result


def _set_balance(new_balance: float) -> None:
    """Set the balance (for internal use)."""
    global balance
    balance = new_balance
    _trading_state.balance = new_balance


# ───────────────────────── EXCHANGE CLIENTS ─────────────────────────
from exchange_clients import (
    get_binance_client,
    get_binance_futures_exchange,
    get_hyperliquid_trader,
)
from market_data import BinanceMarketDataClient, BackpackMarketDataClient

# Initialize hyperliquid trader
hyperliquid_trader = get_hyperliquid_trader()

# For backward compatibility
_market_data_client = None
client = None
binance_futures_exchange = None
MARKET_DATA_BACKEND = _trading_config.MARKET_DATA_BACKEND


def get_market_data_client() -> Optional[Any]:
    """Get or initialize market data client."""
    global _market_data_client
    if _market_data_client is not None:
        return _market_data_client

    backend = MARKET_DATA_BACKEND
    logging.info("Initializing market data backend: %s", backend)

    if backend == "binance":
        binance_client = get_binance_client()
        if not binance_client:
            return None
        _market_data_client = BinanceMarketDataClient(binance_client)
        return _market_data_client

    if backend == "backpack":
        _market_data_client = BackpackMarketDataClient(BACKPACK_API_BASE_URL)
        return _market_data_client

    return None


# ───────────────────────── MARKET DATA ─────────────────────────
from prompt_builder import (
    fetch_market_data as _fetch_market_data,
    collect_prompt_market_data as _collect_prompt_market_data,
)
from trading_loop import (
    calculate_rsi_series,
    add_indicator_columns,
    calculate_atr_series,
    calculate_indicators,
    round_series,
    calculate_pnl_for_price,
    format_leverage_display,
    calculate_sortino_ratio,
    log_trade,
    log_ai_decision,
    record_iteration_message,
    sleep_with_countdown,
)


def fetch_market_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch current market data for a symbol."""
    return _fetch_market_data(symbol, get_market_data_client, INTERVAL)


def collect_prompt_market_data(symbol: str) -> Optional[Dict[str, Any]]:
    """Return rich market snapshot for prompt composition."""
    return _collect_prompt_market_data(symbol, get_market_data_client, INTERVAL)


def get_btc_benchmark_price() -> Optional[float]:
    """Fetch the current BTC/USDT price for benchmarking."""
    data = fetch_market_data("BTCUSDT")
    if data and "price" in data:
        try:
            set_last_btc_price(float(data["price"]))
        except (TypeError, ValueError):
            logging.debug("Received non-numeric BTC price: %s", data["price"])
    return get_last_btc_price()


# ───────────────────────── CSV INIT ─────────────────────────
from state_io import init_csv_files_for_paths as _init_csv_files_for_paths


def init_csv_files() -> None:
    """Initialize CSV files with headers."""
    _init_csv_files_for_paths(
        STATE_CSV, TRADES_CSV, DECISIONS_CSV,
        MESSAGES_CSV, MESSAGES_RECENT_CSV, STATE_COLUMNS,
    )


# ───────────────────────── NOTIFICATIONS ─────────────────────────
from notifications import (
    log_ai_message as _notifications_log_ai_message,
    send_telegram_message as _notifications_send_telegram_message,
    notify_error as _notifications_notify_error,
)


def log_ai_message(direction: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Log raw messages exchanged with the AI provider."""
    _notifications_log_ai_message(
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
    """Send a notification message to Telegram if credentials are configured."""
    _notifications_send_telegram_message(
        bot_token=TELEGRAM_BOT_TOKEN,
        default_chat_id=TELEGRAM_CHAT_ID,
        text=text,
        chat_id=chat_id,
        parse_mode=parse_mode,
    )


def notify_error(message: str, metadata: Optional[Dict[str, Any]] = None, *, log_error: bool = True) -> None:
    """Log an error and forward a brief description to Telegram."""
    _notifications_notify_error(
        message=message,
        metadata=metadata,
        log_error=log_error,
        log_ai_message_fn=log_ai_message,
        send_telegram_message_fn=send_telegram_message,
    )


# ───────────────────────── METRICS ─────────────────────────
from metrics import (
    calculate_unrealized_pnl_for_position as _metrics_unrealized_pnl_for_pos,
    calculate_net_unrealized_pnl_for_position as _metrics_net_unrealized_pnl_for_pos,
    estimate_exit_fee_for_position as _metrics_estimate_exit_fee_for_pos,
    calculate_total_margin_for_positions as _metrics_total_margin_for_positions,
)


def calculate_unrealized_pnl(coin: str, current_price: float) -> float:
    """Calculate unrealized PnL for a position."""
    if coin not in positions:
        return 0.0
    return _metrics_unrealized_pnl_for_pos(positions[coin], current_price)


def calculate_net_unrealized_pnl(coin: str, current_price: float) -> float:
    """Calculate net unrealized PnL after fees."""
    pos = positions.get(coin)
    if not pos:
        return 0.0
    return _metrics_net_unrealized_pnl_for_pos(pos, current_price)


def estimate_exit_fee(pos: Dict[str, Any], exit_price: float) -> float:
    """Estimate exit fee for a position."""
    return _metrics_estimate_exit_fee_for_pos(pos, exit_price, TAKER_FEE_RATE)


def calculate_total_margin() -> float:
    """Return sum of margin allocated across all open positions."""
    return _metrics_total_margin_for_positions(positions.values())


def calculate_total_equity() -> float:
    """Calculate total equity (balance + unrealized PnL)."""
    total = balance + calculate_total_margin()
    for coin in positions:
        symbol = next((s for s, c in SYMBOL_TO_COIN.items() if c == coin), None)
        if not symbol:
            continue
        data = fetch_market_data(symbol)
        if data:
            total += calculate_unrealized_pnl(coin, data['price'])
    return total


# ───────────────────────── LLM CLIENT ─────────────────────────
from llm_client import _recover_partial_decisions, _log_llm_decisions
from strategy_core import parse_llm_json_decisions as _strategy_parse_llm_json_decisions


def call_deepseek_api(prompt: str) -> Optional[Dict[str, Any]]:
    """Call OpenRouter API with DeepSeek Chat V3.1."""
    api_key = LLM_API_KEY
    if not api_key:
        logging.error("No LLM API key configured.")
        return None
    try:
        request_metadata = {"model": LLM_MODEL_NAME, "temperature": LLM_TEMPERATURE, "max_tokens": LLM_MAX_TOKENS}
        if LLM_THINKING_PARAM is not None:
            request_metadata["thinking"] = LLM_THINKING_PARAM

        log_ai_message("sent", "system", TRADING_RULES_PROMPT, request_metadata)
        log_ai_message("sent", "user", prompt, request_metadata)

        request_payload = {
            "model": LLM_MODEL_NAME,
            "messages": [{"role": "system", "content": TRADING_RULES_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
        }
        if LLM_THINKING_PARAM is not None:
            request_payload["thinking"] = LLM_THINKING_PARAM

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        api_type = (LLM_API_TYPE or "openrouter").lower()
        if api_type == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/crypto-trading-bot"
            headers["X-Title"] = "DeepSeek Trading Bot"

        response = requests.post(url=LLM_API_BASE_URL, headers=headers, json=request_payload, timeout=90)

        if response.status_code != 200:
            notify_error(f"LLM API error: {response.status_code}",
                         metadata={"status_code": response.status_code, "response_text": response.text})
            return None

        result = response.json()
        choices = result.get("choices")
        if not choices:
            notify_error("LLM API returned no choices",
                         metadata={"status_code": response.status_code, "response_text": response.text[:500]})
            return None

        primary_choice = choices[0]
        message = primary_choice.get("message") or {}
        content = message.get("content", "") or ""
        finish_reason = primary_choice.get("finish_reason")

        log_ai_message("received", "assistant", content, {
            "status_code": response.status_code, "response_id": result.get("id"),
            "usage": result.get("usage"), "finish_reason": finish_reason,
        })

        return _strategy_parse_llm_json_decisions(
            content, response_id=result.get("id"), status_code=response.status_code,
            finish_reason=finish_reason, notify_error=notify_error,
            log_llm_decisions=_log_llm_decisions, recover_partial_decisions=_recover_partial_decisions,
        )
    except Exception as e:
        logging.exception("Error calling LLM API")
        notify_error(f"Error calling LLM API: {e}", metadata={"context": "call_deepseek_api"}, log_error=False)
        return None


# ───────────────────────── PROMPT BUILDING ─────────────────────────
from prompt_builder import format_prompt_for_deepseek as _format_prompt_for_deepseek


def format_prompt_for_deepseek() -> str:
    """Compose a rich prompt for the LLM."""
    return _format_prompt_for_deepseek(
        get_market_data_client=get_market_data_client,
        get_positions=lambda: positions,
        get_balance=lambda: balance,
        get_current_time=get_current_time,
        get_bot_start_time=get_bot_start_time,
        increment_invocation_count=increment_invocation_count,
        calculate_total_margin=calculate_total_margin,
        calculate_unrealized_pnl=calculate_unrealized_pnl,
        interval=INTERVAL,
    )


# ───────────────────────── TRADE EXECUTION ─────────────────────────
from trade_execution import TradeExecutor
from execution_routing import check_stop_loss_take_profit_for_positions as _check_sltp_for_positions


def _get_trade_executor() -> TradeExecutor:
    """Create a trade executor with current dependencies."""
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


def execute_entry(coin: str, decision: Dict[str, Any], current_price: float) -> None:
    """Execute entry trade."""
    _get_trade_executor().execute_entry(coin, decision, current_price)


def execute_close(coin: str, decision: Dict[str, Any], current_price: float) -> None:
    """Execute close trade."""
    _get_trade_executor().execute_close(coin, decision, current_price)


def process_ai_decisions(decisions: Dict[str, Any]) -> None:
    """Handle AI decisions for each tracked coin."""
    for coin in SYMBOL_TO_COIN.values():
        if coin not in decisions:
            continue

        decision = decisions[coin]
        signal = decision.get("signal", "hold")

        log_ai_decision(
            coin,
            signal,
            decision.get("justification", ""),
            decision.get("confidence", 0),
        )

        symbol = COIN_TO_SYMBOL.get(coin)
        if not symbol:
            logging.debug("No symbol mapping found for coin %s", coin)
            continue

        data = fetch_market_data(symbol)
        if not data:
            continue

        current_price = data["price"]

        if signal == "entry":
            execute_entry(coin, decision, current_price)
        elif signal == "close":
            execute_close(coin, decision, current_price)
        elif signal == "hold":
            _get_trade_executor().process_hold_signal(coin, decision, current_price)


def check_stop_loss_take_profit() -> None:
    """Check and execute stop loss / take profit for all positions."""
    _check_sltp_for_positions(
        positions=positions,
        symbol_to_coin=SYMBOL_TO_COIN,
        fetch_market_data=fetch_market_data,
        execute_close=execute_close,
        hyperliquid_is_live=hyperliquid_trader.is_live,
    )


# ───────────────────────── PORTFOLIO DISPLAY ─────────────────────────
from portfolio_display import (
    log_portfolio_state as _log_portfolio_state,
    display_portfolio_summary as _display_portfolio_summary,
)


def log_portfolio_state() -> None:
    """Log current portfolio state to CSV."""
    _log_portfolio_state(
        positions=positions,
        balance=balance,
        calculate_total_equity=calculate_total_equity,
        calculate_total_margin=calculate_total_margin,
        get_btc_benchmark_price=get_btc_benchmark_price,
        get_current_time=get_current_time,
    )


def display_portfolio_summary() -> None:
    """Display the portfolio summary at the end of an iteration."""
    _display_portfolio_summary(
        positions=positions,
        balance=balance,
        equity_history=equity_history,
        calculate_total_equity=calculate_total_equity,
        calculate_total_margin=calculate_total_margin,
        register_equity_snapshot=register_equity_snapshot,
        record_iteration_message=record_iteration_message,
    )


# ───────────────────────── MAIN LOOP ─────────────────────────
def main() -> None:
    """Main trading loop."""
    logging.info("Initializing DeepSeek Multi-Asset Paper Trading Bot...")
    init_csv_files()
    load_equity_history()
    load_state()

    if not LLM_API_KEY:
        logging.error("No LLM API key configured.")
        return

    logging.info(f"Starting capital: ${START_CAPITAL:.2f}")
    logging.info(f"Monitoring: {', '.join(SYMBOL_TO_COIN.values())}")

    if hyperliquid_trader.is_live:
        logging.warning("Hyperliquid LIVE trading enabled. Wallet: %s", hyperliquid_trader.masked_wallet)
    else:
        logging.info("Hyperliquid live trading disabled; running in paper mode only.")

    if TRADING_BACKEND == "binance_futures":
        if BINANCE_FUTURES_LIVE:
            logging.warning("Binance futures LIVE trading enabled.")
        else:
            logging.warning("TRADING_BACKEND=binance_futures but BINANCE_FUTURES_LIVE is not true; paper mode only.")

    if TRADING_BACKEND == "backpack_futures":
        if BACKPACK_FUTURES_LIVE:
            logging.warning("Backpack futures LIVE trading enabled.")
        else:
            logging.warning("TRADING_BACKEND=backpack_futures but BACKPACK_FUTURES_LIVE is not true; paper mode only.")

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        logging.info("Telegram notifications enabled (chat: %s).", TELEGRAM_CHAT_ID)
    else:
        logging.info("Telegram notifications disabled.")

    log_system_prompt_info("System prompt selected")
    logging.info("LLM model configured: %s", LLM_MODEL_NAME)

    while True:
        try:
            _run_iteration()
        except KeyboardInterrupt:
            print("\n\nShutting down bot...")
            save_state()
            break
        except Exception as e:
            logging.error(f"Error in main loop: {e}", exc_info=True)
            save_state()
            time.sleep(60)


def _run_iteration() -> None:
    """Run a single trading iteration."""
    iteration = increment_iteration_counter()
    clear_iteration_messages()

    if not get_binance_client():
        retry_delay = min(CHECK_INTERVAL, 60)
        logging.warning("Binance client unavailable; retrying in %d seconds.", retry_delay)
        time.sleep(retry_delay)
        return

    # Print iteration header
    line = f"\n{Fore.CYAN}{'='*20}"
    print(line)
    record_iteration_message(line)
    current_dt = get_current_time()
    line = f"{Fore.CYAN}Iteration {iteration} - {current_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    print(line)
    record_iteration_message(line)
    line = f"{Fore.CYAN}{'='*20}\n"
    print(line)
    record_iteration_message(line)

    # Check stop loss / take profit first
    check_stop_loss_take_profit()

    # Get AI decisions
    logging.info("Requesting trading decisions from DeepSeek...")
    prompt = format_prompt_for_deepseek()
    decisions = call_deepseek_api(prompt)

    if not decisions:
        logging.warning("No decisions received from AI")
    else:
        process_ai_decisions(decisions)

    # Display portfolio summary
    display_portfolio_summary()

    # Send iteration messages to Telegram
    messages = get_iteration_messages()
    if messages:
        send_telegram_message("\n".join(messages), parse_mode=None)

    # Log state
    log_portfolio_state()
    save_state()

    # Wait for next check
    logging.info(f"Waiting {CHECK_INTERVAL} seconds until next check...")
    sleep_with_countdown(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
