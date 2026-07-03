# Data Model: 可观测性升级

**Date**: 2026-07-03
**Spec**: specs/005-observability-upgrade/spec.md

**Note**: 以下实体是现有模型（storage.py schema）的补充或增强，不是替代。

## 新增/增强实体

### TraceQueryResult (新增，纯查询)

表示一次 span 树查询的返回结果。

| 字段 | 类型 | 描述 |
|------|------|------|
| trace_id | string | span 树根节点 trace_id |
| tree | TraceSpanNode[] | 嵌套的 span 树（根 span + children 递归） |
| summary | dict | 聚合统计（总耗时、span 数、各 event_type 计数） |
| query_time_ms | int | 查询耗时 |

### TraceSpanNode (新增，查询产物)

```python
{
    "span_id": str,
    "event_type": str,
    "duration_ms": int,
    "ts_start": str,     # ISO datetime
    "ts_end": str,       # ISO datetime
    "inputs": dict,
    "outputs": dict,
    "decisions": dict,
    "error": dict | None,
    "children": [TraceSpanNode]   # 递归嵌套
}
```

### AnalysisSummary (新增，聚合分析产物)

| 字段 | 类型 | 描述 |
|------|------|------|
| run_id | string | run 标识 |
| wall_time_ms | int | 总耗时 |
| state_count | int | 经历过多少个 state |
| transitions | list[dict] | 所有 transition（from→to, gate_result, round） |
| state_timing | dict | 每个 state 的耗时分布（min/avg/max） |
| decision_summary | dict | 决策统计（approve/reject/block 计数） |
| round_count | int | 总 revision round 数 |
| trace_span_count | int | 总 span 数 |
| suggestions | list[str] | 优化建议 |

### AlertRule (新增)

| 字段 | 类型 | 描述 |
|------|------|------|
| rule_id | string | 规则唯一标识 |
| name | string | 人类可读名称 |
| condition_type | enum | stuck_state / revision_loop / silent_agent / gate_failure_chain |
| threshold | int | 触发阈值（秒数/轮数/次数） |
| enabled | bool | 是否启用 |
| last_triggered_at | string (ISO) | 上次触发时间 |

### AlertEvent (新增，存入 audit_events 表)

| 字段 | 类型 | 描述 |
|------|------|------|
| event_id | string | uuid |
| run_id | string | 关联 run |
| rule_id | string | 触发规则 |
| state_id | string | 当前 state |
| severity | enum | info / warning / critical |
| message | string | 人类可读描述 |
| details | dict | 上下文数据 |
| created_at | string (ISO) | 触发时间 |

### AgentThinkingEvent (新增，EventBus 事件类型)

EventBus 事件的 payload 结构：

| 字段 | 类型 | 描述 |
|------|------|------|
| run_id | string | run 标识 |
| session_id | string | agent session 标识 |
| role_id | string | agent 角色 |
| step_type | enum | read_inbox / send_message / submit_decision / query_status |
| inputs | dict | 该步骤的入参（如 inbox 消息列表） |
| output | any | 该步骤的输出 |
| timestamp | string (ISO) | 事件时间戳 |

### Decision 增强（现有 Decisions 表的 schema 不变）

`decisions` 表新增对 `reason` 字段的内容约定：
- reason 中应包含 `source_references` 文本段
- 格式：`"[source: inbox/{message_id}] [source: rule/{state_id}] 实际决策理由"`

## 与现有实体的关系

```
FlowRun (现有)
  ├── states (现有) → TraceSpan (现有 + TraceQueryResult)
  ├── decisions (现有 + Decision 增强)
  ├── messages (现有) → inboxes (现有)
  └── transitions (现有) → AnalysisSummary

AlertRule (新增) → 检测 → AlertEvent (新增, 存入 audit_events)
AgentThinkingEvent (新增, EventBus 瞬时) → 消费 → dashboard 实时展示
```
