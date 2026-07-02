# Tasks: Hermes Flow FSM Agent Loop

**Input**: Design documents from `/specs/001-hermes-flow-fsm/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/flow-tools.openapi.yaml`, `quickstart.md`

**Tests**: Required. The spec defines independent tests for every user story and validation requirements TV-001..TV-006; write the listed pytest tests before implementation and make each test fail for the expected reason before implementing the matching code.

**Organization**: Tasks are grouped by user story so a lower-capability LLM can implement one independently testable slice at a time.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable because it touches different files and does not depend on incomplete tasks in the same phase.
- **[Story]**: User story label. Only user-story phase tasks carry `[US1]`, `[US2]`, etc.
- Every task names exact file paths. Do not implement speculative files not listed here.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the package, plugin adapter, test, and example directories exactly as the plan expects. Keep this phase mechanical; do not implement business logic here.

- [X] T001 Create package skeleton files `hermes_flow/__init__.py`, `hermes_flow/schemas.py`, `hermes_flow/errors.py`, `hermes_flow/flow_loader.py`, `hermes_flow/storage.py`, `hermes_flow/engine.py`, `hermes_flow/routing.py`, `hermes_flow/context.py`, `hermes_flow/worker.py`, `hermes_flow/tools.py`, and `hermes_flow/cli.py` with module docstrings only.
- [X] T002 Create plugin adapter skeleton files `plugins/hermes-flow/plugin.yaml` and `plugins/hermes-flow/__init__.py` that declare the Hermes Flow plugin name and leave tool registration implementation for later tasks.
- [X] T003 [P] Create test package files `tests/hermes_flow/__init__.py`, `tests/hermes_flow/conftest.py`, `tests/hermes_flow/test_flow_loader.py`, `tests/hermes_flow/test_storage.py`, `tests/hermes_flow/test_routing.py`, `tests/hermes_flow/test_engine_gates.py`, `tests/hermes_flow/test_context_projection.py`, `tests/hermes_flow/test_tool_contracts.py`, `tests/hermes_flow/test_worker_adapter.py`, and `tests/hermes_flow/test_cli_quickstart.py` with empty pytest module docstrings.
- [X] T004 [P] Create example directories and placeholder files `.hermes-flow/flows/.gitkeep`, `examples/hermes-flow/simple-plan-review.yaml`, and `examples/hermes-flow/README.md` without adding runtime data under `.hermes-flow/runs/`.
- [X] T005 [P] Create developer validation helper `scripts/verify_hermes_flow_contracts.py` that loads `specs/001-hermes-flow-fsm/contracts/flow-tools.openapi.yaml` and checks it parses as YAML.
- [X] T006 Add minimal project metadata in `pyproject.toml`: project name `hermes-flow-fsm`, `requires-python = ">=3.11"`, runtime dependency `PyYAML`, and `[tool.pytest.ini_options]` with `testpaths = ["tests/hermes_flow"]`. Do NOT add optional frameworks or test-only dependencies beyond `pytest` itself. The implementer MUST read the actual repo root — there is NO existing `pyproject.toml` — so this task creates the file from scratch.

**Checkpoint**: Package paths exist, but importing `hermes_flow` does not yet perform IO, spawn workers, or create runtime state.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement shared entities, persistence, errors, and contract fixtures that all user stories require. No user story work may start until these are complete.

**⚠️ CRITICAL**: The project-local runtime is the source of truth. Do not store business state only in Hermes worker profiles or sessions.

