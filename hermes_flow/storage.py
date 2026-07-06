"""Project-local runtime persistence and audit trail."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hermes_flow.errors import RuntimeStateError
from hermes_flow.schemas import (
    AgentBinding,
    Artifact,
    Decision,
    FlowInitResult,
    FlowRun,
    FlowStatus,
    GateStatus,
    Inbox,
    MemoryMode,
    MessageEnvelope,
    RunStatus,
    StepResult,
    _now,
    to_dict,
)
from hermes_flow.trace import get_tracer


# ── SQLite schema DDL ───────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    flow_id TEXT NOT NULL,
    flow_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    current_state_id TEXT NOT NULL,
    round_counters TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    agent_bindings TEXT NOT NULL DEFAULT '[]',
    agent_specs TEXT NOT NULL DEFAULT '{}',
    memory_modes TEXT NOT NULL DEFAULT '{}',
    artifact_root TEXT NOT NULL,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    role_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    memory_mode TEXT NOT NULL DEFAULT 'run_isolated'
);

CREATE TABLE IF NOT EXISTS states (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    state_id TEXT NOT NULL,
    state_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    state_id TEXT NOT NULL,
    from_role TEXT NOT NULL,
    intended_recipients TEXT NOT NULL,
    authorized_recipients TEXT NOT NULL DEFAULT '[]',
    recipient_availability TEXT NOT NULL DEFAULT '{}',
    visibility TEXT NOT NULL DEFAULT 'targeted',
    kind TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    artifacts TEXT NOT NULL DEFAULT '[]',
    requires_ack INTEGER NOT NULL DEFAULT 0,
    delivery_outcome TEXT NOT NULL DEFAULT 'delivered',
    rejection_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inboxes (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    role_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    state_id TEXT NOT NULL,
    produced_by_role TEXT NOT NULL,
    path TEXT NOT NULL,
    artifact_type TEXT NOT NULL DEFAULT '',
    visibility_scope TEXT NOT NULL DEFAULT 'run',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    state_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    value TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    artifacts TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transitions (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    from_state_id TEXT NOT NULL,
    to_state_id TEXT NOT NULL,
    gate_result TEXT NOT NULL DEFAULT '',
    round_counter INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    state_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_run ON decisions(run_id, state_id);
CREATE INDEX IF NOT EXISTS idx_inboxes_run ON inboxes(run_id, role_id);

CREATE TABLE IF NOT EXISTS trace_events (
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL PRIMARY KEY,
    parent_span_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ts_start TEXT NOT NULL,
    ts_end TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    inputs TEXT NOT NULL DEFAULT '{}',
    outputs TEXT NOT NULL DEFAULT '{}',
    decisions TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    truncated INTEGER NOT NULL DEFAULT 0,
    ended INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events(event_type);
CREATE INDEX IF NOT EXISTS idx_trace_events_run  ON trace_events(run_id, trace_id);

CREATE TABLE IF NOT EXISTS thinking_events (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    state_id TEXT NOT NULL DEFAULT '',
    step_type TEXT NOT NULL,
    inputs_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_thinking_run  ON thinking_events(run_id, created_at);

CREATE TABLE IF NOT EXISTS llm_input_snapshots (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    role_id TEXT NOT NULL,
    state_id TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    messages_json TEXT NOT NULL DEFAULT '[]',
    request_json TEXT NOT NULL DEFAULT '{}',
    context_packet_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_input_run ON llm_input_snapshots(run_id, role_id, state_id, created_at);

CREATE TABLE IF NOT EXISTS agent_session_checkpoints (
    run_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    session_state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, role_id, state_id)
);

CREATE TABLE IF NOT EXISTS run_performance (
    run_id TEXT PRIMARY KEY,
    success_score INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    agent_scores TEXT NOT NULL DEFAULT '{}',
    bottleneck_state TEXT NOT NULL DEFAULT '',
    tool_stats TEXT NOT NULL DEFAULT '{}',
    suggestions TEXT NOT NULL DEFAULT '',
    evaluated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS run_agent_feedback (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manager',
    category TEXT NOT NULL DEFAULT '',
    suggestion TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    applied_run_id TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_agent ON run_agent_feedback(agent_id, status);
"""


