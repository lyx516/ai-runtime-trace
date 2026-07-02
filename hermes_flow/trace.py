"""Span Tree Trace — AI-readable execution trace for the Hermes Flow FSM runtime.

Provides Tracer, NoOpTracer, and SqliteTracer for recording structured spans
with causal parentage into the trace_events SQLite table.
"""

from __future__ import annotations

import atexit
import logging
import sys
import traceback as tb_module
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Optional

from hermes_flow.schemas import to_dict

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_MAX_SPAN_FIELD_BYTES = 100_000

# ── Context var for per-coroutine span stack ────────────────────────────────

_span_stack: ContextVar[list["_SpanContext"]] = ContextVar("_span_stack", default=[])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _truncate_field(value: Any, max_bytes: int = _MAX_SPAN_FIELD_BYTES) -> tuple[Any, bool]:
    """Truncate a dict or str field to max_bytes.

    Returns (truncated_value, was_truncated).
    """
    if isinstance(value, dict):
        serialized = to_dict(value)
        text = __import__("json").dumps(serialized, ensure_ascii=False, default=str)
        if len(text.encode("utf-8")) <= max_bytes:
            return value, False
        return {"_truncated": True, "_original_type": "dict", "_size_bytes": len(text.encode("utf-8"))}, True
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) <= max_bytes:
            return value, False
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        return truncated, True
    return value, False


# ── TraceSpan data class ────────────────────────────────────────────────────

class TraceSpan:
    """One structured execution record in the causal tree."""

    __slots__ = (
        "trace_id", "span_id", "parent_span_id", "run_id", "event_type",
        "ts_start", "ts_end", "duration_ms",
        "inputs", "outputs", "decisions", "error",
        "truncated", "ended",
    )

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: str,
        run_id: str,
        event_type: str,
        inputs: dict[str, Any] | None = None,
    ):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.run_id = run_id
        self.event_type = event_type
        self.ts_start = _now()
        self.ts_end = ""
        self.duration_ms = 0
        self.inputs = inputs or {}
        self.outputs: dict[str, Any] = {}
        self.decisions: dict[str, Any] = {}
        self.error: dict[str, Any] | None = None
        self.truncated = False
        self.ended = False

    def to_sqlite_row(self) -> dict[str, Any]:
        """Serialize to a flat dict matching the trace_events SQLite columns."""
        inputs_val, inputs_trunc = _truncate_field(self.inputs)
        outputs_val, outputs_trunc = _truncate_field(self.outputs)
        decisions_val, dec_trunc = _truncate_field(self.decisions)

        error_val = None
        error_trunc = False
        if self.error is not None:
            error_val, error_trunc = _truncate_field(self.error)

        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "ts_start": self.ts_start,
            "ts_end": self.ts_end,
            "duration_ms": self.duration_ms,
            "inputs": __import__("json").dumps(inputs_val, ensure_ascii=False, default=str),
            "outputs": __import__("json").dumps(outputs_val, ensure_ascii=False, default=str),
            "decisions": __import__("json").dumps(decisions_val, ensure_ascii=False, default=str),
            "error": __import__("json").dumps(error_val, ensure_ascii=False, default=str) if error_val is not None else None,
            "truncated": int(self.truncated or inputs_trunc or outputs_trunc or error_trunc or dec_trunc),
            "ended": int(self.ended),
        }


# ── Span context (context manager) ──────────────────────────────────────────

class _SpanContext:
    """Internal context manager returned by Tracer.span()."""

    def __init__(self, tracer: "Tracer", span: TraceSpan):
        self._tracer = tracer
        self._span = span

    def __enter__(self) -> TraceSpan:
        stack = _span_stack.get()
        stack.append(self)
        _span_stack.set(stack)
        return self._span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # Pop from stack
        try:
            stack = _span_stack.get()
            if stack and stack[-1] is self:
                stack.pop()
                _span_stack.set(stack)
        except Exception:
            pass

        # Compute duration
        self._span.ts_end = _now()
        try:
            start = datetime.fromisoformat(self._span.ts_start)
            end = datetime.fromisoformat(self._span.ts_end)
            self._span.duration_ms = int((end - start).total_seconds() * 1000)
        except Exception:
            self._span.duration_ms = 0

        self._span.ended = True

        # Capture error if exception occurred
        if exc_type is not None and exc_val is not None:
            self._span.error = {
                "type": exc_type.__name__,
                "message": str(exc_val),
                "traceback": "".join(tb_module.format_exception(exc_type, exc_val, exc_tb)),
            }

        # Let the tracer write the span
        self._tracer._write_span(self._span)  # noqa: SLF001


