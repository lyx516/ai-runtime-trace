"""Load and validate project-local flow definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes_flow.errors import FlowValidationError
from hermes_flow.schemas import (
    AgentRole,
    FlowDefinition,
    Gate,
    GateType,
    MemoryMode,
    State,
    Transition,
)
from hermes_flow.trace import get_tracer


def load_flow_from_yaml(path: str | Path) -> FlowDefinition:
    """Parse a YAML flow file into a FlowDefinition dataclass.

    Raises FlowValidationError on unknown top-level fields.
    """
    import yaml

    tracer = get_tracer()
    with tracer.span("load_flow", inputs={"path": str(path)}) as span:
        path = Path(path)
        if not path.exists():
            raise FlowValidationError(f"Flow file not found: {path}")

        with open(path) as f:
            raw: dict[str, Any] = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise FlowValidationError("Flow definition must be a YAML mapping")

        # Reject unknown top-level fields
        known_fields = {
            "flow_id", "name", "version", "initial_state_id", "terminal_state_ids",
            "agents", "states", "routing_policies", "loop_defaults",
        }
        unknown = set(raw) - known_fields
        if unknown:
            raise FlowValidationError(f"Unknown top-level fields: {', '.join(sorted(unknown))}")

        # Parse agents
        agents: dict[str, AgentRole] = {}
        for agent_id, agent_raw in raw.get("agents", {}).items():
            memory_raw = agent_raw.get("memory_mode", "run_isolated")
            try:
                memory_mode = MemoryMode(memory_raw)
            except ValueError:
                memory_mode = MemoryMode.RUN_ISOLATED
            agents[agent_id] = AgentRole(
                role_id=agent_id,
                display_name=agent_raw.get("display_name", agent_id),
                soul=agent_raw.get("soul", ""),
                profile_name=agent_raw.get("profile_name", ""),
                skills=agent_raw.get("skills", []),
                toolsets=agent_raw.get("toolsets", []),
                read_scope=agent_raw.get("read_scope", []),
                write_scope=agent_raw.get("write_scope", []),
                workspace_mode=agent_raw.get("workspace_mode", "isolated"),
                memory_mode=memory_mode,
                max_action_seconds=agent_raw.get("max_action_seconds"),
            )

        # Parse states
        states: dict[str, State] = {}
        for state_id, state_raw in raw.get("states", {}).items():
            gate_raw = state_raw.get("gate")
            gate = None
            if gate_raw:
                try:
                    gate_type = GateType(gate_raw.get("type", "decision"))
                except ValueError:
                    gate_type = GateType.DECISION
                gate = Gate(
                    gate_id=gate_raw.get("gate_id", f"{state_id}_gate"),
                    type=gate_type,
                    required_roles=gate_raw.get("required_roles", []),
                    pass_values=gate_raw.get("pass_values", ["APPROVE", "PASS"]),
                    fail_values=gate_raw.get("fail_values", ["REQUEST_CHANGES", "FAIL"]),
                    blocked_values=gate_raw.get("blocked_values", ["BLOCKED"]),
                    on_pass=gate_raw.get("on_pass", ""),
                    on_fail=gate_raw.get("on_fail", ""),
                    on_blocked=gate_raw.get("on_blocked", ""),
                    on_exhausted=gate_raw.get("on_exhausted", ""),
                    max_rounds=gate_raw.get("max_rounds", 0),
                )

            transitions_raw = state_raw.get("transitions", {})
            transitions = [
                Transition(target_state_id=target, condition=condition)
                for condition, target in transitions_raw.items()
            ]

            states[state_id] = State(
                state_id=state_id,
                description=state_raw.get("description", ""),
                actors=state_raw.get("actors", []),
                input_artifacts=state_raw.get("input_artifacts", []),
                output_artifacts=state_raw.get("output_artifacts", []),
                message_acceptance=state_raw.get("message_acceptance", True),
                gate=gate,
                transitions=transitions,
                max_rounds=state_raw.get("max_rounds", 0),
                on_exhausted=state_raw.get("on_exhausted", ""),
                idle_timeout_seconds=state_raw.get("idle_timeout_seconds"),
                terminal=state_raw.get("terminal", False),
                human=state_raw.get("human", False),
            )

        loop_defaults = raw.get("loop_defaults", {})

        flow = FlowDefinition(
            flow_id=raw.get("flow_id", path.stem),
            name=raw.get("name", path.stem),
            version=str(raw.get("version", "1")),
            agents=agents,
            states=states,
            initial_state_id=raw.get("initial_state_id", ""),
            terminal_state_ids=raw.get("terminal_state_ids", []),
            routing_policies=raw.get("routing_policies", {}),
            loop_defaults=loop_defaults,
        )

        span.outputs = {
            "flow_id": flow.flow_id,
            "agent_count": len(flow.agents),
            "state_count": len(flow.states),
        }
        span.decisions = {}
        return flow


def validate_flow(flow: FlowDefinition) -> None:
    """Validate a flow definition, raising FlowValidationError with all issues.

    Checks:
    - initial_state_id exists
    - at least one terminal state exists
    - every transition target references an existing state
    - every actor references an existing agent role
    - no unreachable states (except terminal)
    - every gate loop has max_rounds or on_exhausted
    - states with idle_timeout_seconds must have on_exhausted
    """
    tracer = get_tracer()
    with tracer.span("validate_flow", inputs={"flow_id": flow.flow_id, "agent_count": len(flow.agents)}) as span:
        errors: list[str] = []

        # 1. initial_state_id exists
        if flow.initial_state_id not in flow.states:
            errors.append(f"initial_state_id '{flow.initial_state_id}' does not exist in states")

        # 2. at least one terminal state
        actual_terminal = [sid for sid, s in flow.states.items() if s.terminal]
        if not actual_terminal:
            errors.append("No terminal state defined")

        # 3. every transition target exists
        for sid, state in flow.states.items():
            for t in state.transitions:
                if t.target_state_id not in flow.states:
                    errors.append(f"State '{sid}' has transition to non-existent state '{t.target_state_id}'")

        # 4. every actor references an existing agent role
        for sid, state in flow.states.items():
            for actor in state.actors:
                if actor not in flow.agents:
                    errors.append(f"State '{sid}' references agent role '{actor}' which is not defined in agents")

        # 5. unreachable states (BFS from initial_state_id)
        if flow.initial_state_id in flow.states:
            reachable = _reachable_states(flow)
            for sid in flow.states:
                if sid not in reachable and not flow.states[sid].terminal:
                    errors.append(f"State '{sid}' is unreachable from initial state '{flow.initial_state_id}'")

        # 6. gate loop without max_rounds or on_exhausted
        for sid, state in flow.states.items():
            if state.gate:
                if state.gate.max_rounds == 0 and not state.gate.on_exhausted:
                    if state.gate.on_fail or state.gate.on_blocked:
                        errors.append(f"State '{sid}' has a revision/blocked path but gate has no max_rounds and no on_exhausted — risk of unbounded loop")

        # 7. idle_timeout_seconds without on_exhausted
        for sid, state in flow.states.items():
            if state.idle_timeout_seconds is not None and state.idle_timeout_seconds > 0:
                if not state.on_exhausted:
                    errors.append(f"State '{sid}' has idle_timeout_seconds={state.idle_timeout_seconds} but no on_exhausted path")

        # 8. gate on_pass/on_fail/on_blocked/on_exhausted targets exist
        for sid, state in flow.states.items():
            if state.gate:
                for target in [state.gate.on_pass, state.gate.on_fail, state.gate.on_blocked, state.gate.on_exhausted]:
                    if target and target not in flow.states:
                        errors.append(f"State '{sid}' gate has target '{target}' which does not exist in states")

        span.outputs = {"valid": len(errors) == 0, "error_count": len(errors)}
        span.decisions = {} if not errors else {"validation_errors": errors}

        if errors:
            raise FlowValidationError(
                f"Flow validation failed: {len(errors)} issue(s)",
                details=errors,
            )


def _reachable_states(flow: FlowDefinition) -> set[str]:
    """BFS from initial_state_id to find all reachable states."""
    visited: set[str] = set()
    queue = [flow.initial_state_id]
    while queue:
        sid = queue.pop(0)
        if sid in visited or sid not in flow.states:
            continue
        visited.add(sid)
        state = flow.states[sid]
        for t in state.transitions:
            if t.target_state_id not in visited:
                queue.append(t.target_state_id)
        # Also follow gate transitions (on_pass, on_fail, on_blocked, on_exhausted)
        if state.gate:
            for target in [state.gate.on_pass, state.gate.on_fail, state.gate.on_blocked, state.gate.on_exhausted]:
                if target and target not in visited and target in flow.states:
                    queue.append(target)
    return visited
