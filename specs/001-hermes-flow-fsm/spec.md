# Feature Specification: Hermes Flow FSM Agent Loop

**Feature Branch**: `001-hermes-flow-fsm`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "Build a Hermes-native finite-state-machine agent loop orchestrator. A main session should configure isolated agents with different souls, toolsets, and skill sets; allow runtime messages to declare the intended recipient range; preserve context isolation through inboxes and artifacts; and use bounded gates, revision loops, and human escalation so multi-agent collaboration can progress without infinite loops."

## Clarifications

### Session 2026-07-02

- Q: Which execution model should the spec require as the primary behavior for running agents? → A: Full Hermes worker sessions/profiles are the canonical execution unit.
- Q: How should worker profiles, sessions, and memory be reused across flow runs? → A: Persistent role profiles store role templates by default; each run uses isolated sessions, inboxes, and artifacts, while specific agents may opt into long-term memory when explicitly configured.
- Q: Where should flow run state, messages, decisions, artifacts, and audit trail be authoritative? → A: Project-local runtime is the authoritative source; Hermes profiles execute agents but do not own flow business state.
- Q: How should a gate decide when multiple agents provide conflicting decisions? → A: Strict all-required semantics; every required agent must approve or pass, any change request routes to revision or fix, and any blocked decision pauses or escalates.
- Q: What should happen when an agent attempts to send a message to a node that cannot currently accept messages? → A: Recipient availability is checked before sending; if any recipient is invalid after validation, the entire send attempt fails and zero delivery occurs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define a bounded multi-agent flow (Priority: P1)

As a Hermes user designing a multi-agent workflow, I want to describe the agent roles, states, allowed transitions, gates, and loop limits in one reviewable flow definition so that the main session can run a repeatable collaboration process without relying on ad-hoc prompting.

**Why this priority**: This is the foundation of the feature. Without a declared flow, the system cannot guarantee orderly progress, bounded loops, or predictable role behavior.

**Independent Test**: Can be fully tested by providing a flow definition with planner, developer, and reviewer roles, then confirming the system accepts the definition, identifies the initial state, validates the allowed transitions, and reports any invalid or missing gate rules before any agent work begins.

**Acceptance Scenarios**:

1. **Given** a valid flow definition with agents, states, transitions, gates, and loop limits, **When** the user starts the flow, **Then** the system creates a new runtime and reports the initial state, participating agents, expected artifacts, and next required action.
2. **Given** a flow definition that references a missing agent, missing terminal state, or unreachable state, **When** the user starts the flow, **Then** the system rejects the flow and explains each blocking issue in plain language.
3. **Given** a flow definition with a revision loop, **When** the system validates it, **Then** the loop is accepted only if it has an explicit maximum round count and an escalation path.

---

### User Story 2 - Run isolated agents with role-specific context (Priority: P1)

As a main-session conductor, I want each agent to run as a full Hermes worker session/profile with its own role identity, allowed skills, allowed tools, readable context, writable artifacts, inbox, and explicit memory mode so that agents can collaborate without sharing private or irrelevant context while still allowing selected long-memory agents when configured.

**Why this priority**: Context isolation is the main quality and safety requirement. Agent collaboration becomes unreliable if every participant sees the same full conversation or can write to the same unrestricted workspace.

**Independent Test**: Can be fully tested by creating two agents with different role definitions and confirming each agent receives only its permitted role instructions, inbox entries, readable artifacts, and output obligations.

**Acceptance Scenarios**:

1. **Given** a planner agent and a developer agent with different role definitions, skills, tools, and writable artifacts, **When** each agent is asked to act in the same state, **Then** each receives only the context and capabilities allowed for that role.
2. **Given** an agent tries to reference context outside its permitted scope, **When** the system prepares or accepts that agent's work, **Then** the unauthorized context is not included and the attempted out-of-scope access is reported as a policy issue.
3. **Given** an agent role uses the default memory mode, **When** the same role participates in a later flow run, **Then** it reuses the role template but does not receive prior-run inboxes, artifacts, or session memory.
4. **Given** an agent role is explicitly configured for long-term memory, **When** the role participates in later flow runs, **Then** the system reports that memory mode in status and includes only the memory allowed by that role's policy.
5. **Given** an agent produces an output, **When** the output is recorded, **Then** it is attached to the correct state, role, message, and artifact target so later agents can inspect it through explicit permissions.

