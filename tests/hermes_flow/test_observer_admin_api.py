from pathlib import Path
import sqlite3

from hermes_flow.observer import SSEHandler


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_run(root: Path, run_id: str, created_at: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(run_dir / "state.sqlite")
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, display_name TEXT, created_at TEXT)")
    conn.execute("INSERT INTO runs VALUES (?, ?, ?)", (run_id, f"Run {run_id}", created_at))
    conn.commit()
    conn.close()


def test_observer_lists_runs_from_all_scanned_dirs(tmp_path, monkeypatch):
    """Observer now scans fixed, env-override, and legacy (.hermes-flow/runs) dirs."""
    fixed_runs = tmp_path / "fixed-runs"
    legacy_runs = tmp_path / "project" / ".hermes-flow" / "runs"
    # Simulate an env-override dir (like agent-pool's HERMES_FLOW_RUNS_DIR)
    pool_runs = tmp_path / "agent-pool" / ".hermes-flow" / "runs"
    _write_run(fixed_runs, "fixed-run", "2026-07-04T10:00:00+00:00")
    _write_run(legacy_runs, "legacy-run", "2026-07-04T09:00:00+00:00")
    _write_run(pool_runs, "pool-run", "2026-07-04T11:00:00+00:00")
    monkeypatch.setenv("HERMES_FLOW_RUNS_DIR", str(pool_runs))

    old_root = SSEHandler.project_root
    old_dir = SSEHandler.runs_dir
    SSEHandler.project_root = tmp_path / "project"
    SSEHandler.runs_dir = fixed_runs
    try:
        handler = object.__new__(SSEHandler)
        runs = handler._list_runs()
        fixed_store = handler._read_store("fixed-run")
        legacy_store = handler._read_store("legacy-run")
        pool_store = handler._read_store("pool-run")
    finally:
        SSEHandler.project_root = old_root
        SSEHandler.runs_dir = old_dir

    ids = [r["run_id"] for r in runs]
    assert "fixed-run" in ids
    assert "legacy-run" in ids
    assert "pool-run" in ids
    assert fixed_store is not None
    assert legacy_store is not None
    assert pool_store is not None


def test_admin_agents_scan_and_merge_inheritance(tmp_path):
    pool = tmp_path / "agent-pool"
    _write(
        pool / "agents" / "developer" / "meta.yaml",
        "agent_id: developer\ndisplay_name: Developer\ntools_allowed:\n- file_read\nassigned_skills:\n- base\n",
    )
    _write(pool / "agents" / "developer" / "SOUL.md", "parent soul")
    _write(
        pool / "agents" / "developer" / "python" / "meta.yaml",
        "agent_id: python-developer\ndisplay_name: Python\ntools_allowed:\n- patch\nassigned_skills:\n- py\n",
    )
    _write(pool / "agents" / "developer" / "python" / "SOUL.md", "child soul")
    _write(pool / "shared" / "skills" / "base" / "SKILL.md", "---\nname: Base\ndescription: shared skill\n---\n")
    _write(pool / "agents" / "manager" / "skills" / "team.md", "---\nname: Team\ndescription: manager skill\n---\n")
    _write(pool / "tools" / "patch" / "meta.yaml", "tool_id: patch\nname: Patch\ndescription: edit files\n")

    old_dir = SSEHandler.agent_pool_dir
    SSEHandler.agent_pool_dir = pool
    try:
        handler = object.__new__(SSEHandler)
        listed = handler._list_admin_agents()["agents"]
        child = handler._get_admin_agent("python-developer")
        skills = handler._list_admin_skills()["skills"]
        tools = handler._list_admin_tools()["tools"]
    finally:
        SSEHandler.agent_pool_dir = old_dir

    assert [a["id"] for a in listed] == ["developer", "python-developer"]
    assert child["parent"] == "developer"
    assert child["soul"] == "parent soul\n\nchild soul"
    assert child["skills"] == ["base", "py"]
    assert child["tools"] == ["file_read", "patch"]
    assert {s["id"] for s in skills} == {"base", "team"}
    assert tools[0]["id"] == "patch"


def test_save_admin_agent_writes_local_files_and_meta(tmp_path):
    pool = tmp_path / "agent-pool"
    _write(pool / "agents" / "reviewer" / "meta.yaml", "agent_id: reviewer\ndisplay_name: Old\n")
    _write(pool / "agents" / "reviewer" / "SOUL.md", "old soul")

    old_dir = SSEHandler.agent_pool_dir
    SSEHandler.agent_pool_dir = pool
    try:
        handler = object.__new__(SSEHandler)
        result = handler._save_admin_agent("reviewer", {
            "display_name": "Reviewer",
            "role": "reviewer",
            "description": "Checks work",
            "local_soul": "new soul",
            "memory": "memory text",
            "local_skills": ["code-review"],
            "local_tools": ["file_read", "patch"],
        })
    finally:
        SSEHandler.agent_pool_dir = old_dir

    assert result["ok"] is True
    assert (pool / "agents" / "reviewer" / "SOUL.md").read_text(encoding="utf-8") == "new soul"
    assert (pool / "agents" / "reviewer" / "Memory.md").read_text(encoding="utf-8") == "memory text"
    meta = (pool / "agents" / "reviewer" / "meta.yaml").read_text(encoding="utf-8")
    assert "display_name: Reviewer" in meta
    assert "assigned_skills:" in meta
    assert "tools_allowed:" in meta
