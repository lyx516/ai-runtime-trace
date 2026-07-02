# Feature Specification: Span Tree Trace

**Feature Branch**: `002-span-tree-trace`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "Add AI-readable execution trace (Span Tree) into the Hermes Flow FSM runtime. Every tool call, gate evaluation, message route, state transition, and context packet generation records a structured span with trace_id/span_id/parent_span_id into a trace_events SQLite table. The trace is always-on and targeted at debugging AI agents (not humans)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every execution step records a structured span (Priority: P1)

As an AI debugging agent (such as the one reading this spec), I want every significant execution step — flow init, flow validation, state entry, gate evaluation, decision recording, message routing, context packet generation, worker dispatch, state transition, loop budget check, idle timeout — to emit a span with `trace_id`, `span_id`, `parent_span_id`, `event_type`, `inputs`, `outputs`, `decisions`, `duration_ms`, and optional `error` so that I can reconstruct the causal tree of any failed or surprising behavior without guessing.

**Why this priority**: Without spans, the only way to debug is reading human-oriented audit logs, which omit intermediate inputs, decisions, and causal parentage. This is the core of the feature.

**Independent Test**: Can be fully tested by running a minimal flow (init → validate → create_run) and confirming the trace_events table contains at least one row per call, with correct trace_id/span_id/parent_span_id forming a tree, and each row having non-empty event_type, inputs, outputs, and duration_ms.

**Acceptance Scenarios**:

1. **Given** a flow init call succeeds, **When** the test inspects the trace_events table, **Then** it finds a span with `event_type=flow_init` whose `span_id` is the root (no parent), and nested spans for `load_flow`, `validate_flow`, and `create_run` with matching `parent_span_id`.
2. **Given** a message send call with an invalid recipient, **When** routing fails, **Then** the rejected route span includes `inputs` (intended_recipients, from_role), `outputs` (delivery_outcome=rejected), and `decisions` (which recipient failed availability).
3. **Given** a gate evaluation where decisions are split, **When** evaluate_gate runs, **Then** the span captures `inputs` (required_roles, present decisions), `outputs` (satisfied=true/false, next_state_if_ready), and `decisions` (the gate result).
4. **Given** an exception is raised during any span, **When** the span exits, **Then** it records `error` with traceback and `outputs` is absent or partial.

---

### User Story 2 - Trace events survive across sessions and can be queried by trace_id (Priority: P1)

As an AI debugging agent, I want trace events persisted to the SQLite database alongside the flow run so that I can query them by `trace_id` or `event_type` in a separate session, days after the original run, and reconstruct the full execution timeline of any past run.

**Why this priority**: Debugging often happens after the fact. In-memory-only traces are useless for post-mortem analysis.

**Independent Test**: Start a flow run, confirm trace events exist, close and reopen the RuntimeStore, query by trace_id, and verify all spans from the original run are present with matching event types and timestamps.

**Acceptance Scenarios**:

1. **Given** a completed flow run with trace events, **When** a new RuntimeStore opens the same state.sqlite, **Then** SELECT * FROM trace_events WHERE trace_id = ? returns all spans in chronological order.
2. **Given** a run produced 10+ trace events, **When** queried by event_type='gate_evaluate', **Then** only gate evaluation spans are returned.
3. **Given** a run that produced multiple independent flows, **When** queried by trace_id, **Then** each trace_id returns only spans from that run.

---

### User Story 3 - Error spans include complete traceback for AI diagnosis (Priority: P2)

As an AI debugging agent, I want error spans to include the full Python traceback, the exact inputs that triggered the error, and the error type/message so that I can identify the root cause without re-running the failing code path.

**Why this priority**: Errors are the most time-consuming to debug. Having the exact failing inputs + traceback in a structured span eliminates the reproduce-guess cycle.

**Independent Test**: Force an error in a tracked operation (e.g., load a non-existent flow file, validate a flow with a missing agent), confirm the error span has non-empty error.traceback, error.type, error.message, and inputs.

**Acceptance Scenarios**:

1. **Given** a flow_load call with a non-existent file path, **When** the span exits with exception, **Then** the span has `error.traceback` containing the FileNotFoundError traceback, `error.type=FileNotFoundError`, and `error.message` with the path.
2. **Given** a gate_evaluate call where gate has no required_roles, **When** the span exits with exception, **Then** the span has `error.traceback`, `error.type`, and `inputs` showing the empty required_roles.

---

### User Story 4 - Trace is always-on with zero configuration (Priority: P2)

As an AI debugging agent, I want traces to be recorded automatically on every flow run without needing to set environment variables or pass CLI flags, so that I can debug any run even if the system was not explicitly configured for tracing.

**Why this priority**: If tracing is opt-in, the first time someone needs to debug a run they won't have the data. Always-on means every run is debuggable.

**Independent Test**: Start a flow run without setting any environment variables or trace flags, confirm trace_events table exists and is populated after init.

**Acceptance Scenarios**:

1. **Given** a fresh project with no trace configuration, **When** flow_init is called, **Then** trace_events table is created and at least one span is recorded.
2. **Given** tracing is always on, **When** a large run produces many spans, **Then** the trace overhead (latency per span) is under 1ms and SQLite storage growth is under 1KB per span.

---

### Edge Cases

- A span begins but the process crashes before it closes (no end record). The trace should still contain the start record with `duration_ms: null` and `ended: false`.
- A trace_id collision across independent runs (UUID probability negligible, but include a unique run_id check in query paths).
- Nested spans deeper than 10 levels (tool calling another tool calling another tool). The schema must support arbitrary nesting depth.
- Very large inputs/outputs (>100KB in one span). The schema should truncate or hash oversized fields, recording a `truncated: true` flag.
- Concurrent runs producing interleaved trace events — trace_id filtering must keep them fully isolated.
- An AI agent reads the trace_events table while a flow run is still writing to it (read-uncommitted isolation).

### Out of Scope *(mandatory)*

- A human-readable dashboard or visualization of span trees.
- Exporting traces to OpenTelemetry, Jaeger, Zipkin, or any external observability backend.
- Span-level sampling or rate-limiting (every span is always recorded).
- Tracing of operations outside the hermes_flow package (e.g., Hermes core itself).
- Automated anomaly detection or alerting based on trace patterns.
- Trace replay ("re-run a past trace_id").

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST define a `TraceSpan` schema with fields: `trace_id`, `span_id`, `parent_span_id`, `event_type`, `ts_start`, `ts_end`, `duration_ms`, `inputs` (JSON), `outputs` (JSON), `decisions` (JSON), `error` (JSON with type/message/traceback), `truncated`, and `ended`.
- **FR-002**: The system MUST define a `trace_events` SQLite table matching the TraceSpan schema, created via `init_schema()` alongside existing tables.
- **FR-003**: The system MUST provide a `Tracer` class that uses `contextvars` to maintain a per-coroutine span stack, supporting `span(event_type, inputs=None)` as a context manager.
- **FR-004**: The tracer MUST auto-assign `trace_id` (inherited from parent span or generated fresh for root spans), `span_id` (unique), and `parent_span_id` (from the current stack top).
- **FR-005**: The tracer MUST record `ts_start` on enter, `ts_end` + `duration_ms` on clean exit, and on exception MUST record `error` (type, message, traceback) and mark `ended=True`.
- **FR-006**: The tracer MUST flush completed spans to the `trace_events` SQLite table immediately on exit (not buffered), using the existing `RuntimeStore` connection.
- **FR-007**: The tracer MUST support a no-op mode (`NoOpTracer`) where the context manager yields instantly without recording anything.
- **FR-008**: The hermes_flow package MUST use a module-level global tracer instance, defaulting to `NoOpTracer` in tests and `SqliteTracer` in production (determined by whether a `RuntimeStore` is active).
- **FR-009**: Each production code path (`flow_init`, `load_flow_from_yaml`, `validate_flow`, `create_run`, `build_context_packet`, `validate_artifact_write`, `route_message`, `evaluate_gate`, `record_decision`, `record_message_attempt`, `advance_state`, `flow_send`, `flow_decide`, `flow_step`, `worker_dispatch`, idle timeout checks, loop budget checks) MUST wrap its body in a `tracer.span(event_type=...)` context manager.
- **FR-010**: The tracer MUST truncate any `inputs`, `outputs`, `decisions`, or `error.traceback` field exceeding 100KB, recording `truncated=True` on the span.
- **FR-011**: The tracer MUST provide a query helper `get_trace(run_id, trace_id)` that returns all spans for a trace_id in chronological order, and `get_traces_by_event(run_id, event_type)` that returns all spans of a given event_type.
- **FR-012**: The tracer MUST be injectable into `RuntimeStore` so that when a store is created with tracing enabled, the module-level tracer is automatically wired to the store's SQLite connection.

