"""Workspace scope guard for file tools.

All file operations are scoped to HERMES_WORKSPACE_ROOT.
Paths outside this boundary are rejected.
The agent never sees this parameter — it's injected automatically.
"""

import os
from pathlib import Path


def get_workspace_root() -> Path:
    """Return the absolute workspace root path.
    
    Set via HERMES_WORKSPACE_ROOT env var, or falls back to cwd.
    """
    root = os.environ.get("HERMES_WORKSPACE_ROOT") or os.getcwd()
    return Path(root).resolve()


def resolve_path(path: str) -> Path:
    """Resolve a user-provided path within the workspace root.
    
    Relative paths are resolved relative to workspace root.
    Absolute paths are allowed only if they're within the workspace.
    
    Returns the resolved absolute Path.
    Raises PermissionError if path is outside workspace.
    """
    workspace = get_workspace_root()
    
    if not path:
        raise PermissionError(f"path is empty")
    
    target = Path(path)
    if not target.is_absolute():
        target = workspace / path
    
    target = target.resolve()
    
    # Reject if outside workspace
    try:
        target.relative_to(workspace)
    except ValueError:
        raise PermissionError(
            f"Access denied: '{path}' is outside the workspace ({workspace}). "
            f"All file operations are scoped to the current working directory."
        )
    
    return target


def safe_path(path: str):
    """Resolve a path safely. Returns (path, error)."""
    try:
        return resolve_path(path), None
    except PermissionError as e:
        return Path(), str(e)
