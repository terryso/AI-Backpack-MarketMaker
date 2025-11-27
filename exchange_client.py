from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING, runtime_checkable


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

    raise NotImplementedError(
        "Concrete ExchangeClient implementations (e.g. HyperliquidExchangeClient, "
        "BinanceFuturesExchangeClient) are only available for explicitly supported backends."
    )
