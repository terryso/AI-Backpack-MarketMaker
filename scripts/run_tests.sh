#!/usr/bin/env bash
set -euo pipefail

# Simple test runner for this repo.
# - Forces pytest to ignore globally-installed plugins (PYTEST_DISABLE_PLUGIN_AUTOLOAD=1)
# - By default runs the whole tests/ directory
# - You can pass additional args to pytest, e.g.:
#     ./scripts/run_tests.sh tests/test_exchange_client_binance_futures.py -k entry

# Resolve repo root as parent of this scripts/ directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR%/scripts}"
cd "${ROOT_DIR}"

export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

if [ "$#" -eq 0 ]; then
  pytest tests
else
  pytest "$@"
fi
