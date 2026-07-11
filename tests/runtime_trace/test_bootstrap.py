"""Tests for bootstrap_runtime — handler registration + MESSAGE_SENT persistence."""

import json
import tempfile
from uuid import uuid4

import pytest

from runtime_trace.bootstrap import bootstrap_runtime
from runtime_trace.hooks import Hook, emit, get_bus, reset_bus
from runtime_trace.storage import RuntimeStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as td:
        s = RuntimeStore(td)
        s.init_schema()
        yield s


def _seed_run(store, run_id, status="completed"):
    conn = store.connect()
    conn.execute(
        "INSERT INTO runs (run_id, flow_id, flow_version, status, current_state_id, "
        "round_counters, created_at, updated_at, agent_bindings, agent_specs, "
        "memory_modes, artifact_root) "
        "VALUES (?, 'test', '1', ?, 'DONE', '{}', '', '', '[]', '{}', '{}', '')",
        (run_id, status),
    )
    conn.commit()


@pytest.fixture
def clean_bus():
    reset_bus()
    yield
    reset_bus()


def test_bootstrap_registers_all_handlers(store, clean_bus):
    """bootstrap_runtime should register handlers for all 7 hooks."""
    run_id = "boot-test-001"
    _seed_run(store, run_id)

    bootstrap_runtime(store, run_id, enable_observer=False)

    bus = get_bus()
    expected_hooks = [
        Hook.LLM_DONE,
        Hook.TOOL_DONE,
        Hook.TURN_END,
        Hook.SESSION_DECIDE,
        Hook.SESSION_DONE,
        Hook.MESSAGE_SENT,
        Hook.RUN_COMPLETED,
    ]
    for h in expected_hooks:
        assert h in bus._handlers, f"Hook {h} not registered"
        assert len(bus._handlers[h]) >= 1, f"Hook {h} has no handlers"


def test_message_sent_handler_persists_message(store, clean_bus):
    """emit(MESSAGE_SENT) → store should have message + inbox rows."""
    run_id = "boot-test-002"
    _seed_run(store, run_id)

    bootstrap_runtime(store, run_id, enable_observer=False)

    msg_id = uuid4().hex[:12]
    emit(Hook.MESSAGE_SENT, {
        "message_id": msg_id,
        "run_id": run_id,
        "state_id": "SPEC",
        "from_role": "spec-writer",
        "recipients": ["plan-maker", "implementer"],
        "content": "spec is ready",
        "kind": "question",
        "delivery_outcome": "delivered",
    })

    conn = store.connect()

    # Message row exists
    msg = conn.execute(
        "SELECT * FROM messages WHERE message_id=?", (msg_id,)
    ).fetchone()
    assert msg is not None
    assert msg["from_role"] == "spec-writer"
    assert msg["content"] == "spec is ready"
    assert msg["delivery_outcome"] == "delivered"

    # Inbox entries for both recipients
    inbox_rows = conn.execute(
        "SELECT role_id FROM inboxes WHERE run_id=? AND message_id=? ORDER BY role_id",
        (run_id, msg_id),
    ).fetchall()
    assert len(inbox_rows) == 2
    assert [r["role_id"] for r in inbox_rows] == ["implementer", "plan-maker"]


def test_run_completed_handler_triggers_quick_evaluate(store, clean_bus):
    """emit(RUN_COMPLETED) → run_performance row should exist."""
    run_id = "boot-test-003"
    _seed_run(store, run_id, "completed")

    bootstrap_runtime(store, run_id, enable_observer=False)

    emit(Hook.RUN_COMPLETED, {
        "run_id": run_id,
        "final_state": "DONE",
        "status": "completed",
        "completed_at": "2026-07-11T12:00:00Z",
    })

    perf = store.load_run_performance(run_id)
    assert perf is not None
    assert perf["success_score"] == 85


def test_bootstrap_idempotent_within_same_bus(store, clean_bus):
    """Calling bootstrap twice without reset_bus should not duplicate handlers."""
    run_id = "boot-test-004"
    _seed_run(store, run_id)

    bootstrap_runtime(store, run_id, enable_observer=False)
    count_after_first = len(get_bus()._handlers.get(Hook.MESSAGE_SENT, []))

    bootstrap_runtime(store, run_id, enable_observer=False)
    count_after_second = len(get_bus()._handlers.get(Hook.MESSAGE_SENT, []))

    assert count_after_first == 1
    assert count_after_second == 1  # No duplicate