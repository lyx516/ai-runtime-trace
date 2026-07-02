"""Tool handlers exposed by plugin registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_flow.flow_loader import load_flow_from_yaml, validate_flow
from hermes_flow.schemas import (
    AgentBinding,
    FlowInitResult,
    FlowStatus,
    GateStatus,
    MessageEnvelope,
    StepResult,
    _now,
    to_dict,
)
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import SqliteTracer, set_tracer


# ── JSON response helpers ───────────────────────────────────────────────────

def ok_result(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap a successful result with an ok flag."""
    return {"ok": True, **data}


def error_result(message: str, details: list[str] | None = None) -> dict[str, Any]:
    """Wrap an error result with an ok flag and message."""
    return {"ok": False, "error": message, "details": details or []}


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
        override_run_id=run_id,  # use the directory name as run_id
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
    raise NotImplementedError("flow_status — implement in US5 (Phase 7)")


def flow_step(
    run_id: str,
    max_actions: int = 1,
) -> dict[str, Any]:
    """Execute the next eligible state action or gate evaluation."""
    raise NotImplementedError("flow_step — implement in US4 (Phase 6)")


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
    raise NotImplementedError("flow_send — implement in US3 (Phase 5)")


def flow_decide(
    run_id: str,
    state_id: str,
    role_id: str,
    value: str,
    reason: str = "",
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    """Record an agent or human decision for the current gate."""
    raise NotImplementedError("flow_decide — implement in US4 (Phase 6)")


def flow_pause(
    run_id: str,
    reason: str,
) -> dict[str, Any]:
    """Pause an active run."""
    raise NotImplementedError("flow_pause — implement in US5 (Phase 7)")


def flow_resume(
    run_id: str,
    continuation_state: str = "",
) -> dict[str, Any]:
    """Resume a paused or escalated run."""
    raise NotImplementedError("flow_resume — implement in US5 (Phase 7)")


def flow_abort(
    run_id: str,
    reason: str,
) -> dict[str, Any]:
    """Abort a run with an audit reason."""
    raise NotImplementedError("flow_abort — implement in US5 (Phase 7)")
