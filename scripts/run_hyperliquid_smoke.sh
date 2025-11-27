#!/usr/bin/env bash
set -euo pipefail

# Hyperliquid live trading smoke test wrapper.
#
# This is a thin convenience wrapper around scripts/manual_hyperliquid_smoke.py.
# It does NOT change any trading logic; it only:
#   - Resolves the project root
#   - Ensures we run the Python script from the repo root
#   - Forwards all CLI arguments as-is
#
# WARNING:
#   This script can submit REAL ORDERS on Hyperliquid mainnet when the
#   underlying Python script is configured for live trading.
#   Make sure you understand and double-check:
#     - HYPERLIQUID_WALLET_ADDRESS
#     - HYPERLIQUID_PRIVATE_KEY
#     - Notional size, leverage, and BPS parameters
#   before running it.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR%/scripts}"
cd "${ROOT_DIR}"

# Keep output unbuffered for easier monitoring
export PYTHONUNBUFFERED=1

# Default behaviour: rely on manual_hyperliquid_smoke.py's own defaults.
# Examples:
#   ./scripts/run_hyperliquid_smoke.sh
#   ./scripts/run_hyperliquid_smoke.sh --coin BTC --notional 5 --leverage 2 --use-exchange-client

python scripts/manual_hyperliquid_smoke.py "$@"
