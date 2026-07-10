"""Workspace scope guard for file tools.

All file operations are scoped to HERMES_WORKSPACE_ROOT.
On top of that, write operations are further restricted to HERMES_WRITE_SCOPE
and read operations to HERMES_READ_SCOPE (falling back to HERMES_WRITE_SCOPE
if HERMES_READ_SCOPE is not set).

Env vars:
  HERMES_WORKSPACE_ROOT  — the outermost boundary (required)
  HERMES_WRITE_SCOPE     — JSON list of allowed write dirs, relative to workspace
  HERMES_READ_SCOPE      — JSON list of allowed read dirs, relative to workspace

The caller (run_flow) sets these per-agent before each agent session.
"""

import json
import os
from pathlib import Path


def get_workspace_root() -> Path:
    """Return the absolute workspace root path."""
    root = os.environ.get("HERMES_WORKSPACE_ROOT") or os.getcwd()
    return Path(root).resolve()


def _resolve_against_workspace(path: str) -> Path:
    """Resolve a path to absolute, checking it's within workspace. Internal."""
    workspace = get_workspace_root()

    if not path:
        raise PermissionError("path is empty")

    target = Path(path)
    if not target.is_absolute():
        target = workspace / path

    target = target.resolve()

    # Sandbox mode: allow redirected paths (under sandbox root)
    import tools._security as _sec
    if _sec._SANDBOX_ROOT and str(target).startswith(str(_sec._SANDBOX_ROOT)):
        return target

    try:
        target.relative_to(workspace)
    except ValueError:
        raise PermissionError(
            f"Access denied: '{path}' is outside the workspace ({workspace}). "
            f"All file operations are scoped to the current working directory."
        )

    return target


def _check_scope(target: Path, scope_dirs: list[str]) -> None:
    """Raise PermissionError if target is not under any of scope_dirs."""
    workspace = get_workspace_root()

    if not scope_dirs:
        # No scope restriction — allow anywhere under workspace
        return

    for d in scope_dirs:
        scope_path = (workspace / d).resolve()
        try:
            target.relative_to(scope_path)
            return  # allowed
        except ValueError:
            continue

    raise PermissionError(
        f"Access denied: path is outside allowed scope. "
        f"Allowed: {scope_dirs}"
    )


def resolve_write_path(path: str) -> Path:
    """Resolve a path for writing — must be within write_scope."""
    target = _resolve_against_workspace(path)

    write_scope = _parse_scope_list(os.environ.get("HERMES_WRITE_SCOPE", ""))
    _check_scope(target, write_scope)

    return target


def resolve_read_path(path: str) -> Path:
    """Resolve a path for reading — must be within read_scope (or write_scope fallback)."""
    target = _resolve_against_workspace(path)

    read_scope = _parse_scope_list(os.environ.get("HERMES_READ_SCOPE", ""))
    if not read_scope:
        read_scope = _parse_scope_list(os.environ.get("HERMES_WRITE_SCOPE", ""))

    _check_scope(target, read_scope)

    return target


# ── Backward compat (without scope check) ──

def resolve_path(path: str) -> Path:
    """Resolve a path within workspace only (no scope check). Use resolve_write_path / resolve_read_path for sandboxed access."""
    return _resolve_against_workspace(path)


def safe_path(path: str):
    """Resolve a path safely. Returns (path, error)."""
    try:
        return resolve_path(path), None
    except PermissionError as e:
        return Path(), str(e)


def safe_write_path(path: str):
    """Resolve a write path safely. Returns (path, error)."""
    try:
        return resolve_write_path(path), None
    except PermissionError as e:
        return Path(), str(e)


def safe_read_path(path: str):
    """Resolve a read path safely. Returns (path, error)."""
    try:
        return resolve_read_path(path), None
    except PermissionError as e:
        return Path(), str(e)


# ── Helpers ──

def _parse_scope_list(raw: str) -> list[str]:
    """Parse a JSON-encoded list of scope dirs from env var."""
    if not raw or not raw.strip():
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(v) for v in val]
        return []
    except json.JSONDecodeError:
        return []
