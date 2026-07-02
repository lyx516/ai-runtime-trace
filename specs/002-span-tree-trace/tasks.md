# Tasks: Span Tree Trace

**Input**: Design documents from `/specs/002-span-tree-trace/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/trace-span-schema.yaml`, `quickstart.md`

**Tests**: Required. The spec defines independent tests for every user story. Write pytest tests before implementation and make each test fail for the expected reason before implementing the matching code.

**Organization**: Tasks are grouped by user story so a lower-capability LLM can implement one independently testable slice at a time.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable because it touches different files and does not depend on incomplete tasks in the same phase.
- **[Story]**: User story label. Only user-story phase tasks carry `[US1]`, `[US2]`, etc.
- Every task names exact file paths. Do not implement speculative files not listed here.

---

## Phase 1: Setup

**Purpose**: Ensure the test package and any new directories exist. Minimal — the `hermes_flow` package and test structure already exist from feature 001.

- [ ] T001 [P] Create test file `tests/hermes_flow/test_trace.py` with a pytest module docstring and no tests yet.

**Checkpoint**: `tests/hermes_flow/test_trace.py` exists and `python -m pytest tests/hermes_flow/` still passes all prior tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the Tracer core (trace.py), the trace_events SQLite table (storage.py), and the module-level tracer API. No user story work may start until these are complete.

**⚠️ CRITICAL**: Span write strategy is 1-write on `__exit__` + `atexit` flush (Clarify Q1). Trace write failure must be swallowed with `logging.warning` (Clarify Q2).

- [ ] T002 Define TraceSpan dataclass in `hermes_flow/trace.py` with fields matching data-model.md: `trace_id`, `span_id`, `parent_span_id`, `run_id`, `event_type`, `ts_start`, `ts_end`, `duration_ms`, `inputs`, `outputs`, `decisions`, `error`, `truncated`, `ended`. All JSON fields use `dict[str, Any]`. No enums needed — event_type is a plain string.
- [ ] T003 Implement `Tracer` abstract base with `span(event_type, inputs=None)` context manager in `hermes_flow/trace.py`. Must use `contextvars` for per-coroutine span stack.
- [ ] T004 Implement `NoOpTracer` in `hermes_flow/trace.py` that yields instantly without recording anything.
- [ ] T005 Implement `_truncate_field(value, max_bytes=100_000)` helper in `hermes_flow/trace.py` that truncates a dict/str to `max_bytes` and returns `(truncated_value, True)` if truncated.
- [ ] T006 Implement `SqliteTracer` in `hermes_flow/trace.py`. On `__enter__`: create in-memory TraceSpan with `_now()` as ts_start, push to contextvar stack, inherit `trace_id` and `parent_span_id` from parent span or generate fresh. On `__exit__` (both success and exception): compute `ts_end`/`duration_ms`, serialize to dict (use `to_dict` from schemas), truncate oversized fields, write single INSERT to `trace_events` via `RuntimeStore` connection. On exception: capture `error` (type, message, traceback). If INSERT fails: catch exception, `logging.warning("trace write failed: ...")`, do not re-raise. Register `atexit` handler that flushes any unclosed spans (span with `ended=False`).
- [ ] T007 Implement module-level `set_tracer(tracer)` and `get_tracer()` in `hermes_flow/trace.py`. Default value is `NoOpTracer()`. `get_tracer()` returns the current instance.
- [ ] T008 [P] Add `trace_events` table to `init_schema()` in `hermes_flow/storage.py` using the DDL from data-model.md (columns: trace_id, span_id PK, parent_span_id, run_id, event_type, ts_start, ts_end, duration_ms, inputs, outputs, decisions, error, truncated, ended). Include indexes on `trace_id`, `event_type`, and `(run_id, trace_id)`.
- [ ] T009 [P] Write tracer unit tests in `tests/hermes_flow/test_trace.py`: NoOpTracer does nothing, SqliteTracer writes one span, span has all required fields, `ts_end >= ts_start`, `duration_ms >= 0`.

**Checkpoint**: `python -m pytest tests/hermes_flow/test_trace.py` passes. The existing 38 tests in other files still pass.

---

## Phase 3: User Story 1 — Every execution step records a structured span (Priority: P1) 🎯 MVP

**Goal**: All ~15 production code paths wrap their body in `tracer.span()`, producing a valid span tree for any flow operation.

**Independent Test**: Run a minimal flow (init → validate → create_run) and confirm trace_events contains ≥5 spans with correct trace_id/span_id/parent_span_id forming a tree, each with non-empty event_type, inputs, outputs, and duration_ms.

