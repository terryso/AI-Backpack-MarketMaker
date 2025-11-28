from __future__ import annotations

import base64
import json
import logging
import time

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING, runtime_checkable

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@dataclass(slots=True)
class EntryResult:
    """统一的开仓结果结构，用于抽象不同交易所返回的数据。

    Attributes:
        success: 本次请求在交易所侧是否被接受并处于有效/已成交状态。
        backend: 后端标识，例如 "hyperliquid"、"binance_futures" 等。
        errors: 面向用户/开发者的高层错误摘要列表；成功时应为空。
        entry_oid: 主要开仓订单 ID（如有）。
        tp_oid: 关联的止盈订单 ID（如有）。
        sl_oid: 关联的止损订单 ID（如有）。
        raw: 交易所 SDK / REST 客户端返回的原始数据，用于 debug 与扩展。
        extra: 预留的扩展字段字典，用于承载 backend 特有但对上层仍有价值的信息
               （如状态码、撮合细节等），不在统一 schema 中强制规范。
    """

    success: bool
    backend: str
    errors: List[str]
    entry_oid: Optional[Any] = None
    tp_oid: Optional[Any] = None
    sl_oid: Optional[Any] = None
    raw: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CloseResult:
    """统一的平仓结果结构，与 EntryResult 保持语义一致。"""

    success: bool
    backend: str
    errors: List[str]
    close_oid: Optional[Any] = None
    raw: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExchangeClient(Protocol):
    """统一的交易执行抽象接口（Exchange Execution Layer）。

    本接口对应 `docs/epics.md` 中 Epic 6 / Story 6.1 所要求的 ExchangeClient 抽象：
    为 Bot 主循环和策略层提供与具体交易所无关的开仓 / 平仓调用方式。
    """

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
        """提交开仓请求，并在可能的情况下附带止损 / 止盈。

        参数语义需与 Story 6.1 / PRD 4.1/4.2 中对风控与执行行为的约束保持一致，
        但具体撮合细节与特殊参数由各 backend 在 **kwargs 中自行扩展实现。
        """

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **kwargs: Any,
    ) -> CloseResult:
        """提交平仓请求。

        size 省略时表示「全仓平掉当前在该 backend 上的持仓」；
        fallback_price 仅作为在无法从订单簿获取合理价格时的兜底输入，
        是否以及如何使用由具体 backend 决定。
        """


if TYPE_CHECKING:
    from hyperliquid_client import HyperliquidTradingClient


