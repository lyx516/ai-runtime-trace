# Hermes Flow FSM — Project Overview

## What This Is

A **multi-agent execution engine** for Hermes Agent. Define a workflow in YAML
(roles, states, gates), and the Runtime Loop drives it automatically: dispatches
agent sessions, collects decisions, evaluates gates, and advances states.

```
flow.yaml → flow_init → RuntimeLoop → auto-run → DONE
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  RuntimeLoop (runtime_loop.py)                           │
│  Central daemon, ticks every N seconds.                  │
│  Tick: dispatch → collect → gate → advance               │
└──────┬───────────────────────┬───────────────────────────┘
       │ subprocess mode       │ delegate mode
       ▼                       ▼
┌──────────────┐    ┌──────────────────────────────┐
│ agent_runner │    │ _manifest.json (written by    │
│ (thread)     │    │ RuntimeLoop)                   │
│              │    │  → Hermes agent scans          │
│ Python rule  │    │  → delegate_task(subagent)     │
│ engine       │    │  → LLM reads goal, thinks,    │
│              │    │    calls agent_tools.py,       │
│              │    │    writes result.json          │
└──────────────┘    └──────────────────────────────┘
       │                       │
       ▼                       ▼
┌──────────────────────────────────────────────────────────┐
│  agent_tools.py                                         │
│  inbox_read / message_send / submit_decision / status   │
│  → wraps tools.py → wraps store.py                     │
└──────────────────────────────────────────────────────────┘
```

## Directory Structure

```
hermes_flow/
├── engine.py          # FSM: evaluate_gate, advance_state, detect_idle_timeout
├── routing.py         # Message routing & validation
├── flow_loader.py     # YAML → FlowDefinition + validate_flow()
├── tools.py           # flow_init/send/decide/status/resume
├── storage.py         # SQLite: runs/states/decisions/messages/inboxes/audit
├── schemas.py         # FlowStatus, Decision, enums
├── errors.py          # RuntimeStateError
├── trace.py           # Span tracer (NoOpTracer / SqliteTracer)

├── runtime_loop.py    # RuntimeLoop: tick cycle, dispatch, collect, gate
├── agent_tools.py     # Agent-facing tool wrappers
├── agent_runner.py    # Session executor (rule engine / subprocess mode)
├── agent_session.py   # Context packet builder + file I/O
├── delegate_spawner.py# Manifest bridge + build_delegate_goal()
└── observer.py        # HTTP server: REST API + SSE + dashboard

specs/004-agent-loop/
├── spec.md            # Feature spec (FR, user stories)
├── plan.md            # Implementation plan
├── data-model.md      # AgentContextPacket, SessionResult entities
├── contracts/         # JSON schema
├── tasks.md           # Task breakdown
└── progress-and-vision.md  # Current vs future

experiments/vector-db/
├── exp-flow.yaml           # 2-agent flow (DESIGN→IMPLEMENT→REVIEW→DONE)
├── exp-flow-revision.yaml  # Multi-round discussion flow
├── exp-flow-three-agent.yaml  # 3-agent broadcast test
└── exp-flow-five-agent.yaml   # 5-agent stress test
```

## Two Modes

| Mode | Config | How agents run | Best for |
|------|--------|---------------|----------|
| **subprocess** | `spawn_mode='subprocess'` | Thread + Python rule engine | CI, testing, demos |
| **delegate** | `spawn_mode='delegate'` | Manifest → Hermes delegate_task → LLM | Production, real discussion |

Both are verified end-to-end with multi-round discussion (revision loops).

## Verified Capabilities

- 2-agent discussion with revision loop
- 3-agent broadcast/multicast with concurrent dispatch
- 5-agent concurrent dispatch with 5-role gate
- Message isolation (inbox per role, no cross-contamination)
- Self-loop state transitions (on_fail → same state)
- Human escalation (state with `human: true` pauses loop)
- Round counter with max_rounds exhaustion
- Inbox consumption (read once, removed)
- flow_resume from any state
- Observer dashboard (state flow graph + REST API + SSE)

## How to Run

```python
from hermes_flow.tools import flow_init
from hermes_flow.runtime_loop import RuntimeLoop

result = flow_init(project_root='.', flow_path='flow.yaml', run_name='demo')
run_id = result['run_id']

store = RuntimeStore(Path(...))
loop = RuntimeLoop(run_id, store, spawn_mode='subprocess')
loop.start()  # blocks until DONE
```

Or with observer:

```python
from hermes_flow.observer import FlowObserver
obs = FlowObserver(port=8080, project_root='.')
obs.start()

loop = RuntimeLoop(run_id, store, spawn_mode='delegate')
import threading
t = threading.Thread(target=loop.start, daemon=True)
t.start()

# From another terminal:
# Hermes spawner scans manifest → calls delegate_task for each session
```

## Current Gaps

### P0 — Blocking (all resolved)
- ✅ Flow validation (validate_flow in flow_init)
- ✅ Sender permission check (from_role must be registered agent)
- ✅ delegate_task automation (manifest + broker)
- ✅ LLM-driven discussion (goal built, bridge ready, agent_runner simulates)

### P1 — Important
- ✅ flow_resume (exists, observer UI supports "restart from state")
- ✅ Human escalation (state with human: true pauses loop)

### P2 — Nice-to-have
- ❌ Other gate types: acknowledgement, artifact, human approval
- ❌ read_scope / write_scope context isolation
- ❌ Profile template system (agent_bindings but no template)
- ❌ memory_mode enforcement
- ❌ Session timeout per agent session
- ❌ Flow definition change detection on active run
- ❌ Hermes plugin / `hermes flow run` CLI
- ❌ Trace analysis CLI (`hermes flow analyze`)

## Future Direction

### Phase B — Flow CLI
```
hermes flow create review-pipeline   # Scaffold flow YAML
hermes flow validate flow.yaml        # Pre-flight check
hermes flow run flow.yaml --detach    # Start + detach
hermes flow status <run_id>           # Check progress
```

### Phase C — Real LLM Agents
The bridge is built. Replace `agent_runner.py`'s rule-based decision engine
with actual Hermes `delegate_task` subagents. The subagent receives
`build_delegate_goal()` output — a rich prompt with:
- Role identity & personality (soul)
- Current state & gate conditions
- Inbox messages & discussion history
- Ready-to-copy `python -c` commands for agent_tools.py

The subagent uses its terminal tool to call agent_tools, thinks (LLM),
and writes the result file. This gives each agent **real LLM reasoning**
during discussion.

### Phase D — Observability
Current observer has REST + SSE + dashboard. Future:
- `hermes flow analyze <run_id>` → trace span tree + timing report
- Real-time SSE push during agent discussion
- DAG visualization with agent decision bubbles
- Audit trail export

## Key Files for New Developers

| File | What to read first |
|------|-------------------|
| `specs/004-agent-loop/progress-and-vision.md` | Full vision doc |
| `specs/004-agent-loop/spec.md` | Feature spec with all FRs |
| `specs/004-agent-loop/data-model.md` | AgentContextPacket, SessionResult |
| `specs/004-agent-loop/contracts/agent-context-schema.yaml` | File schema |
| `specs/004-agent-loop/plan.md` | Implementation plan |
| `hermes_flow/runtime_loop.py` | Core loop (start here) |
| `hermes_flow/agent_runner.py` | Session executor |
| `hermes_flow/agent_session.py` | Context packet logic |
| `hermes_flow/delegate_spawner.py` | Hermes bridge |
| `hermes_flow/observer.py` | Dashboard |
