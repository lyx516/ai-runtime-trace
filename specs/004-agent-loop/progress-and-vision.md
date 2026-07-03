# Hermes Flow FSM — 进展与远景

## 当前进展

### 已实现三层架构

```
┌─────────────────────────────────────────────────┐
│  Tier 3: Agent Loop — 执行层                     │
│  runtime_loop.py / agent_runner.py              │
│  delegate_spawner.py                            │
│  - 自动 tick 循环，2 种 spawn mode               │
│  - subprocess: 线程内运行 agent_runner           │
│  - delegate: 写 _manifest.json → Hermes 调度     │
│  - state entry dispatch + inbox dispatch         │
│  - 自动 gate 评估 + idle timeout                 │
└──────────────────────┬──────────────────────────┘
                       │ context.json / result.json
                       │
┌──────────────────────▼──────────────────────────┐
│  Tier 2: FSM Engine — 逻辑层                     │
│  engine.py / routing.py / tools.py              │
│  - 状态机、gate、路由、决策记录                   │
│  - 与 Hermes 解耦，独立可测试                     │
│  - 项目本地的 state.sqlite 是单一真实来源          │
└──────────────────────┬──────────────────────────┘
                       │ RuntimeStore
                       │
┌──────────────────────▼──────────────────────────┐
│  Tier 1: Storage — 持久层                        │
│  storage.py / schemas.py / trace.py              │
│  - SQLite，project-local                          │
│  - 字段级 trace span                             │
│  - 可导出、可恢复、可审计                          │
└─────────────────────────────────────────────────┘
```

### 已实现的端到端能力

| 场景 | 状态 |
|------|------|
| 定义 flow YAML → 启动 run | ✅ |
| Flow 自动从 DESIGN → IMPLEMENT → REVIEW → DONE | ✅ |
| 子 agent 通过 subprocess 运行 | ✅ |
| 子 agent 通过 delegate_task 桥接运行 | ✅ |
| 子 agent 动态决策（读 inbox → 决定 Approve/Change/Block） | ✅ |
| Gate 评估后自动推进状态 | ✅ |
| 状态变更时自动调度 actors | ✅ |
| Inbox 消息到达时重新调度 agent | ✅ |
| Idle timeout 自动推进 | ✅ |
| SQLite 审计追踪（transitions, decisions, audit events） | ✅ |

---

## 远景：1 — Flow 作为一等公民

### 现状

Flow 定义是本地 YAML 文件，存在于 `experiments/vector-db/exp-flow.yaml`。只有手动调用 `flow_init()` 才能启动。

### 目标

```yaml
# .hermes-flow/flows/my-flow.yaml
flow_id: three-agent-review
initial_state: DESIGN
terminal_states: [DONE, ABORT, ESCALATED]

roles:
  architect:
    soul: "你擅长设计系统架构…"
    skills: [speckit-plan]
    toolsets: [file, web]
    memory_mode: run_isolated

states:
  DESIGN:
    actors: [architect]
    gate: ...
  IMPLEMENT:
    actors: [implementer]
    gate: ...
  REVIEW:
    actors: [reviewer]
    gate: ...
```

**能力**：

- `hermes flow new <name>` — 脚手架生成标准 flow 模板
- `hermes flow list` — 列出项目所有 flow
- `hermes flow validate <path>` — 预检 flow 合法性
- `hermes flow run <flow> --context "xxx"` — 启动运行
- Flow 定义是**可审查、可版本控制、可复用**的项目资产

### 差距 & 下一步

| 缺什么 | 复杂度 |
|--------|--------|
| `hermes flow new` CLI 子命令 | 低 |
| Flow YAML schema 校验 | 中 |
| 多 flow 管理（目录扫描 + 注册） | 低 |
| `hermes flow run` 集成 | 中 |

---

## 远景：3 — Agent 真正在讨论

### 现状

当前 agent 的决策流程：

```
agent_runner.py 被调用
  → 读 context.json
  → 读 inbox (agent_inbox_read)
  → 读 status (agent_query_status)
  → 规则引擎决定 APPROVE / REQUEST_CHANGES / BLOCKED
  → 写 result.json
```

规则引擎是**静态关键词匹配**，不是 LLM 决策。所以所有 agent 都 APPROVE，没有真正的讨论。

### 目标

在 delegate mode 下，每个 agent session 由 **Hermes delegate_task 子 agent（LLM）** 执行：

