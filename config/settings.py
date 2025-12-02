"""
Trading configuration and global constants.

This module centralizes all configuration loading, environment parsing,
and global constants used throughout the trading bot.
"""
from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv


# ───────────────────────── ENV PARSING HELPERS ─────────────────────────
EARLY_ENV_WARNINGS: List[str] = []


def _parse_bool_env(value: Optional[str], *, default: bool = False) -> bool:
    """Convert environment string to bool with sensible defaults."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float_env(value: Optional[str], *, default: float) -> float:
    """Convert environment string to float with fallback and logging."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        EARLY_ENV_WARNINGS.append(
            f"Invalid float environment value '{value}'; using default {default:.2f}"
        )
        return default


def _parse_float_env_with_range(
    value: Optional[str],
    *,
    default: float,
    min_val: float,
    max_val: float,
    var_name: str,
) -> float:
    """Convert environment string to float with range validation.

    If the value is outside [min_val, max_val], logs a warning and returns default.
    """
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        EARLY_ENV_WARNINGS.append(
            f"Invalid {var_name} value '{value}'; using default {default:.2f}"
        )
        return default
    if parsed < min_val or parsed > max_val:
        EARLY_ENV_WARNINGS.append(
            f"{var_name} value {parsed:.2f} out of range [{min_val}, {max_val}]; "
            f"using default {default:.2f}"
        )
        return default
    return parsed


def _parse_int_env(value: Optional[str], *, default: int) -> int:
    """Convert environment string to int with fallback and logging."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        EARLY_ENV_WARNINGS.append(
            f"Invalid int environment value '{value}'; using default {default}"
        )
        return default


def _parse_thinking_env(value: Optional[str]) -> Optional[Any]:
    """Parse LLM thinking budget/configuration from environment."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    return raw


def emit_early_env_warnings() -> None:
    """Log and clear any configuration warnings collected during import time."""
    global EARLY_ENV_WARNINGS
    for msg in EARLY_ENV_WARNINGS:
        logging.warning(msg)
    EARLY_ENV_WARNINGS = []


# ───────────────────────── LLM CONFIG LOADERS ─────────────────────────
DEFAULT_LLM_MODEL = "deepseek/deepseek-chat-v3.1"


def _load_llm_model_name(default_model: str = DEFAULT_LLM_MODEL) -> str:
    """Resolve LLM model name from environment or fall back to default."""
    raw = os.getenv("TRADEBOT_LLM_MODEL", default_model)
    if not raw:
        return default_model
    value = raw.strip()
    return value or default_model


def _load_llm_temperature(default: float = 0.7) -> float:
    """Resolve LLM temperature from environment."""
    return _parse_float_env(
        os.getenv("TRADEBOT_LLM_TEMPERATURE"),
        default=default,
    )


def _load_llm_max_tokens(default: int = 4000) -> int:
    """Resolve LLM max tokens from environment."""
    return _parse_int_env(
        os.getenv("TRADEBOT_LLM_MAX_TOKENS"),
        default=default,
    )


def _load_llm_api_base_url() -> str:
    """Resolve LLM API base URL from environment or fall back to OpenRouter."""
    raw = os.getenv("LLM_API_BASE_URL")
    if raw:
        value = raw.strip()
        if value:
            return value
    return "https://openrouter.ai/api/v1/chat/completions"


def _load_llm_api_key(openrouter_api_key_fallback: str) -> str:
    """Resolve LLM API key, falling back to the provided OpenRouter key."""
    raw = os.getenv("LLM_API_KEY")
    if raw:
        value = raw.strip()
        if value:
            return value
    return openrouter_api_key_fallback


def _load_llm_api_type() -> str:
    """Resolve LLM API type based on environment configuration."""
    raw = os.getenv("LLM_API_TYPE")
    if raw:
        value = raw.strip().lower()
        if value:
            return value
    if os.getenv("LLM_API_BASE_URL"):
        return "custom"
    return "openrouter"


# ───────────────────────── TRADING CONFIG DATACLASS ─────────────────────────
@dataclass
class TradingConfig:
    paper_start_capital: float
    hyperliquid_capital: float
    trading_backend: str
    market_data_backend: str
    # Global master switch: when True and backend is non-paper, live trading is enabled
    live_trading_enabled: bool
    # Per-backend derived flags (for convenience and logging)
    hyperliquid_live_trading: bool
    binance_futures_live: bool
    backpack_futures_live: bool
    binance_futures_max_risk_usd: float
    binance_futures_max_leverage: float
    binance_futures_max_margin_usd: float
    live_start_capital: float
    live_max_risk_usd: float
    live_max_leverage: float
    live_max_margin_usd: float
    is_live_backend: bool
    start_capital: float


