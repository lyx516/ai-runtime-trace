#!/usr/bin/env python3
"""CLI entry point for `debate` command (registered via pyproject.toml console_scripts).

Usage:
    debate <task description>
    debate "实现一个向量数据库，索引性能为先"

Uses the current working directory as the project root.
Flow runs, artifacts, and workspaces are created relative to cwd.
"""

import os
import sys
from pathlib import Path


def main():
    project_root = os.getcwd()

    # Locate the agent-pool package relative to this file
    pkg_dir = Path(__file__).resolve().parent.parent / "experiments" / "agent-pool"
    if str(pkg_dir) not in sys.path:
        sys.path.insert(0, str(pkg_dir))

    # Set workspace to cwd
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = project_root
    os.environ["HERMES_WORKSPACE_ROOT"] = project_root

    from cli import main as debate_main
    sys.argv[0] = "debate"
    debate_main()


if __name__ == "__main__":
    main()
