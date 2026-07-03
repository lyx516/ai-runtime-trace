# Tasks: Core FSM Implementation

**Input**: Design documents from `/specs/003-core-fsm-impl/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/engine-router-schemas.yaml`, `quickstart.md`

**Tests**: Required. The spec defines independent tests for each user story. Write pytest tests before implementation (TDD) and confirm they fail for the intended missing behavior before implementing.

**Organization**: Tasks are grouped by user story so a lower-capability LLM can implement one independently testable slice at a time.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable because it touches different files and does not depend on incomplete tasks in the same phase.
- **[Story]**: User story label. Only user-story phase tasks carry `[US1]`, `[US2]`, etc.
- Every task names exact file paths. Do not implement speculative files not listed here.

---

## Phase 1: Setup

**Purpose**: Ensure the test files exist. The `hermes_flow` package, test structure, and existing tools.py already exist from features 001 and 002.

- [X] T001 [P] Create test files `tests/hermes_flow/test_engine.py` and `tests/hermes_flow/test_routing.py` with pytest module docstrings and no tests yet.

**Checkpoint**: Both test files exist and `python -m pytest tests/hermes_flow/` passes all prior tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No blocking prerequisites — the RuntimeStore already provides all methods needed by engine and router (`load_decisions`, `record_transition`, `update_status`, `record_message_attempt`, `add_inbox_entries`, `append_audit_event`, `list_visible_messages`, `load_status`). This phase is empty. Proceed directly to user story phases.

**Checkpoint**: No code changes needed. Verify `python -m pytest tests/hermes_flow/` passes.

---

## Phase 3: User Story 1 — FSM Engine (Priority: P1) 🎯 MVP

**Goal**: Implement engine.py with `evaluate_gate()`, `detect_idle_timeout()`, and `advance_state()`. The engine is stateless — it reads decisions from RuntimeStore and writes transitions back.

**Key design decisions**:
- Round counter increments only on unsatisfied (on_fail/on_blocked) — never on_pass (Clarify Q1)
- Decisions filtered by `created_at > last_transition_into_state.created_at` — no round field on Decision needed
- `max_rounds=0` means unlimited (no exhaustion)
- flow_step does NOT auto-advance through gapless states (Clarify Q2)
- `evaluate_gate` on a gapless state returns `satisfied=False` with empty `next_state_id`

**Independent Test**: Create a run in a review state with 2 required roles. Record an approve decision for one role, confirm outstanding_roles contains the other. Record approve for the second, confirm gate satisfied and next_state_id set. Repeat with change-request and confirm on_fail target.

### Tests for User Story 1

- [X] T002 [P] [US1] Write gate satisfaction test in `tests/hermes_flow/test_engine.py` proving that when all required roles submit pass_values decisions, `evaluate_gate()` returns `satisfied=True` with the correct `next_state_id` from the gate's `on_pass`.
- [X] T003 [US1] Write gate fail test in `tests/hermes_flow/test_engine.py` proving that when any required role submits a fail_values decision, `evaluate_gate()` returns `satisfied=False` with `next_state_id` from `on_fail`. (Not [P] — shares file T002.)
- [X] T004 [US1] Write gate blocked test in `tests/hermes_flow/test_engine.py` proving that a blocked decision returns `next_state_id` from `on_blocked`. (Not [P] — shares file T002.)
- [X] T005 [US1] Write round counter exhaustion test in `tests/hermes_flow/test_engine.py` proving that after max_rounds unsatisfied evaluations, the engine returns `next_state_id` from `on_exhausted`. (Not [P] — shares file T002.)
- [X] T006 [US1] Write idle timeout test in `tests/hermes_flow/test_engine.py` proving that `detect_idle_timeout()` transitions to `on_exhausted` when elapsed time exceeds `idle_timeout_seconds`. (Not [P] — shares file T002.)
- [X] T007 [US1] Write non-active run gate rejection test in `tests/hermes_flow/test_engine.py` proving that `evaluate_gate()` raises or returns an error for runs with status `paused`, `completed`, or `aborted`. (Not [P] — shares file T002.)
- [X] T008 [US1] Write gapless state test in `tests/hermes_flow/test_engine.py` proving that `evaluate_gate()` for a state with no gate returns `satisfied=False` with empty `next_state_id`. (Not [P] — shares file T002.)
- [X] T009 [US1] Write advance_state test in `tests/hermes_flow/test_engine.py` proving that `advance_state()` updates `run.current_state_id`, persists a transition record, and appends an audit event. (Not [P] — shares file T002.)

