"""Evolution framework smoke tests — backup/revert cycle, whitelist validation."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hermes_flow"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "agent-pool"))

from hermes_flow.storage import RuntimeStore


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def tmp_store():
    with tempfile.TemporaryDirectory() as td:
        store = RuntimeStore(Path(td))
        store.init_schema()
        yield store


def _make_temp_file(content: str) -> Path:
    """Create a temp file with given content, return its Path."""
    fd, path = tempfile.mkstemp(text=True)
    with open(fd, "w") as f:
        f.write(content)
    return Path(path)


# ── backup + revert cycle ──────────────────────────────────────────────


def test_evolution_backup_roundtrip(tmp_store):
    """Backup → verify stored → revert → verify file restored."""
    original = "line 1\nline 2\nline 3\n"
    fp = _make_temp_file(original)
    fp.write_text(original)

    backup_id = tmp_store.save_evolution_backup(
        "test-run-1", str(fp), original, "test patch"
    )
    assert backup_id > 0

    bk = tmp_store.get_evolution_backup(backup_id)
    assert bk is not None
    assert bk["run_id"] == "test-run-1"
    assert bk["file_path"] == str(fp)
    assert bk["original_content"] == original
    assert bk["patch_summary"] == "test patch"
    assert bk["reverted"] == 0

    # Mutate file
    fp.write_text("corrupted")
    assert fp.read_text() == "corrupted"

    # Revert
    ok = tmp_store.revert_evolution_backup(backup_id)
    assert ok
    assert fp.read_text() == original

    # Verify marked reverted
    bk2 = tmp_store.get_evolution_backup(backup_id)
    assert bk2["reverted"] == 1


def test_evolution_backup_list_filter(tmp_store):
    """list_evolution_backups filters by reverted flag."""
    fp = _make_temp_file("x")
    fp.write_text("x")
    tmp_store.save_evolution_backup("r1", str(fp), "x", "p1")
    bid2 = tmp_store.save_evolution_backup("r2", str(fp), "x", "p2")

    active = tmp_store.list_evolution_backups(reverted=0)
    assert len(active) == 2

    tmp_store.revert_evolution_backup(bid2)
    active2 = tmp_store.list_evolution_backups(reverted=0)
    assert len(active2) == 1


def test_revert_evolution_backup_not_found(tmp_store):
    """Reverting a non-existent backup returns False."""
    assert tmp_store.revert_evolution_backup(99999) is False


# ── Whitelist validation (no disk writes) ──────────────────────────────


def test_framework_whitelist_contains_session_py():
    """Whitelist includes the session.py prompt template."""
    from engine.evolve import _FRAMEWORK_WHITELIST
    assert "experiments/agent-pool/engine/session.py" in _FRAMEWORK_WHITELIST


def test_framework_whitelist_contains_team_skills():
    """Whitelist includes spec-team and spec-clarify-team YAML templates."""
    from engine.evolve import _FRAMEWORK_WHITELIST
    assert "experiments/agent-pool/agents/manager/skills/spec-team.md" in _FRAMEWORK_WHITELIST
    assert "experiments/agent-pool/agents/manager/skills/spec-clarify-team.md" in _FRAMEWORK_WHITELIST
