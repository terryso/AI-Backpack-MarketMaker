"""
Trading configuration and global constants.

This module centralizes all configuration loading, environment parsing,
and global constants used throughout the trading bot.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from bot_config import (
    EARLY_ENV_WARNINGS,
    DEFAULT_LLM_MODEL,
    TradingConfig,
    _parse_bool_env,
    _parse_float_env,
    _parse_int_env,
    _parse_thinking_env,
    _load_llm_model_name,
    _load_llm_temperature,
    _load_llm_max_tokens,
    _load_llm_api_base_url,
    _load_llm_api_key,
    _load_llm_api_type,
    emit_early_env_warnings,
    load_trading_config_from_env,
    load_system_prompt_from_env,
)

# ───────────────────────── PATH SETUP ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / ".env"

if DOTENV_PATH.exists():
    dotenv_loaded = load_dotenv(dotenv_path=DOTENV_PATH, override=True)
else:
    dotenv_loaded = load_dotenv(override=True)

DEFAULT_DATA_DIR = BASE_DIR / "data"
DATA_DIR = Path(os.getenv("TRADEBOT_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ───────────────────────── API KEYS ─────────────────────────
API_KEY = os.getenv("BN_API_KEY", "")
API_SECRET = os.getenv("BN_SECRET", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_SIGNALS_CHAT_ID = os.getenv("TELEGRAM_SIGNALS_CHAT_ID", "")

HYPERLIQUID_WALLET_ADDRESS = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
HYPERLIQUID_PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")

BACKPACK_API_PUBLIC_KEY = os.getenv("BACKPACK_API_PUBLIC_KEY", "")
BACKPACK_API_SECRET_SEED = os.getenv("BACKPACK_API_SECRET_SEED", "")
BACKPACK_API_BASE_URL = os.getenv("BACKPACK_API_BASE_URL", "https://api.backpack.exchange")
BACKPACK_API_WINDOW_MS = _parse_int_env(
    os.getenv("BACKPACK_API_WINDOW_MS"),
    default=5000,
)

# ───────────────────────── TRADING CONFIG ─────────────────────────
_TRADING_CFG: TradingConfig = load_trading_config_from_env()

PAPER_START_CAPITAL = _TRADING_CFG.paper_start_capital
HYPERLIQUID_CAPITAL = _TRADING_CFG.hyperliquid_capital
TRADING_BACKEND = _TRADING_CFG.trading_backend
MARKET_DATA_BACKEND = _TRADING_CFG.market_data_backend
LIVE_TRADING_ENABLED = _TRADING_CFG.live_trading_enabled
HYPERLIQUID_LIVE_TRADING = _TRADING_CFG.hyperliquid_live_trading
BINANCE_FUTURES_LIVE = _TRADING_CFG.binance_futures_live
BACKPACK_FUTURES_LIVE = _TRADING_CFG.backpack_futures_live
BINANCE_FUTURES_MAX_RISK_USD = _TRADING_CFG.binance_futures_max_risk_usd
BINANCE_FUTURES_MAX_LEVERAGE = _TRADING_CFG.binance_futures_max_leverage
BINANCE_FUTURES_MAX_MARGIN_USD = _TRADING_CFG.binance_futures_max_margin_usd
LIVE_START_CAPITAL = _TRADING_CFG.live_start_capital
LIVE_MAX_RISK_USD = _TRADING_CFG.live_max_risk_usd
LIVE_MAX_LEVERAGE = _TRADING_CFG.live_max_leverage
LIVE_MAX_MARGIN_USD = _TRADING_CFG.live_max_margin_usd
IS_LIVE_BACKEND = _TRADING_CFG.is_live_backend
START_CAPITAL = _TRADING_CFG.start_capital

# ───────────────────────── SYMBOLS ─────────────────────────
SYMBOLS = [
    "ETHUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDT", "DOGEUSDT",
    "BNBUSDT", "PAXGUSDT", "PUMPUSDT", "MONUSDT", "HYPEUSDT"
]
SYMBOL_TO_COIN = {
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "XRPUSDT": "XRP",
    "BTCUSDT": "BTC",
    "DOGEUSDT": "DOGE",
    "BNBUSDT": "BNB",
    "PAXGUSDT": "PAXG",
    "PUMPUSDT": "PUMP",
    "MONUSDT": "MON",
    "HYPEUSDT": "HYPE",
}
COIN_TO_SYMBOL = {coin: symbol for symbol, coin in SYMBOL_TO_COIN.items()}

# ───────────────────────── SYSTEM PROMPT ─────────────────────────
DEFAULT_TRADING_RULES_PROMPT = """
You are a top level crypto trader focused on multiplying the account while safeguarding capital. Always apply these core rules:

