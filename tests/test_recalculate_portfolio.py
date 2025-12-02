import os
import sys
from pathlib import Path
import unittest
from unittest import mock

# Make scripts/ importable so we can load recalculate_portfolio as a module
ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import recalculate_portfolio as rp


class RecalculatePortfolioTests(unittest.TestCase):
    def test_detect_starting_capital_uses_paper_when_not_live(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "TRADING_BACKEND": "hyperliquid",
                "LIVE_TRADING_ENABLED": "false",
                "PAPER_START_CAPITAL": "12345.6",
            },
            clear=True,
        ):
            value = rp.detect_starting_capital()
        self.assertEqual(value, 12345.6)

    def test_detect_starting_capital_uses_hyper_when_live(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "TRADING_BACKEND": "hyperliquid",
                "LIVE_TRADING_ENABLED": "true",
                "HYPERLIQUID_CAPITAL": "789.0",
            },
            clear=True,
        ):
            value = rp.detect_starting_capital()
        self.assertEqual(value, 789.0)

    def test_detect_starting_capital_defaults_for_live(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "TRADING_BACKEND": "hyperliquid",
                "LIVE_TRADING_ENABLED": "true",
            },
            clear=True,
        ):
            value = rp.detect_starting_capital()
        self.assertEqual(value, 500.0)

    def test_extract_fee_parses_amount_from_reason(self) -> None:
        self.assertEqual(rp.extract_fee("AI entry | Fees: $1.23"), 1.23)
        self.assertEqual(rp.extract_fee("Fees: $0.00"), 0.0)
        self.assertEqual(rp.extract_fee("no fee info here"), 0.0)
        self.assertEqual(rp.extract_fee(""), 0.0)
        self.assertEqual(rp.extract_fee("Fees: $abc"), 0.0)

    def test_clean_reason_text_strips_after_pipe(self) -> None:
        self.assertEqual(rp.clean_reason_text("AI entry | Fees: $1.00"), "AI entry")
        self.assertEqual(rp.clean_reason_text("  Just text  "), "Just text")

    def test_position_from_trade_derives_margin_fee_and_risk(self) -> None:
        row = {
            "coin": "BTC",
            "side": "LONG",
            "quantity": "2",
            "price": "100",
            "leverage": "4",
            "profit_target": "120",
            "stop_loss": "90",
            "confidence": "0.5",
            "reason": "AI entry | Fees: $1.00 | extra",
            "timestamp": "2024-01-01T00:00:00Z",
        }

        pos = rp.Position.from_trade(row)

        self.assertEqual(pos.coin, "BTC")
        self.assertEqual(pos.side, "long")
        self.assertEqual(pos.quantity, 2.0)
        self.assertEqual(pos.entry_price, 100.0)
        self.assertEqual(pos.profit_target, 120.0)
        self.assertEqual(pos.stop_loss, 90.0)
        self.assertEqual(pos.leverage, 4.0)
        self.assertAlmostEqual(pos.margin, 50.0)
        self.assertEqual(pos.entry_fee, 1.0)
        self.assertAlmostEqual(pos.fee_rate, 1.0 / (2.0 * 100.0))
        self.assertAlmostEqual(pos.risk_usd, abs(100.0 - 90.0) * 2.0)
        self.assertEqual(pos.entry_reason, "AI entry")
        self.assertEqual(pos.entry_timestamp, row["timestamp"])
        self.assertGreaterEqual(pos.confidence, 0.0)

        state_dict = pos.to_state_dict()
        self.assertEqual(state_dict["side"], "long")
        self.assertEqual(state_dict["quantity"], 2.0)
        self.assertEqual(state_dict["entry_price"], 100.0)
        self.assertEqual(state_dict["profit_target"], 120.0)
        self.assertEqual(state_dict["stop_loss"], 90.0)
        self.assertEqual(state_dict["margin"], 50.0)
        self.assertEqual(state_dict["fees_paid"], 1.0)
        self.assertEqual(state_dict["fee_rate"], pos.fee_rate)
        self.assertEqual(state_dict["entry_justification"], "AI entry")
        self.assertEqual(state_dict["last_justification"], "AI entry")
        self.assertEqual(state_dict["risk_usd"], pos.risk_usd)

    def test_process_trades_single_round_trip_updates_balance_and_clears_position(self) -> None:
        trades = [
            {
                "action": "ENTRY",
                "coin": "BTC",
                "quantity": "2",
                "price": "100",
                "side": "long",
                "leverage": "2",
                "profit_target": "120",
                "stop_loss": "90",
                "confidence": "0",
                "reason": "AI entry | Fees: $1.00",
                "timestamp": "2024-01-01T00:00:00Z",
            },
            {
                "action": "CLOSE",
                "coin": "BTC",
                "quantity": "2",
                "price": "120",
                "side": "long",
                "reason": "AI close | Fees: $2.00",
                "timestamp": "2024-01-01T01:00:00Z",
            },
        ]

        starting_balance = 1000.0
        state = rp.process_trades(trades, starting_balance)

        self.assertEqual(state["positions"], {})
        self.assertEqual(state["warnings"], [])
        self.assertAlmostEqual(state["total_margin"], 0.0)

        # ENTRY: margin = (2 * 100) / 2 = 100, entry_fee = 1 → balance = 1000 - 100 - 1 = 899
        # CLOSE: gross = (120 - 100) * 2 = 40, total_fees = 2 → net = 38
        #        balance = 899 + 100 + 38 = 1037
        self.assertAlmostEqual(state["balance"], 1037.0)

    def test_process_trades_close_without_entry_generates_warning_and_keeps_balance(self) -> None:
        trades = [
            {
                "action": "CLOSE",
                "coin": "ETH",
                "quantity": "1",
                "price": "100",
                "side": "long",
                "reason": "AI close | Fees: $1.00",
                "timestamp": "2024-01-01T00:00:00Z",
            }
        ]

        starting_balance = 500.0
        state = rp.process_trades(trades, starting_balance)

        self.assertAlmostEqual(state["balance"], starting_balance)
        self.assertEqual(state["positions"], {})
        self.assertAlmostEqual(state["total_margin"], 0.0)
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("CLOSE for ETH", state["warnings"][0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
