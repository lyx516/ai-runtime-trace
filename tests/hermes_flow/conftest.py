"""Reusable pytest fixtures for Hermes Flow tests."""

import json as std_json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from hermes_flow.schemas import (
    AgentBinding,
    MemoryMode,
)
from hermes_flow.trace import NoOpTracer, set_tracer


# Auto-reset tracer before every test
@pytest.fixture(autouse=True)
def _reset_tracer() -> Generator:
    """Reset the module-level tracer to NoOpTracer before each test."""
    set_tracer(NoOpTracer())
    yield


@pytest.fixture
def tmp_project_root() -> Generator[Path, None, None]:
    """Create a temporary project root directory that is cleaned up after the test."""
    tmpdir = Path(tempfile.mkdtemp(prefix="hermes-flow-test-"))
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_flow_yaml_path(tmp_project_root: Path) -> Path:
    """Create a sample valid flow definition YAML and return its path."""
    content = {
        "flow_id": "test-flow",
        "name": "Test Flow",
        "version": 1,
        "initial_state_id": "PLAN",
        "terminal_state_ids": ["DONE", "ABORT"],
        "agents": {
            "planner": {
                "profile_name": "flow-planner",
                "soul": "Plan things.",
                "skills": [],
                "toolsets": ["file"],
                "memory_mode": "run_isolated",
                "read_scope": ["spec.md"],
                "write_scope": ["artifacts/plan.md"],
            },
            "reviewer": {
                "profile_name": "flow-reviewer",
                "soul": "Review things.",
                "skills": [],
                "toolsets": ["file"],
                "memory_mode": "run_isolated",
                "read_scope": ["spec.md", "artifacts/plan.md"],
                "write_scope": ["artifacts/review.md"],
            },
        },
        "states": {
            "PLAN": {
                "actors": ["planner"],
                "output_artifacts": ["artifacts/plan.md"],
                "transitions": {"on_complete": "REVIEW"},
            },
            "REVIEW": {
                "actors": ["reviewer"],
                "gate": {
                    "type": "decision",
                    "required_roles": ["reviewer"],
                    "pass_values": ["APPROVE", "PASS"],
                    "fail_values": ["REQUEST_CHANGES", "FAIL"],
                    "blocked_values": ["BLOCKED"],
                    "on_pass": "DONE",
                    "on_fail": "PLAN",
                    "on_blocked": "HUMAN_ESCALATION",
                    "max_rounds": 3,
                },
            },
            "HUMAN_ESCALATION": {
                "human": True,
                "transitions": {"resume": "PLAN", "abort": "ABORT"},
            },
            "DONE": {"terminal": True},
            "ABORT": {"terminal": True},
        },
    }
    path = tmp_project_root / "test-flow.yaml"
    import yaml
    with open(path, "w") as f:
        yaml.dump(content, f, default_flow_style=False)
    return path


@pytest.fixture
def invalid_flow_yaml_path(tmp_project_root: Path) -> Path:
    """Create a flow definition with a missing agent role (should fail validation)."""
    content = {
        "flow_id": "bad-flow",
        "name": "Bad Flow",
        "version": 1,
        "initial_state_id": "PLAN",
        "terminal_state_ids": ["DONE"],
        "agents": {},
        "states": {
            "PLAN": {
                "actors": ["missing_agent"],
                "output_artifacts": ["plan.md"],
                "transitions": {"on_complete": "DONE"},
            },
            "DONE": {"terminal": True},
        },
    }
    path = tmp_project_root / "bad-flow.yaml"
    import yaml
    with open(path, "w") as f:
        yaml.dump(content, f, default_flow_style=False)
    return path


@pytest.fixture
def sample_run_id() -> str:
    return "test-run-001"


@pytest.fixture
def sample_agent_bindings() -> list[AgentBinding]:
    return [
        AgentBinding(role_id="planner", profile_name="flow-planner", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
        AgentBinding(role_id="reviewer", profile_name="flow-reviewer", session_id="", memory_mode=MemoryMode.RUN_ISOLATED),
    ]
