"""Binance Futures exchange client implementation.

This module provides the ExchangeClient implementation for Binance Futures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from exchange.base import EntryResult, CloseResult, Position, AccountSnapshot, TPSLResult, AuditData


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    if value is None:
        return default
    try:
        result = float(value)
        return default if result != result else result  # NaN check
    except (TypeError, ValueError):
        return default


def _safe_decimal(value: Any) -> Optional[Decimal]:
    """Safely convert a value to Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_coin_from_symbol(symbol: str) -> str:
    """Extract coin name from various symbol formats.
    
    Supports:
    - ccxt format: BTC/USDT:USDT -> BTC
    - Binance raw: BTCUSDT -> BTC
    """
    upper = symbol.upper()
    if "/" in upper:
        return upper.split("/", 1)[0]
    if upper.endswith("USDT"):
        return upper[:-4]
    if upper.endswith("USDC"):
        return upper[:-4]
    if upper.endswith("USD"):
        return upper[:-3]
    return upper


class BinanceFuturesExchangeClient:
    """ExchangeClient implementation for Binance Futures."""
    
    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange

    def get_account_snapshot(self) -> Optional[AccountSnapshot]:
        """Get account snapshot including balance and positions.
        
        Returns:
            AccountSnapshot with standardized data format.
        """
        try:
            # Fetch balance info
            balance_info = self._exchange.fetch_balance()
            
            # Extract USDT balance (main margin currency for USDM futures)
            usdt_info = balance_info.get("USDT", {})
            free_balance = _safe_float(usdt_info.get("free"))
            total_balance = _safe_float(usdt_info.get("total"))
            
            # Get total equity from info if available
            info = balance_info.get("info", {})
            total_equity = 0.0
            total_margin = 0.0
            
            if isinstance(info, dict):
                total_equity = _safe_float(info.get("totalWalletBalance"))
                total_margin = _safe_float(info.get("totalPositionInitialMargin"))
            
            if total_equity == 0:
                total_equity = total_balance
            
            # Fetch and parse positions
            positions_raw = self._exchange.fetch_positions()
            positions = self._parse_positions(positions_raw)
            
            return AccountSnapshot(
                balance=free_balance,
                total_equity=total_equity,
                total_margin=total_margin,
                positions=positions,
                raw={"balance_info": info, "positions_raw": positions_raw},
            )
        except Exception as e:
            logging.warning("Failed to get Binance account snapshot: %s", e)
            return None

    def _parse_positions(self, positions_raw: List[Dict[str, Any]]) -> List[Position]:
        """Parse raw positions into standardized Position objects."""
        positions: List[Position] = []
        
        for pos in positions_raw:
            if not isinstance(pos, dict):
                continue
            
            # Get quantity - skip if zero
            contracts = _safe_float(pos.get("contracts"))
            if contracts == 0:
                continue
            
            # Parse symbol to coin name
            symbol = str(pos.get("symbol", "") or "")
            coin = _parse_coin_from_symbol(symbol)
            
            # Determine side from positionSide (hedge mode) or contracts sign
            position_side = str(pos.get("side", "") or "").upper()
            if position_side in ("LONG", "SHORT"):
                side = position_side.lower()
            else:
                side = "long" if contracts > 0 else "short"
            
            quantity = abs(contracts)
            entry_price = _safe_float(pos.get("entryPrice"))
            mark_price = _safe_float(pos.get("markPrice"))
            
            # Notional and margin
            notional = _safe_float(pos.get("notional"))
            if notional == 0 and entry_price > 0:
                notional = quantity * entry_price
            notional = abs(notional)
            
            margin = _safe_float(pos.get("initialMargin"))
            if margin == 0:
                margin = _safe_float(pos.get("collateral"))
            
            # Leverage
            leverage = _safe_float(pos.get("leverage"))
            if leverage == 0 and margin > 0 and notional > 0:
                leverage = notional / margin
            if leverage == 0:
                leverage = 1.0
            
            # PnL
            unrealized_pnl = _safe_float(pos.get("unrealizedPnl"))
            if unrealized_pnl == 0:
                unrealized_pnl = _safe_float(pos.get("unrealizedProfit"))
            
            # Liquidation price
            liq_price = _safe_float(pos.get("liquidationPrice"))
            liq_price = liq_price if liq_price > 0 else None
            
            positions.append(Position(
                coin=coin,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                mark_price=mark_price if mark_price > 0 else None,
                leverage=leverage,
                margin=margin,
                notional=notional,
                unrealized_pnl=unrealized_pnl,
                liquidation_price=liq_price,
                raw=pos,
            ))
        
        return positions

    def get_current_price(self, coin: str) -> Optional[float]:
        """Get current price for a coin."""
        symbol = f"{coin}USDT"
        try:
            ticker = self._exchange.fetch_ticker(symbol)
            return _safe_float(ticker.get("last"))
        except Exception as e:
            logging.warning("Failed to get price for %s: %s", symbol, e)
            return None

    # ═══════════════════════════════════════════════════════════════════
    # AUDIT DATA (for /audit command)
    # ═══════════════════════════════════════════════════════════════════

    def fetch_audit_data(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> AuditData:
        """Aggregate Binance Futures income history into AuditData.

        使用 Binance USDT-M 永续合约的收益历史 (income history) 统计：
        - FUNDING_FEE      -> 资金费 (funding_total / funding_by_symbol)
        - REALIZED_PNL     -> 结算 RealizePnl
        - COMMISSION       -> 手续费 TradingFees
        - 其他类型         -> 归入 settlement_by_source 的对应类型
        """
        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)

        start_ms = int(start_utc.timestamp() * 1000)
        end_ms = int(end_utc.timestamp() * 1000)

        incomes: List[Dict[str, Any]] = []
        try:
            params: Dict[str, Any] = {
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }
            raw = self._exchange.fapiPrivateGetIncome(params)
            if isinstance(raw, list):
                incomes = [item for item in raw if isinstance(item, dict)]
        except Exception as exc:  # noqa: BLE001
            logging.warning("Binance income history request failed: %s", exc)

        funding_total = Decimal("0")
        funding_by_symbol: Dict[str, Decimal] = {}
        settlement_total = Decimal("0")
        settlement_by_source: Dict[str, Decimal] = {}

        for item in incomes:
            income_type = str(item.get("incomeType") or item.get("type") or "").upper()
            amount = _safe_decimal(item.get("income"))
            if amount is None or amount == 0:
                continue

            symbol = str(item.get("symbol") or "").upper()
            key_symbol = symbol or "(unknown)"

            if income_type == "FUNDING_FEE":
                funding_total += amount
                funding_by_symbol[key_symbol] = funding_by_symbol.get(key_symbol, Decimal("0")) + amount
                continue

            if income_type == "REALIZED_PNL":
                settlement_total += amount
                settlement_by_source["RealizePnl"] = settlement_by_source.get("RealizePnl", Decimal("0")) + amount
                continue

            if income_type == "COMMISSION":
                settlement_total += amount
                settlement_by_source["TradingFees"] = settlement_by_source.get("TradingFees", Decimal("0")) + amount
                continue

            # 其他类型收入/支出统一记入各自类型的桶中
            label = income_type or "Other"
            settlement_total += amount
            settlement_by_source[label] = settlement_by_source.get(label, Decimal("0")) + amount

        # 目前暂不从 Binance 提取充值/提现数据，保持为 0
        deposit_total = Decimal("0")
        withdrawal_total = Decimal("0")

        return AuditData(
            backend="binance_futures",
            funding_total=funding_total,
            funding_by_symbol=funding_by_symbol,
            settlement_total=settlement_total,
            settlement_by_source=settlement_by_source,
            deposit_total=deposit_total,
            withdrawal_total=withdrawal_total,
            raw={"income_history": incomes},
        )

    def update_tpsl(
        self,
        coin: str,
        side: str,
        quantity: float,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> TPSLResult:
        """Update stop loss and/or take profit for a position.
        
        Creates STOP_MARKET and/or TAKE_PROFIT_MARKET orders on Binance Futures.
        First cancels any existing SL/TP orders for the position, then creates new ones.
        
        Args:
            coin: Coin symbol (e.g., "BTC", "ETH").
            side: Position side ("long" or "short").
            quantity: Position quantity for the SL/TP orders.
            new_sl: New stop loss price, or None to skip.
            new_tp: New take profit price, or None to skip.
            
        Returns:
            TPSLResult with success status and order IDs.
        """
        symbol = f"{coin}USDT"
        errors: List[str] = []
        sl_order_id = None
        tp_order_id = None
        raw_results: Dict[str, Any] = {}
        
        if new_sl is None and new_tp is None:
            return TPSLResult(
                success=True,
                backend="binance_futures",
                errors=[],
                raw={"reason": "no SL/TP values provided"},
            )
        
        # Determine order side (opposite of position side for closing)
        close_side = "sell" if side.lower() == "long" else "buy"
        position_side = "LONG" if side.lower() == "long" else "SHORT"
        
        # Cancel existing SL/TP orders first
        try:
            self._cancel_existing_tpsl_orders(symbol, position_side)
        except Exception as e:
            logging.warning("Failed to cancel existing TP/SL orders for %s: %s", symbol, e)
            # Continue anyway - new orders might still work
        
        def _place_tpsl_order(
            order_type: str,
            stop_price: float,
            label: str,
        ) -> Optional[Any]:
            """Place TP/SL order helper."""
            params = {
                "stopPrice": stop_price,
                "positionSide": position_side,
            }
            try:
                return self._exchange.create_order(
                    symbol=symbol,
                    type=order_type,
                    side=close_side,
                    amount=quantity,
                    params=params,
                )
            except Exception as exc:
                error_msg = f"{label} order failed: {exc}"
                errors.append(error_msg)
                logging.error("Binance %s: %s", symbol, error_msg)
                return None
        
        # Create Stop Loss order
        if new_sl is not None and new_sl > 0:
            sl_order = _place_tpsl_order("STOP_MARKET", new_sl, "SL")
            if sl_order is not None:
                sl_order_id = self._extract_order_id(sl_order)
                raw_results["sl_order"] = sl_order
                logging.info(
                    "Binance SL order created: %s %s @ %s, order_id=%s",
                    symbol, close_side, new_sl, sl_order_id,
                )
        
        # Create Take Profit order
        if new_tp is not None and new_tp > 0:
            tp_order = _place_tpsl_order("TAKE_PROFIT_MARKET", new_tp, "TP")
            if tp_order is not None:
                tp_order_id = self._extract_order_id(tp_order)
                raw_results["tp_order"] = tp_order
                logging.info(
                    "Binance TP order created: %s %s @ %s, order_id=%s",
                    symbol, close_side, new_tp, tp_order_id,
                )
        
        # Success if at least one order was created without errors
        success = (
            (new_sl is None or sl_order_id is not None) and
            (new_tp is None or tp_order_id is not None)
        )
        
        return TPSLResult(
            success=success,
            backend="binance_futures",
            errors=errors,
            sl_order_id=sl_order_id,
            tp_order_id=tp_order_id,
            raw=raw_results,
        )

    def _cancel_existing_tpsl_orders(self, symbol: str, position_side: str) -> None:
        """Cancel existing SL/TP orders for a position."""
        try:
            open_orders = self._exchange.fetch_open_orders(symbol)
            for order in open_orders:
                order_type = str(order.get("type", "")).upper()
                order_info = order.get("info", {})
                order_position_side = order_info.get("positionSide", "")
                
                # Only cancel STOP_MARKET and TAKE_PROFIT_MARKET orders for this position
                if order_type in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
                    if order_position_side == position_side:
                        order_id = order.get("id")
                        if order_id:
                            self._exchange.cancel_order(order_id, symbol)
                            logging.debug("Cancelled existing %s order %s", order_type, order_id)
        except Exception as e:
            logging.warning("Error cancelling existing TP/SL orders: %s", e)

    @staticmethod
    def _deduplicate_errors(errors: List[str]) -> List[str]:
        seen: Dict[str, None] = {}
        for item in errors:
            if item and item not in seen:
                seen[item] = None
        return list(seen.keys())

    @staticmethod
    def _extract_order_id(order: Any) -> Optional[Any]:
        if not isinstance(order, dict):
            return None
        if "id" in order:
            return order["id"]
        info = order.get("info")
        if isinstance(info, dict):
            for key in ("orderId", "order_id", "id"):
                if key in info:
                    return info[key]
        for key in ("orderId", "order_id"):
            if key in order:
                return order[key]
        return None

    @classmethod
    def _collect_errors(cls, payload: Any, label: str) -> List[str]:
        if payload is None:
            return []
        errors: List[str] = []
        if isinstance(payload, dict):
            status = payload.get("status")
            if isinstance(status, str):
                status_lower = status.lower()
                if status_lower in {"rejected", "expired", "canceled", "cancelled", "error"}:
                    errors.append(f"{label}: status={status}")
            info = payload.get("info") or {}
            if isinstance(info, dict):
                message = info.get("msg") or info.get("message")
                code = info.get("code")
                if message:
                    if code not in (None, "0", 0):
                        errors.append(f"{label}: {code} {message}".strip())
                    else:
                        errors.append(f"{label}: {message}")
        else:
            text = str(payload).strip()
            if text:
                errors.append(f"{label}: {text}")
        return cls._deduplicate_errors(errors)

    def place_entry(
        self,
        coin: str,
        side: str,
        size: float,
        entry_price: Optional[float],
        stop_loss_price: Optional[float],
        take_profit_price: Optional[float],
        leverage: float,
        liquidity: str,
        **kwargs: Any,
    ) -> EntryResult:
        symbol = kwargs.get("symbol") or f"{coin}USDT"
        order_side = "buy" if side.lower() == "long" else "sell"

        raw: Any = {}
        errors: List[str] = []

        try:
            try:
                leverage_int = int(leverage)
                self._exchange.set_leverage(leverage_int, symbol)
            except Exception as exc:  # noqa: BLE001
                logging.warning(
                    "Failed to set leverage %s for %s on Binance futures: %s",
                    leverage,
                    symbol,
                    exc,
                )

            params: Dict[str, Any] = {
                "positionSide": "LONG" if side.lower() == "long" else "SHORT",
            }

            raw = self._exchange.create_order(
                symbol=symbol,
                type="market",
                side=order_side,
                amount=size,
                params=params,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Binance futures live entry failed: %s", coin, exc)
            raw = {"status": "error", "exception": str(exc)}
            errors.append(f"entry: {exc}")

        if not errors:
            errors.extend(self._collect_errors(raw, "entry"))

        success = not errors
        if isinstance(raw, dict):
            status = raw.get("status")
            if isinstance(status, str):
                status_lower = status.lower()
                if status_lower in {"rejected", "expired", "canceled", "cancelled", "error"}:
                    success = False

        if not success and not errors:
            errors.append("Binance futures entry order was not accepted; see raw payload for details.")

        return EntryResult(
            success=success,
            backend="binance_futures",
            errors=self._deduplicate_errors(errors),
            entry_oid=self._extract_order_id(raw),
            raw=raw,
            extra={
                "order": raw,
                "symbol": symbol,
                "side": order_side,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
            },
        )

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **kwargs: Any,
    ) -> CloseResult:
        symbol = kwargs.get("symbol") or f"{coin}USDT"
        amount = size if size is not None else 0.0
        order_side = "sell" if side.lower() == "long" else "buy"

        raw: Any = {}
        errors: List[str] = []

        if amount <= 0:
            return CloseResult(
                success=True,
                backend="binance_futures",
                errors=[],
                close_oid=None,
                raw=None,
                extra={"reason": "no position size to close"},
            )

        try:
            params: Dict[str, Any] = {
                "reduceOnly": True,
                "positionSide": "LONG" if side.lower() == "long" else "SHORT",
            }
            try:
                raw = self._exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=order_side,
                    amount=amount,
                    params=params,
                )
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if "-1106" in message and "reduceonly" in message.lower():
                    logging.warning(
                        "%s: Binance futures close failed due to reduceOnly parameter; retrying without reduceOnly.",
                        coin,
                    )
                    fallback_params: Dict[str, Any] = {
                        "positionSide": "LONG" if side.lower() == "long" else "SHORT",
                    }
                    raw = self._exchange.create_order(
                        symbol=symbol,
                        type="market",
                        side=order_side,
                        amount=amount,
                        params=fallback_params,
                    )
                else:
                    raise
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: Binance futures live close failed: %s", coin, exc)
            raw = {"status": "error", "exception": str(exc)}
            errors.append(f"close: {exc}")

        if not errors:
            errors.extend(self._collect_errors(raw, "close"))

        success = not errors
        if isinstance(raw, dict):
            status = raw.get("status")
            if isinstance(status, str):
                status_lower = status.lower()
                if status_lower in {"rejected", "expired", "canceled", "cancelled", "error"}:
                    success = False

        if not success and not errors:
            errors.append("Binance futures close order was not accepted; see raw payload for details.")

        return CloseResult(
            success=success,
            backend="binance_futures",
            errors=self._deduplicate_errors(errors),
            close_oid=self._extract_order_id(raw),
            raw=raw,
            extra={
                "order": raw,
                "symbol": symbol,
                "fallback_price": fallback_price,
            },
        )
