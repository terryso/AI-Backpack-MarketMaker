"""
CLI context builder for llm-trader.

This module provides functions to build the context needed by command handlers,
reusing the same data sources as the Telegram bot.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class CLIContext:
    """Context object containing all dependencies for CLI commands."""
    
    # Risk control state
    risk_control_state: Any  # RiskControlState
    
    # Account data functions
    balance_fn: Callable[[], float]
    total_equity_fn: Callable[[], Optional[float]]
    total_margin_fn: Callable[[], float]
    positions_count_fn: Callable[[], int]
    positions_snapshot_fn: Callable[[], Dict[str, Dict[str, Any]]]
    account_snapshot_fn: Optional[Callable[[], Optional[Dict[str, Any]]]]
    
    # Trading functions
    execute_close_fn: Optional[Callable[[str, str, float], Any]]
    update_tpsl_fn: Optional[Callable[[str, Optional[float], Optional[float]], Any]]
    get_current_price_fn: Optional[Callable[[str], Optional[float]]]
    
    # Config values
    start_capital: float
    risk_control_enabled: bool
    daily_loss_limit_enabled: bool
    daily_loss_limit_pct: float
    sortino_ratio_fn: Optional[Callable[[], Optional[float]]]
    
    # Backend info
    trading_backend: str = "paper"


def _load_portfolio_state() -> Dict[str, Any]:
    """Load portfolio state from persistence file."""
    import json
    
    state_file = os.getenv("PORTFOLIO_STATE_FILE", "portfolio_state.json")
    if not os.path.exists(state_file):
        return {
            "balance": 0.0,
            "positions": {},
            "equity_history": [],
        }
    
    try:
        with open(state_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning("Failed to load portfolio state: %s", e)
        return {
            "balance": 0.0,
            "positions": {},
            "equity_history": [],
        }


def _get_exchange_client(backend: str) -> Optional[Any]:
    """Get exchange client based on TRADING_BACKEND configuration.
    
    Args:
        backend: Trading backend name (binance_futures, backpack_futures, hyperliquid, paper)
        
    Returns:
        Exchange client instance or None if not configured/available.
    """
    normalized = backend.strip().lower()
    
    if normalized == "binance_futures":
        return _get_binance_futures_client()
    elif normalized == "backpack_futures":
        return _get_backpack_client()
    elif normalized == "hyperliquid":
        return _get_hyperliquid_client()
    else:
        # paper or unknown backend
        return None


def _get_binance_futures_client() -> Optional[Any]:
    """Get Binance Futures client if configured.
    
    Note: For CLI read-only operations (positions, balance), we create the client
    even if LIVE_TRADING_ENABLED is false. The client is needed to query account state.
    """
    from config.settings import API_KEY, API_SECRET
    
    if not API_KEY or not API_SECRET:
        logging.warning("Binance API credentials not configured")
        return None
    
    try:
        import ccxt
        from exchange.binance import BinanceFuturesExchangeClient
        
        # Create exchange directly without checking BINANCE_FUTURES_LIVE
        # This allows read-only operations even when live trading is disabled
        # Skip load_markets() for faster initialization - it will be loaded lazily when needed
        exchange = ccxt.binanceusdm({
            "apiKey": API_KEY,
            "secret": API_SECRET,
            "enableRateLimit": True,
            "timeout": 10000,  # 10 second timeout
        })
        
        return BinanceFuturesExchangeClient(exchange)
    except Exception as e:
        logging.warning("Failed to create Binance Futures client: %s", e)
        return None


def _get_backpack_client() -> Optional[Any]:
    """Get Backpack Futures client if configured."""
    api_public_key = os.getenv("BACKPACK_API_PUBLIC_KEY", "").strip()
    api_secret_seed = os.getenv("BACKPACK_API_SECRET_SEED", "").strip()
    
    if not api_public_key or not api_secret_seed:
        return None
    
    try:
        from exchange.backpack import BackpackFuturesExchangeClient
        
        base_url = os.getenv("BACKPACK_API_BASE_URL") or "https://api.backpack.exchange"
        window_raw = os.getenv("BACKPACK_API_WINDOW_MS") or "5000"
        try:
            window_ms = int(window_raw)
        except (TypeError, ValueError):
            window_ms = 5000
        
        return BackpackFuturesExchangeClient(
            api_public_key=api_public_key,
            api_secret_seed=api_secret_seed,
            base_url=base_url,
            window_ms=window_ms,
        )
    except Exception as e:
        logging.warning("Failed to create Backpack client: %s", e)
        return None


def _get_hyperliquid_client() -> Optional[Any]:
    """Get Hyperliquid client if configured."""
    from config.settings import (
        HYPERLIQUID_LIVE_TRADING,
        HYPERLIQUID_WALLET_ADDRESS,
        HYPERLIQUID_PRIVATE_KEY,
    )
    
    if not HYPERLIQUID_LIVE_TRADING:
        logging.debug("Hyperliquid live trading not enabled")
        return None
    
    if not HYPERLIQUID_WALLET_ADDRESS or not HYPERLIQUID_PRIVATE_KEY:
        logging.warning("Hyperliquid credentials not configured")
        return None
    
    try:
        from exchange.factory import get_hyperliquid_trader
        from exchange.hyperliquid import HyperliquidExchangeClient
        
        trader = get_hyperliquid_trader()
        return HyperliquidExchangeClient(trader)
    except Exception as e:
        logging.warning("Failed to create Hyperliquid client: %s", e)
        return None


def _get_live_account_snapshot(client: Any) -> Optional[Any]:
    """Get live account snapshot from exchange.
    
    Returns:
        AccountSnapshot object or None if unavailable.
    """
    if client is None:
        return None
    
    try:
        return client.get_account_snapshot()
    except Exception as e:
        logging.warning("Failed to get live account snapshot: %s", e)
        return None


def build_cli_context() -> CLIContext:
    """Build CLI context with all required dependencies.
    
    This function initializes the context needed for CLI commands by:
    1. Loading portfolio state from persistence
    2. Creating risk control state
    3. Setting up account data functions based on TRADING_BACKEND
    4. Configuring trading functions if exchange is available
    
    Returns:
        CLIContext with all dependencies configured.
    """
    from core.risk_control import RiskControlState
    from config.settings import (
        START_CAPITAL,
        RISK_CONTROL_ENABLED,
        DAILY_LOSS_LIMIT_ENABLED,
        DAILY_LOSS_LIMIT_PCT,
        TRADING_BACKEND,
    )
    
    # Load portfolio state
    portfolio = _load_portfolio_state()
    balance = float(portfolio.get("balance", 0.0))
    positions: Dict[str, Dict[str, Any]] = portfolio.get("positions", {})
    
    # Create or load risk control state
    risk_state_data = portfolio.get("risk_control_state", {})
    risk_control_state = RiskControlState(
        kill_switch_active=risk_state_data.get("kill_switch_active", False),
        kill_switch_reason=risk_state_data.get("kill_switch_reason"),
        kill_switch_triggered_at=risk_state_data.get("kill_switch_triggered_at"),
        daily_start_equity=risk_state_data.get("daily_start_equity"),
        daily_start_date=risk_state_data.get("daily_start_date"),
        daily_loss_pct=risk_state_data.get("daily_loss_pct", 0.0),
        daily_loss_triggered=risk_state_data.get("daily_loss_triggered", False),
    )
    
    # Get exchange client based on TRADING_BACKEND
    trading_backend = TRADING_BACKEND
    exchange_client = _get_exchange_client(trading_backend)
    
    logging.debug("CLI using trading backend: %s, client: %s", 
                  trading_backend, type(exchange_client).__name__ if exchange_client else None)
    
    # Account data functions - now using standardized AccountSnapshot
    def get_balance() -> float:
        snapshot = _get_live_account_snapshot(exchange_client)
        if snapshot is not None:
            return snapshot.balance
        return balance
    
    def get_total_equity() -> Optional[float]:
        snapshot = _get_live_account_snapshot(exchange_client)
        if snapshot is not None:
            return snapshot.total_equity
        # Fallback: balance + unrealized PnL
        total = balance
        for pos in positions.values():
            total += float(pos.get("unrealized_pnl", 0) or 0)
        return total
    
    def get_total_margin() -> float:
        snapshot = _get_live_account_snapshot(exchange_client)
        if snapshot is not None:
            return snapshot.total_margin
        # Fallback: sum of position margins
        total = 0.0
        for pos in positions.values():
            total += float(pos.get("margin", 0) or 0)
        return total
    
    def get_positions_count() -> int:
        snapshot = _get_live_account_snapshot(exchange_client)
        if snapshot is not None:
            return snapshot.positions_count
        return len(positions)
    
    def get_positions_snapshot() -> Dict[str, Dict[str, Any]]:
        """Get positions as dict (for backward compatibility with command handlers)."""
        snapshot = _get_live_account_snapshot(exchange_client)
        if snapshot is not None and snapshot.positions:
            # Convert Position objects to dict format for command handlers
            result: Dict[str, Dict[str, Any]] = {}
            for pos in snapshot.positions:
                result[pos.coin] = {
                    "side": pos.side,
                    "quantity": pos.quantity,
                    "entry_price": pos.entry_price,
                    "profit_target": pos.take_profit,
                    "stop_loss": pos.stop_loss,
                    "leverage": pos.leverage,
                    "margin": pos.margin,
                    "risk_usd": 0.0,
                    "pnl": pos.unrealized_pnl + pos.realized_pnl,
                    "liquidation_price": pos.liquidation_price,
                    "mark_price": pos.mark_price,
                    "notional": pos.notional,
                    "unrealized_pnl": pos.unrealized_pnl,
                }
            return result
        return positions
    
    def get_account_snapshot() -> Optional[Any]:
        """Get raw AccountSnapshot object."""
        return _get_live_account_snapshot(exchange_client)
    
    # Trading functions (only if exchange is configured)
    execute_close_fn = None
    update_tpsl_fn = None
    get_current_price_fn = None
    
    if exchange_client is not None:
        def execute_close(coin: str, side: str, quantity: float) -> Any:
            """Execute position close via exchange."""
            try:
                return exchange_client.close_position(coin, side, quantity)
            except Exception as e:
                logging.error("Failed to execute close: %s", e)
                return None
        
        def update_tpsl(
            coin: str,
            new_sl: Optional[float],
            new_tp: Optional[float],
        ) -> Any:
            """Update TP/SL via exchange."""
            try:
                return exchange_client.update_tpsl(coin, new_sl, new_tp)
            except Exception as e:
                logging.error("Failed to update TP/SL: %s", e)
                return None
        
        def get_current_price(coin: str) -> Optional[float]:
            """Get current price for a coin."""
            try:
                return exchange_client.get_current_price(coin)
            except Exception as e:
                logging.warning("Failed to get current price for %s: %s", coin, e)
                return None
        
        execute_close_fn = execute_close
        update_tpsl_fn = update_tpsl
        get_current_price_fn = get_current_price
    
    return CLIContext(
        risk_control_state=risk_control_state,
        balance_fn=get_balance,
        total_equity_fn=get_total_equity,
        total_margin_fn=get_total_margin,
        positions_count_fn=get_positions_count,
        positions_snapshot_fn=get_positions_snapshot,
        account_snapshot_fn=get_account_snapshot,
        execute_close_fn=execute_close_fn,
        update_tpsl_fn=update_tpsl_fn,
        get_current_price_fn=get_current_price_fn,
        start_capital=START_CAPITAL,
        risk_control_enabled=RISK_CONTROL_ENABLED,
        daily_loss_limit_enabled=DAILY_LOSS_LIMIT_ENABLED,
        daily_loss_limit_pct=DAILY_LOSS_LIMIT_PCT,
        sortino_ratio_fn=None,  # Not critical for CLI
        trading_backend=trading_backend,
    )


def save_risk_control_state(ctx: CLIContext) -> None:
    """Save risk control state back to persistence file."""
    import json
    
    state_file = os.getenv("PORTFOLIO_STATE_FILE", "portfolio_state.json")
    
    # Load existing state
    portfolio = _load_portfolio_state()
    
    # Update risk control state
    state = ctx.risk_control_state
    portfolio["risk_control_state"] = {
        "kill_switch_active": state.kill_switch_active,
        "kill_switch_reason": state.kill_switch_reason,
        "kill_switch_triggered_at": state.kill_switch_triggered_at,
        "daily_start_equity": state.daily_start_equity,
        "daily_start_date": state.daily_start_date,
        "daily_loss_pct": state.daily_loss_pct,
        "daily_loss_triggered": state.daily_loss_triggered,
    }
    
    try:
        with open(state_file, "w") as f:
            json.dump(portfolio, f, indent=2, default=str)
        logging.info("Risk control state saved to %s", state_file)
    except IOError as e:
        logging.error("Failed to save risk control state: %s", e)
