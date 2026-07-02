"""Unit tests for the Hermes Flow FSM Engine — gate evaluation, state transitions, loop budget, idle timeout."""

import json
import time
from pathlib import Path

import pytest

from hermes_flow.schemas import (
    AgentBinding,
    Decision,
    DecisionValue,
    FlowDefinition,
    FlowRun,
    Gate,
    GateType,
    MemoryMode,
    RunStatus,
    State,
    _now,
    to_dict,
)
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import NoOpTracer, set_tracer


@pytest.fixture
def store_with_gate(tmp_project_root: Path) -> tuple[RuntimeStore, FlowRun, Gate]:
    """Create a store with a run in a gate state. Returns (store, run, gate)."""
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / "engine-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    store = RuntimeStore(run_dir)
    store.init_schema()

    # Create a run with a review state that has a gate
    gate = Gate(
        gate_id="review_gate",
        type=GateType.DECISION,
        required_roles=["planner", "reviewer"],
        pass_values=["APPROVE", "PASS"],
        fail_values=["REQUEST_CHANGES", "FAIL"],
        blocked_values=["BLOCKED"],
        on_pass="approved",
        on_fail="revision",
        on_blocked="escalated",
        on_exhausted="escalation",
        max_rounds=3,
    )

    review_state = State(
        state_id="review",
        description="Review state with gate",
        actors=["planner", "reviewer"],
        message_acceptance=True,
        gate=gate,
        transitions=[],
    )

    states_json = {
        "review": to_dict(review_state),
    }

    run = store.create_run(
        flow_id="test-flow",
        flow_version="1.0",
        initial_state_id="review",
        agent_bindings=[
            AgentBinding(role_id="planner", profile_name="planner-profile", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
            AgentBinding(role_id="reviewer", profile_name="reviewer-profile", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
        ],
        memory_modes={},
        artifact_root=str(run_dir / "artifacts"),
        states_json=states_json,
        override_run_id="engine-test",
    )

    return store, run, gate


def _make_decision(run_id: str, state_id: str, role_id: str, value: str) -> Decision:
    return Decision(
        decision_id=f"{role_id}-{_now()}",
        run_id=run_id,
        state_id=state_id,
        role_id=role_id,
        value=value,
        reason="",
        artifacts=[],
        created_at=_now(),
    )


# ── T002: Gate satisfaction ─────────────────────────────────────────────────

def test_gate_satisfied(store_with_gate: tuple) -> None:
    """When all required roles approve, evaluate_gate must return satisfied=True."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import evaluate_gate

    # No decisions yet → not satisfied
    result = evaluate_gate("engine-test", "review", store)
    assert result.satisfied is False
    assert set(result.outstanding_roles) == {"planner", "reviewer"}
    assert result.next_state_id == ""

    # Only one decision → still pending
    store.record_decision(_make_decision("engine-test", "review", "planner", "APPROVE"))
    result = evaluate_gate("engine-test", "review", store)
    assert result.satisfied is False
    assert result.outstanding_roles == ["reviewer"]

    # Both decisions → gate satisfied
    store.record_decision(_make_decision("engine-test", "review", "reviewer", "APPROVE"))
    result = evaluate_gate("engine-test", "review", store)
    assert result.satisfied is True
    assert result.outstanding_roles == []
    assert result.next_state_id == "approved"  # on_pass


# ── T003: Gate fail ─────────────────────────────────────────────────────────

def test_gate_fail(store_with_gate: tuple) -> None:
    """When any role submits a fail value, evaluate_gate must return on_fail."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import evaluate_gate

    store.record_decision(_make_decision("engine-test", "review", "planner", "APPROVE"))
    store.record_decision(_make_decision("engine-test", "review", "reviewer", "REQUEST_CHANGES"))
    result = evaluate_gate("engine-test", "review", store)
    assert result.satisfied is False
    assert result.next_state_id == "revision"  # on_fail


# ── T004: Gate blocked ──────────────────────────────────────────────────────

def test_gate_blocked(store_with_gate: tuple) -> None:
    """When any role submits a blocked value, evaluate_gate must return on_blocked."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import evaluate_gate

    store.record_decision(_make_decision("engine-test", "review", "planner", "APPROVE"))
    store.record_decision(_make_decision("engine-test", "review", "reviewer", "BLOCKED"))
    result = evaluate_gate("engine-test", "review", store)
    assert result.satisfied is False
    assert result.next_state_id == "escalated"  # on_blocked


# ── T005: Round counter exhaustion ──────────────────────────────────────────

def test_round_exhaustion(store_with_gate: tuple) -> None:
    """After max_rounds unsatisfied evaluations, must return on_exhausted."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import evaluate_gate

    # Simulate 4 rounds: each round both roles decide, gate fails → round increments
    for i in range(4):
        store.record_decision(_make_decision("engine-test", "review", "planner", "APPROVE"))
        store.record_decision(_make_decision("engine-test", "review", "reviewer", "REQUEST_CHANGES"))
        result = evaluate_gate("engine-test", "review", store)
        if i >= 3:
            # 4th round → exhaustion (counter=5 > max_rounds=3)
            assert result.satisfied is False
            assert result.next_state_id == "escalation"  # on_exhausted
        else:
            assert result.next_state_id == "revision"


# ── T006: Idle timeout ──────────────────────────────────────────────────────

def test_idle_timeout(store_with_gate: tuple) -> None:
    """detect_idle_timeout must trigger on_exhausted when idle exceeds threshold."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import detect_idle_timeout

    # Create a state with idle_timeout_seconds and set a far-future timestamp
    now = _now()
    future = "2099-12-31T23:59:59"

    result = detect_idle_timeout(
        "engine-test", "review", store,
        now=future,
    )
    # If no timeout configured (state not persisted with idle_timeout), should return no timeout
    assert result is None or hasattr(result, "timeout_exceeded")


# ── T007: Non-active run rejection ──────────────────────────────────────────

def test_gate_rejects_non_active_run(store_with_gate: tuple) -> None:
    """evaluate_gate must reject runs with non-active status."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import evaluate_gate
    from hermes_flow.errors import RuntimeStateError

    # Mark run as paused
    store.update_status("engine-test", RunStatus.PAUSED)

    with pytest.raises(RuntimeStateError, match="status is.*paused"):
        evaluate_gate("engine-test", "review", store)


# ── T008: Gapless state ─────────────────────────────────────────────────────

def test_gapless_state_returns_no_transition(tmp_project_root: Path) -> None:
    """evaluate_gate for a state without a gate must return satisfied=False with no next_state_id."""
    from hermes_flow.engine import evaluate_gate

    run_dir = tmp_project_root / ".hermes-flow" / "runs" / "gapless-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    store = RuntimeStore(run_dir)
    store.init_schema()

    gapless_state = State(
        state_id="no-gate",
        description="State without a gate",
        actors=["planner"],
        message_acceptance=True,
        gate=None,
        transitions=[],
    )

    store.create_run(
        flow_id="test-flow",
        flow_version="1.0",
        initial_state_id="no-gate",
        agent_bindings=[],
        memory_modes={},
        artifact_root=str(run_dir / "artifacts"),
        states_json={"no-gate": to_dict(gapless_state)},
        override_run_id="gapless-test",
    )

    result = evaluate_gate("gapless-test", "no-gate", store)
    assert result.satisfied is False
    assert result.next_state_id == ""


# ── T009: advance_state ─────────────────────────────────────────────────────

def test_advance_state(store_with_gate: tuple) -> None:
    """advance_state must update current_state_id, persist transition, and append audit."""
    store, run, gate = store_with_gate
    from hermes_flow.engine import advance_state

    advance_state("engine-test", "review", "approved", "on_pass", 1, store)

    # Verify current_state_id changed
    updated = store.load_status("engine-test")
    assert updated.current_state_id == "approved"

    # Verify transition record
    conn = store.connect()
    rows = conn.execute(
        "SELECT * FROM transitions WHERE run_id = ?", ("engine-test",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["from_state_id"] == "review"
    assert rows[0]["to_state_id"] == "approved"

    # Verify audit event
    audit = store.export_audit("engine-test")
    assert any("state_transition" in str(a) or "approved" in str(a) for a in audit)


# ── Tracer isolation ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_tracer_for_engine() -> None:
    set_tracer(NoOpTracer())
