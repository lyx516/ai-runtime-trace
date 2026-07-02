# Data Model: Span Tree Trace

## Entity: TraceSpan

Represents one structured execution record in the causal tree.

**Fields**:
- `trace_id`: root identifier for one causal tree (UUID hex, 12 chars). Generated fresh for root spans; inherited from parent span for nested spans.
- `span_id`: unique identifier for this span (UUID hex, 12 chars).
- `parent_span_id`: parent span's span_id, empty string for root spans.
- `run_id`: owning flow run identifier, for cross-run isolation.
- `event_type`: machine-readable label (e.g., `flow_init`, `gate_evaluate`, `msg_route`, `load_flow`, `validate_flow`, `create_run`, `build_context`, `validate_write`, `route_message`, `record_decision`, `record_message`, `advance_state`, `worker_dispatch`, `loop_check`, `idle_check`).
- `ts_start`: ISO-8601 UTC timestamp of span entry.
- `ts_end`: ISO-8601 UTC timestamp of span exit.
- `duration_ms`: integer milliseconds (ts_end - ts_start).
- `inputs`: JSON dict — the arguments passed to this step.
- `outputs`: JSON dict — the return values of this step.
- `decisions`: JSON dict — choice-based outcomes (gate result, routing decision, loop budget status).
- `error`: JSON dict or null — `{type: str, message: str, traceback: str}` if the span exited with an exception.
- `truncated`: boolean — true if any field was truncated at the 100KB limit.
- `ended`: boolean — always true for correctly closed spans; false only if `atexit` flushed an unclosed span.

**Validation rules**:
- `trace_id` and `span_id` must be non-empty strings.
- `parent_span_id` must be empty for root spans, non-empty for nested spans.
- `inputs`, `outputs`, `decisions` must be valid JSON dicts (or null if not captured).
- At least one of `outputs` or `error` must be present (a span either succeeds or fails).
- `duration_ms` must be >= 0.
- If `truncated` is true, the truncated field value is replaced with `"<truncated: N chars>"`.

## SQLite Table: trace_events

```sql
CREATE TABLE IF NOT EXISTS trace_events (
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL PRIMARY KEY,
    parent_span_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ts_start TEXT NOT NULL,
    ts_end TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    inputs TEXT NOT NULL DEFAULT '{}',
    outputs TEXT NOT NULL DEFAULT '{}',
    decisions TEXT NOT NULL DEFAULT '{}',
    error TEXT,       -- null or JSON
    truncated INTEGER NOT NULL DEFAULT 0,
    ended INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events(event_type);
CREATE INDEX IF NOT EXISTS idx_trace_events_run  ON trace_events(run_id, trace_id);
```

## Entity: Tracer (module-level singleton)

Maintains a per-coroutine span stack using `contextvars`. Provides two implementations:

- **NoOpTracer**: `span()` yields instantly, no recording. Default for tests.
- **SqliteTracer**: `span()` enters → creates in-memory TraceSpan, pushes to stack → `__exit__` computes duration, writes single INSERT to trace_events → on exception captures error → pops stack. `atexit` flush writes any unclosed spans.

**Module-level API**:
- `set_tracer(tracer)` — replace the global tracer (safe for test teardown).
- `get_tracer()` — return the current tracer, defaulting to `NoOpTracer()`.
- `Tracer.span(event_type, inputs=None)` → context manager returning `SpanContext`.

## Query Helpers (on RuntimeStore)

```python
def get_trace(self, run_id: str, trace_id: str) -> list[dict]:
    """Return all spans for a trace_id in chronological order."""

def get_traces_by_event(self, run_id: str, event_type: str) -> list[dict]:
    """Return all spans of a given event_type across traces."""
```

## State Transitions

```text
Span lifecycle:
  created (in-memory, __enter__)
    → completed (written to SQLite, __exit__ clean)
    → failed (written to SQLite with error, __exit__ exception)
    → unclosed (written by atexit if process terminates mid-span)
```