class HyperliquidExchangeClient:
    def __init__(self, trader: "HyperliquidTradingClient") -> None:  # type: ignore[name-defined]
        self._trader = trader

    @staticmethod
    def _extract_statuses(payload: Any) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        response = payload.get("response")
        if isinstance(response, dict):
            data = response.get("data")
            if isinstance(data, dict):
                statuses = data.get("statuses")
                if isinstance(statuses, list):
                    return [
                        status
                        for status in statuses
                        if isinstance(status, dict)
                    ]
        statuses = payload.get("statuses")
        if isinstance(statuses, list):
            return [status for status in statuses if isinstance(status, dict)]
        return []

    @classmethod
    def _collect_errors(cls, payload: Any, label: str) -> List[str]:
        if not isinstance(payload, dict):
            return []
        errors: List[str] = []
        for status in cls._extract_statuses(payload):
            message = status.get("error")
            if isinstance(message, str) and message:
                errors.append(f"{label}: {message}")
        status_value = payload.get("status")
        if isinstance(status_value, str) and status_value.lower() not in {"ok", "success"}:
            errors.append(f"{label}: status={status_value}")
        exception_text = payload.get("exception") or payload.get("message")
        if isinstance(exception_text, str) and exception_text:
            errors.append(f"{label}: {exception_text}")
        return errors

    @staticmethod
    def _deduplicate_errors(errors: List[str]) -> List[str]:
        seen: Dict[str, None] = {}
        for item in errors:
            if item and item not in seen:
                seen[item] = None
        return list(seen.keys())

    @staticmethod
    def _format_quantity(size: float) -> str:
        """Format order quantity with a safe number of decimal places.

        Backpack will reject orders when the quantity has too many decimal
        places ("Quantity decimal too long"). To avoid this, we clamp the
        decimal precision to 6 places and strip trailing zeros.
        """

        if size <= 0:
            raise ValueError("Order quantity must be positive.")

        # Format with fixed precision, then strip trailing zeros and dot.
        qty_str = f"{size:.6f}"
        qty_str = qty_str.rstrip("0").rstrip(".")
        if not qty_str or qty_str == "0":
            # Fallback to a minimal positive quantity; the exchange will
            # enforce its own minimum size constraints.
            qty_str = "0.000001"
        return qty_str

    def _build_entry_result(self, raw: Dict[str, Any]) -> EntryResult:
        entry_payload = raw.get("entry_result")
        sl_payload = raw.get("stop_loss_result")
        tp_payload = raw.get("take_profit_result")

        errors: List[str] = []
        errors.extend(self._collect_errors(entry_payload, "entry"))
        errors.extend(self._collect_errors(sl_payload, "stop_loss"))
        errors.extend(self._collect_errors(tp_payload, "take_profit"))

        success = bool(raw.get("success"))
        if not success and not errors:
            errors.append("Hyperliquid order was not accepted; see raw payload for details.")

        return EntryResult(
            success=success,
            backend="hyperliquid",
            errors=self._deduplicate_errors(errors),
            entry_oid=raw.get("entry_oid"),
            tp_oid=raw.get("take_profit_oid"),
            sl_oid=raw.get("stop_loss_oid"),
            raw=raw,
            extra={
                "entry_result": entry_payload,
                "stop_loss_result": sl_payload,
                "take_profit_result": tp_payload,
            },
        )

    def _build_close_result(self, raw: Dict[str, Any]) -> CloseResult:
        close_payload = raw.get("close_result")

        errors: List[str] = []
        errors.extend(self._collect_errors(close_payload, "close"))

        success = bool(raw.get("success"))
        if not success and not errors:
            errors.append("Hyperliquid close order was not accepted; see raw payload for details.")

        return CloseResult(
            success=success,
            backend="hyperliquid",
            errors=self._deduplicate_errors(errors),
            close_oid=raw.get("close_oid"),
            raw=raw,
            extra={"close_result": close_payload},
        )

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
        raw = self._trader.place_entry_with_sl_tp(
            coin=coin,
            side=side,
            size=size,
            entry_price=entry_price if entry_price is not None else 0.0,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            leverage=leverage,
            liquidity=liquidity,
        )
        if not isinstance(raw, dict):
            raw = {"success": False, "entry_result": raw}
        return self._build_entry_result(raw)

    def close_position(
        self,
        coin: str,
        side: str,
        size: Optional[float] = None,
        fallback_price: Optional[float] = None,
        **_: Any,
    ) -> CloseResult:
        raw = self._trader.close_position(
            coin=coin,
            side=side,
            size=size,
            fallback_price=fallback_price,
        )
        if not isinstance(raw, dict):
            raw = {"success": False, "close_result": raw}
        return self._build_close_result(raw)


class BinanceFuturesExchangeClient:
    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange

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
        """Format order quantity with a safe number of decimal places.

        Backpack will reject orders when the quantity has too many decimal
        places ("Quantity decimal too long"). From manual smoke tests, a
        precision of 4 decimal places (e.g. 0.0003) is accepted. To avoid
        rejections, we clamp the decimal precision to 4 places and strip
        trailing zeros.
        """

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
        if not success and not errors:
            errors.append("Backpack futures close order was not accepted; see raw payload for details.")
        return CloseResult(
            success=success,
            backend="backpack_futures",
            errors=self._deduplicate_errors(errors),
            close_oid=raw.get("id"),
            raw=raw,
            extra={
                "order": raw,
                "symbol": symbol,
            },
        )


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
        return HyperliquidExchangeClient(trader)  # type: ignore[arg-type]

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
