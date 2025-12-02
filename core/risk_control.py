"""
Risk control state management.

This module defines the RiskControlState data structure for managing
risk control features including Kill-Switch and daily loss limits.
It also provides the check_risk_limits() entry point for the main trading loop.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple


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


def update_daily_baseline(
    state: RiskControlState,
    current_equity: float,
) -> None:
    """Update the daily baseline equity for risk control checks.

    This helper is called at the start of each iteration and is idempotent
    for a given UTC date. When the UTC date changes (including first
    initialization), it resets the daily baseline fields on the provided
    RiskControlState instance.

    Args:
        state: The mutable RiskControlState instance to update.
        current_equity: Current total equity used as the new daily baseline
            when the date changes.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    previous_date = state.daily_start_date
    previous_equity = state.daily_start_equity

    if previous_date == today:
        # Same UTC day: keep existing baseline to avoid resetting intra-day.
        logging.debug(
            "Daily baseline unchanged: date=%s, equity=%s",
            today,
            "None" if previous_equity is None else f"{previous_equity:.2f}",
        )
        return

    # New UTC day (or first initialization): reset baseline fields.
    state.daily_start_date = today
    state.daily_start_equity = current_equity
    state.daily_loss_pct = 0.0
    state.daily_loss_triggered = False

    logging.info(
        "Daily baseline reset: equity=%.2f, date=%s, previous_date=%s, previous_equity=%s",
        current_equity,
        today,
        previous_date or "",
        "None" if previous_equity is None else f"{previous_equity:.2f}",
    )


def calculate_daily_loss_pct(
    state: RiskControlState,
    current_equity: float,
) -> float:
    """Calculate the daily loss percentage based on current equity.

    This helper computes the percentage change from the daily baseline equity
    to the current equity. The result is written to state.daily_loss_pct and
    also returned for caller convenience.

    Formula: (current_equity - daily_start_equity) / daily_start_equity * 100

    The return value sign convention:
    - Positive value: profit (current_equity > daily_start_equity)
    - Negative value: loss (current_equity < daily_start_equity)
    - Zero: no change or invalid baseline

    This function is designed to be called after update_daily_baseline() has
    established the daily baseline. It does NOT trigger Kill-Switch or read
    threshold configuration; those responsibilities belong to Story 7.3.3.

    Args:
        state: The mutable RiskControlState instance to update.
        current_equity: Current total equity to compare against daily baseline.

    Returns:
        The calculated daily loss percentage. Returns 0.0 if daily_start_equity
        is None, zero, or negative (boundary cases).

    References:
        - Epic 7.3 / FR13: Calculate daily equity change percentage each iteration
        - Story 7.3.2: Implement daily loss percentage calculation helper
    """
    daily_start_equity = state.daily_start_equity

    # Boundary case handling (AC2): avoid division by zero or invalid baseline
    if daily_start_equity is None or daily_start_equity <= 0:
        # Safe default: set daily_loss_pct to 0.0 to avoid undefined state
        state.daily_loss_pct = 0.0
        logging.debug(
            "calculate_daily_loss_pct: invalid baseline (daily_start_equity=%s), "
            "returning 0.0",
            daily_start_equity,
        )
        return 0.0

    # Normal case: compute percentage change
    loss_pct = (current_equity - daily_start_equity) / daily_start_equity * 100

    # Update state field (AC1, AC2)
    state.daily_loss_pct = loss_pct

    logging.debug(
        "calculate_daily_loss_pct: current_equity=%.2f, daily_start_equity=%.2f, "
        "loss_pct=%.4f%%",
        current_equity,
        daily_start_equity,
        loss_pct,
    )

    return loss_pct


