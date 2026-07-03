# Feature Specification: Agent Loop — 事件驱动执行层

**Feature Branch**: `004-agent-loop`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "设计执行层，要确保每个子 agent 能决策发送消息的权利，能决策是否向下一级推进。要能在 agent 之间建立双向的沟通通道且可以多次沟通讨论，基于不同人格实现团队协作。"

---

## Clarifications

### Session 2026-07-02

- Q: How do agent sessions execute — how does the agent call message_send / submit_decision functions? → A: Option B — Hermes subprocess + terminal call. The Runtime Loop writes the context packet as a file, then spawns a delegate_task subagent. The subagent receives the context file path and uses the terminal tool to run Python commands that import agent_tools.py and call its functions. When done, the subagent writes a result file; the loop collects and parses it. This bridges the gap between delegate_task's tool-based execution model and the need to call Python-level flow functions.
- Q: What happens when a required agent session times out without calling submit_decision? → A: Option A — No special handling. The run remains in the current state with the missing decision; the gate is not evaluated because not all required roles have decided. If the state has `idle_timeout_seconds` configured, the loop's normal idle-timeout detection will eventually trigger `on_exhausted`. If no idle timeout is configured, the run stays in the state (designer responsibility to configure idle_timeout_seconds or ensure agents respond).
- Q: Can the Runtime Loop spawn multiple agent sessions simultaneously for different roles in the same state? → A: Option B — Concurrent. All actor roles with unread inbox entries get a session simultaneously on the same tick. This enables natural bidirectional discussion (e.g., architect and reviewer can both respond to each other without waiting for serial processing).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent autonomously communicates and decides within a flow run (Priority: P1)

As a flow conductor, I want each participating agent to be able to send messages to other agents via the flow's inbox system and submit gate decisions so that multi-agent collaboration happens through the FSM's routing and auditing infrastructure rather than through ad-hoc file sharing.

**Why this priority**: Without this, agents cannot communicate through the flow system — they rely on external coordination (file markers, separate conductors), defeating the purpose of the FSM. This is the foundational capability for all agent-loop scenarios.

**Independent Test**: Can be fully tested by starting a flow, spawning an agent session for the REVIEW state, calling the agent-side `message_send` and `submit_decision` tools, and verifying the message appears in the target inbox and the decision is recorded in the run store.

**Acceptance Scenarios**:

1. **Given** an active flow run with two agent roles (reviewer, architect), **When** the reviewer agent calls `message_send` to send a question to the architect, **Then** the message is persisted via `record_message_attempt`, appears in the architect's inbox, and the delivery is recorded in the audit trail.
2. **Given** a gate state requiring the reviewer's approval, **When** the reviewer agent calls `submit_decision(value="APPROVE", reason="Looks good")`, **Then** the decision is persisted via `record_decision`, an audit event is appended, and subsequent gate evaluation can use it.
3. **Given** the reviewer sends a message to the architect and the architect has not yet been assigned a session, **When** the runtime loop detects the unread inbox entry, **Then** it creates a new session for the architect with the inbox message included in the context packet.

---

### User Story 2 - Runtime loop automatically advances flow without manual intervention (Priority: P1)

As a flow conductor, I want the FSM to continuously monitor the run state — checking for new decisions, evaluating gates, detecting timeouts — and advance states automatically so that I do not need to manually call `flow_decide` and `flow_step` after every agent action.

**Why this priority**: The current bottleneck is that every gate evaluation and state transition requires an external caller. Without an automatic loop, the "agent loop" is not autonomous.

**Independent Test**: Can be fully tested by creating a run with a gate requiring two approvals, recording decisions for both roles via the store, and confirming that the runtime loop's next tick detects the completed decisions, evaluates the gate, and advances the run to the configured `on_pass` state without any external tool call.

**Acceptance Scenarios**:

1. **Given** a run in a review state requiring two approvals, **When** both agents submit their decisions, **Then** within the next loop tick the gate is evaluated, the run advances to the `on_pass` state, and the transition is recorded in the audit trail.
2. **Given** a state with `idle_timeout_seconds=5` and no agent activity, **When** the runtime loop checks the elapsed time, **Then** the loop triggers the configured `on_exhausted` transition without any external trigger.
3. **Given** a run reaches a terminal state, **When** the runtime loop inspects the run status, **Then** the loop stops processing that run and records the outcome.

---

### User Story 3 - Multi-round discussion between agents with different personalities (Priority: P2)

As an architect agent in a flow, I want to receive feedback from a reviewer agent, respond to it, and iterate through multiple discussion rounds so that the team can refine designs through natural back-and-forth conversation before the gate is satisfied.

**Why this priority**: Real team collaboration requires discussion and iteration, not single-shot approvals. This is what makes the flow feel like a team, not a pipeline.

