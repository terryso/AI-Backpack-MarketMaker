"""Exchange client factory and initialization.

This module handles the initialization and caching of exchange clients
for Binance, Backpack, and Hyperliquid.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import ccxt
from binance.client import Client
from requests.exceptions import RequestException, Timeout

from config.settings import (
    API_KEY,
    API_SECRET,
    TRADING_BACKEND,
    BINANCE_FUTURES_LIVE,
    BACKPACK_API_BASE_URL,
    MARKET_DATA_BACKEND,
    HYPERLIQUID_LIVE_TRADING,
    HYPERLIQUID_WALLET_ADDRESS,
    HYPERLIQUID_PRIVATE_KEY,
)
from exchange.hyperliquid_client import HyperliquidTradingClient
from exchange.market_data import BinanceMarketDataClient, BackpackMarketDataClient
from exchange.base import ExchangeClient
from exchange.hyperliquid import HyperliquidExchangeClient
from exchange.binance import BinanceFuturesExchangeClient
from exchange.backpack import BackpackFuturesExchangeClient


# ───────────────────────── CACHED CLIENTS ─────────────────────────
_binance_client: Optional[Client] = None
_binance_futures_exchange: Optional[Any] = None
_market_data_client: Optional[Any] = None
_hyperliquid_trader: Optional[HyperliquidTradingClient] = None


def init_hyperliquid_trader() -> HyperliquidTradingClient:
    """Initialize and return the Hyperliquid trading client."""
    global _hyperliquid_trader
    if _hyperliquid_trader is not None:
        return _hyperliquid_trader
    
    try:
        _hyperliquid_trader = HyperliquidTradingClient(
            live_mode=HYPERLIQUID_LIVE_TRADING,
            wallet_address=HYPERLIQUID_WALLET_ADDRESS,
            secret_key=HYPERLIQUID_PRIVATE_KEY,
        )
        return _hyperliquid_trader
    except Exception as exc:
        logging.critical("Hyperliquid live trading initialization failed: %s", exc)
        raise SystemExit(1) from exc


def get_hyperliquid_trader() -> HyperliquidTradingClient:
    """Get the cached Hyperliquid trading client."""
    global _hyperliquid_trader
    if _hyperliquid_trader is None:
        return init_hyperliquid_trader()
    return _hyperliquid_trader


def get_binance_futures_exchange() -> Optional[Any]:
    """Get or initialize Binance futures exchange client."""
    global _binance_futures_exchange
    if TRADING_BACKEND != "binance_futures" or not BINANCE_FUTURES_LIVE:
        return None
    if _binance_futures_exchange is not None:
        return _binance_futures_exchange

    api_key = API_KEY
    api_secret = API_SECRET
    if not api_key or not api_secret:
        logging.error("BINANCE_API_KEY and/or BINANCE_API_SECRET missing.")
        return None

    try:
        exchange = ccxt.binanceusdm({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        exchange.load_markets()
        _binance_futures_exchange = exchange
        logging.info("Binance futures client initialized successfully.")
    except Exception as exc:
        logging.error("Failed to initialize Binance futures client: %s", exc)
        _binance_futures_exchange = None
    return _binance_futures_exchange


def get_binance_client() -> Optional[Client]:
    """Return a connected Binance client or None if initialization failed."""
    global _binance_client
    if _binance_client is not None:
        return _binance_client
    if not API_KEY or not API_SECRET:
        logging.error("BN_API_KEY and/or BN_SECRET missing.")
        return None

    try:
        logging.info("Attempting to initialize Binance client...")
        _binance_client = Client(API_KEY, API_SECRET, testnet=False)
        logging.info("Binance client initialized successfully.")
    except Timeout as exc:
        logging.warning("Timed out while connecting to Binance API: %s", exc)
        _binance_client = None
    except RequestException as exc:
        logging.error("Network error while connecting to Binance API: %s", exc)
        _binance_client = None
    except Exception as exc:
        logging.error("Unexpected error while initializing Binance client: %s", exc, exc_info=True)
        _binance_client = None
    return _binance_client


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


def set_market_data_client(client: Any) -> None:
    """Set the market data client (for testing)."""
    global _market_data_client
    _market_data_client = client


def reset_clients() -> None:
    """Reset all cached clients (for testing)."""
    global _binance_client, _binance_futures_exchange, _market_data_client, _hyperliquid_trader
    _binance_client = None
    _binance_futures_exchange = None
    _market_data_client = None
    _hyperliquid_trader = None


def get_exchange_client(
    backend: str,
    **kwargs: Any,
) -> ExchangeClient:
    """ExchangeClient 工厂函数，根据 backend 构造具体实现。

    Bot 主循环与辅助脚本应统一通过此工厂获取具体适配器（如 Hyperliquid、Binance Futures），
    对于未显式支持的 backend 会抛出 NotImplementedError。
    """
    normalized = (backend or "").strip().lower()
    if normalized == "hyperliquid":
        trader = kwargs.get("trader")
        if trader is None:
            raise ValueError("HyperliquidExchangeClient requires 'trader' keyword argument.")
        return HyperliquidExchangeClient(trader)

    if normalized == "binance_futures":
        exchange = kwargs.get("exchange")
        if exchange is None:
            raise ValueError("BinanceFuturesExchangeClient requires 'exchange' keyword argument.")
        return BinanceFuturesExchangeClient(exchange)

    if normalized == "backpack_futures":
        api_public_key = kwargs.get("api_public_key")
        api_secret_seed = kwargs.get("api_secret_seed")
        if not api_public_key or not api_secret_seed:
            raise ValueError(
                "BackpackFuturesExchangeClient requires 'api_public_key' and 'api_secret_seed' keyword arguments.",
            )
        base_url = kwargs.get("base_url", "https://api.backpack.exchange")
        window_ms = kwargs.get("window_ms", 5000)
        return BackpackFuturesExchangeClient(
            api_public_key=str(api_public_key),
            api_secret_seed=str(api_secret_seed),
            base_url=str(base_url),
            window_ms=int(window_ms),
        )

    raise NotImplementedError(
        "Concrete ExchangeClient implementations (e.g. HyperliquidExchangeClient, "
        "BinanceFuturesExchangeClient) are only available for explicitly supported backends."
    )
