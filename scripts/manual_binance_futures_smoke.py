#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manual smoke test for Binance USDT-margined futures via ExchangeClient.

This script is intended for **manual**, small-notional live verification only.
It will place a tiny market order on Binance futures, wait briefly, then
attempt to close the position. You are responsible for your API keys,
position sizes, and risk.

Key properties:
- Uses ccxt `binanceusdm` for USDT-margined futures.
- Can route orders either directly through ccxt or via
  `BinanceFuturesExchangeClient` (ExchangeClient adapter).
- Designed to be run explicitly by a human; DO NOT add to automated tests.

Before running, ensure you have:
- BINANCE_API_KEY / BINANCE_API_SECRET (or BN_API_KEY / BN_SECRET) configured
  in your environment or `.env` at the project root.
- Read and understood the notional, leverage, and side you are using.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Tuple

import ccxt
from dotenv import load_dotenv

# Ensure project root is on sys.path so local modules resolve when script is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from exchange_client import BinanceFuturesExchangeClient


DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_NOTIONAL = Decimal("5")  # ~5 USDT
DEFAULT_LEVERAGE = 1.0
DEFAULT_WAIT_SECONDS = 15


def _parse_decimal(value: str, *, name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"Invalid decimal value for {name}: {value}") from exc


def determine_order_params(
    exchange: ccxt.binanceusdm,  # type: ignore[name-defined]
    symbol: str,
    notional: Decimal,
    leverage: float,
) -> Tuple[float, float]:
    """Resolve (size, last_price) for a small Binance futures order.

    - Fetches the latest price via `fetch_ticker`.
    - Computes size = notional / price * leverage.
    - Uses `amount_to_precision` to respect symbol precision.
    """

    try:
        ticker = exchange.fetch_ticker(symbol)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to fetch ticker for {symbol}: {exc}") from exc

    price = ticker.get("last") or ticker.get("close")
    try:
        price_val = float(price)
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid price {price!r} for {symbol}") from None
    if price_val <= 0:
        raise RuntimeError(f"Non-positive price {price_val} for {symbol}")

    raw_size = (notional / Decimal(str(price_val))) * Decimal(str(leverage))
    size_float = float(raw_size)
    if size_float <= 0:
        raise RuntimeError(f"Computed order size {size_float} is non-positive; increase notional or leverage.")

    # Consult market metadata to determine minimum viable size before snapping to precision.
    min_from_limits = 0.0
    min_from_precision = 0.0
    min_from_notional = 0.0
    try:
        market = exchange.market(symbol)
        # limits.amount.min
        limits = market.get("limits") or {}
        amount_limits = limits.get("amount") or {}
        min_raw = amount_limits.get("min")
        if min_raw is not None:
            min_from_limits = float(min_raw)
        # limits.cost.min (min notional in quote currency, e.g. USDT)
        cost_limits = limits.get("cost") or {}
        min_cost_raw = cost_limits.get("min")
        if min_cost_raw is not None:
            try:
                min_notional = float(min_cost_raw)
                if min_notional > 0 and price_val > 0:
                    min_from_notional = min_notional / price_val
            except (TypeError, ValueError):  # noqa: BLE001
                min_from_notional = 0.0
        # precision.amount (often used to derive minimum step)
        precision = market.get("precision") or {}
        prec_amount = precision.get("amount")
        if prec_amount is not None:
            min_from_precision = float(prec_amount)
    except Exception:  # noqa: BLE001
        min_from_limits = 0.0
        min_from_precision = 0.0

    min_required = max(min_from_limits, min_from_precision, min_from_notional, 0.0)
    if min_required > 0 and size_float < min_required:
        logging.info(
            "Adjusted raw order size from %.10f to Binance minimum %.10f for %s",
            size_float,
            min_required,
            symbol,
        )
        size_float = min_required

    # Snap to allowed precision; at this point, size_float should already be >= minimum.
    size_precise = float(exchange.amount_to_precision(symbol, size_float))
    if size_precise <= 0:
        raise RuntimeError(
            f"Size after precision adjustment is non-positive ({size_precise}); "
            "try increasing notional or leverage."
        )

    return size_precise, price_val


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manually smoke-test Binance USDT-margined futures with a tiny position.",
    )
    parser.add_argument(
        "--symbol",
        default=DEFAULT_SYMBOL,
        help=(
            "Binance futures symbol (USDT-margined), e.g. BTCUSDT. "
            "Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--notional",
        type=lambda v: _parse_decimal(v, name="notional"),
        default=DEFAULT_NOTIONAL,
        help="Approximate USD notional to deploy (default: %(default)s)",
    )
    parser.add_argument(
        "--leverage",
        type=float,
        default=DEFAULT_LEVERAGE,
        help="Leverage multiplier to use (default: %(default)s)",
    )
    parser.add_argument(
        "--side",
        choices=["long", "short"],
        default="long",
        help="Position side to open (default: %(default)s)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=DEFAULT_WAIT_SECONDS,
        help="Seconds to wait before submitting the close order (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: %(default)s)",
    )
    parser.add_argument(
        "--use-exchange-client",
        action="store_true",
        help=(
            "Route orders through BinanceFuturesExchangeClient adapter for this smoke test "
            "(otherwise use raw ccxt create_order)."
        ),
    )
    return parser


def _resolve_api_keys() -> Tuple[str, str]:
    # Prefer dedicated futures keys if set; otherwise fall back to BN_API_KEY/BN_SECRET
    api_key = os.getenv("BINANCE_API_KEY") or os.getenv("BN_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or os.getenv("BN_SECRET") or ""
    if not api_key or not api_secret:
        raise SystemExit(
            "BINANCE_API_KEY/BINANCE_API_SECRET (or BN_API_KEY/BN_SECRET) "
            "must be set for live Binance futures smoke test."
        )
    return api_key, api_secret


def _make_exchange() -> ccxt.binanceusdm:  # type: ignore[name-defined]
    api_key, api_secret = _resolve_api_keys()
    try:
        exchange = ccxt.binanceusdm(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            }
        )
        exchange.load_markets()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Failed to initialize Binance futures client: {exc}") from exc
    return exchange


def run_smoke_test(
    symbol: str,
    notional: Decimal,
    leverage: float,
    side: str,
    wait_seconds: int,
    use_exchange_client: bool,
) -> None:
    load_dotenv(override=True)

    exchange = _make_exchange()
    logging.info(
        "Running Binance futures smoke test on %s with ~%s USDT notional at %sx leverage.",
        symbol,
        notional,
        leverage,
    )

    size, last_price = determine_order_params(
        exchange=exchange,
        symbol=symbol,
        notional=notional,
        leverage=leverage,
    )

    logging.info(
        "Placing entry: symbol=%s side=%s size=%.6f last_price=%.6f",
        symbol,
        side,
        size,
        last_price,
    )

    entry_receipt: Any
    coin = symbol.replace("USDT", "")

    if use_exchange_client:
        client = BinanceFuturesExchangeClient(exchange=exchange)
        entry_result = client.place_entry(
            coin=coin,
            side=side,
            size=size,
            entry_price=last_price,
            stop_loss_price=None,
            take_profit_price=None,
            leverage=leverage,
            liquidity="taker",
            symbol=symbol,
        )
        entry_receipt = {
            "success": entry_result.success,
            "order": entry_result.extra.get("order") if isinstance(entry_result.extra, dict) else None,
            "entry_oid": entry_result.entry_oid,
            "errors": entry_result.errors,
        }
    else:
        order_side = "buy" if side == "long" else "sell"
        params = {
            "positionSide": "LONG" if side == "long" else "SHORT",
        }
        try:
            order = exchange.create_order(
                symbol=symbol,
                type="market",
                side=order_side,
                amount=size,
                params=params,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("Entry order failed: %s", exc)
            raise SystemExit(1) from exc
        entry_receipt = {"success": True, "order": order}

    if not entry_receipt.get("success"):
        logging.error("Entry order failed: %s", entry_receipt)
        raise SystemExit(1)

    logging.info("Entry placed successfully. Receipt: %s", entry_receipt)

    logging.info("Sleeping %d seconds before closing...", wait_seconds)
    time.sleep(wait_seconds)

    logging.info("Submitting close order...")
    if use_exchange_client:
        client = BinanceFuturesExchangeClient(exchange=exchange)
        close_result = client.close_position(
            coin=coin,
            side=side,
            size=size,
            fallback_price=last_price,
            symbol=symbol,
        )
        close_receipt = {
            "success": close_result.success,
            "order": close_result.extra.get("order") if isinstance(close_result.extra, dict) else None,
            "close_oid": close_result.close_oid,
            "errors": close_result.errors,
        }
    else:
        order_side = "sell" if side == "long" else "buy"
        params = {
            "reduceOnly": True,
            "positionSide": "LONG" if side == "long" else "SHORT",
        }
        try:
            order = exchange.create_order(
                symbol=symbol,
                type="market",
                side=order_side,
                amount=size,
                params=params,
            )
        except Exception as exc:  # noqa: BLE001
            logging.error("Close order failed: %s", exc)
            raise SystemExit(1) from exc
        close_receipt = {"success": True, "order": order}

    if not close_receipt.get("success"):
        logging.error("Close order failed: %s", close_receipt)
        raise SystemExit(1)

    logging.info("Close order submitted successfully. Receipt: %s", close_receipt)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        run_smoke_test(
            symbol=args.symbol,
            notional=args.notional,
            leverage=args.leverage,
            side=args.side,
            wait_seconds=args.wait,
            use_exchange_client=args.use_exchange_client,
        )
    except KeyboardInterrupt:
        logging.error("Interrupted by user.")
        sys.exit(1)
    except SystemExit as exc:
        raise exc
    except Exception as exc:  # noqa: BLE001
        logging.exception("Binance futures smoke test failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