---

### User Story 3 - Route runtime messages to scoped recipients (Priority: P2)

As an agent participating in a flow, I want to declare who should receive my current message so that discussion can be targeted to the right agent, reviewer group, orchestrator, or human without broadcasting every message to everyone.

**Why this priority**: Targeted routing keeps collaboration readable and prevents context leakage. It also enables agents to ask for review, clarification, or approval from only the necessary participants.

**Independent Test**: Can be fully tested by having an agent emit messages to a single recipient, a reviewer group, the orchestrator, and all participants, then confirming only authorized recipients receive each message.

**Acceptance Scenarios**:

1. **Given** a state allows the planner to message the developer and reviewer, **When** the planner sends a proposal to those recipients, **Then** only those recipients receive the message in their inboxes.
2. **Given** an agent attempts to send a message to a recipient not allowed in the current state or to a node that cannot currently accept messages, **When** the message is submitted, **Then** the system rejects the entire send attempt before delivery, records the reason, and delivers the message to no recipients.
3. **Given** a message requires acknowledgement, **When** each required recipient responds, **Then** the system records the acknowledgements and makes them available to the gate evaluation for that state.

---

### User Story 4 - Advance through gates without infinite loops (Priority: P2)

As a user supervising a multi-agent run, I want the flow to advance only when gate conditions are satisfied and to escalate when repeated revisions stop making progress so that the process is both collaborative and bounded.

**Why this priority**: The feature must support back-and-forth agent negotiation, but the main workflow must not stall forever in planner-developer-reviewer loops.

**Independent Test**: Can be fully tested by running a flow where reviewers first request changes, then approve, and by running another flow where reviewers repeatedly reject without progress until the escalation path is triggered.

**Acceptance Scenarios**:

1. **Given** a review state requiring approvals from developer and reviewer, **When** both submit approval decisions, **Then** the system advances to the next state.
2. **Given** a review state receives a change request, **When** the revision round limit has not been reached, **Then** the system transitions to the configured revision state and includes the review findings in the revising agent's context.
3. **Given** a review state reaches its maximum revision rounds without satisfying the gate, **When** another change request is submitted, **Then** the system stops autonomous progression and escalates to the human-defined escalation state.
4. **Given** a fix loop is configured to require issue reduction, **When** consecutive revisions do not reduce or resolve open findings, **Then** the system treats the loop as non-converging and escalates instead of continuing automatically.

---

### User Story 5 - Inspect and resume a durable flow run (Priority: P3)

As a user or main-session conductor, I want to inspect the project-local runtime state, message history, decisions, artifacts, round counts, and pending actions of a flow run so that work can be resumed or audited after interruptions.

**Why this priority**: Multi-agent flows may outlive a single conversation turn. Durable status and auditability are necessary for trust, recovery, and debugging.

**Independent Test**: Can be fully tested by starting a flow, progressing through multiple states, interrupting the main session, and confirming a resumed session can report the same current state and pending actions.

**Acceptance Scenarios**:

1. **Given** an active flow run, **When** the user requests status, **Then** the system reports current state, active agents, pending gates, round counts, recent decisions, and next action from the project-local runtime record.
2. **Given** a flow run has produced artifacts and messages, **When** the user inspects the run history, **Then** the system shows the ordered sequence of state transitions, message envelopes, decisions, and artifact references.
3. **Given** the main session is interrupted before the flow reaches a terminal state, **When** the user resumes the run, **Then** the system continues from the last recorded state without replaying already completed agent actions unless the user explicitly requests a retry.

---

### Edge Cases

- A flow references an agent role that has no soul, no allowed skills, or no allowed tool scope.
- A state has no valid outgoing transition and is not marked terminal.
- A revision loop has no maximum round count or no escalation path.
- Two agents submit conflicting decisions for the same gate; strict all-required semantics treat any change request as a revision or fix trigger and any blocked decision as a pause or escalation trigger.
- A required recipient does not respond before the state budget expires.
- An agent attempts to send a message to an unauthorized recipient, a node that cannot currently accept messages, or all participants from a state that only allows targeted routing; the entire send attempt fails with zero delivery.
- An agent produces an artifact outside its writable scope.
- A previous run is resumed after the flow definition has changed.
- A human escalation is triggered while some agent actions are still pending.
- A flow reaches a terminal state while non-blocking messages remain unread.

