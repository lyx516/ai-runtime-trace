# Research: Span Tree Trace

All unclear design points from the spec were resolved during speckit-clarify (Session 2026-07-02). No Phase 0 research was required.

## Resolved Decisions

| Decision | Outcome | Source |
|----------|---------|--------|
| Write strategy | 1-write on `__exit__` + `atexit` flush | Clarify Q1 |
| Write failure policy | Swallow + `logging.warning`, main op continues | Clarify Q2 |
| Tracer wiring | Explicit `set_tracer(SqliteTracer(store))` in `flow_init()` | Clarify Q3 |