**Independent Test**: Can be fully tested by creating a flow where the reviewer requests changes via `message_send` to the architect, the architect responds and revises, the reviewer submits `REQUEST_CHANGES` as the gate decision, the loop routes to `on_fail` (revision state), the architect resubmits, and the reviewer finally approves — all without external intervention.

**Acceptance Scenarios**:

1. **Given** a review state where the reviewer has not yet submitted a decision, **When** the reviewer sends a change request message to the architect and then calls `submit_decision("REQUEST_CHANGES")`, **Then** the runtime loop evaluates the gate as unsatisfied, increments the round counter, and transitions to the `on_fail` state.
2. **Given** a revision round where the architect has updated the design, **When** the architect sends a revised proposal back to the reviewer, **Then** the runtime loop detects the new inbox message, schedules a new session for the reviewer, and the reviewer can read the update and approve.
3. **Given** a gate with `max_rounds=3` and three revision rounds have already occurred, **When** the reviewer submits another `REQUEST_CHANGES` decision, **Then** the runtime loop detects the counter has exceeded `max_rounds` and transitions to `on_exhausted` instead of routing to `on_fail`.

---

### Edge Cases

- Agent calls `message_send` to a recipient not authorized by the current state's routing policy → the router rejects the send, zero delivery, and the error is returned to the agent.
- Agent calls `submit_decision` for a gate that does not include that role → the decision is still persisted but the gate is not evaluated (only required roles trigger evaluation).
- Runtime loop encounters a state with no gate → no automatic transition occurs (per Clarify Q2 of feature 003).
- Runtime loop encounters a state where some required roles have not submitted decisions → no gate evaluation, loop waits.
- Agent session times out without calling `submit_decision` → the run remains in the current state; the loop does not take special action. If the state has `idle_timeout_seconds` configured, normal idle-timeout detection will eventually trigger `on_exhausted`. If not configured, the run waits indefinitely (per Clarify Q2).
- Two agents send messages simultaneously → inbox entries are persisted in order; each is processed on the next loop tick.
- Agent sends an empty `intended_recipients` list → router rejects with "no recipients specified".

### Out of Scope *(mandatory)*

- Visual dashboard for monitoring agent interactions.
- Real-time streaming communication between agents (all messages are async via inbox).
- Agent spawning via Hermes worker profiles (delegate_task-based subagent sessions are the initial execution mechanism; worker profile integration is deferred).
- Cross-flow or cross-run message routing or agent scheduling.
- Automatic conflict resolution when agents disagree (the `on_fail` path routes to revision; human escalation is configured in the flow definition).
- Agent self-improvement or autonomous skill acquisition.

---

## Requirements *(mandatory)*

### Functional Requirements

**Agent-Facing Tools (agent_tools.py)**:

- **FR-001**: The system MUST provide an `agent_inbox_read(run_id, role_id)` function that returns all unread and recent inbox messages addressed to the given role, including sender, content, kind, and message_id.
- **FR-002**: The system MUST provide an `agent_message_send(run_id, role_id, state_id, intended_recipients, kind, content)` function that delegates to `flow_send` using the agent's role_id as the from_role and returns the delivery outcome. The existing routing validation (FR-010/FR-011 of feature 003) applies.
- **FR-003**: The system MUST provide an `agent_submit_decision(run_id, role_id, state_id, value, reason)` function that delegates to `flow_decide` and returns the decision_id.
- **FR-004**: All agent-facing tool functions MUST wrap their core logic in a tracer span with event_type matching the function name.

**Runtime Loop (runtime_loop.py)**:

- **FR-005**: The runtime loop MUST run as a background daemon process that polls the run state every 1 second and processes all active runs.
- **FR-006**: On each tick, the runtime loop MUST inspect the current state's gate conditions and, if all required roles have submitted decisions since the last evaluation, call `evaluate_gate` and, if a transition is triggered, call `advance_state`.
- **FR-007**: On each tick, the runtime loop MUST check each actor role in the current state for unread inbox entries. If an actor has unread messages and no active session, the loop MUST schedule a new agent session for that role. Sessions for different roles MUST be scheduled concurrently — all eligible actors get a session on the same tick (per Clarify Q3).
- **FR-008**: The runtime loop MUST detect idle timeout by calling `detect_idle_timeout` on each tick. If timeout is exceeded, the loop MUST trigger `advance_state` to the configured `on_exhausted` target.
- **FR-009**: The runtime loop MUST stop processing a run when its status is `completed` or `aborted`. It MUST NOT create new sessions or evaluate gates for runs in a terminal state.

**Agent Session Management (agent_session.py)**:

