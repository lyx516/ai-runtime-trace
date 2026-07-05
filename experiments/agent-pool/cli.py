#!/usr/bin/env python3
"""CLI entry point for `debate` command.

Usage:
    debate <task description>
    debate "实现一个向量数据库，索引性能为先"

The command uses the repository root as the default project root.
Set HERMES_FLOW_PROJECT_ROOT to override.
"""

import os
import sys
from pathlib import Path


def main():
    # Locate the package root (where agents/, tools/, shared/ live)
    pkg_dir = Path(__file__).resolve().parent
    project_root = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or str(pkg_dir.parent.parent)
    runs_dir = os.environ.get("HERMES_FLOW_RUNS_DIR") or str(pkg_dir / ".hermes-flow" / "runs")

    # Ensure hermes_flow is importable (in case not pip-installed)
    hermes_flow_dir = pkg_dir.parent.parent
    if hermes_flow_dir not in sys.path:
        sys.path.insert(0, str(hermes_flow_dir))

    # Set env vars for child processes and tools
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = project_root
    os.environ["HERMES_FLOW_RUNS_DIR"] = runs_dir
    os.environ["HERMES_WORKSPACE_ROOT"] = project_root

    # Delegate to auto-debate (load by file path since the filename has a hyphen)
    import importlib.util
    mod_path = pkg_dir / "auto-debate.py"
    spec = importlib.util.spec_from_file_location("auto_debate", mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["auto_debate"] = mod
    spec.loader.exec_module(mod)
    sys.argv[0] = "debate"
    mod.main()


if __name__ == "__main__":
    main()
