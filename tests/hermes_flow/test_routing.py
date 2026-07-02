"""Unit tests for the Message Router — recipient validation, atomic zero-delivery routing."""

from pathlib import Path

import pytest

from hermes_flow.routing import RouteValidation, validate_message
from hermes_flow.schemas import (
    AgentBinding,
    MemoryMode,
    State,
    _now,
    to_dict,
)
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import NoOpTracer, set_tracer


@pytest.fixture
def store_with_states(tmp_project_root: Path) -> tuple[RuntimeStore, Path]:
    """Create a store with 3 states: active, no-message, terminal."""
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / "router-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    store = RuntimeStore(run_dir)
    store.init_schema()

    states = {}
    # State A — accepts messages
    state_a = State(
        state_id="planning",
        description="Planning state",
        actors=["planner", "developer"],
        message_acceptance=True,
        gate=None,
        transitions=[],
    )
    states["planning"] = to_dict(state_a)

    # State B — message_acceptance=False (inbox-inactive)
    state_b = State(
        state_id="pending",
        description="Pending state, no messaging",
        actors=["developer"],
        message_acceptance=False,
        gate=None,
        transitions=[],
    )
    states["pending"] = to_dict(state_b)

    # State C — terminal (inbox-inactive)
    state_c = State(
        state_id="completed",
        description="Terminal state",
        actors=[],
        message_acceptance=False,
        gate=None,
        transitions=[],
        terminal=True,
    )
    states["completed"] = to_dict(state_c)

    store.create_run(
        flow_id="test-flow",
        flow_version="1.0",
        initial_state_id="planning",
        agent_bindings=[
            AgentBinding(role_id="planner", profile_name="planner-profile", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
            AgentBinding(role_id="developer", profile_name="dev-profile", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
            AgentBinding(role_id="reviewer", profile_name="reviewer-profile", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
        ],
        memory_modes={},
        artifact_root=str(run_dir / "artifacts"),
        states_json=states,
        override_run_id="router-test",
    )

    return store, run_dir


def test_router_unauthorized(store_with_states: tuple) -> None:
    """Message intended for unauthorized recipient must be rejected."""
    store, run_dir = store_with_states

    routing_policies = {"planner": ["developer", "reviewer"]}

    result = validate_message(
        run_id="router-test",
        state_id="planning",
        from_role="planner",
        intended_recipients=["developer", "reviewer", "outsider"],
        routing_policies=routing_policies,
        store=store,
    )
    assert result.valid is False
    assert "outsider" in result.invalid_recipients
    assert result.reason is not None


def test_router_unavailable(store_with_states: tuple) -> None:
    """Message intended for inbox-inactive recipient must be rejected."""
    store, run_dir = store_with_states

    routing_policies = {"planner": ["developer"]}

    # Developer is in "pending" state → not accepting messages
    store.connect().execute(
        "UPDATE runs SET current_state_id = ? WHERE run_id = ?",
        ("pending", "router-test"),
    )
    store.connect().commit()

    result = validate_message(
        run_id="router-test",
        state_id="planning",
        from_role="planner",
        intended_recipients=["developer"],
        routing_policies=routing_policies,
        store=store,
    )
    assert result.valid is False, f"Expected rejected, got {result}"
    assert "developer" in result.unavailable_recipients
    assert result.reason is not None


def test_router_accepts(store_with_states: tuple) -> None:
    """Message where all recipients are authorized and available must be accepted."""
    store, run_dir = store_with_states

    routing_policies = {"planner": ["developer", "reviewer"]}

    result = validate_message(
        run_id="router-test",
        state_id="planning",
        from_role="planner",
        intended_recipients=["developer", "reviewer"],
        routing_policies=routing_policies,
        store=store,
    )
    assert result.valid is True
    assert result.invalid_recipients == []
    assert result.unavailable_recipients == []
    assert result.reason is None
    assert set(result.authorized_recipients) == {"developer", "reviewer"}


def test_router_empty_recipients(store_with_states: tuple) -> None:
    """Empty intended_recipients must be rejected."""
    store, run_dir = store_with_states

    result = validate_message(
        run_id="router-test",
        state_id="planning",
        from_role="planner",
        intended_recipients=[],
        routing_policies={},
        store=store,
    )
    assert result.valid is False
    assert result.reason is not None


def test_router_mixed_rejection(store_with_states: tuple) -> None:
    """Message with both unauthorized AND unavailable must report both."""
    store, run_dir = store_with_states

    routing_policies = {"planner": ["developer"]}

    # Developer is in terminal state → unavailable
    store.connect().execute(
        "UPDATE runs SET current_state_id = ? WHERE run_id = ?",
        ("completed", "router-test"),
    )
    store.connect().commit()

    result = validate_message(
        run_id="router-test",
        state_id="planning",
        from_role="planner",
        intended_recipients=["developer", "outsider"],
        routing_policies=routing_policies,
        store=store,
    )
    assert result.valid is False
    assert "outsider" in result.invalid_recipients
    assert "developer" in result.unavailable_recipients


def test_router_no_store_mutation(store_with_states: tuple) -> None:
    """validate_message must not call any write methods on the store."""
    store, run_dir = store_with_states

    routing_policies = {"planner": ["developer"]}

    # Count rows before
    conn = store.connect()
    msg_count_before = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    inbox_count_before = conn.execute("SELECT COUNT(*) FROM inboxes").fetchone()[0]

    result = validate_message(
        run_id="router-test",
        state_id="planning",
        from_role="planner",
        intended_recipients=["developer"],
        routing_policies=routing_policies,
        store=store,
    )

    msg_count_after = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    inbox_count_after = conn.execute("SELECT COUNT(*) FROM inboxes").fetchone()[0]

    assert msg_count_after == msg_count_before, "Router should not create message records"
    assert inbox_count_after == inbox_count_before, "Router should not create inbox entries"
    assert result.valid is True


@pytest.fixture(autouse=True)
def _reset_tracer() -> None:
    set_tracer(NoOpTracer())
