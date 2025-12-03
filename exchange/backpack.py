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

from exchange.base import EntryResult, CloseResult


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

    def get_account_snapshot(self) -> Optional[Dict[str, Any]]:
        """Retrieve live account snapshot from Backpack API.

        This method calls the collateralQuery and positionQuery endpoints to
        build a unified account snapshot for the /balance Telegram command.

        Returns:
            Dictionary with keys:
            - balance: Available balance (netEquityAvailable from collateral)
            - total_equity: Total account equity (netEquity from collateral)
            - total_margin: Locked equity / margin in use (netEquityLocked)
            - positions_count: Number of open futures positions
            - unrealized_pnl: Unrealized PnL from collateral
            Returns None if API call fails.
        """
        collateral = self._get_collateral()
        if collateral is None:
            return None

        positions = self._get_open_positions()
        positions_count = len(positions) if positions is not None else 0

        try:
            net_equity = float(collateral.get("netEquity", 0) or 0)
            net_equity_available = float(collateral.get("netEquityAvailable", 0) or 0)
            net_equity_locked = float(collateral.get("netEquityLocked", 0) or 0)
            unrealized_pnl = float(collateral.get("pnlUnrealized", 0) or 0)
        except (TypeError, ValueError) as exc:
            logging.warning("Failed to parse Backpack collateral values: %s", exc)
            return None

        return {
            "balance": net_equity_available,
            "total_equity": net_equity,
            "total_margin": net_equity_locked,
            "positions_count": positions_count,
            "unrealized_pnl": unrealized_pnl,
            "positions": positions or [],
        }

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
