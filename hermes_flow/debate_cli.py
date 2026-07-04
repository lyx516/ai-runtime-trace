#!/usr/bin/env python3
"""CLI entry point for `debate` command (registered via pyproject.toml console_scripts).

Usage:
    debate <task description>
    debate --workdir /tmp/my-project "实现一个向量数据库，索引性能为先"

Uses the repository root as the default project root.
Set --workdir to override, or set HERMES_FLOW_PROJECT_ROOT env var.
"""

import os
import sys
from pathlib import Path


def resolve_project_root() -> str:
    """Resolve where debate runs and artifacts should be stored."""
    return os.environ.get("HERMES_FLOW_PROJECT_ROOT") or str(Path(__file__).resolve().parent.parent)


def main():
    repo_root = Path(__file__).resolve().parent.parent

    # ── Parse --workdir from argv before delegating ──
    workdir = ""
    remaining = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--workdir" and i + 1 < len(sys.argv):
            workdir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i].startswith("--workdir="):
            workdir = sys.argv[i].split("=", 1)[1]
            i += 1
        else:
            remaining.append(sys.argv[i])
            i += 1

    if workdir:
        workdir = str(Path(workdir).resolve())
        project_root = workdir
        os.makedirs(workdir, exist_ok=True)
    else:
        project_root = resolve_project_root()

    os.environ.setdefault("HERMES_FLOW_RUNS_DIR", str(repo_root / ".hermes-flow" / "runs"))

    sys.argv = [sys.argv[0]] + remaining

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