- **FR-010**: The system MUST prepare a context packet for each agent session that includes: role identity and soul, current state description, inbox messages, visible artifacts, pending decisions from other roles, and a list of available agent-facing tools (inbox_read, message_send, submit_decision, query_status). The context packet MUST be written to a file at a known path so that the spawned subagent can read it via terminal/file tools.
- **FR-010a**: The Runtime Loop MUST spawn each agent session as a Hermes delegate_task subagent. The subagent receives the context file path and the expected result file path via its goal string. The subagent uses the terminal tool to run Python commands that import agent_tools.py and call the agent-facing functions. When done, the subagent writes a JSON result file containing the actions taken (messages sent, decisions submitted, artifacts written). The Loop polls for the result file.
- **FR-011**: Each agent session MUST have a configurable maximum duration. If the session exceeds this duration without writing a result file, the session is terminated and the run continues without that role's decision (idle timeout may apply).
- **FR-012**: Agent sessions MUST be ephemeral — each session handles one work cycle (read inbox → think → send/decide → exit). When new messages arrive for the agent, a new session is created.

**Communication & Collaboration**:

- **FR-013**: The system MUST support multi-round discussion through the inbox mechanism: Agent A sends a message → runtime loop detects unread inbox for Agent B → schedules Agent B → Agent B reads and responds → loop detects Agent A's inbox → schedules Agent A, etc.
- **FR-014**: The soul field of AgentRole MUST be included verbatim in the agent session's context packet so that it influences the agent's behavior during discussion and decision-making.
- **FR-015**: Revision loops (gate on_fail routing back to a previous state) MUST preserve the round counter from feature 003 and enforce max_rounds limits.

### Traceability & Validation Requirements *(mandatory)*

- **TV-001**: Each user story MUST define a repeatable validation path.
- **TV-002**: Requirements involving runtime behavior MUST state the observable execution fact, not only the human-facing message.
- **TV-003**: Any requested abstraction, extension point, or reusable component MUST name its concrete current consumers or be listed as out of scope.
- **TV-004**: Every agent session (start → tool calls → exit) MUST be traceable through trace_events with causal parentage linking the session to the run and state.

### Key Entities *(include if feature involves data)*

- **Agent Context Packet**: A structured data bundle prepared for each agent session, containing the agent's role identity, soul, current state definition, inbox messages, visible artifacts, pending group decisions, and available tool list. This is the FR-005 "context packet" from feature 001, now concretely defined.
- **Agent Session**: An ephemeral execution unit representing one agent's work cycle within a flow state. Created by the runtime loop when an agent has pending work (inbox messages or first entry into a state). Exits when the agent calls submit_decision or times out.
- **Runtime Loop Tick**: One iteration of the runtime loop's polling cycle. Each tick checks: agent inboxes → session scheduling → gate evaluation → idle timeout → terminal detection.
- **Discussion Round**: A complete cycle of message-exchange between agents within one state visit. Multiple discussion rounds can occur within a single gate evaluation cycle before decisions are submitted.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a two-agent flow, an agent can call `message_send` and `submit_decision` through the provided agent-facing tools, and the results are persisted in the runtime store. Verified within 30 seconds of starting the flow.
- **SC-002**: The runtime loop advances a run from a gate state to the next state within 5 seconds of all required decisions being submitted, without any external tool call.
- **SC-003**: A multi-round discussion between architect and reviewer (message → response → change request → revision → approval) completes without any human or external-driver intervention. Verified across at least 3 independent runs.
- **SC-004**: A revision loop with max_rounds=3 correctly escalates to on_exhausted on the 4th revision, with the round counter visible in the audit trail.
- **SC-005**: Each agent session produces at least one trace_events entry showing session start, tool calls, and session end, linked to the run_id and state_id.

---

## Assumptions

- The existing FSM engine (evaluate_gate, advance_state, detect_idle_timeout) and tool handlers (flow_send, flow_decide, flow_step) from features 001-003 are complete and correct — the runtime loop consumes them, it does not reimplement them.
- Agent sessions are executed as Hermes delegate_task subagents. The Runtime Loop
  writes a context packet file, spawns a subagent with the file path as its goal,
  and the subagent uses the terminal tool to run Python commands that import
  and call agent_tools.py functions. This is the clarified execution
  model per Clarify Q1 (Session 2026-07-02). Full Hermes worker profile
  integration is deferred.
- The runtime loop is designed for single-run, single-process execution. Cross-run scheduling and multi-host distribution are out of scope.
- Agent personality is expressed through the soul field only — no separate behavior tree, decision graph, or ML classification of agent responses.
- The existing routing validation (FR-009 to FR-013 of feature 003) covers all message authorization and availability checks — the agent-facing tools do not add a separate authorization layer.
- The runtime loop polls at 1-second intervals, which is sufficient for step-driven multi-agent interaction. Sub-second latency is not required.
