"""Tool handlers exposed by plugin registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_flow.engine import advance_state, detect_idle_timeout, evaluate_gate
from hermes_flow.errors import RuntimeStateError
from hermes_flow.flow_loader import load_flow_from_yaml, validate_flow
from hermes_flow.routing import validate_message
from hermes_flow.schemas import (
    AgentBinding,
    Decision,
    DeliveryOutcome,
    FlowInitResult,
    FlowStatus,
    GateStatus,
    MessageEnvelope,
    RunStatus,
    StepResult,
    _new_id,
    _now,
    to_dict,
)
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import SqliteTracer, set_tracer, get_tracer


# ── JSON response helpers ───────────────────────────────────────────────────

def ok_result(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap a successful result with an ok flag."""
    return {"ok": True, **data}


def error_result(message: str, details: list[str] | None = None) -> dict[str, Any]:
    """Wrap an error result with an ok flag and message."""
    return {"ok": False, "error": message, "details": details or []}


def _get_store(run_id: str) -> RuntimeStore:
    """Resolve a run's store from the project root."""
    # This is a simplified resolution — in practice the project_root is stored
    # in a config or inferred from the run directory structure.
    # For now, search common locations.
    import os
    # Check if HERMES_FLOW_PROJECT_ROOT is set
    project_root = os.environ.get("HERMES_FLOW_PROJECT_ROOT", "")
    if project_root:
        run_dir = Path(project_root) / ".hermes-flow" / "runs" / run_id
        if run_dir.exists():
            store = RuntimeStore(run_dir)
            store.init_schema()
            return store

    # Fall back to current directory search
    import glob
    for base in [Path.cwd(), Path.home()]:
        pattern = str(base / ".hermes-flow" / "runs" / run_id)
        matches = list(Path(base / ".hermes-flow" / "runs").glob(f"{run_id}*"))
        if matches:
            store = RuntimeStore(matches[0])
            store.init_schema()
            return store

    raise RuntimeStateError(f"Run {run_id} not found — cannot resolve store")


# ── Tool handlers ───────────────────────────────────────────────────────────