### Tests for User Story 1

- [ ] T010 [P] [US1] Write span tree validity test in `tests/hermes_flow/test_trace.py` proving that a call to `flow_init` (via tools.py) with a valid flow produces at least 5 spans (root: flow_init, children: load_flow, validate_flow, create_run) with correct `parent_span_id` chain.
- [ ] T011 [P] [US1] Write nested span test in `tests/hermes_flow/test_trace.py` proving that a deeply nested call (e.g., flow_init → load_flow → inner_parse) produces correct parent_span_id at each level, up to at least 5 levels deep.
- [ ] T012 [P] [US1] Write span inputs/outputs test in `tests/hermes_flow/test_trace.py` proving that each span records the `inputs` dict on enter and `outputs`/`decisions` on exit with the correct values.
- [ ] T013 [P] [US1] Write trace isolation test in `tests/hermes_flow/test_trace.py` proving that two concurrent trace_ids (simulated by sequential calls) produce spans with different `trace_id` values and no cross-contamination.

### Implementation for User Story 1

- [ ] T014 [US1] Instrument `flow_init()` in `hermes_flow/tools.py`: wrap the function body in `tracer.span(event_type='flow_init', inputs={'flow_path': ..., 'project_root': ..., 'dry_run': ...})`. After creating the run, also call `set_tracer(SqliteTracer(store))`.
- [ ] T015 [US1] Instrument `load_flow_from_yaml()` in `hermes_flow/flow_loader.py`: wrap in `tracer.span(event_type='load_flow', inputs={'path': path})`. Record `outputs` with agent count, state count, flow_id.
- [ ] T016 [US1] Instrument `validate_flow()` in `hermes_flow/flow_loader.py`: wrap in `tracer.span(event_type='validate_flow')`. Record `outputs` with `valid` boolean and `error_count`. On `FlowValidationError`, the span catches it, records it in `error`, and re-raises.
- [ ] T017 [US1] Instrument `create_run()` in `hermes_flow/storage.py`: wrap in `tracer.span(event_type='create_run', inputs={'flow_id': ..., 'initial_state': ...})`. Record `outputs` with `run_id`.
- [ ] T018 [US1] Instrument `build_context_packet()` in `hermes_flow/context.py`: wrap in `tracer.span(event_type='build_context', inputs={'role_id': ..., 'state_id': ...})`. Record `outputs` with keys count.
- [ ] T019 [US1] Instrument `validate_artifact_write()` in `hermes_flow/context.py`: wrap in `tracer.span(event_type='validate_write', inputs={'role_id': ..., 'path': ...})`. Record `outputs` with `valid` boolean.
- [ ] T020 [US1] Instrument `WorkerAdapter.run_role_action()` in `hermes_flow/worker.py`: wrap in `tracer.span(event_type='worker_dispatch', inputs={'role_id': ..., 'profile_name': ...})`. Record `outputs` with exit code.
- [ ] T021 [US1] Instrument `record_decision()` in `hermes_flow/storage.py`: wrap in `tracer.span(event_type='record_decision', inputs={'role_id': ..., 'value': ...})`. Record `outputs` with `decision_id`.
- [ ] T022 [US1] Instrument `record_message_attempt()` in `hermes_flow/storage.py`: wrap in `tracer.span(event_type='record_message', inputs={'message_id': ..., 'from_role': ..., 'intended_recipients': ...})`. Record `outputs` with `delivery_outcome`.
- [ ] T023 [US1] Add span wrappers in `hermes_flow/routing.py` and `hermes_flow/engine.py` for `route_message`, `evaluate_gate`, `advance_state`, `loop_check`, `idle_check` — each wrapped in `tracer.span(event_type='<name>', inputs={...})` with relevant inputs captured. These files may not exist in their final form yet; wrap only the code paths that are already implemented.

**Checkpoint**: US1 is independently complete when the span tree test passes (T010) and `python -m pytest tests/hermes_flow/test_trace.py::test_span_tree_validity` passes with a real flow init call producing a valid span tree.

---

## Phase 4: User Story 2 — Trace events can be queried across sessions (Priority: P1)

**Goal**: Persisted trace events survive after the RuntimeStore closes and can be queried by `trace_id` or `event_type`.

**Independent Test**: Start a flow run, confirm trace events exist, close and reopen the RuntimeStore, query by trace_id, verify all spans from the original run are present with matching event types and timestamps.

### Tests for User Story 2

