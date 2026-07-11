"""Trace Query Engine — read-only span tree query and analysis aggregation.

Provides TraceQueryEngine with two primary methods:
- trace_tree(trace_id) — build nested span tree from flat trace_events table
- trace_analyze(run_id) — compute timing distributions and summary stats
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from runtime_trace.storage import RuntimeStore

logger = logging.getLogger(__name__)


class TraceQueryError(Exception):
    """Raised when trace data cannot be queried."""


class TraceQueryEngine:
    """Read-only query engine over the trace_events SQLite table.

    Does NOT modify any data — purely analytical reads.
    Uses the existing RuntimeStore connection to avoid extra connections.
    """

    def __init__(self, store: RuntimeStore):
        self._store = store

    # ── Span tree ──────────────────────────────────────────────────────────

    def trace_tree(self, trace_id: str, max_depth: int = 50) -> dict[str, Any] | None:
        """Build a nested span tree for a given trace_id.

        Returns the root span with recursive 'children', or None if not found.
        """
        conn = self._store.connect()
        rows = conn.execute(
            "SELECT * FROM trace_events WHERE trace_id=? ORDER BY ts_start",
            (trace_id,),
        ).fetchall()

        if not rows:
            return None

        spans = [dict(r) for r in rows]
        span_map: dict[str, dict] = {}
        root = None

        for s in spans:
            node = {
                "span_id": s["span_id"],
                "event_type": s["event_type"],
                "parent_span_id": s["parent_span_id"],
                "ts_start": s["ts_start"],
                "ts_end": s["ts_end"],
                "duration_ms": s["duration_ms"],
                "inputs": self._safe_json(s.get("inputs", "{}")),
                "outputs": self._safe_json(s.get("outputs", "{}")),
                "error": self._safe_json(s.get("error")) if s.get("error") else None,
                "children": [],
            }
            span_map[s["span_id"]] = node
            if not s["parent_span_id"] or s["parent_span_id"] == s["span_id"]:
                root = node
            else:
                parent = span_map.get(s["parent_span_id"])
                if parent and len(parent["children"]) < max_depth:
                    parent["children"].append(node)

        return root

    # ── Analysis ───────────────────────────────────────────────────────────

    def trace_analyze(self, run_id: str) -> dict[str, Any]:
        """Compute a full analysis summary for a run.

        Returns timing distributions, decision summary, transition counts,
        and optimization suggestions.
        """
        conn = self._store.connect()

        # Span count and timing
        span_rows = conn.execute(
            "SELECT event_type, duration_ms FROM trace_events WHERE run_id=?",
            (run_id,),
        ).fetchall()

        total_spans = len(span_rows)
        total_duration = sum(r["duration_ms"] for r in span_rows) if span_rows else 0

        # Per-event-type timing
        type_timing: dict[str, dict] = {}
        for r in span_rows:
            et = r["event_type"]
            d = r["duration_ms"]
            if et not in type_timing:
                type_timing[et] = {"count": 0, "total_ms": 0, "min_ms": d, "max_ms": 0}
            t = type_timing[et]
            t["count"] += 1
            t["total_ms"] += d
            t["min_ms"] = min(t["min_ms"], d)
            t["max_ms"] = max(t["max_ms"], d)

        # Transitions
        trans_rows = conn.execute(
            "SELECT * FROM transitions WHERE run_id=? ORDER BY row_id",
            (run_id,),
        ).fetchall()
        transitions = [dict(r) for r in trans_rows]

        # Decisions
        dec_rows = conn.execute(
            "SELECT value FROM decisions WHERE run_id=?",
            (run_id,),
        ).fetchall()
        decision_summary: dict[str, int] = {}
        for r in dec_rows:
            v = r["value"]
            decision_summary[v] = decision_summary.get(v, 0) + 1

        # Round count
        round_count = 0
        for t in transitions:
            rc = t.get("round_counter", 0) or 0
            round_count = max(round_count, rc)

        # Suggestions
        suggestions = []
        slow_events = [(et, d["total_ms"]) for et, d in type_timing.items()
                       if d["count"] > 0 and d["total_ms"] > 1000]
        slow_events.sort(key=lambda x: -x[1])
        for et, ms in slow_events[:3]:
            pct = round(ms / max(total_duration, 1) * 100)
            suggestions.append(f"{et} took {ms}ms ({pct}% of total). Consider reducing.")

        if round_count >= 3:
            suggestions.append(
                f"High revision count ({round_count} rounds). "
                "Check gate conditions or increase max_rounds."
            )

        return {
            "run_id": run_id,
            "wall_time_ms": total_duration,
            "trace_span_count": total_spans,
            "event_type_timing": type_timing,
            "transition_count": len(transitions),
            "round_count": round_count,
            "decision_summary": decision_summary,
            "suggestions": suggestions,
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_json(value: Any) -> Any:
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value) if isinstance(value, str) else value
        except (json.JSONDecodeError, TypeError):
            return {"_parse_error": True, "_raw": str(value)[:200]}