### Implementation for User Story 1

- [X] T010 [P] [US1] Create `hermes_flow/engine.py` with engine functions (evaluate_gate, round counter, state transitions).
- [X] T011 [US1] Implement `detect_idle_timeout()` in `hermes_flow/engine.py`. (Not [P] — shares file T010.)
- [X] T012 [US1] Implement `advance_state()` in `hermes_flow/engine.py` with transition persistence, audit events, terminal detection. (Not [P] — shares file T010.)

**Checkpoint**: US1 is complete when all engine unit tests pass (T002–T009) and `python -m pytest tests/hermes_flow/test_engine.py` reports all passing.

---

## Phase 4: User Story 2 — Message Router (Priority: P1)

**Goal**: Implement routing.py with `validate_message()`. The router is a pure function — it reads routing policies from the FlowDefinition's state definition, checks each intended recipient against the policy and availability, and returns a RouteValidation result. It NEVER writes to storage (FR-013).

**Key design decisions**:
- Routing policy is per-state, per-sender: `routing_policies[sender_role]` → list of allowed recipient roles
- Recipient is `inbox-active` if: the recipient's current state has `message_acceptance=True` AND the recipient is not in a terminal state
- Unauthorized + unavailable both cause `valid=False` — the router reports both lists but still rejects the entire send (atomic zero-delivery, FR-010/FR-011)
- Empty `intended_recipients` → `valid=False, reason="no recipients specified"`
- All recipients authorized but all unavailable → `valid=False, reason="all recipients unavailable"`

**Independent Test**: Create a state with routing_policy allowing messaging from "planner" to ["developer", "reviewer"]. Send a message from "planner" to ["developer", "reviewer", "outsider"] — confirm `valid=False` with `invalid_recipients=["outsider"]`. Send to ["developer"] where developer is in a terminal state — confirm `valid=False` with `unavailable_recipients=["developer"]`. Send to ["developer"] where both authorized and available — confirm `valid=True`.

### Tests for User Story 2

- [X] T013 [P] [US2] Write router authorization rejection test in `tests/hermes_flow/test_routing.py` proving that a message intended for an unauthorized recipient returns `valid=False` with the unauthorized recipient in `invalid_recipients`.
- [X] T014 [US2] Write router availability rejection test in `tests/hermes_flow/test_routing.py` proving that a message intended for an inbox-inactive recipient returns `valid=False` with that recipient in `unavailable_recipients`. (Not [P] — shares file T013.)
- [X] T015 [US2] Write router acceptance test in `tests/hermes_flow/test_routing.py` proving that when all recipients are authorized and available, `valid=True` with no invalid/unavailable lists. (Not [P] — shares file T013.)
- [X] T016 [US2] Write router empty recipients test in `tests/hermes_flow/test_routing.py` proving that empty `intended_recipients` returns `valid=False` with an appropriate reason. (Not [P] — shares file T013.)
- [X] T017 [US2] Write router mixed rejection test in `tests/hermes_flow/test_routing.py` proving that a message with both unauthorized AND unavailable recipients is rejected with both lists populated. (Not [P] — shares file T013.)
- [X] T018 [US2] Write router no-store-mutation test in `tests/hermes_flow/test_routing.py` proving that `validate_message()` never calls any write method on the store (uses a mock). (Not [P] — shares file T013.)

### Implementation for User Story 2

- [X] T019 [US2] Create `hermes_flow/routing.py` with `validate_message()` — pure validation, no store writes, returns RouteValidation with authorization + availability checks.

**Checkpoint**: US2 is complete when all router unit tests pass (T013–T018) and `python -m pytest tests/hermes_flow/test_routing.py` reports all passing.