- [ ] T024 [P] [US2] Write get_trace query test in `tests/hermes_flow/test_storage.py` proving `RuntimeStore.get_trace(run_id, trace_id)` returns all spans for that trace_id in chronological order across a reopen cycle.
- [ ] T025 [P] [US2] Write get_traces_by_event query test in `tests/hermes_flow/test_storage.py` proving `get_traces_by_event(run_id, 'gate_evaluate')` returns only gate evaluation spans.
- [ ] T026 [P] [US2] Write trace_id isolation test in `tests/hermes_flow/test_storage.py` proving that with spans from 3 different trace_ids in the same run, `get_trace()` for each trace_id returns only its own spans with no mixing.

### Implementation for User Story 2

- [ ] T027 [US2] Implement `get_trace(run_id, trace_id)` in `hermes_flow/storage.py` on `RuntimeStore`: execute `SELECT * FROM trace_events WHERE run_id=? AND trace_id=? ORDER BY rowid`, return list of dicts.
- [ ] T028 [US2] Implement `get_traces_by_event(run_id, event_type)` in `hermes_flow/storage.py` on `RuntimeStore`: execute `SELECT * FROM trace_events WHERE run_id=? AND event_type=? ORDER BY ts_start`, return list of dicts.

**Checkpoint**: US2 is independently complete when query tests pass across a reopen cycle and trace_id isolation is verified.

---

## Phase 5: User Story 3 — Error spans include complete traceback (Priority: P2)

**Goal**: When a traced operation raises an exception, the span captures the full Python traceback, error type, error message, and the exact inputs that triggered the failure.

**Note**: The error capture mechanism is already implemented in SqliteTracer (T006). This phase focuses on test coverage and edge cases (truncation, atexit, concurrent errors).

### Tests for User Story 3

- [ ] T029 [P] [US3] Write error span test in `tests/hermes_flow/test_trace.py` proving that a traced function raising `FileNotFoundError` produces a span with `error.type='FileNotFoundError'`, `error.message` containing the path, and `error.traceback` containing the traceback.
- [ ] T030 [P] [US3] Write error span test for `FlowValidationError` in `tests/hermes_flow/test_trace.py` proving the span captures the error type and the validation error details in `inputs`.
- [ ] T031 [P] [US3] Write truncation test in `tests/hermes_flow/test_trace.py` proving that a span with inputs exceeding 100KB is truncated, `truncated=True` is set, and the field value is replaced with `"<truncated: N chars>"`.
- [ ] T032 [P] [US3] Write atexit flush test in `tests/hermes_flow/test_trace.py` proving that if the process exits via `sys.exit()` mid-span (simulated by raising SystemExit inside a span), the span is still written to trace_events (via atexit handler).

### Implementation for User Story 3

- [ ] T033 [US3] Verify atexit registration in `hermes_flow/trace.py`: the SqliteTracer constructor registers an `atexit` handler that calls `_flush_unclosed()`. This handler iterates any spans remaining on the contextvar stack, writes them with `ended=False`, and commits.
- [ ] T034 [US3] Ensure error traceback capture in `hermes_flow/trace.py` uses `traceback.format_exc()` to capture the full stack. If `sys.exc_info()` is empty (no active exception), do not record error — the span is a success.

**Checkpoint**: US3 is independently complete when all 4 error/truncation/atexit tests pass.

---

## Phase 6: User Story 4 — Trace is always-on with zero configuration (Priority: P2)

**Goal**: Tracing activates automatically whenever `flow_init()` creates a run, without any environment variables or CLI flags.

**Independent Test**: Start a flow run without setting any environment variables or trace flags, confirm trace_events table exists and is populated after init.

### Tests for User Story 4

- [ ] T035 [P] [US4] Write always-on test in `tests/hermes_flow/test_cli_quickstart.py` proving that a `flow_init` call without any tracing setup (no env vars, no flags) produces a non-empty trace_events table.
- [ ] T036 [P] [US4] Write flow_status trace test in `tests/hermes_flow/test_trace.py` proving that `flow_status()` (which uses `get_tracer()`) does not crash when no tracer is set (defaults to NoOpTracer).
- [ ] T037 [P] [US4] Write test reset test in `tests/hermes_flow/test_trace.py` proving that after `set_tracer(NoOpTracer())`, subsequent spans are no-op (trace_events stays empty).

### Implementation for User Story 4

