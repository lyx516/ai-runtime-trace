# Feature Specification: Hermes Flow 可观测性升级

**Feature Branch**: `005-observability-upgrade`

**Created**: 2026-07-03

**Status**: Draft

**Input**: User description: "Upgrade Hermes Flow observability: trace query engine, standalone dashboard, agent decision transparency, performance alerts, CLI analysis tools"

## User Scenarios & Testing

### User Story 1 - 通过 CLI 查询和导出运行追踪数据 (Priority: P1)

作为开发者，运行 `hermes flow analyze <run_id>` 后可看到完整的 trace 分析报告：span 树（文本 DAG）、各阶段耗时分布、决策序列。支持 `--json` 导出供外部工具处理。

**Why this priority**: trace 数据已存在但不可查询，这是所有高级观测能力的基础。没有查询能力，其他所有功能都是空中楼阁。

**Independent Test**: 可独立测试：启动一个 3-agent flow 运行，运行完后执行 `hermes flow analyze <run_id>`，检查输出包含至少 3 个 state 节点和耗时信息。

**Acceptance Scenarios**:

1. **Given** 一个已完成的 flow run，**When** 运行 `hermes flow analyze <run_id>`，**Then** 输出包含 span 树文本 DAG、每个 state 的耗时、总耗时
2. **Given** 一个 flow run，**When** 运行 `hermes flow analyze --json <run_id>`，**Then** 输出合法的 JSON 且包含 `trace_tree` 键
3. **Given** 两个不同的 flow run，**When** 运行 `hermes flow diff <run_id_a> <run_id_b>`，**Then** 输出显示差异的决策序列和时间线对比
4. **Given** 一个 flow run，**When** 运行 `hermes flow budget <run_id>`，**Then** 输出包含 round 数、每轮耗时、建议（如需优化）

---

### User Story 2 - 通过仪表盘实时观察运行状态 (Priority: P1)

作为开发者，启动 Observer 后打开浏览器（`http://localhost:8080`），能看到：
- 状态流转图（Mermaid DAG）
- 当前 state 的决策热力图（每个 agent 的决策分布）
- 时间线瀑布图（横轴时间/纵轴 agent 角色）
- Agent 思考日志实时推流

**Why this priority**: 现有 embedded 仪表盘功能有限且不可维护。这是最直接的用户可见改进。

**Independent Test**: 可独立测试：用 5-agent flow 验证仪表盘可展示所有 5 个 agent 的状态、决策和消息。

**Acceptance Scenarios**:

1. **Given** Observer 在运行，**When** 在浏览器中访问 `http://localhost:8080`，**Then** 展示 Mermaid 状态机图，每个 state 节点包含 agent 名称和决策计数
2. **Given** 一个 agent 正在运行，**When** 打开实时跟踪页，**Then** agent 的决策过程日志以流式方式展示（类似 `tail -f`）
3. **Given** 一个已完成 run，**When** 打开时间线页，**Then** 显示横轴为时间、纵轴为 agent 角色的瀑布图
4. **Given** 一个 run，**When** 打开分析页，**Then** 显示平均 round 数、耗时分布、gate 通过率统计

---

### User Story 3 - Agent 决策过程可审计 (Priority: P1)

作为系统审计者，对于任何 agent session，能追溯到：
- 该 agent 接收了哪些 inbox 消息
- 做出了什么决策及理由
- 决策引用了哪些来源（state 规则 / inbox 内容 / 讨论历史）
- 完整的思考链（当决策包含推理时）

**Why this priority**: 当前 agent 是黑箱。要实现 LLM 驱动的真实讨论（Phase C），必须先建立透明的决策可审计性。

**Independent Test**: 可独立测试：启动一个 2-agent discussion flow，通过 `hermes flow analyze --json` 查看每个 agent 的 decision_reason 包含引用来源。

**Acceptance Scenarios**:

1. **Given** 一个 agent session 完成，**When** 查询该 session 的决策日志，**Then** 能看到 inbound messages list、outbound decision（含 reason）、decision 引用的 source references
2. **Given** 一个 agent 在处理 inbox 消息，**When** 通过 EventBus 订阅，**Then** 收到 `agent_thinking` 事件包含中间推理步骤
3. **Given** 一个 multi-round discussion，**When** 查看任一 agent 的 session 日志，**Then** 能看到各 round 的 inbox 变化链

---

### User Story 4 - 运行时告警与异常识别 (Priority: P2)

作为运维人员，当 flow 出现异常时系统能自动识别并告警：
- state 停留超时（>120s）
- 同一 state 反复进入（revision loop，>5 轮）
- agent 被调度后超过 60s 无输出
- 连续 gate 失败（>3 次）

**Why this priority**: 告警依赖 trace 查询和实时事件流，必须在 trace query engine 和 EventBus 增强之后才能实现。

**Independent Test**: 构建一个故意陷入 revision loop 的 flow（gate 永远不满足），验证 5 轮后告警触发。

**Acceptance Scenarios**:

1. **Given** 一个 state 超过 120s 无进展，**When** AlertEngine 检测，**Then** 发布 `alert_stuck_state` 事件并在仪表盘显示通知
2. **Given** 一个 state 第 6 次进入 revision loop，**When** AlertEngine 检测，**Then** 发布 `alert_revision_loop` 事件
3. **Given** 连续 4 次 gate 评估失败，**When** AlertEngine 检测，**Then** 发布 `alert_gate_failure_chain` 事件

---

### User Story 5 - 性能基准与开销测量 (Priority: P2)

作为开发者，运行 benchmark 脚本后能看到：
- trace 框架的开销占比（目标 <5%）
- 各 agent session 的耗时分布
- SQLite I/O 的延迟
- 推荐优化点

**Why this priority**: 需要建立基线数据来评判 trace 的开销，确保可观测性本身不成为性能瓶颈。

**Independent Test**: 运行 benchmark 脚本，检查输出包含 trace overhead % 指标。

**Acceptance Scenarios**:

1. **Given** benchmark 脚本，**When** 运行 `python -m hermes_flow.benchmark`，**Then** 输出包含 trace_overhead_pct < 5
2. **Given** benchmark 脚本，**When** 指定 `--agent-count 5`，**Then** 测试覆盖 5 agent 并发场景

---

### Edge Cases

- Agent 进程意外终止时，decision 数据不完整如何处理？
- 仪表盘尝试展示一个还在运行中的大型 run（上千个 span）时，应支持分页/懒加载
- SSE 连接断开时，EventBus 的队列满如何处理（当前是丢弃最旧的订阅者）
- 多个 observer 实例同时连接同一个 run_dir 时的并发读写

### Out of Scope

- 分布式追踪（跨进程/跨容器 trace 关联）— 当前所有 hermes_flow 运行在单进程内
- 与 OpenTelemetry 兼容 export — 未来可以考虑，当前优先内部格式
- 自动死循环修复（只检测告警，不自动干预）
- 历史 run 数据的离线分析仪表盘

## Requirements

### Functional Requirements

- **FR-001**: system MUST provide a CLI command `hermes flow analyze <run_id>` that outputs a structured text DAG of the trace span tree with per-state timing
- **FR-002**: system MUST support `hermes flow analyze --json <run_id>` output in valid JSON with keys `trace_tree`, `summary`, `decisions`, `messages`
- **FR-003**: system MUST support `hermes flow diff <run_id_a> <run_id_b>` comparing decision sequences and timeline
- **FR-004**: system MUST support `hermes flow budget <run_id>` reporting round count, per-round timing, and optimization suggestions
- **FR-005**: Observer MUST serve a standalone HTML dashboard from `dashboard/` directory (Mermaid state graph, real-time agent log stream, timeline waterfall, analysis page, diff page)
- **FR-006**: Agent session MUST publish `agent_thinking` events to EventBus containing intermediate reasoning steps
- **FR-007**: AlertEngine MUST detect stuck states (>120s), revision loops (>5 rounds), silent agents (>60s), gate failure chains (>3 consecutive)
- **FR-008**: system MUST provide `benchmark/run_benchmark.py` that measures trace overhead and reports `< 5%` target compliance
- **FR-009**: decision recording MUST include `source_references` field listing which inbox messages or state rules the decision is based on
- **FR-010**: Trace query engine MUST support `trace_tree(trace_id)` returning nested span tree and `trace_analyze(run_id)` returning timing distributions

