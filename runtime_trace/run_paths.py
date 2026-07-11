"""Canonical filesystem locations for Runtime Trace runtime stores."""

from __future__ import annotations

import os
from pathlib import Path

RUNS_DIR_NAME = ".runtime-trace/runs"
RUNS_DIR_ENV = "RUNTIME_TRACE_RUNS_DIR"
PROJECT_ROOT_ENV = "RUNTIME_TRACE_PROJECT_ROOT"


def default_project_root() -> Path:
    """Return the repository/package root used as the default runtime root."""
    return Path(__file__).resolve().parent.parent


def get_project_root(project_root: str | Path | None = None) -> Path:
    """Resolve the workspace/project root without creating directories."""
    if project_root:
        return Path(project_root).expanduser().resolve()
    env_root = os.environ.get(PROJECT_ROOT_ENV)
    if env_root:
        return Path(env_root).expanduser().resolve()
    return default_project_root().resolve()


def get_runs_dir(project_root: str | Path | None = None, *, create: bool = False) -> Path:
    """Return the canonical directory containing per-run SQLite stores.

    RUNTIME_TRACE_RUNS_DIR pins all runs to one fixed location.  If it is not
    set, runs remain project-local under <project-root>/.runtime-trace/runs.
    """
    override = os.environ.get(RUNS_DIR_ENV)
    if override:
        runs_dir = Path(override).expanduser().resolve()
    else:
        runs_dir = get_project_root(project_root) / RUNS_DIR_NAME
    if create:
        runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir


def get_run_dir(run_id: str, project_root: str | Path | None = None, *, create: bool = False) -> Path:
    """Return the canonical directory for one run id."""
    run_dir = get_runs_dir(project_root, create=create) / run_id
    if create:
        run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