- [X] T007 Define domain enums and constants in `hermes_flow/schemas.py`: `RunStatus`, `MemoryMode`, `DeliveryOutcome`, `DecisionValue`, `GateType`, `MessageKind`, and `Visibility`, using exact values from `data-model.md` and `flow-tools.openapi.yaml`.
- [X] T008 Define dataclasses in `hermes_flow/schemas.py` for `FlowDefinition`, `AgentRole`, `State`, `Transition`, `Gate`, `FlowRun`, `MessageEnvelope`, `Inbox`, `Artifact`, `Decision`, and `AgentBinding` with fields matching `specs/001-hermes-flow-fsm/data-model.md`. Include `idle_timeout_seconds: Optional[int] = None` on `State` for required-response / idle budget timeout enforcement.
- [X] T008a [P] Add domain-level constants for idle budget validation in `hermes_flow/schemas.py`: `IDLE_BUDGET_UNLIMITED = -1` and default values for `loop_defaults.idle_timeout` parsed from flow definition.
- [X] T009 Add pure serialization helpers `to_dict()` and `from_dict()` for every dataclass in `hermes_flow/schemas.py`, preserving snake_case field names used by `contracts/flow-tools.openapi.yaml`.
- [X] T010 [P] Implement typed exception classes in `hermes_flow/errors.py`: `FlowValidationError`, `RuntimeStateError`, `RoutingError`, `GateEvaluationError`, `ContextPolicyError`, and `WorkerExecutionError`, each carrying a human-readable `message` and optional `details` list.
- [X] T011 [P] Add reusable pytest fixtures in `tests/hermes_flow/conftest.py` for `tmp_project_root`, `sample_flow_yaml_path`, `invalid_flow_yaml_path`, and `sample_run_id`, ensuring fixtures never write outside pytest temporary directories.
- [X] T012 [P] Add contract schema loading tests in `tests/hermes_flow/test_tool_contracts.py` that parse `specs/001-hermes-flow-fsm/contracts/flow-tools.openapi.yaml` and assert operationIds `flow_init`, `flow_status`, `flow_step`, `flow_send`, `flow_decide`, `flow_pause`, `flow_resume`, and `flow_abort` exist.
- [X] T013 Implement SQLite schema creation in `hermes_flow/storage.py` for tables `runs`, `agents`, `states`, `messages`, `inboxes`, `artifacts`, `decisions`, `transitions`, and `audit_events` under `.hermes-flow/runs/<run_id>/state.sqlite`.
- [X] T014 Implement atomic transaction helper `RuntimeStore.transaction()` in `hermes_flow/storage.py` so state transition, message delivery/rejection, inbox updates, and audit writes can commit or roll back together.
- [X] T015 Implement append-only audit helper `RuntimeStore.append_audit_event()` in `hermes_flow/storage.py` recording `event_id`, `run_id`, `state_id`, `event_type`, `actor`, `payload_json`, and `created_at`.
- [X] T016 Add storage tests in `tests/hermes_flow/test_storage.py` proving runtime initialization creates `.hermes-flow/runs/<run_id>/state.sqlite`, creates all required tables, and records an initial audit event.
- [X] T017 Add storage rollback test in `tests/hermes_flow/test_storage.py` proving a raised exception inside `RuntimeStore.transaction()` leaves no partial message, inbox, decision, or audit writes.
- [X] T018 Implement common JSON response helpers in `hermes_flow/tools.py` for success and error results with keys `ok`, `error`, `details`, and `audit_event_id` to keep all tool outputs readable and contract-like.
- [X] T019 Implement CLI argument parser skeleton in `hermes_flow/cli.py` for subcommands `init`, `status`, `step`, `send`, `decide`, `pause`, `resume`, `abort`, and `audit`, with each subcommand returning a non-zero exit and clear message until its story implementation is complete.

**Checkpoint**: Shared schemas, errors, storage, audit, contract parsing, and CLI skeleton exist. Run `python -m pytest tests/hermes_flow/test_storage.py tests/hermes_flow/test_tool_contracts.py` before starting user story tasks.

---

## Phase 3: User Story 1 - Define a bounded multi-agent flow (Priority: P1) 🎯 MVP

**Goal**: A user can define a reviewable flow, validate it before execution, initialize a durable project-local run, and see initial state, agents, expected artifacts, and next action.

**Independent Test**: Provide valid and invalid flow definitions; valid flow initializes a run, invalid flows report all blocking issues before any agent action starts.

### Tests for User Story 1

