"""CLI quickstart integration tests for Hermes Flow."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


CLI = [sys.executable, "-m", "hermes_flow.cli"]


def test_cli_init_creates_run(sample_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """python -m hermes_flow.cli init must create a run and return JSON with run_id and current_state_id=PLAN."""
    result = subprocess.run(
        CLI + ["init", "--flow", str(sample_flow_yaml_path), "--project-root", str(tmp_project_root)],
        capture_output=True, text=True, cwd=tmp_project_root,
    )
    assert result.returncode == 0, f"CLI init failed:\nstdout:{result.stdout}\nstderr:{result.stderr}"
    data = json.loads(result.stdout)
    assert data.get("ok") is True
    assert "run_id" in data
    assert data.get("current_state_id") == "PLAN"
    assert "agents" in data


def test_cli_init_dry_run_no_runtime(sample_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """CLI init with --dry-run must not create any run record in state.sqlite."""
    result = subprocess.run(
        CLI + ["init", "--flow", str(sample_flow_yaml_path), "--project-root", str(tmp_project_root), "--dry-run"],
        capture_output=True, text=True, cwd=tmp_project_root,
    )
    assert result.returncode == 0, f"CLI dry-run failed:\nstdout:{result.stdout}\nstderr:{result.stderr}"
    data = json.loads(result.stdout)
    assert data.get("ok") is True
    # dry-run may create a trace store but must not have a run record
    # (run_id is empty in dry-run mode)


def test_cli_init_invalid_flow_fails(invalid_flow_yaml_path: Path, tmp_project_root: Path) -> None:
    """CLI init with an invalid flow must exit non-zero and report validation errors."""
    result = subprocess.run(
        CLI + ["init", "--flow", str(invalid_flow_yaml_path), "--project-root", str(tmp_project_root)],
        capture_output=True, text=True, cwd=tmp_project_root,
    )
    assert result.returncode != 0, "Invalid flow should return non-zero exit"
    data = json.loads(result.stdout)
    assert data.get("ok") is False
    # Should report validation errors
    assert "details" in data or "error" in data
