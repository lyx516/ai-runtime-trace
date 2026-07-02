# Feature Specification: Core FSM Implementation

**Feature Branch**: `003-core-fsm-impl`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "Complete the two remaining stub modules in Hermes Flow FSM — the FSM Engine (gate evaluation, state transitions, loop budget, idle timeout) and the Message Router (recipient availability checks, atomic zero-delivery routing). Also implement the remaining seven tool stubs: flow_status, flow_step, flow_send, flow_decide, flow_pause, flow_resume, flow_abort."

**Reference**: Feature 001 (`001-hermes-flow-fsm`) defines the full FSM design — this feature fills the remaining implementation gaps. The data model, contracts, and user stories from 001 already define the semantics; this spec focuses on non-duplicating completion criteria.

## Clarifications

### Session 2026-07-02

- Q: How does the round counter work — when is it incremented and how are decisions grouped into rounds? → A: Option A — round counter increments only when evaluate_gate returns unsatisfied (on_fail / on_blocked). Decisions for the current round are filtered by querying the transitions table for the last time the state was entered, then loading decisions created after that timestamp. on_pass does not increment the counter (state has already advanced).
- Q: What does flow_step do on a state without a gate — auto-advance or stop? → A: Option B — flow_step returns the current status without advancing. The caller decides whether to call flow_step again. This preserves step-driven semantics and avoids unexpected recursive state advances.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - FSM engine evaluates gates and transitions states correctly (Priority: P1)

As a flow conductor running a multi-agent collaboration, I want the runtime engine to evaluate gate conditions (decisions from required roles), compute the next state based on gate results, enforce loop-budget limits, and detect idle timeouts so that multi-agent workflows advance predictably and terminate rather than looping forever.

**Why this priority**: Without the engine, the flow cannot advance beyond the initial state. Gate evaluation, state transition, loop budget, and idle timeout are the four execution primitives that every non-trivial flow run depends on.

**Independent Test**: Can be fully tested by creating a run in a review state with two required approvers, recording decisions for both, triggering state advancement, and verifying the run appears in the expected next state. Also verify loop budget exhaustion triggers escalation, and idle timeout triggers the configured exhaust path.

**Acceptance Scenarios**:

1. **Given** a run in a review state with a gate requiring both planner and reviewer approval, **When** both agents have submitted approved decisions and no revision requests are outstanding, **Then** the engine evaluates the gate as satisfied and transitions the run to the configured `on_pass` state.
2. **Given** the same review state receives a change request from the reviewer, **When** the gate is evaluated, **Then** the engine records the split decision and transitions to the configured `on_fail` (revision) state without advancing past the review.
3. **Given** a gate configures `max_rounds=3` and the review has undergone 3 revision rounds without approval, **When** a fourth revision request arrives, **Then** the engine triggers the `on_exhausted` transition instead of continuing the loop.
4. **Given** a state with `idle_timeout_seconds=3600` and no activity for more than one hour, **When** the next `flow_step` or `flow_status` call occurs, **Then** the engine detects the timeout and transitions to the configured `on_exhausted` state.
5. **Given** a run reaches a terminal state, **When** any tool handler inspects the run status, **Then** the run is marked `completed` and no further step/send/decide operations are allowed.

---

### User Story 2 - Message router validates recipients and enforces atomic zero-delivery (Priority: P1)

As a main-session conductor, I want every message submission to validate that all intended recipients are authorized by the current state's routing policy and currently available to receive messages, and — if any recipient fails validation — the entire send is rejected with zero deliveries.

**Why this priority**: Message leaks (delivering to unauthorized recipients) or partial deliveries (some succeed, some fail) undermine context isolation and make the collaboration outcome unpredictable. The existing spec demands atomic zero-delivery; this is its implementation.

**Independent Test**: Can be fully tested by constructing a state with a routing policy that allows messaging to only two of three possible roles, then submitting a message intended for all three, and confirming zero messages are delivered and the rejection reason shows the invalid recipient.

