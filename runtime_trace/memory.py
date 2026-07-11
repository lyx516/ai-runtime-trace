"""Global agent memory store — persists across runs.

SQLite at PROJECT_ROOT/.runtime-trace/memory.sqlite
Table: agent_memory(agent_id TEXT, key TEXT, value TEXT, updated_at TEXT, source_run_id TEXT)
Primary key: (agent_id, key)
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is not None:
        return _DB_PATH
    # Resolve from env or fall back to script_dir/.runtime-trace/memory.sqlite
    root = Path(__file__).resolve().parent.parent  # ai-runtime-trace/
    _DB_PATH = root / ".runtime-trace" / "memory.sqlite"
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


class MemoryStore:
    """Global key-value memory store, scoped per agent_id."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_memory (
                    agent_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_run_id TEXT,
                    PRIMARY KEY (agent_id, key)
                )
            """)
            conn.commit()

    def read(self, agent_id: str, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM agent_memory WHERE agent_id=? AND key=?",
                (agent_id, key),
            ).fetchone()
            return row["value"] if row else None

    def write(self, agent_id: str, key: str, value: str, source_run_id: str = "") -> None:
        if not key or not key.strip():
            raise ValueError("memory key must not be empty")
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            # Evict oldest entry if at cap and key is new
            existing = conn.execute(
                "SELECT 1 FROM agent_memory WHERE agent_id=? AND key=?", (agent_id, key)
            ).fetchone()
            if not existing:
                count = conn.execute(
                    "SELECT COUNT(*) as c FROM agent_memory WHERE agent_id=?", (agent_id,)
                ).fetchone()["c"]
                if count >= 50:
                    conn.execute(
                        """DELETE FROM agent_memory WHERE agent_id=?
                           AND key=(SELECT key FROM agent_memory WHERE agent_id=?
                                    ORDER BY updated_at ASC LIMIT 1)""",
                        (agent_id, agent_id),
                    )
            conn.execute(
                """INSERT INTO agent_memory (agent_id, key, value, updated_at, source_run_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, key) DO UPDATE SET
                       value=excluded.value,
                       updated_at=excluded.updated_at,
                       source_run_id=excluded.source_run_id""",
                (agent_id, key, value, now, source_run_id),
            )
            conn.commit()

    def list_keys(self, agent_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at, source_run_id FROM agent_memory WHERE agent_id=? ORDER BY key",
                (agent_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete(self, agent_id: str, key: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM agent_memory WHERE agent_id=? AND key=?",
                (agent_id, key),
            )
            conn.commit()
            return cur.rowcount > 0