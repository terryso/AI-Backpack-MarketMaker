#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manual smoke test for Backpack USDC perpetual futures via BackpackFuturesExchangeClient.

This script is intended for **manual**, small-notional live verification only.
It will place a tiny market order on Backpack futures, wait briefly, then
attempt to close the position using a reduce-only market order.

WARNING:
    This script can submit REAL ORDERS on Backpack futures when valid API
    credentials are configured. Make sure you understand and double-check:
        - BACKPACK_API_PUBLIC_KEY
        - BACKPACK_API_SECRET_SEED
        - Coin, size, and side parameters
    before running it.

Usage example (from project root):
    ./scripts/run_backpack_futures_smoke.sh --coin BTC --size 0.001 --side long

Environment variables:
    BACKPACK_API_PUBLIC_KEY   Base64-encoded ED25519 public key.
    BACKPACK_API_SECRET_SEED  Base64-encoded ED25519 secret seed.
    BACKPACK_API_BASE_URL     Optional; defaults to https://api.backpack.exchange.
    BACKPACK_API_WINDOW_MS    Optional; defaults to 5000.
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

from dotenv import load_dotenv

# Ensure project root is on sys.path so local modules resolve when script is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from exchange.backpack import BackpackFuturesExchangeClient  # noqa: E402


DEFAULT_COIN = "BTC"
DEFAULT_SIZE = Decimal("0.001")  # 0.001 BTC equivalent size for minimal smoke
DEFAULT_WAIT_SECONDS = 15


def _parse_decimal(value: str, *, name: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:  # noqa: B904
        raise argparse.ArgumentTypeError(f"Invalid decimal value for {name}: {value}") from exc


def _resolve_backpack_credentials() -> Tuple[str, str]:
    api_public_key = os.getenv("BACKPACK_API_PUBLIC_KEY", "").strip()
    api_secret_seed = os.getenv("BACKPACK_API_SECRET_SEED", "").strip()

    if not api_public_key or not api_secret_seed:
        raise SystemExit(
            "BACKPACK_API_PUBLIC_KEY and BACKPACK_API_SECRET_SEED must be set "
            "for Backpack futures smoke test.",
        )

    return api_public_key, api_secret_seed


def _make_client() -> BackpackFuturesExchangeClient:
    api_public_key, api_secret_seed = _resolve_backpack_credentials()

    base_url = os.getenv("BACKPACK_API_BASE_URL") or "https://api.backpack.exchange"
    window_raw = os.getenv("BACKPACK_API_WINDOW_MS") or "5000"
    try:
        window_ms = int(window_raw)
    except (TypeError, ValueError):  # noqa: B904
        logging.warning("Invalid BACKPACK_API_WINDOW_MS %r; defaulting to 5000", window_raw)
        window_ms = 5000

    logging.info(
        "Initializing BackpackFuturesExchangeClient (base_url=%s, window_ms=%s)",
        base_url,
        window_ms,
    )

    return BackpackFuturesExchangeClient(
        api_public_key=api_public_key,
        api_secret_seed=api_secret_seed,
        base_url=base_url,
        window_ms=window_ms,
    )


def run_smoke_test(
    coin: str,
    size: Decimal,
    side: str,
    wait_seconds: int,
) -> None:
    """Run a minimal open-then-close smoke on Backpack futures.

    The script opens a small perp position on {COIN}_USDC_PERP, waits for a
    short period, then submits a reduce-only market order to close it.
    """

    load_dotenv(override=True)

    client = _make_client()

    size_float = float(size)
    if size_float <= 0:
        raise SystemExit("Order size must be positive for smoke test.")

    coin_clean = coin.strip().upper()
    logging.info(
        "Running Backpack futures smoke test on %s_USDC_PERP: side=%s size=%.8f",
        coin_clean,
        side,
        size_float,
    )

    logging.info("Placing entry order...")
    entry_result = client.place_entry(
        coin=coin_clean,
        side=side,
        size=size_float,
        entry_price=None,
        stop_loss_price=None,
        take_profit_price=None,
        leverage=1.0,
        liquidity="taker",
    )

    if not entry_result.success:
        logging.error("Entry order failed. errors=%s raw=%s", entry_result.errors, entry_result.raw)
        raise SystemExit(1)

    logging.info("Entry placed successfully. entry_oid=%s", entry_result.entry_oid)
    if entry_result.errors:
        logging.warning("Non-empty error list on successful entry: %s", entry_result.errors)

    logging.debug("Entry raw payload: %s", entry_result.raw)

    logging.info("Sleeping %d seconds before closing...", wait_seconds)
    time.sleep(wait_seconds)

    logging.info("Submitting close (reduce-only) order...")
    close_result = client.close_position(
        coin=coin_clean,
        side=side,
        size=size_float,
        fallback_price=None,
    )

    if not close_result.success:
        logging.error("Close order failed. errors=%s raw=%s", close_result.errors, close_result.raw)
        raise SystemExit(1)

    logging.info("Close order submitted successfully. close_oid=%s", close_result.close_oid)
    if close_result.errors:
        logging.warning("Non-empty error list on successful close: %s", close_result.errors)

    logging.debug("Close raw payload: %s", close_result.raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manually smoke-test Backpack USDC perpetual futures with a tiny position.",
    )
    parser.add_argument(
        "--coin",
        default=DEFAULT_COIN,
        help=(
            "Perp coin symbol on Backpack (e.g. BTC). The script uses {COIN}_USDC_PERP "
            "as the market. Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--size",
        type=lambda v: _parse_decimal(v, name="size"),
        default=DEFAULT_SIZE,
        help="Position size in coin units (e.g. BTC). Default: %(default)s",
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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        run_smoke_test(
            coin=args.coin,
            size=args.size,
            side=args.side,
            wait_seconds=args.wait,
        )
    except KeyboardInterrupt:
        logging.error("Interrupted by user.")
        sys.exit(1)
    except SystemExit as exc:  # re-raise explicit SystemExit codes
        raise exc
    except Exception as exc:  # noqa: BLE001
        logging.exception("Backpack futures smoke test failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
