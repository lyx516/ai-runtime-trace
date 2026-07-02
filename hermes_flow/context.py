"""State-specific context packet generation for agent roles."""

from __future__ import annotations

from typing import Any

from hermes_flow.errors import ContextPolicyError
from hermes_flow.schemas import (
    AgentRole,
    Artifact,
    FlowDefinition,
    FlowRun,
    MemoryMode,
    MessageEnvelope,
    State,
    to_dict,
)


def build_context_packet(
    run: FlowRun,
    flow: FlowDefinition,
    state: State,
    role: AgentRole,
    inbox_messages: list[MessageEnvelope],
    readable_artifacts: list[Artifact],
) -> dict[str, Any]:
    """Produce a JSON-serializable context packet for one agent action.

    The packet includes only the role-specific context, never the full
    conversation history or project state.
    """
    return {
        "run_id": run.run_id,
        "state_id": state.state_id,
        "role_id": role.role_id,
        "soul": role.soul,
        "skills": list(role.skills),
        "toolsets": list(role.toolsets),
        "memory_mode": role.memory_mode.value,
        "read_scope": list(role.read_scope),
        "write_scope": list(role.write_scope),
        "inbox_messages": [to_dict(m) for m in inbox_messages],
        "readable_artifacts": [to_dict(a) for a in readable_artifacts],
        "required_outputs": list(state.output_artifacts),
        "current_state_objective": state.description or f"Execute role '{role.role_id}' in state '{state.state_id}'",
        "memory_modes": dict(run.memory_modes),
    }


def validate_artifact_write(role: AgentRole, artifact_path: str) -> None:
    """Validate that `artifact_path` is inside the role's `write_scope`.

    Raises ContextPolicyError if the path is outside permitted scope.
    """
    if not role.write_scope:
        raise ContextPolicyError(
            f"Role '{role.role_id}' has no write_scope configured",
            details=["Write scope is empty — no artifact writes are permitted"],
        )

    # Normalise paths for comparison
    from pathlib import Path
    target = Path(artifact_path)

    for permitted in role.write_scope:
        permitted_path = Path(permitted)
        # Check if target is under permitted path, or exact match
        try:
            target.relative_to(permitted_path)
            return  # Path is within scope
        except ValueError:
            pass

        # Also allow exact match (pathlib relative_to fails for non-prefix)
        if str(target) == str(permitted_path):
            return

    raise ContextPolicyError(
        f"Role '{role.role_id}' cannot write to '{artifact_path}'",
        details=[
            f"Write scope: {role.write_scope}",
            f"Requested path is outside all permitted prefixes",
        ],
    )