- [ ] T020 [P] [US1] Write valid-flow loader test in `tests/hermes_flow/test_flow_loader.py` asserting `examples/hermes-flow/simple-plan-review.yaml` loads into `FlowDefinition` with agents `planner` and `reviewer`, initial state `PLAN`, terminal states `DONE` and `ABORT`, and gate max rounds `3`.
- [ ] T021 [US1] Write invalid-flow validation tests in `tests/hermes_flow/test_flow_loader.py` for missing agent role, missing terminal state, unreachable state, invalid transition target, and revision loop without max rounds or escalation path. (Not [P] — shares file with T020.)
- [ ] T022 [P] [US1] Write init tool contract test in `tests/hermes_flow/test_tool_contracts.py` asserting `flow_init(project_root, flow_path, dry_run=True)` returns `ok`, `validation_errors`, and never creates `.hermes-flow/runs/` when validation fails.
- [X] T020 [P] [US1] Write valid-flow loader test in `tests/hermes_flow/test_flow_loader.py` asserting `examples/hermes-flow/simple-plan-review.yaml` loads into `FlowDefinition` with agents `planner` and `reviewer`, initial state `PLAN`, terminal states `DONE` and `ABORT`, and gate max rounds `3`.
- [X] T021 [US1] Write invalid-flow validation tests in `tests/hermes_flow/test_flow_loader.py` for missing agent role, missing terminal state, unreachable state, invalid transition target, and revision loop without max rounds or escalation path. (Not [P] — shares file with T020.)
- [X] T022 [P] [US1] Write init tool contract test in `tests/hermes_flow/test_tool_contracts.py` asserting `flow_init(project_root, flow_path, dry_run=True)` returns `ok`, `validation_errors`, and never creates `.hermes-flow/runs/` when validation fails.
- [X] T023 [P] [US1] Write CLI init integration test in `tests/hermes_flow/test_cli_quickstart.py` invoking `python -m hermes_flow.cli init --flow <sample> --project-root <tmp>` and expecting JSON with `run_id`, `current_state_id=PLAN`, `artifact_root`, and agent bindings.
- [X] T024 [US1] Implement YAML parsing in `hermes_flow/flow_loader.py` that reads project-local flow files into `FlowDefinition` and rejects unknown top-level fields with `FlowValidationError`.
- [X] T025 [US1] Implement flow validation in `hermes_flow/flow_loader.py` for missing agents, missing initial state, missing terminal state, unreachable states, invalid transition targets, invalid gate target states, unsupported routing groups, unbounded loops, and **states with `idle_timeout_seconds` that lack `on_exhausted`**.
- [X] T026 [US1] Implement sample flow content in `examples/hermes-flow/simple-plan-review.yaml` matching `quickstart.md` exactly, including `PLAN`, `REVIEW`, `HUMAN_ESCALATION`, `DONE`, and `ABORT` states.
- [X] T027 [US1] Implement `RuntimeStore.create_run()` in `hermes_flow/storage.py` to create a new run directory, initialize `state.sqlite`, persist `FlowRun`, states, agent bindings, memory modes, and initial audit event.
- [X] T028 [US1] Implement `flow_init()` in `hermes_flow/tools.py` to load and validate a flow, support `dry_run`, create a runtime only on valid non-dry-run input, and return `FlowInitResult` fields from the OpenAPI contract.
- [X] T029 [US1] Wire `python -m hermes_flow.cli init` in `hermes_flow/cli.py` to call `flow_init()`, print JSON to stdout, and exit non-zero only on invalid flow or IO failure.
- [X] T030 [US1] Add plain-language validation error formatting in `hermes_flow/flow_loader.py` so every rejected invalid flow reports all blocking issues in one response, not just the first error.

**Checkpoint**: US1 is independently complete when `pytest tests/hermes_flow/test_flow_loader.py tests/hermes_flow/test_tool_contracts.py::test_flow_init* tests/hermes_flow/test_cli_quickstart.py::test_cli_init*` passes and `python -m hermes_flow.cli init --flow examples/hermes-flow/simple-plan-review.yaml --project-root <tmp>` creates a run.

---

## Phase 4: User Story 2 - Run isolated agents with role-specific context (Priority: P1)

**Goal**: Each agent role executes through a full Hermes worker session/profile identity and receives only the role-specific context, inbox entries, artifacts, output obligations, and explicit memory mode configured for the run.

**Independent Test**: Create two roles with different permissions and verify their generated context packets differ exactly according to `read_scope`, `write_scope`, `toolsets`, `skills`, and `memory_mode`.

### Tests for User Story 2

