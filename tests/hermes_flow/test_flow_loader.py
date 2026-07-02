"""Flow loader tests — valid flow loading and invalid flow validation."""

from pathlib import Path

import pytest
import yaml

from hermes_flow.errors import FlowValidationError
from hermes_flow.flow_loader import load_flow_from_yaml, validate_flow


def test_valid_flow_loads_correctly(sample_flow_yaml_path: Path) -> None:
    """A valid flow definition must load into a FlowDefinition with expected fields."""
    flow = load_flow_from_yaml(str(sample_flow_yaml_path))
    assert flow.flow_id == "test-flow"
    assert flow.initial_state_id == "PLAN"
    assert "DONE" in flow.terminal_state_ids
    assert "ABORT" in flow.terminal_state_ids
    assert "planner" in flow.agents
    assert "reviewer" in flow.agents
    assert "PLAN" in flow.states
    assert "REVIEW" in flow.states
    # REVIEW gate should have max_rounds=3
    review = flow.states["REVIEW"]
    assert review.gate is not None
    assert review.gate.max_rounds == 3


def test_invalid_flow_missing_agent_raises(sample_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """A flow referencing a missing agent role must fail validation."""
    import yaml
    bad_yaml = tmp_project_root / "missing-agent.yaml"
    with open(sample_flow_yaml_path) as f:
        data = yaml.safe_load(f)
    # Replace planner agent with a missing one
    data["states"]["PLAN"]["actors"] = ["nonexistent_agent"]
    with open(bad_yaml, "w") as f:
        yaml.dump(data, f)

    flow = load_flow_from_yaml(str(bad_yaml))
    with pytest.raises(FlowValidationError) as exc:
        validate_flow(flow)
    details = " ".join(exc.value.details)
    assert "nonexistent_agent" in details


def test_invalid_flow_no_terminal_state(sample_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """A flow without any terminal state must fail validation."""
    import yaml
    bad_yaml = tmp_project_root / "no-terminal.yaml"
    with open(sample_flow_yaml_path) as f:
        data = yaml.safe_load(f)
    data["terminal_state_ids"] = []
    del data["states"]["DONE"]
    del data["states"]["ABORT"]
    with open(bad_yaml, "w") as f:
        yaml.dump(data, f)

    flow = load_flow_from_yaml(str(bad_yaml))
    with pytest.raises(FlowValidationError) as exc:
        validate_flow(flow)
    details = " ".join(exc.value.details).lower()
    assert "terminal" in details


def test_invalid_flow_unreachable_state(sample_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """A state that is not reachable from the initial state must fail validation."""
    import yaml
    bad_yaml = tmp_project_root / "unreachable.yaml"
    with open(sample_flow_yaml_path) as f:
        data = yaml.safe_load(f)
    # Add an orphan state
    data["states"]["ORPHAN"] = {"actors": [], "transitions": {}}
    with open(bad_yaml, "w") as f:
        yaml.dump(data, f)

    flow = load_flow_from_yaml(str(bad_yaml))
    with pytest.raises(FlowValidationError) as exc:
        validate_flow(flow)
    details = " ".join(exc.value.details).lower()
    assert "unreachable" in details or "orphan" in details


def test_invalid_flow_invalid_transition_target(sample_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """A transition referencing a non-existent state must fail validation."""
    import yaml
    bad_yaml = tmp_project_root / "bad-transition.yaml"
    with open(sample_flow_yaml_path) as f:
        data = yaml.safe_load(f)
    data["states"]["PLAN"]["transitions"] = {"on_complete": "NONEXISTENT"}
    with open(bad_yaml, "w") as f:
        yaml.dump(data, f)

    flow = load_flow_from_yaml(str(bad_yaml))
    with pytest.raises(FlowValidationError) as exc:
        validate_flow(flow)
    details = " ".join(exc.value.details)
    assert "NONEXISTENT" in details


def test_invalid_flow_loop_without_max_rounds(tmp_project_root: Path) -> None:
    """A revision loop without max_rounds or escalation path must fail validation."""
    import yaml
    bad_yaml = tmp_project_root / "bad-loop.yaml"
    data = {
        "flow_id": "bad-loop",
        "name": "Bad Loop",
        "version": 1,
        "initial_state_id": "PLAN",
        "terminal_state_ids": ["DONE"],
        "agents": {
            "planner": {"profile_name": "fp", "soul": "x", "skills": [], "toolsets": [], "memory_mode": "run_isolated", "read_scope": [], "write_scope": []},
            "reviewer": {"profile_name": "fr", "soul": "y", "skills": [], "toolsets": [], "memory_mode": "run_isolated", "read_scope": [], "write_scope": []},
        },
        "states": {
            "PLAN": {
                "actors": ["planner"],
                "gate": {
                    "type": "decision",
                    "required_roles": ["reviewer"],
                    "pass_values": ["APPROVE"],
                    "fail_values": ["REQUEST_CHANGES"],
                    "on_pass": "DONE",
                    "on_fail": "PLAN",
                    # max_rounds omitted — should fail validation
                },
                "transitions": {},
            },
            "DONE": {"terminal": True},
        },
    }
    with open(bad_yaml, "w") as f:
        yaml.dump(data, f)

    flow = load_flow_from_yaml(str(bad_yaml))
    with pytest.raises(FlowValidationError) as exc:
        validate_flow(flow)
    # Should mention missing max_rounds or unbounded loop
    details = " ".join(exc.value.details).lower()
    assert "max_rounds" in details or "unbounded" in details or "loop" in details


def test_validation_reports_all_issues(tmp_project_root: Path) -> None:
    """Invalid flow validation must report all blocking issues, not just the first."""
    import yaml
    bad_yaml = tmp_project_root / "multi-error.yaml"
    data = {
        "flow_id": "multi-error",
        "name": "Multi Error",
        "version": 1,
        "initial_state_id": "MISSING",
        "terminal_state_ids": [],
        "agents": {},
        "states": {
            "A": {"actors": [], "transitions": {"on_complete": "B"}},
            "B": {"actors": [], "transitions": {}},
        },
    }
    with open(bad_yaml, "w") as f:
        yaml.dump(data, f)

    flow = load_flow_from_yaml(str(bad_yaml))
    with pytest.raises(FlowValidationError) as exc:
        validate_flow(flow)
    errors = exc.value.details
    assert len(errors) >= 2, f"Expected at least 2 validation errors, got {len(errors)}: {errors}"
