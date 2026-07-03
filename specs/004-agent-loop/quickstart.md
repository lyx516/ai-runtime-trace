# Quickstart: Agent Loop — 事件驱动执行层

## 1. Start a flow with the Runtime Loop

```python
from pathlib import Path
from hermes_flow.runtime_loop import RuntimeLoop
from hermes_flow.storage import RuntimeStore

# After flow_init creates a run:
run_id = "abc123"
store = RuntimeStore(Path("/path/to/.hermes-flow/runs/abc123"))
store.init_schema()

# Create and start the runtime loop
loop = RuntimeLoop(run_id=run_id, store=store, tick_interval=1.0)
loop.start()  # blocks until run reaches terminal state
```

## 2. Agent reads its inbox and sends a message

```bash
# Inside the delegate_task subagent's terminal tool:
python -c "
from hermes_flow.agent_tools import agent_inbox_read, agent_message_send

# Read inbox
msgs = agent_inbox_read(run_id='abc123', role_id='reviewer')
for m in msgs:
    print(f'{m.from_role}: {m.content}')

# Send a message
result = agent_message_send(
    run_id='abc123',
    role_id='reviewer',
    state_id='REVIEW',
    intended_recipients=['architect'],
    kind='question',
    content='Should M be 32 instead of 16 for d=1000?',
)
print(f'Delivered: {result[\"delivery_outcome\"]}')
"
```

## 3. Agent submits a decision

```bash
python -c "
from hermes_flow.agent_tools import agent_submit_decision

result = agent_submit_decision(
    run_id='abc123',
    role_id='reviewer',
    state_id='REVIEW',
    value='APPROVE',
    reason='Design updated per feedback.',
)
print(f'Decision recorded: {result[\"decision_id\"]}')
"
```

## 4. Runtime Loop tick logic (simplified)

```python
def tick(self):
    run = self.store.load_status(self.run_id)
    if run.status in (COMPLETED, ABORTED):
        self._running = False
        return

    # 1. Schedule agents with unread inbox
    for role in self._state_actors(run.current_state_id):
        if self._has_unread_inbox(role) and not self._active_session(role):
            self._create_session(run.current_state_id, role)

    # 2. Collect completed sessions
    self._collect_results()

    # 3. Evaluate gate if all decisions in
    self._try_evaluate_gate(run)

    # 4. Check idle timeout
    self._check_idle_timeout(run)
```

## 5. Context packet file structure

```text
.hermes-flow/runs/<run_id>/sessions/
├── <session_id>.context.json    # Written by Loop, read by subagent
└── <session_id>.result.json     # Written by subagent, read by Loop
```

## 6. SQL queries for debug

```sql
-- View pending sessions
SELECT * FROM pending_actions ORDER BY created_at;

-- View inbox for a specific role
SELECT * FROM inboxes WHERE run_id = '<run_id>' AND role_id = '<role>';

-- View decisions for current round (by state entry timestamp)
SELECT d.* FROM decisions d
WHERE d.run_id = '<run_id>' AND d.state_id = '<state_id>'
ORDER BY d.created_at;

-- View trace events from loop ticks
SELECT * FROM trace_events WHERE run_id = '<run_id>' ORDER BY ts_start;
```
