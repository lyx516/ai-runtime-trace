"""Tests for quick_evaluate — deterministic run scoring."""

import tempfile
from pathlib import Path

import pytest

from hermes_flow.evaluator import quick_evaluate
from hermes_flow.storage import RuntimeStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        s = RuntimeStore(td)
        s.init_schema()
        yield s


def _seed_run(store, run_id, status="completed"):
    """Insert a minimal run row for testing."""
    conn = store.connect()
    conn.execute(
        "INSERT INTO runs (run_id, flow_id, flow_version, status, current_state_id, "
        "round_counters, created_at, updated_at, agent_bindings, agent_specs, "
        "memory_modes, artifact_root) "
        "VALUES (?, 'test', '1', ?, 'DONE', '{}', '', '', '[]', '{}', '{}', '')",
        (run_id, status),
    )
    conn.commit()


def test_quick_evaluate_completed_run(store):
    """Completed run → score 85, with telemetry-driven agent_scores."""
    run_id = "eval-test-001"
    _seed_run(store, run_id, "completed")

    conn = store.connect()
    # 2 thinking events for agent-a, 1 for agent-b
    for _ in range(2):
        conn.execute(
            "INSERT INTO thinking_events (run_id, role_id, state_id, step_type, "
            "inputs_json, output_json, created_at) VALUES (?, 'agent-a', 'IMPL', "
            "'file_write', '{}', '{}', '')",
            (run_id,),
        )
    conn.execute(
        "INSERT INTO thinking_events (run_id, role_id, state_id, step_type, "
        "inputs_json, output_json, created_at) VALUES (?, 'agent-b', 'REVIEW', "
        "'file_read', '{}', '{}', '')",
        (run_id,),
    )
    # 1 decision for agent-a
    conn.execute(
        "INSERT INTO decisions (decision_id, run_id, state_id, role_id, value, "
        "reason, artifacts, created_at) VALUES ('d1', ?, 'IMPL', 'agent-a', "
        "'APPROVE', '', '[]', '')",
        (run_id,),
    )
    # 1 transition
    conn.execute(
        "INSERT INTO transitions (run_id, from_state_id, to_state_id, gate_result, "
        "round_counter, created_at) VALUES (?, 'IMPL', 'DONE', 'pass', 1, '')",
        (run_id,),
    )
    conn.commit()

    result = quick_evaluate(store, run_id)

    assert result is not None
    assert result["success_score"] == 85
    assert result["bottleneck_state"] == "IMPL"
    assert "file_write" in result["tool_stats"]
    assert result["tool_stats"]["file_write"] == 2
    # agent-a: base 70 + min(2*2, 20)=4 + min(1*5, 10)=5 = 79
    assert result["agent_scores"]["agent-a"] == 79
    # agent-b: base 70 + min(1*2, 20)=2 + min(0*5, 10)=0 = 72
    assert result["agent_scores"]["agent-b"] == 72


def test_quick_evaluate_non_completed_run(store):
    """Non-completed run → score = max(30, 50 - transitions*5)."""
    run_id = "eval-test-002"
    _seed_run(store, run_id, "active")

    # No transitions, no events
    result = quick_evaluate(store, run_id)

    assert result["success_score"] == 50  # max(30, 50 - 0*5)


def test_quick_evaluate_many_transitions_caps_at_30(store):
    """5+ transitions → score floors at 30."""
    run_id = "eval-test-003"
    _seed_run(store, run_id, "active")

    conn = store.connect()
    for i in range(6):
        conn.execute(
            "INSERT INTO transitions (run_id, from_state_id, to_state_id, "
            "gate_result, round_counter, created_at) VALUES (?, ?, ?, '', 1, '')",
            (run_id, f"S{i}", f"S{i+1}"),
        )
    conn.commit()

    result = quick_evaluate(store, run_id)
    assert result["success_score"] == 30  # max(30, 50 - 6*5) = max(30, 20) = 30


def test_quick_evaluate_empty_run(store):
    """Empty run (no telemetry) → should not crash, agent_scores empty."""
    run_id = "eval-test-004"
    _seed_run(store, run_id, "completed")

    result = quick_evaluate(store, run_id)

    assert result["success_score"] == 85
    assert result["agent_scores"] == {}
    assert result["bottleneck_state"] == "?"