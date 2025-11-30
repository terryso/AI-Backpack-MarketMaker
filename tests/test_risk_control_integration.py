"""Integration tests for risk control state persistence and main loop integration.

Covers:
- Saving RiskControlState into portfolio_state.json via core.state.save_state
- Loading RiskControlState from JSON via core.state.load_state
- Backward compatibility when risk_control field is missing or malformed
- Risk control check entry point in main loop (Story 7.1.4)
- Risk control configuration logging at startup
"""

import copy
import json
import logging
import tempfile
from pathlib import Path
from unittest import TestCase, mock

import core.state as core_state
from core.risk_control import RiskControlState, check_risk_limits


class RiskControlPersistenceIntegrationTests(TestCase):
    """Integration tests for RiskControlState persistence and compatibility."""

    def setUp(self) -> None:
        self._orig_balance = core_state.balance
        self._orig_positions = copy.deepcopy(core_state.positions)
        self._orig_iteration = core_state.iteration_counter
        self._orig_risk_control_state = core_state.risk_control_state
        self._orig_state_json = core_state.STATE_JSON

    def tearDown(self) -> None:
        core_state.balance = self._orig_balance
        core_state.positions = copy.deepcopy(self._orig_positions)
        core_state.iteration_counter = self._orig_iteration
        core_state.risk_control_state = self._orig_risk_control_state
        core_state.STATE_JSON = self._orig_state_json

    def test_save_state_includes_risk_control_field(self) -> None:
        """save_state should include risk_control field matching to_dict()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            core_state.balance = 111.1
            core_state.positions = {}
            core_state.iteration_counter = 42
            core_state.risk_control_state = RiskControlState(
                kill_switch_active=True,
                kill_switch_reason="Daily loss limit",
                daily_start_equity=5000.0,
                daily_start_date="2025-11-30",
                daily_loss_pct=-5.0,
                daily_loss_triggered=True,
            )

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.save_state()

            data = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("risk_control", data)
            self.assertEqual(data["risk_control"], core_state.risk_control_state.to_dict())

    def test_load_state_restores_risk_control_from_json(self) -> None:
        """load_state should restore RiskControlState from risk_control field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            payload = {
                "balance": 9000.0,
                "positions": {},
                "iteration": 7,
                "updated_at": "2025-11-30T00:00:00+00:00",
                "risk_control": {
                    "kill_switch_active": True,
                    "kill_switch_reason": "Manual trigger",
                    "kill_switch_triggered_at": "2025-11-30T10:00:00+00:00",
                    "daily_start_equity": 10000.0,
                    "daily_start_date": "2025-11-30",
                    "daily_loss_pct": -3.5,
                    "daily_loss_triggered": False,
                },
            }
            state_path.write_text(json.dumps(payload), encoding="utf-8")

            core_state.balance = 0.0
            core_state.positions = {}
            core_state.iteration_counter = 0
            core_state.risk_control_state = RiskControlState()

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.load_state()

            self.assertEqual(core_state.balance, 9000.0)
            self.assertEqual(core_state.iteration_counter, 7)

            state = core_state.risk_control_state
            self.assertTrue(state.kill_switch_active)
            self.assertEqual(state.kill_switch_reason, "Manual trigger")
            self.assertEqual(state.kill_switch_triggered_at, "2025-11-30T10:00:00+00:00")
            self.assertEqual(state.daily_start_equity, 10000.0)
            self.assertEqual(state.daily_start_date, "2025-11-30")
            self.assertEqual(state.daily_loss_pct, -3.5)
            self.assertFalse(state.daily_loss_triggered)

    def test_load_state_uses_default_when_risk_control_missing(self) -> None:
        """load_state should fall back to default RiskControlState when field missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            payload = {
                "balance": 5000.0,
                "positions": {},
                "iteration": 1,
                "updated_at": "2025-11-30T00:00:00+00:00",
            }
            state_path.write_text(json.dumps(payload), encoding="utf-8")

            core_state.balance = 0.0
            core_state.positions = {}
            core_state.iteration_counter = 0
            core_state.risk_control_state = RiskControlState(
                kill_switch_active=True,
                daily_loss_pct=-10.0,
                daily_loss_triggered=True,
            )

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.load_state()

            self.assertEqual(core_state.balance, 5000.0)

            state = core_state.risk_control_state
            self.assertFalse(state.kill_switch_active)
            self.assertEqual(state.daily_loss_pct, 0.0)
            self.assertFalse(state.daily_loss_triggered)

    def test_load_state_handles_malformed_risk_control_field(self) -> None:
        """Non-dict risk_control field should be treated as missing and use defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            payload = {
                "balance": 6000.0,
                "positions": {},
                "iteration": 2,
                "updated_at": "2025-11-30T00:00:00+00:00",
                "risk_control": "not-a-dict",
            }
            state_path.write_text(json.dumps(payload), encoding="utf-8")

            core_state.balance = 0.0
            core_state.positions = {}
            core_state.iteration_counter = 0
            core_state.risk_control_state = RiskControlState(
                kill_switch_active=True,
                daily_loss_pct=-1.0,
                daily_loss_triggered=True,
            )

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.load_state()

            self.assertEqual(core_state.balance, 6000.0)

            state = core_state.risk_control_state
            self.assertFalse(state.kill_switch_active)
            self.assertEqual(state.daily_loss_pct, 0.0)
            self.assertFalse(state.daily_loss_triggered)


