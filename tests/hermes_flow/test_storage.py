"""Storage tests — verify SQLite schema creation, transactions, audit, and status queries."""

import json
import tempfile
from pathlib import Path

import pytest

from hermes_flow.errors import RuntimeStateError
from hermes_flow.schemas import (
    AgentBinding,
    Artifact,
    Decision,
    FlowRun,
    MemoryMode,
    MessageEnvelope,
    RunStatus,
    _now,
)
from hermes_flow.storage import RuntimeStore


@pytest.fixture
def store(tmp_project_root: Path) -> RuntimeStore:
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / "test-run"
    return RuntimeStore(run_dir)


def test_init_schema_creates_all_tables(store: RuntimeStore) -> None:
    """Runtime initialization must create state.sqlite with all required tables."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    assert store._db_path.exists()

    conn = store.connect()
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    expected = {"runs", "agents", "states", "messages", "inboxes", "artifacts",
                "decisions", "transitions", "audit_events", "llm_input_snapshots"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_init_schema_records_initial_audit_event(store: RuntimeStore) -> None:
    """Creating a run must record an initial audit event."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    bindings = [
        AgentBinding(role_id="planner", profile_name="fp", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
    ]
    states_json = {
        "PLAN": {"actors": ["planner"], "output_artifacts": ["plan.md"]},
        "DONE": {"terminal": True},
    }
    run = store.create_run(
        flow_id="test", flow_version="1", initial_state_id="PLAN",
        agent_bindings=bindings, memory_modes={"planner": "run_isolated"},
        artifact_root=str(store.run_dir / "artifacts"),
        states_json=states_json,
    )

    audit = store.export_audit(run.run_id)
    assert len(audit) >= 1
    assert audit[0]["event_type"] == "run_created"


def test_create_run_persists_agent_specs(store: RuntimeStore) -> None:
    """Creating a run must persist full agent metadata used to build prompts."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    bindings = [
        AgentBinding(role_id="planner", profile_name="fp", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
    ]
    agent_specs = {
        "planner": {
            "role_id": "planner",
            "display_name": "Planner",
            "profile_name": "fp",
            "soul": "Plan with evidence.",
            "skills": ["speckit-plan"],
            "toolsets": ["file", "terminal"],
            "read_scope": ["spec.md"],
            "write_scope": ["artifacts/plan.md"],
            "workspace_mode": "isolated",
            "memory_mode": "run_isolated",
        }
    }

    run = store.create_run(
        flow_id="test", flow_version="1", initial_state_id="PLAN",
        agent_bindings=bindings, memory_modes={"planner": "run_isolated"},
        artifact_root=str(store.run_dir / "artifacts"),
        states_json={"PLAN": {"actors": ["planner"]}},
        agent_specs=agent_specs,
    )

    assert store.load_agent_specs(run.run_id)["planner"]["skills"] == ["speckit-plan"]
    assert store.load_agent_spec(run.run_id, "planner")["soul"] == "Plan with evidence."


def test_llm_input_snapshot_round_trip(store: RuntimeStore) -> None:
    """LLM input snapshots must preserve exact messages and omit secrets."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user prompt"},
    ]
    request = {
        "model": "test-model",
        "messages": messages,
        "headers": {"Authorization": "Bearer secret", "Content-Type": "application/json"},
    }

    snapshot_id = store.append_llm_input_snapshot(
        run_id="run1",
        session_id="sess1",
        role_id="planner",
        state_id="PLAN",
        provider="https://example.invalid/v1",
        model="test-model",
        messages=messages,
        request=request,
        context_packet={"session_id": "sess1"},
    )
    loaded = store.load_llm_input_snapshots("run1", role_id="planner", state_id="PLAN")

    assert loaded[0]["snapshot_id"] == snapshot_id
    assert loaded[0]["messages"] == messages
    assert loaded[0]["request"]["headers"]["Authorization"] == "[REDACTED]"
    assert loaded[0]["context_packet"]["session_id"] == "sess1"


