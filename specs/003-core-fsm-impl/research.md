# Research: Core FSM Implementation

All unclear design points were resolved during speckit-clarify (Session 2026-07-02). No Phase 0 research was required.

## Resolved Decisions

| Decision | Outcome | Source |
|----------|---------|--------|
| Round counter semantics | Increment only on unsatisfied (on_fail/on_blocked); filter decisions by transition timestamp | Clarify Q1 |
| Gapless state flow_step | Return current status, do NOT auto-advance; caller decides next call | Clarify Q2 |
