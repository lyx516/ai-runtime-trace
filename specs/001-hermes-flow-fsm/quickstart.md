# Quickstart: Hermes Flow FSM Agent Loop

This quickstart describes the first end-to-end validation path for the Hermes Flow MVP.

## 1. Prepare a sample project flow

Create a project-local flow definition such as `.hermes-flow/flows/simple-plan-review.yaml`:

```yaml
flow_id: simple-plan-review
name: Simple Plan Review
version: 1
initial_state_id: PLAN
terminal_state_ids: [DONE, ABORT]

agents:
  planner:
    profile_name: flow-planner
    soul: Produce minimal executable plans.
    skills: [speckit-plan]
    toolsets: [file]
    memory_mode: run_isolated
    read_scope: [spec.md]
    write_scope: [artifacts/plan.md]
  reviewer:
    profile_name: flow-reviewer
    soul: Review plans for scope and testability.
    skills: [speckit-analyze]
    toolsets: [file]
    memory_mode: run_isolated
    read_scope: [spec.md, artifacts/plan.md]
    write_scope: [artifacts/reviews/plan-review.md]

states:
  PLAN:
    actors: [planner]
    output_artifacts: [artifacts/plan.md]
    transitions:
      on_complete: REVIEW
  REVIEW:
    actors: [reviewer]
    gate:
      type: decision
      required_roles: [reviewer]
      pass_values: [APPROVE, PASS]
      fail_values: [REQUEST_CHANGES, FAIL]
      blocked_values: [BLOCKED]
      on_pass: DONE
      on_fail: PLAN
      on_blocked: HUMAN_ESCALATION
      max_rounds: 3
  HUMAN_ESCALATION:
    human: true
    transitions:
      resume: PLAN
      abort: ABORT
  DONE:
    terminal: true
  ABORT:
    terminal: true
```

## 2. Validate and initialize a run

From the project root, call the Hermes Flow init tool through Hermes or the local debug entry point:

```bash
python -m hermes_flow.cli init --flow .hermes-flow/flows/simple-plan-review.yaml --project-root .
```

Expected result:

- A new run id is returned.
- `.hermes-flow/runs/<run_id>/state.sqlite` exists.
- Status reports `current_state_id=PLAN`.
- Agent bindings show full Hermes worker profile/session references.

## 3. Check status

```bash
python -m hermes_flow.cli status --run-id <run_id>
```

Expected result:

- Current state, pending actor, pending gate, memory modes, artifact root, and next action are visible.
- The project-local runtime is sufficient to inspect the run without opening worker profile histories.

## 4. Validate atomic routing

Attempt to send a message from `planner` to one valid recipient and one invalid recipient:

```bash
python -m hermes_flow.cli send --run-id <run_id> --state PLAN --from planner --to reviewer,unknown_role --kind proposal --content "plan ready"
```

Expected result:

- Delivery outcome is `rejected`.
- Rejection reason identifies the invalid recipient.
- No recipient inbox receives the message.
- The rejected envelope appears only in audit with a zero delivery outcome.

## 5. Advance through a strict gate

Record a reviewer decision:

```bash
python -m hermes_flow.cli decide --run-id <run_id> --state REVIEW --role reviewer --value APPROVE --reason "plan is scoped and testable"
```

Expected result:

- Gate status becomes satisfied only after every required role has a pass value.
- The next `step` advances to `DONE`.
- If the reviewer submits `REQUEST_CHANGES`, the run returns to `PLAN` until the loop budget is exhausted.

## 6. Resume validation

Stop the main session or process after a non-terminal state, then run:

```bash
python -m hermes_flow.cli status --run-id <run_id>
python -m hermes_flow.cli step --run-id <run_id>
```

Expected result:

- The run resumes from the project-local runtime.
- Completed state actions are not replayed unless a retry is explicitly requested.

## 7. Audit validation

Export the audit trail:

```bash
python -m hermes_flow.cli audit --run-id <run_id>
```

Expected result:

- State transitions, delivered messages, rejected messages, gate decisions, escalations, and terminal outcome are all present.
- Each rejected message includes intended recipients, recipient availability, routing decision, and zero-delivery outcome.