```
RuntimeLoop 写 context.json + manifest
  ↓
Hermes agent 扫描 manifest → delegate_task(goal=build_delegate_goal(...))
  ↓
子 agent (LLM) 拿到 context prompt:
  ┌─────────────────────────────────────┐
  │ # Flow Run: a1b2c3                  │
  │ ## Your Role: reviewer              │
  │ ### Personality: 你严格审查设计…      │
  │ ## Current State: REVIEW            │
  │ ### Gate: required=[reviewer]       │
  │ ### Inbox (2 messages):             │
  │ - From architect: 设计 v2 已更新    │
  │ - From implementer: M=32 够用吗？   │
  │ ## 你的任务是审阅并决定…              │
  └─────────────────────────────────────┘
  → 子 agent LLM 思考
  → 通过 terminal 工具调用 agent_tools.py
  → 写 result.json
```

**真正讨论的场景**：

```
architect 写出设计 → APPROVE
  ↓ 推进到 REVIEW
reviewer 被调度 → 读设计 → 发现缺陷
  → agent_message_send(architect, "M=16 在 d=1000 时不够")
  → agent_submit_decision(REQUEST_CHANGES)
  ↓ gate 不满足 → 回退到 DESIGN
architect 被重新调度 → 读反馈 → 修改参数
  → agent_message_send(reviewer, "已改为 M=32")
  → agent_submit_decision(APPROVE)
  ↓ 推进到 REVIEW（第 2 轮）
reviewer 再次调度 → 读设计 → 满意
  → agent_submit_decision(APPROVE)
  ↓ gate 满足 → 推进到 DONE
```

### 差距 & 下一步

| 缺什么 | 复杂度 |
|--------|--------|
| agent_runner 规则引擎 → delegate_task LLM | **核心**（见 #1） |
| `build_delegate_goal()` 的 prompt 优化 | 低 |
| 多轮 inbox 驱动的 re-dispatch 已在 RuntimeLoop 中 | ✅ 已有 |
| discussion_history 在 context packet 中的传递 | 中 |

**这里的 1 就是 delegate_task 集成**——架设好了桥，只差把桥上的车从"脚本"换成"LLM"。

---

## 远景：4 — Trace 作为第一性原理

### 现状

`hermes_flow/trace.py` 已有完整基础设施：

- `NoOpTracer` / `SqliteTracer`
- `tracer.span()` 包裹所有重要操作
- `trace_events` 表记录 span 树
- 字段级 truncation 防止大 dict 撑爆

所有 agent_tools、runtime_loop、engine 函数都已标注 `tracer.span()`。

### 目标

```
hermes flow analyze <run_id>
```

输出：

```
=== Flow Run: a1b2c3 ===
DESIGN (architect) ─┬─ entry dispatch        0.3ms
                    ├─ agent_session_scheduled 0.1ms
                    ├─ session runtime          4.2s
                    ├─ submit_decision         0.8ms
                    ├─ gate_evaluate           1.2ms  → APPROVE
                    └─ advance_state           0.5ms
IMPLEMENT ─┬─ ...
           └─ ...
REVIEW ─┬─ ...
        └─ ...

Summary:
  Wall time: 12.4s
  Agent sessions: 3
  Decisions: 3
  Discussion rounds: 0
  Total trace spans: 124
```

**进阶能力**：

- `hermes flow trace --json <run_id>` — 导出完整 span 树
- `hermes flow diff <run_id_A> <run_id_B>` — 比较两次运行的 trace 差异
- `hermes flow budget <run_id>` — 检查 token/时间 budget 使用情况
- 用 trace 数据做**策略优化**：哪些 flow 总是需要 3 轮 review？哪里耗时最多？

### 差距 & 下一步

| 缺什么 | 复杂度 |
|--------|--------|
| `hermes flow analyze` CLI 子命令 | 中 |
| Span 树可视化（表格/文本 DAG） | 中 |
| 统计聚合（平均 round 数、耗时分布） | 中 |
| Trace 数据 → 策略建议 | 高 |

---

## 路线图总结

```
Phase A: 基建 ✅ (已完成)
  ├── FSM Engine + Storage + Routing
  ├── Runtime Loop + Agent Runner
  └── delegate_task 桥接 + 动态决策

Phase B: Flow 作为一等公民 (1)
  ├── hermes flow new / list / validate / run CLI
  └── Flow 模板系统

Phase C: LLM 驱动的 Agent 讨论 (3)
  ├── delegate_task 子 agent 真正用 LLM 执行
  ├── 多轮 inbox 驱动的 revision loop
  └── Soul 注入 personality prompt

Phase D: Trace 分析和策略优化 (4)
  ├── hermes flow analyze CLI
  ├── Span 树可视化和统计
  └── 策略建议（budget/round 优化）
```

### 当前在 Phase A 末端，Phase B 起点
