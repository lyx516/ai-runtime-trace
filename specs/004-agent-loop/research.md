# Research: Agent Loop — 事件驱动执行层

All design decisions were resolved during speckit-clarify (Session 2026-07-02). No additional Phase 0 research was required beyond reading existing source code.

## Resolved Decisions

| Decision | Outcome | Source |
|----------|---------|--------|
| Agent session execution mechanism | Hermes subprocess + terminal call: Loop writes context file, spawns delegate_task subagent, subagent runs `python -c` commands to call agent_tools.py functions | Clarify Q1 |
| Required agent timeout handling | No special action; loop relies on state's `idle_timeout_seconds` to naturally trigger `on_exhausted`. If not configured, run waits indefinitely. | Clarify Q2 |
| Concurrent vs sequential session scheduling | Concurrent: all actors with unread inbox get sessions on the same tick | Clarify Q3 |

## Source Code References

- `hermes_flow/engine.py` — `evaluate_gate`, `advance_state`, `detect_idle_timeout` (all consumed by runtime_loop.py)
- `hermes_flow/tools.py` — `flow_send`, `flow_decide` (wrapped by agent_tools.py)
- `hermes_flow/storage.py` — `RuntimeStore` methods (`load_decisions`, `record_transition`, `load_status`, `record_message_attempt`, `append_audit_event`, `list_inbox_entries`)
- `hermes_flow/schemas.py` — data models (`Decision`, `MessageEnvelope`, `FlowStatus`, `RunStatus`)
- `hermes_flow/trace.py` — `get_tracer`, `NoOpTracer`, `SqliteTracer`

All source code confirmed: no new storage methods, no schema changes needed. The RuntimeStore already provides all required query capabilities.
