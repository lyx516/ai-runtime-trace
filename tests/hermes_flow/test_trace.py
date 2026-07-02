"""Trace unit tests for the Span Tree Trace feature — Tracer, spans, and trace_events."""

import json
import tempfile
from pathlib import Path

import pytest

from hermes_flow.schemas import _now
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import (
    NoOpTracer,
    SqliteTracer,
    TraceSpan,
    _SpanContext,
    _truncate_field,
    get_tracer,
    set_tracer,
)


@pytest.fixture
def store_with_trace(tmp_project_root: Path) -> RuntimeStore:
    """Create a RuntimeStore with trace_events table initialized."""
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / "test-trace"
    run_dir.mkdir(parents=True, exist_ok=True)
    store = RuntimeStore(run_dir)
    store.init_schema()
    return store


def test_noop_tracer_does_nothing() -> None:
    """NoOpTracer.span() must return instantly without recording."""
    tracer = NoOpTracer()
    with tracer.span("test_event") as span:
        assert span is None
    # No crash means success


def test_sqlite_tracer_writes_one_span(store_with_trace: RuntimeStore) -> None:
    """SqliteTracer must write one span to trace_events after __exit__."""
    tracer = SqliteTracer(store_with_trace, run_id="test-run")
    with tracer.span("test_event", inputs={"key": "value"}):
        pass

    rows = store_with_trace.connect().execute(
        "SELECT * FROM trace_events WHERE event_type = ?", ("test_event",)
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["trace_id"] != ""
    assert row["span_id"] != ""
    assert row["parent_span_id"] == ""
    assert row["run_id"] == "test-run"
    assert row["event_type"] == "test_event"
    assert row["ts_start"] != ""
    assert row["ts_end"] != ""
    assert row["duration_ms"] >= 0
    assert row["ended"] == 1
    assert row["truncated"] == 0

    # Check inputs were stored
    inputs = json.loads(row["inputs"])
    assert inputs["key"] == "value"


def test_span_has_all_required_fields(store_with_trace: RuntimeStore) -> None:
    """A SqliteTracer span must have all required non-empty fields."""
    tracer = SqliteTracer(store_with_trace, run_id="r1")
    with tracer.span("test_event", inputs={"a": 1}) as span:
        assert span.trace_id != ""
        assert span.span_id != ""
        assert span.event_type == "test_event"
        assert span.inputs == {"a": 1}

    row = store_with_trace.connect().execute(
        "SELECT * FROM trace_events"
    ).fetchone()
    assert row is not None
    assert row["trace_id"] == span.trace_id
    assert row["span_id"] == span.span_id
    assert row["parent_span_id"] == span.parent_span_id


def test_ts_end_after_ts_start(store_with_trace: RuntimeStore) -> None:
    """A span's ts_end must be >= ts_start and duration_ms >= 0."""
    tracer = SqliteTracer(store_with_trace, run_id="r1")
    import time
    with tracer.span("timing_test"):
        time.sleep(0.001)  # tiny delay

    row = store_with_trace.connect().execute(
        "SELECT * FROM trace_events WHERE event_type = ?", ("timing_test",)
    ).fetchone()
    assert row["ts_end"] >= row["ts_start"]
    assert row["duration_ms"] >= 1


def test_duration_ms_non_negative(store_with_trace: RuntimeStore) -> None:
    """duration_ms must never be negative, even for zero-duration spans."""
    tracer = SqliteTracer(store_with_trace, run_id="r1")
    with tracer.span("quick"):
        pass

    row = store_with_trace.connect().execute(
        "SELECT * FROM trace_events WHERE event_type = ?", ("quick",)
    ).fetchone()
    assert row["duration_ms"] >= 0


def test_truncate_large_dict() -> None:
    """_truncate_field must truncate dicts exceeding 100KB."""
    large = {"data": "x" * 200_000}
    result, was_truncated = _truncate_field(large, max_bytes=50_000)
    assert was_truncated is True
    assert result["_truncated"] is True


def test_truncate_small_dict_not_truncated() -> None:
    """_truncate_field must not truncate dicts under the limit."""
    small = {"key": "value"}
    result, was_truncated = _truncate_field(small)
    assert was_truncated is False
    assert result == small


def test_set_tracer_and_get_tracer() -> None:
    """set_tracer/get_tracer must work as module-level accessors."""
    original = get_tracer()
    assert isinstance(original, NoOpTracer)

    custom = NoOpTracer()
    set_tracer(custom)
    assert get_tracer() is custom

    # Reset
    set_tracer(NoOpTracer())
