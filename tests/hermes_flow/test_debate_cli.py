"""Tests for debate CLI project-root resolution."""

import importlib.util
from pathlib import Path

from hermes_flow import debate_cli


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_debate_cli_defaults_to_repo_root_not_cwd(tmp_path, monkeypatch) -> None:
    """The pip-installed debate entrypoint must not create runs under arbitrary cwd."""
    monkeypatch.delenv("HERMES_FLOW_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    assert debate_cli.resolve_project_root() == str(REPO_ROOT)


def test_auto_debate_defaults_to_repo_root_not_import_cwd(tmp_path, monkeypatch) -> None:
    """auto-debate must honor the package project root even when imported from ~."""
    monkeypatch.delenv("HERMES_FLOW_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    path = REPO_ROOT / "experiments" / "agent-pool" / "auto-debate.py"
    spec = importlib.util.spec_from_file_location("auto_debate_root_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.PROJECT_ROOT == str(REPO_ROOT)


def test_debate_cli_respects_explicit_project_root(tmp_path, monkeypatch) -> None:
    """Advanced users can still override the project root explicitly."""
    monkeypatch.setenv("HERMES_FLOW_PROJECT_ROOT", str(tmp_path))

    assert debate_cli.resolve_project_root() == str(tmp_path)