---

## Phase 5: User Story 3 — Tool Handlers (Priority: P2)

**Goal**: Implement 7 tool handler stubs in `hermes_flow/tools.py`. Each handler wraps a flow operation, delegates to engine/router/storage as needed, wraps logic in `tracer.span()` (FR-021), and returns structured dicts matching the OpenAPI contracts from feature 001.

**Key design decisions**:
- Handlers are thin orchestration layers — they delegate to engine, router, or storage methods
- flow_step: call evaluate_gate → if transition needed → call advance_state → return result
- flow_send: call router validate_message → if valid → call record_message_attempt + add_inbox_entries → return outcome
- flow_decide: call record_decision → append audit → return decision_id
- flow_status: call store.load_status → return structured status dict
- flow_pause/resume/abort: call store.update_status → append audit → return result
- All handlers check run status before operating (reject non-active runs)
- All handlers wrap core logic in `tracer.span()` with the event_type matching the function name

**Independent Test**: Start a flow via flow_init. Call flow_status → confirm returns correct state_id. Call flow_send with valid recipients → confirm delivered. Call flow_decide → confirm decision recorded. Call flow_step → confirm gate evaluated. Call flow_pause → confirm status changed. Call flow_resume → confirm status active. Call flow_abort → confirm status aborted.

### Tests for User Story 3

- [X] T020 [P] [US3] Write flow_status test in `tests/hermes_flow/test_tools.py` proving that `flow_status()` returns run_id, current_state_id, agent_bindings, and pending_gate structure matching the OpenAPI contract from feature 001.
- [X] T021 [US3] Write flow_step test in `tests/hermes_flow/test_tools.py` proving that `flow_step()` processes decisions and advances state when gate is satisfied. (Not [P] — shares file T020.)
- [X] T022 [US3] Write flow_send test in `tests/hermes_flow/test_tools.py` proving that `flow_send()` with valid recipients creates a message record and inbox entries. (Not [P] — shares file T020.)
- [X] T023 [US3] Write flow_send rejection test in `tests/hermes_flow/test_tools.py` proving that `flow_send()` with invalid recipients returns a rejected delivery outcome with zero inbox entries. (Not [P] — shares file T020.)
- [X] T024 [US3] Write flow_decide test in `tests/hermes_flow/test_tools.py` proving that `flow_decide()` persists a decision and appends an audit event. (Not [P] — shares file T020.)
- [X] T025 [US3] Write flow_pause test in `tests/hermes_flow/test_tools.py` proving that `flow_pause()` changes run status to `paused` and subsequent step/send/decide calls raise an error. (Not [P] — shares file T020.)
- [X] T026 [US3] Write flow_resume test in `tests/hermes_flow/test_tools.py` proving that `flow_resume()` restores run status to `active`. (Not [P] — shares file T020.)
- [X] T027 [US3] Write flow_abort test in `tests/hermes_flow/test_tools.py` proving that `flow_abort()` changes run status to `aborted` and all future operations fail. (Not [P] — shares file T020.)
- [X] T028 [US3] Write idempotent lifecycle test in `tests/hermes_flow/test_tools.py` proving that pause/pause, abort/abort, and resume/active are idempotent (return success without error). (Not [P] — shares file T020.)

### Implementation for User Story 3

- [X] T029 [US3] Implement `flow_status()` in `hermes_flow/tools.py`.
- [X] T030 [US3] Implement `flow_step()` in `hermes_flow/tools.py` with gate evaluation and idle timeout.
- [X] T031 [US3] Implement `flow_send()` in `hermes_flow/tools.py` with router validation and inbox delivery.
- [X] T032 [US3] Implement `flow_decide()` in `hermes_flow/tools.py` with decision persistence and audit.
- [X] T033 [US3] Implement `flow_pause()` in `hermes_flow/tools.py`.
- [X] T034 [US3] Implement `flow_resume()` in `hermes_flow/tools.py`.
- [X] T035 [US3] Implement `flow_abort()` in `hermes_flow/tools.py`.