**Acceptance Scenarios**:

1. **Given** a state whose routing policy allows messaging to role A and role B, **When** an agent sends a message intended for A, B, and C, **Then** the router rejects the send, records a rejection reason identifying C as invalid, and delivers zero messages.
2. **Given** a state where role A is inbox-active (can receive) and role B is not, **When** an agent sends a message intended for A and B, **Then** the router rejects the send because B is unavailable and delivers zero messages.
3. **Given** a state where role A and role B are both authorized and available, **When** an agent sends a message to A and B, **Then** the router accepts the send, delivers the message to both inboxes, and records a successful delivery outcome.
4. **Given** a message that requires acknowledgement, **When** the delivery succeeds, **Then** the message record includes `requires_ack=True` and each recipient's acknowledgement is tracked independently.

---

### User Story 3 - Tool handlers expose runtime status, step, send, decide, and lifecycle operations (Priority: P2)

As a Hermes user, I want the complete set of `flow_*` tool handlers to work end-to-end so that I can inspect a run's current state and pending actions, submit decisions and messages, advance the flow step by step, and pause/resume/abort a run using the same tool surface that the Hermes plugin exposes.

**Why this priority**: The tool surface is the user-facing API. Without these implementations, the flow cannot be driven interactively.

**Independent Test**: Can be fully tested by starting a flow run via `flow_init`, calling `flow_status` to confirm the initial state, calling `flow_send` and `flow_decide`, calling `flow_step` to advance the flow, and confirming the run transitions through states. Then test `flow_pause`/`flow_resume` and `flow_abort` produce the correct run status transitions.

**Acceptance Scenarios**:

1. **Given** an active flow run, **When** `flow_status` is called, **Then** it returns the current state, agent bindings, pending decisions, recent messages, round counters, and next action.
2. **Given** an active flow run in a review state, **When** `flow_step(max_actions=1)` is called, **Then** the engine evaluates the current gate and either advances the state or returns the pending gate with a summary of outstanding decisions.
3. **Given** an active flow run, **When** `flow_send` is called with valid recipients, **Then** the message is routed, recorded, and delivered to the recipients' inboxes.
4. **Given** an active flow run in a gate state, **When** `flow_decide` records the last required decision, **Then** `flow_step` on the next call completes the gate and advances the state.
5. **Given** an active flow run, **When** `flow_pause` is called, **Then** the run status changes to `paused` and all step/send/decide operations return an error.
6. **Given** a paused flow run, **When** `flow_resume` is called, **Then** the run status returns to `active`.
7. **Given** an active flow run, **When** `flow_abort` is called, **Then** the run status changes to `aborted` and all subsequent operations return an error.

---

### Edge Cases

- Engine receives `evaluate_gate` call for a run that has already reached a terminal state → return a no-op with current status.
- Engine receives `evaluate_gate` call for a state without any gate → immediately transition via first matching transition condition.
- Router receives a message with empty `intended_recipients` → reject with "no recipients specified".
- Router receives a message where ALL recipients are authorized and ALL are unavailable → reject with "all recipients unavailable".
- `flow_step` called on a run already awaiting decisions and no new decisions have arrived → return current status without re-evaluating the gate.
- `flow_step` called on a paused/aborted/completed run → return error with run status.
- `flow_pause` called on an already paused run → return success (idempotent).
- `flow_abort` called on an already aborted run → return success (idempotent).
- `flow_resume` called on an active run → return success (idempotent).
- Loop budget decrement reaches zero mid-evaluation → the engine must still complete the current transition to `on_exhausted` before returning.

### Out of Scope *(mandatory)*

- Replaying historical decisions to reconstruct past gate states (audit trail already exists).
- Custom route-policy DSL beyond the existing per-state recipient lists.
- Human-in-the-loop notification (email/SMS) for escalation or idle-timeout events.
- Dashboard or human-readable UI for flow timing or gate statistics.
- Parallel state evaluation (engine processes one step at a time).
- Cross-run gate dependencies or inter-run message routing.
- Automatic retry of failed worker dispatches.