class RiskControlCheckIntegrationTests(TestCase):
    """Integration tests for check_risk_limits() entry point (Story 7.1.4)."""

    def test_check_risk_limits_returns_true_when_enabled(self) -> None:
        """check_risk_limits should return True when risk control is enabled."""
        state = RiskControlState()
        result = check_risk_limits(
            risk_control_state=state,
            total_equity=10000.0,
            risk_control_enabled=True,
        )
        self.assertTrue(result)

    def test_check_risk_limits_returns_true_when_disabled(self) -> None:
        """check_risk_limits should return True and skip checks when disabled."""
        state = RiskControlState(kill_switch_active=True)
        result = check_risk_limits(
            risk_control_state=state,
            total_equity=10000.0,
            risk_control_enabled=False,
        )
        self.assertTrue(result)

    def test_check_risk_limits_logs_skip_when_disabled(self, caplog=None) -> None:
        """check_risk_limits should log when risk control is disabled."""
        state = RiskControlState()
        with self.assertLogs(level=logging.INFO) as cm:
            check_risk_limits(
                risk_control_state=state,
                risk_control_enabled=False,
            )
        self.assertTrue(
            any("RISK_CONTROL_ENABLED=False" in msg for msg in cm.output),
            f"Expected log message about disabled risk control, got: {cm.output}",
        )

    def test_check_risk_limits_accepts_optional_params(self) -> None:
        """check_risk_limits should accept optional total_equity and iteration_time."""
        from datetime import datetime, timezone

        state = RiskControlState()
        # Should not raise
        result = check_risk_limits(
            risk_control_state=state,
            total_equity=None,
            iteration_time=None,
            risk_control_enabled=True,
        )
        self.assertTrue(result)

        result = check_risk_limits(
            risk_control_state=state,
            total_equity=5000.0,
            iteration_time=datetime.now(timezone.utc),
            risk_control_enabled=True,
        )
        self.assertTrue(result)


class RiskControlStateRestartTests(TestCase):
    """Integration tests for risk control state persistence across restarts."""

    def setUp(self) -> None:
        self._orig_balance = core_state.balance
        self._orig_positions = copy.deepcopy(core_state.positions)
        self._orig_iteration = core_state.iteration_counter
        self._orig_risk_control_state = core_state.risk_control_state
        self._orig_state_json = core_state.STATE_JSON

    def tearDown(self) -> None:
        core_state.balance = self._orig_balance
        core_state.positions = copy.deepcopy(self._orig_positions)
        core_state.iteration_counter = self._orig_iteration
        core_state.risk_control_state = self._orig_risk_control_state
        core_state.STATE_JSON = self._orig_state_json

    def test_risk_control_state_survives_simulated_restart(self) -> None:
        """Risk control state should be preserved across save/load cycles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            # Simulate iteration 1: set initial state
            core_state.balance = 10000.0
            core_state.positions = {}
            core_state.iteration_counter = 1
            core_state.risk_control_state = RiskControlState(
                kill_switch_active=False,
                daily_start_equity=10000.0,
                daily_start_date="2025-11-30",
                daily_loss_pct=0.0,
            )

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.save_state()

            # Simulate iteration 2: update state
            core_state.balance = 9500.0
            core_state.iteration_counter = 2
            core_state.risk_control_state = RiskControlState(
                kill_switch_active=False,
                daily_start_equity=10000.0,
                daily_start_date="2025-11-30",
                daily_loss_pct=-5.0,
            )

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.save_state()

            # Simulate restart: reset state and reload
            core_state.balance = 0.0
            core_state.positions = {}
            core_state.iteration_counter = 0
            core_state.risk_control_state = RiskControlState()

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.load_state()

            # Verify state was restored
            self.assertEqual(core_state.balance, 9500.0)
            self.assertEqual(core_state.iteration_counter, 2)
            self.assertEqual(core_state.risk_control_state.daily_start_equity, 10000.0)
            self.assertEqual(core_state.risk_control_state.daily_start_date, "2025-11-30")
            self.assertEqual(core_state.risk_control_state.daily_loss_pct, -5.0)
            self.assertFalse(core_state.risk_control_state.kill_switch_active)

    def test_risk_control_state_with_kill_switch_survives_restart(self) -> None:
        """Kill-switch state should be preserved across restarts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"

            # Set state with kill switch active
            core_state.balance = 8000.0
            core_state.positions = {}
            core_state.iteration_counter = 5
            core_state.risk_control_state = RiskControlState(
                kill_switch_active=True,
                kill_switch_reason="Daily loss limit exceeded",
                kill_switch_triggered_at="2025-11-30T10:30:00+00:00",
                daily_start_equity=10000.0,
                daily_start_date="2025-11-30",
                daily_loss_pct=-20.0,
                daily_loss_triggered=True,
            )

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.save_state()

            # Reset and reload
            core_state.balance = 0.0
            core_state.iteration_counter = 0
            core_state.risk_control_state = RiskControlState()

            with mock.patch.object(core_state, "STATE_JSON", state_path):
                core_state.load_state()

            # Verify kill switch state was restored
            self.assertTrue(core_state.risk_control_state.kill_switch_active)
            self.assertEqual(
                core_state.risk_control_state.kill_switch_reason,
                "Daily loss limit exceeded",
            )
            self.assertEqual(
                core_state.risk_control_state.kill_switch_triggered_at,
                "2025-11-30T10:30:00+00:00",
            )
            self.assertTrue(core_state.risk_control_state.daily_loss_triggered)
            self.assertEqual(core_state.risk_control_state.daily_loss_pct, -20.0)


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
