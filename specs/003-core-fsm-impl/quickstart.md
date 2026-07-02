# Quickstart: Core FSM Implementation

This quickstart describes how an AI debugging agent validates the FSM engine and message router.

## 1. Run a complete flow: init → send → decide → step

```python
from pathlib import Path
from hermes_flow.tools import flow_init, flow_status, flow_send, flow_decide, flow_step

# Start a run
result = flow_init(
    project_root=str(project_root),
    flow_path=str(flow_yaml_path),
)
run_id = result["run_id"]

# Check status
status = flow_status(run_id)
assert status["current_state_id"] == "planning"
assert status["pending_gate"] is None  # planning has no gate

# The tool handler is not yet calling engine, but the contract is:
#   flow_step(run_id) → evaluates gate → advances state

# Send a message
send_result = flow_send(
    run_id=run_id,
    state_id="planning",
    from_role="planner",
    intended_recipients=["developer"],
    kind="proposal",
    content="Implement feature X",
)
assert send_result["delivery_outcome"] == "delivered"
```

## 2. Test gate evaluation

```python
from hermes_flow.engine import evaluate_gate

# Load state from storage
flow_store = RuntimeStore(run_dir)
state = ...  # reconstruct from state_json

# If all required roles approved:
result = evaluate_gate(run_id, "review", flow_store)
assert result.satisfied is True
assert result.next_state_id == "approved"
assert result.outstanding_roles == []

# If a decision is blocked:
assert result.satisfied is False
assert result.next_state_id == "blocked"  # on_blocked value
assert result.reason == "blocked by reviewer: security concern"
```

## 3. Test route validation

```python
from hermes_flow.routing import validate_message

# Business-as-usual: all recipients valid
result = validate_message(
    run_id, "planning", "planner",
    ["developer", "reviewer"],
    routing_policies={"planner": ["developer", "reviewer"]},
    store=flow_store,
)
assert result.valid is True
assert result.invalid_recipients == []

# Unauthorized recipient → zero delivery
result = validate_message(
    run_id, "planning", "planner",
    ["developer", "outsider"],
    routing_policies={"planner": ["developer"]},
    store=flow_store,
)
assert result.valid is False
assert result.invalid_recipients == ["outsider"]
assert result.reason is not None
```

## 4. Test round counter exhaustion

```python
# After 3 revision rounds without approval:
result = evaluate_gate(run_id, "review", flow_store)
assert result.satisfied is False
assert result.round == 4  # round 4 triggers exhaustion
assert result.next_state_id == "escalation"  # on_exhausted target
assert result.reason == "round 4 exhausted (max_rounds=3)"
```

## 5. Test idle timeout

```python
from hermes_flow.engine import detect_idle_timeout

# If state has idle_timeout_seconds=3600 and last activity was >3600s ago
result = detect_idle_timeout(run_id, "review", flow_store, now=some_future_time)
assert result.timeout_exceeded is True
assert result.next_state_id == "escalation"
```

## 6. SQL queries for debug

```sql
-- View all transitions for a run
SELECT * FROM transitions WHERE run_id = '<run_id>' ORDER BY created_at;

-- View decisions that triggered a specific transition
SELECT d.* FROM decisions d
JOIN transitions t ON d.run_id = t.run_id
WHERE d.run_id = '<run_id>'
  AND d.state_id = t.from_state_id
  AND d.created_at > t.created_at  -- round filter
ORDER BY d.created_at;

-- Check round counters
SELECT run_id, round_counters FROM runs WHERE run_id = '<run_id>';
```
