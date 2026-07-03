# Data Model: Agent Loop — 事件驱动执行层

## Entity: AgentContextPacket

Serialized to a JSON file by the Runtime Loop, read by the agent subagent via terminal/file tools.

**Fields**:
- `run_id`: `str` — the flow run identifier
- `session_id`: `str` — unique session identifier (used for trace correlation)
- `role_id`: `str` — the agent role (e.g., "architect", "reviewer")
- `soul`: `str` — the role's personality definition (verbatim from AgentRole.soul)
- `state_id`: `str` — the current state's identifier
- `state_description`: `str` — human-readable state purpose
- `gate_info`: `dict | null` — current gate configuration (required_roles, pass_values, fail_values) if state has a gate
- `inbox_messages`: `list[dict]` — each with `message_id`, `from_role`, `kind`, `content`, `created_at`; sorted by created_at ascending
- `visible_artifacts`: `list[dict]` — each with `artifact_id`, `path`, `produced_by_role`, `created_at`
- `pending_decisions`: `list[dict]` — decisions already submitted this round by other roles; each with `role_id`, `value`, `reason`
- `available_tools`: `list[str]` — tool names the agent may call; always `["inbox_read", "message_send", "submit_decision", "query_status"]`
- `discussion_history`: `list[dict]` — all messages exchanged in this state visit (inbox + sent), chronologically ordered

**Validation rules**:
- `run_id`, `session_id`, `role_id`, `state_id` MUST be non-empty
- `available_tools` MUST contain at least `message_send` and `submit_decision`
- `inbox_messages` MAY be empty (first entry into state)

---

## Entity: SessionResult

JSON file written by the agent subagent, read and parsed by the Runtime Loop.

**Fields**:
- `session_id`: `str` — matches the session_id from the context packet
- `actions_taken`: `list[dict]` — each action is one of:
  - `{"type": "message_send", "recipients": [...], "kind": "...", "content": "..."}`
  - `{"type": "submit_decision", "value": "...", "reason": "..."}`
  - `{"type": "read_artifact", "path": "..."}`
  - `{"type": "write_artifact", "path": "...", "content": "..."}`
- `exited_early`: `bool` — true if the agent chose to exit without submitting a decision (expecting further discussion)
- `error`: `str | null` — error message if the session encountered a problem
- `completed_at`: `str` — ISO-8601 timestamp

**Validation rules**:
- `session_id` MUST match the context packet's session_id (the loop validates this)
- If `actions_taken` contains `submit_decision`, the `value` field MUST be one of the gate's configured values (pass/fail/blocked)
- If `error` is non-null, the loop logs the error and does not process `actions_taken`

---

## Entity: LoopTickResult

Internal state of one Runtime Loop tick for a single run. Not persisted — used for loop logic and trace events.

**Fields**:
- `run_id`: `str`
- `current_state_id`: `str`
- `active_sessions`: `list[str]` — session_ids currently in progress
- `pending_inbox_roles`: `list[str]` — roles with unread inbox but no active session
- `gate_evaluated`: `bool` — whether evaluate_gate was called this tick
- `gate_satisfied`: `bool | null` — result of gate evaluation (null if not evaluated)
- `transition_taken`: `str | null` — state transition that occurred (null if none)
- `idle_timeout_triggered`: `bool`
- `tick_duration_ms`: `float`

---

## Relationships

```
RuntimeLoop (1) ──tick──> LoopTickResult (many)
RuntimeLoop (1) ──spawns──> AgentContextPacket (many per state)
AgentContextPacket (1) ──produces──> SessionResult (1)
SessionResult ──records──> actions_taken[]
actions_taken[type=message_send] ──calls──> flow_send() ──persists──> MessageEnvelope + InboxEntry
actions_taken[type=submit_decision] ──calls──> flow_decide() ──persists──> Decision + AuditEvent
```

## State Machine: Runtime Loop Lifecycle

```text
[START] ──create loop──> [RUNNING]
                            │
                            ├── tick()
                            │     ├── check inbox → schedule sessions
                            │     ├── check sessions → collect results
                            │     ├── check gate → evaluate / advance
                            │     └── check idle timeout
                            │
                            ├── run becomes COMPLETED/ABORTED ──> [STOPPED]
                            └── loop process killed ──> [STOPPED]
```

No persistence required for loop state — loop is stateless between ticks, reading all state from RuntimeStore.
