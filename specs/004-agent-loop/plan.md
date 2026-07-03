# Implementation Plan: Agent Loop — 事件驱动执行层

**Branch**: `004-agent-loop` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-agent-loop/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Build the execution layer that connects the passive FSM engine to active agent collaboration. Three new modules:

1. **agent_tools.py** — agent-facing wrappers around `flow_send`/`flow_decide`/inbox read, callable via `python -c` from a subagent's terminal tool.
2. **runtime_loop.py** — background daemon that polls the RuntimeStore every 1s, schedules agent sessions (concurrent per role), evaluates gates automatically, and handles idle timeouts.
3. **agent_session.py** — context packet preparation and result file parsing; bridges the loop (Python process) and agent subagents (delegate_task).

All three consume existing FSM components from features 001-003; no new storage or schema changes.

## Technical Context

**Language/Version**: Python 3.11+ (same as existing hermes_flow package)

**Primary Dependencies**: Python standard library (`sqlite3`, `json`, `datetime`, `logging`), existing `hermes_flow` modules (`engine`, `routing`, `storage`, `tools`, `trace`). No new external dependencies.

**Storage**: Existing project-local SQLite database at `.hermes-flow/runs/<run_id>/state.sqlite`. Runtime Loop reads/writes via RuntimeStore. Agent sessions access the store through agent_tools.py functions called via terminal `python -c` commands.

**Testing**: pytest. Key scenarios: agent tool wrappers call through to flow_send/flow_decide, runtime loop detects inbox messages and schedules sessions, runtime loop evaluates gate when all decisions present, multi-round discussion completes end-to-end.

**Target Platform**: Same as existing Hermes Flow — macOS and Linux first.

**Project Type**: Python library module (adds `hermes_flow/agent_tools.py`, `hermes_flow/runtime_loop.py`, `hermes_flow/agent_session.py`).

**Performance Goals**: Loop tick under 50ms for 10 active runs with 1000 inbox entries each. Agent session spawn (context write → delegate_task → result poll) under 2s overhead.

**Constraints**: No new external dependencies. Agent sessions use delegate_task + terminal tool — no Hermes worker profiles. Concurrent sessions limited by Hermes delegation max (configurable per run). Loop polls at 1s intervals (not event-driven).

**Scale/Scope**: Single-run, single-process execution. Cross-run scheduling and multi-host distribution out of scope.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Minimal Useful Scope**: PASS — Three modules map directly to the three user stories: agent tools (US1), runtime loop (US2), session management + multi-round discussion (US3). No speculative infrastructure.
- **Reusable Core Only**: PASS — agent_tools.py wraps existing flow_send/flow_decide (no new abstraction). runtime_loop.py is the single consumer of the scheduling pattern. agent_session.py's context packet format is consumed by exactly one spawner (the loop) and one parser (the result collector).
- **Readability**: PASS — Function names match domain concepts (agent_inbox_read, agent_message_send, submit_decision). Context packet structure mirrors the spec's entity definitions.
- **Evidence Before Expansion**: PASS — The need for agent-facing tools (Q1), timeout handling (Q2), and concurrent sessions (Q3) were all clarified during speckit-clarify. No speculative choices.
- **宁缺毋滥 Quality Bar**: PASS — Error branches are explicit (router rejection, session timeout, missing result file). Each module has a defined success/failure contract.

## Project Structure

### Documentation (this feature)

```text
specs/004-agent-loop/
├── plan.md              # This file
├── research.md          # Phase 0 — resolved from clarify session
├── data-model.md        # Phase 1 — ContextPacket, SessionResult, LoopTick
├── quickstart.md        # Phase 1 — integration walkthrough
└── contracts/
    └── agent-context-schema.yaml  # Phase 1 — context packet JSON schema
```

### Source Code (repository root)

```text
# NEW files:
hermes_flow/
├── agent_tools.py       # Agent-facing tool wrappers (inbox_read, message_send, submit_decision)
├── runtime_loop.py      # Event loop daemon (tick, schedule, gate eval, idle timeout)
└── agent_session.py     # Context packet builder + result file parser

# MODIFIED files:
hermes_flow/
└── tools.py             # Minor: extend as needed (none expected)

tests/hermes_flow/
├── test_agent_tools.py  # NEW — unit tests for agent-facing wrappers
├── test_runtime_loop.py # NEW — loop tick tests with mock store
└── test_agent_session.py# NEW — context packet builder tests
```

**Structure Decision**: Files added to the existing `hermes_flow/` package, consistent with features 001-003. No new package structure. Tests follow the existing `tests/hermes_flow/` convention.

## Complexity Tracking

No constitution violations — all three modules have well-defined boundaries:

| Boundary | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|--------------------------------------|
| `agent_tools.py` module | Wrapping flow_send/flow_decide into agent-callable one-liners; subagent cannot import and call tools.py directly | Inline in each subagent's goal string → duplicated, untestable |
| `runtime_loop.py` module | Single daemon managing inbox dispatch, gate eval, and timeout across ticks | Embedding in an existing module → violates single-responsibility; a cron job → loses fine-grained tick control |
| `agent_session.py` module | Context packet serialization is a distinct concern from loop tick logic | Inlining in runtime_loop.py → 250+ line file; testing context format in isolation becomes impossible |