- [ ] T031 [P] [US2] Write context projection test in `tests/hermes_flow/test_context_projection.py` proving planner and reviewer context packets contain different `role_id`, `soul`, `skills`, `toolsets`, `read_scope`, `write_scope`, and state objective.
- [ ] T032 [P] [US2] Write context isolation test in `tests/hermes_flow/test_context_projection.py` proving artifacts outside an agent `read_scope` and messages outside its inbox are absent from the generated context packet.
- [ ] T033 [P] [US2] Write memory mode test in `tests/hermes_flow/test_context_projection.py` proving default `run_isolated` roles do not receive prior-run inboxes/artifacts/session memory and explicit `long_term` roles show memory mode in context metadata.
- [X] T031 [US2] Write context projection test in `tests/hermes_flow/test_context_projection.py` proving planner and reviewer context packets contain different `role_id`, `soul`, `skills`, `toolsets`, `read_scope`, `write_scope`, and state objective.
- [X] T032 [US2] Write context isolation test in `tests/hermes_flow/test_context_projection.py` proving artifacts outside an agent `read_scope` and messages outside its inbox are absent from the generated context packet.
- [X] T033 [US2] Write memory mode test in `tests/hermes_flow/test_context_projection.py` proving default `run_isolated` roles do not receive prior-run inboxes/artifacts/session memory and explicit `long_term` roles show memory mode in context metadata.
- [X] T034 [US2] Write worker adapter test in `tests/hermes_flow/test_worker_adapter.py` using a fake Hermes command runner to assert the adapter is invoked with profile/session identity and a context packet path, not raw full conversation history.
- [X] T035 [US2] Write artifact permission test in `tests/hermes_flow/test_context_projection.py` proving an output path outside `write_scope` raises `ContextPolicyError` and records an audit event.
- [X] T036 [US2] Implement `build_context_packet()` in `hermes_flow/context.py` to produce a JSON-serializable packet with `run_id`, `state_id`, `role_id`, `soul`, `skills`, `toolsets`, `memory_mode`, `inbox_messages`, `readable_artifacts`, `required_outputs`, and `current_state_objective`.
- [X] T037 [US2] Implement `RuntimeStore.list_visible_messages()` and `RuntimeStore.list_readable_artifacts()` in `hermes_flow/storage.py` so context packets derive visibility from delivered inbox records and artifact scope, never from raw session history.
- [X] T038 [US2] Implement `validate_artifact_write()` in `hermes_flow/context.py` to accept only artifact paths inside the role's `write_scope` and reject unrestricted project-wide writes.
- [X] T039 [US2] Implement `WorkerAdapter` in `hermes_flow/worker.py` with methods `prepare_session_binding()`, `write_context_packet()`, and `run_role_action()`, using injectable command runner for tests and preserving full Hermes worker session/profile as the canonical execution unit.
- [X] T040 [US2] Implement `RuntimeStore.record_artifact()` in `hermes_flow/storage.py` to persist artifact metadata, producing role, state, path, visibility scope, and audit event records.
- [X] T041 [US2] Extend `flow_init()` in `hermes_flow/tools.py` to persist role profile names and memory modes in `agent_bindings` and return them in init/status outputs.
- [X] T042 [US2] Add CLI debug command `python -m hermes_flow.cli context --run-id <id> --role <role_id>` in `hermes_flow/cli.py` to print the generated context packet for manual isolation inspection.

**Checkpoint**: US2 is independently complete when context projection tests prove no unauthorized messages/artifacts/session memory enter role packets and the worker adapter can be tested without launching a real external model.

---

## Phase 5: User Story 3 - Route runtime messages to scoped recipients (Priority: P2)

**Goal**: An agent can send targeted messages, groups, orchestrator messages, or human messages only when allowed by the current state, and invalid recipient sets fail atomically with zero delivery.

**Independent Test**: Send messages to valid and invalid recipients and verify exactly the authorized recipients receive inbox entries; invalid sets produce a rejected audit envelope and no inbox writes.

### Tests for User Story 3

- [ ] T043 [P] [US3] Write valid targeted routing test in `tests/hermes_flow/test_routing.py` proving a planner message to reviewer in an allowed state creates one delivered `MessageEnvelope` and one reviewer inbox entry.
- [ ] T044 [US3] Write invalid recipient zero-delivery test in `tests/hermes_flow/test_routing.py` proving a message to `[reviewer, unknown_role]` is rejected, has empty `authorized_recipients`, records `recipient_availability`, and creates no inbox entries for any recipient. (Not [P] — shares file T043.)
- [ ] T045 [US3] Write unavailable node zero-delivery test in `tests/hermes_flow/test_routing.py` proving a known role that cannot currently accept messages causes the entire send to fail with no partial delivery. (Not [P] — shares file T043.)
- [ ] T046 [US3] Write acknowledgement routing test in `tests/hermes_flow/test_routing.py` proving messages with `requires_ack=True` expose pending acknowledgement data for gate evaluation. (Not [P] — shares file T043.)
- [ ] T047 [P] [US3] Write send CLI test in `tests/hermes_flow/test_cli_quickstart.py` for `python -m hermes_flow.cli send --run-id <id> --state PLAN --from planner --to reviewer,unknown_role ...` expecting `delivery_outcome=rejected` and zero inbox writes.

