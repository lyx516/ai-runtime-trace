"""Agent-facing tool wrappers — callable from a subagent's terminal tool via python -c.

Each function wraps the corresponding flow tool from `hermes_flow/tools.py`,
adding a tracer span per FR-004. The subagent receives the run_id and role_id
from its context packet file.
"""

from __future__ import annotations

import json
from typing import Any

from hermes_flow.errors import RuntimeStateError
from hermes_flow.observer import get_event_bus
from hermes_flow.storage import RuntimeStore
from hermes_flow.tools import flow_decide, flow_send, flow_status
from hermes_flow.trace import get_tracer


def _resolve_store(run_id: str) -> RuntimeStore:
    """Resolve a run's RuntimeStore, raising RuntimeStateError if not found.

    Uses the same resolution logic as hermes_flow.tools._get_store.
    """
    import os
    from pathlib import Path

    project_root = os.environ.get("HERMES_FLOW_PROJECT_ROOT", "")
    if project_root:
        run_dir = Path(project_root) / ".hermes-flow" / "runs" / run_id
        if run_dir.exists():
            store = RuntimeStore(run_dir)
            store.init_schema()
            return store

    # Fallback search
    for base in [Path.cwd(), Path.home()]:
        matches = list((base / ".hermes-flow" / "runs").glob(f"{run_id}*"))
        if matches:
            store = RuntimeStore(matches[0])
            store.init_schema()
            return store

    raise RuntimeStateError(f"Run {run_id} not found — cannot resolve store")


def agent_inbox_read(run_id: str, role_id: str) -> list[dict[str, Any]]:
    """Read all inbox messages addressed to a given role.

    Returns a list of message dicts sorted by created_at ascending.
    Each dict contains: message_id, run_id, state_id, from_role, kind,
    content, intended_recipients, created_at.
    """
    tracer = get_tracer()
    with tracer.span("agent_inbox_read", inputs={"run_id": run_id, "role_id": role_id}) as span:
        try:
            store = _resolve_store(run_id)
        except RuntimeStateError as e:
            span.outputs = {"error": str(e)}
            return []

        conn = store.connect()
        rows = conn.execute(
            """SELECT m.message_id, m.run_id, m.state_id, m.from_role,
                      m.kind, m.content, m.intended_recipients, m.created_at
               FROM inboxes i
               JOIN messages m ON i.message_id = m.message_id
               WHERE i.run_id = ? AND i.role_id = ?
               ORDER BY m.created_at ASC""",
            (run_id, role_id),
        ).fetchall()

        results = [dict(r) for r in rows]
        span.outputs = {"count": len(results)}
        _publish_thinking(run_id, role_id, "read_inbox", {"count": len(results)}, {"count": len(results)})
        return results


def agent_message_send(
    run_id: str,
    role_id: str,
    state_id: str,
    intended_recipients: list[str],
    kind: str,
    content: str,
    visibility: str = "targeted",
    artifacts: list[str] | None = None,
    requires_ack: bool = False,
) -> dict[str, Any]:
    """Send a message from an agent to other agents.

    Delegates to flow_send from hermes_flow.tools, using the agent's
    role_id as the from_role. Returns the delivery outcome dict.
    """
    tracer = get_tracer()
    with tracer.span("agent_message_send", inputs={
        "run_id": run_id, "role_id": role_id, "state_id": state_id,
        "intended_recipients": intended_recipients, "kind": kind,
    }) as span:
        result = flow_send(
            run_id=run_id,
            state_id=state_id,
            from_role=role_id,
            intended_recipients=intended_recipients,
            kind=kind,
            content=content,
            visibility=visibility,
            artifacts=artifacts,
            requires_ack=requires_ack,
        )
        span.outputs = result
        _publish_thinking(run_id, role_id, "send_message", {
            "intended_recipients": intended_recipients, "kind": kind,
        }, result, state_id=state_id)
        return result


def agent_submit_decision(
    run_id: str,
    role_id: str,
    state_id: str,
    value: str,
    reason: str = "",
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    """Submit a gate decision on behalf of an agent.

    Delegates to flow_decide from hermes_flow.tools. Returns
    {"ok": true, "decision_id": "...", "value": "..."} or
    {"ok": false, "error": "..."}.
    """
    tracer = get_tracer()
    with tracer.span("agent_submit_decision", inputs={
        "run_id": run_id, "role_id": role_id, "state_id": state_id, "value": value,
    }) as span:
        # Build source_references from inbox
        try:
            inbox_msgs = agent_inbox_read(run_id, role_id)
            source_refs = _build_source_references(inbox_msgs, state_id)
            enriched_reason = source_refs + reason if source_refs else reason
        except Exception:
            enriched_reason = reason

        result = flow_decide(
            run_id=run_id,
            state_id=state_id,
            role_id=role_id,
            value=value,
            reason=enriched_reason,
            artifacts=artifacts,
        )
        span.outputs = result
        _publish_thinking(run_id, role_id, "submit_decision", {
            "state_id": state_id, "value": value,
        }, result, state_id=state_id)
        return result


def agent_query_status(run_id: str) -> dict[str, Any]:
    """Query the current flow run status.

    Delegates to flow_status from hermes_flow.tools.
    """
    tracer = get_tracer()
    with tracer.span("agent_query_status", inputs={"run_id": run_id}) as span:
        result = flow_status(run_id)
        span.outputs = result
        _publish_thinking(run_id, None, "query_status", {}, result)
        return result


def _publish_thinking(
    run_id: str,
    role_id: str | None,
    step_type: str,
    inputs: dict,
    output: dict,
    state_id: str = "",
) -> None:
    """Publish an agent_thinking event to the EventBus and persist to store."""
    try:
        bus = get_event_bus()
        bus.publish("agent_thinking", {
            "run_id": run_id,
            "role_id": role_id or "system",
            "step_type": step_type,
            "inputs": inputs,
            "output": output,
        })
    except Exception:
        pass  # Non-critical; don't disrupt the agent flow

    # Persist to thinking_events table
    try:
        store = _resolve_store(run_id)
        store.append_thinking_event(
            run_id=run_id,
            role_id=role_id or "system",
            state_id=state_id,
            step_type=step_type,
            inputs=inputs,
            output=output,
        )
    except Exception:
        pass


def _build_source_references(
    inbox_messages: list[dict],
    state_id: str,
) -> str:
    """Build a source_references string for decision reasons.

    Examines the agent's inbox messages and current state to produce
    a traceable reference string that can be prepended to the decision reason.
    """
    refs = []
    if inbox_messages:
        for m in inbox_messages[:5]:  # Limit to prevent bloat
            msg_id = m.get("message_id", "?")
            refs.append(f"[source: inbox/{msg_id}]")
    if state_id:
        refs.append(f"[source: state/{state_id}]")
    if refs:
        return " ".join(refs) + " "
    return ""
