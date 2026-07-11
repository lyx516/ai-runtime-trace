"""Observer — real-time observability for Hermes Flow runs.

Exposes a lightweight HTTP server with:
- SSE (Server-Sent Events) stream for live updates
- REST API for current state, decisions, messages, trace
- Built-in HTML dashboard at /

Usage:
    from hermes_flow.observer import FlowObserver
    observer = FlowObserver(port=8080)
    observer.start()  # background thread

    # Or standalone:
    python -m hermes_flow.observer --port 8080 --project-root /path/to/project
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import queue
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_flow.run_paths import get_runs_dir

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_runs_dir(project_root: str | None = None) -> Path:
    """Return the canonical .hermes-flow/runs directory."""
    return get_runs_dir(project_root)


def _get_store(run_id: str, runs_dir: Path):
    """Get a RuntimeStore for a run by scanning runs_dir."""
    from hermes_flow.storage import RuntimeStore

    run_dir = runs_dir / run_id
    if run_dir.exists():
        store = RuntimeStore(run_dir)
        store.init_schema()
        return store
    # Scan subdirectories
    for d in runs_dir.iterdir():
        if d.is_dir() and d.name.startswith(run_id):
            store = RuntimeStore(d)
            store.init_schema()
            return store
    return None


# ── Event bus for SSE push ──────────────────────────────────────────────

class EventBus:
    """Simple pub/sub for runtime events."""

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not q]

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        msg = json.dumps({"type": event_type, "data": data, "ts": _now()}, default=str)
        with self._lock:
            dead: list[queue.Queue] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)


# Global event bus
_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


# ── SSE handler ─────────────────────────────────────────────────────────

class SSEHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that serves SSE and REST APIs."""

    # Shared across instances
    runs_dir = _find_runs_dir()
    project_root: Path | None = None
    agent_pool_dir: Path | None = None
    event_bus = _bus

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, data: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def _read_store(self, run_id: str):
        if not run_id:
            return None
        for runs_dir in self._iter_runs_dirs():
            try:
                store = _get_store(run_id, runs_dir)
                if store:
                    return store
            except Exception:
                continue
        return None

    def _iter_runs_dirs(self) -> list[Path]:
        """Return all run directories — evn override, primary, and fallback."""
        dirs = []
        # 1. Env override (HERMES_FLOW_RUNS_DIR)
        _env_runs = os.environ.get("HERMES_FLOW_RUNS_DIR")
        if _env_runs:
            _p = Path(_env_runs).expanduser().resolve()
            if _p.exists():
                dirs.append(_p)
        # 2. Primary: default  (hermes_flow/.hermes-flow/runs)
        if self.runs_dir.exists():
            dirs.append(self.runs_dir)
        # 3. Fallback: git root .hermes-flow/runs
        if self.project_root:
            _legacy = Path(self.project_root) / ".hermes-flow" / "runs"
            if _legacy.exists() and _legacy not in dirs:
                dirs.append(_legacy)
        return dirs

    def _list_runs(self) -> list[dict]:
        runs = []
        by_id: dict[str, dict] = {}
        for runs_dir in self._iter_runs_dirs():
            for d in sorted(runs_dir.iterdir(), reverse=True):
                if d.is_dir():
                    db = d / "state.sqlite"
                    if db.exists():
                        display_name = d.name
                        created_at = ""
                        updated_at = ""
                        try:
                            from datetime import datetime, timezone

                            updated_at = datetime.fromtimestamp(
                                db.stat().st_mtime,
                                tz=timezone.utc,
                            ).isoformat()
                        except Exception:
                            pass
                        try:
                            import sqlite3
                            c = sqlite3.connect(str(db))
                            row = c.execute(
                                "SELECT display_name, created_at FROM runs WHERE run_id=?",
                                (d.name,),
                            ).fetchone()
                            if row and row[0]:
                                display_name = row[0]
                            if row and len(row) > 1 and row[1]:
                                created_at = row[1]
                            c.close()
                        except Exception:
                            pass
                        item = {
                            "run_id": d.name,
                            "display_name": display_name,
                            "created_at": created_at,
                            "updated_at": updated_at,
                            "path": str(d),
                            "db_size": db.stat().st_size if db.exists() else 0,
                        }
                        current = by_id.get(d.name)
                        if not current or (item.get("updated_at") or "") > (current.get("updated_at") or ""):
                            by_id[d.name] = item
        runs = list(by_id.values())
        runs.sort(key=lambda r: r.get("created_at") or r.get("updated_at") or "", reverse=True)
        return runs

    def _get_run_status(self, run_id: str) -> dict | None:
        store = self._read_store(run_id)
        if not store:
            return None
        try:
            from hermes_flow.schemas import RunStatus
            status = store.load_status(run_id)
            return {
                "run_id": status.run_id,
                "status": status.status.value if hasattr(status.status, "value") else str(status.status),
                "current_state_id": status.current_state_id,
                "pending_gate": None,
                "round_counters": status.round_counters,
                "next_actions": status.next_actions,
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_audit(self, run_id: str) -> list[dict]:
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE run_id=? ORDER BY row_id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_decisions(self, run_id: str) -> list[dict]:
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            rows = conn.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_messages(self, run_id: str) -> list[dict]:
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            rows = conn.execute(
                "SELECT * FROM messages WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_transitions(self, run_id: str) -> list[dict]:
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            rows = conn.execute(
                "SELECT * FROM transitions WHERE run_id=? ORDER BY row_id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_trace_events(self, run_id: str) -> list[dict]:
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            rows = conn.execute(
                "SELECT * FROM trace_events WHERE run_id=? ORDER BY ts_start",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _get_inboxes(self, run_id: str) -> list[dict]:
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            rows = conn.execute(
                "SELECT * FROM inboxes WHERE run_id=? ORDER BY row_id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Request routing ────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = urllib.parse.parse_qs(parsed.query)

        # Dashboard - serve static files from dashboard/ directory
        if path == "" or path == "/":
            return self._serve_dashboard_file("index.html")

        # Static file (non-API) - serve from dashboard/
        if not path.startswith("/api/"):
            filename = path.lstrip("/")
            return self._serve_dashboard_file(filename)
        if path == "/api/events":
            run_id = qs.get("run_id", [""])[0]
            return self._handle_sse(run_id)

        # REST API
        if path == "/api/runs":
            return self._send_json(self._list_runs())

        if path == "/api/pool":
            return self._serve_pool_api()

        if path == "/api/admin/agents":
            return self._send_json(self._list_admin_agents())

        if path.startswith("/api/admin/agents/"):
            agent_id = urllib.parse.unquote(path.removeprefix("/api/admin/agents/"))
            data = self._get_admin_agent(agent_id)
            status = 404 if data.get("error") else 200
            return self._send_json(data, status)

        if path == "/api/admin/skills":
            return self._send_json(self._list_admin_skills())

        if path == "/api/admin/tools":
            return self._send_json(self._list_admin_tools())

        if path.startswith("/api/runs/"):
            parts = path.split("/")
            if len(parts) >= 4:
                run_id = parts[3]
                resource = parts[4] if len(parts) > 4 else "status"

                data = None
                if resource == "status":
                    data = self._get_run_status(run_id)
                elif resource == "audit":
                    data = self._get_audit(run_id)
                elif resource == "decisions":
                    data = self._get_decisions(run_id)
                elif resource == "messages":
                    data = self._get_messages(run_id)
                elif resource == "transitions":
                    data = self._get_transitions(run_id)
                elif resource == "trace":
                    data = self._get_trace_events(run_id)
                elif resource == "inboxes":
                    data = self._get_inboxes(run_id)
                elif resource == "graph":
                    data = self._get_graph(run_id)
                elif resource == "all":
                    data = {
                        "status": self._get_run_status(run_id),
                        "decisions": self._get_decisions(run_id),
                        "messages": self._get_messages(run_id),
                        "transitions": self._get_transitions(run_id),
                        "audit": self._get_audit(run_id),
                        "trace": self._get_trace_events(run_id),
                    }
                elif resource == "analyze":
                    data = self._get_analyze(run_id)
                elif resource == "agent-sessions":
                    data = self._get_agent_sessions(run_id)
                elif resource == "agent-context":
                    role_id = qs.get("role_id", [""])[0]
                    state_id = qs.get("state_id", [""])[0]
                    at = qs.get("at", [""])[0]
                    data = self._get_agent_context(run_id, role_id, state_id, at)
                elif resource == "thinking":
                    role_id = qs.get("role_id", [None])[0]
                    state_id = qs.get("state_id", [None])[0]
                    data = self._get_thinking(run_id, role_id, state_id)
                elif resource == "performance":
                    data = self._get_performance(run_id)

                if data is not None:
                    return self._send_json(data)
                return self._send_json({"error": "unknown resource"}, 404)

        return self._send_json({"error": "not found"}, 404)

    def _handle_sse(self, run_id: str):
        """SSE connection: push live events as they happen."""
        q = self.event_bus.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            # Send initial state
            if run_id:
                status = self._get_run_status(run_id)
                if status:
                    init = json.dumps({"type": "init", "data": status, "ts": _now()}, default=str)
                    self.wfile.write(f"data: {init}\n\n".encode())
                    self.wfile.flush()

            while True:
                try:
                    msg = q.get(timeout=30)
                    # Filter by run_id: SSE clients only see events for their run
                    if run_id:
                        try:
                            parsed = json.loads(msg)
                            evt_rid = parsed.get("run_id", "")
                            if not evt_rid and isinstance(parsed.get("data"), dict):
                                evt_rid = parsed["data"].get("run_id", "")
                            if evt_rid and evt_rid != run_id:
                                continue
                        except (json.JSONDecodeError, TypeError):
                            pass
                    self.wfile.write(f"data: {msg}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    # Keep-alive
                    self.wfile.write(":keepalive\n\n".encode())
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.event_bus.unsubscribe(q)

    def do_POST(self):
        """Handle POST requests (resume)."""
        parsed = urllib.parse.urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode() if content_len else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/api/resume":
            run_id = payload.get("run_id", "")
            state = payload.get("continuation_state", "")
            if not run_id:
                return self._send_json({"ok": False, "error": "run_id required"}, 400)
            try:
                from hermes_flow.tools import flow_resume
                result = flow_resume(run_id, continuation_state=state)
                _bus.publish("run_resumed", {"run_id": run_id, "to_state": state, "result": result})
                return self._send_json(result)
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)

        return self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        """Handle CORS preflight for admin writes."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_PUT(self):
        """Handle admin writes."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode() if content_len else "{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return self._send_json({"ok": False, "error": "invalid json"}, 400)

        if path.startswith("/api/admin/agents/"):
            agent_id = urllib.parse.unquote(path.removeprefix("/api/admin/agents/"))
            result = self._save_admin_agent(agent_id, payload)
            status = 400 if result.get("error") else 200
            return self._send_json(result, status)

        return self._send_json({"error": "not found"}, 404)

    def _get_graph(self, run_id: str) -> dict | None:
        """Build a structured DAG of states, transitions, decisions, and messages."""
        store = self._read_store(run_id)
        if not store:
            return None
        try:
            conn = store.connect()
            transitions = conn.execute(
                "SELECT * FROM transitions WHERE run_id=? ORDER BY row_id", (run_id,)
            ).fetchall()
            decisions = conn.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
            messages = conn.execute(
                "SELECT * FROM messages WHERE run_id=? ORDER BY created_at", (run_id,)
            ).fetchall()
            states_rows = conn.execute(
                "SELECT state_id, state_json FROM states WHERE run_id=?", (run_id,)
            ).fetchall()

            # Build state registry
            state_registry = {}
            for s in states_rows:
                sd = json.loads(s["state_json"])
                state_registry[s["state_id"]] = sd

            # Build graph nodes
            nodes = {}
            for s in states_rows:
                sid = s["state_id"]
                sd = state_registry.get(sid, {})
                nodes[sid] = {
                    "state_id": sid,
                    "terminal": sd.get("terminal", False),
                    "human": sd.get("human", False),
                    "actors": sd.get("actors", []),
                    "gate": sd.get("gate"),
                    "decisions": [],
                    "in_messages": [],
                    "out_messages": [],
                    "visit_count": 0,
                }

            # Attach decisions to states
            for d in decisions:
                dd = dict(d)
                sid = dd["state_id"]
                if sid in nodes:
                    nodes[sid]["decisions"].append({
                        "role_id": dd["role_id"],
                        "value": dd["value"],
                        "reason": dd.get("reason", ""),
                        "created_at": dd.get("created_at", ""),
                    })

            # Attach messages to states
            for m in messages:
                md = dict(m)
                sid = md["state_id"]
                if sid in nodes:
                    entry = {
                        "from_role": md["from_role"],
                        "intended_recipients": md.get("intended_recipients", []),
                        "kind": md.get("kind", ""),
                        "content": md.get("content", ""),
                        "delivery_outcome": md.get("delivery_outcome", ""),
                    }
                    nodes[sid]["out_messages"].append(entry)

            # Count visits and build edges
            edges = []
            for t in transitions:
                td = dict(t)
                edges.append({
                    "from": td["from_state_id"],
                    "to": td["to_state_id"],
                    "gate_result": td.get("gate_result", ""),
                    "round": td.get("round_counter", td.get("round", 0)),
                    "created_at": td.get("created_at", ""),
                })
                if td["to_state_id"] in nodes:
                    nodes[td["to_state_id"]]["visit_count"] += 1

            # Determine current state from status
            status_result = self._get_run_status(run_id)
            current_state = None
            run_status = None
            if status_result and "current_state_id" in status_result:
                current_state = status_result["current_state_id"]
                run_status = status_result.get("status")

            return {
                "run_id": run_id,
                "status": run_status,
                "current_state_id": current_state,
                "states": list(nodes.values()),
                "transitions": edges,
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_analyze(self, run_id: str) -> dict | None:
        """Return TraceQueryEngine analysis for a run."""
        store = self._read_store(run_id)
        if not store:
            return None
        try:
            from hermes_flow.trace_query import TraceQueryEngine
            engine = TraceQueryEngine(store)
            return engine.trace_analyze(run_id)
        except Exception as e:
            return {"error": str(e)}

    def _get_agent_sessions(self, run_id: str) -> list[dict]:
        """Return per-session aggregated decision data."""
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            conn = store.connect()
            decisions = conn.execute(
                "SELECT * FROM decisions WHERE run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()

            # Group decisions by role_id as a proxy for session
            sessions: dict[str, dict] = {}
            for d in decisions:
                dd = dict(d)
                role = dd["role_id"]
                if role not in sessions:
                    sessions[role] = {
                        "role_id": role,
                        "decisions": [],
                        "thinking_events": [],
                    }
                sessions[role]["decisions"].append({
                    "state_id": dd["state_id"],
                    "value": dd["value"],
                    "reason": dd.get("reason", ""),
                    "created_at": dd.get("created_at", ""),
                })

            return list(sessions.values())
        except Exception as e:
            return [{"error": str(e)}]

    def _get_thinking(
        self,
        run_id: str,
        role_id: str | None = None,
        state_id: str | None = None,
    ) -> list[dict]:
        """Get thinking events for a run."""
        store = self._read_store(run_id)
        if not store:
            return []
        return store.load_thinking_events(run_id, role_id, state_id)

    def _get_performance(self, run_id: str) -> dict | None:
        """Get performance evaluation for a run."""
        store = self._read_store(run_id)
        if not store:
            return None
        return store.load_run_performance(run_id)

    def _decode_json_value(self, value: Any, default: Any) -> Any:
        """Decode JSON stored in SQLite TEXT columns."""
        if value is None or value == "":
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def _decode_row_json_fields(self, row: dict, fields: list[str]) -> dict:
        decoded = dict(row)
        for field in fields:
            if field in decoded:
                fallback: Any = [] if field.endswith("recipients") or field == "artifacts" else {}
                decoded[field] = self._decode_json_value(decoded.get(field), fallback)
        return decoded

    def _message_visible_to_role(self, message: dict, role_id: str) -> bool:
        if not role_id:
            return False
        if message.get("from_role") == role_id:
            return True
        if message.get("visibility") in {"all", "group"}:
            return True
        intended = self._decode_json_value(message.get("intended_recipients"), [])
        authorized = self._decode_json_value(message.get("authorized_recipients"), [])
        return role_id in intended or role_id in authorized

    def _rows_before(self, sql: str, params: tuple, at: str) -> tuple[str, tuple]:
        if at:
            return sql + " AND created_at <= ?", (*params, at)
        return sql, params

    def _load_session_contexts(
        self,
        store: Any,
        role_id: str,
        state_id: str,
        at: str,
    ) -> list[dict]:
        """Load persisted AgentContextPacket files for one role/state."""
        sessions_dir = Path(store.run_dir) / "sessions"
        if not sessions_dir.exists():
            return []
        contexts = []
        for path in sorted(sessions_dir.glob("*.context.json")):
            try:
                packet = json.loads(path.read_text())
            except Exception:
                continue
            if role_id and packet.get("role_id") != role_id:
                continue
            if state_id and packet.get("state_id") != state_id:
                continue
            created_at = packet.get("created_at", "")
            if at and created_at and created_at > at:
                continue
            contexts.append({
                "session_id": packet.get("session_id", path.stem.replace(".context", "")),
                "role_id": packet.get("role_id", ""),
                "state_id": packet.get("state_id", ""),
                "created_at": created_at,
                "context_file": path.name,
                "context": packet,
            })
        contexts.sort(key=lambda c: c.get("created_at") or "")
        return contexts

    def _get_agent_context(
        self,
        run_id: str,
        role_id: str,
        state_id: str = "",
        at: str = "",
    ) -> dict:
        """Return full context visible to an agent around a selected timeline point."""
        if not role_id:
            return {"error": "role_id required"}
        store = self._read_store(run_id)
        if not store:
            return {"error": "run not found"}

        try:
            conn = store.connect()
            if not state_id:
                status = self._get_run_status(run_id) or {}
                state_id = status.get("current_state_id", "")

            state_row = conn.execute(
                "SELECT state_json FROM states WHERE run_id=? AND state_id=?",
                (run_id, state_id),
            ).fetchone()
            state_definition = self._decode_json_value(
                state_row["state_json"] if state_row else "{}", {}
            )

            inbox_rows = conn.execute(
                """SELECT i.row_id AS inbox_row_id, i.role_id, i.generated_at,
                          m.*
                   FROM inboxes i
                   JOIN messages m ON i.message_id = m.message_id
                   WHERE i.run_id=? AND i.role_id=?
                   ORDER BY m.created_at""",
                (run_id, role_id),
            ).fetchall()
            json_fields = [
                "intended_recipients", "authorized_recipients",
                "recipient_availability", "artifacts",
            ]
            inbox_messages = [self._decode_row_json_fields(dict(r), json_fields) for r in inbox_rows]

            msg_sql, msg_params = self._rows_before(
                "SELECT * FROM messages WHERE run_id=?", (run_id,), at,
            )
            message_rows = conn.execute(msg_sql + " ORDER BY created_at", msg_params).fetchall()
            visible_messages = []
            for row in message_rows:
                message = self._decode_row_json_fields(dict(row), json_fields)
                if self._message_visible_to_role(message, role_id):
                    visible_messages.append(message)

            dec_sql, dec_params = self._rows_before(
                "SELECT * FROM decisions WHERE run_id=?", (run_id,), at,
            )
            decision_rows = conn.execute(dec_sql + " ORDER BY created_at", dec_params).fetchall()
            decisions_seen = [
                self._decode_row_json_fields(dict(r), ["artifacts"])
                for r in decision_rows
                if not state_id or r["state_id"] == state_id
            ]

            thinking = store.load_thinking_events(
                run_id,
                role_id=role_id,
                state_id=state_id or None,
                limit=500,
            )
            if at:
                thinking = [t for t in thinking if not t.get("created_at") or t["created_at"] <= at]

            trans_sql, trans_params = self._rows_before(
                "SELECT * FROM transitions WHERE run_id=? AND to_state_id=?",
                (run_id, state_id),
                at,
            )
            transition_rows = conn.execute(trans_sql + " ORDER BY row_id", trans_params).fetchall()
            transitions = [dict(r) for r in transition_rows]
            round_counter = max((t.get("round_counter") or 0 for t in transitions), default=0)

            audit_sql, audit_params = self._rows_before(
                "SELECT * FROM audit_events WHERE run_id=? AND actor=?",
                (run_id, role_id),
                at,
            )
            audit_rows = conn.execute(audit_sql + " ORDER BY created_at", audit_params).fetchall()
            audit_events = []
            for row in audit_rows:
                event = dict(row)
                event["payload"] = self._decode_json_value(event.get("payload_json"), {})
                event.pop("payload_json", None)
                audit_events.append(event)

            session_contexts = self._load_session_contexts(store, role_id, state_id, at)
            latest_context = session_contexts[-1]["context"] if session_contexts else None
            llm_snapshots = store.load_llm_input_snapshots(
                run_id,
                role_id=role_id,
                state_id=state_id or None,
                at=at,
                limit=100,
            )
            llm_input = llm_snapshots[-1] if llm_snapshots else {
                "source": "session_file_fallback" if latest_context else "reconstructed_fallback",
                "snapshot_id": None,
                "run_id": run_id,
                "session_id": (latest_context or {}).get("session_id", ""),
                "role_id": role_id,
                "state_id": state_id,
                "provider": "",
                "model": "",
                "messages": ([{"role": "user", "content": latest_context.get("agent_prompt", "")}] if latest_context and latest_context.get("agent_prompt") else []),
                "request": {},
                "context_packet": latest_context or {},
                "created_at": (latest_context or {}).get("created_at", ""),
            }
            reconstructed_context = {
                "run_id": run_id,
                "role_id": role_id,
                "state_id": state_id,
                "state_description": state_definition.get("description", ""),
                "gate_info": state_definition.get("gate"),
                "round_counter": round_counter,
                "inbox_messages": inbox_messages,
                "visible_messages": visible_messages,
                "pending_decisions": decisions_seen,
                "thinking_events": thinking,
                "available_tools": ["inbox_read", "message_send", "submit_decision", "query_status"],
            }

            return {
                "run_id": run_id,
                "role_id": role_id,
                "state_id": state_id,
                "selected_at": at,
                "round_counter": round_counter,
                "state_definition": state_definition,
                "inbox_messages": inbox_messages,
                "visible_messages": visible_messages,
                "decisions_seen": decisions_seen,
                "thinking_events": thinking,
                "audit_events": audit_events,
                "session_contexts": session_contexts,
                "context_packet": latest_context or reconstructed_context,
                "context_source": "session_file" if latest_context else "reconstructed",
                "llm_input": llm_input,
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_agent_pool_dir(self) -> Path | None:
        """Locate the agent-pool data directory used by admin APIs."""
        if self.agent_pool_dir and self.agent_pool_dir.exists():
            return self.agent_pool_dir
        candidates = [
            Path(__file__).resolve().parent.parent / "experiments" / "agent-pool",
            Path(__file__).resolve().parent.parent / "experiments" / "agent-pool-plugin",
            Path.home() / ".hermes" / "plugins" / "agent-pool",
        ]
        for candidate in candidates:
            if (candidate / "agents").exists():
                return candidate
        return None

    def _read_yaml_file(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_yaml_file(self, path: Path, data: dict) -> None:
        import yaml
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _parse_markdown_meta(self, path: Path) -> dict:
        """Read YAML front matter from skill markdown files."""
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        end = text.find("\n---", 3)
        if end < 0:
            return {}
        try:
            import yaml
            data = yaml.safe_load(text[3:end])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _agent_id_from_parts(self, parts: tuple[str, ...]) -> str:
        if len(parts) == 1:
            return parts[0]
        parent_id = self._agent_id_from_parts(parts[:-1])
        return f"{parts[-1]}-{parent_id}"

    def _scan_agent_dirs(self) -> dict[str, dict]:
        pool_dir = self._get_agent_pool_dir()
        if not pool_dir:
            return {}
        agents_dir = pool_dir / "agents"
        candidates: list[Path] = []
        for path in sorted(agents_dir.rglob("*")):
            if path.is_dir() and ((path / "meta.yaml").exists() or (path / "SOUL.md").exists()):
                candidates.append(path)
        by_parts = {tuple(path.relative_to(agents_dir).parts): path for path in candidates}
        scanned: dict[str, dict] = {}
        for parts, path in sorted(by_parts.items(), key=lambda item: (len(item[0]), item[0])):
            agent_id = self._agent_id_from_parts(parts)
            parent_parts = parts[:-1]
            parent_id = self._agent_id_from_parts(parent_parts) if parent_parts in by_parts else None
            scanned[agent_id] = {
                "id": agent_id,
                "path": path,
                "relative_path": "/".join(parts),
                "parent": parent_id,
            }
        return scanned

    def _read_agent_local(self, agent_id: str, scanned: dict[str, dict] | None = None) -> dict | None:
        scanned = scanned or self._scan_agent_dirs()
        entry = scanned.get(agent_id)
        if not entry:
            return None
        path = entry["path"]
        meta = self._read_yaml_file(path / "meta.yaml")
        soul_path = path / "SOUL.md"
        memory_path = path / "Memory.md"
        local_soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else str(meta.get("soul") or "")
        memory = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
        local_skills = meta.get("assigned_skills", meta.get("skills", [])) or []
        local_tools = meta.get("tools_allowed", meta.get("tools", [])) or []
        if not isinstance(local_skills, list):
            local_skills = [str(local_skills)]
        if not isinstance(local_tools, list):
            local_tools = [str(local_tools)]
        private_skills_dir = path / "skills"
        private_skills = sorted(p.stem for p in private_skills_dir.glob("*.md")) if private_skills_dir.exists() else []
        return {
            "id": agent_id,
            "agent_id": meta.get("agent_id", agent_id),
            "display_name": meta.get("display_name", agent_id),
            "role": meta.get("role", ""),
            "description": meta.get("description", ""),
            "parent": entry["parent"],
            "relative_path": entry["relative_path"],
            "meta": meta,
            "local_soul": local_soul,
            "memory": memory,
            "local_skills": [str(s) for s in local_skills],
            "private_skills": private_skills,
            "local_tools": [str(t) for t in local_tools],
        }

    def _merge_unique(self, *groups: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                if item not in seen:
                    seen.add(item)
                    merged.append(item)
        return merged

    def _get_admin_agent(self, agent_id: str) -> dict:
        scanned = self._scan_agent_dirs()
        local = self._read_agent_local(agent_id, scanned)
        if not local:
            return {"error": "agent not found"}
        chain: list[dict] = []
        parent_id = local.get("parent")
        while parent_id:
            parent = self._read_agent_local(parent_id, scanned)
            if not parent:
                break
            chain.insert(0, parent)
            parent_id = parent.get("parent")
        inherited_soul = "\n\n".join(a["local_soul"] for a in chain if a.get("local_soul"))
        soul = "\n\n".join(part for part in [inherited_soul, local["local_soul"]] if part)
        inherited_skills = self._merge_unique(*[a["local_skills"] for a in chain]) if chain else []
        inherited_tools = self._merge_unique(*[a["local_tools"] for a in chain]) if chain else []
        local["inherited_soul"] = inherited_soul
        local["soul"] = soul
        local["inherited_skills"] = inherited_skills
        local["skills"] = self._merge_unique(inherited_skills, local["local_skills"])
        local["inherited_tools"] = inherited_tools
        local["tools"] = self._merge_unique(inherited_tools, local["local_tools"])
        return local

    def _list_admin_agents(self) -> dict:
        scanned = self._scan_agent_dirs()
        agents = []
        for agent_id in sorted(scanned):
            detail = self._get_admin_agent(agent_id)
            if detail.get("error"):
                continue
            agents.append({
                "id": agent_id,
                "agent_id": detail.get("agent_id", agent_id),
                "display_name": detail.get("display_name", agent_id),
                "role": detail.get("role", ""),
                "description": detail.get("description", ""),
                "parent": detail.get("parent"),
                "relative_path": detail.get("relative_path", ""),
                "skills": detail.get("skills", []),
                "tools": detail.get("tools", []),
                "private_skills": detail.get("private_skills", []),
            })
        pool_dir = self._get_agent_pool_dir()
        return {"agents": agents, "root": str(pool_dir.resolve()) if pool_dir else ""}

    def _save_admin_agent(self, agent_id: str, payload: dict) -> dict:
        scanned = self._scan_agent_dirs()
        entry = scanned.get(agent_id)
        if not entry:
            return {"ok": False, "error": "agent not found"}
        path = entry["path"]
        meta_path = path / "meta.yaml"
        meta = self._read_yaml_file(meta_path)
        for key in ["display_name", "role", "description"]:
            if key in payload:
                meta[key] = payload.get(key) or ""
        local_soul = payload.get("local_soul", payload.get("soul"))
        if local_soul is not None:
            text = str(local_soul)
            (path / "SOUL.md").write_text(text, encoding="utf-8")
            if "soul" in meta:
                meta["soul"] = text
        if "memory" in payload:
            (path / "Memory.md").write_text(str(payload.get("memory") or ""), encoding="utf-8")
        if "local_skills" in payload or "assigned_skills" in payload:
            skills = payload.get("local_skills", payload.get("assigned_skills")) or []
            meta["assigned_skills"] = [str(s) for s in skills]
        if "local_tools" in payload or "tools_allowed" in payload:
            tools = payload.get("local_tools", payload.get("tools_allowed")) or []
            meta["tools_allowed"] = [str(t) for t in tools]
        meta.setdefault("agent_id", agent_id)
        self._write_yaml_file(meta_path, meta)
        return {"ok": True, "agent": self._get_admin_agent(agent_id)}

    def _list_admin_skills(self) -> dict:
        pool_dir = self._get_agent_pool_dir()
        if not pool_dir:
            return {"skills": [], "error": "Agent pool plugin not found"}
        roots = [("shared", pool_dir / "shared" / "skills"), ("manager", pool_dir / "agents" / "manager" / "skills")]
        skills = []
        for source, root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.md")):
                meta = self._parse_markdown_meta(path)
                skill_id = path.parent.name if path.name == "SKILL.md" else path.stem
                skills.append({
                    "id": skill_id,
                    "name": str(meta.get("name") or skill_id),
                    "description": str(meta.get("description") or ""),
                    "source": source,
                    "relative_path": str(path.relative_to(pool_dir)),
                })
        return {"skills": skills}

    def _list_admin_tools(self) -> dict:
        pool_dir = self._get_agent_pool_dir()
        if not pool_dir:
            return {"tools": [], "error": "Agent pool plugin not found"}
        tools_dir = pool_dir / "tools"
        tools = []
        if tools_dir.exists():
            for meta_path in sorted(tools_dir.glob("*/meta.yaml")):
                meta = self._read_yaml_file(meta_path)
                tool_id = str(meta.get("tool_id") or meta_path.parent.name)
                tools.append({
                    "id": tool_id,
                    "name": str(meta.get("name") or tool_id),
                    "description": str(meta.get("description") or ""),
                    "category": str(meta.get("category") or ""),
                    "risk": str(meta.get("risk") or ""),
                    "universal": bool(meta.get("universal", False)),
                    "relative_path": str(meta_path.relative_to(pool_dir)),
                })
        return {"tools": tools}

    def _serve_pool_api(self):
        """Serve agent pool data from the project's agents/ directory."""
        plugin_dir = self._get_agent_pool_dir()
        if not plugin_dir:
            return self._send_json({"error": "Agent pool plugin not found"}, 404)
        import yaml
        agents_list = []
        agents_dir = plugin_dir / "agents"
        for d in sorted(agents_dir.iterdir()):
            meta = d / "meta.yaml"
            if not meta.exists():
                continue
            with open(meta) as f:
                info = yaml.safe_load(f)
                private_dir = d / "private"
                info["private_skills"] = sorted(f.name for f in private_dir.iterdir() if f.suffix == ".md") if private_dir.exists() else []
                agents_list.append(info)
        return self._send_json({"agents": agents_list, "pool_id": "hermes-flow-agent-pool"})

    def _serve_dashboard_file(self, filename: str) -> None:
        """Serve a static file from the dashboard/ directory."""
        import os
        import mimetypes

        # Find dashboard/ directory by scanning relative to this file
        base = Path(__file__).resolve().parent.parent / "dashboard"
        if not base.exists():
            self._send_json({"error": "dashboard/ directory not found"}, 404)
            return

        # Security: prevent directory traversal
        safe_path = (base / filename).resolve()
        if not str(safe_path).startswith(str(base.resolve())):
            self._send_json({"error": "forbidden"}, 403)
            return

        if not safe_path.exists() or not safe_path.is_file():
            self._send_json({"error": f"file not found: {filename}"}, 404)
            return

        content = safe_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(safe_path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


# ── Server wrapper ─────────────────────────────────────────────────────

class FlowObserver:
    """Real-time observer for Hermes Flow runs.

    Starts a lightweight HTTP server with SSE stream and REST API.
    """

    def __init__(self, port: int = 8080, project_root: str | None = None):
        self.port = port
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None
        if project_root:
            SSEHandler.project_root = Path(project_root)
            SSEHandler.runs_dir = _find_runs_dir(project_root)

    def start(self) -> None:
        """Start the observer in a background thread."""
        if self._thread and self._thread.is_alive():
            return

        from http.server import ThreadingHTTPServer

        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), SSEHandler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("FlowObserver listening on http://localhost:%d", self.port)
        print(f"  🌐 FlowObserver: http://localhost:{self.port}")

    def stop(self) -> None:
        """Stop the observer."""
        if self._server:
            self._server.shutdown()
            self._server = None

    def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event to all SSE subscribers."""
        _bus.publish(event_type, data)


# ── Convenience: auto-start observer ───────────────────────────────────────

_observer_instance: FlowObserver | None = None


def ensure_observer(port: int = 8765, project_root: str | None = None) -> FlowObserver:
    """Ensure an observer is running on `port`. Starts one if not already.

    Idempotent — safe to call multiple times. Returns the singleton instance.
    Called by run_flow() so every debate run gets a live dashboard.
    """
    global _observer_instance

    if _observer_instance is not None and _observer_instance._thread and _observer_instance._thread.is_alive():
        return _observer_instance

    # Check if port is already in use (maybe from a previous --standalone launch)
    import socket as _socket
    _in_use = False
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
            _s.settimeout(0.5)
            _in_use = _s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        pass

    if _in_use:
        logger.info("Observer already running on port %d, not starting a new one", port)
        return FlowObserver(port=port, project_root=project_root)  # stub — not started

    _observer_instance = FlowObserver(port=port, project_root=project_root)
    # Honour HERMES_FLOW_RUNS_DIR if set (so observer finds runs alongside auto-debate.py)
    _runs_dir = os.environ.get("HERMES_FLOW_RUNS_DIR")
    if _runs_dir:
        SSEHandler.runs_dir = Path(_runs_dir)
    _observer_instance.start()
    return _observer_instance


# ── Legacy embedded dashboard (unused) ─────────────────────────────────
# Static files under dashboard/ are the supported dashboard source. Keep this
# string only as a historical fallback/reference so new changes do not fork UI.

LEGACY_DASHBOARD_HTML_UNUSED = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hermes Flow — State Flow</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', sans-serif; }
  .topbar { background: #161b22; border-bottom: 1px solid #30363d; padding: 12px 20px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .topbar h1 { font-size: 18px; color: #e6edf3; white-space: nowrap; }
  .topbar input { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 6px 12px; color: #c9d1d9; font-size: 13px; width: 240px; font-family: monospace; }
  .topbar input:focus { border-color: #58a6ff; outline: none; }
  .topbar button { padding: 6px 16px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; font-size: 13px; cursor: pointer; }
  .topbar button:hover { background: #30363d; }
  .topbar .status-badge { font-size: 12px; padding: 3px 10px; border-radius: 10px; }
  .topbar .done { background: #3fb95033; color: #56d364; border: 1px solid #3fb95055; }
  .topbar .active { background: #1f6feb33; color: #58a6ff; border: 1px solid #1f6feb55; }
  .topbar .error { background: #f8514933; color: #ff7b72; border: 1px solid #f8514955; }

  .main { display: flex; height: calc(100vh - 56px); }
  .sidebar { width: 360px; min-width: 360px; background: #161b22; border-right: 1px solid #30363d; overflow-y: auto; padding: 12px; }
  .content { flex: 1; overflow-y: auto; padding: 16px 20px; }

  .node { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; margin-bottom: 8px; cursor: pointer; transition: all 0.15s; }
  .node:hover { border-color: #58a6ff55; }
  .node.active { border-color: #58a6ff; box-shadow: 0 0 0 1px #58a6ff33; }
  .node.current { border-color: #d29922; }
  .node.terminal { opacity: 0.7; }
  .node-header { padding: 10px 14px; display: flex; align-items: center; justify-content: space-between; }
  .node-name { font-weight: 600; font-size: 14px; }
  .node-count { font-size: 11px; color: #8b949e; }
  .node-actors { font-size: 11px; color: #8b949e; margin-top: 2px; }
  .node-body { padding: 0 14px 10px; display: none; }
  .node.open .node-body { display: block; }

  .arrow { text-align: center; color: #484f58; font-size: 14px; padding: 2px 0; }
  .arrow .label { font-size: 10px; display: block; color: #6e7681; }

  .decision-item { font-size: 12px; padding: 4px 8px; margin: 3px 0; border-left: 2px solid #30363d; }
  .decision-item.approve { border-color: #3fb950; }
  .decision-item.reject { border-color: #f85149; }
  .decision-item.info { border-color: #58a6ff; }
  .decision-item .role { font-weight: 600; }
  .decision-item .val { font-size: 11px; }
  .msg-item { font-size: 11px; padding: 4px 8px; margin: 2px 0; background: #161b22; border-radius: 4px; }
  .msg-item .from { color: #58a6ff; }

  .resume-btn { display: inline-block; padding: 4px 12px; border-radius: 6px; border: 1px solid #3fb95055; background: #3fb95022; color: #56d364; font-size: 12px; cursor: pointer; margin-top: 6px; }
  .resume-btn:hover { background: #3fb95033; }

  .detail-panel { display: none; }
  .detail-panel.open { display: block; }
  .detail-panel h2 { font-size: 18px; margin-bottom: 12px; color: #e6edf3; }
  .detail-panel h3 { font-size: 14px; margin: 16px 0 8px; color: #e6edf3; }
  .detail-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .detail-table td { padding: 6px 10px; border-bottom: 1px solid #21262d; }

  .empty-state { color: #8b949e; text-align: center; padding: 60px; font-size: 14px; }

  #toast { position: fixed; bottom: 20px; right: 20px; padding: 10px 20px; border-radius: 8px; font-size: 13px; display: none; z-index: 999; }
  #toast.ok { background: #3fb95033; border: 1px solid #3fb95055; color: #56d364; display: block; }
  #toast.err { background: #f8514933; border: 1px solid #f8514955; color: #ff7b72; display: block; }
</style>
</head>
<body>
<div class="topbar">
  <h1>State Flow</h1>
  <input id="run-input" type="text" placeholder="输入 Run ID..." onkeydown="if(event.key=='Enter')loadRun()">
  <button onclick="loadRun()">查看</button>
  <span id="run-badge"></span>
</div>

<div id="main-content" class="main">
  <div class="empty-state" id="empty-msg">输入 Run ID 查看状态流转图<br><br>每个节点可点击展开详情<br>点击「从此恢复」可从该状态继续</div>
  <div class="sidebar" id="sidebar" style="display:none"></div>
  <div class="content" id="content" style="display:none"></div>
</div>

<div id="toast"></div>

<script>
let currentRunId = '';
let graphData = null;

async function loadRun() {
  const runId = document.getElementById('run-input').value.trim();
  if (!runId) return;
  currentRunId = runId;
  document.getElementById('empty-msg').style.display = 'none';

  try {
    const r = await fetch('/api/runs/' + runId + '/graph');
    graphData = await r.json();
    if (graphData.error) { showToast(graphData.error, 'err'); return; }

    document.getElementById('sidebar').style.display = 'block';
    document.getElementById('content').style.display = 'block';
    render();
  } catch(e) {
    showToast('Failed to load: ' + e.message, 'err');
  }
}

function render() {
  if (!graphData || !graphData.states) return;
  const states = graphData.states;
  const edges = graphData.transitions || [];
  const currentState = graphData.current_state_id;
  const runStatus = graphData.status;

  // Badge
  const badge = document.getElementById('run-badge');
  badge.innerHTML = '<span class="status-badge ' + (runStatus=='completed'?'done':runStatus=='active'?'active':'error') + '">' + (runStatus||'?') + '</span> <span style="font-size:12px;color:#8b949e">' + currentRunId.slice(0,12) + '</span>';

  // Build transition DAG for ordering
  const visited = new Set();
  const order = [];
  edges.forEach(e => {
    if (!visited.has(e.from)) { visited.add(e.from); order.push(e.from); }
  });
  edges.forEach(e => {
    if (!visited.has(e.to)) { visited.add(e.to); order.push(e.to); }
  });
  // Add any states not in edges
  states.forEach(s => {
    if (!visited.has(s.state_id)) { order.push(s.state_id); }
  });

  // Sidebar: state nodes as DAG
  const sb = document.getElementById('sidebar');
  let html = '<div style="font-size:12px;color:#8b949e;margin-bottom:8px">' + states.length + ' states, ' + edges.length + ' transitions</div>';
  order.forEach(sid => {
    const s = states.find(x => x.state_id === sid);
    if (!s) return;
    const isCurrent = sid === currentState;
    const isTerminal = s.terminal;
    const cls = (isCurrent ? ' current' : '') + (isTerminal ? ' terminal' : '');
    const decCount = s.decisions ? s.decisions.length : 0;
    const msgCount = s.out_messages ? s.out_messages.length : 0;
    const visits = s.visit_count || 0;
    html += '<div class="node' + cls + '" data-state="' + sid + '" onclick="toggleNode(this)">';
    html += '<div class="node-header"><div><div class="node-name">' + sid + (visits > 1 ? ' <span style="font-size:11px;color:#8b949e">x' + visits + '</span>' : '') + '</div><div class="node-actors">' + (s.actors||[]).join(', ') + '</div></div><div class="node-count">' + decCount + ' dec / ' + msgCount + ' msg</div></div>';
    html += '<div class="node-body" id="body-' + sid + '"></div>';
    html += '</div>';

    // Outgoing edges
    const outEdges = edges.filter(e => e.from === sid);
    outEdges.forEach(e => {
      const target = states.find(x => x.state_id === e.to);
      const label = e.gate_result ? (e.gate_result.includes('fail') ? 'fail' : 'pass') : '';
      html += '<div class="arrow">|</div>';
      html += '<div class="arrow"><span class="label">' + (e.round > 0 ? 'r' + e.round + ' ' : '') + (label||'→') + '</span></div>';
      html += '<div class="arrow">v</div>';
    });
  });
  sb.innerHTML = html;

  // Content: detail for first state
  if (order.length > 0) {
    showDetail(order[0]);
  }
}

function toggleNode(el) {
  const sid = el.dataset.state;
  const body = document.getElementById('body-' + sid);
  el.classList.toggle('open');
  if (el.classList.contains('open')) {
    showDetail(sid);
  }
}

function showDetail(sid) {
  const s = graphData.states.find(x => x.state_id === sid);
  if (!s) return;
  const ct = document.getElementById('content');
  const isCurrent = sid === graphData.current_state_id;
  const isTerminal = s.terminal;
  const runActive = graphData.status === 'active';

  let html = '<div class="detail-panel open">';
  html += '<h2>' + sid + ' <span style="font-size:14px;color:#8b949e;font-weight:400">(' + (isCurrent ? 'current' : '') + (isTerminal ? ' terminal' : '') + ')</span></h2>';

  // Gate info
  if (s.gate) {
    html += '<div style="font-size:12px;color:#8b949e;margin-bottom:8px">Gate: required=' + JSON.stringify(s.gate.required_roles||[]) + ' pass=' + JSON.stringify(s.gate.pass_values||[]) + ' fail=' + JSON.stringify(s.gate.fail_values||[]) + '</div>';
  }

  // Resume button (if not terminal and run is paused/active)
  if (!isTerminal && !runActive) {
    html += '<button class="resume-btn" data-state="' + sid + '" onclick="resumeFrom(this)">从该状态重启流程</button>';
  }
  if (isCurrent && runActive) {
    html += '<button class="resume-btn" data-state="' + sid + '" onclick="resumeFrom(this)" style="border-color:#58a6ff55;background:#58a6ff22;color:#58a6ff">从当前状态继续</button>';
  }

  // Decisions in this state
  if (s.decisions && s.decisions.length > 0) {
    html += '<h3>Decisions (' + s.decisions.length + ')</h3>';
    s.decisions.forEach(d => {
      const cls = d.value === 'APPROVE' || d.value === 'PASS' ? 'approve' : d.value === 'REQUEST_CHANGES' || d.value === 'BLOCKED' ? 'reject' : 'info';
      html += '<div class="decision-item ' + cls + '"><span class="role">' + d.role_id + '</span> <span class="val">' + d.value + '</span> — ' + (d.reason||'').slice(0,60) + '</div>';
    });
  } else {
    html += '<div style="font-size:12px;color:#8b949e;margin-top:8px">No decisions in this state.</div>';
  }

  // Messages from this state
  if (s.out_messages && s.out_messages.length > 0) {
    html += '<h3>Outgoing Messages (' + s.out_messages.length + ')</h3>';
    s.out_messages.forEach(m => {
      html += '<div class="msg-item"><span class="from">' + m.from_role + '</span> → [' + (m.intended_recipients||[]).join(',') + ']: ' + (m.content||'').slice(0,80) + '</div>';
    });
  }

  // Transitions from this state
  const outTrans = (graphData.transitions||[]).filter(e => e.from === sid);
  if (outTrans.length > 0) {
    html += '<h3>Outgoing Transitions</h3>';
    outTrans.forEach(e => {
      html += '<div class="msg-item">' + e.from + ' → ' + e.to + ' (' + (e.gate_result||'auto') + ' r' + e.round + ')</div>';
    });
  }

  html += '</div>';
  ct.innerHTML = html;
}

async function resumeFrom(btn) {
  const stateId = btn.dataset.state;
  btn.textContent = '重启中...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/resume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({run_id: currentRunId, continuation_state: stateId}),
    });
    const result = await r.json();
    if (result.ok) {
      showToast('已重启到 ' + stateId + '！请启动 RuntimeLoop 继续运行。', 'ok');
      // Refresh graph
      setTimeout(loadRun, 1500);
    } else {
      showToast('重启失败: ' + (result.error||'unknown'), 'err');
      btn.textContent = '从该状态重启流程';
      btn.disabled = false;
    }
  } catch(e) {
    showToast('重启失败: ' + e.message, 'err');
    btn.textContent = '从该状态重启流程';
    btn.disabled = false;
  }
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.className = type;
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 4000);
}

// Auto-load from URL hash
if (location.hash) {
  document.getElementById('run-input').value = location.hash.slice(1);
  loadRun();
}
</script>
</body>
</html>
"""


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Hermes Flow Observer")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--project-root", help="Project root directory")
    args = parser.parse_args()

    if args.project_root:
        SSEHandler.project_root = Path(args.project_root)
        SSEHandler.runs_dir = _find_runs_dir(args.project_root)

    from http.server import ThreadingHTTPServer

    observer = FlowObserver(port=args.port)
    print(f"Hermes Flow Observer starting on http://localhost:{args.port}")
    print(f"  Runs dir: {SSEHandler.runs_dir}")

    # Start in foreground with threading to avoid SSE blocking other requests
    server = ThreadingHTTPServer(("0.0.0.0", args.port), SSEHandler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nShutting down...")


if __name__ == "__main__":
    main()