# ── RuntimeStore ────────────────────────────────────────────────────────────

class RuntimeStore:
    """Project-local runtime store backed by per-run SQLite."""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self._db_path = self.run_dir / "state.sqlite"
        self._conn: Optional[sqlite3.Connection] = None

    # ── Connection lifecycle ──────────────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "RuntimeStore":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Schema ────────────────────────────────────────────────────────────

    def init_schema(self) -> None:
        """Create all tables if they do not exist."""
        conn = self.connect()
        conn.executescript(SCHEMA_SQL)
        # Migration: add display_name column to existing databases
        try:
            conn.execute("ALTER TABLE runs ADD COLUMN display_name TEXT")
        except Exception:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE runs ADD COLUMN agent_specs TEXT NOT NULL DEFAULT '{}'")
        except Exception:
            pass  # Column already exists
        conn.commit()

    # ── Transaction helper ─────────────────────────────────────────────────

    def transaction(self) -> _Transaction:
        """Return a context manager that commits on success, rolls back on exception."""
        return _Transaction(self.connect())

    # ── Audit helper ──────────────────────────────────────────────────────

    def append_audit_event(
        self,
        run_id: str,
        event_type: str,
        state_id: str = "",
        actor: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Append an audit event. Returns the event id."""
        event_id = uuid.uuid4().hex[:12]
        conn = self.connect()
        conn.execute(
            """INSERT INTO audit_events (event_id, run_id, state_id, event_type, actor, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, run_id, state_id, event_type, actor,
             json_dumps(payload or {}), _now()),
        )
        conn.commit()
        return event_id

    def append_thinking_event(
        self,
        run_id: str,
        role_id: str,
        state_id: str,
        step_type: str,
        inputs: dict | None = None,
        output: dict | None = None,
    ) -> int:
        """Persist an agent_thinking event to the thinking_events table."""
        conn = self.connect()
        cur = conn.execute(
            """INSERT INTO thinking_events (run_id, role_id, state_id, step_type,
               inputs_json, output_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, role_id, state_id, step_type,
             json_dumps(inputs or {}), json_dumps(output or {}), _now()),
        )
        conn.commit()
        return cur.lastrowid or 0

    def load_thinking_events(
        self,
        run_id: str,
        role_id: str | None = None,
        state_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query thinking events for a run, optionally filtered."""
        import json

        sql = "SELECT * FROM thinking_events WHERE run_id=?"
        params: list = [run_id]
        if role_id:
            sql += " AND role_id=?"
            params.append(role_id)
        if state_id:
            sql += " AND state_id=?"
            params.append(state_id)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        conn = self.connect()
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["inputs"] = json.loads(d.get("inputs_json", "{}"))
            except Exception:
                d["inputs"] = {}
            try:
                d["output"] = json.loads(d.get("output_json", "{}"))
            except Exception:
                d["output"] = {}
            del d["inputs_json"]
            del d["output_json"]
            result.append(d)
        return result

    def load_agent_specs(self, run_id: str) -> dict[str, Any]:
        """Load full per-role agent metadata persisted at run creation."""
        conn = self.connect()
        row = conn.execute("SELECT agent_specs FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return {}
        try:
            specs = json_loads(row["agent_specs"])
        except Exception:
            return {}
        return specs if isinstance(specs, dict) else {}

    def load_agent_spec(self, run_id: str, role_id: str) -> dict[str, Any]:
        """Load one role's persisted agent metadata, or an empty dict."""
        spec = self.load_agent_specs(run_id).get(role_id, {})
        return spec if isinstance(spec, dict) else {}

    def append_llm_input_snapshot(
        self,
        run_id: str,
        session_id: str,
        role_id: str,
        state_id: str,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        request: dict[str, Any],
        context_packet: dict[str, Any],
    ) -> int:
        """Persist the exact LLM input payload, with credentials redacted."""
        conn = self.connect()
        cur = conn.execute(
            """INSERT INTO llm_input_snapshots (
                   run_id, session_id, role_id, state_id, provider, model,
                   messages_json, request_json, context_packet_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                session_id,
                role_id,
                state_id,
                provider,
                model,
                json_dumps(messages or []),
                json_dumps(_redact_request_secrets(request)),
                json_dumps(context_packet or {}),
                _now(),
            ),
        )
        conn.commit()
        return cur.lastrowid or 0

    def load_llm_input_snapshots(
        self,
        run_id: str,
        role_id: str | None = None,
        state_id: str | None = None,
        at: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Load LLM input snapshots for a run, newest last."""
        sql = "SELECT * FROM llm_input_snapshots WHERE run_id=?"
        params: list[Any] = [run_id]
        if role_id:
            sql += " AND role_id=?"
            params.append(role_id)
        if state_id:
            sql += " AND state_id=?"
            params.append(state_id)
        if at:
            sql += " AND created_at <= ?"
            params.append(at)
        sql += " ORDER BY created_at ASC, row_id ASC LIMIT ?"
        params.append(limit)

        rows = self.connect().execute(sql, params).fetchall()
        snapshots = []
        for row in rows:
            d = dict(row)
            snapshots.append({
                "source": "llm_input_snapshot",
                "snapshot_id": d.get("row_id"),
                "run_id": d.get("run_id", ""),
                "session_id": d.get("session_id", ""),
                "role_id": d.get("role_id", ""),
                "state_id": d.get("state_id", ""),
                "provider": d.get("provider", ""),
                "model": d.get("model", ""),
                "messages": _json_loads_fallback(d.get("messages_json"), []),
                "request": _json_loads_fallback(d.get("request_json"), {}),
                "context_packet": _json_loads_fallback(d.get("context_packet_json"), {}),
                "created_at": d.get("created_at", ""),
            })
        return snapshots

    # ── Create run ────────────────────────────────────────────────────────

    def create_run(
        self,
        flow_id: str,
        flow_version: str,
        initial_state_id: str,
        agent_bindings: list[AgentBinding],
        memory_modes: dict[str, str],
        artifact_root: str,
        states_json: dict[str, Any],
        override_run_id: str | None = None,
        display_name: str | None = None,
        agent_specs: dict[str, Any] | None = None,
    ) -> FlowRun:
        """Initialize a new run directory and SQLite database."""
        tracer = get_tracer()
        with tracer.span("create_run", inputs={
            "flow_id": flow_id,
            "flow_version": flow_version,
            "initial_state_id": initial_state_id,
            "agent_count": len(agent_bindings),
        }) as span:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.init_schema()

            run_id = override_run_id or uuid.uuid4().hex[:12]
            now = _now()

            run = FlowRun(
                run_id=run_id,
                flow_id=flow_id,
                flow_version=flow_version,
                status=RunStatus.ACTIVE,
                current_state_id=initial_state_id,
                round_counters={},
                created_at=now,
                updated_at=now,
                agent_bindings=agent_bindings,
                memory_modes=memory_modes,
                artifact_root=artifact_root,
            )

            conn = self.connect()
            conn.execute(
                """INSERT INTO runs (run_id, flow_id, flow_version, status, current_state_id,
                   round_counters, created_at, updated_at, agent_bindings, agent_specs,
                   memory_modes, artifact_root, display_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.run_id, run.flow_id, run.flow_version, run.status.value,
                 run.current_state_id, json_dumps(run.round_counters),
                 run.created_at, run.updated_at, json_dumps([to_dict(b) for b in run.agent_bindings]),
                 json_dumps(agent_specs or {}), json_dumps(run.memory_modes), run.artifact_root, display_name),
            )

            # Persist states
            for state_id, state_data in states_json.items():
                conn.execute(
                    "INSERT INTO states (run_id, state_id, state_json) VALUES (?, ?, ?)",
                    (run_id, state_id, json_dumps(state_data)),
                )

            # Persist agent bindings
            for b in agent_bindings:
                conn.execute(
                    "INSERT INTO agents (run_id, role_id, profile_name, session_id, memory_mode) VALUES (?, ?, ?, ?, ?)",
                    (run_id, b.role_id, b.profile_name, b.session_id, b.memory_mode.value),
                )

            # Initial audit event
            self.append_audit_event(
                run_id=run_id,
                event_type="run_created",
                state_id=initial_state_id,
                actor="system",
                payload={"flow_id": flow_id, "flow_version": flow_version},
            )

            conn.commit()

            span.outputs = {"run_id": run.run_id, "status": run.status.value}
            return run

    # ── Load status ───────────────────────────────────────────────────────

    def load_status(self, run_id: str) -> FlowStatus:
        """Assemble FlowStatus from project-local tables."""
        conn = self.connect()
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise RuntimeStateError(f"Run {run_id} not found")

        status = FlowStatus(
            run_id=row["run_id"],
            status=RunStatus(row["status"]) if row["status"] else RunStatus.ABORTED,
            current_state_id=row["current_state_id"],
            round_counters=json_loads(row["round_counters"]),
            memory_modes=json_loads(row["memory_modes"]),
        )

        # Recent messages (last 10)
        msg_rows = conn.execute(
            "SELECT * FROM messages WHERE run_id = ? ORDER BY created_at DESC LIMIT 10",
            (run_id,),
        ).fetchall()
        status.recent_messages = [_row_to_message(r) for r in reversed(msg_rows)]

        # Pending gate — build from decisions in current state
        current_state_id = status.current_state_id
        dec_rows = conn.execute(
            "SELECT * FROM decisions WHERE run_id = ? AND state_id = ? ORDER BY created_at",
            (run_id, current_state_id),
        ).fetchall()
        decisions = [_row_to_decision(r) for r in dec_rows]

        # Determine next actions
        if status.status in (RunStatus.COMPLETED, RunStatus.ABORTED):
            status.next_actions = ["audit"]
        elif status.status == RunStatus.PAUSED:
            status.next_actions = ["resume", "abort"]
        elif status.status == RunStatus.ESCALATED:
            status.next_actions = ["resume", "abort"]
        else:
            status.next_actions = ["send", "decide", "step", "pause", "abort"]

        return status

    # ── Record message ────────────────────────────────────────────────────

    def record_message_attempt(self, envelope: MessageEnvelope) -> None:
        tracer = get_tracer()
        with tracer.span("record_message", inputs={
            "message_id": envelope.message_id,
            "from_role": envelope.from_role,
            "intended_recipients": envelope.intended_recipients,
        }) as span:
            conn = self.connect()
            conn.execute(
                """INSERT INTO messages (message_id, run_id, state_id, from_role,
                   intended_recipients, authorized_recipients, recipient_availability,
                   visibility, kind, content, artifacts, requires_ack,
                   delivery_outcome, rejection_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (envelope.message_id, envelope.run_id, envelope.state_id, envelope.from_role,
                 json_dumps(envelope.intended_recipients),
                 json_dumps(envelope.authorized_recipients),
                 json_dumps(envelope.recipient_availability),
                 envelope.visibility, envelope.kind, envelope.content,
                 json_dumps(envelope.artifacts), int(envelope.requires_ack),
                 envelope.delivery_outcome.value, envelope.rejection_reason,
                 envelope.created_at),
            )
            conn.commit()
            span.outputs = {"delivery_outcome": envelope.delivery_outcome.value}

    # ── Add inbox entries ─────────────────────────────────────────────────

    def add_inbox_entries(self, run_id: str, role_id: str, state_id: str, message_ids: list[str]) -> None:
        conn = self.connect()
        now = _now()
        for mid in message_ids:
            conn.execute(
                "INSERT INTO inboxes (run_id, role_id, state_id, message_id, generated_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, role_id, state_id, mid, now),
            )
        conn.commit()

    # ── Record decision ───────────────────────────────────────────────────

    def record_decision(self, decision: Decision) -> None:
        tracer = get_tracer()
        with tracer.span("record_decision", inputs={
            "role_id": decision.role_id,
            "value": decision.value,
            "state_id": decision.state_id,
        }) as span:
            conn = self.connect()
            conn.execute(
                """INSERT INTO decisions (decision_id, run_id, state_id, role_id, value, reason, artifacts, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (decision.decision_id, decision.run_id, decision.state_id,
                 decision.role_id, decision.value, decision.reason,
                 json_dumps(decision.artifacts), decision.created_at),
            )
            conn.commit()
            span.outputs = {"decision_id": decision.decision_id}

    # ── Record artifact ───────────────────────────────────────────────────

    def record_artifact(self, artifact: Artifact) -> None:
        conn = self.connect()
        conn.execute(
            """INSERT INTO artifacts (artifact_id, run_id, state_id, produced_by_role, path, artifact_type, visibility_scope, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (artifact.artifact_id, artifact.run_id, artifact.state_id,
             artifact.produced_by_role, artifact.path, artifact.artifact_type,
             artifact.visibility_scope, artifact.created_at),
        )
        conn.commit()

    # ── State transitions ─────────────────────────────────────────────────

    def record_transition(self, run_id: str, from_state: str, to_state: str, gate_result: str = "", round_counter: int = 0) -> None:
        conn = self.connect()
        conn.execute(
            "UPDATE runs SET current_state_id = ?, updated_at = ? WHERE run_id = ?",
            (to_state, _now(), run_id),
        )
        conn.execute(
            """INSERT INTO transitions (run_id, from_state_id, to_state_id, gate_result, round_counter, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, from_state, to_state, gate_result, round_counter, _now()),
        )
        conn.commit()

    # ── Update run status ─────────────────────────────────────────────────

    def update_status(self, run_id: str, status: RunStatus, completed_at: str | None = None) -> None:
        conn = self.connect()
        if completed_at:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ?, completed_at = ? WHERE run_id = ?",
                (status.value, _now(), completed_at, run_id),
            )
        else:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status.value, _now(), run_id),
            )
        conn.commit()

    # ── Resume / reopen ───────────────────────────────────────────────────

    def resume_run(self, run_id: str) -> FlowRun:
        """Reopen existing state.sqlite and return the run record."""
        if not self._db_path.exists():
            raise RuntimeStateError(f"Run {run_id} not found at {self._db_path}")
        self.init_schema()
        row = self.connect().execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise RuntimeStateError(f"Run {run_id} not found in database")
        return _row_to_run(row)

    # ── Audit export ──────────────────────────────────────────────────────

    def export_audit(self, run_id: str) -> list[dict[str, Any]]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Load decisions for a state (for gate evaluation) ──────────────────

    def load_decisions(self, run_id: str, state_id: str) -> list[Decision]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM decisions WHERE run_id = ? AND state_id = ? ORDER BY created_at",
            (run_id, state_id),
        ).fetchall()
        return [_row_to_decision(r) for r in rows]

    # ── List visible messages for a role ──────────────────────────────────

    def list_visible_messages(self, run_id: str, role_id: str) -> list[MessageEnvelope]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT m.* FROM messages m
               INNER JOIN inboxes i ON m.message_id = i.message_id
               WHERE i.run_id = ? AND i.role_id = ?
               ORDER BY m.created_at""",
            (run_id, role_id),
        ).fetchall()
        return [_row_to_message(r) for r in rows]

    # ── List readable artifacts for a role ────────────────────────────────

    def list_readable_artifacts(self, run_id: str, role_id: str, read_scope: list[str] | None = None) -> list[Artifact]:
        conn = self.connect()
        if read_scope:
            placeholders = ",".join("?" for _ in read_scope)
            rows = conn.execute(
                f"""SELECT * FROM artifacts
                    WHERE run_id = ? AND path IN ({placeholders})
                    ORDER BY created_at""",
                [run_id] + read_scope,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    # ── Increment round counter ───────────────────────────────────────────

    def increment_round(self, run_id: str, state_id: str) -> int:
        conn = self.connect()
        row = conn.execute("SELECT round_counters FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        counters = json_loads(row["round_counters"])
        current = counters.get(state_id, 0) + 1
        counters[state_id] = current
        conn.execute("UPDATE runs SET round_counters = ? WHERE run_id = ?",
                     (json_dumps(counters), run_id))
        conn.commit()
        return current

    def get_round_count(self, run_id: str, state_id: str) -> int:
        conn = self.connect()
        row = conn.execute("SELECT round_counters FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json_loads(row["round_counters"]).get(state_id, 0)

    # ── Agent session checkpoint ───────────────────────────────────────────

    def save_agent_session_checkpoint(self, state_json: str, run_id: str, role_id: str, state_id: str) -> None:
        """INSERT OR REPLACE checkpoint for (run_id, role_id, state_id)."""
        conn = self.connect()
        conn.execute(
            """INSERT OR REPLACE INTO agent_session_checkpoints
               (run_id, role_id, state_id, session_state_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, role_id, state_id, state_json, _now()),
        )
        conn.commit()

    def load_agent_session_checkpoint(self, run_id: str, role_id: str, state_id: str) -> dict[str, Any] | None:
        """Load checkpoint or return None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT session_state_json FROM agent_session_checkpoints WHERE run_id=? AND role_id=? AND state_id=?",
            (run_id, role_id, state_id),
        ).fetchone()
        if row is None:
            return None
        try:
            return json_loads(row["session_state_json"])
        except Exception:
            return None

    def delete_agent_session_checkpoint(self, run_id: str, role_id: str, state_id: str) -> None:
        """Delete checkpoint after successful session completion."""
        conn = self.connect()
        conn.execute(
            "DELETE FROM agent_session_checkpoints WHERE run_id=? AND role_id=? AND state_id=?",
            (run_id, role_id, state_id),
        )
        conn.commit()

    def agent_has_decision(self, run_id: str, state_id: str, role_id: str) -> bool:
        """Check if a role has already submitted a decision for this state. 幂等性保证。"""
        conn = self.connect()
        row = conn.execute(
            "SELECT 1 FROM decisions WHERE run_id=? AND state_id=? AND role_id=?",
            (run_id, state_id, role_id),
        ).fetchone()
        return row is not None

    # ── Run performance ─────────────────────────────────────────────────

    def save_run_performance(
        self, run_id: str, success_score: int, summary: str,
        agent_scores: dict, bottleneck_state: str,
        tool_stats: dict, suggestions: str,
    ) -> None:
        """INSERT OR REPLACE run performance evaluation."""
        conn = self.connect()
        conn.execute(
            """INSERT OR REPLACE INTO run_performance
               (run_id, success_score, summary, agent_scores, bottleneck_state,
                tool_stats, suggestions, evaluated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, success_score, summary, json_dumps(agent_scores),
             bottleneck_state, json_dumps(tool_stats), suggestions, _now()),
        )
        conn.commit()

    def load_run_performance(self, run_id: str) -> dict[str, Any] | None:
        """Load performance evaluation for a run, or None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM run_performance WHERE run_id=?", (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "success_score": row["success_score"],
            "summary": row["summary"],
            "agent_scores": json_loads(row["agent_scores"]),
            "bottleneck_state": row["bottleneck_state"],
            "tool_stats": json_loads(row["tool_stats"]),
            "suggestions": row["suggestions"],
            "evaluated_at": row["evaluated_at"],
        }

    # ── Agent feedback ───────────────────────────────────────────────────

    def save_agent_feedback(
        self, run_id: str, agent_id: str, category: str,
        suggestion: str, evidence: str, source: str = "manager",
    ) -> int:
        """Insert a per-agent feedback entry. Returns row_id."""
        conn = self.connect()
        now = _now()
        cur = conn.execute(
            """INSERT INTO run_agent_feedback
               (run_id, agent_id, source, category, suggestion, evidence, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (run_id, agent_id, source, category, suggestion, evidence, now, now),
        )
        conn.commit()
        return cur.lastrowid or 0

    def load_agent_feedback(
        self, agent_id: str, status: str = "pending", limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Load pending feedback for an agent."""
        conn = self.connect()
        rows = conn.execute(
            """SELECT * FROM run_agent_feedback
               WHERE agent_id=? AND status=? ORDER BY row_id DESC LIMIT ?""",
            (agent_id, status, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_feedback_applied(self, row_id: int, applied_run_id: str = "") -> None:
        """Mark feedback as applied."""
        conn = self.connect()
        conn.execute(
            "UPDATE run_agent_feedback SET status='applied', applied_run_id=?, updated_at=? WHERE row_id=?",
            (applied_run_id, _now(), row_id),
        )
        conn.commit()

    def mark_feedback_dismissed(self, row_id: int) -> None:
        """Soft-delete feedback by marking as dismissed."""
        conn = self.connect()
        conn.execute(
            "UPDATE run_agent_feedback SET status='dismissed', updated_at=? WHERE row_id=?",
            (_now(), row_id),
        )
        conn.commit()

    def load_all_pending_feedback(self) -> list[dict[str, Any]]:
        """Load all pending feedback across all agents."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM run_agent_feedback WHERE status='pending' ORDER BY agent_id, row_id",
        ).fetchall()
        return [dict(r) for r in rows]


# ── Internal transaction context manager ─────────────────────────────────────

class _Transaction:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()


# ── JSON helpers ────────────────────────────────────────────────────────────

def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def json_loads(s: str) -> Any:
    import json
    if not s:
        return {} if s == "" else s
    return json.loads(s)


def _json_loads_fallback(s: Any, fallback: Any) -> Any:
    try:
        if not isinstance(s, str) or not s:
            return fallback
        return json_loads(s)
    except Exception:
        return fallback


def _redact_request_secrets(request: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of an LLM request payload with secret header values removed."""
    if not isinstance(request, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in request.items():
        if key.lower() == "headers" and isinstance(value, dict):
            safe[key] = {
                h: "[REDACTED]" if h.lower() in {"authorization", "api-key", "x-api-key"} else v
                for h, v in value.items()
            }
        else:
            safe[key] = value
    return safe


# ── Row converters ──────────────────────────────────────────────────────────

def _row_to_message(row: sqlite3.Row) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=row["message_id"],
        run_id=row["run_id"],
        state_id=row["state_id"],
        from_role=row["from_role"],
        intended_recipients=json_loads(row["intended_recipients"]),
        authorized_recipients=json_loads(row["authorized_recipients"]),
        recipient_availability=json_loads(row["recipient_availability"]),
        visibility=row["visibility"],
        kind=row["kind"],
        content=row["content"],
        artifacts=json_loads(row["artifacts"]),
        requires_ack=bool(row["requires_ack"]),
        delivery_outcome=row["delivery_outcome"],
        rejection_reason=row["rejection_reason"],
        created_at=row["created_at"],
    )


def _row_to_decision(row: sqlite3.Row) -> Decision:
    return Decision(
        decision_id=row["decision_id"],
        run_id=row["run_id"],
        state_id=row["state_id"],
        role_id=row["role_id"],
        value=row["value"],
        reason=row["reason"],
        artifacts=json_loads(row["artifacts"]),
        created_at=row["created_at"],
    )


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        artifact_id=row["artifact_id"],
        run_id=row["run_id"],
        state_id=row["state_id"],
        produced_by_role=row["produced_by_role"],
        path=row["path"],
        artifact_type=row["artifact_type"],
        visibility_scope=row["visibility_scope"],
        created_at=row["created_at"],
    )


def _row_to_run(row: sqlite3.Row) -> FlowRun:
    return FlowRun(
        run_id=row["run_id"],
        flow_id=row["flow_id"],
        flow_version=row["flow_version"],
        status=RunStatus(row["status"]) if row["status"] else RunStatus.ABORTED,
        current_state_id=row["current_state_id"],
        round_counters=json_loads(row["round_counters"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        agent_bindings=[AgentBinding(**b) for b in json_loads(row["agent_bindings"])],
        memory_modes=json_loads(row["memory_modes"]),
        artifact_root=row["artifact_root"],
    )