### Traceability & Validation Requirements *(mandatory)*

- **TV-001**: Each user story MUST define a repeatable validation path.
- **TV-002**: Requirements involving runtime behavior MUST state the observable execution fact, not only the human-facing message.
- **TV-003**: Any requested abstraction, extension point, or reusable component MUST name its concrete current consumers or be listed as out of scope.

### Key Entities *(include if feature involves data)*

- **TraceSpan**: A single structured execution record containing trace_id (root identifier for one causal tree), span_id (this span's identifier), parent_span_id (parent span, empty for root), event_type (machine-readable label like "gate_evaluate" or "msg_route"), timing (start/end/duration), inputs (the arguments passed to this step), outputs (the return values), decisions (choice-based outcomes like gate results or routing decisions), error (structured error with type/message/traceback if the span failed), truncated flag (if any field was truncated for size), and ended flag (false if the process crashed before the span could close).
- **Tracer**: The orchestrator that maintains the span stack (via contextvars), auto-generates trace_id/span_id, provides the `span()` context manager, and flushes completed spans to SQLite. Two implementations: NoOpTracer (no-op, for tests) and SqliteTracer (writes to trace_events via RuntimeStore connection).
- **trace_events table**: SQLite table holding all spans for a run, indexed on trace_id and event_type for AI-queryable access.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A minimal flow (init + validate + create_run) produces at least 5 trace spans forming a valid tree (one root, 3-4 children, correct parent_span_id chain).
- **SC-002**: Any exception raised inside a traced operation produces a span with non-null `error` field containing traceback, type, and message — verified with 3 distinct error types (FileNotFoundError, FlowValidationError, RuntimeStateError).
- **SC-003**: 100% of the production code paths listed in FR-009 produce a span with the correct `event_type` when executed — verified by instrumenting each function and reading trace_events.
- **SC-004**: A query `get_trace(run_id, trace_id)` returns all spans for that trace_id with no spans from other trace_ids mixed in — verified with 3 concurrent fake trace_ids.
- **SC-005**: The tracer adds no more than 1ms overhead per span and no more than 1KB SQLite storage per typical span — verified by a performance smoke test with 1000 spans.
- **SC-006**: A span with inputs exceeding 100KB is truncated, and `truncated=True` is recorded — verified by passing a 200KB input.
- **SC-007**: When a process crashes mid-span (simulated by raising an unhandled exception), the span is recorded with `ended=True` and non-null `error` — verified by wrapping a raised exception in a test.

## Assumptions

- The AI debugging agent reads trace_events directly via SQL queries — no visualization layer is needed.
- Trace spans are recorded synchronously within the same process; distributed tracing across process boundaries is deferred.
- The `contextvars` stack is sufficient for span nesting within a single coroutine or thread; Hermes Flow does not currently use thread pools or process pools that would require manual span propagation.
- The trace_events table is bound to a run's state.sqlite; cross-run queries require iterating multiple run directories.
- Trace overhead (sub-millisecond per span on modern hardware) is acceptable for an always-on feature targeting debugging, not high-throughput production serving.
- The debugger AI has direct file-system access to read state.sqlite; no HTTP API or gRPC endpoint is needed.
- The same run_id uniquely identifies a trace's home database; trace_id uniqueness across runs relies on UUID probability.
