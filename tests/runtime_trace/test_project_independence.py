"""Repository-level guard for the standalone Runtime Trace distribution."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_MARKER = bytes.fromhex("6865726d6573").decode("ascii")


def test_tracked_project_files_contain_no_legacy_brand_or_host_dependency():
    tracked_paths = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    offenders: list[str] = []
    for relative_path in tracked_paths:
        path = PROJECT_ROOT / relative_path
        if LEGACY_MARKER.casefold() in relative_path.casefold():
            offenders.append(relative_path)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if LEGACY_MARKER.casefold() in content.casefold():
            offenders.append(relative_path)

    assert not offenders, f"legacy references remain: {offenders}"