- [ ] T038 [US4] Wire `flow_init()` in `hermes_flow/tools.py` to call `set_tracer(SqliteTracer(store))` after successfully creating a run. Also add `Tracer.__del__()` or explicit `close()` so the tracer's `atexit` handler doesn't hold a stale database reference.
- [ ] T039 [US4] Add `set_tracer(NoOpTracer())` call to test setup/teardown in `tests/hermes_flow/conftest.py` to ensure each test starts with a clean tracer state.

**Checkpoint**: US4 is independently complete when always-on test proves trace_events is populated without any configuration, and test reset test proves tracer state is properly isolated between tests.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, performance verification, and edge-case hardening. Do not add new product scope in this phase.

- [ ] T040 [P] Add contract schema loading test in `tests/hermes_flow/test_tool_contracts.py` that parses `contracts/trace-span-schema.yaml` and asserts TraceSpan has all required fields (trace_id, span_id, event_type, ts_start, ts_end, duration_ms, ended).
- [ ] T041 [P] Add performance smoke test in `tests/hermes_flow/test_trace.py` that creates 1000 spans and asserts total duration < 1 second (i.e., <1ms per span) and SQLite database growth < 1MB.
- [ ] T042 [P] Add concurrent trace isolation stress test in `tests/hermes_flow/test_trace.py` that generates 3 interleaved traces (using sequential calls with 3 fake trace_ids) and proves the trace_events table can be queried without cross-contamination.
- [ ] T043 Update `test_tool_contracts.py` to also verify that the `trace-span-schema.yaml` enum values for `event_type` match the one used in T014–T023, reporting any missing event types.
- [ ] T044 Run `python -m pytest tests/hermes_flow/` and record the command plus result in `specs/002-span-tree-trace/implementation-report.md`.
- [ ] T045 Run the quickstart SQL queries from `specs/002-span-tree-trace/quickstart.md` against a real trace file and record observed results in `specs/002-span-tree-trace/implementation-report.md`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user-story phases.
- **US1 (Phase 3)**: Depends on Foundational (tracer + trace_events table); this is the MVP.
- **US2 (Phase 4)**: Depends on US1 (spans must be recorded before they can be queried).
- **US3 (Phase 5)**: Depends on US1 (error capture is part of the tracer); tests can be written with US1 fixtures.
- **US4 (Phase 6)**: Depends on US1 (flow_init instrumentation must exist before wiring).
- **Polish (Phase 7)**: Depends on all user stories.

### Parallel Opportunities

- T008 and T009 can run in parallel after T002–T007 (different files: storage.py vs test_trace.py).
- T010–T013 (US1 tests) touch the same file (test_trace.py) — only T010 carries [P].
- T014–T023 (US1 implementation) touch different source files, several can run in parallel.
- T024–T026 (US2 tests) touch test_storage.py — only T024 carries [P]; T025, T026 are sequential.
- T029–T032 (US3 tests) touch test_trace.py — only T029 carries [P]; T030–T032 are sequential.
- T035–T037 (US4 tests) — T035 is [P] (test_cli_quickstart.py), T036/T037 share test_trace.py.

### Within Each User Story

- Write tests first and confirm they fail for the intended missing behavior.
- Implement instrumentation after tests are written.
- Keep each span wrapper minimal — capture inputs on enter, record outputs/decisions on exit.
- After a story checkpoint passes, do not refactor earlier story behavior unless tests remain green.

---

## Implementation Strategy

### MVP First (User Story 1)

1. Complete Phase 1 Setup (test file).
2. Complete Phase 2 Foundational (trace.py + trace_events table).
3. Complete Phase 3 US1 (instrumentation of all ~15 code paths).
4. Stop and validate US1 before adding query helpers or wiring.

### Incremental Delivery

1. **MVP A**: Setup + Foundational + US1 = Every step records a structured span.
2. **Query Increment**: US2 = query helpers for AI agents.
3. **Error Increment**: US3 = error capture tests and hardening.
4. **Wiring Increment**: US4 = always-on zero-config activation.
5. **Polish**: Performance smoke test, contract consistency, full pytest validation.

### Guidance for Cheap LLM Implementers

- Implement only the files named in the current task.
- Do NOT add new dependencies, external services, or storage backends.
- Do NOT change the SQLite schema of existing tables (only ADD the trace_events table).
- Do NOT wrap non-existent code paths — if `engine.py` or `routing.py` functions don't exist yet, skip those tasks and leave a comment.
- Keep span inputs concise (<10 keys each). Never capture full file contents or large binary data in `inputs`.
- When unsure, prefer recording nothing (no-op) over recording incorrect structured data.
- Use `hermes_flow.trace.get_tracer()` to access the tracer, never import a private instance.
