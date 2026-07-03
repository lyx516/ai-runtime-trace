# Tasks: 可观测性升级

**Input**: Design documents from `/specs/005-observability-upgrade/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/README.md

**Tests**: Not included — spec does not request explicit test tasks. Validation via Independent Test criteria per user story.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project at repository root
- `hermes_flow/` — existing package, new modules go here
- `dashboard/` — standalone HTML/JS directory at repo root

---

## Phase 1: Setup

**Purpose**: Create new directory structure for this feature

- [x] T001 [P] Create `hermes_flow/cli/` package with `__init__.py`
- [x] T002 [P] Create `dashboard/` directory at repo root

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: TraceQueryEngine — core query abstraction needed by US1, US3, US4

- [x] T003 Create `hermes_flow/trace_query.py` with `TraceQueryEngine` class — `trace_tree(trace_id)` method that reads from `trace_events` table (storage.py) and builds nested span tree, plus `trace_analyze(run_id)` that computes timing distributions across all spans

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 1 — CLI 查询和导出 (Priority: P1) 🎯 MVP

**Goal**: 开发者通过 CLI 命令查询 trace 数据并获得结构化分析报告

**Independent Test**: 启动一个 3-agent flow 运行，运行后执行 `python -m hermes_flow.cli.analyze <run_id>`，检查输出包含至少 3 个 state 节点和耗时信息

### Implementation for User Story 1

- [x] T004 [P] [US1] Implement `hermes_flow/cli/analyze.py` — analyze command: read TraceQueryEngine output, render text DAG with per-state timing (Not [P] — depends on T003 TraceQueryEngine)
- [x] T005 [US1] Add `--json` flag to analyze command outputting full `trace_tree`, `summary`, `decisions`, `messages` as JSON (Not [P] — shares file T004)
- [x] T006 [US1] Implement `diff` subcommand in `hermes_flow/cli/analyze.py` — compares two runs' decision sequences and timeline, renders diff text
- [x] T007 [US1] Implement `budget` subcommand in `hermes_flow/cli/analyze.py` — reports round count, per-round timing, optimization suggestions

**Checkpoint**: `python -m hermes_flow.cli.analyze <run_id>` works with text and JSON output

---

## Phase 4: User Story 2 — 仪表盘 (Priority: P1)

**Goal**: 开发者启动 Observer 后在浏览器中查看状态机图、实时 agent 日志、时间线瀑布图、分析统计、diff 对比

**Independent Test**: 用 5-agent flow 验证仪表盘可展示所有 5 个 agent 的状态、决策和消息

### Implementation for User Story 2

- [x] T008 [P] [US2] Create `dashboard/index.html` — SPA entry point with navigation tabs (Graph / Stream / Timeline / Analysis / Diff), loads Mermaid from CDN, connects to Observer SSE stream
- [x] T009 [P] [US2] Create `dashboard/graph.js` — Mermaid state DAG renderer: fetches `/api/runs/<id>/graph`, renders Mermaid sequence, highlights current state, clickable nodes show details
- [x] T010 [P] [US2] Create `dashboard/stream.js` — real-time agent thinking log viewer: subscribes to SSE `/api/events`, renders agent_thinking events as streaming log entries with role_id color coding
- [x] T011 [P] [US2] Create `dashboard/timeline.js` — timeline waterfall chart: fetches spans from `/api/runs/<id>/trace`, renders horizontal bars per agent role with time axis
- [x] T012 [P] [US2] Create `dashboard/analysis.js` — stats page: fetches `/api/runs/<id>/analyze`, renders round count distribution, state timing, decision summary as cards/charts
- [x] T013 [P] [US2] Create `dashboard/diff.js` — comparison page: dual run_id input, fetches both runs' data, renders side-by-side decision timeline and timing comparison
- [x] T014 [US2] Modify `hermes_flow/observer.py` — replace embedded DASHBOARD_HTML with `dashboard/` static file serving, add `/api/runs/<id>/analyze` REST endpoint, add SSE event_types for agent_thinking and alert_*

**Checkpoint**: Dashboard serves at http://localhost:8080 with all 5 tabs functional

---

## Phase 5: User Story 3 — Agent 决策审计 (Priority: P1)

**Goal**: 系统审计者能追溯到每个 agent 的完整决策链

**Independent Test**: 启动 2-agent discussion flow，通过 `hermes flow analyze --json` 验证每个 agent 的 `decision_reason` 包含 source_references

### Implementation for User Story 3

- [x] T015 [P] [US3] Add `source_references` generation in `hermes_flow/agent_tools.py` — when `agent_submit_decision()` is called, record which inbox message IDs and state rules informed the decision value
- [x] T016 [US3] Publish `agent_thinking` EventBus event in `hermes_flow/agent_tools.py` — on each tool call (read_inbox / send_message / submit_decision / query_status), emit event with step_type, inputs, output, timestamp (Not [P] — shares file T015)
- [x] T017 [US3] Add `/api/runs/<id>/agent-sessions` REST endpoint in `hermes_flow/observer.py` — returns per-session aggregated data: decisions, thinking_events, inbox_snapshot

**Checkpoint**: Agent decisions include source_references; SSE delivers agent_thinking events in real-time

---

## Phase 6: User Story 4 — 运行时告警 (Priority: P2)

**Goal**: 运维人员能收到 flow 异常告警

**Independent Test**: 构建一个 revision loop flow（gate 永远不满足），验证 5 轮后告警触发

### Implementation for User Story 4

- [x] T018 Create `hermes_flow/alerts.py` with `AlertEngine` class — subscribes to EventBus, detects stuck_state (>120s), revision_loop (>5 rounds), silent_agent (>60s), gate_failure_chain (>3 consecutive), publishes alert_* events to EventBus and writes to audit_events table
- [x] T019 Integrate AlertEngine into `hermes_flow/runtime_loop.py` — instantiate AlertEngine in tick loop, pass run status and transitions for detection
- [x] T020 Add alert display in `dashboard/stream.js` — render alert_* SSE events as notification toasts with severity color coding
- [x] T021 Create `hermes_flow/benchmark.py` — runs N agent sessions (configurable via --agent-count, default 5), measures with/without trace enabled, reports trace_overhead_pct, session_timing_distribution, sqlite_io_latency
**Checkpoint**: AlertEngine detects and reports abnormal states within 2 detection cycles

---

## Phase 7: User Story 5 — 性能基准 (Priority: P2)

**Goal**: 开发者运行 benchmark 确认 trace 开销 <5%

**Independent Test**: 运行 `python -m hermes_flow.benchmark`，输出包含 trace_overhead_pct < 5

### Implementation for User Story 5

- [x] T021 Create `hermes_flow/benchmark.py` — runs N agent sessions (configurable via --agent-count, default 5), measures with/without trace enabled, reports trace_overhead_pct, session_timing_distribution, sqlite_io_latency

**Checkpoint**: Benchmark reports trace_overhead_pct < 5 on typical runs

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and cleanup

- [x] T022 Update `specs/005-observability-upgrade/quickstart.md` if any API changes during implementation
- [x] T023 Run full test suite and verify 74+ tests pass plus new scenarios

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — TraceQueryEngine blocks US1, US3, US4
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Setup only — can proceed in parallel with US1
- **US3 (Phase 5)**: Depends on Foundational + US1 (shares trace.py changes)
- **US4 (Phase 6)**: Depends on Foundational + US2 (EventBus + dashboard integration)
- **US5 (Phase 7)**: Depends on Foundational — can proceed as soon as TraceQueryEngine is done
- **Polish (Phase 8)**: Depends on all user stories

### User Story Dependencies

- **US1 (P1)**: Starts after Foundational — no deps on other stories
- **US2 (P1)**: Starts after Setup — no deps on other stories (parallel with US1)
- **US3 (P1)**: Starts after Foundational — shares trace.py so sequential after US1
- **US4 (P2)**: Starts after Foundational + observer.py updates from US2
- **US5 (P2)**: Starts after Foundational — independent

### Parallel Opportunities

- Phase 1: T001 and T002 run in parallel
- Phase 3-4: US1 (Phase 3) and US2 (Phase 4) can run in parallel after Phase 2
- Phase 5-7: US3, US4, US5 contain internal sequential deps but can run in parallel once their blocking phases complete
- Within US2: T008-T013 all [P] (different JS files) — run in parallel

### Parallel Example: User Story 2

```bash
# Launch all Dashboard files together:
Task: "Create dashboard/index.html"
Task: "Create dashboard/graph.js"
Task: "Create dashboard/stream.js"
Task: "Create dashboard/timeline.js"
Task: "Create dashboard/analysis.js"
Task: "Create dashboard/diff.js"

# Then integrate with observer:
Task: "Modify observer.py to serve dashboard/ + new API endpoints"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (TraceQueryEngine)
3. Complete Phase 3: User Story 1 (CLI analyze)
4. **STOP and VALIDATE**: Test CLI on a real flow run
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → TraceQueryEngine ready
2. Add US1 (CLI) → `hermes flow analyze` works (MVP!)
3. Add US2 (Dashboard) → Visual debugging experience
4. Add US3 (Agent audit) → Decision transparency
5. Add US4 (Alerts) → Proactive monitoring
6. Add US5 (Benchmark) → Performance confidence

### Parallel Team Strategy

With multiple developers:

1. Setup + Foundational together
2. Developer A: US1 (CLI) + US3 (Agent audit — sequential)
3. Developer B: US2 (Dashboard) — parallel with A
4. Developer C: US4 (Alerts) + US5 (Benchmark) — starts after Foundational

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