def test_transaction_rollback(store: RuntimeStore) -> None:
    """A raised exception inside transaction() must leave no partial writes."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()

    # Disable FK for test that inserts audit event referencing a non-existent run
    store.connect().execute("PRAGMA foreign_keys=OFF")

    with store.transaction() as conn:
        conn.execute("INSERT INTO audit_events (event_id, run_id, state_id, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     ("manual-event", "test-run", "", "manual", "tester", "{}", _now()))
    # Verify the manual event was committed
    events = store.export_audit("test-run")
    assert events[-1]["event_id"] == "manual-event"


def test_transaction_rollback_on_error(store: RuntimeStore) -> None:
    """An exception inside transaction() must rollback all writes."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()

    # Disable FK for test
    store.connect().execute("PRAGMA foreign_keys=OFF")

    try:
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_events (event_id, run_id, state_id, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("rollback-event", "test-run", "", "manual", "tester", "{}", _now()),
            )
            raise ValueError("simulated failure")
    except ValueError:
        pass

    # The event must not be visible
    events = store.export_audit("test-run")
    event_ids = [e["event_id"] for e in events]
    assert "rollback-event" not in event_ids


def test_load_status_returns_expected_fields(store: RuntimeStore) -> None:
    """load_status() must return current state, agents, pending gate, round counters, etc."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    bindings = [
        AgentBinding(role_id="planner", profile_name="fp", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
    ]
    states_json = {
        "PLAN": {"actors": ["planner"]},
        "DONE": {"terminal": True},
    }
    run = store.create_run(
        flow_id="test", flow_version="1", initial_state_id="PLAN",
        agent_bindings=bindings, memory_modes={"planner": "run_isolated"},
        artifact_root=str(store.run_dir / "artifacts"),
        states_json=states_json,
    )

    status = store.load_status(run.run_id)
    assert status.run_id == run.run_id
    assert status.current_state_id == "PLAN"
    assert isinstance(status.round_counters, dict)


def test_resume_run_loads_last_state(store: RuntimeStore) -> None:
    """A reopened store must load the last recorded state from state.sqlite."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    bindings = [
        AgentBinding(role_id="planner", profile_name="fp", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
    ]
    states_json = {
        "PLAN": {"actors": ["planner"]},
        "DONE": {"terminal": True},
    }
    run = store.create_run(
        flow_id="test", flow_version="1", initial_state_id="PLAN",
        agent_bindings=bindings, memory_modes={},
        artifact_root=str(store.run_dir / "artifacts"),
        states_json=states_json,
    )

    # Simulate a transition
    store.record_transition(run.run_id, "PLAN", "DONE", "approve", 1)
    store.update_status(run.run_id, RunStatus.COMPLETED, _now())

    # Reopen with a new store instance
    store2 = RuntimeStore(store.run_dir)
    resumed = store2.resume_run(run.run_id)
    assert resumed.current_state_id == "DONE"
    assert resumed.status == RunStatus.COMPLETED


def test_export_audit_chronological(store: RuntimeStore) -> None:
    """Audit export must return events in chronological order."""
    store.run_dir.mkdir(parents=True, exist_ok=True)
    store.init_schema()
    bindings = [
        AgentBinding(role_id="planner", profile_name="fp", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
    ]
    states_json = {
        "PLAN": {"actors": ["planner"]},
        "DONE": {"terminal": True},
    }
    run = store.create_run(
        flow_id="test", flow_version="1", initial_state_id="PLAN",
        agent_bindings=bindings, memory_modes={},
        artifact_root=str(store.run_dir / "artifacts"),
        states_json=states_json,
    )

    store.append_audit_event(run.run_id, "msg_sent", state_id="PLAN", actor="planner", payload={"msg": "hello"})
    store.record_decision(Decision(decision_id="dec1", run_id=run.run_id, state_id="REVIEW", role_id="reviewer", value="APPROVE", created_at=_now()))
    store.record_transition(run.run_id, "PLAN", "DONE", "approve", 1)

    events = store.export_audit(run.run_id)
    timestamps = [e["created_at"] for e in events]
    assert timestamps == sorted(timestamps), "Audit events must be chronological"
    event_types = [e["event_type"] for e in events]
    assert "run_created" in event_types
