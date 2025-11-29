from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests
from binance.client import Client


# Local interval mapping for Backpack market data lookbacks. This mirrors
# the mapping used in the main bot module so behaviour remains consistent.
_INTERVAL_TO_SECONDS: Dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}


class BinanceMarketDataClient:
    def __init__(self, binance_client: Client) -> None:
        self._client = binance_client

    def get_klines(self, symbol: str, interval: str, limit: int) -> List[List[Any]]:
        return self._client.get_klines(symbol=symbol, interval=interval, limit=limit)

    def get_funding_rate_history(self, symbol: str, limit: int) -> List[float]:
        try:
            hist = self._client.futures_funding_rate(symbol=symbol, limit=limit)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.debug("Funding rate history unavailable for %s: %s", symbol, exc)
            return []
        rates: List[float] = []
        if hist:
            for entry in hist:
                if not isinstance(entry, dict):
                    continue
                value = entry.get("fundingRate")
                try:
                    rates.append(float(value))
                except (TypeError, ValueError):
                    continue
        return rates

    def get_open_interest_history(self, symbol: str, limit: int) -> List[float]:
        try:
            hist = self._client.futures_open_interest_hist(symbol=symbol, period="5m", limit=limit)
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.debug("Open interest history unavailable for %s: %s", symbol, exc)
            return []
        values: List[float] = []
        if hist:
            for entry in hist:
                if not isinstance(entry, dict):
                    continue
                value = entry.get("sumOpenInterest")
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
        return values


class BackpackMarketDataClient:
    def __init__(self, base_url: str) -> None:
        base = (base_url or "https://api.backpack.exchange").strip()
        if not base:
            base = "https://api.backpack.exchange"
        self._base_url = base.rstrip("/")
        self._session = requests.Session()
        self._timeout = 10.0

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        raw = (symbol or "").strip().upper()
        if not raw:
            return raw
        # Already a Backpack-style symbol like BTC_USDC_PERP
        if "_" in raw:
            return raw
        # Common case: Binance-style future/spot symbol like BTCUSDT
        if raw.endswith("USDT") and len(raw) > 4:
            base = raw[:-4]
            return f"{base}_USDC_PERP"
        return raw

    def _get_mark_price_entry(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        url = f"{self._base_url}/api/v1/markPrices"
        params: Dict[str, Any] = {}
        if normalized:
            params["symbol"] = normalized
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
            data = response.json()
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.debug("Backpack markPrices request failed for %s: %s", normalized or symbol, exc)
            return None
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and (not normalized or item.get("symbol") == normalized):
                    return item
        return None

    def get_klines(self, symbol: str, interval: str, limit: int) -> List[List[Any]]:
        normalized = self._normalize_symbol(symbol)
        now_s = int(time.time())
        seconds_per_bar = _INTERVAL_TO_SECONDS.get(interval, 60)
        lookback_seconds = max(limit, 1) * seconds_per_bar
        params: Dict[str, Any] = {
            "symbol": normalized,
            "interval": interval,
            "startTime": now_s - lookback_seconds,
        }
        url = f"{self._base_url}/api/v1/klines"
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
            data = response.json()
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.warning("Backpack klines request failed for %s: %s", symbol, exc)
            return []
        if response.status_code != 200:
            logging.warning(
                "Backpack klines HTTP %s for %s with params %s: %s",
                response.status_code,
                normalized,
                params,
                data,
            )
            return []
        if not isinstance(data, list):
            return []
        rows: List[List[Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            start_val = item.get("start")
            end_val = item.get("end")
            open_val = item.get("open")
            high_val = item.get("high")
            low_val = item.get("low")
            close_val = item.get("close")
            volume_val = item.get("volume")
            quote_volume = item.get("quoteVolume")
            trades = item.get("trades")
            row: List[Any] = [
                start_val,
                open_val,
                high_val,
                low_val,
                close_val,
                volume_val,
                end_val,
                quote_volume,
                trades,
                None,
                None,
                None,
            ]
            rows.append(row)
        return rows

    def get_funding_rate_history(self, symbol: str, limit: int) -> List[float]:
        entry = self._get_mark_price_entry(symbol)
        if not entry:
            return []
        value = entry.get("fundingRate")
        try:
            rate = float(value)
        except (TypeError, ValueError):
            return []
        return [rate]

    def get_open_interest_history(self, symbol: str, limit: int) -> List[float]:
        normalized = self._normalize_symbol(symbol)
        url = f"{self._base_url}/api/v1/openInterest"
        params: Dict[str, Any] = {}
        if normalized:
            params["symbol"] = normalized
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
            data = response.json()
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.debug("Backpack open interest request failed for %s: %s", symbol, exc)
            return []
        items: List[Any]
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            items = []
        values: List[float] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get("openInterest")
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not values:
            return []
        return [values[-1]]
