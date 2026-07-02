# Research: Hermes Flow FSM Agent Loop

## Decision: Implement as a Hermes plugin tool surface backed by a testable Python core

**Rationale**: The feature must be Hermes-native and expose run control, status, message submission, and decision recording to the main session without making the main session impersonate workers. Hermes plugins can register tools through the existing registry, while a Python core keeps FSM logic testable outside a live session.

**Alternatives considered**:
- Pure skill: rejected because skills cannot own durable runtime state, enforce routing, or expose structured tool calls.
- External frameworks such as LangGraph/CrewAI/AutoGen: rejected by scope and because they would make Hermes a worker rather than the orchestration host.
- Direct changes to Hermes core first: rejected for MVP because a plugin boundary proves behavior with lower blast radius.

## Decision: Use project-local runtime as authoritative state

**Rationale**: Clarification requires flow state, inboxes, decisions, artifacts, and audit trail to belong to the project. A project-local runtime can be version-adjacent, auditable, resumable, and independent of individual worker profile histories.

**Alternatives considered**:
- Hermes profile/session state as authority: rejected because worker profiles are execution identities and may have isolated or long-memory behavior that should not own flow truth.
- Kanban board as authority: rejected because the feature is state-machine and message-routing centric, not task-board centric.
- Dual-authority writes: rejected because conflict resolution would add complexity and undermine a clear resume source.

## Decision: Store durable runtime in per-run SQLite plus project-local artifacts

**Rationale**: The runtime needs atomic transition updates, strict gate evaluation, zero-delivery message rejection, resumability, and audit queries. SQLite is available through Python's standard library and matches Hermes' existing preference for durable local state. Human-readable artifacts remain as files referenced by the runtime.

**Alternatives considered**:
- JSON files only: rejected because atomic multi-entity updates and queryable audit history are harder to validate reliably.
- In-memory runtime: rejected because resume and audit are core user stories.
- External database: rejected as unnecessary infrastructure for a project-local MVP.

## Decision: Full Hermes worker sessions/profiles are canonical agent execution units

**Rationale**: Clarification selected full worker sessions/profiles. This satisfies separate soul, skills, toolsets, session identity, and optional memory mode. The project-local runtime prepares context packets and records outcomes; workers execute roles.

**Alternatives considered**:
- `delegate_task`: rejected as canonical behavior because it has weaker profile/session durability and hides child intermediate context from the project-local runtime.
- Kanban workers: rejected as canonical behavior because they shift the feature toward task-board semantics.
- Hybrid execution from day one: rejected as too broad for MVP; the data model can later add execution backends if evidence supports it.

## Decision: Persistent role profiles as templates; per-run sessions, inboxes, and artifacts isolated by default

**Rationale**: This balances reuse with isolation. Role profiles can carry stable soul/skills/toolsets while each run has its own context packet, inbox, artifacts, and state. Long-term memory is allowed only when explicitly configured and visible in status/audit.

**Alternatives considered**:
- Fresh profile per run: rejected because setup/debug cost is high and role templates become hard to maintain.
- Long-lived profile memory for all agents: rejected because context contamination is a primary risk.
- Fully per-role choice without default: rejected because the system needs safe behavior when the flow author omits a memory mode.

## Decision: Strict all-required gate semantics

**Rationale**: The workflow must not accidentally advance when a required reviewer has unresolved findings. Strict all-required semantics are predictable and align with the quality bar: every required approval/pass must be present before forward progress; change requests go to revision/fix; blocked decisions pause or escalate.

**Alternatives considered**:
- Majority vote: rejected because it can hide minority blocking issues and lead to unsafe progress.
- Role-weighted voting: rejected for MVP because it adds a second policy axis not required by the clarified spec.
- Human tie-break for every conflict: rejected because it would over-interrupt normal review loops.

## Decision: Atomic zero-delivery routing for invalid recipient sets

**Rationale**: The user clarified that each node's ability to accept messages must be checked before sending. If any intended recipient is invalid after validation, the entire send fails and no recipients receive the message. This avoids ambiguous partial delivery.

**Alternatives considered**:
- Auto-reroute to orchestrator: rejected because it hides routing policy errors.
- Automatically trim invalid recipients: rejected because sender intent and actual delivery diverge.
- Immediate human escalation: rejected because most routing mistakes can be fixed by the sender through a valid route.

## Decision: Tool contracts define Hermes flow tools, not network APIs

**Rationale**: The feature's user actions are Hermes tool calls, not public HTTP endpoints. A contract file still gives tests and future implementations a stable schema for `flow_init`, `flow_status`, `flow_step`, `flow_send`, `flow_decide`, and lifecycle controls.

**Alternatives considered**:
- REST API first: rejected as out of scope and unnecessary for a CLI/plugin MVP.
- No contract: rejected because tool inputs/outputs are central to validation and auditability.