### Implementation for User Story 3

- [ ] T048 [US3] Implement recipient resolution in `hermes_flow/routing.py` for explicit role ids and allowed groups `orchestrator`, `human`, and `all`, rejecting unknown groups unless the current state routing policy declares them.
- [ ] T049 [US3] Implement recipient availability checks in `hermes_flow/routing.py` using current state, recipient role, state `message_acceptance`, and sender-to-recipient routing policy.
- [ ] T050 [US3] Implement atomic `route_message()` in `hermes_flow/routing.py`: validate every intended recipient before delivery; if any recipient is invalid, return `DeliveryOutcome.REJECTED`, empty authorized recipients, and zero inbox writes.
- [ ] T051 [US3] Implement `RuntimeStore.record_message_attempt()` in `hermes_flow/storage.py` to store both delivered and rejected message envelopes with sender, intended recipients, recipient availability, routing decision, and delivery outcome.
- [ ] T052 [US3] Implement `RuntimeStore.add_inbox_entries()` in `hermes_flow/storage.py` that is called only after `route_message()` validates all intended recipients.
- [ ] T053 [US3] Implement `flow_send()` in `hermes_flow/tools.py` according to `SendRequest` and `MessageEnvelope` contract schemas in `contracts/flow-tools.openapi.yaml`.
- [ ] T054 [US3] Wire `python -m hermes_flow.cli send` in `hermes_flow/cli.py` to parse comma-separated recipients, call `flow_send()`, print JSON, and exit zero for both delivered and rejected message outcomes.

**Checkpoint**: US3 is independently complete when invalid recipient tests prove there are no partial inbox writes and every rejected message remains visible in audit only.

---

## Phase 6: User Story 4 - Advance through gates without infinite loops (Priority: P2)

**Goal**: The engine advances only when strict all-required gate conditions are satisfied, routes change requests to revision/fix states, and escalates when loop budgets or convergence expectations are exhausted.

**Independent Test**: Run gate scenarios for approve, request changes, blocked, missing required decision, and max-round exhaustion without invoking real worker agents.

### Tests for User Story 4

- [ ] T055 [P] [US4] Write strict all-required pass test in `tests/hermes_flow/test_engine_gates.py` proving a gate with required roles `[developer, reviewer]` advances only after both submit `APPROVE` or `PASS`.
- [ ] T056 [US4] Write change-request test in `tests/hermes_flow/test_engine_gates.py` proving any `REQUEST_CHANGES` or `FAIL` decision prevents forward progress and transitions to the configured revision/fix state. (Not [P] — shares file T055.)
- [ ] T057 [US4] Write blocked-decision test in `tests/hermes_flow/test_engine_gates.py` proving any `BLOCKED` decision pauses or escalates according to the gate's `on_blocked` transition. (Not [P] — shares file T055.)
- [ ] T058 [US4] Write max-round escalation test in `tests/hermes_flow/test_engine_gates.py` proving repeated failures stop autonomous progress no later than the configured `max_rounds`. (Not [P] — shares file T055.)
- [ ] T059 [US4] Write non-converging loop test in `tests/hermes_flow/test_engine_gates.py` proving consecutive revisions that do not reduce unresolved findings escalate instead of looping forever. (Not [P] — shares file T055.)
- [ ] T059a [US4] Write idle-budget timeout test in `tests/hermes_flow/test_engine_gates.py` proving a gate state with `idle_timeout_seconds` triggers `on_exhausted` escalation when required decisions are not received within the budget. (Not [P] — shares file T059.)
- [ ] T060 [P] [US4] Write decide CLI test in `tests/hermes_flow/test_cli_quickstart.py` proving `python -m hermes_flow.cli decide --run-id <id> --state REVIEW --role reviewer --value APPROVE` records a decision and reports gate status.

### Implementation for User Story 4

