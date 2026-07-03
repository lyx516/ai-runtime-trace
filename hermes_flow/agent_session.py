"""Agent Session management — context packet building, file serialization, result parsing.

Bridges the Runtime Loop (Python process) and agent subagents (delegate_task).
The loop calls prepare_context() to build a context file, then the subagent
reads it via terminal/file tools, calls agent_tools.py functions, and writes
a result file that the loop collects via parse_result().
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import get_tracer

logger = logging.getLogger(__name__)

# Session files directory name
SESSION_DIR_NAME = "sessions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Context Packet Builder ────────────────────────────────────────────────

def prepare_context(
    run_id: str,
    role_id: str,
    store: RuntimeStore,
    inbox_messages: list[dict] | None = None,
    state_id: str | None = None,
) -> dict[str, Any]:
    """Build an AgentContextPacket dict for an agent session.

    Reads from the RuntimeStore to populate:
    - Current state description, actors, gate_info
    - Inbox messages addressed to this role
    - Pending decisions from other roles (current round)
    - Available tools list

    Args:
        run_id: The flow run identifier.
        role_id: The agent role (e.g., "architect", "reviewer").
        store: RuntimeStore for the run.
        inbox_messages: Optional pre-fetched inbox messages. If None, fetches from store.
        state_id: Optional state override. If None, uses the run's current_state_id.

    Returns:
        AgentContextPacket dict matching contracts/agent-context-schema.yaml.
    """
    tracer = get_tracer()
    with tracer.span("prepare_context", inputs={"run_id": run_id, "role_id": role_id}) as span:
        conn = store.connect()

        # Resolve state
        resolved_state = state_id
        if resolved_state is None:
            run_row = conn.execute(
                "SELECT current_state_id FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run_row is None:
                raise ValueError(f"Run {run_id} not found")
            resolved_state = run_row["current_state_id"]

        # Load state definition
        state_row = conn.execute(
            "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
            (run_id, resolved_state),
        ).fetchone()
        state_dict = json.loads(state_row["state_json"]) if state_row else {}
        state_description = state_dict.get("description", "")

        # Gate info
        gate_info = None
        gate = state_dict.get("gate")
        if gate:
            gate_info = {
                "required_roles": gate.get("required_roles", []),
                "pass_values": gate.get("pass_values", []),
                "fail_values": gate.get("fail_values", []),
                "blocked_values": gate.get("blocked_values", []),
                "max_rounds": gate.get("max_rounds", 0),
                "on_pass": gate.get("on_pass", ""),
                "on_fail": gate.get("on_fail", ""),
                "on_blocked": gate.get("on_blocked", ""),
                "on_exhausted": gate.get("on_exhausted", ""),
            }

        # Fetch inbox messages
        if inbox_messages is None:
            inbox_rows = conn.execute(
                """SELECT m.message_id, m.run_id, m.state_id, m.from_role,
                          m.kind, m.content, m.intended_recipients, m.created_at
                   FROM inboxes i
                   JOIN messages m ON i.message_id = m.message_id
                   WHERE i.run_id = ? AND i.role_id = ?
                   ORDER BY m.created_at ASC""",
                (run_id, role_id),
            ).fetchall()
            inbox_messages = [dict(r) for r in inbox_rows]

        # Fetch pending decisions (current round group)
        # Filter by last transition into this state — same as evaluate_gate logic
        from hermes_flow.engine import _load_last_transition_into_state

        last_transition = _load_last_transition_into_state(store, run_id, resolved_state)
        cutoff = last_transition["created_at"] if last_transition else "1970-01-01T00:00:00"

        all_decisions = store.load_decisions(run_id, resolved_state)
        current_decisions = [d for d in all_decisions if d.created_at >= cutoff]
        pending_decisions = [
            {
                "role_id": d.role_id,
                "value": d.value,
                "reason": d.reason,
                "created_at": d.created_at,
            }
            for d in current_decisions
        ]

        # Visible artifacts
        artifacts = store.list_visible_messages(run_id, role_id)
        visible_artifacts = [
            {
                "artifact_id": "",
                "path": "",
                "produced_by_role": "",
                "created_at": "",
            }
        ]
        # Clear placeholder if no real artifacts exist
        if not artifacts:
            visible_artifacts = []

        session_id = _new_id()

        context = {
            "run_id": run_id,
            "session_id": session_id,
            "role_id": role_id,
            "state_id": resolved_state,
            "state_description": state_description,
            "gate_info": gate_info,
            "inbox_messages": inbox_messages,
            "pending_decisions": pending_decisions,
            "visible_artifacts": visible_artifacts,
            "available_tools": ["inbox_read", "message_send", "submit_decision", "query_status"],
            "discussion_history": [],
            "created_at": _now(),
        }

        span.outputs = {
            "session_id": session_id,
            "state_id": resolved_state,
            "inbox_count": len(inbox_messages),
            "pending_decision_count": len(pending_decisions),
        }
        return context


# ── Context File Writer ───────────────────────────────────────────────────

def write_context_file(context: dict[str, Any], run_dir: str | Path) -> str:
    """Serialize a context packet to a JSON file.

    Args:
        context: AgentContextPacket dict (from prepare_context()).
        run_dir: The run's directory (.hermes-flow/runs/<run_id>/).

    Returns:
        Absolute path to the written context file.
    """
    tracer = get_tracer()
    with tracer.span("write_context_file", inputs={
        "session_id": context.get("session_id", ""),
        "role_id": context.get("role_id", ""),
    }) as span:
        session_dir = Path(run_dir) / SESSION_DIR_NAME
        session_dir.mkdir(parents=True, exist_ok=True)

        session_id = context["session_id"]
        file_path = session_dir / f"{session_id}.context.json"

        with open(file_path, "w") as f:
            json.dump(context, f, indent=2, default=str, ensure_ascii=False)

        span.outputs = {"path": str(file_path)}
        return str(file_path)


# ── Result File Parser ────────────────────────────────────────────────────

def parse_result(session_id: str, run_dir: str | Path) -> Optional[dict[str, Any]]:
    """Read and validate a session result JSON file.

    Args:
        session_id: The session ID (must match the context packet's session_id).
        run_dir: The run's directory (.hermes-flow/runs/<run_id>/).

    Returns:
        Parsed SessionResult dict if the file exists and is valid, None otherwise.
    """
    tracer = get_tracer()
    with tracer.span("parse_result", inputs={"session_id": session_id}) as span:
        result_file = Path(run_dir) / SESSION_DIR_NAME / f"{session_id}.result.json"

        if not result_file.exists():
            span.outputs = {"found": False}
            return None

        try:
            with open(result_file) as f:
                result = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse result for session %s: %s", session_id, e)
            span.outputs = {"found": True, "error": str(e)}
            return None

        # Basic validation
        if not isinstance(result, dict):
            logger.warning("Result for session %s is not a dict", session_id)
            span.outputs = {"found": True, "error": "not a dict"}
            return None

        if result.get("session_id") != session_id:
            logger.warning(
                "Result session_id mismatch: expected %s, got %s",
                session_id, result.get("session_id"),
            )
            span.outputs = {"found": True, "error": "session_id mismatch"}
            return None

        span.outputs = {"found": True, "actions": len(result.get("actions_taken", []))}
        return result