def flow_init(
    project_root: str,
    flow_path: str,
    run_name: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a new project-local flow run from a flow definition.

    Supports dry_run=True for validation without creating runtime state.
    """
    import uuid
    project_root_p = Path(project_root)
    flow_path_p = Path(flow_path)

    # Resolve flow path relative to project root if not absolute
    if not flow_path_p.is_absolute():
        flow_path_p = project_root_p / flow_path_p

    # Create tracing store first so ALL operations are captured
    _trace_run_id = uuid.uuid4().hex[:12]
    _trace_run_dir = project_root_p / ".hermes-flow" / "runs" / _trace_run_id
    _trace_run_dir.mkdir(parents=True, exist_ok=True)
    _trace_store = RuntimeStore(_trace_run_dir)
    _trace_store.init_schema()
    set_tracer(SqliteTracer(_trace_store, run_id=_trace_run_id))

    # Load and validate
    try:
        flow = load_flow_from_yaml(str(flow_path_p))
    except Exception as e:
        return error_result(str(e))

    try:
        validate_flow(flow)
    except Exception as e:
        errors = getattr(e, "details", [str(e)])
        return error_result(str(e), details=errors if isinstance(errors, list) else [str(errors)])

    if dry_run:
        return ok_result({
            "run_id": "",
            "current_state_id": flow.initial_state_id,
            "agents": [],
            "artifact_root": "",
            "validation_errors": [],
        })

    # Use the tracing store for the real run
    run_dir = _trace_run_dir
    run_id = _trace_run_id
    artifact_root = str(run_dir / "artifacts")
    store = _trace_store

    # Build agent bindings
    bindings = [
        AgentBinding(
            role_id=role_id,
            profile_name=role.profile_name,
            session_id="",
            memory_mode=role.memory_mode,
        )
        for role_id, role in flow.agents.items()
    ]
    memory_modes = {role_id: role.memory_mode.value for role_id, role in flow.agents.items()}
    agent_specs = {role_id: to_dict(role) for role_id, role in flow.agents.items()}

    # Build states JSON for persistence
    states_json = {}
    for sid, state in flow.states.items():
        states_json[sid] = to_dict(state)

    run = store.create_run(
        flow_id=flow.flow_id,
        flow_version=flow.version,
        initial_state_id=flow.initial_state_id,
        agent_bindings=bindings,
        memory_modes=memory_modes,
        artifact_root=artifact_root,
        states_json=states_json,
        override_run_id=run_id,
        display_name=run_name or None,
        agent_specs=agent_specs,
    )

    result = ok_result({
        "run_id": run.run_id,
        "current_state_id": run.current_state_id,
        "agents": [to_dict(b) for b in bindings],
        "artifact_root": artifact_root,
        "validation_errors": [],
    })
    return result


def flow_status(
    run_id: str,
    include_recent_messages: bool = True,
) -> dict[str, Any]:
    """Inspect current run state, gates, messages, and next actions."""
    tracer = get_tracer()
    with tracer.span("flow_status", inputs={"run_id": run_id, "include_recent_messages": include_recent_messages}) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        try:
            status = store.load_status(run_id)
        except Exception as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        result = ok_result({
            "run_id": status.run_id,
            "status": status.status.value if hasattr(status.status, "value") else str(status.status),
            "current_state_id": status.current_state_id,
            "pending_gate": to_dict(status.pending_gate) if status.pending_gate else None,
            "round_counters": status.round_counters,
            "next_actions": status.next_actions,
        })
        span.outputs = result
        return result


def flow_step(
    run_id: str,
    max_actions: int = 1,
) -> dict[str, Any]:
    """Execute the next eligible state action or gate evaluation."""
    tracer = get_tracer()
    with tracer.span("flow_step", inputs={"run_id": run_id, "max_actions": max_actions}) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        try:
            status = store.load_status(run_id)
        except Exception as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        # Reject non-active runs
        if status.status not in (RunStatus.ACTIVE,):
            result = error_result(f"Run {run_id} status is '{status.status.value}', only 'active' runs can step")
            span.outputs = result
            return result

        # Check idle timeout first
        timeout_result = detect_idle_timeout(run_id, status.current_state_id, store)
        if timeout_result and timeout_result.timeout_exceeded and timeout_result.next_state_id:
            # Get current round for the transition record
            round_counter = status.round_counters.get(status.current_state_id, 1)
            advance_state(run_id, status.current_state_id, timeout_result.next_state_id,
                         "idle_timeout", round_counter, store)
            new_status = store.load_status(run_id)
            result = ok_result({
                "action_taken": "idle_timeout",
                "from_state": status.current_state_id,
                "to_state": timeout_result.next_state_id,
                "run_id": run_id,
                "current_state_id": new_status.current_state_id,
            })
            span.outputs = result
            return result

        # Evaluate gate
        try:
            gate_result = evaluate_gate(run_id, status.current_state_id, store)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        # If gate is satisfied or has a transition target, advance state
        if gate_result.next_state_id:
            # Check if the new state should be a completed state (terminal)
            advance_state(run_id, status.current_state_id, gate_result.next_state_id,
                         gate_result.reason, gate_result.round, store)
            new_status = store.load_status(run_id)
            result = ok_result({
                "action_taken": "gate_transition",
                "from_state": status.current_state_id,
                "to_state": gate_result.next_state_id,
                "gate_satisfied": gate_result.satisfied,
                "gate_reason": gate_result.reason,
                "run_id": run_id,
                "current_state_id": new_status.current_state_id,
                "status": new_status.status.value,
            })
            span.outputs = result
            return result

        # No transition — return pending status
        status_dict = flow_status(run_id)
        result = ok_result({
            "action_taken": "none",
            "gate_result": {
                "satisfied": gate_result.satisfied,
                "outstanding_roles": gate_result.outstanding_roles,
                "round": gate_result.round,
                "reason": gate_result.reason,
            },
            "run_id": run_id,
            "current_state_id": status.current_state_id,
        })
        span.outputs = result
        return result


def flow_send(
    run_id: str,
    state_id: str,
    from_role: str,
    intended_recipients: list[str],
    kind: str,
    content: str,
    visibility: str = "targeted",
    artifacts: list[str] | None = None,
    requires_ack: bool = False,
) -> dict[str, Any]:
    """Submit a scoped runtime message with atomic recipient validation."""
    tracer = get_tracer()
    with tracer.span("flow_send", inputs={
        "run_id": run_id, "state_id": state_id, "from_role": from_role,
        "intended_recipients": intended_recipients, "kind": kind,
    }) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        # Load state definition for routing policies
        conn = store.connect()
        state_row = conn.execute(
            "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
            (run_id, state_id),
        ).fetchone()
        if state_row is None:
            result = error_result(f"State {state_id} not found in run {run_id}")
            span.outputs = result
            return result

        from json import loads as json_loads
        state_dict = json_loads(state_row["state_json"])

        # FR-006 sender check: from_role must be a valid agent in this flow run
        conn2 = store.connect()
        agent_exists = conn2.execute(
            "SELECT 1 FROM agents WHERE run_id = ? AND role_id = ?",
            (run_id, from_role),
        ).fetchone()
        if agent_exists is None:
            actors = state_dict.get("actors", [])
            result = error_result(
                f"Sender '{from_role}' is not a registered agent in this run. "
                f"Known agents: {[r['role_id'] for r in conn2.execute('SELECT role_id FROM agents WHERE run_id=?', (run_id,)).fetchall()]}"
            )
            span.outputs = result
            return result

        # Build routing policies: allow sender to reach any known agent
        all_agent_roles = [
            r["role_id"] for r in conn.execute(
                "SELECT role_id FROM agents WHERE run_id = ?", (run_id,)
            ).fetchall()
        ]
        routing_policies: dict[str, list[str]] = {from_role: all_agent_roles}

        # Validate via router
        route_result = validate_message(
            run_id, state_id, from_role, intended_recipients,
            routing_policies, store,
        )

        # Create message envelope
        message_id = _new_id()
        now = _now()
        envelope = MessageEnvelope(
            message_id=message_id,
            run_id=run_id,
            state_id=state_id,
            from_role=from_role,
            intended_recipients=intended_recipients,
            authorized_recipients=route_result.authorized_recipients,
            recipient_availability={r: r not in route_result.unavailable_recipients for r in intended_recipients},
            visibility=visibility,
            kind=kind,
            content=content,
            artifacts=artifacts or [],
            requires_ack=requires_ack,
            delivery_outcome=DeliveryOutcome.DELIVERED if route_result.valid else DeliveryOutcome.REJECTED,
            rejection_reason=route_result.reason or "",
            created_at=now,
        )

        # Persist message record
        store.record_message_attempt(envelope)

        # If valid, deliver inbox entries to each authorized recipient
        if route_result.valid and route_result.authorized_recipients:
            for recipient in route_result.authorized_recipients:
                store.add_inbox_entries(run_id, recipient, state_id, [message_id])

        result = ok_result({
            "message_id": message_id,
            "delivery_outcome": envelope.delivery_outcome.value,
            "authorized_recipients": route_result.authorized_recipients,
            "invalid_recipients": route_result.invalid_recipients,
            "unavailable_recipients": route_result.unavailable_recipients,
            "rejection_reason": route_result.reason,
        })
        span.outputs = result
        return result


def flow_decide(
    run_id: str,
    state_id: str,
    role_id: str,
    value: str,
    reason: str = "",
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    """Record an agent or human decision for the current gate."""
    tracer = get_tracer()
    with tracer.span("flow_decide", inputs={
        "run_id": run_id, "state_id": state_id, "role_id": role_id, "value": value,
    }) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        now = _now()
        decision = Decision(
            decision_id=_new_id(),
            run_id=run_id,
            state_id=state_id,
            role_id=role_id,
            value=value,
            reason=reason,
            artifacts=artifacts or [],
            created_at=now,
        )

        store.record_decision(decision)
        store.append_audit_event(
            run_id=run_id,
            event_type="decision_recorded",
            state_id=state_id,
            actor=role_id,
            payload={"decision_value": value, "reason": reason},
        )

        result = ok_result({
            "decision_id": decision.decision_id,
            "value": value,
        })
        span.outputs = result
        return result


def flow_pause(
    run_id: str,
    reason: str,
) -> dict[str, Any]:
    """Pause an active run."""
    tracer = get_tracer()
    with tracer.span("flow_pause", inputs={"run_id": run_id, "reason": reason}) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        store.update_status(run_id, RunStatus.PAUSED)
        store.append_audit_event(
            run_id=run_id,
            event_type="run_paused",
            state_id="",
            actor="system",
            payload={"reason": reason},
        )

        result = ok_result({"run_id": run_id, "status": "paused"})
        span.outputs = result
        return result


def flow_resume(
    run_id: str,
    continuation_state: str = "",
) -> dict[str, Any]:
    """Resume a paused or escalated run."""
    tracer = get_tracer()
    with tracer.span("flow_resume", inputs={"run_id": run_id, "continuation_state": continuation_state}) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        # Optionally advance to a specific state
        if continuation_state:
            status = store.load_status(run_id)
            store.record_transition(run_id, status.current_state_id, continuation_state, "resume", 0)

        store.update_status(run_id, RunStatus.ACTIVE)
        store.append_audit_event(
            run_id=run_id,
            event_type="run_resumed",
            state_id=continuation_state or "",
            actor="system",
            payload={"continuation_state": continuation_state},
        )

        result = ok_result({"run_id": run_id, "status": "active"})
        span.outputs = result
        return result


def flow_abort(
    run_id: str,
    reason: str,
) -> dict[str, Any]:
    """Abort a run with an audit reason."""
    tracer = get_tracer()
    with tracer.span("flow_abort", inputs={"run_id": run_id, "reason": reason}) as span:
        try:
            store = _get_store(run_id)
        except RuntimeStateError as e:
            result = error_result(str(e))
            span.outputs = result
            return result

        store.update_status(run_id, RunStatus.ABORTED)
        store.append_audit_event(
            run_id=run_id,
            event_type="run_aborted",
            state_id="",
            actor="system",
            payload={"reason": reason},
        )

        result = ok_result({"run_id": run_id, "status": "aborted"})
        span.outputs = result
        return result
