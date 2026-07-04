#!/usr/bin/env python3
"""CLI entry point for `debate` command (registered via pyproject.toml console_scripts).

Usage:
    debate <task description>
    debate "实现一个向量数据库，索引性能为先"

Uses the repository root as the default project root so runs are visible in
the bundled dashboard even when `debate` is invoked from another directory.
Set HERMES_FLOW_PROJECT_ROOT to override.
"""

import os
import sys
from pathlib import Path


def resolve_project_root() -> str:
    """Resolve where debate runs and artifacts should be stored."""
    return os.environ.get("HERMES_FLOW_PROJECT_ROOT") or str(Path(__file__).resolve().parent.parent)


def main():
    project_root = resolve_project_root()

    # Locate the agent-pool package relative to this file
    pkg_dir = Path(__file__).resolve().parent.parent / "experiments" / "agent-pool"
    if str(pkg_dir) not in sys.path:
        sys.path.insert(0, str(pkg_dir))

    # Set workspace for child processes and tools
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = project_root
    os.environ["HERMES_WORKSPACE_ROOT"] = project_root

    from cli import main as debate_main
    sys.argv[0] = "debate"
    debate_main()


if __name__ == "__main__":
    main()
