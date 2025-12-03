#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from exchange.backpack import BackpackFuturesExchangeClient  # noqa: E402


def _make_client() -> BackpackFuturesExchangeClient:
    api_public_key = os.getenv("BACKPACK_API_PUBLIC_KEY", "").strip()
    api_secret_seed = os.getenv("BACKPACK_API_SECRET_SEED", "").strip()

    if not api_public_key or not api_secret_seed:
        raise SystemExit(
            "BACKPACK_API_PUBLIC_KEY and BACKPACK_API_SECRET_SEED must be set "
            "to debug Backpack positions.",
        )

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


def main() -> None:
    load_dotenv(override=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    client = _make_client()
    positions = client._get_open_positions() or []

    print("Open positions count:", len(positions))
    for pos in positions:
        symbol = pos.get("symbol")
        print("\n=== POSITION:", symbol, "===")
        print(json.dumps(pos, indent=2, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
