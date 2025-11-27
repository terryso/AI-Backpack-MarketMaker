#!/usr/bin/env bash
set -euo pipefail

# Binance USDT-margined futures live trading smoke test wrapper.
#
# This is a thin convenience wrapper around scripts/manual_binance_futures_smoke.py.
# It does NOT change any trading logic; it only:
#   - Resolves the project root
#   - Ensures we run the Python script from the repo root
#   - Forwards all CLI arguments as-is
#
# WARNING:
#   This script can submit REAL ORDERS on Binance USDT-margined futures when
#   valid API keys are configured. Make sure you understand and double-check:
#     - BINANCE_API_KEY / BINANCE_API_SECRET (or BN_API_KEY / BN_SECRET)
#     - Notional size, leverage, and side parameters
#   before running it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR%/scripts}"
cd "${ROOT_DIR}"

# Keep output unbuffered for easier monitoring
export PYTHONUNBUFFERED=1

# Default behaviour: rely on manual_binance_futures_smoke.py's own defaults.
# Examples:
#   ./scripts/run_binance_futures_smoke.sh
#   ./scripts/run_binance_futures_smoke.sh --symbol BTCUSDT --notional 5 --leverage 2 --use-exchange-client

python scripts/manual_binance_futures_smoke.py "$@"
