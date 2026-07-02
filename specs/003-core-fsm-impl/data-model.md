# Data Model: Core FSM Implementation

## Entity: GateResult

Returned by `evaluate_gate()`. Describes the outcome of evaluating a state's gate.

**Fields**:
- `satisfied`: `bool` — true if all required roles submitted pass_values decisions
- `next_state_id`: `str` — the target state if a transition is needed (from gate's on_pass/on_fail/on_blocked/on_exhausted), or empty if not satisfied and no transition triggered
- `outstanding_roles`: `list[str]` — required roles that have not yet submitted a decision this round
- `round`: `int` — current round number for this state
- `reason`: `str` — human-readable explanation (e.g., "gate satisfied: all 2 roles approved", "round 3 exhausted, max_rounds=3")

**Validation rules**:
- `satisfied=True` → `next_state_id` MUST be non-empty
- `satisfied=False` and no transition triggered → `next_state_id` MUST be empty (caller determines next action)
- `round >= 0`
- `outstanding_roles` is empty when `satisfied=True`

## Entity: RouteValidation

Returned by `validate_message()`. Describes whether a message send is valid for the current state's routing policy.

**Fields**:
- `valid`: `bool` — true only if ALL intended recipients are both authorized AND available
- `authorized_recipients`: `list[str]` — recipients that pass the routing policy check
- `invalid_recipients`: `list[str]` — recipients not authorized by the current state's routing policy
- `unavailable_recipients`: `list[str]` — recipients whose state does not accept messages
- `reason`: `str | None` — null when valid, describes the first rejection reason when invalid

**Validation rules**:
- `valid=False` → `reason` MUST be non-empty
- If both invalid and unavailable recipients exist, the router reports both but still rejects the entire send
- `authorized_recipients + invalid_recipients == intended_recipients` (all recipients are classified)

## Entity: StateTransition

Persisted record of one state advancement (stored in `transitions` table via `RuntimeStore.record_transition`).

**Fields** (from existing storage.py):
- `run_id`: `str`
- `from_state_id`: `str`
- `to_state_id`: `str`
- `gate_result`: `str` — the trigger (e.g., "on_pass", "on_fail", "on_exhausted", "idle_timeout")
- `round_counter`: `int` — the round number at the time of transition
- `created_at`: `str` — ISO-8601 timestamp

## State Transition Flow

```text
State A (with gate)
  │
  ├── evaluate_gate()
  │     ├── satisfied=True (all pass_values)  →  advance_state(A → on_pass)
  │     ├── unsatisfied (fail_values)        →  round++ → advance_state(A → on_fail)
  │     ├── unsatisfied (blocked_values)     →  round++ → advance_state(A → on_blocked)
  │     ├── round >= max_rounds, still unsatisfied → advance_state(A → on_exhausted)
  │     └── outstanding roles remain         →  return pending status (no transition)
  │
  └── detect_idle_timeout()
        └── elapsed >= idle_timeout_seconds  →  advance_state(A → on_exhausted)

State B (no gate, terminal, or unknown)
  └── flow_step returns current status without advancing (per Clarify Q2)
```

### Round Counter Lifecycle

1. State is entered → `round_counters[state_id]` initialized to 1 (or absent → treated as 1)
2. `evaluate_gate` called:
   - Satisfied → advance_state, round counter for this state is no longer needed (state exited)
   - Unsatisfied (on_fail/on_blocked) → `round_counters[state_id] += 1`, advance_state
   - Unsatisfied but no decision yet → return without changing counter
3. `max_rounds=0` means unlimited rounds (never exhaust)
4. When `round_counters[state_id] > max_rounds` (and max_rounds > 0) → on_exhausted

### Decision-to-Round Filtering

Decisions must be filtered to the "current round" to avoid stale approvals:
- Query the `transitions` table for the last transition INTO this state
- Filter decisions by `created_at > transition.created_at`
- This naturally isolates decisions from previous rounds when the state is re-entered after revision
