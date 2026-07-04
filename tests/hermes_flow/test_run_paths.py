from pathlib import Path

from hermes_flow.tools import flow_init
from hermes_flow.run_paths import get_runs_dir, get_run_dir


def test_runs_dir_env_override_is_canonical(tmp_path, monkeypatch):
    fixed = tmp_path / "fixed-runs"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("HERMES_FLOW_RUNS_DIR", str(fixed))

    assert get_runs_dir(workspace) == fixed
    assert get_run_dir("run-1", workspace) == fixed / "run-1"


def test_runs_dir_defaults_to_project_root_when_no_override(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_FLOW_RUNS_DIR", raising=False)

    assert get_runs_dir(tmp_path) == tmp_path / ".hermes-flow" / "runs"


def test_flow_init_writes_new_run_to_fixed_runs_dir(tmp_path, monkeypatch):
    fixed = tmp_path / "fixed-runs"
    workspace = tmp_path / "workspace"
    flow_path = workspace / "flow.yaml"
    flow_path.parent.mkdir(parents=True)
    flow_path.write_text(
        """
flow_id: fixed-test
name: Fixed test
version: 1
initial_state_id: done
agents: {}
states:
  done:
    terminal: true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_FLOW_RUNS_DIR", str(fixed))

    result = flow_init(str(workspace), str(flow_path), "fixed test")

    assert result["ok"] is True
    run_id = result["run_id"]
    assert (fixed / run_id / "state.sqlite").exists()
    assert not (workspace / ".hermes-flow" / "runs" / run_id).exists()
