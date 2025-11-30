"""
Risk control state management.

This module defines the RiskControlState data structure for managing
risk control features including Kill-Switch and daily loss limits.
It also provides the check_risk_limits() entry point for the main trading loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.risk_control import RiskControlState as _RiskControlState


@dataclass
class RiskControlState:
    """Risk control system state data structure.

    This dataclass holds all state related to risk control features,
    including Kill-Switch status and daily loss tracking.

    Attributes:
        kill_switch_active: Whether Kill-Switch is currently activated.
        kill_switch_reason: The reason for Kill-Switch activation.
        kill_switch_triggered_at: ISO 8601 timestamp when Kill-Switch was triggered.
        daily_start_equity: Starting equity for the current day (UTC).
        daily_start_date: Date string (YYYY-MM-DD) for daily baseline.
        daily_loss_pct: Current daily loss percentage (negative = loss).
        daily_loss_triggered: Whether Kill-Switch was triggered by daily loss limit.
    """

    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    kill_switch_triggered_at: Optional[str] = None
    daily_start_equity: Optional[float] = None
    daily_start_date: Optional[str] = None
    daily_loss_pct: float = 0.0
    daily_loss_triggered: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state to a dictionary for JSON persistence.

        Returns:
            A dictionary representation of the state that can be
            serialized with json.dumps().
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskControlState":
        """Deserialize state from a dictionary.

        Handles missing fields gracefully by using default values.

        Args:
            data: Dictionary containing state fields. Missing fields
                will use their default values.

        Returns:
            A new RiskControlState instance with values from the dictionary.
        """
        return cls(
            kill_switch_active=data.get("kill_switch_active", False),
            kill_switch_reason=data.get("kill_switch_reason"),
            kill_switch_triggered_at=data.get("kill_switch_triggered_at"),
            daily_start_equity=data.get("daily_start_equity"),
            daily_start_date=data.get("daily_start_date"),
            daily_loss_pct=data.get("daily_loss_pct", 0.0),
            daily_loss_triggered=data.get("daily_loss_triggered", False),
        )


def check_risk_limits(
    risk_control_state: RiskControlState,
    total_equity: Optional[float] = None,
    iteration_time: Optional[datetime] = None,
    risk_control_enabled: bool = True,
) -> bool:
    """Check risk limits at the start of each trading iteration.

    This is the unified entry point for risk control checks in the main loop.
    It is called at the beginning of each iteration, before market data fetching
    and LLM decision making.

    Currently, this function serves as a placeholder that logs the check and
    returns immediately. The actual Kill-Switch and daily loss limit logic
    will be implemented in Epic 7.2 and 7.3 respectively.

    Args:
        risk_control_state: The current risk control state object.
        total_equity: Current total account equity (optional, for future use).
        iteration_time: Current iteration timestamp (optional, for future use).
        risk_control_enabled: Whether risk control is enabled (from RISK_CONTROL_ENABLED).

    Returns:
        True if trading should proceed, False if trading should be blocked
        (e.g., Kill-Switch is active). Currently always returns True as
        blocking logic is not yet implemented.
    """
    if not risk_control_enabled:
        logging.info("Risk control check skipped: RISK_CONTROL_ENABLED=False")
        return True

    # Log the risk control check (placeholder for future Epic 7.2/7.3 logic)
    logging.debug(
        "Risk control check: kill_switch_active=%s, daily_loss_pct=%.2f%%",
        risk_control_state.kill_switch_active,
        risk_control_state.daily_loss_pct,
    )

    # Future Epic 7.2: Check Kill-Switch status
    # if risk_control_state.kill_switch_active:
    #     logging.warning("Kill-Switch is active: %s", risk_control_state.kill_switch_reason)
    #     return False

    # Future Epic 7.3: Check daily loss limit
    # if daily_loss_limit_enabled and check_daily_loss_limit(...):
    #     return False

    return True
