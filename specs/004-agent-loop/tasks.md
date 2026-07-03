# Tasks: Agent Loop — 事件驱动执行层

**Input**: Design documents from `/specs/004-agent-loop/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/agent-context-schema.yaml, quickstart.md

**Tests**: The spec defines acceptance scenarios for each user story. Test tasks are included — write tests before implementation (TDD) and confirm they fail for the intended missing behavior before implementing.

**Organization**: Tasks are grouped by user story so a lower-capability LLM can implement one independently testable slice at a time.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable because it touches different files and does not depend on incomplete tasks in the same phase.
- **[Story]**: User story label. Only user-story phase tasks carry `[US1]`, `[US2]`, etc.
- Every task names exact file paths. Do not implement speculative files not listed here.

---

## Phase 1: Setup

**Purpose**: Create test files. The `hermes_flow` package already exists from features 001-003.

- [X] T001 [P] Create test files `tests/hermes_flow/test_agent_tools.py`, `tests/hermes_flow/test_runtime_loop.py`, and `tests/hermes_flow/test_agent_session.py` with pytest module docstrings and no tests yet.

**Checkpoint**: All 3 test files exist and `python -m pytest tests/hermes_flow/` passes all prior tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No blocking prerequisites — the RuntimeStore already provides all methods needed (`load_status`, `load_decisions`, `record_decision`, `record_message_attempt`, `add_inbox_entries`, `list_inbox_entries`, `append_audit_event`, `record_transition`, `update_status`). This phase is empty. Proceed directly to user story phases.

**Checkpoint**: No code changes needed. Verify `python -m pytest tests/hermes_flow/` passes.

---

## Phase 3: User Story 1 — Agent-Facing Tools (Priority: P1) 🎯 MVP

**Goal**: Provide `agent_inbox_read`, `agent_message_send`, `agent_submit_decision`, `agent_query_status` — Python functions that a subagent can call via `python -c` from its terminal tool. Each wraps the corresponding flow tool from `hermes_flow/tools.py`.

**Key design decisions**:
- Functions accept `run_id` and `role_id` explicitly (the subagent knows these from its context packet)
- `agent_message_send` calls `flow_send` with the agent's role_id as `from_role`
- `agent_submit_decision` calls `flow_decide` with the agent's role_id
- `agent_inbox_read` reads from the store's `inboxes` table and loads matching `MessageEnvelope` records
- All functions wrap logic in `tracer.span()` per FR-004

**Independent Test**: Start a flow via flow_init directly. Use a Python script to call `agent_message_send` and verify the message appears in the target inbox. Call `agent_submit_decision` and verify the decision is recorded. Call `agent_inbox_read` and verify it returns the correct messages.

### Implementation for User Story 1

- [X] T002 [P] [US1] Create `hermes_flow/agent_tools.py` with `agent_inbox_read(run_id, role_id)` that queries inboxes and returns list of `MessageEnvelope` dicts.
- [X] T003 [US1] Implement `agent_message_send(run_id, role_id, state_id, intended_recipients, kind, content)` in `hermes_flow/agent_tools.py` that wraps `flow_send` from `hermes_flow/tools.py`. (Not [P] — shares file T002.)
- [X] T004 [US1] Implement `agent_submit_decision(run_id, role_id, state_id, value, reason)` in `hermes_flow/agent_tools.py` that wraps `flow_decide` from `hermes_flow/tools.py`. (Not [P] — shares file T002.)
- [X] T005 [US1] Implement `agent_query_status(run_id)` in `hermes_flow/agent_tools.py` that wraps `flow_status`. (Not [P] — shares file T002.)

**Checkpoint**: US1 is complete when all 4 tool functions can be called with correct input and produce expected output. Manual verification: `python -c "from hermes_flow.agent_tools import agent_inbox_read; print(agent_inbox_read(run_id='test', role_id='reviewer'))"` runs without import error.

---

## Phase 4: User Story 2 — Runtime Loop (Priority: P1)

**Goal**: Implement `runtime_loop.py` with `RuntimeLoop` class that runs a tick loop:
1. Check inbox → schedule agent sessions
2. Collect completed session results
3. Evaluate gate → advance state
4. Check idle timeout

**Key design decisions**:
- Loop is per-run (one `RuntimeLoop` instance per run_id)
- Tick interval is 1 second (configurable via constructor)
- Agent sessions are NOT spawned by the loop itself — the loop writes a context packet file and a "pending action" marker. A separate Hermes mechanism (delegate_task) picks up the marker. The loop collects results from result files.
- Gate evaluation uses the existing `evaluate_gate` from `engine.py`
- State advancement uses the existing `advance_state` from `engine.py`
- Idle timeout uses the existing `detect_idle_timeout` from `engine.py`

**Independent Test**: Create a run with two required roles. Manually inject decisions via the store. Start the loop (with session spawning mocked out) and verify that within 5 ticks the gate is evaluated and the state advances.

### Implementation for User Story 2

- [X] T006 [P] [US2] Create `hermes_flow/runtime_loop.py` with `RuntimeLoop` class skeleton: constructor, `start()`, `stop()`, and `_tick()` method.
- [X] T007 [US2] Implement inbox dispatch in `RuntimeLoop._tick()` (in `hermes_flow/runtime_loop.py`): check each actor role for unread inbox entries and write context packet files for roles needing sessions. (Not [P] — shares file T006.)
- [X] T008 [US2] Implement session result collection in `RuntimeLoop._tick()` (in `hermes_flow/runtime_loop.py`): poll for result files, parse actions, call `flow_decide` for submit_decision actions. (Not [P] — shares file T006.)
- [X] T009 [US2] Implement automatic gate evaluation in `RuntimeLoop._tick()` (in `hermes_flow/runtime_loop.py`): if all required roles have submitted decisions since last transition, call `evaluate_gate` and `advance_state`. (Not [P] — shares file T006.)
- [X] T010 [US2] Implement idle timeout check in `RuntimeLoop._tick()` (in `hermes_flow/runtime_loop.py`): call `detect_idle_timeout` and advance if exceeded. (Not [P] — shares file T006.)

**Checkpoint**: US2 is complete when `python -c "from hermes_flow.runtime_loop import RuntimeLoop; loop = RuntimeLoop(run_id='test', store=store); loop.start()"` runs and processes ticks until the run reaches a terminal state.

---

## Phase 5: User Story 3 — Agent Session Management & Multi-Round Discussion (Priority: P2)

**Goal**: Implement `agent_session.py` with:
- `prepare_context(run_id, role_id, store)` — builds AgentContextPacket from store data
- `spawn_session(context_packet, goal_strategy)` — writes context file + creates pending action
- `parse_result(session_id)` — reads and validates session result file
- Integration: full multi-round discussion loop (message → respond → change request → revise → approve)

**Key design decisions**:
- Context packet is serialized to JSON following `contracts/agent-context-schema.yaml`
- Context includes: soul, state_description, inbox_messages, visible_artifacts, pending_decisions, discussion_history
- Session result is a JSON file matching `SessionResult` schema from data-model.md
- The loop calls `prepare_context` before writing each session's context file
- After collecting a result with `submit_decision`, the loop calls gate evaluation (US2) which may route to on_fail (revision) or advance
- Multi-round discussion is naturally supported: after a state transition (or revision loop), the next state's agent receives a fresh context with updated inbox and discussion_history

**Independent Test**: Create a flow with REVIEW state (gate requires reviewer). Prepare a context for the reviewer with an inbox message from architect requesting a design review. Simulate the reviewer's response (message_send to architect + submit_decision APPROVE). Verify the discussion_history captures both messages and the gate evaluates correctly.

### Implementation for User Story 3

- [X] T011 [P] [US3] Implement `prepare_context(run_id, role_id, store)` in `hermes_flow/agent_session.py` that reads inbox, artifacts, decisions, and builds an `AgentContextPacket` dict matching the schema.
- [X] T012 [US3] Implement context file writer in `hermes_flow/agent_session.py` that serializes the context packet to JSON and writes to `.hermes-flow/runs/<run_id>/sessions/<session_id>.context.json`. (Not [P] — shares file T011.)
- [X] T013 [US3] Implement `parse_result(session_id, run_dir)` in `hermes_flow/agent_session.py` that reads and validates the session result JSON file. (Not [P] — shares file T011.)
- [X] T014 [US3] Integrate session spawning with `RuntimeLoop` from US2: when a role needs a session, call `prepare_context`, write the file, and set up the pending action marker. (Modifies `hermes_flow/runtime_loop.py`.)

**Checkpoint**: US3 is complete when a full multi-round discussion can be driven through the Runtime Loop: architect sends message → loop schedules reviewer → reviewer reads inbox, sends feedback, submits decision → loop evaluates gate and routes correctly.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end integration, contract verification, and documentation.

- [X] T015 [P] Write end-to-end integration test in `tests/hermes_flow/test_runtime_loop.py` (or a standalone script) that creates a flow run, starts the Runtime Loop, simulates an agent session (by writing a result file), and verifies the loop detects the result and advances the state.
- [X] T016 [P] Write context packet schema validation test that creates an `AgentContextPacket` dict and validates it against the schema in `specs/004-agent-loop/contracts/agent-context-schema.yaml` (parse the YAML and check all required fields are present).
- [X] T017 Run `python -m pytest tests/hermes_flow/` and record the command plus result in `specs/004-agent-loop/implementation-report.md`.
- [ ] T018 Run the quickstart Python and SQL examples from `quickstart.md` against a real flow run and record observed results in `specs/004-agent-loop/implementation-report.md`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Empty — no blocking prerequisites.
- **US1 (Phase 3)**: Depends on Setup; no dependencies on features 001-003 (agent_tools.py only wraps tools that already exist).
- **US2 (Phase 4)**: Depends on Setup; does NOT depend on US1 (runtime_loop.py can use store directly; agent session spawning is a future integration).
- **US3 (Phase 5)**: Depends on US2 (session management integrates with the loop) AND US1 (agent_tools.py functions are what the subagent calls).
- **Polish (Phase 6)**: Depends on all user stories.

### Parallel Opportunities

- T001 [P] — Setup task; creates 3 test files, no conflicts.
- T002 [P] is the first US1 task; T003–T005 share the same file (agent_tools.py) — sequential.
- T006 [P] is the first US2 task; T007–T010 share the same file (runtime_loop.py) — sequential.
- T011 [P] is the first US3 task; T012–T013 share the same file (agent_session.py) — sequential. T014 modifies runtime_loop.py and depends on T011–T013.
- T015–T016 are independent [P] tasks.

### Within Each User Story

- Implement the module after any test files are created.
- Keep each implementation minimal — these are thin orchestrators.
- After a story checkpoint passes, do not refactor earlier story behavior unless tests remain green.

---

## Implementation Strategy

### MVP First (User Story 1 + 2)

1. Complete Phase 1 Setup (test files).
2. Complete Phase 3 US1 (agent_tools.py) — agent-facing tools MVP.
3. Complete Phase 4 US2 (runtime_loop.py) — runtime loop MVP (with mocked session spawning).
4. Complete Phase 5 US3 (agent_session.py + integration) — full multi-round discussion.
5. Complete Phase 6 Polish (integration tests, contract validation).

### Incremental Delivery

1. **MVP**: agent_tools.py — 4 agent-facing tool wrappers.
2. **Runtime Loop**: runtime_loop.py — automatic inbox dispatch, gate evaluation, idle timeout.
3. **Session Mgmt**: agent_session.py — context packet, session spawning, result parsing.
4. **Integration**: Full multi-round discussion loop through the Runtime Loop.

### Guidance for Implementer

- Implement only the files named in the current task.
- Do NOT add new dependencies, external services, or storage backends.
- Do NOT change the SQLite schema or add new tables — all needed storage methods already exist.
- The existing `RuntimeStore` in `hermes_flow/storage.py` provides all needed query methods.
- Use `hermes_flow.trace.get_tracer()` for tracer.span() calls — never import a private instance.
- When in doubt about a field name or schema, check `hermes_flow/schemas.py` — it's the authoritative definition.
- For agent session spawning: the loop does NOT call delegate_task directly (that's a Hermes tool, not a Python function). Instead, it writes a context file and leaves a pending-action marker. The integration with Hermes delegate_task is an external wiring concern.