Most Important Rules for Crypto Traders

Capital preservation is the foundation of successful crypto trading—your primary goal is to protect what you have so you can continue trading and growing.

Never Risk More Than 1-2% Per Trade
- Treat the 1% rule as non-negotiable; never risk more than 1-2% of total capital on a single trade.
- Survive losing streaks with enough capital to recover.

Use Stop-Loss Orders on Every Trade
- Define exit points before entering any position.
- Stop-loss orders are mandatory safeguards against emotional decisions.

Follow the Trend—Don't Fight the Market
- Buy rising coins and sell falling ones; the market is always right.
- Wait for confirmation before committing capital.

Stay Inactive Most of the Time
- Trade only when high-probability setups emerge.
- Avoid overtrading; patience and discipline preserve capital.

Cut Losses Quickly and Let Profits Run
- Close losing trades decisively; exit weak performers without hesitation.
- Let winning trades develop and grow when they show early profit.

Maintain a Written Trading Plan
- Know entry, exit, and profit targets before executing.
- Consistently follow the plan to keep emotions in check.

Control Leverage and Position Sizing
- Use leverage responsibly; ensure even a worst-case loss stays within the 1-2% risk cap.
- Proper sizing is central to risk management.

Focus on Small Consistent Wins
- Prioritize steady gains over chasing moonshots.
- Incremental growth compounds reliably and is easier to manage.

Think in Probabilities, Not Predictions
- Treat trading like a probability game with positive expectancy over many trades.
- Shift mindset from needing to be right to managing outcomes.