## Requirements *(mandatory)*

### Functional Requirements

**Engine (engine.py)**:

- **FR-001**: The engine MUST provide `evaluate_gate(run_id, state_id)` that inspects all decisions recorded for the current round group, compares them against the gate's `required_roles`, and returns a result with fields: `satisfied` (bool), `next_state_id` (str), `outstanding_roles` (list[str]), `round` (int), `reason` (str).
- **FR-002**: The engine MUST detect when all required roles have submitted a decision whose value matches one of the gate's `pass_values`. When satisfied, set `satisfied=True` and return `next_state_id` from `on_pass`.
- **FR-003**: The engine MUST detect when any required role's decision value matches one of the gate's `fail_values` or `blocked_values`. When unsatisfied, set `satisfied=False`, return `next_state_id` from `on_fail` or `on_blocked` respectively, and include the decision details in `reason`.
- **FR-004**: The engine MUST maintain a per-state round counter (in `run.round_counters`), incremented only when `evaluate_gate` returns unsatisfied (on_fail or on_blocked). If `round >= max_rounds` and the gate is still unsatisfied, the engine MUST set `satisfied=False` and return `next_state_id` from `on_exhausted`. on_pass transitions do NOT increment the counter because the state has already advanced.
- **FR-005**: The engine MUST provide `detect_idle_timeout(run_id, state_id)` that checks the elapsed time since the last recorded activity against `idle_timeout_seconds`. If exceeded, the engine MUST trigger the state's `on_exhausted` transition.
- **FR-006**: The engine MUST provide `advance_state(run_id, from_state_id, to_state_id, reason)` that persists the state transition, resets the round counter for the new state, appends an audit event, and updates `run.current_state_id`.
- **FR-007**: The engine MUST reject `evaluate_gate` or `advance_state` calls for runs whose status is not `active`.
- **FR-008**: The engine MUST reject `evaluate_gate` for a state that has no gate defined. `flow_step` MUST NOT auto-advance through gapless states — it returns the current status and the caller decides whether to call `flow_step` again (step-driven semantics, per Clarify Q2).

**Router (routing.py)**:

- **FR-009**: The router MUST provide `validate_message(run_id, state_id, from_role, intended_recipients, routing_policies)` that returns a validation result with fields: `valid` (bool), `authorized_recipients` (list[str]), `invalid_recipients` (list[str]), `unavailable_recipients` (list[str]), `reason` (str or null).
- **FR-010**: The router MUST reject (`valid=False`) the entire message if any intended recipient is not listed in the current state's routing policy for the sender role. Zero messages are delivered.
- **FR-011**: The router MUST reject (`valid=False`) the entire message if any intended recipient is `inbox-inactive` (not in an accept-messages state or is in a terminal/completed state). Zero messages are delivered.
- **FR-012**: The router MUST accept (`valid=True`) only when ALL intended recipients are both authorized (by routing policy) and available (inbox-active). Messages are delivered to all recipients.
- **FR-013**: The router MUST NOT modify the flow state or storage — it returns a validation result only. The caller (tool handler) is responsible for persisting the message record and delivering inbox entries.

**Tool handlers (tools.py)**:

