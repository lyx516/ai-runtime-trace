# Implementation Plan: Span Tree Trace

**Branch**: `002-span-tree-trace` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-span-tree-trace/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Add an AI-readable execution trace (Span Tree) into the Hermes Flow FSM runtime. Every significant execution step records a structured span with trace_id/span_id/parent_span_id into a `trace_events` SQLite table. The trace is always-on, always persisted, and consumed directly by AI agents via SQL queries. Implementation adds a `Tracer` module (contextvars-based span stack), injects `tracer.span()` calls into ~15 production code paths, and provides query helpers.

## Technical Context

**Language/Version**: Python 3.11+ (same as existing hermes_flow package)

**Primary Dependencies**: Python standard library (`sqlite3`, `json`, `contextvars`, `logging`, `uuid`, `atexit`, `datetime`, `traceback`). No new external dependencies.

**Storage**: Existing run-local SQLite database at `.hermes-flow/runs/<run_id>/state.sqlite`. A new `trace_events` table is created by `init_schema()` alongside existing tables. No separate storage.

**Testing**: pytest. Tracer tests use an in-memory SQLite store + the existing `tmp_project_root` fixture. Key scenarios: span tree validity, error capture, truncation, crash safety via `atexit`, write failure swallow, concurrent trace_id isolation.

**Target Platform**: Same as existing Hermes Flow — macOS and Linux first.

**Project Type**: Python library module (adds `hermes_flow/trace.py`). Pure addition, no new package structure.

**Performance Goals**: Under 1ms overhead per span. Under 1KB SQLite storage per typical span. Verified by a performance smoke test with 1000 spans (SC-005). 1-write per span (no double-write).

**Constraints**: Always-on (no opt-out). Must not cause main operation failure if trace write fails (swallow + logging.warning). Must not add new external dependencies. Must be usable by AI agents reading SQLite directly (no HTTP/gRPC layer).

**Scale/Scope**: Single run's trace fits in one SQLite database (thousands of spans per run). No cross-run aggregation needed in this feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Minimal Useful Scope**: PASS — The feature adds exactly one thing (structured execution trace) with one output (trace_events table) and one consumer (AI agent reading SQLite). Dashboard, OpenTelemetry export, sampling, alerting are explicitly out of scope.
- **Reusable Core Only**: PASS — The Tracer is a reusable module consumed by every traced function (~15 call sites). No single-use wrappers or empty abstractions.
- **Readability**: PASS — event_type names are machine-readable action labels (gate_evaluate, msg_route). Span fields (inputs/outputs/decisions/error) are JSON with documented structure.
- **Evidence Before Expansion**: PASS — Every design decision (1-write, swallow errors, explicit set_tracer) was clarified during speckit-clarify with documented rationale.
- **宁缺毋滥 Quality Bar**: PASS — If trace write fails, the tracer logs a warning and the span is lost (no fake or partial records). Truncation is explicit with a `truncated` flag.

## Project Structure

### Documentation (this feature)

```text
specs/002-span-tree-trace/
├── plan.md              # This file
├── research.md          # Phase 0 — minimal (all clarifications resolved)
├── data-model.md        # Phase 1 — TraceSpan entity, trace_events table, query helpers
├── quickstart.md        # Phase 1 — AI agent query walkthrough
└── contracts/
    └── trace-span-schema.yaml  # Phase 1 — self-describing TraceSpan schema
```

### Source Code (repository root)

```text
# NEW file:
hermes_flow/
├── trace.py             # Tracer, SqliteTracer, NoOpTracer, set_tracer/get_tracer
└── storage.py           # (add trace_events table to init_schema, add query methods)

# MODIFIED files:
hermes_flow/
├── tools.py             # flow_init sets tracer; remaining handlers use get_tracer()
├── flow_loader.py       # load_flow_from_yaml + validate_flow wrapped in tracer.span()
├── context.py           # build_context_packet wrapped in tracer.span()
├── worker.py            # worker_dispatch wrapped in tracer.span()
├── engine.py            # evaluate_gate, advance_state, loop budget/ idle checks
├── routing.py           # route_message wrapped in tracer.span()
├── storage.py           # create_run, record_decision, record_message_attempt wrapped

tests/hermes_flow/
├── test_trace.py        # NEW — tracer unit tests
└── test_storage.py      # (extend — trace_events table tests)
```

**Structure Decision**: Single-module addition (`trace.py`) + minimal patches to existing modules. No new package. The Tracer is a standalone class that depends only on stdlib; it imports nothing from hermes_flow except schemas (for the span data model).

## Complexity Tracking

No constitution violations are required. The only new boundary is justified by multiple concrete consumers:

| Boundary | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|--------------------------------------|
| `trace.py` module | Used by ~15 production code paths + tests | Inlining tracer into every caller would violate DRY and make test mocking impossible |
| `contextvars` span stack | Enables automatic parent_span_id without manual propagation | Passing `parent_span` through every function signature would bloat all interfaces |
