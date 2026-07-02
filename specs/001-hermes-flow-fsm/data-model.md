# Data Model: Hermes Flow FSM Agent Loop

## Entity: FlowDefinition

Represents a reviewable project-local definition of a multi-agent flow.

**Fields**:
- `flow_id`: stable unique identifier within the project
- `name`: human-readable flow name
- `version`: flow definition version
- `agents`: map of `AgentRole` by role id
- `states`: map of `State` by state id
- `initial_state_id`: first state for new runs
- `terminal_state_ids`: states that end a run
- `routing_policies`: per-state sender/recipient rules
- `loop_defaults`: default maximum rounds and idle budgets

**Validation rules**:
- `initial_state_id` must exist in `states`.
- At least one terminal state must exist.
- Every transition target must reference an existing state.
- Every actor referenced by a state must reference an existing agent role.
- Every loop must declare a maximum round count and an escalation or abort path.
- Routing policies must not grant recipients that are unknown agent roles or unsupported recipient groups.

## Entity: AgentRole

Represents one declared participant in a flow.

**Fields**:
- `role_id`: unique role id within a flow
- `display_name`: user-facing name
- `soul`: role identity and behavioral constraints
- `profile_name`: persistent Hermes role profile template
- `skills`: allowed skills for this role
- `toolsets`: allowed toolsets for this role
- `read_scope`: artifact/context paths the role may receive
- `write_scope`: artifact paths the role may produce
- `workspace_mode`: default, isolated, or worktree-like workspace expectation
- `memory_mode`: `run_isolated` by default, or explicit `long_term`
- `max_action_seconds`: optional execution budget for one action

**Validation rules**:
- `role_id` must be unique.
- `soul`, `skills`, and `toolsets` must be explicit; no implicit full-access defaults.
- `memory_mode=long_term` must be visible in status and audit output.
- `write_scope` must not include project-wide unrestricted writes unless explicitly approved by a future spec.

## Entity: State

Represents one finite-state-machine node.

**Fields**:
- `state_id`: unique state id within the flow
- `description`: readable intent
- `actors`: one or more agent roles expected to act
- `input_artifacts`: artifacts visible in generated context packets
- `output_artifacts`: artifacts expected from this state
- `message_acceptance`: whether this state/node can currently receive messages
- `gate`: optional `Gate`
- `transitions`: possible next states by gate result or unconditional transition
- `max_rounds`: state-specific loop budget
- `on_exhausted`: escalation or abort state

**Validation rules**:
- Non-terminal states must have at least one outgoing transition.
- States participating in a loop must define `max_rounds`.
- If `actors` has multiple required roles, the gate must use strict all-required semantics.

## Entity: FlowRun

Represents one durable project-local execution of a flow definition.

**Fields**:
- `run_id`: unique run identifier
- `flow_id`: associated flow definition
- `flow_version`: definition version captured at run start
- `status`: `active`, `paused`, `completed`, `aborted`, or `escalated`
- `current_state_id`: current FSM state
- `round_counters`: per-state round count
- `created_at`, `updated_at`, `completed_at`
- `agent_bindings`: role id to worker profile/session information
- `memory_modes`: role id to memory mode used for this run
- `artifact_root`: project-local artifact directory for this run

**Validation rules**:
- A run cannot advance from a terminal state.
- Resuming a run must use the captured `flow_version` unless the user explicitly confirms applying a changed flow definition.
- Worker profile/session records are execution references only; runtime state remains authoritative in the project-local store.

## Entity: MessageEnvelope

Represents an attempted or delivered message.

**Fields**:
- `message_id`: unique message id
- `run_id`: flow run id
- `state_id`: state where message was attempted
- `from_role`: sender role id
- `intended_recipients`: explicit recipient list or group
- `authorized_recipients`: resolved recipients after policy validation
- `recipient_availability`: per-recipient can-accept result
- `visibility`: targeted, group, orchestrator, human, or all when allowed
- `kind`: proposal, question, review, decision, status, error, or audit
- `content`: message body or summary
- `artifacts`: referenced artifact ids/paths
- `requires_ack`: boolean
- `delivery_outcome`: `delivered` or `rejected`
- `rejection_reason`: required when rejected
- `created_at`

**Validation rules**:
- If any intended recipient is unauthorized or cannot currently accept messages, `delivery_outcome` is `rejected` and `authorized_recipients` must be empty.
- Delivered messages must be visible only to authorized recipients and later states allowed by flow policy.
- Rejected messages must remain in audit but must not enter any recipient inbox.

## Entity: Inbox

Represents the messages visible to a role for a state/run.

**Fields**:
- `run_id`
- `role_id`
- `state_id`
- `message_ids`
- `generated_at`

**Validation rules**:
- Inbox contents are derived from delivered message envelopes and policy; agents do not mutate inboxes directly.
- Rejected messages never appear in inboxes.

## Entity: Artifact

Represents a project-local work product.

**Fields**:
- `artifact_id`
- `run_id`
- `state_id`
- `produced_by_role`
- `path`
- `artifact_type`: plan, tasks, review, implementation-report, convergence-report, context-packet, audit-export, or other declared type
- `visibility_scope`
- `created_at`

**Validation rules**:
- Producer role must have write permission for the artifact path.
- Consumers must have read permission or receive the artifact through a state context packet.

## Entity: Gate

Represents a state advancement rule.

**Fields**:
- `gate_id`
- `type`: decision, acknowledgement, artifact-marker, human-approval, or unconditional
- `required_roles`
- `pass_values`: values such as APPROVE or PASS
- `fail_values`: values such as REQUEST_CHANGES or FAIL
- `blocked_values`: values such as BLOCKED
- `on_pass`, `on_fail`, `on_blocked`, `on_exhausted`
- `max_rounds`

**Validation rules**:
- For multiple required roles, every required role must submit a pass value before forward progress.
- Any fail value routes to revision/fix according to the state transition.
- Any blocked value pauses or escalates according to the state transition.

## Entity: Decision

Represents one actor's gate or routing-related decision.

**Fields**:
- `decision_id`
- `run_id`
- `state_id`
- `role_id`
- `value`
- `reason`
- `artifacts`
- `created_at`

**Validation rules**:
- `value` must be allowed by the current gate.
- A decision must be attributable to a role allowed to decide in the current state.

## State Transitions

```text
FlowRun.status:
active -> paused       when human or system pause occurs
active -> completed    when terminal completed state is reached
active -> escalated    when autonomous progress is unsafe or exhausted
active -> aborted      when user or policy aborts
paused -> active       when user resumes
escalated -> active    when user selects a continuation path
```

```text
Gate outcome:
all required pass -> on_pass
any fail          -> on_fail revision/fix
any blocked       -> on_blocked pause/escalate
max rounds hit    -> on_exhausted escalation/abort
```

```text
Message delivery:
created -> validating_recipients -> delivered
created -> validating_recipients -> rejected_zero_delivery
```
