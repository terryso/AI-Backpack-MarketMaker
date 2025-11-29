"""Binance Futures exchange client implementation.

This module provides the ExchangeClient implementation for Binance Futures.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from exchange.base import EntryResult, CloseResult


class BinanceFuturesExchangeClient:
    """ExchangeClient implementation for Binance Futures."""
    
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