**Checkpoint**: US3 is complete when all tool handler tests pass (T020–T028) and `python -m pytest tests/hermes_flow/test_tools.py` reports all passing.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Contract verification, integration tests, performance smoke tests, and documentation.

- [ ] T036 [P] Add contract schema loading test in `tests/hermes_flow/test_tool_contracts.py` (or extend existing) that parses `contracts/engine-router-schemas.yaml` and asserts `GateResult` and `RouteValidation` contain all required fields matching the data model.
- [ ] T037 [P] Write end-to-end integration test in `tests/hermes_flow/test_tools.py` proving a complete flow lifecycle: init → status → send → decide → step → status → pause → resume → step → status reaches a terminal state, with trace_events populated.
- [ ] T038 [P] Write performance smoke test in `tests/hermes_flow/test_engine.py` that runs `evaluate_gate` with 10 required roles and 100 existing decisions, asserting completion under 100ms.
- [ ] T039 Update `test_tool_contracts.py` to verify that the `event_type` values used in tracer.span() for all 7 tool handlers match the expected naming convention.
- [ ] T040 Run `python -m pytest tests/hermes_flow/` and record the command plus result in `specs/003-core-fsm-impl/implementation-report.md`.
- [ ] T041 Run the quickstart SQL queries and code examples from `quickstart.md` against a real trace file and record observed results in `specs/003-core-fsm-impl/implementation-report.md`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Empty — no blocking prerequisites.
- **US1 (Phase 3)**: Depends on Setup; this is the MVP.
- **US2 (Phase 4)**: Independent of US1 (router doesn't call engine); can run in parallel with US1 at the implementer's discretion.
- **US3 (Phase 5)**: Depends on US1 (flow_step calls evaluate_gate) AND US2 (flow_send calls validate_message).
- **Polish (Phase 6)**: Depends on all user stories.

### Parallel Opportunities

- T001 [P] — only Phase 1 task, no conflicts.
- T002 [P] is the first US1 test; T003–T009 share the same file (test_engine.py) — sequential.
- T013 [P] is the first US2 test; T014–T018 share the same file (test_routing.py) — sequential.
- T020 [P] is the first US3 test; T021–T028 share the same file (test_tools.py) — sequential.
- T010 [P] (engine.py) can be written in parallel with T019 [P] (routing.py) since they are independent modules.
- T036–T038 are independent [P] and can run in parallel.

### Within Each User Story

- Write tests first and confirm they fail for the intended missing behavior.
- Implement the module after tests are written.
- Keep each implementation minimal — the engine/router/tool-handler are thin orchestrators.
- After a story checkpoint passes, do not refactor earlier story behavior unless tests remain green.

---

## Implementation Strategy

### MVP First (User Story 1)

1. Complete Phase 1 Setup (test files).
2. Complete Phase 3 US1 (engine.py + tests) — this is the MVP.
3. Complete Phase 4 US2 (routing.py + tests) — independent of US1, can be parallel.
4. Complete Phase 5 US3 (tools.py + tests) — depends on US1 + US2.
5. Complete Phase 6 Polish (integration, contracts, performance).

### Incremental Delivery

1. **MVP**: engine.py — gate eval + idle timeout + advance state
2. **Router**: routing.py — recipient validation + atomic zero-delivery
3. **Tools**: 7 tool handlers — status/step/send/decide/pause/resume/abort
4. **Polish**: End-to-end lifecycle test, contract verification, performance

### Guidance for Cheap LLM Implementers

- Implement only the files named in the current task.
- Do NOT add new dependencies, external services, or storage backends.
- Do NOT change the SQLite schema or add new tables — all needed storage methods already exist.
- The existing `RuntimeStore` in `hermes_flow/storage.py` provides: `load_decisions`, `record_transition`, `update_status`, `record_message_attempt`, `add_inbox_entries`, `append_audit_event`, `list_visible_messages`, `load_status`, `resume_run`.
- Use `hermes_flow.trace.get_tracer()` for tracer.span() calls — never import a private instance.
- When in doubt about a field name or schema, check `hermes_flow/schemas.py` — it's the authoritative definition.
