import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bot
import core.state as core_state


class StateManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_balance = bot.balance
        self._orig_positions = copy.deepcopy(bot.positions)
        self._orig_iteration = bot.iteration_counter
        self._orig_state_json = bot.STATE_JSON
        self._orig_core_state_json = core_state.STATE_JSON
        self._orig_core_balance = core_state.balance
        self._orig_core_positions = copy.deepcopy(core_state.positions)
        self._orig_core_iteration = core_state.iteration_counter
        self._orig_core_risk_control = core_state.risk_control_state

    def tearDown(self) -> None:
        bot.balance = self._orig_balance
        bot.positions = copy.deepcopy(self._orig_positions)
        bot.iteration_counter = self._orig_iteration
        bot.STATE_JSON = self._orig_state_json
        core_state.STATE_JSON = self._orig_core_state_json
        core_state.balance = self._orig_core_balance
        core_state.positions = copy.deepcopy(self._orig_core_positions)
        core_state.iteration_counter = self._orig_core_iteration
        core_state.risk_control_state = self._orig_core_risk_control

    def test_load_state_no_file_keeps_existing_state(self) -> None:
        """When state file doesn't exist, load_state uses defaults from core.state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "state.json"

            # Note: bot.load_state() now delegates to core.state.load_state()
            # When file is missing, core.state.load_state() uses START_CAPITAL default
            # So we verify that the state is synced from core.state after load
            with mock.patch.object(core_state, "STATE_JSON", missing_path):
                bot.load_state()

            # After loading with missing file, bot.balance should match core_state.balance
            self.assertEqual(bot.balance, core_state.balance)
            self.assertEqual(bot.positions, core_state.positions)
            self.assertEqual(bot.iteration_counter, core_state.iteration_counter)

    def test_load_state_restores_balance_iteration_and_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            raw_state = {
                "balance": 999.5,
                "iteration": "5",
                "positions": {
                    "BTC": {
                        "side": "short",
                        "quantity": "2.0",
                        "entry_price": "100",
                        "profit_target": "80",
                        "stop_loss": "110",
                        "leverage": "3",
                        "confidence": "0.7",
                        "margin": "50",
                        "fees_paid": "1.2",
                        "fee_rate": "0.0005",
                        "liquidity": "taker",
                        "entry_justification": "test entry",
                        "last_justification": "",
                        "live_backend": "paper",
                        "entry_oid": 10,
                        "tp_oid": None,
                        "sl_oid": 20,
                        "close_oid": 30,
                    }
                },
            }
            state_path.write_text(json.dumps(raw_state), encoding="utf-8")

            bot.balance = 0.0
            bot.positions = {}
            bot.iteration_counter = 0

            # Must mock core_state.STATE_JSON since bot.load_state() delegates to core.state
            with mock.patch.object(core_state, "STATE_JSON", state_path):
                bot.load_state()

            self.assertAlmostEqual(bot.balance, 999.5)
            self.assertEqual(bot.iteration_counter, 5)
            self.assertIn("BTC", bot.positions)
            pos = bot.positions["BTC"]
            self.assertEqual(pos["side"], "short")
            self.assertAlmostEqual(pos["quantity"], 2.0)
            self.assertAlmostEqual(pos["entry_price"], 100.0)
            self.assertAlmostEqual(pos["profit_target"], 80.0)
            self.assertAlmostEqual(pos["stop_loss"], 110.0)
            self.assertAlmostEqual(pos["leverage"], 3.0)
            self.assertAlmostEqual(pos["confidence"], 0.7)
            self.assertAlmostEqual(pos["margin"], 50.0)
            self.assertAlmostEqual(pos["fees_paid"], 1.2)
            self.assertAlmostEqual(pos["fee_rate"], 0.0005)
            self.assertEqual(pos["liquidity"], "taker")
            self.assertEqual(pos["entry_justification"], "test entry")
            # Empty last_justification should remain empty string
            self.assertEqual(pos["last_justification"], "")
            self.assertEqual(pos["live_backend"], "paper")
            self.assertEqual(pos["entry_oid"], 10)
            # Explicit None tp_oid in stored JSON should remain None
            self.assertIsNone(pos["tp_oid"])
            self.assertEqual(pos["sl_oid"], 20)
            self.assertEqual(pos["close_oid"], 30)

    def test_save_state_persists_balance_positions_and_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            bot.balance = 111.1
            bot.positions = {
                "ETH": {
                    "side": "long",
                    "quantity": 1.5,
                    "entry_price": 200.0,
                }
            }
            bot.iteration_counter = 42

            # Must mock core_state.STATE_JSON since bot.save_state() delegates to core.state
            with mock.patch.object(core_state, "STATE_JSON", state_path):
                bot.save_state()

            self.assertTrue(state_path.exists())
            data = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertAlmostEqual(data["balance"], 111.1)
            self.assertEqual(data["iteration"], 42)
            self.assertIn("updated_at", data)
            self.assertIsInstance(data["updated_at"], str)
            self.assertIn("ETH", data["positions"])
            self.assertEqual(data["positions"]["ETH"]["side"], "long")
            # Verify risk_control field is included (Story 7.1.4)
            self.assertIn("risk_control", data)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
