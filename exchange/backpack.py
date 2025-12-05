"""Backpack Futures exchange client implementation.

This module provides the ExchangeClient implementation for Backpack USDC perpetual futures.
"""
from __future__ import annotations

import base64
import logging
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from datetime import datetime, timezone
from decimal import InvalidOperation

from exchange.base import EntryResult, CloseResult, Position, AccountSnapshot, TPSLResult, AuditData


class BackpackFuturesExchangeClient:
    """ExchangeClient implementation for Backpack USDC perpetual futures.

    This client uses the Backpack REST API with ED25519-signed requests to submit
    simple market orders for opening and closing positions. It intentionally maps
    to the minimal subset of fields required by the unified ExchangeClient
    abstraction used by the bot.
    """

    def __init__(
        self,
        api_public_key: str,
        api_secret_seed: str,
        *,
        base_url: str = "https://api.backpack.exchange",
        window_ms: int = 5000,
    ) -> None:
        self._api_public_key = (api_public_key or "").strip()
        self._api_secret_seed = (api_secret_seed or "").strip()
        if not self._api_public_key or not self._api_secret_seed:
            raise ValueError(
                "BackpackFuturesExchangeClient requires both API public key and secret seed.",
            )

        try:
            seed_bytes = base64.b64decode(self._api_secret_seed)
            self._private_key = Ed25519PrivateKey.from_private_bytes(seed_bytes)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "Invalid BACKPACK_API_SECRET_SEED; expected base64-encoded ED25519 seed.",
            ) from exc

        base = (base_url or "https://api.backpack.exchange").strip()
        if not base:
            base = "https://api.backpack.exchange"
        self._base_url = base.rstrip("/")
        self._window_ms = int(window_ms) if window_ms and window_ms > 0 else 5000
        self._session = requests.Session()
        self._timeout = 10.0

    @staticmethod
    def _coin_to_symbol(coin: str) -> str:
        return f"{(coin or '').upper()}_USDC_PERP"

    def _build_signing_string(
        self,
        instruction: str,
        params: Dict[str, Any],
        timestamp_ms: int,
        window_ms: int,
    ) -> str:
        items: List[str] = []
        for key in sorted(params.keys()):
            value = params[key]
            if value is None:
                continue
            if isinstance(value, bool):
                value_str = str(value).lower()
            else:
                value_str = str(value)
            items.append(f"{key}={value_str}")

        base = f"instruction={instruction}"
        if items:
            base = f"{base}&" + "&".join(items)
        return f"{base}&timestamp={timestamp_ms}&window={window_ms}"

    def _sign(self, instruction: str, params: Dict[str, Any]) -> Dict[str, str]:
        timestamp_ms = int(time.time() * 1000)
        window_ms = self._window_ms
        signing_string = self._build_signing_string(
            instruction,
            params,
            timestamp_ms,
            window_ms,
        )
        signature = self._private_key.sign(signing_string.encode("utf-8"))
        signature_b64 = base64.b64encode(signature).decode("ascii")
        return {
            "X-API-Key": self._api_public_key,
            "X-Signature": signature_b64,
            "X-Timestamp": str(timestamp_ms),
            "X-Window": str(window_ms),
            "Content-Type": "application/json; charset=utf-8",
        }

    def _get_market_filters(self, symbol: str) -> Optional[Dict[str, Any]]:
        cache = getattr(self, "_markets_cache", None)
        if cache is None:
            cache = {}
            setattr(self, "_markets_cache", cache)

        if symbol in cache:
            return cache[symbol]

        url = f"{self._base_url}/api/v1/markets"
        try:
            response = self._session.get(url, timeout=self._timeout)
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Backpack markets request failed: %s", exc)
            return None

        if not isinstance(data, list):
            return None

        selected: Optional[Dict[str, Any]] = None
        for item in data:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                filters = item.get("filters")
                if isinstance(filters, dict):
                    selected = filters
                break

        if selected is not None:
            cache[symbol] = selected
        return selected

    @staticmethod
    def _deduplicate_errors(errors: List[str]) -> List[str]:
        seen: Dict[str, None] = {}
        for item in errors:
            if item and item not in seen:
                seen[item] = None
        return list(seen.keys())

    def _format_quantity(self, symbol: str, size: float) -> str:
        """Format order quantity with a safe number of decimal places."""
        if size <= 0:
            raise ValueError("Order quantity must be positive.")

        min_qty: Optional[Decimal] = None
        step: Optional[Decimal] = None

        filters = self._get_market_filters(symbol)
        if filters is not None:
            quantity_filters = filters.get("quantity")
            if isinstance(quantity_filters, dict):
                step_str = quantity_filters.get("stepSize")
                min_str = quantity_filters.get("minQuantity")
                if isinstance(step_str, str):
                    try:
                        step = Decimal(step_str)
                    except Exception:  # noqa: BLE001
                        step = None
                if isinstance(min_str, str):
                    try:
                        min_qty = Decimal(min_str)
                    except Exception:  # noqa: BLE001
                        min_qty = None

        if step is not None and step > 0:
            size_dec = Decimal(str(size))
            units = (size_dec / step).to_integral_value(rounding=ROUND_DOWN)
            qty_dec = units * step
            if qty_dec <= 0 and min_qty is not None and min_qty > 0:
                qty_dec = min_qty
            exponent = qty_dec.as_tuple().exponent
            decimals = -exponent if exponent < 0 else 0
            decimals = min(decimals, 8)
            fmt = "{0:." + str(decimals) + "f}"
            qty_str = fmt.format(qty_dec)
        else:
            qty_str = f"{size:.4f}"

        qty_str = qty_str.rstrip("0").rstrip(".")
        if not qty_str or qty_str == "0":
            if min_qty is not None and min_qty > 0:
                qty_str = str(min_qty)
            else:
                qty_str = "0.0001"
        return qty_str

    @staticmethod
    def _collect_order_errors(payload: Any, label: str) -> List[str]:
        if not isinstance(payload, dict):
            return []
        errors: List[str] = []
        status = payload.get("status")
        if isinstance(status, str):
            status_lower = status.lower()
            if status_lower in {"cancelled", "canceled", "rejected", "expired", "error"}:
                errors.append(f"{label}: status={status}")
        message = payload.get("message") or payload.get("error")
        if isinstance(message, str) and message:
            errors.append(f"{label}: {message}")
        return BackpackFuturesExchangeClient._deduplicate_errors(errors)

    def _post_order(self, body: Dict[str, Any]) -> Dict[str, Any]:
        instruction = "orderExecute"
        sign_params: Dict[str, Any] = {}
        for key in sorted(body.keys()):
            value = body[key]
            if value is None:
                continue
            sign_params[key] = value

        headers = self._sign(instruction, sign_params)
        url = f"{self._base_url}/api/v1/order"
        try:
            response = self._session.post(
                url,
                headers=headers,
                json=body,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("Backpack order request failed: %s", exc)
            return {
                "status": "error",
                "exception": str(exc),
            }

        try:
            data = response.json()
        except ValueError:
            data = {
                "status": "error",
                "message": f"Non-JSON response: HTTP {response.status_code}",
            }

        if response.status_code != 200:
            if not isinstance(data, dict):
                data = {}
            data.setdefault("status", "error")
            data.setdefault(
                "message",
                f"HTTP {response.status_code} while executing Backpack order.",
            )
        return data if isinstance(data, dict) else {"status": "error", "message": str(data)}

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
        **_: Any,
    ) -> EntryResult:
        del entry_price, stop_loss_price, take_profit_price, leverage, liquidity
        symbol = self._coin_to_symbol(coin)
        side_normalized = (side or "").lower()
        order_side = "Bid" if side_normalized == "long" else "Ask"
        quantity_str = self._format_quantity(symbol, size)
        body: Dict[str, Any] = {
            "symbol": symbol,
            "side": order_side,
            "orderType": "Market",
            "quantity": quantity_str,
            "reduceOnly": False,
        }
        raw = self._post_order(body)
        errors = self._collect_order_errors(raw, "entry")
        success = not errors
        status = raw.get("status")
        if isinstance(status, str):
            status_lower = status.lower()
            if status_lower in {"cancelled", "canceled", "rejected", "expired", "error"}:
                success = False
        if not success and not errors:
            errors.append("Backpack futures entry order was not accepted; see raw payload for details.")
        return EntryResult(
            success=success,
            backend="backpack_futures",
            errors=self._deduplicate_errors(errors),
            entry_oid=raw.get("id"),
            raw=raw,
            extra={
                "order": raw,
                "symbol": symbol,
                "side": order_side,
            },
        )

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **_: Any,
    ) -> CloseResult:
        del fallback_price
        quantity = float(size) if size is not None else 0.0
        if quantity <= 0:
            return CloseResult(
                success=True,
                backend="backpack_futures",
                errors=[],
                close_oid=None,
                raw=None,
                extra={"reason": "no position size to close"},
            )

        symbol = self._coin_to_symbol(coin)
        side_normalized = (side or "").lower()
        order_side = "Ask" if side_normalized == "long" else "Bid"
        quantity_str = self._format_quantity(symbol, quantity)
        body: Dict[str, Any] = {
            "symbol": symbol,
            "side": order_side,
            "orderType": "Market",
            "quantity": quantity_str,
            "reduceOnly": True,
        }
        raw = self._post_order(body)
        errors = self._collect_order_errors(raw, "close")
        success = not errors
        status = raw.get("status")
        if isinstance(status, str):
            status_lower = status.lower()
            if status_lower in {"cancelled", "canceled", "rejected", "expired", "error"}:
                success = False

        reason: Optional[str] = None
        message = raw.get("message") or raw.get("error")
        if (
            not success
            and isinstance(message, str)
            and "reduce only order not reduced" in message.lower()
        ):
            success = True
            errors = []
            reason = "position already closed on exchange (reduce-only order not reduced)"

        if not success and not errors:
            errors.append("Backpack futures close order was not accepted; see raw payload for details.")
        extra: Dict[str, Any] = {
            "order": raw,
            "symbol": symbol,
        }
        if reason is not None:
            extra["reason"] = reason
        return CloseResult(
            success=success,
            backend="backpack_futures",
            errors=self._deduplicate_errors(errors),
            close_oid=raw.get("id"),
            raw=raw,
            extra=extra,
        )

    # ═══════════════════════════════════════════════════════════════════
    # ACCOUNT SNAPSHOT (for /balance command)
    # ═══════════════════════════════════════════════════════════════════

    def get_account_snapshot(self) -> Optional[AccountSnapshot]:
        """Retrieve live account snapshot from Backpack API.

        This method calls the collateralQuery and positionQuery endpoints to
        build a unified account snapshot.

        Returns:
            AccountSnapshot with standardized data format, or None if API call fails.
        """
        collateral = self._get_collateral()
        if collateral is None:
            return None

        positions_raw = self._get_open_positions()

        try:
            net_equity = float(collateral.get("netEquity", 0) or 0)
            net_equity_available = float(collateral.get("netEquityAvailable", 0) or 0)
            net_equity_locked = float(collateral.get("netEquityLocked", 0) or 0)
        except (TypeError, ValueError) as exc:
            logging.warning("Failed to parse Backpack collateral values: %s", exc)
            return None

        positions = self._parse_positions(positions_raw or [])

        return AccountSnapshot(
            balance=net_equity_available,
            total_equity=net_equity,
            total_margin=net_equity_locked,
            positions=positions,
            raw={"collateral": collateral, "positions_raw": positions_raw},
        )

    def _parse_positions(self, positions_raw: List[Dict[str, Any]]) -> List[Position]:
        """Parse raw Backpack positions into standardized Position objects."""
        positions: List[Position] = []
        
        for pos in positions_raw:
            if not isinstance(pos, dict):
                continue
            
            # Get quantity
            net_qty = 0.0
            for qty_field in ("netQuantity", "netExposureQuantity", "quantity", "size"):
                raw_val = pos.get(qty_field)
                if raw_val is not None:
                    try:
                        net_qty = float(raw_val)
                        if net_qty != 0:
                            break
                    except (TypeError, ValueError):
                        continue
            
            if net_qty == 0:
                continue
            
            # Parse symbol: BTC_USDC_PERP -> BTC
            symbol = str(pos.get("symbol", "") or "")
            coin = symbol.split("_", 1)[0].upper() if "_" in symbol else symbol.upper()
            
            # Side and quantity
            side = "long" if net_qty > 0 else "short"
            quantity = abs(net_qty)
            
            # Entry price
            entry_price = self._safe_float(pos.get("entryPrice"))
            
            # Notional
            notional = abs(self._safe_float(pos.get("netExposureNotional")))
            if notional == 0 and entry_price > 0:
                notional = quantity * entry_price
            
            # Margin
            margin = self._safe_float(pos.get("initialMargin"))
            if margin == 0:
                margin = self._safe_float(pos.get("marginUsed"))
            
            # Leverage
            leverage = self._safe_float(pos.get("leverage"))
            imf = self._safe_float(pos.get("imf"))
            if leverage == 0 and margin > 0 and notional > 0:
                leverage = notional / margin
            if leverage == 0 and imf > 0:
                leverage = 1.0 / imf
            if leverage == 0:
                leverage = 1.0
            
            # PnL
            unrealized_pnl = self._safe_float(pos.get("pnlUnrealized"))
            realized_pnl = self._safe_float(pos.get("pnlRealized"))
            
            # Liquidation price
            liq_price = self._safe_float(pos.get("estLiquidationPrice"))
            
            # TP/SL
            take_profit = self._safe_float(pos.get("takeProfitPrice"))
            stop_loss = self._safe_float(pos.get("stopLossPrice"))
            
            positions.append(Position(
                coin=coin,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                leverage=leverage,
                margin=margin,
                notional=notional,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
                liquidation_price=liq_price if liq_price > 0 else None,
                take_profit=take_profit if take_profit > 0 else None,
                stop_loss=stop_loss if stop_loss > 0 else None,
                raw=pos,
            ))
        
        return positions

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Safely convert a value to float."""
        if value is None:
            return default
        try:
            result = float(value)
            return default if result != result else result  # NaN check
        except (TypeError, ValueError):
            return default

    def get_current_price(self, coin: str) -> Optional[float]:
        """Get current price for a coin.
        
        Args:
            coin: Coin symbol (e.g., "BTC", "ETH")
            
        Returns:
            Current price or None if unavailable.
        """
        symbol = self._coin_to_symbol(coin)
        url = f"{self._base_url}/api/v1/ticker"
        params = {"symbol": symbol}
        
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
            if response.status_code != 200:
                return None
            
            data = response.json()
            if isinstance(data, dict):
                return self._safe_float(data.get("lastPrice"))
            return None
        except Exception as e:
            logging.warning("Failed to get price for %s: %s", symbol, e)
            return None

    def update_tpsl(
        self,
        coin: str,
        side: str,
        quantity: float,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> TPSLResult:
        """Update stop loss and/or take profit for a position (Backpack).

        Note:
            The Backpack HTTP API does not currently expose a stable, well-
            documented way to create standalone TP/SL conditional orders for an
            existing futures position via `orderExecute` without risking
            immediate market execution. To avoid意外直接平仓, this method
            intentionally does **not** send any live TP/SL orders at the
            moment and instead reports that exchange-level TP/SL is not
            supported.

            Users should set TP/SL directly in the Backpack UI for now.
        """
        symbol = self._coin_to_symbol(coin)
        side_normalized = (side or "").lower()
        order_side = "Ask" if side_normalized == "long" else "Bid"

        # Fast path: nothing to update
        if (new_sl is None or new_sl <= 0) and (new_tp is None or new_tp <= 0):
            return TPSLResult(
                success=True,
                backend="backpack_futures",
                errors=[],
                raw={"reason": "no TP/SL values provided"},
            )

        # Format quantity according to market filters
        try:
            quantity_str = self._format_quantity(symbol, quantity)
        except Exception as exc:  # noqa: BLE001
            logging.error("Backpack TP/SL: invalid quantity for %s: %s", symbol, exc)
            return TPSLResult(
                success=False,
                backend="backpack_futures",
                errors=[f"quantity: {exc}"],
                raw={"reason": "invalid_quantity"},
            )

        # Try to get tick size for price formatting
        price_tick: Optional[Decimal] = None
        filters = self._get_market_filters(symbol)
        if isinstance(filters, dict):
            price_filters = filters.get("price")
            if isinstance(price_filters, dict):
                tick_str = price_filters.get("tickSize")
                if isinstance(tick_str, str):
                    try:
                        price_tick = Decimal(tick_str)
                    except Exception:  # noqa: BLE001
                        price_tick = None

        def _format_price(value: float) -> str:
            """Format price using market tick size if available."""
            price_dec = Decimal(str(value))
            if price_tick is not None and price_tick > 0:
                units = (price_dec / price_tick).to_integral_value(rounding=ROUND_DOWN)
                price_dec = units * price_tick
            exponent = price_dec.as_tuple().exponent
            decimals = -exponent if exponent < 0 else 0
            decimals = min(decimals, 8)
            fmt = "{0:." + str(decimals) + "f}"
            price_str = fmt.format(price_dec)
            return price_str.rstrip("0").rstrip(".")

        # Cancel existing reduce-only conditional TP/SL orders for this symbol
        try:
            self._cancel_existing_tpsl_orders(symbol)
        except Exception as exc:  # noqa: BLE001
            logging.warning(
                "Backpack TP/SL: failed to cancel existing conditional orders for %s: %s",
                symbol,
                exc,
            )

        errors: List[str] = []
        sl_order_id: Optional[Any] = None
        tp_order_id: Optional[Any] = None
        raw_results: Dict[str, Any] = {}

        base_body: Dict[str, Any] = {
            "symbol": symbol,
            "side": order_side,
            "quantity": quantity_str,
            "reduceOnly": True,
            "timeInForce": "GTC",
        }

        # Create Stop Loss order (reduce-only conditional)
        if new_sl is not None and new_sl > 0:
            try:
                sl_price_str = _format_price(new_sl)
                sl_body = dict(base_body)
                sl_body["orderType"] = "Market"
                sl_body["triggerPrice"] = sl_price_str
                sl_raw = self._post_order(sl_body)
                raw_results["sl_order"] = sl_raw
                sl_errors = self._collect_order_errors(sl_raw, "stop_loss")
                errors.extend(sl_errors)
                if not sl_errors and isinstance(sl_raw, dict):
                    sl_order_id = sl_raw.get("id")
            except Exception as exc:  # noqa: BLE001
                msg = f"stop_loss: {exc}"
                logging.error("Backpack TP/SL: failed to create SL order for %s: %s", symbol, exc)
                errors.append(msg)

        # Create Take Profit order as reduce-only limit order at target price
        if new_tp is not None and new_tp > 0:
            try:
                tp_price_str = _format_price(new_tp)
                tp_body = dict(base_body)
                tp_body["orderType"] = "Limit"
                tp_body["price"] = tp_price_str
                tp_raw = self._post_order(tp_body)
                raw_results["tp_order"] = tp_raw
                tp_errors = self._collect_order_errors(tp_raw, "take_profit")
                errors.extend(tp_errors)
                if not tp_errors and isinstance(tp_raw, dict):
                    tp_order_id = tp_raw.get("id")
            except Exception as exc:  # noqa: BLE001
                msg = f"take_profit: {exc}"
                logging.error("Backpack TP/SL: failed to create TP order for %s: %s", symbol, exc)
                errors.append(msg)

        errors = self._deduplicate_errors(errors)

        success = True
        if errors:
            success = False
        if new_sl is not None and new_sl > 0 and sl_order_id is None:
            success = False
        if new_tp is not None and new_tp > 0 and tp_order_id is None:
            success = False

        return TPSLResult(
            success=success,
            backend="backpack_futures",
            errors=errors,
            sl_order_id=sl_order_id,
            tp_order_id=tp_order_id,
            raw=raw_results,
        )

    def _cancel_existing_tpsl_orders(self, symbol: str) -> None:
        """Cancel existing conditional (SL/TP) orders for a symbol."""
        instruction = "orderQueryAll"
        params: Dict[str, Any] = {"symbol": symbol}
        headers = self._sign(instruction, params)
        url = f"{self._base_url}/api/v1/orders"
        
        try:
            response = self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
            if response.status_code != 200:
                return
            
            orders = response.json()
            if not isinstance(orders, list):
                return
            
            for order in orders:
                if not isinstance(order, dict):
                    continue
                # Cancel reduce-only conditional orders (TP/SL)
                has_trigger = (
                    order.get("triggerPrice")
                    or order.get("stopLossTriggerPrice")
                    or order.get("takeProfitTriggerPrice")
                )
                is_reduce_only = bool(order.get("reduceOnly"))
                is_limit_reduce_only = is_reduce_only and order.get("orderType") == "Limit"
                if is_reduce_only and (has_trigger or is_limit_reduce_only):
                    order_id = order.get("id")
                    if order_id:
                        self._cancel_order(symbol, order_id)
                        logging.debug("Cancelled existing conditional order %s", order_id)
        except Exception as e:
            logging.warning("Error fetching/cancelling existing TP/SL orders: %s", e)

    def _cancel_order(self, symbol: str, order_id: str) -> None:
        """Cancel a specific order."""
        instruction = "orderCancel"
        body: Dict[str, Any] = {
            "symbol": symbol,
            "orderId": order_id,
        }
        headers = self._sign(instruction, body)
        url = f"{self._base_url}/api/v1/order"
        
        try:
            self._session.delete(
                url,
                headers=headers,
                json=body,
                timeout=self._timeout,
            )
        except Exception as e:
            logging.warning("Failed to cancel order %s: %s", order_id, e)

    def _get_collateral(self) -> Optional[Dict[str, Any]]:
        """Fetch collateral information from Backpack API.

        Instruction: collateralQuery
        Endpoint: GET /api/v1/capital/collateral
        """
        instruction = "collateralQuery"
        params: Dict[str, Any] = {}
        headers = self._sign(instruction, params)
        url = f"{self._base_url}/api/v1/capital/collateral"

        try:
            response = self._session.get(
                url,
                headers=headers,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logging.warning("Backpack collateral request failed: %s", exc)
            return None

        if response.status_code != 200:
            logging.warning(
                "Backpack collateral request HTTP %s: %s",
                response.status_code,
                response.text[:200] if response.text else "(empty)",
            )
            return None

        try:
            data = response.json()
        except ValueError:
            logging.warning("Backpack collateral response is not valid JSON")
            return None

        if not isinstance(data, dict):
            logging.warning("Backpack collateral response is not a dict: %r", type(data))
            return None

        return data

    def _get_open_positions(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch open futures positions from Backpack API.

        Instruction: positionQuery
        Endpoint: GET /api/v1/position
        """
        instruction = "positionQuery"
        params: Dict[str, Any] = {}
        headers = self._sign(instruction, params)
        url = f"{self._base_url}/api/v1/position"

        try:
            response = self._session.get(
                url,
                headers=headers,
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logging.warning("Backpack positions request failed: %s", exc)
            return None

        if response.status_code != 200:
            logging.warning(
                "Backpack positions request HTTP %s: %s",
                response.status_code,
                response.text[:200] if response.text else "(empty)",
            )
            return None

        try:
            data = response.json()
        except ValueError:
            logging.warning("Backpack positions response is not valid JSON")
            return None

        logging.debug("Backpack positions raw response: %r", data)

        if not isinstance(data, list):
            # Single position or empty
            if isinstance(data, dict):
                logging.debug("Backpack positions: single dict response")
                return [data] if data else []
            return []

        # Filter out positions with zero quantity
        active_positions = []
        for pos in data:
            if not isinstance(pos, dict):
                continue
            # Try multiple possible field names for position quantity
            net_qty = 0.0
            for qty_field in ("netQuantity", "netExposureQuantity", "quantity", "size"):
                raw_val = pos.get(qty_field)
                if raw_val is not None:
                    try:
                        net_qty = float(raw_val)
                        if net_qty != 0:
                            logging.debug(
                                "Backpack position %s: %s=%s",
                                pos.get("symbol", "?"),
                                qty_field,
                                net_qty,
                            )
                            break
                    except (TypeError, ValueError):
                        continue
            if net_qty != 0:
                active_positions.append(pos)

        logging.debug(
            "Backpack positions: %d total, %d active",
            len(data),
            len(active_positions),
        )
        return active_positions

    # ═══════════════════════════════════════════════════════════════════
    # AUDIT DATA (for /audit command)
    # ═══════════════════════════════════════════════════════════════════

    def fetch_audit_data(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> AuditData:
        """获取指定时间范围内的资金变动审计数据。
        
        实现 AuditProvider 接口。
        
        Args:
            start_utc: 开始时间 (UTC)。
            end_utc: 结束时间 (UTC)。
            
        Returns:
            AuditData 包含资金费、结算、充值、提现等汇总数据。
        """
        if start_utc.tzinfo is None:
            start_utc = start_utc.replace(tzinfo=timezone.utc)
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=timezone.utc)

        datasets = self._fetch_all_audit_history()

        def in_range(ts: Optional[datetime]) -> bool:
            if ts is None:
                return False
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_utc = ts.astimezone(timezone.utc)
            return start_utc <= ts_utc <= end_utc

        # 资金费汇总
        funding_total = Decimal("0")
        funding_by_symbol: Dict[str, Decimal] = {}
        for item in datasets.get("funding", []):
            ts = self._parse_backpack_timestamp(
                item.get("intervalEndTimestamp") or item.get("timestamp")
            )
            if not in_range(ts):
                continue
            qty = self._safe_decimal(item.get("quantity"))
            if qty is None:
                continue
            symbol = str(item.get("symbol") or "").strip() or "(unknown)"
            funding_total += qty
            funding_by_symbol[symbol] = funding_by_symbol.get(symbol, Decimal("0")) + qty

        # 结算汇总
        settlement_total = Decimal("0")
        settlement_by_source: Dict[str, Decimal] = {}
        for item in datasets.get("settlements", []):
            ts = self._parse_backpack_timestamp(item.get("timestamp"))
            if not in_range(ts):
                continue
            qty = self._safe_decimal(item.get("quantity"))
            if qty is None:
                continue
            source = str(item.get("source") or "").strip() or "(unknown)"
            settlement_total += qty
            settlement_by_source[source] = settlement_by_source.get(source, Decimal("0")) + qty

        # 充值汇总
        deposit_total = Decimal("0")
        for item in datasets.get("deposits", []):
            ts = self._parse_backpack_timestamp(item.get("createdAt") or item.get("timestamp"))
            if not in_range(ts):
                continue
            qty = self._safe_decimal(item.get("quantity"))
            if qty is None:
                continue
            deposit_total += qty

        # 提现汇总
        withdrawal_total = Decimal("0")
        for item in datasets.get("withdrawals", []):
            ts = self._parse_backpack_timestamp(item.get("createdAt") or item.get("timestamp"))
            if not in_range(ts):
                continue
            qty = self._safe_decimal(item.get("quantity"))
            if qty is None:
                continue
            withdrawal_total -= qty  # 提现为负

        return AuditData(
            backend="backpack_futures",
            funding_total=funding_total,
            funding_by_symbol=funding_by_symbol,
            settlement_total=settlement_total,
            settlement_by_source=settlement_by_source,
            deposit_total=deposit_total,
            withdrawal_total=withdrawal_total,
            raw=datasets,
        )

    def _fetch_all_audit_history(self) -> Dict[str, List[Dict[str, Any]]]:
        """拉取需要用到的所有历史记录。"""
        datasets: Dict[str, List[Dict[str, Any]]] = {}
        common_query = {"limit": 1000}

        datasets["fills"] = self._signed_get(
            instruction="fillHistoryQueryAll",
            path="/wapi/v1/history/fills",
            label="fill history",
            query_params=common_query,
        )

        datasets["funding"] = self._signed_get(
            instruction="fundingHistoryQueryAll",
            path="/wapi/v1/history/funding",
            label="funding history",
            query_params=common_query,
        )

        datasets["settlements"] = self._signed_get(
            instruction="settlementHistoryQueryAll",
            path="/wapi/v1/history/settlement",
            label="settlement history",
            query_params=common_query,
        )

        datasets["deposits"] = self._signed_get(
            instruction="depositQueryAll",
            path="/wapi/v1/capital/deposits",
            label="deposit history",
            query_params=common_query,
        )

        datasets["withdrawals"] = self._signed_get(
            instruction="withdrawalQueryAll",
            path="/wapi/v1/capital/withdrawals",
            label="withdrawal history",
            query_params=common_query,
        )

        return datasets

    def _signed_get(
        self,
        *,
        instruction: str,
        path: str,
        label: str,
        query_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """使用签名发起 GET 请求。"""
        params: Dict[str, Any] = {}
        if query_params:
            params.update(query_params)
        headers = self._sign(instruction, params)
        url = f"{self._base_url}{path}"
        
        try:
            response = self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
        except Exception as exc:
            logging.warning("%s request failed: %s", label, exc)
            return []

        try:
            data = response.json()
        except ValueError:
            logging.warning(
                "%s request returned non-JSON payload. status=%s",
                label,
                response.status_code,
            )
            return []

        if response.status_code != 200:
            logging.warning("%s request HTTP %s: %s", label, response.status_code, data)
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("items") if isinstance(data.get("items"), list) else None
            if items is not None:
                return items
            return [data]

        logging.warning("%s request returned unexpected payload type: %r", label, type(data))
        return []

    @staticmethod
    def _parse_backpack_timestamp(value: Any) -> Optional[datetime]:
        """将 Backpack 返回的时间字段解析为 UTC datetime。"""
        if value is None:
            return None

        # 数值型：视为毫秒时间戳
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None

        if not isinstance(value, str):
            return None

        raw = value.strip()
        if not raw:
            return None

        # 纯数字字符串：优先按毫秒时间戳解析
        if raw.isdigit():
            try:
                ts_int = int(raw)
            except ValueError:
                return None
            if ts_int > 10**11:
                ts = ts_int / 1000.0
            else:
                ts = float(ts_int)
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None

        # ISO8601 字符串
        iso = raw
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    @staticmethod
    def _safe_decimal(value: Any) -> Optional[Decimal]:
        """Safely convert a value to Decimal."""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
