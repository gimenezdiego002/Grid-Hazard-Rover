"""Pure Relay choice admission using pollard-jev 0.1's real contracts.

This is an application policy, not the package's toy robot DecisionPolicy. It
accepts only local-controller-approved supervisory labels and never dispatches
an action or calls a provider. A rejected proposal cannot clear a local alarm.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Iterable

from pollard_jev.contracts import (
    ActionChoice,
    DecisionRequest,
    Observation,
    PolicyOutcome,
    fresh,
)


POLICY_VERSION = "relay-supervision-admission-v1"
PERMITTED_ACTIONS = (
    "hold", "request_evidence", "escalate_gemini", "continue_monitoring",
)
# Relay's simulator has relative seconds. This fixed epoch only maps those
# seconds into the package's timezone-aware temporal contracts.
SIMULATION_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_HYPOTHESES = {
    "hold": "Keep the simulated controller in safe holding for review.",
    "request_evidence": "Request one new structured observation while holding.",
    "escalate_gemini": "Request bounded Gemini interpretation while holding.",
    "continue_monitoring": "Continue passive local monitoring with no motion.",
}


@dataclass(frozen=True)
class ChoiceAdmission:
    """Admission evidence, never an action-completion or hazard-clear receipt."""

    accepted: bool
    action: str | None
    reason: str
    policy: PolicyOutcome | None = None

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "action": self.action,
            "reason": self.reason,
            "policy": self.policy.model_dump(mode="json") if self.policy else None,
            "simulated": True,
            "dispatched": False,
        }


def _seconds(value: object, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError("relative seconds must be finite numbers")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise ValueError("relative seconds are outside the permitted range")
    return number


def validate_choice(
    choice: object,
    allowed_actions: Iterable[str],
    observed_at_seconds: int | float | None,
    now_seconds: int | float,
    max_age_seconds: int | float,
    deadline_expired: bool = False,
    *,
    request_id: str = "relay-supervision",
) -> ChoiceAdmission:
    """Validate a data-only choice against the controller's current allowlist.

    ``observed_at_seconds`` identifies the controller snapshot's earliest
    required observation, not inference completion time. The caller determines
    missing/conflicting evidence, numeric thresholds and alarm state, narrows
    ``allowed_actions``, and calls this again immediately before simulated
    receipt. This gate cannot discover new observations or controller changes.

    All labels have zero parameters: Jev cannot supply servo timing, distances,
    thresholds or arbitrary commands. A score is deliberately absent because
    TypeSafe choice confidence is not a categorical probability distribution.
    """
    if type(deadline_expired) is not bool:
        return ChoiceAdmission(False, None, "invalid_deadline_context")
    if deadline_expired:
        return ChoiceAdmission(False, None, "deadline_expired")
    if observed_at_seconds is None:
        return ChoiceAdmission(False, None, "missing_observation_timestamp")
    if isinstance(allowed_actions, (str, bytes, dict)):
        return ChoiceAdmission(False, None, "invalid_allowlist")
    try:
        # At most four distinct reviewed labels are permitted. Bounded iteration
        # also avoids consuming an accidental unbounded input iterator.
        names = []
        for name in allowed_actions:
            if len(names) >= len(PERMITTED_ACTIONS):
                return ChoiceAdmission(False, None, "invalid_allowlist")
            if type(name) is not str or name not in PERMITTED_ACTIONS or name in names:
                return ChoiceAdmission(False, None, "invalid_allowlist")
            names.append(name)
    except TypeError:
        return ChoiceAdmission(False, None, "invalid_allowlist")
    if not names:
        return ChoiceAdmission(False, None, "no_permitted_action")

    try:
        observed = _seconds(observed_at_seconds)
        evaluated = _seconds(now_seconds)
        validity = _seconds(max_age_seconds, positive=True)
        observed_at = SIMULATION_EPOCH + timedelta(seconds=observed)
        evaluated_at = SIMULATION_EPOCH + timedelta(seconds=evaluated)
        valid_until = observed_at + timedelta(seconds=validity)
        request = DecisionRequest(
            request_id=request_id,
            question="Choose only a permitted Relay supervisory action; all actions are simulated.",
            created_at=observed_at,
            valid_until=valid_until,
            observations=(Observation(
                observation_id="controller-snapshot",
                source="relay-local-controller",
                feature="snapshot_available",
                value=1.0,
                unit="bool",
                observed_at=observed_at,
                valid_until=valid_until,
            ),),
            choices=tuple(ActionChoice(name=name, hypothesis=_HYPOTHESES[name])
                          for name in PERMITTED_ACTIONS if name in names),
        )
    except (TypeError, ValueError, OverflowError):
        return ChoiceAdmission(False, None, "invalid_freshness_context")

    def outcome(accepted: bool, reason: str, action: str | None = None) -> ChoiceAdmission:
        policy = PolicyOutcome(
            request_id=request.request_id,
            policy_version=POLICY_VERSION,
            disposition="accept" if accepted else "defer",
            reason=reason,
            evaluated_at=evaluated_at,
            action=action,
        )
        return ChoiceAdmission(accepted, action, reason, policy)

    # Package freshness requires every timestamp <= now < expiry, including the
    # snapshot envelope. Equality at expiry is already stale.
    if not fresh(request, evaluated_at):
        return outcome(False, "stale_or_future_evidence")
    if choice is None:
        return outcome(False, "no_proposal")
    if type(choice) is not str:
        return outcome(False, "invalid_choice")
    if choice not in {candidate.name for candidate in request.choices}:
        return outcome(False, "unauthorized_action")
    return outcome(True, "permitted_fresh_supervisory_choice", choice)
