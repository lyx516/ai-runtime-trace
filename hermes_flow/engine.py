"""FSM Engine — gate evaluation, state transitions, loop budget, idle timeout.

Stateless module that reads from and writes to RuntimeStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from hermes_flow.errors import RuntimeStateError
from hermes_flow.schemas import (
    DecisionValue,
    RunStatus,
    _now,
    from_dict,
    to_dict,
)
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import get_tracer


# ── Result types ────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    """Outcome of evaluate_gate()."""
    satisfied: bool = False
    next_state_id: str = ""
    outstanding_roles: list[str] = field(default_factory=list)
    round: int = 0
    reason: str = ""


@dataclass
class IdleTimeoutResult:
    """Outcome of detect_idle_timeout()."""
    timeout_exceeded: bool = False
    next_state_id: str = ""
    reason: str = ""


# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_last_transition_into_state(
    store: RuntimeStore,
    run_id: str,
    state_id: str,
) -> Optional[dict[str, Any]]:
    """Find the most recent transition INTO state_id. Returns row dict or None."""
    conn = store.connect()
    rows = conn.execute(
        "SELECT * FROM transitions WHERE run_id = ? AND to_state_id = ? ORDER BY created_at DESC LIMIT 1",
        (run_id, state_id),
    ).fetchall()
    return dict(rows[0]) if rows else None


def _load_state_definition(
    store: RuntimeStore,
    run_id: str,
    state_id: str,
) -> Optional[dict[str, Any]]:
    """Load the state JSON from the states table."""
    conn = store.connect()
    row = conn.execute(
        "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
        (run_id, state_id),
    ).fetchone()
    if row is None:
        return None
    from json import loads
    return loads(row["state_json"])


def _get_gate_from_state(state_dict: dict[str, Any] | None) -> Optional[dict[str, Any]]:
    """Extract the gate dict from a state dict."""
    if state_dict is None:
        return None
    gate = state_dict.get("gate")
    if not gate:
        return None
    return gate


# ── evaluate_gate ───────────────────────────────────────────────────────────

def evaluate_gate(
    run_id: str,
    state_id: str,
    store: RuntimeStore,
) -> GateResult:
    """Evaluate the gate for a state, returning gate status with possible transition target.

    Steps:
    1. Verify run is active.
    2. Load state definition and check for gate.
    3. Find last transition INTO this state (for round filtering).
    4. Load decisions created since that transition.
    5. Determine outstanding roles and classify decisions.
    6. Return GateResult with transition target if triggered.
    """
    # 1. Verify run is active
    run = store.load_status(run_id)
    if run.run_id != run_id:
        raise RuntimeStateError(f"Run {run_id} not found")
    if run.status != RunStatus.ACTIVE:
        raise RuntimeStateError(f"Run {run_id} status is '{run.status.value}', not 'active'")

    # 2. Load state and gate
    state_dict = _load_state_definition(store, run_id, state_id)
    if state_dict is None:
        raise RuntimeStateError(f"State {state_id} not found in run {run_id}")

    gate_dict = _get_gate_from_state(state_dict)
    if gate_dict is None:
        # No gate → return unsatisfied with no transition (per Clarify Q2)
        return GateResult(
            satisfied=False,
            next_state_id="",
            outstanding_roles=[],
            round=0,
            reason=f"State '{state_id}' has no gate",
        )

    required_roles = gate_dict.get("required_roles", [])
    pass_values = gate_dict.get("pass_values", ["APPROVE", "PASS"])
    fail_values = gate_dict.get("fail_values", ["REQUEST_CHANGES", "FAIL"])
    blocked_values = gate_dict.get("blocked_values", ["BLOCKED"])
    on_pass = gate_dict.get("on_pass", "")
    on_fail = gate_dict.get("on_fail", "")
    on_blocked = gate_dict.get("on_blocked", "")
    on_exhausted = gate_dict.get("on_exhausted", "")
    max_rounds = gate_dict.get("max_rounds", 0)

    # 3. Find last transition INTO this state for round filtering
    last_transition = _load_last_transition_into_state(store, run_id, state_id)
    cutoff = last_transition["created_at"] if last_transition else "1970-01-01T00:00:00"

    # 4. Load current decisions (since cutoff)
    all_decisions = store.load_decisions(run_id, state_id)
    current_decisions = [d for d in all_decisions if d.created_at >= cutoff]

    # 5. Build decision map per role and classify
    role_decisions: dict[str, str] = {}  # role_id → value
    has_change_request = False
    has_blocked = False

    for d in current_decisions:
        role_decisions[d.role_id] = d.value
        if d.value in fail_values:
            has_change_request = True
        if d.value in blocked_values:
            has_blocked = True

    # Determine outstanding roles
    outstanding = [r for r in required_roles if r not in role_decisions]

    # Get current round from round_counters
    round_counters = getattr(run, "round_counters", {})
    current_round = round_counters.get(state_id, 1)

    if outstanding:
        return GateResult(
            satisfied=False,
            next_state_id="",
            outstanding_roles=outstanding,
            round=current_round,
            reason=f"Waiting for decisions from: {', '.join(outstanding)}",
        )

    # 6. Classify gate outcome
    # Check pass first (all required roles must be in pass_values)
    all_pass = all(v in pass_values for v in role_decisions.values())
    if all_pass:
        return GateResult(
            satisfied=True,
            next_state_id=on_pass,
            outstanding_roles=[],
            round=current_round,
            reason=f"Gate satisfied: all {len(required_roles)} roles approved",
        )

    # Check blocked (highest priority — block overrides change request)
    if has_blocked:
        next_round = current_round + 1
        # Update round counter
        round_counters[state_id] = next_round
        conn = store.connect()
        from json import dumps as json_dumps
        conn.execute(
            "UPDATE runs SET round_counters = ? WHERE run_id = ?",
            (json_dumps(round_counters), run_id),
        )
        conn.commit()

        blocking_roles = [r for r, v in role_decisions.items() if v in blocked_values]
        return GateResult(
            satisfied=False,
            next_state_id=on_blocked,
            outstanding_roles=[],
            round=next_round,
            reason=f"Blocked by {', '.join(blocking_roles)}",
        )

    # Check fail / change request
    if has_change_request:
        next_round = current_round + 1

        # Check exhaustion before advancing
        if max_rounds > 0 and current_round > max_rounds:
            round_counters[state_id] = next_round
            conn = store.connect()
            from json import dumps as json_dumps
            conn.execute(
                "UPDATE runs SET round_counters = ? WHERE run_id = ?",
                (json_dumps(round_counters), run_id),
            )
            conn.commit()
            return GateResult(
                satisfied=False,
                next_state_id=on_exhausted,
                outstanding_roles=[],
                round=next_round,
                reason=f"Round {next_round} exhausted (max_rounds={max_rounds})",
            )

        # Increment round counter
        round_counters[state_id] = next_round
        conn = store.connect()
        from json import dumps as json_dumps
        conn.execute(
            "UPDATE runs SET round_counters = ? WHERE run_id = ?",
            (json_dumps(round_counters), run_id),
        )
        conn.commit()

        failing_roles = [r for r, v in role_decisions.items() if v in fail_values]
        return GateResult(
            satisfied=False,
            next_state_id=on_fail,
            outstanding_roles=[],
            round=next_round,
            reason=f"Change requested by {', '.join(failing_roles)}",
        )

    # Fallback — decisions present but none match known categories
    return GateResult(
        satisfied=False,
        next_state_id="",
        outstanding_roles=outstanding,
        round=current_round,
        reason="Decisions present but no gate outcome determined",
    )


# ── detect_idle_timeout ─────────────────────────────────────────────────────

def detect_idle_timeout(
    run_id: str,
    state_id: str,
    store: RuntimeStore,
    now: str | None = None,
) -> IdleTimeoutResult | None:
    """Check if the state's idle timeout has been exceeded.

    Returns None or IdleTimeoutResult if the state has no idle_timeout_seconds configured.
    Returns IdleTimeoutResult(timeout_exceeded=True) if the timeout is exceeded.
    """
    state_dict = _load_state_definition(store, run_id, state_id)
    if state_dict is None:
        return None

    idle_timeout = state_dict.get("idle_timeout_seconds")
    if idle_timeout is None:
        return None  # No timeout configured

    current_time = now or _now()

    # Find last activity timestamp from transitions or audit events for this state
    conn = store.connect()
    activity_row = conn.execute(
        """SELECT MAX(created_at) as last_activity FROM (
            SELECT created_at FROM transitions WHERE run_id = ? AND to_state_id = ?
            UNION ALL
            SELECT created_at FROM decisions WHERE run_id = ? AND state_id = ?
        )""",
        (run_id, state_id, run_id, state_id),
    ).fetchone()

    if activity_row is None or activity_row["last_activity"] is None:
        # No activity yet since entering the state — use state entry time
        last_transition = _load_last_transition_into_state(store, run_id, state_id)
        if last_transition is None:
            return None
        last_activity = last_transition["created_at"]
    else:
        last_activity = activity_row["last_activity"]

    # Compare elapsed time
    try:
        from datetime import datetime, timezone
        last_dt = datetime.fromisoformat(last_activity)
        now_dt = datetime.fromisoformat(current_time)
        elapsed = (now_dt - last_dt).total_seconds()
    except Exception:
        return None

    on_exhausted = state_dict.get("on_exhausted", "")

    if elapsed >= idle_timeout:
        return IdleTimeoutResult(
            timeout_exceeded=True,
            next_state_id=on_exhausted if on_exhausted else "",
            reason=f"Idle timeout exceeded: {elapsed:.0f}s >= {idle_timeout}s",
        )

    return IdleTimeoutResult(
        timeout_exceeded=False,
        reason=f"Idle time {elapsed:.0f}s < {idle_timeout}s",
    )


# ── advance_state ───────────────────────────────────────────────────────────

def advance_state(
    run_id: str,
    from_state_id: str,
    to_state_id: str,
    gate_result: str,
    round_counter: int,
    store: RuntimeStore,
) -> None:
    """Advance the run to a new state.

    Persists transition record, updates current_state_id, resets round counter
    for the new state, and appends an audit event. If the new state is terminal,
    sets run status to completed.
    """
    tracer = get_tracer()
    with tracer.span("advance_state", inputs={
        "run_id": run_id,
        "from_state_id": from_state_id,
        "to_state_id": to_state_id,
        "gate_result": gate_result,
    }) as span:
        # Record the transition
        store.record_transition(run_id, from_state_id, to_state_id, gate_result, round_counter)

        # Update current_state_id via record_transition already does this, but
        # we also need to ensure the round counter is reset for the new state
        run = store.load_status(run_id)
        round_counters = getattr(run, "round_counters", {})
        # Don't reset counter — record_transition already persists it.
        # The new state's round counter starts at 1 (default on first evaluate_gate).

        # Check if the target state is terminal
        state_dict = _load_state_definition(store, run_id, to_state_id)
        if state_dict and state_dict.get("terminal", False):
            store.update_status(run_id, RunStatus.COMPLETED, completed_at=_now())
            store.append_audit_event(
                run_id=run_id,
                event_type="flow_completed",
                state_id=to_state_id,
                actor="system",
                payload={"gate_result": gate_result, "previous_state": from_state_id},
            )
        else:
            store.append_audit_event(
                run_id=run_id,
                event_type="state_transition",
                state_id=to_state_id,
                actor="system",
                payload={
                    "gate_result": gate_result,
                    "from_state": from_state_id,
                    "to_state": to_state_id,
                    "round": round_counter,
                },
            )

        span.outputs = {
            "from_state_id": from_state_id,
            "to_state_id": to_state_id,
            "gate_result": gate_result,
        }
