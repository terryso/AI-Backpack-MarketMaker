from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


@dataclass
class TradingConfig:
    paper_start_capital: float
    hyperliquid_capital: float
    trading_backend: str
    market_data_backend: str
    live_trading_enabled: Optional[bool]
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

    live_trading_env = os.getenv("LIVE_TRADING_ENABLED")
    if live_trading_env is not None:
        live_trading_enabled: Optional[bool] = _parse_bool_env(live_trading_env, default=False)
    else:
        live_trading_enabled = None

    if live_trading_enabled is not None:
        hyperliquid_live_trading = bool(live_trading_enabled and trading_backend == "hyperliquid")
    else:
        hyperliquid_live_trading = _parse_bool_env(
            os.getenv("HYPERLIQUID_LIVE_TRADING"),
            default=False,
        )

    if live_trading_enabled is not None:
        binance_futures_live = bool(live_trading_enabled and trading_backend == "binance_futures")
    else:
        binance_futures_live = _parse_bool_env(
            os.getenv("BINANCE_FUTURES_LIVE"),
            default=False,
        )

    if live_trading_enabled is not None:
        backpack_futures_live = bool(live_trading_enabled and trading_backend == "backpack_futures")
    else:
        backpack_futures_live = False

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
        live_trading_enabled=live_trading_enabled,
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
    """Load system prompt content and metadata from env or file.

    This centralizes the logic for resolving TRADEBOT_SYSTEM_PROMPT_FILE/
    TRADEBOT_SYSTEM_PROMPT while preserving existing behaviour and warnings.
    """
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
