# API Contracts: 可观测性升级

**Date**: 2026-07-03
**Spec**: specs/005-observability-upgrade/spec.md

## CLI Commands

### `hermes flow analyze <run_id>`

输出结构化文本报告。

```text
$ python -m hermes_flow.cli.analyze <run_id>

=== Trace Analysis: <run_id> ===
Wall time: 12.4s | States: 3 | Spans: 124

State Timeline:
  DESIGN (architect) ─┬─ dispatch        0.3ms
                      ├─ session         4.2s
                      ├─ gate_evaluate   1.2ms  → APPROVE
                      └─ advance_state   0.5ms
  IMPLEMENT ...       ─┬─ ...
  REVIEW ...           ─┬─ ...

Decisions: 3 (1 APPROVE, 1 APPROVE, 1 APPROVE)
Rounds: 1

Suggestions:
  - DESIGN state took 4.2s (43% of total). Consider reducing session timeout.
```

### `hermes flow analyze --json <run_id>`

```json
{
  "run_id": "a1b2c3",
  "trace_tree": {
    "span_id": "root",
    "event_type": "runtime_loop",
    "duration_ms": 12400,
    "children": [ ... ]
  },
  "summary": {
    "wall_time_ms": 12400,
    "state_count": 3,
    "round_count": 1,
    "trace_span_count": 124
  },
  "decisions": [ ... ],
  "messages": [ ... ]
}
```

### `hermes flow diff <run_id_a> <run_id_b>`

```text
=== Diff: <run_id_a> vs <run_id_b> ===

Common states: DESIGN → IMPLEMENT → REVIEW → DONE
Divergent states:
  DESIGN (A: 4.2s, B: 8.1s) — B had 2 additional revision rounds
  REVIEW (A: 1.0s, B: 3.5s) — B had 1 extra decision

Decision differences:
  REVIEW round 2: A=APPROVE, B=REQUEST_CHANGES
```

### `hermes flow budget <run_id>`

```text
=== Budget: <run_id> ===
Round count: 3
Per-round timing:
  round 1: 4.2s
  round 2: 3.1s
  round 3: 5.0s
Total: 12.4s

Suggestions:
  - Round 3 is 40% slower than average. Check if agent has enough context.
  - Consider setting max_rounds=5 to prevent runaway revisions.
```

## REST API (Observer 新增端点)

Observer 现有 `/api/runs/<id>/graph`, `status`, `audit`, `decisions`, `messages`, `transitions`, `trace`, `inboxes`, `all` 不变。新增：

### `GET /api/runs/<id>/analyze`

返回 AnalysisSummary 格式的 JSON。

### `GET /api/runs/<id>/agent-sessions`

```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "role_id": "designer",
      "state_id": "DESIGN",
      "status": "completed",
      "decisions": [...],
      "thinking_events": [
        {"step_type": "read_inbox", "timestamp": "...", "inputs": {...}},
        {"step_type": "submit_decision", "timestamp": "...", "output": {...}}
      ]
    }
  ]
}
```

### `GET /api/runs/<id>/alerts`

```json
{
  "alerts": [
    {
      "event_id": "...",
      "rule_id": "revision_loop",
      "state_id": "REVIEW",
      "severity": "warning",
      "message": "REVIEW state entered 6 times without passing gate",
      "created_at": "..."
    }
  ]
}
```

### `SSE 事件类型（新增）`

| 事件类型 | payload | 触发时机 |
|----------|---------|----------|
| `agent_thinking` | AgentThinkingEvent | agent 每次工具调用 |
| `alert_stuck_state` | AlertEvent | state 超时 |
| `alert_revision_loop` | AlertEvent | revision > 5 轮 |
| `alert_gate_failure` | AlertEvent | gate 连续失败 > 3 次 |
| `alert_silent_agent` | AlertEvent | agent > 60s 无输出 |
