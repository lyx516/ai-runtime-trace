# Implementation Plan: Hermes Flow FSM Agent Loop

**Branch**: `001-hermes-flow-fsm` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-hermes-flow-fsm/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Build a Hermes-native finite-state-machine orchestrator for bounded multi-agent collaboration. The implementation exposes a small Hermes tool surface backed by a project-local runtime store. Each agent role executes as a full Hermes worker session/profile, while the project-local runtime remains the authoritative source for flow state, inboxes, decisions, artifacts, gate results, and audit trail. The MVP emphasizes correctness, context isolation, strict all-required gates, atomic message routing, and resumability before dashboard or fleet-scale concerns.

## Technical Context

**Language/Version**: Python 3.11+ compatible with the existing Hermes Agent runtime

**Primary Dependencies**: Python standard library (`sqlite3`, `json`, `subprocess`, `pathlib`, `dataclasses`), PyYAML already used by Hermes, Hermes plugin/tool registry, Hermes profile/session CLI

**Storage**: Project-local runtime directory `.hermes-flow/` with per-run `state.sqlite`, generated context packets, inbox records, artifacts, and audit log exports

**Testing**: pytest unit tests for engine/storage/routing plus integration tests that exercise the Hermes tool contract through a temporary project runtime; until a canonical suite exists, use focused ad-hoc verification scripts for generated artifacts

**Target Platform**: Hermes CLI environments on macOS and Linux first; design avoids platform-specific shell assumptions so Windows support can follow Hermes' existing profile and subprocess behavior

**Project Type**: Python library plus Hermes plugin/tool surface

**Performance Goals**: Start a valid three-agent flow and report initial state within 30 seconds; status queries complete within 1 second for a typical run; routing and gate evaluation complete within 500 ms for 10 agents and 1,000 recorded messages

**Constraints**: Project-local runtime is authoritative; worker profiles execute agents but do not own business state; message sends are atomic with zero delivery if any intended recipient is invalid; gates use strict all-required semantics; default memory mode isolates sessions/inboxes/artifacts per run; long-term memory is opt-in per role; no external orchestration framework dependency

**Scale/Scope**: MVP supports one project-local flow definition at a time, multiple resumable runs in the same project, 3-10 typical agents per run, and enough audit history for planning/development/review loops; cross-project fleet scheduling and dashboard views are deferred

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Minimal Useful Scope**: PASS — MVP is limited to project-local FSM orchestration, role profiles, scoped routing, gates, persistence, and resume/status. Dashboard, external orchestrators, arbitrary workflow programs, and fleet management remain out of scope.
- **Reusable Core Only**: PASS — Shared modules are limited to boundaries with multiple current consumers: schemas are used by loader/storage/engine/tests; routing policy is used by send/status/audit; storage is used by all tools; context projection is used by worker dispatch and tests.
- **Readability**: PASS — Flow, state, gate, message, inbox, artifact, and memory-mode terms are explicit in spec and mirrored in planned schemas/contracts.
- **Evidence Before Expansion**: PASS — Choices are driven by clarified requirements: full worker sessions/profiles, project-local authority, strict gates, opt-in long memory, and atomic zero-delivery routing.
- **宁缺毋滥 Quality Bar**: PASS — Plan excludes best-effort routing, hidden profile-owned state, speculative integrations, and implicit memory sharing.

## Project Structure

### Documentation (this feature)

```text
specs/001-hermes-flow-fsm/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── flow-tools.openapi.yaml
└── tasks.md             # Phase 2 output from speckit-tasks, not created here
```

### Source Code (repository root)

```text
hermes_flow/
├── __init__.py
├── schemas.py           # FlowDefinition, AgentRole, State, Gate, MessageEnvelope, FlowRun models
├── flow_loader.py       # Load and validate project-local flow definitions
├── storage.py           # Project-local runtime persistence and audit trail
├── engine.py            # FSM step, transition, gate, loop-budget evaluation
├── routing.py           # Recipient availability and atomic zero-delivery routing checks
├── context.py           # State-specific context packet generation
├── worker.py            # Full Hermes worker session/profile dispatch and resume adapter
├── tools.py             # Tool handlers exposed by plugin registration
└── cli.py               # Local validation/debug entry points

plugins/hermes-flow/
├── plugin.yaml
└── __init__.py          # Registers flow_* tools with Hermes plugin context

tests/hermes_flow/
├── test_flow_loader.py
├── test_storage.py
├── test_routing.py
├── test_engine_gates.py
├── test_context_projection.py
└── test_tool_contracts.py
```

**Structure Decision**: Use a small importable `hermes_flow` package for core logic and a thin `plugins/hermes-flow` adapter for Hermes tool registration. This keeps the FSM testable without a live Hermes session while still delivering the requested Hermes-native tool surface.

## Complexity Tracking

No constitution violations are required. The only shared boundaries are justified by isolation or multiple concrete consumers:

| Boundary | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|--------------------------------------|
| `storage.py` project-local runtime | Used by init/status/step/send/decide/resume/audit tools | Storing state only in worker sessions violates project-local authority and makes resume/audit unreliable |
| `routing.py` policy module | Used by flow validation, send, status, tests, and audit | Inline routing would risk inconsistent zero-delivery behavior across tools |
| `context.py` projection module | Used by worker dispatch and tests to enforce context isolation | Passing raw session history would violate scoped inbox/artifact requirements |
| `worker.py` adapter | Encapsulates full Hermes worker session/profile execution | Using `delegate_task` directly cannot satisfy canonical profile/session isolation |

## Phase 0 Research Summary

See [research.md](./research.md). All planning questions are resolved; no unresolved clarification markers remain.

## Phase 1 Design Summary

See [data-model.md](./data-model.md), [contracts/flow-tools.openapi.yaml](./contracts/flow-tools.openapi.yaml), and [quickstart.md](./quickstart.md).

## Post-Design Constitution Check

- **Minimal Useful Scope**: PASS — Generated design covers only the MVP tool surface and project-local runtime required by the five user stories.
- **Reusable Core Only**: PASS — Each planned module has at least two immediate consumers or is an isolation/safety boundary.
- **Readability**: PASS — Contracts and data model use canonical terms from the spec and expose observable outcomes for routing, gates, and resume.
- **Evidence Before Expansion**: PASS — Research records alternatives rejected for each major design choice.
- **宁缺毋滥 Quality Bar**: PASS — Ambiguous behavior is resolved: no partial message delivery, no implicit long-term memory, no majority-vote gates, no hidden profile-owned authority.

## Agent Context Update

Skipped for Hermes. The Spec Kit script supports agent types such as claude, codex, copilot, gemini, and generic; Hermes is not a supported update target in this project. Planning artifacts are complete without an agent context update.
