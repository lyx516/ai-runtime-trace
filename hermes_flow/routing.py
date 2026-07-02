"""Message Router — recipient validation, atomic zero-delivery routing.

Pure validation: never writes to storage. Returns RouteValidation result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from hermes_flow.storage import RuntimeStore


# ── Result type ────────────────────────────────────────────────────────────

@dataclass
class RouteValidation:
    """Result of validate_message()."""
    valid: bool = False
    authorized_recipients: list[str] = field(default_factory=list)
    invalid_recipients: list[str] = field(default_factory=list)
    unavailable_recipients: list[str] = field(default_factory=list)
    reason: Optional[str] = None


# ── validate_message ────────────────────────────────────────────────────────

def validate_message(
    run_id: str,
    state_id: str,
    from_role: str,
    intended_recipients: list[str],
    routing_policies: dict[str, list[str]],
    store: RuntimeStore,
) -> RouteValidation:
    """Validate a message send against routing policy and recipient availability.

    Returns RouteValidation with valid=False if ANY intended recipient is
    unauthorized or unavailable. The caller is responsible for persisting the
    message record and inbox entries (FR-013).

    Args:
        run_id: The run identifier.
        state_id: The current state id (for availability lookups).
        from_role: The sender role.
        intended_recipients: List of recipients intended by the sender.
        routing_policies: Dict mapping sender_role -> list[allowed recipient roles].
        store: RuntimeStore for reading state definitions and run status.

    Returns:
        RouteValidation with validity, classification lists, and reason.
    """
    # Validate non-empty recipients
    if not intended_recipients:
        return RouteValidation(
            valid=False,
            reason="No recipients specified",
        )

    # Get the allowed recipients for this sender role
    allowed_recipients = routing_policies.get(from_role, [])

    # Fetch run info for current_state_id lookups
    conn = store.connect()
    run_row = conn.execute(
        "SELECT current_state_id, status FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        return RouteValidation(
            valid=False,
            reason=f"Run {run_id} not found",
        )

    # Determine which states accept messages (terminal & message_acceptance=False
    # states are unavailable). We need to check each recipient's CURRENT state.
    # Since a run has one current state, all recipients share it unless we track
    # per-role states (which we don't in the current model).
    # The simplest approach: check the run's current state.
    current_state_id = run_row["current_state_id"]
    current_status = run_row["status"]

    # Load state definition
    state_row = conn.execute(
        "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
        (run_id, state_id),
    ).fetchone()
    if state_row is None:
        return RouteValidation(
            valid=False,
            reason=f"State {state_id} not found for run {run_id}",
        )

    from json import loads as json_loads

    # Load the run's CURRENT state definition for availability check
    current_state_row = conn.execute(
        "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
        (run_id, current_state_id),
    ).fetchone()
    current_state_dict = json_loads(current_state_row["state_json"]) if current_state_row else {}
    message_acceptance = current_state_dict.get("message_acceptance", True)
    is_terminal_state = current_state_dict.get("terminal", False)

    # Check each intended recipient
    invalid: list[str] = []
    unavailable: list[str] = []
    authorized: list[str] = []

    for recipient in intended_recipients:
        # Check authorization
        if recipient not in allowed_recipients:
            invalid.append(recipient)
            continue

        # Check availability: recipient is in the run's agent list
        agent_row = conn.execute(
            "SELECT 1 FROM agents WHERE run_id = ? AND role_id = ?",
            (run_id, recipient),
        ).fetchone()
        if agent_row is None:
            invalid.append(recipient)
            continue

        # Check if the recipient's current state accepts messages.
        # Since all agents share the run's current_state_id, we check:
        # - The run's current state must accept messages
        # - The run must not be terminal/completed/aborted
        if not message_acceptance or is_terminal_state or current_status in ("completed", "aborted"):
            unavailable.append(recipient)
            continue

        authorized.append(recipient)

    # Determine overall validity
    if invalid or unavailable:
        parts = []
        if invalid:
            parts.append(f"unauthorized recipients: {invalid}")
        if unavailable:
            parts.append(f"unavailable recipients: {unavailable}")
        return RouteValidation(
            valid=False,
            authorized_recipients=authorized,
            invalid_recipients=invalid,
            unavailable_recipients=unavailable,
            reason="; ".join(parts),
        )

    return RouteValidation(
        valid=True,
        authorized_recipients=authorized,
        reason=None,
    )