### Traceability & Validation Requirements

- **TV-001**: Each user story MUST define a repeatable validation path.
- **TV-002**: Requirements involving runtime behavior MUST state the observable execution fact, not only the human-facing message.
- **TV-003**: Any requested abstraction, extension point, or reusable component MUST name its concrete current consumers or be listed as out of scope.

### Key Entities

- **TraceSpan**: execution span with trace_id, span_id, parent_span_id, event_type, ts_start, ts_end, duration_ms, inputs, outputs, decisions, error. Already exists in trace.py — enhancement adds tree query and analysis aggregation.
- **AlertRule**: named rule with condition type (stuck_state/revision_loop/silent_agent/gate_failure_chain), threshold, enabled flag. New entity in alerts.py.
- **AgentDecisionLog**: per-session record of decisions with source_references, thinking_chain, inbox_snapshot. Enhancement to existing Decision schema.
- **BenchmarkResult**: measurement set with trace_overhead_pct, session_timing_distribution, sqlite_io_latency. New entity output by benchmark script.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Users can run `hermes flow analyze` on any completed run and receive structured output in under 1 second
- **SC-002**: Trace framework overhead stays below 5% of total execution time (measured by benchmark)
- **SC-003**: Dashboard loads in under 2 seconds on first visit and updates state changes within 500ms via SSE
- **SC-004**: Agent decision audit log captures `source_references` for 100% of decisions in a flow run
- **SC-005**: AlertEngine detects a stuck-state scenario within 2 detection cycles (2x the configured check interval)
- **SC-006**: 5-agent concurrent stress test completes without observable degradation (timeline waterfall displays all 5 agents correctly)

## Clarifications

### Session 2026-07-03

- Q: 仪表盘架构 — 单文件 SPA 还是独立 HTML 多页面？ → A: 单入口 SPA，JS 按功能分文件（dashboard/graph.js, dashboard/timeline.js 等），observer 只 serve dashboard/index.html
- Q: 告警持久化 — 仪表盘断开时告警是否应保存？ → A: 双写策略，EventBus 实时推送 + audit_events 表持久化，dashboard 重连后回放历史告警
- Q: Agent 思考粒度 — 什么算一次"思考步骤"？ → A: 每次工具调用（read_inbox / send_message / submit_decision 各算一步）
- Q: CLI 集成方式 — 独立入口还是 Hermes CLI 子命令？ → A: python -m hermes_flow.cli.analyze 独立入口，后期可被 Hermes CLI 包装

（以上设计决策已集成到对应 FR 和 Assumptions 中）

## Assumptions

- 现有 `trace.py` 的 SqliteTracer 和 span 记录基础不变，只新增查询聚合方法（新增 TraceQueryEngine 类封装树查询和分析聚合）
- 现有 EventBus（`observer.py` 中的 `EventBus` 类）基础不变，新增事件类型（agent_thinking / alert_*）和 audit_events 双写
- 仪表盘为单入口 SPA（dashboard/index.html），JS 按功能分目录存放，不引入前端构建工具链
- CLI 命令通过新增 `hermes_flow/cli/analyze.py` 实现，作为独立 python -m 入口，不修改现有的 `tools.py` 接口
- AlertEngine 通过 EventBus 消费事件，告警同时写入 audit_events 表持久化
- Agent thinking 事件在每次 agent_tools 调用时发布（read_inbox / send_message / submit_decision）
- 依赖：现有 `storage.py` 的 SQLite schema（trace_events、audit_events 表已有），无需迁移