# ── Tracer base ─────────────────────────────────────────────────────────────

class Tracer:
    """Abstract tracer base. Subclasses implement _write_span()."""

    def span(
        self,
        event_type: str,
        inputs: dict[str, Any] | None = None,
    ) -> Any:
        """Create a new span context manager.

        Auto-assigns trace_id (inherited from parent span or generated fresh),
        span_id (unique), and parent_span_id (from current stack top).
        """
        stack = _span_stack.get()
        parent = stack[-1]._span if stack else None  # noqa: SLF001
        trace_id = parent.trace_id if parent else _new_id()
        span_id = _new_id()
        parent_span_id = parent.span_id if parent else ""

        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            run_id=parent.run_id if parent else "",
            event_type=event_type,
            inputs=inputs,
        )

        ctx = _SpanContext(self, span)
        return ctx

    def _write_span(self, span: TraceSpan) -> None:
        """Subclasses override this to persist the span."""
        raise NotImplementedError


# ── NoOpTracer ──────────────────────────────────────────────────────────────

class NoOpTracer(Tracer):
    """Tracer that does nothing. Default for tests."""

    def span(
        self,
        event_type: str,
        inputs: dict[str, Any] | None = None,
    ) -> _SpanContext:
        # Return a no-op context manager
        return _NoOpSpanContext()


class _NoOpSpanContext:
    """Context manager that yields a mutable dummy for attribute assignment."""

    def __init__(self):
        self._dummy = _NoOpSpan()

    def __enter__(self):
        return self._dummy

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpSpan:
    """Dummy span object that silently accepts attribute writes."""
    def __init__(self):
        self.outputs = {}
        self.decisions = {}


# ── SqliteTracer ────────────────────────────────────────────────────────────

class SqliteTracer(Tracer):
    """Tracer that writes spans to trace_events via a RuntimeStore connection."""

    def __init__(self, store: Any, run_id: str = ""):
        self._store = store
        self._run_id = run_id
        # Register atexit handler for unclosed spans
        self._atexit_registered = False
        self._register_atexit()

    def _register_atexit(self) -> None:
        if not self._atexit_registered:
            atexit.register(self._flush_unclosed)
            self._atexit_registered = True

    def _flush_unclosed(self) -> None:
        """Flush any spans remaining on the contextvar stack (process exit)."""
        try:
            stack = _span_stack.get()
            while stack:
                ctx = stack.pop()
                span = ctx._span  # noqa: SLF001
                if not span.ended:
                    span.ts_end = _now()
                    span.ended = False  # explicitly mark as unclosed
                    self._write_span(span)
        except Exception:
            pass

    def _write_span(self, span: TraceSpan) -> None:
        """Write a single span to trace_events. Swallows errors with logging.warning."""
        try:
            row = span.to_sqlite_row()
            conn = self._store.connect()
            conn.execute(
                """INSERT INTO trace_events
                   (trace_id, span_id, parent_span_id, run_id, event_type,
                    ts_start, ts_end, duration_ms,
                    inputs, outputs, decisions, error,
                    truncated, ended)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["trace_id"],
                    row["span_id"],
                    row["parent_span_id"],
                    self._run_id or row["run_id"],
                    row["event_type"],
                    row["ts_start"],
                    row["ts_end"],
                    row["duration_ms"],
                    row["inputs"],
                    row["outputs"],
                    row["decisions"],
                    row["error"],
                    row["truncated"],
                    row["ended"],
                ),
            )
            conn.commit()
        except Exception as e:
            logger.warning("trace write failed for %s: %s", span.event_type, e)


# ── Module-level tracer API ─────────────────────────────────────────────────

_tracer: Tracer = NoOpTracer()


def set_tracer(tracer: Tracer) -> None:
    """Set the global tracer instance."""
    global _tracer  # noqa: PLW0603
    _tracer = tracer


def get_tracer() -> Tracer:
    """Return the current global tracer instance."""
    return _tracer