- [ ] T061 [US4] Implement `RuntimeStore.record_decision()` in `hermes_flow/storage.py` to persist role, state, value, reason, artifacts, created timestamp, and audit event for every gate decision.
- [ ] T062 [US4] Implement `evaluate_gate()` in `hermes_flow/engine.py` with strict all-required semantics: all required roles must have pass values; any fail value routes to `on_fail`; any blocked value routes to `on_blocked`; missing required decisions keep the gate pending.
- [ ] T063 [US4] Implement `advance_state()` in `hermes_flow/engine.py` to persist state transitions, increment round counters for loops, and write transition audit events atomically.
- [ ] T064 [US4] Implement loop budget enforcement in `hermes_flow/engine.py` so review, revision, fix, and convergence loops escalate or abort when `max_rounds` is reached.
- [ ] T065 [US4] Implement `flow_decide()` and `flow_step()` in `hermes_flow/tools.py` according to contract schemas `Decision`, `GateStatus`, and `StepResult`.
- [ ] T066 [P] Wire `python -m hermes_flow.cli decide` and `python -m hermes_flow.cli step` in `hermes_flow/cli.py` to call tool handlers, print JSON, and preserve non-zero exit only for invalid input or runtime errors.
- [ ] T066a [US4] Implement idle budget enforcement in `hermes_flow/engine.py`: when `evaluate_gate()` or `advance_state()` detects the current state has `idle_timeout_seconds` set and the elapsed time since the last state activity exceeds the budget with no new decisions, record an idle-timeout escalation audit event and transition to `on_exhausted` without waiting for the next explicit `step` call.
- [ ] T067 [US4] Add audit payload details in `hermes_flow/engine.py` for gate result, required roles, present decisions, missing roles, selected transition, and loop counter values.

**Checkpoint**: US4 is independently complete when gate tests prove no majority-vote behavior exists and every autonomous loop exposes current and maximum round counts.

---

## Phase 7: User Story 5 - Inspect and resume a durable flow run (Priority: P3)

**Goal**: A user can inspect project-local runtime state, message history, decisions, artifacts, round counts, pending actions, terminal outcomes, and resume an interrupted run without replaying completed actions.

**Independent Test**: Start a run, progress through multiple states, stop the process, reopen status from project-local runtime, resume, and verify no completed state action is duplicated.

### Tests for User Story 5

- [ ] T068 [P] [US5] Write status test in `tests/hermes_flow/test_storage.py` proving `RuntimeStore.load_status()` returns current state, active agents, pending gate, round counters, memory modes, recent decisions, recent messages, artifact root, and next actions.
- [ ] T069 [US5] Write resume test in `tests/hermes_flow/test_storage.py` proving a reopened `RuntimeStore` loads the last recorded state from `.hermes-flow/runs/<run_id>/state.sqlite` and does not replay completed actions. (Not [P] — shares file T068.)
- [ ] T070 [P] [US5] Write modified-flow protection test in `tests/hermes_flow/test_flow_loader.py` proving an active run with captured `flow_version` rejects or requires explicit confirmation before applying a changed flow definition.
- [ ] T071 [US5] Write audit export test in `tests/hermes_flow/test_storage.py` proving delivered messages, rejected messages, decisions, gate evaluations, escalations, and terminal outcome appear in chronological order. (Not [P] — shares file T068.)
- [ ] T072 [P] [US5] Write pause/resume/abort CLI tests in `tests/hermes_flow/test_cli_quickstart.py` for `pause`, `resume`, `abort`, `status`, and `audit` subcommands using a temporary runtime.

### Implementation for User Story 5

- [ ] T073 [US5] Implement `RuntimeStore.load_status()` in `hermes_flow/storage.py` to assemble `FlowStatus` fields from project-local tables without reading Hermes worker profile histories.
- [ ] T074 [US5] Implement `RuntimeStore.resume_run()` in `hermes_flow/storage.py` to reopen existing `state.sqlite`, validate run status, and preserve completed state action records.
- [ ] T075 [US5] Implement modified-flow protection in `hermes_flow/flow_loader.py` and `hermes_flow/storage.py` by comparing active run `flow_version` with the flow definition version and requiring explicit confirmation flag before applying changes.
- [ ] T076 [US5] Implement `flow_status()`, `flow_pause()`, `flow_resume()`, and `flow_abort()` in `hermes_flow/tools.py` according to `FlowStatus` contract fields.
- [ ] T077 [US5] Implement `RuntimeStore.export_audit()` in `hermes_flow/storage.py` to return chronological audit entries with event type, actor, state, payload, and timestamp.
- [ ] T078 [US5] Wire `python -m hermes_flow.cli status`, `pause`, `resume`, `abort`, and `audit` in `hermes_flow/cli.py` to print JSON and avoid replaying worker actions during status or audit operations.
- [ ] T079 [US5] Update `examples/hermes-flow/README.md` with exact manual resume and audit commands copied from `specs/001-hermes-flow-fsm/quickstart.md`.