### Out of Scope *(mandatory)*

- A visual dashboard for designing or monitoring flows.
- Arbitrary model-written workflow programs that execute as part of the orchestration layer.
- Direct integrations with external orchestration frameworks such as LangGraph, CrewAI, or AutoGen.
- Agents freely creating new agent roles at runtime without a declared flow update.
- Cross-project fleet management or organization-wide agent scheduling.
- Automatic merging of implementation changes into a primary branch.
- Replacing Hermes' existing skill, memory, profile, or tool systems.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow a user to define a named flow containing agent roles, states, transitions, gate conditions, routing policies, loop limits, and terminal states.
- **FR-002**: The system MUST validate a flow before starting a run and report missing agents, invalid transitions, unreachable required states, missing terminal states, missing gate outcomes, and unbounded loops.
- **FR-003**: The system MUST create a durable project-local runtime record for each started flow, including its current state, participating agents, pending gates, round counters, messages, decisions, and artifact references.
- **FR-004**: The system MUST treat full Hermes worker sessions/profiles as the canonical execution unit for agent roles and allow each role to declare a distinct soul, skill set, tool sets, readable context scope, writable artifact scope, workspace isolation requirement, and memory mode.
- **FR-005**: The system MUST prepare a state-specific context packet for each agent action that includes only the agent's role instructions, permitted inputs, relevant inbox messages, required output format, and current state objective.
- **FR-006**: The system MUST prevent an agent from receiving messages, artifacts, or historical context outside the recipient and context rules declared for the current state.
- **FR-007**: The system MUST support structured runtime messages that identify sender, intended recipients, visibility, message kind, related state, acknowledgement requirement, decision request, and referenced artifacts.
- **FR-008**: The system MUST validate each message's intended recipients and each recipient node's current ability to accept messages before delivery; if any intended recipient is invalid, the entire send attempt MUST fail with zero delivery.
- **FR-009**: The system MUST deliver accepted messages only to authorized recipients and make them visible to later states only when the flow policy allows it.
- **FR-010**: The system MUST support gate conditions based on explicit agent decisions, required acknowledgements, required artifact markers, or human approval, and gates with multiple required agents MUST use strict all-required semantics.
- **FR-011**: The system MUST advance to the next state only when the current state's gate condition is satisfied or when the state is configured as an unconditional transition.
- **FR-012**: The system MUST route failed gates to the configured revision, fix, escalation, or abort state with the relevant findings preserved as input for the next actor; any required-agent change request MUST prevent forward progress until resolved.
- **FR-013**: The system MUST enforce maximum round counts for review, revision, fix, and convergence loops.
- **FR-014**: The system MUST escalate to a human-controlled state when a loop exceeds its maximum rounds, required responses are missing after the configured budget, or repeated revisions fail to reduce unresolved findings.
- **FR-015**: The system MUST provide a status view that shows current state, pending actor, pending gate, round count, latest decisions, latest messages, relevant artifacts, and available next actions.
- **FR-016**: The system MUST provide a project-local audit trail of state transitions, delivered messages, rejected messages, decisions, gate evaluations, escalations, and terminal outcome.
- **FR-017**: The system MUST allow a paused or interrupted run to resume from the last recorded state without duplicating completed state actions.
- **FR-018**: The system MUST make terminal outcomes explicit as completed, aborted, or escalated for human action.
- **FR-019**: The system MUST reject or require explicit human confirmation before applying a modified flow definition to an already active run.
- **FR-020**: The system MUST keep the main session in the conductor role by exposing run control, status, message submission, and decision recording without requiring the main session to impersonate worker agents.
- **FR-021**: The system MUST use persistent role profiles as reusable templates for soul, skills, and toolsets while defaulting each flow run to isolated sessions, inboxes, and artifacts.
- **FR-022**: The system MUST allow individual agent roles to explicitly opt into long-term memory and MUST expose that memory mode in run status and audit output.
- **FR-023**: The system MUST treat the project-local runtime as the authoritative source for flow state, messages, decisions, artifacts, and audit trail; worker profiles MUST NOT be the only source needed to resume or audit a run.

### Traceability & Validation Requirements *(mandatory)*

