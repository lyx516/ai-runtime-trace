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

logger = logging.getLogger(__name__)

RUNS_DIR_NAME = ".hermes-flow/runs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_runs_dir(project_root: str | None = None) -> Path:
    """Find the .hermes-flow/runs directory."""
    if project_root:
        p = Path(project_root) / RUNS_DIR_NAME
        if p.exists():
            return p
    for base in [Path.cwd(), Path.home()]:
        p = base / RUNS_DIR_NAME
        if p.exists():
            return p
    # Fallback to experiments
    p = Path.home() / "ai-runtime-trace" / RUNS_DIR_NAME.lstrip("/")
    return p


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
        try:
            return _get_store(run_id, self.runs_dir)
        except Exception:
            return None

    def _list_runs(self) -> list[dict]:
        runs = []
        if not self.runs_dir.exists():
            return runs
        for d in sorted(self.runs_dir.iterdir(), reverse=True):
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
                    runs.append({
                        "run_id": d.name,
                        "display_name": display_name,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "path": str(d),
                        "db_size": db.stat().st_size if db.exists() else 0,
                    })
        runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
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
                elif resource == "thinking":
                    role_id = qs.get("role_id", [None])[0]
                    state_id = qs.get("state_id", [None])[0]
                    data = self._get_thinking(run_id, role_id, state_id)

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
        """Query thinking events for a run."""
        store = self._read_store(run_id)
        if not store:
            return []
        try:
            return store.load_thinking_events(
                run_id, role_id=role_id, state_id=state_id,
            )
        except Exception as e:
            return [{"error": str(e)}]

    def _serve_pool_api(self):
        """Serve agent pool data from the project's agents/ directory."""
        candidates = [
            Path(__file__).resolve().parent.parent / "experiments" / "agent-pool",
            Path(__file__).resolve().parent.parent / "experiments" / "agent-pool-plugin",
            Path.home() / ".hermes" / "plugins" / "agent-pool",
        ]
        plugin_dir = None
        for c in candidates:
            if (c / "agents").exists():
                plugin_dir = c
                break
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