**Checkpoint**: US5 is independently complete when the run can be inspected and resumed using only `.hermes-flow/runs/<run_id>/state.sqlite` plus project-local artifacts.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, readability, and contract consistency across all stories. Do not add new product scope in this phase.

- [ ] T080 [P] Add complete quickstart integration test in `tests/hermes_flow/test_cli_quickstart.py` covering init, status, invalid send zero delivery, decide approve, step to terminal, audit export, and resume from project-local runtime.
- [ ] T081 [P] Add performance smoke test in `tests/hermes_flow/test_storage.py` that creates 10 agents and 1,000 message records and asserts status query and gate evaluation helpers complete within documented plan goals on a normal local machine.
- [ ] T082 [P] Add static contract consistency test in `tests/hermes_flow/test_tool_contracts.py` that compares dataclass field names in `hermes_flow/schemas.py` against schema properties in `contracts/flow-tools.openapi.yaml` for `FlowStatus`, `MessageEnvelope`, `Decision`, and `AgentBinding`.
- [ ] T083 Update `specs/001-hermes-flow-fsm/quickstart.md` command examples only if implementation CLI flags differ, preserving the expected results and zero-delivery semantics.
- [ ] T084 Update `examples/hermes-flow/README.md` with a troubleshooting section for invalid flow validation, rejected message routing, strict gate waiting, and project-local runtime recovery.
- [ ] T085 Remove speculative TODOs, empty abstractions, and single-use wrappers from `hermes_flow/*.py`, keeping only modules listed in `plan.md` and used by tests.
- [ ] T086 Run `python -m pytest tests/hermes_flow/` and record the command plus result in `specs/001-hermes-flow-fsm/implementation-report.md`.
- [ ] T087 Run `python scripts/verify_hermes_flow_contracts.py` and record the command plus result in `specs/001-hermes-flow-fsm/implementation-report.md`.
- [ ] T088 Run the manual commands from `specs/001-hermes-flow-fsm/quickstart.md` against a temporary project root and record the observed outputs in `specs/001-hermes-flow-fsm/implementation-report.md`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user-story phases.
- **US1 (Phase 3)**: Depends on Foundational; MVP starts here.
- **US2 (Phase 4)**: Depends on Foundational and can run alongside US1 after shared schemas/storage exist, but final integration benefits from US1 run creation.
- **US3 (Phase 5)**: Depends on Foundational and uses runtime rows created by US1; can be implemented with fixtures before full US1 CLI is complete.
- **US4 (Phase 6)**: Depends on Foundational and uses decisions/messages/runtime from US1/US3 fixtures; gate logic is independently testable.
- **US5 (Phase 7)**: Depends on project-local runtime from US1 and audit/state writes from US3/US4.
- **Polish (Phase 8)**: Depends on all selected user stories.

### User Story Dependencies

- **User Story 1 (P1)**: No story dependency after Foundational. This is the MVP and must be demoable alone.
- **User Story 2 (P1)**: No story dependency after Foundational for context packet tests; worker binding output should align with US1 run creation.
- **User Story 3 (P2)**: Depends on runtime storage and state/role fixtures from US1/Foundational.
- **User Story 4 (P2)**: Depends on runtime storage and decision/message persistence from Foundational/US3.
- **User Story 5 (P3)**: Depends on durable runtime, audit events, and state transitions from US1/US3/US4.

### Within Each User Story

- Write tests first and confirm they fail for the intended missing behavior.
- Implement schemas/storage helpers before tool or CLI handlers that expose them.
- Keep tool handlers thin; core behavior belongs in `flow_loader.py`, `storage.py`, `routing.py`, `context.py`, `worker.py`, or `engine.py`.
- After a story checkpoint passes, do not refactor earlier story behavior unless tests remain green.

### Parallel Opportunities