Stay Informed but Trade Less
- Track market-moving news but trade only when indicators align and risk-reward is favorable.
""".strip()

SYSTEM_PROMPT_SOURCE: Dict[str, Any] = {"type": "default"}


def _load_system_prompt() -> str:
    """Load system prompt from env variables or fall back to default."""
    global SYSTEM_PROMPT_SOURCE
    prompt, source = load_system_prompt_from_env(BASE_DIR, DEFAULT_TRADING_RULES_PROMPT)
    SYSTEM_PROMPT_SOURCE = dict(source)
    return prompt


def describe_system_prompt_source() -> str:
    """Return human-readable description of the active system prompt."""
    source_type = SYSTEM_PROMPT_SOURCE.get("type", "default")
    if source_type == "file":
        return f"file:{SYSTEM_PROMPT_SOURCE.get('path', '?')}"
    if source_type == "env":
        return "env:TRADEBOT_SYSTEM_PROMPT"
    return "default prompt"


TRADING_RULES_PROMPT = _load_system_prompt()

# ───────────────────────── INTERVAL CONFIG ─────────────────────────
DEFAULT_INTERVAL = "15m"
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


def _load_trade_interval(default: str = DEFAULT_INTERVAL) -> str:
    """Resolve trade interval from environment."""
    raw = os.getenv("TRADEBOT_INTERVAL")
    if raw:
        candidate = raw.strip().lower()
        if candidate in _INTERVAL_TO_SECONDS:
            return candidate
        EARLY_ENV_WARNINGS.append(
            f"Unsupported TRADEBOT_INTERVAL '{raw}'; using default {default}."
        )
    return default


INTERVAL = _load_trade_interval()
CHECK_INTERVAL = _INTERVAL_TO_SECONDS[INTERVAL]
DEFAULT_RISK_FREE_RATE = 0.0  # Annualized baseline for Sortino ratio calculations

# ───────────────────────── LLM CONFIG ─────────────────────────
LLM_MODEL_NAME = _load_llm_model_name()
LLM_TEMPERATURE = _load_llm_temperature()
LLM_MAX_TOKENS = _load_llm_max_tokens()
LLM_THINKING_PARAM = _parse_thinking_env(os.getenv("TRADEBOT_LLM_THINKING"))
LLM_API_BASE_URL = _load_llm_api_base_url()
LLM_API_KEY = _load_llm_api_key(OPENROUTER_API_KEY)
LLM_API_TYPE = _load_llm_api_type()


def refresh_llm_configuration_from_env() -> None:
    """Reload LLM-related runtime settings from environment variables."""
    global LLM_MODEL_NAME, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_THINKING_PARAM
    global TRADING_RULES_PROMPT, LLM_API_BASE_URL, LLM_API_KEY, LLM_API_TYPE
    LLM_MODEL_NAME = _load_llm_model_name()
    LLM_TEMPERATURE = _load_llm_temperature()
    LLM_MAX_TOKENS = _load_llm_max_tokens()
    LLM_THINKING_PARAM = _parse_thinking_env(os.getenv("TRADEBOT_LLM_THINKING"))
    TRADING_RULES_PROMPT = _load_system_prompt()
    LLM_API_BASE_URL = _load_llm_api_base_url()
    LLM_API_KEY = _load_llm_api_key(OPENROUTER_API_KEY)
    LLM_API_TYPE = _load_llm_api_type()


def log_system_prompt_info(prefix: str = "System prompt in use") -> None:
    """Log the current system prompt configuration."""
    description = describe_system_prompt_source()
    logging.info("%s: %s", prefix, description)


# ───────────────────────── INDICATOR SETTINGS ─────────────────────────
EMA_LEN = 20
RSI_LEN = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ───────────────────────── FEE STRUCTURE ─────────────────────────
MAKER_FEE_RATE = 0.0         # 0.0000%
TAKER_FEE_RATE = 0.000275    # 0.0275%

# ───────────────────────── RISK FREE RATE ─────────────────────────
def _resolve_risk_free_rate() -> float:
    """Determine the annualized risk-free rate used in Sortino calculations."""
    env_value = os.getenv("SORTINO_RISK_FREE_RATE")
    if env_value is None:
        env_value = os.getenv("RISK_FREE_RATE")
    if env_value is None:
        return DEFAULT_RISK_FREE_RATE
    try:
        return float(env_value)
    except (TypeError, ValueError):
        logging.warning(
            "Invalid SORTINO_RISK_FREE_RATE/RISK_FREE_RATE value '%s'; using default %.4f",
            env_value,
            DEFAULT_RISK_FREE_RATE,
        )
        return DEFAULT_RISK_FREE_RATE


RISK_FREE_RATE = _resolve_risk_free_rate()

# ───────────────────────── CSV FILES ─────────────────────────
STATE_CSV = DATA_DIR / "portfolio_state.csv"
STATE_JSON = DATA_DIR / "portfolio_state.json"
TRADES_CSV = DATA_DIR / "trade_history.csv"
DECISIONS_CSV = DATA_DIR / "ai_decisions.csv"
MESSAGES_CSV = DATA_DIR / "ai_messages.csv"
MESSAGES_RECENT_CSV = DATA_DIR / "ai_messages_recent.csv"
MAX_RECENT_MESSAGES = 100
STATE_COLUMNS = [
    'timestamp',
    'total_balance',
    'total_equity',
    'total_return_pct',
    'num_positions',
    'position_details',
    'total_margin',
    'net_unrealized_pnl',
    'btc_price',
]
