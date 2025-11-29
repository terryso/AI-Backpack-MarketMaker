"""Hyperliquid exchange client implementation.

This module provides the ExchangeClient implementation for Hyperliquid.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from exchange.base import EntryResult, CloseResult

if TYPE_CHECKING:
    from hyperliquid_client import HyperliquidTradingClient


class HyperliquidExchangeClient:
    """ExchangeClient implementation for Hyperliquid."""
    
    def __init__(self, trader: "HyperliquidTradingClient") -> None:
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
        """Format order quantity with a safe number of decimal places."""
        if size <= 0:
            raise ValueError("Order quantity must be positive.")
        qty_str = f"{size:.6f}"
        qty_str = qty_str.rstrip("0").rstrip(".")
        if not qty_str or qty_str == "0":
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