- **FR-014**: `flow_status(run_id, include_recent_messages=True)` MUST query the RuntimeStore for run status, current state, agent bindings, pending gate state, round counters, recent messages, decisions, and artifacts. Return structured data per the OpenAPI contract from feature 001.
- **FR-015**: `flow_step(run_id, max_actions=1)` MUST call `evaluate_gate`, detect idle timeout, and if a transition is required, call `advance_state`. Return the new state or the current pending gate state.
- **FR-016**: `flow_send(run_id, state_id, from_role, intended_recipients, kind, content, visibility, artifacts, requires_ack)` MUST call the router for validation, persist the message envelope via `record_message_attempt`, deliver inbox entries to valid recipients, and return the delivery outcome.
- **FR-017**: `flow_decide(run_id, state_id, role_id, value, reason, artifacts)` MUST persist the decision via `record_decision`, append an audit event, and return the decision_id.
- **FR-018**: `flow_pause(run_id, reason)` MUST set the run status to `paused` and append an audit event. Idempotent if already paused.
- **FR-019**: `flow_resume(run_id, continuation_state)` MUST set the run status to `active` (optionally advancing to `continuation_state` if provided) and append an audit event.
- **FR-020**: `flow_abort(run_id, reason)` MUST set the run status to `aborted`, append an audit event, and prevent all future operations. Idempotent if already aborted.
- **FR-021**: All tool handlers MUST wrap their core logic in `tracer.span()` with appropriate event_type matching the trace contract.

### Traceability & Validation Requirements *(mandatory)*

- **TV-001**: Each user story MUST define a repeatable validation path.
- **TV-002**: Requirements involving runtime behavior MUST state the observable execution fact.
- **TV-003**: Any requested abstraction, extension point, or reusable component MUST name its concrete current consumers.

### Key Entities *(include if feature involves data)*

- **GateResult**: Result of `evaluate_gate` — satisfied boolean, next_state_id, outstanding_roles list, current round, reason string
- **RouteValidation**: Result of `validate_message` — valid boolean, authorized_recipients, invalid_recipients, unavailable_recipients, reason string
- **StateTransition**: Persisted record of transitioning from one state to another — run_id, from_state, to_state, reason, triggered_by (gate/timeout/explicit), created_at

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A two-agent approve gate evaluates correctly through at least 3 scenarios: both approve (pass), one requests changes (fail revision), one blocks (fail escalation) — verified with distinct decision values.
- **SC-002**: A loop-budget gate with `max_rounds=3` correctly prevents a 4th revision round and triggers `on_exhausted` — verified by submitting 4 change requests and confirming the 4th triggers escalation.
- **SC-003**: An idle-timeout of 2 seconds triggers correctly when the engine detects elapsed time exceeding the threshold — verified by advancing time in test with a mocked clock.
- **SC-004**: A message intended for 3 recipients where 1 is unauthorized is rejected with zero deliveries — verified by checking the message envelope's `delivery_outcome` field and the absence of inbox entries.
- **SC-005**: A message intended for 3 recipients where all are authorized and available is accepted and delivered to all 3 inboxes — verified by checking inbox entries for each recipient.
- **SC-006**: All 7 tool handlers (`flow_status`, `flow_step`, `flow_send`, `flow_decide`, `flow_pause`, `flow_resume`, `flow_abort`) return appropriate structured results with no `NotImplementedError` raised — verified by calling each handler with valid run state.
- **SC-007**: A complete end-to-end flow: init → status → send → decide → step → status → pause → resume → step → status reaches a terminal state with all spans recorded in trace_events.

## Assumptions

- Engine and router are stateless: they read from and write to the RuntimeStore, not maintaining in-memory state.
- The RuntimeStore already provides `record_decision`, `record_message_attempt`, `add_inbox_entries`, and `append_audit_event` (implemented in feature 001).
- Gate evaluation considers only decisions submitted in the current round group (a round group is the set of decisions collected since the last state advancement).
- The engine does not re-evaluate after every individual decision — it evaluates on `flow_step` call, making this a step-driven (not event-driven) evaluation model.
- Loop budget is tracked per state via round counters persisted in the run record; a state transition resets the counter for the new state.
- Recipient availability is determined by the target state's `message_acceptance` flag and the recipient's current state not being terminal; no additional online/offline signal exists.
- Idle timeout detection is synchronous (checked on `flow_step` or `flow_status`) rather than via a background timer. This is sufficient for step-driven interaction.
- The existing `RuntimeStore` methods (`load_status`, `resume_run`, `export_audit`) from feature 001 are sufficient for `flow_status` — no new storage methods needed beyond those already implemented.
