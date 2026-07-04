"""Unit tests for Agent Session context packet building."""

from pathlib import Path

from hermes_flow.agent_session import prepare_context
from hermes_flow.schemas import AgentBinding, MemoryMode
from hermes_flow.storage import RuntimeStore


def test_prepare_context_includes_agent_metadata_from_run_specs(tmp_project_root: Path) -> None:
    """Context packets must include the metadata that becomes part of LLM input."""
    run_id = "ctx-agent-meta"
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / run_id
    store = RuntimeStore(run_dir)
    store.create_run(
        flow_id="test-flow",
        flow_version="1",
        initial_state_id="PLAN",
        agent_bindings=[
            AgentBinding("planner", "planner-profile", "", MemoryMode.RUN_ISOLATED),
        ],
        memory_modes={"planner": "run_isolated"},
        artifact_root=str(run_dir / "artifacts"),
        states_json={"PLAN": {"description": "Plan", "actors": ["planner"]}},
        override_run_id=run_id,
        agent_specs={
            "planner": {
                "role_id": "planner",
                "display_name": "Planner",
                "profile_name": "planner-profile",
                "soul": "Plan with evidence.",
                "skills": ["speckit-plan"],
                "toolsets": ["file", "terminal"],
                "read_scope": ["spec.md"],
                "write_scope": ["artifacts/plan.md"],
                "workspace_mode": "isolated",
                "memory_mode": "run_isolated",
            }
        },
    )

    context = prepare_context(run_id, "planner", store, state_id="PLAN")

    assert context["agent_metadata"]["soul"] == "Plan with evidence."
    assert context["skills"] == ["speckit-plan"]
    assert context["toolsets"] == ["file", "terminal"]
    assert context["read_scope"] == ["spec.md"]
    assert context["write_scope"] == ["artifacts/plan.md"]
