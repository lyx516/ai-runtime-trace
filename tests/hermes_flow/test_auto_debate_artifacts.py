import importlib.util
from pathlib import Path


def _load_auto_debate():
    path = Path(__file__).resolve().parents[2] / "experiments" / "agent-pool" / "auto-debate.py"
    spec = importlib.util.spec_from_file_location("auto_debate_for_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_output_artifact_ignores_stale_other_flow(tmp_path):
    mod = _load_auto_debate()
    current = tmp_path / "output" / "auto-current"
    stale = tmp_path / "output" / "auto-stale"
    current.mkdir(parents=True)
    stale.mkdir(parents=True)
    (stale / "spec.md").write_text("# stale\n\n" + "old\n" * 100, encoding="utf-8")

    artifact, reason = mod._find_output_artifact(str(tmp_path), "spec.md", ["output/auto-current/"])

    assert artifact is None
    assert reason == "missing in current write scope"


def test_find_output_artifact_rejects_one_line_stub(tmp_path):
    mod = _load_auto_debate()
    current = tmp_path / "output" / "auto-current"
    current.mkdir(parents=True)
    (current / "tasks.md").write_text("# Tasks for Vector Database System", encoding="utf-8")

    artifact, reason = mod._find_output_artifact(str(tmp_path), "tasks.md", ["output/auto-current/"])

    assert artifact is None
    assert "stub-like" in reason


def test_find_output_artifact_accepts_current_substantive_file(tmp_path):
    mod = _load_auto_debate()
    current = tmp_path / "output" / "auto-current"
    current.mkdir(parents=True)
    (current / "plan.md").write_text("# Plan\n\n" + "detail\n" * 80, encoding="utf-8")

    artifact, reason = mod._find_output_artifact(str(tmp_path), "plan.md", ["output/auto-current/"])

    assert artifact == current / "plan.md"
    assert reason == "ok"