def load_trading_config_from_env() -> TradingConfig:
    paper_start_capital = _parse_float_env(
        os.getenv("PAPER_START_CAPITAL"),
        default=10000.0,
    )
    hyperliquid_capital = _parse_float_env(
        os.getenv("HYPERLIQUID_CAPITAL"),
        default=500.0,
    )

    raw_backend = os.getenv("TRADING_BACKEND")
    if raw_backend:
        trading_backend = raw_backend.strip().lower() or "paper"
    else:
        trading_backend = "paper"
    if trading_backend not in {"paper", "hyperliquid", "binance_futures", "backpack_futures"}:
        EARLY_ENV_WARNINGS.append(
            f"Unsupported TRADING_BACKEND '{raw_backend}'; using 'paper'."
        )
        trading_backend = "paper"

    raw_market_backend = os.getenv("MARKET_DATA_BACKEND")
    if raw_market_backend:
        market_data_backend = raw_market_backend.strip().lower() or "binance"
    else:
        market_data_backend = "binance"
    if market_data_backend not in {"binance", "backpack"}:
        EARLY_ENV_WARNINGS.append(
            f"Unsupported MARKET_DATA_BACKEND '{raw_market_backend}'; using 'binance'."
        )
        market_data_backend = "binance"

    # Global live-trading master switch. When True and TRADING_BACKEND is a
    # non-paper backend, live trading is enabled for that backend.
    live_trading_enabled = _parse_bool_env(
        os.getenv("LIVE_TRADING_ENABLED"),
        default=False,
    )

    # Derive per-backend live flags from the global switch and selected backend.
    hyperliquid_live_trading = bool(live_trading_enabled and trading_backend == "hyperliquid")
    binance_futures_live = bool(live_trading_enabled and trading_backend == "binance_futures")
    backpack_futures_live = bool(live_trading_enabled and trading_backend == "backpack_futures")

    binance_futures_max_risk_usd = _parse_float_env(
        os.getenv("BINANCE_FUTURES_MAX_RISK_USD"),
        default=100.0,
    )
    binance_futures_max_leverage = _parse_float_env(
        os.getenv("BINANCE_FUTURES_MAX_LEVERAGE"),
        default=10.0,
    )

    binance_futures_max_margin_usd = _parse_float_env(
        os.getenv("BINANCE_FUTURES_MAX_MARGIN_USD"),
        default=0.0,
    )

    live_start_capital = _parse_float_env(
        os.getenv("LIVE_START_CAPITAL"),
        default=hyperliquid_capital,
    )

    live_max_risk_usd = _parse_float_env(
        os.getenv("LIVE_MAX_RISK_USD"),
        default=binance_futures_max_risk_usd,
    )
    live_max_leverage = _parse_float_env(
        os.getenv("LIVE_MAX_LEVERAGE"),
        default=binance_futures_max_leverage,
    )
    live_max_margin_usd = _parse_float_env(
        os.getenv("LIVE_MAX_MARGIN_USD"),
        default=binance_futures_max_margin_usd,
    )

    is_live_backend = (
        (trading_backend == "hyperliquid" and hyperliquid_live_trading)
        or (trading_backend == "binance_futures" and binance_futures_live)
        or (trading_backend == "backpack_futures" and backpack_futures_live)
    )

    start_capital = live_start_capital if is_live_backend else paper_start_capital

    return TradingConfig(
        paper_start_capital=paper_start_capital,
        hyperliquid_capital=hyperliquid_capital,
        trading_backend=trading_backend,
        market_data_backend=market_data_backend,
        live_trading_enabled=bool(live_trading_enabled),
        hyperliquid_live_trading=hyperliquid_live_trading,
        binance_futures_live=binance_futures_live,
        backpack_futures_live=backpack_futures_live,
        binance_futures_max_risk_usd=binance_futures_max_risk_usd,
        binance_futures_max_leverage=binance_futures_max_leverage,
        binance_futures_max_margin_usd=binance_futures_max_margin_usd,
        live_start_capital=live_start_capital,
        live_max_risk_usd=live_max_risk_usd,
        live_max_leverage=live_max_leverage,
        live_max_margin_usd=live_max_margin_usd,
        is_live_backend=is_live_backend,
        start_capital=start_capital,
    )


