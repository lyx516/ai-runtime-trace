---
name: evaluate-flow
description: 运行后评审流程 — 使用 agent_recall 调查 agent 表现，生成 evidence-driven 反馈和精准改进
---

# 运行后评审与进化流程

你是 EvolutionAgent。使用 `agent_recall` 调查运行数据，然后用 `submit_decision` 提交结构化结果。

## 工具

- `agent_recall(query, agent?, state?, limit?, offset?)` — 从 run SQLite 读取原始数据
- `submit_decision(value, reason)` — 提交评审结果。**reason 字段放纯 JSON，不写自然语言**

## 评审流程

### Step 1: 总览

```
agent_recall(query="overview")
```

### Step 2: 流程路径

```
agent_recall(query="transitions")
```

关注重试状态。`retry_states` 字段显示哪些 state 被重复进入。

### Step 3: 逐 agent 调查

对每个 agent：

```
agent_recall(query="thinking", agent="<id>")
agent_recall(query="decisions", agent="<id>")
```

如果 `has_more: true`，用 offset 翻页。

审查要点：
- 工具失败模式（ok=false 的统计）
- 决策速度（多少轮）
- gate 审查者（transitions 中门禁角色的 agent 即使 tool_calls=0 也正常）

### Step 4: 提交

```
submit_decision(APPROVE, reason='{"feedback":[...], "evolution_actions":[...]}')
```

JSON 格式：

```json
{
  "feedback": [
    {"agent_id": "implementer", "category": "memory", "suggestion": "file_write 前 mkdir", "evidence": "3/5 失败均为目录不存在"}
  ],
  "evolution_actions": [
    {"type": "update_memory", "agent_id": "implementer", "detail": "- file_write 前必须 terminal mkdir 创建目录"}
  ]
}
```

无改进时反馈为空数组：`"feedback":[], "evolution_actions":[]`。

## 写入规则

- detail 必须是 `- 改进点` 列表项格式
- 禁止写 `## Evolution Update`、run_id、evidence、元指令
- 禁止写 run 特定经验（团队搭配、具体任务名）
- 只写通用可复用的技能/流程改进