- **TV-001**: Each user story MUST define a repeatable validation path.
- **TV-002**: Requirements involving runtime behavior MUST state the observable execution fact, not only the human-facing message.
- **TV-003**: Any requested abstraction, extension point, or reusable component MUST name its concrete current consumers or be listed as out of scope.
- **TV-004**: Every transition in a flow run MUST be traceable to a gate result, explicit decision, or configured unconditional transition.
- **TV-005**: Every delivered or rejected message MUST be traceable to a sender, intended recipient set, state, routing policy decision, recipient availability check, and delivery outcome.
- **TV-006**: Every autonomous loop MUST expose its current round count and maximum allowed round count.

### Key Entities *(include if feature involves data)*

- **Flow Definition**: A reviewable description of the multi-agent process, including states, transitions, agents, gates, routing rules, loop limits, and terminal outcomes.
- **Agent Role**: A participant definition containing role identity, soul, allowed skills, allowed tools, context scope, artifact permissions, workspace expectations, memory mode, and the worker session/profile used to execute the role.
- **Flow Run**: A durable project-local execution instance of a flow definition with current state, counters, messages, decisions, artifacts, and outcome.
- **State**: A named step in the flow that identifies expected actors, input context, required outputs, gate rules, and possible next states.
- **Transition**: A permitted movement from one state to another, justified by a gate result, explicit decision, revision path, escalation, abort, or completion.
- **Message Envelope**: A structured communication record with sender, intended recipient range, visibility, kind, content, state, acknowledgement needs, decision request, artifact references, recipient availability check, and delivery outcome.
- **Inbox**: The scoped set of messages visible to a specific agent for a specific state or run.
- **Artifact**: A shared work product such as a plan, task list, review finding, decision record, implementation report, or convergence report.
- **Gate**: A strict all-required condition that determines whether a state can advance, revise, fix, escalate, abort, or complete; all required approvals or passes must be present before forward progress.
- **Loop Budget**: The allowed number of rounds, idle steps, or waiting period before the system must stop autonomous progression.
- **Memory Mode**: The per-agent setting that determines whether the role uses default run-isolated context only or explicitly receives long-term memory across runs.
- **Human Escalation**: A human-controlled escalation state where the system pauses autonomous execution and asks the user to decide how to continue.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can start a valid three-agent flow and see the initial state, participating agents, and next required action within 30 seconds.
- **SC-002**: 100% of invalid sample flows with missing agents, unreachable states, or unbounded loops are rejected before any agent action begins.
- **SC-003**: In validation runs, agents receive no messages or artifacts outside their declared recipient and context scope, and invalid recipient sets produce zero partial deliveries.
- **SC-004**: In a review loop where all required approvals are eventually provided, the flow advances to the next state without human intervention in at least 95% of runs, and never advances while any required agent has an unresolved change request or blocked decision.
- **SC-005**: In a non-converging loop, the system escalates instead of continuing automatically no later than the configured maximum round count.
- **SC-006**: A user can inspect any active run and identify current state, pending gate, unresolved findings, and next action in under 1 minute.
- **SC-007**: A paused or interrupted run can be resumed without duplicating already completed state actions in 100% of tested resume scenarios.
- **SC-008**: Every completed run has a project-local audit trail that accounts for all state transitions, delivered messages, rejected messages, and terminal outcome.
- **SC-009**: In default-memory validation runs, repeated runs with the same role profiles do not expose prior-run inboxes, artifacts, or session memory unless the role is explicitly configured for long-term memory.

## Assumptions

- The first supported users are advanced Hermes users who can read and review a declarative flow definition.
- The main session acts as conductor and supervisor; worker agents act only through declared roles.
- Persistent role profiles store reusable role templates such as soul, skills, and toolsets; per-run sessions, inboxes, and artifacts are isolated by default.
- Some agent roles may be intentionally long-memory agents, but that behavior requires explicit role configuration and must be visible in status and audit output.
- Flow definitions are project-local and versioned with the project unless the user chooses otherwise.
- Flow run state, inboxes, decisions, artifacts, and audit trail are project-local authoritative records; Hermes worker profiles are execution identities, not the sole source of flow truth.
- Agent souls, skills, and tool scopes are treated as user-visible configuration, not hidden implementation details.
- Context isolation is enforced by generated context packets, scoped inboxes, artifact permissions, and routing policy validation.
- Human escalation is acceptable whenever the system cannot prove safe progress within the configured loop budget.
- The initial feature focuses on correctness, auditability, and bounded progress before optimizing for visual design or large-scale fleet management.