- T003, T004, and T005 can run in parallel after T001 because they touch different directories.
- T010, T011, and T012 can run in parallel after schemas are sketched.
- User-story test files can be written in parallel: T020-T023, T031-T035, T043-T047, T055-T060, and T068-T072 touch separate test scopes.
- US2 context work and US3 routing work can proceed in parallel once T007-T019 are complete.
- US4 engine work can proceed in parallel with US3 routing once decision storage contracts are stable.
- Polish tests T080-T082 can be prepared in parallel after all user-story APIs are known.

---

## Parallel Example: User Story 1

```bash
# T020 [P] runs first; T021 runs after (same file)
Task: "T020 [P] [US1] Write valid-flow loader test in tests/hermes_flow/test_flow_loader.py"
Task: "T021 [US1] Write invalid-flow validation tests in tests/hermes_flow/test_flow_loader.py"
Task: "T022 [P] [US1] Write init tool contract test in tests/hermes_flow/test_tool_contracts.py"
Task: "T023 [P] [US1] Write CLI init integration test in tests/hermes_flow/test_cli_quickstart.py"
```

## Parallel Example: User Story 2

```bash
Task: "T031 [P] [US2] Write context projection test in tests/hermes_flow/test_context_projection.py"
Task: "T034 [P] [US2] Write worker adapter test in tests/hermes_flow/test_worker_adapter.py"
Task: "T035 [P] [US2] Write artifact permission test in tests/hermes_flow/test_context_projection.py"
```

## Parallel Example: User Story 3

```bash
# T043 [P] runs first; T044, T045, T046 run after (same file)
Task: "T043 [P] [US3] Write valid targeted routing test in tests/hermes_flow/test_routing.py"
Task: "T044 [US3] Write invalid recipient zero-delivery test in tests/hermes_flow/test_routing.py"
Task: "T045 [US3] Write unavailable node zero-delivery test in tests/hermes_flow/test_routing.py"
```

## Parallel Example: User Story 4

```bash
# T055 [P] runs first; T056, T058 run after (same file)
Task: "T055 [P] [US4] Write strict all-required pass test in tests/hermes_flow/test_engine_gates.py"
Task: "T056 [US4] Write change-request test in tests/hermes_flow/test_engine_gates.py"
Task: "T058 [US4] Write max-round escalation test in tests/hermes_flow/test_engine_gates.py"
```

## Parallel Example: User Story 5

```bash
# T068 [P] runs first; T069, T071 run after (same file)
Task: "T068 [P] [US5] Write status test in tests/hermes_flow/test_storage.py"
Task: "T069 [US5] Write resume test in tests/hermes_flow/test_storage.py"
Task: "T071 [US5] Write audit export test in tests/hermes_flow/test_storage.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. Complete Phase 1 Setup.
2. Complete Phase 2 Foundational.
3. Complete Phase 3 US1 so a valid flow can initialize a project-local run.
4. Complete Phase 4 US2 so role-specific context isolation and profile/session bindings are testable.
5. Stop and validate US1+US2 before implementing routing or gates.

### Incremental Delivery

1. **MVP A**: Setup + Foundational + US1 = valid flow definition, validation, and project-local run creation.
2. **MVP B**: Add US2 = isolated context packets and worker profile/session adapter.
3. **Routing Increment**: Add US3 = atomic scoped messages with zero delivery on invalid recipient sets.
4. **Gate Increment**: Add US4 = strict all-required gate transitions and bounded loops.
5. **Durability Increment**: Add US5 = status, pause/resume/abort, and audit export.
6. **Polish**: Run quickstart, contract, performance, and full pytest validation.

### Guidance for Cheap LLM Implementers

- Implement only the files named in the current task.
- Do not add new frameworks, dashboards, REST servers, background daemons, or external orchestrators.
- Do not replace project-local runtime authority with Hermes profile/session state.
- Do not implement majority voting or partial message delivery.
- Do not give default long-term memory to any agent role.
- Keep functions small and directly covered by the test named in the task.
- When unsure, prefer rejecting invalid input with a readable error over accepting best-effort behavior.

---

## Notes

- `[P]` tasks are safe to parallelize only when their listed files do not overlap with another active task.
- `[US1]` to `[US5]` labels map directly to the five user stories in `spec.md`.
- Every user story has test tasks before implementation tasks because the spec requires repeatable validation.
- Commit after each completed story checkpoint, not after every tiny task, unless the working tree becomes hard to reason about.
- Stop at each checkpoint and run the listed pytest subset before proceeding.