def load_system_prompt_from_env(
    base_dir: Path,
    default_prompt: str,
) -> Tuple[str, Dict[str, Any]]:
    """Load system prompt content and metadata from env or file."""
    system_prompt_source: Dict[str, Any] = {"type": "default"}

    prompt_file = os.getenv("TRADEBOT_SYSTEM_PROMPT_FILE")
    if prompt_file:
        path = Path(prompt_file).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        try:
            if path.exists():
                system_prompt_source = {"type": "file", "path": str(path)}
                return path.read_text(encoding="utf-8").strip(), system_prompt_source
            EARLY_ENV_WARNINGS.append(
                f"System prompt file '{path}' not found; using default prompt."
            )
        except Exception as exc:  # pragma: no cover - defensive logging only
            EARLY_ENV_WARNINGS.append(
                f"Failed to read system prompt file '{path}': {exc}; using default prompt."
            )

    prompt_env = os.getenv("TRADEBOT_SYSTEM_PROMPT")
    if prompt_env:
        system_prompt_source = {"type": "env"}
        return prompt_env.strip(), system_prompt_source

    system_prompt_source = {"type": "default"}
    return default_prompt, system_prompt_source

# ───────────────────────── PATH SETUP ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
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
TELEGRAM_ADMIN_USER_ID = os.getenv("TELEGRAM_ADMIN_USER_ID", "")

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
    "ETHUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDT", "BNBUSDT"
]
SYMBOL_TO_COIN = {
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "XRPUSDT": "XRP",
    "BTCUSDT": "BTC",
    "BNBUSDT": "BNB",
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

# ───────────────────────── RISK CONTROL CONFIG ─────────────────────────
RISK_CONTROL_ENABLED = _parse_bool_env(
    os.getenv("RISK_CONTROL_ENABLED"),
    default=True,
)
KILL_SWITCH = _parse_bool_env(
    os.getenv("KILL_SWITCH"),
    default=False,
)
DAILY_LOSS_LIMIT_ENABLED = _parse_bool_env(
    os.getenv("DAILY_LOSS_LIMIT_ENABLED"),
    default=True,
)
DAILY_LOSS_LIMIT_PCT = _parse_float_env_with_range(
    os.getenv("DAILY_LOSS_LIMIT_PCT"),
    default=5.0,
    min_val=0.0,
    max_val=100.0,
    var_name="DAILY_LOSS_LIMIT_PCT",
)

# ───────────────────────── EFFECTIVE CONFIG GETTERS ─────────────────────────
# These functions implement the priority: runtime override > env > default
# They are the preferred way to access the 4 whitelisted config values at runtime

def get_effective_trading_backend() -> str:
    """
    Get the effective trading backend with override priority.
    
    Priority: runtime override > env > default ('paper')
    
    Returns:
        Effective trading backend value
    """
    from config.runtime_overrides import get_runtime_override, VALID_TRADING_BACKENDS
    
    override = get_runtime_override("TRADING_BACKEND")
    if override is not None:
        # Normalize and validate the override value
        normalized = str(override).strip().lower()
        if normalized in VALID_TRADING_BACKENDS:
            return normalized
        # Invalid override value - log warning and fall through to env
        EARLY_ENV_WARNINGS.append(
            f"Invalid TRADING_BACKEND override '{override}'; ignoring and using env/default."
        )
    
    # Fall back to module-level value (loaded from env at import time)
    return TRADING_BACKEND


def get_effective_market_data_backend() -> str:
    """
    Get the effective market data backend with override priority.
    
    Priority: runtime override > env > default ('binance')
    
    Returns:
        Effective market data backend value
    """
    from config.runtime_overrides import get_runtime_override, VALID_MARKET_DATA_BACKENDS
    
    override = get_runtime_override("MARKET_DATA_BACKEND")
    if override is not None:
        # Normalize and validate the override value
        normalized = str(override).strip().lower()
        if normalized in VALID_MARKET_DATA_BACKENDS:
            return normalized
        # Invalid override value - log warning and fall through to env
        EARLY_ENV_WARNINGS.append(
            f"Invalid MARKET_DATA_BACKEND override '{override}'; ignoring and using env/default."
        )
    
    # Fall back to module-level value (loaded from env at import time)
    return MARKET_DATA_BACKEND


def get_effective_interval() -> str:
    """
    Get the effective trading interval with override priority.
    
    Priority: runtime override > env > default ('15m')
    
    Returns:
        Effective interval value (e.g., '15m', '1h')
    """
    from config.runtime_overrides import get_runtime_override, VALID_INTERVALS
    
    override = get_runtime_override("TRADEBOT_INTERVAL")
    if override is not None:
        # Normalize and validate the override value
        normalized = str(override).strip().lower()
        if normalized in VALID_INTERVALS:
            return normalized
        # Invalid override value - log warning and fall through to env
        EARLY_ENV_WARNINGS.append(
            f"Invalid TRADEBOT_INTERVAL override '{override}'; ignoring and using env/default."
        )
    
    # Fall back to module-level value (loaded from env at import time)
    return INTERVAL


def get_effective_check_interval() -> int:
    """
    Get the effective check interval in seconds with override priority.
    
    This is derived from get_effective_interval().
    
    Returns:
        Effective check interval in seconds
    """
    interval = get_effective_interval()
    return _INTERVAL_TO_SECONDS.get(interval, _INTERVAL_TO_SECONDS[DEFAULT_INTERVAL])


def get_effective_llm_temperature() -> float:
    """
    Get the effective LLM temperature with override priority.
    
    Priority: runtime override > env > default (0.7)
    
    Returns:
        Effective LLM temperature value
    """
    from config.runtime_overrides import (
        get_runtime_override, LLM_TEMPERATURE_MIN, LLM_TEMPERATURE_MAX
    )
    
    override = get_runtime_override("TRADEBOT_LLM_TEMPERATURE")
    if override is not None:
        try:
            float_value = float(override)
            if LLM_TEMPERATURE_MIN <= float_value <= LLM_TEMPERATURE_MAX:
                return float_value
            # Out of range - log warning and fall through to env
            EARLY_ENV_WARNINGS.append(
                f"TRADEBOT_LLM_TEMPERATURE override {float_value} out of range "
                f"[{LLM_TEMPERATURE_MIN}, {LLM_TEMPERATURE_MAX}]; ignoring and using env/default."
            )
        except (TypeError, ValueError):
            # Invalid value - log warning and fall through to env
            EARLY_ENV_WARNINGS.append(
                f"Invalid TRADEBOT_LLM_TEMPERATURE override '{override}'; "
                "ignoring and using env/default."
            )
    
    # Fall back to module-level value (loaded from env at import time)
    return LLM_TEMPERATURE


def get_effective_live_trading_enabled() -> bool:
    """Get the effective LIVE_TRADING_ENABLED flag with override priority.
    
    Priority: runtime override > env/default (LIVE_TRADING_ENABLED constant).
    
    Returns:
        True if live trading is effectively enabled for the selected backend,
        False otherwise.
    """
    from config.runtime_overrides import get_runtime_override
    
    override = get_runtime_override("LIVE_TRADING_ENABLED")
    if override is not None:
        normalized = str(override).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        EARLY_ENV_WARNINGS.append(
            f"Invalid LIVE_TRADING_ENABLED override '{override}'; ignoring and using env/default."
        )
    return bool(LIVE_TRADING_ENABLED)


def get_effective_tradebot_loop_enabled() -> bool:
    """Get the effective TRADEBOT_LOOP_ENABLED flag with override priority.

    Priority: runtime override > env/default (True).

    This flag controls whether the main trading loop actively runs `_run_iteration`
    logic or stays in a paused state between iterations.
    """
    from config.runtime_overrides import get_runtime_override

    override = get_runtime_override("TRADEBOT_LOOP_ENABLED")
    if override is not None:
        normalized = str(override).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        EARLY_ENV_WARNINGS.append(
            f"Invalid TRADEBOT_LOOP_ENABLED override '{override}'; ignoring and using env/default."
        )

    # Env fallback; default to True so existing behaviour is preserved
    env_value = os.getenv("TRADEBOT_LOOP_ENABLED")
    if env_value is not None:
        return _parse_bool_env(env_value, default=True)
    return True


def get_telegram_admin_user_id() -> str:
    """
    Get the Telegram admin user ID for permission control.
    
    This function returns the configured admin user ID that is authorized
    to execute privileged Telegram commands like /config set.
    
    Returns:
        Admin user ID string, or empty string if not configured.
        
    Note:
        When empty, all /config set commands will be rejected with a
        permission denied message. This is a secure default.
    """
    return TELEGRAM_ADMIN_USER_ID.strip()


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
