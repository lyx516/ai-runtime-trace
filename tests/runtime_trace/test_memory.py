"""Memory store tests — read/write/delete round-trip and agent isolation."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "runtime_trace"))

from memory import MemoryStore


def _tmp_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(db_path=tmp_path / "test_memory.sqlite")


def test_write_and_read():
    import pytest
    with tempfile.TemporaryDirectory() as td:
        store = _tmp_store(Path(td))
        store.write("agent-a", "pref", "pytest")
        assert store.read("agent-a", "pref") == "pytest"


def test_read_nonexistent():
    with tempfile.TemporaryDirectory() as td:
        store = _tmp_store(Path(td))
        assert store.read("agent-a", "missing") is None


def test_overwrite():
    with tempfile.TemporaryDirectory() as td:
        store = _tmp_store(Path(td))
        store.write("agent-a", "k", "v1")
        store.write("agent-a", "k", "v2")
        assert store.read("agent-a", "k") == "v2"


def test_agent_isolation():
    with tempfile.TemporaryDirectory() as td:
        store = _tmp_store(Path(td))
        store.write("agent-a", "shared-key", "from-a")
        store.write("agent-b", "shared-key", "from-b")
        assert store.read("agent-a", "shared-key") == "from-a"
        assert store.read("agent-b", "shared-key") == "from-b"


def test_list_keys():
    with tempfile.TemporaryDirectory() as td:
        store = _tmp_store(Path(td))
        store.write("agent-a", "k1", "v1")
        store.write("agent-a", "k2", "v2")
        keys = store.list_keys("agent-a")
        assert len(keys) == 2
        assert {k["key"] for k in keys} == {"k1", "k2"}


def test_delete():
    with tempfile.TemporaryDirectory() as td:
        store = _tmp_store(Path(td))
        store.write("agent-a", "k", "v")
        assert store.delete("agent-a", "k") is True
        assert store.read("agent-a", "k") is None
        assert store.delete("agent-a", "k") is False


def test_persistence_across_instances():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "persist.sqlite"
        s1 = MemoryStore(db_path=db)
        s1.write("agent-a", "persisted", "yes")
        s2 = MemoryStore(db_path=db)
        assert s2.read("agent-a", "persisted") == "yes"