def check_daily_loss_limit(
    state: RiskControlState,
    current_equity: float,
    *,
    daily_loss_limit_enabled: bool = True,
    daily_loss_limit_pct: float = 5.0,
    risk_control_enabled: bool = True,
    positions_count: int = 0,
    notify_fn: Optional[Callable[[float, float, float, float], None]] = None,
    record_event_fn: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Check if daily loss limit has been reached and trigger Kill-Switch if so.

    This function is the core implementation for Epic 7.3.3. It:
    1. Calculates the current daily loss percentage using calculate_daily_loss_pct()
    2. Compares against the configured threshold (DAILY_LOSS_LIMIT_PCT)
    3. Triggers Kill-Switch via activate_kill_switch() when threshold is reached
    4. Records the event and sends notifications

    The trigger condition is: loss_pct <= -daily_loss_limit_pct
    (e.g., -6.2% <= -5.0% means the threshold is reached)

    Args:
        state: The mutable RiskControlState instance to check and update.
        current_equity: Current total equity for loss calculation.
        daily_loss_limit_enabled: Whether daily loss limit feature is enabled.
        daily_loss_limit_pct: The threshold percentage (positive value, e.g., 5.0 for 5%).
        risk_control_enabled: Whether risk control is globally enabled.
        positions_count: Current number of open positions (for notification).
        notify_fn: Optional callback for sending daily loss limit notification.
            Signature: notify_fn(loss_pct, limit_pct, daily_start_equity, current_equity).
        record_event_fn: Optional callback for recording risk control event.
            Signature: record_event_fn(action, reason).

    Returns:
        True if Kill-Switch was triggered by daily loss limit in this call
        (first time trigger only), False otherwise.

    Boundary cases (returns False without triggering):
        - DAILY_LOSS_LIMIT_ENABLED=False
        - RISK_CONTROL_ENABLED=False
        - daily_start_equity is None, 0, or negative
        - daily_loss_triggered is already True (prevents duplicate triggers)
        - loss_pct > -daily_loss_limit_pct (threshold not reached)

    References:
        - PRD FR12-FR14: Daily loss limit configuration and trigger behavior
        - Epic 7.3.3: Implement daily loss threshold trigger
        - Story 7.3.3 AC1: Core trigger logic implementation
    """
    # Boundary case 1: Feature disabled
    if not risk_control_enabled:
        logging.debug(
            "check_daily_loss_limit: skipped (RISK_CONTROL_ENABLED=False)"
        )
        return False

    if not daily_loss_limit_enabled:
        logging.debug(
            "check_daily_loss_limit: skipped (DAILY_LOSS_LIMIT_ENABLED=False)"
        )
        return False

    # Boundary case 2: Invalid daily_start_equity
    daily_start_equity = state.daily_start_equity
    if daily_start_equity is None or daily_start_equity <= 0:
        logging.debug(
            "check_daily_loss_limit: skipped (invalid daily_start_equity=%s)",
            daily_start_equity,
        )
        return False

    # Calculate current daily loss percentage (updates state.daily_loss_pct)
    loss_pct = calculate_daily_loss_pct(state, current_equity)

    # Boundary case 3: Already triggered today (prevent duplicate triggers)
    if state.daily_loss_triggered:
        logging.debug(
            "check_daily_loss_limit: already triggered today, loss_pct=%.2f%%",
            loss_pct,
        )
        return False

    # Check if threshold is reached: loss_pct <= -daily_loss_limit_pct
    # e.g., -6.2% <= -5.0% means threshold reached
    threshold = -daily_loss_limit_pct
    if loss_pct > threshold:
        logging.debug(
            "check_daily_loss_limit: threshold not reached, loss_pct=%.2f%% > %.2f%%",
            loss_pct,
            threshold,
        )
        return False

    # === Threshold reached: First-time trigger ===
    state.daily_loss_triggered = True

    # Build reason string with details
    reason = (
        f"Daily loss limit reached: {loss_pct:.2f}% <= -{daily_loss_limit_pct:.2f}%"
    )

    # Log structured warning (AC3)
    logging.warning(
        "Daily loss limit triggered: loss_pct=%.2f%%, threshold=%.2f%%, "
        "daily_start_equity=%.2f, current_equity=%.2f, first_trigger=True",
        loss_pct,
        -daily_loss_limit_pct,
        daily_start_equity,
        current_equity,
    )

    # Activate Kill-Switch (AC1, AC2)
    # Note: activate_kill_switch returns a new state, but we need to update
    # the mutable state object passed to us
    new_state = activate_kill_switch(
        state,
        reason=reason,
        positions_count=positions_count,
    )
    # Copy Kill-Switch fields back to the mutable state
    state.kill_switch_active = new_state.kill_switch_active
    state.kill_switch_reason = new_state.kill_switch_reason
    state.kill_switch_triggered_at = new_state.kill_switch_triggered_at

    # Record risk control event (AC3 - for ai_decisions.csv)
    if record_event_fn is not None:
        try:
            record_event_fn("DAILY_LOSS_LIMIT_TRIGGERED", reason)
        except Exception as e:
            logging.error(
                "Failed to record daily loss limit event: %s", e
            )

    # Send notification (AC3 - for Story 7.3.4 integration)
    if notify_fn is not None:
        try:
            notify_fn(loss_pct, daily_loss_limit_pct, daily_start_equity, current_equity)
        except Exception as e:
            logging.error(
                "Failed to send daily loss limit notification: %s", e
            )

    return True


def check_risk_limits(
    risk_control_state: RiskControlState,
    total_equity: Optional[float] = None,
    iteration_time: Optional[datetime] = None,
    risk_control_enabled: bool = True,
    *,
    daily_loss_limit_enabled: bool = True,
    daily_loss_limit_pct: float = 5.0,
    positions_count: int = 0,
    notify_daily_loss_fn: Optional[Callable[[float, float, float, float], None]] = None,
    record_event_fn: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Check risk limits at the start of each trading iteration.

    This is the unified entry point for risk control checks in the main loop.
    It is called at the beginning of each iteration, before market data fetching
    and LLM decision making.

    When Kill-Switch is active, this function returns False to signal that
    new entry trades should be blocked. Close trades and SL/TP checks are
    not affected by this function.

    Args:
        risk_control_state: The current risk control state object.
        total_equity: Current total account equity for daily loss calculation.
        iteration_time: Current iteration timestamp (optional, for future use).
        risk_control_enabled: Whether risk control is enabled (from RISK_CONTROL_ENABLED).
        daily_loss_limit_enabled: Whether daily loss limit feature is enabled.
        daily_loss_limit_pct: The threshold percentage (positive value, e.g., 5.0 for 5%).
        positions_count: Current number of open positions (for notification).
        notify_daily_loss_fn: Optional callback for daily loss limit notification.
        record_event_fn: Optional callback for recording risk control events.

    Returns:
        True if new entry trades should be allowed, False if they should be blocked
        (e.g., Kill-Switch is active or daily loss limit triggered).
    """
    if not risk_control_enabled:
        logging.info("Risk control check skipped: RISK_CONTROL_ENABLED=False")
        return True

    # Log the risk control check
    logging.debug(
        "Risk control check: kill_switch_active=%s, daily_loss_pct=%.2f%%",
        risk_control_state.kill_switch_active,
        risk_control_state.daily_loss_pct,
    )

    # Check Kill-Switch status (Epic 7.2)
    if risk_control_state.kill_switch_active:
        logging.warning(
            "Kill-Switch is active: reason=%s, triggered_at=%s",
            risk_control_state.kill_switch_reason,
            risk_control_state.kill_switch_triggered_at,
        )
        return False

    # Check daily loss limit (Epic 7.3.3)
    # Only check if we have valid equity and the feature is enabled
    if total_equity is not None and daily_loss_limit_enabled:
        triggered = check_daily_loss_limit(
            state=risk_control_state,
            current_equity=total_equity,
            daily_loss_limit_enabled=daily_loss_limit_enabled,
            daily_loss_limit_pct=daily_loss_limit_pct,
            risk_control_enabled=risk_control_enabled,
            positions_count=positions_count,
            notify_fn=notify_daily_loss_fn,
            record_event_fn=record_event_fn,
        )
        if triggered:
            # Kill-Switch was just activated by daily loss limit
            return False

    return True


def activate_kill_switch(
    state: RiskControlState,
    reason: str,
    triggered_at: Optional[datetime] = None,
    *,
    positions_count: int = 0,
    notify_fn: Optional[Callable[[str, str, int], None]] = None,
) -> RiskControlState:
    """Activate the Kill-Switch and return a new state.

    This function creates a new RiskControlState with Kill-Switch activated.
    It sets the reason and timestamp for the activation. If a notification
    callback is provided and the state actually changes, it will be called.

    Args:
        state: The current risk control state.
        reason: The reason for activating Kill-Switch (e.g., "env:KILL_SWITCH",
            "runtime:manual", "daily_loss_limit").
        triggered_at: The timestamp when Kill-Switch was triggered. If None,
            uses current UTC time.
        positions_count: Current number of open positions (for notification).
        notify_fn: Optional callback for sending activation notification.
            Signature: notify_fn(reason, triggered_at_str, positions_count).

    Returns:
        A new RiskControlState with Kill-Switch activated.
    """
    was_active = state.kill_switch_active

    if triggered_at is None:
        triggered_at = datetime.now(timezone.utc)

    triggered_at_str = triggered_at.isoformat()

    new_state = replace(
        state,
        kill_switch_active=True,
        kill_switch_reason=reason,
        kill_switch_triggered_at=triggered_at_str,
    )

    # Log state change (AC4)
    if not was_active:
        logging.warning(
            "Kill-Switch state change: old_state=inactive, new_state=active, "
            "reason=%s, positions_count=%d, triggered_at=%s",
            reason,
            positions_count,
            triggered_at_str,
        )
        # Send notification only when state actually changes (idempotency)
        if notify_fn is not None:
            try:
                notify_fn(reason, triggered_at_str, positions_count)
            except Exception as e:
                logging.error(
                    "Failed to send Kill-Switch activation notification: %s", e
                )
    else:
        logging.debug(
            "Kill-Switch activate called but was already active: reason=%s",
            reason,
        )

    return new_state


def deactivate_kill_switch(
    state: RiskControlState,
    reason: str = "runtime:resume",
    total_equity: Optional[float] = None,
    *,
    notify_fn: Optional[Callable[[str, str], None]] = None,
) -> RiskControlState:
    """Deactivate the Kill-Switch and return a new state.

    This function creates a new RiskControlState with Kill-Switch deactivated.
    It preserves the kill_switch_triggered_at field for audit purposes and
    sets a new reason indicating the deactivation. If a notification callback
    is provided and the state actually changes, it will be called.

    Args:
        state: The current risk control state.
        reason: The reason for deactivating Kill-Switch (e.g., "runtime:resume",
            "telegram:/resume", "env:KILL_SWITCH"). Defaults to "runtime:resume".
        total_equity: Current total account equity for logging (optional).
        notify_fn: Optional callback for sending deactivation notification.
            Signature: notify_fn(deactivated_at_str, reason).

    Returns:
        A new RiskControlState with Kill-Switch deactivated.
    """
    was_active = state.kill_switch_active
    previous_reason = state.kill_switch_reason
    deactivated_at = datetime.now(timezone.utc)
    deactivated_at_str = deactivated_at.isoformat()

    new_state = replace(
        state,
        kill_switch_active=False,
        kill_switch_reason=reason,
        # Preserve kill_switch_triggered_at for audit trail (AC1)
    )

    # Log the deactivation event (AC4)
    if was_active:
        equity_str = f", total_equity={total_equity:.2f}" if total_equity is not None else ""
        logging.info(
            "Kill-Switch state change: old_state=active, new_state=inactive, "
            "previous_reason=%s, deactivation_reason=%s, daily_loss_triggered=%s%s",
            previous_reason,
            reason,
            state.daily_loss_triggered,
            equity_str,
        )
        # Send notification only when state actually changes (idempotency)
        if notify_fn is not None:
            try:
                notify_fn(deactivated_at_str, reason)
            except Exception as e:
                logging.error(
                    "Failed to send Kill-Switch deactivation notification: %s", e
                )
    else:
        logging.debug(
            "Kill-Switch deactivate called but was already inactive: reason=%s",
            reason,
        )

    return new_state


def reset_daily_baseline(
    state: RiskControlState,
    current_equity: float,
    *,
    reason: str = "telegram:/reset_daily",
) -> RiskControlState:
    """Manually reset the daily loss baseline via explicit user action.

    This function is designed for the /reset_daily Telegram command. Unlike
    update_daily_baseline() which is called automatically at day boundaries,
    this function allows users to explicitly reset the daily baseline at any
    time, typically after reviewing a large drawdown and deciding to start
    a new risk window.

    The function:
    1. Updates daily_start_equity to current_equity
    2. Updates daily_start_date to current UTC date
    3. Resets daily_loss_pct to 0.0
    4. Resets daily_loss_triggered to False

    IMPORTANT: This function does NOT automatically deactivate Kill-Switch.
    Users must explicitly call /resume after /reset_daily to resume
    trading. This design prevents accidental resumption after large losses.

    Args:
        state: The mutable RiskControlState instance to update.
        current_equity: Current total equity to use as the new daily baseline.
        reason: The reason for the reset (for audit logging).

    Returns:
        A new RiskControlState with updated daily baseline fields.

    References:
        - Epic 7.4.4: Implement /reset_daily command
        - PRD FR12-FR18: Daily loss limit functionality
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Capture old values for audit logging
    old_daily_start_equity = state.daily_start_equity
    old_daily_start_date = state.daily_start_date
    old_daily_loss_pct = state.daily_loss_pct
    old_daily_loss_triggered = state.daily_loss_triggered

    # Create new state with reset daily baseline fields
    new_state = replace(
        state,
        daily_start_equity=current_equity,
        daily_start_date=today,
        daily_loss_pct=0.0,
        daily_loss_triggered=False,
    )

    # Log structured audit information (AC4)
    logging.info(
        "Daily baseline manually reset: reason=%s | "
        "old_daily_start_equity=%s | new_daily_start_equity=%.2f | "
        "old_daily_start_date=%s | new_daily_start_date=%s | "
        "old_daily_loss_pct=%.2f%% | new_daily_loss_pct=0.00%% | "
        "old_daily_loss_triggered=%s | new_daily_loss_triggered=False | "
        "kill_switch_active=%s",
        reason,
        f"{old_daily_start_equity:.2f}" if old_daily_start_equity is not None else "None",
        current_equity,
        old_daily_start_date or "None",
        today,
        old_daily_loss_pct,
        old_daily_loss_triggered,
        state.kill_switch_active,
    )

    return new_state


def apply_kill_switch_env_override(
    state: RiskControlState,
    kill_switch_env: Optional[str] = None,
    *,
    positions_count: int = 0,
    activate_notify_fn: Optional[Callable[[str, str, int], None]] = None,
    deactivate_notify_fn: Optional[Callable[[str, str], None]] = None,
) -> Tuple[RiskControlState, bool]:
    """Apply KILL_SWITCH environment variable override to the state.

    This function implements the priority logic for Kill-Switch:
    - If KILL_SWITCH env var is explicitly set to 'true' or 'false', it overrides
      the persisted state.
    - If KILL_SWITCH env var is not set, the persisted state is preserved.

    Args:
        state: The current risk control state (typically loaded from persistence).
        kill_switch_env: The value of KILL_SWITCH environment variable. If None,
            reads from os.environ.
        positions_count: Current number of open positions (for notification).
        activate_notify_fn: Optional callback for activation notification.
        deactivate_notify_fn: Optional callback for deactivation notification.

    Returns:
        A tuple of (new_state, was_overridden) where:
        - new_state: The potentially modified RiskControlState.
        - was_overridden: True if the env var caused a state change.
    """
    if kill_switch_env is None:
        kill_switch_env = os.environ.get("KILL_SWITCH")

    if kill_switch_env is None:
        # Env var not set, preserve persisted state
        return state, False

    normalized = kill_switch_env.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        # Env var explicitly enables Kill-Switch
        if not state.kill_switch_active:
            new_state = activate_kill_switch(
                state,
                reason="env:KILL_SWITCH",
                positions_count=positions_count,
                notify_fn=activate_notify_fn,
            )
            logging.warning(
                "Kill-Switch activated via environment variable: KILL_SWITCH=%s",
                kill_switch_env,
            )
            return new_state, True
        else:
            # Already active, just update reason if different
            if state.kill_switch_reason != "env:KILL_SWITCH":
                new_state = replace(state, kill_switch_reason="env:KILL_SWITCH")
                return new_state, True
            return state, False

    if normalized in {"0", "false", "no", "off"}:
        # Env var explicitly disables Kill-Switch
        if state.kill_switch_active:
            # Note: deactivate_kill_switch already logs the event, so we don't
            # duplicate the log here. The reason "env:KILL_SWITCH" indicates
            # the deactivation was triggered by environment variable.
            new_state = deactivate_kill_switch(
                state,
                reason="env:KILL_SWITCH",
                notify_fn=deactivate_notify_fn,
            )
            return new_state, True
        return state, False

    # Invalid value, preserve persisted state and log warning
    logging.warning(
        "Invalid KILL_SWITCH environment variable value '%s'; ignoring. "
        "Valid values: true, false, 1, 0, yes, no, on, off",
        kill_switch_env,
    )
    return state, False
