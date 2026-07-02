# Implementation Plan: Core FSM Implementation

**Branch**: `003-core-fsm-impl` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-core-fsm-impl/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Implement the two remaining stub modules in Hermes Flow FSM — the FSM Engine (gate evaluation, state transitions, loop budget, idle timeout) and the Message Router (recipient validation, atomic zero-delivery). Also implement the 7 tool handler stubs: flow_status, flow_step, flow_send, flow_decide, flow_pause, flow_resume, flow_abort. All 3 user stories are P1/P2 and unblock the next iteration of multi-agent flow runs.

## Technical Context

**Language/Version**: Python 3.11+ (same as existing hermes_flow package)

**Primary Dependencies**: Python standard library (`sqlite3`, `json`, `datetime`, `logging`). No new external dependencies. Existing `RuntimeStore` methods (`load_decisions`, `record_transition`, `update_status`, `record_message_attempt`, `add_inbox_entries`, `append_audit_event`, `list_visible_messages`) cover all persistence needs.

**Storage**: Existing project-local SQLite database at `.hermes-flow/runs/<run_id>/state.sqlite`. Engine and Router are stateless — they read from and write to RuntimeStore.

**Testing**: pytest. Key scenarios: gate evaluation (approve/pass/blocked), round counter exhaustion, idle timeout, router validation (authorized+available, unauthorized, unavailable), tool handler integration (end-to-end init → send → decide → step → pause → resume → abort).

**Target Platform**: Same as existing Hermes Flow — macOS and Linux first.

**Project Type**: Python library module (implements `hermes_flow/engine.py`, `hermes_flow/routing.py`, patches `hermes_flow/tools.py`).

**Performance Goals**: Gate evaluation under 10ms for 10 required roles. Router validation under 5ms. flow_step end-to-end under 50ms.

**Constraints**: Round counter increments only on gate unsatisfied (on_fail/on_blocked). Decisions for current round filtered by transition timestamp (Clarify Q1). flow_step does not auto-advance through gapless states (Clarify Q2). No new external dependencies.

**Scale/Scope**: Single-run stateless evaluation. No cross-run dependencies. 10 agents, 1000 messages, 100 decisions per state.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Minimal Useful Scope**: PASS — The feature implements exactly what was stubbed in feature 001 (engine, router, 7 tool handlers). Status, step, send, decide, pause, resume, abort are the minimum set for a working multi-agent FSM.
- **Reusable Core Only**: PASS — Engine.evaluate_gate is consumed by flow_step and flow_status. Router.validate_message is consumed by flow_send. Both modules are independent and testable.
- **Readability**: PASS — GateResult and RouteValidation field names mirror the existing GateStatus and Decision schemas. Function signatures are self-documenting.
- **Evidence Before Expansion**: PASS — Every design decision (round counter semantics, gapless state behavior) was clarified during speckit-clarify.
- **宁缺毋滥 Quality Bar**: PASS — If validation fails, the router rejects zero messages. If gate is unsatisfied, the engine does not advance. Error branches are explicit.

## Project Structure

### Documentation (this feature)

```text
specs/003-core-fsm-impl/
├── plan.md              # This file
├── research.md          # Phase 0 — clarified decisions
├── data-model.md        # Phase 1 — GateResult, RouteValidation, transition flow
├── quickstart.md        # Phase 1 — integration scenarios
└── contracts/
    └── engine-router-schemas.yaml  # Phase 1 — self-describing schemas
```

### Source Code (repository root)

```text
# NEW files:
hermes_flow/
├── engine.py             # FSM Engine — gate eval, state transition, loop budget, idle timeout
└── routing.py            # Message Router — recipient validation, atomic zero-delivery

# MODIFIED files:
hermes_flow/
└── tools.py              # Implement flow_status, flow_step, flow_send, flow_decide,
                          #   flow_pause, flow_resume, flow_abort (replacing NotImplementedError stubs)

tests/hermes_flow/
├── test_engine.py        # NEW — engine unit tests
├── test_routing.py       # NEW — router unit tests
└── test_tools.py         # NEW — tool handler integration tests
```

**Structure Decision**: Two new modules (`engine.py`, `routing.py`) that consume existing RuntimeStore methods and schemas. No new package structure. Tools.py patches replace 7 stub functions with real implementations.

## Complexity Tracking

No constitution violations. Engine and Router are standalone modules with well-defined boundaries:

| Boundary | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|--------------------------------------|
| `engine.py` module | Evaluate gate + detect timeout + advance state is a distinct concern consumed by tools.py | Inlining into tools.py would make flow_step 200+ lines; testing gate logic in isolation becomes impossible |
| `routing.py` module | Recipient validation is a pure function with defined inputs/outputs | Inline validation in flow_send would duplicate the same logic across multiple future message-sending code paths |
