# Agent Loop 评测体系建设方案

> 调研时间：2026-07-09 | 版本：v1

## 1. 数据资产清单

每个 `debate` run 写入一个独立 SQLite (`state.sqlite`)。当前管理 30+ 个已完成/失败的 run，数据天然多样。

| 表 | 记录内容 | 可计算指标 |
|---|---|---|
| `runs` | status, current_state, time | 完成率 (completed/all)、平均运行时间 |
| `thinking_events` | per state/agent tool 调用明细 | 工具调用数、工具分布、每轮调用数 |
| `decisions` | 每个 gate 的 agent 投票 | APPROVE 率、第几轮达成共识 |
| `transitions` | state 流转路径 | 重试次数、backtracking 模式 |
| `messages` | agent-agent 对话 | 对话长度、协调次数 |
| `run_performance` | Post-run 自动聚合 | by_state tool_calls、total_seconds |
| `evolution_backups` | patch_framework 历史 | 试错次数、回滚率 |
| 磁盘 artifact | spec.md, plan.md, code, test | 产出质量 (未测量) |

**关键示例：** 从 3 个代表性的 run 中提取数据——

```
Run 44a58bd7920d (completed@DONE, 651s):
  IMPLEMENT implementer: 80 tool_calls (大部分是 terminal 测试)
  REVIEW code-reviewer: 44 tool_calls (全部是终端验证)
  决策: 11, 所有 gate 均 APPROVE

Run cd518ce5e527 (completed, post-fix):
  IMPLEMENT code-reviewer: 35 file_read
  REVIEW code-reviewer: 24 skill_load
  run_performance 仍使用旧格式 (工具名称计数), 缺失 by_state

Run ece45337af6c (script.sh gate blocked):
  run_performance 缺失 — 最终状态=active, 未触发提交
```

## 2. 三层评测体系

每一层直接映射到现有 SQLite schema，无需新基础设施。

### 2.1 单元层 — 单工具调用正确性

**对标：** `hermes-bench-tool-call` (61 个任务) · BFCL · ToolBench

| 指标 | SQL | 现状 |
|---|---|---|
| 工具调用成功率 | `SELECT COUNT(*) FROM thinking_events WHERE output_json LIKE '%ok\": true%'` | ✅ 可用 |
| 工具频率分布 | `SELECT step_type, COUNT(*) FROM thinking_events GROUP BY 1 ORDER BY 2 DESC` | ✅ 可用 |
| 工具调用平均耗时 | `SELECT step_type, AVG(duration) FROM thinking_events GROUP BY 1` | ⚠️ 需要 duration 字段 (尚未添加) |
| 语法错误率 | 正则匹配 `output_json` 中的 error 字段 | ✅ 可用 |

**最小可行方案：** 1 个 SQL 查询 + 1 个 Python 脚本，跨 30+ 个 run 统计工具级错误率。

### 2.2 工流层 — Run 完成效率

**对标：** SWE-bench · AgentBench · WebArena (任务完成视角)

这是当前数据结构的最强点。`capture_run_metrics()` 已自动写入 `run_performance`。

| 指标 | SQL/数据来源 | 现状 |
|---|---|---|
| 完成率 | `COUNT(*) FROM runs WHERE status='completed'` | ✅ 可用 |
| 首次通过率 | `COUNT(*) FROM runs WHERE ... AND (select count(distinct state_id) from transitions where run_id=... <= len(states))` | ✅ 可用 |
| 瓶颈阶段识别 | `run_performance.tool_stats -> by_state` | ✅ 可用 |
| 决策效率 | `decisions 每阶段 count(*) > 1 = retry` | ✅ 可用 |
| 团队效率比 | implementer_tool_calls / reviewer_tool_calls | ✅ 可用 |

**真实示例：**
- run `44a58bd7920d`: IMPLEMENT 阶段 113 次工具调用中，implementer 88、code-reviewer 25 → 效率比 = 3.52
- run `cd518ce5e527`: IMPLEMENT code-reviewer 35 次 `file_read` → 审查者过度读取文件

### 2.3 系统层 — 演化有效性

这是本系统的独特能力：不是单次 run 好不好，而是 **进化是否真的让行为变好**。

| 指标 | 数据来源 | 现状 |
|---|---|---|
| 跨 run 趋势 (同任务类型) | `run_performance WHERE run in (baseline)` + `goal_kw` 匹配 | ✅ `agent_recall(baseline)` 已可用 |
| 演化命中率 | `evolution_backups WHERE reverted=0` | ✅ 可用 |
| 框架修改有效数 | `evolution_backups WHERE reverted=0 AND 后续 run score > 前序 run score` | ⚠️ 需要 `compare_runs()` 集成到 evol loop |
| 记忆采纳率 | `agent_memory` 表的新增率 vs Memory.md 文件大小 | ✅ 可用 |

## 3. 最小可行评测管线 (今天就可运行)

```
debate --evolve        ← 评估+进化 (已有)
     ↓
debate --eval-suite    ← 新增: 跨所有 run 生成评测报告
```

只需 1 个新脚本：`experiments/agent-pool/engine/eval_suite.py`

### 输入：所有 run 的 SQLite 目录
### 输出：3 份报告

```sql
-- 报告 1: Run 完成率 (by flow type)
SELECT 
    substr(r.flow_id, 1, 30) as flow,
    COUNT(*) as total,
    SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) as completed,
    ROUND(AVG(CASE WHEN rp.tool_stats IS NOT NULL THEN json_extract(rp.tool_stats, '$.total_seconds') END), 0) as avg_seconds
FROM runs r
LEFT JOIN run_performance rp ON r.run_id = rp.run_id
GROUP BY 1
ORDER BY total DESC;

-- 报告 2: 按代理的指标
SELECT
    te.role_id,
    COUNT(*) as total_calls,
    SUM(CASE WHEN te.step_type = 'terminal' THEN 1 ELSE 0 END) as terminal_calls,
    SUM(CASE WHEN te.step_type = 'file_read' THEN 1 ELSE 0 END) as file_read_calls
FROM thinking_events te
JOIN runs r ON te.run_id = r.run_id
WHERE r.status = 'completed'
GROUP BY 1
ORDER BY total_calls DESC;

-- 报告 3: 瓶颈阶段热力图
SELECT
    json_each.key as state,
    json_each.value as total_calls
FROM run_performance, json_each(json_extract(tool_stats, '$.by_state'))
WHERE success_score >= 40
ORDER BY total_calls DESC
LIMIT 10;
```

## 4. 缺口与路径

### 缺口 1: 稳定任务标识 (goal_id)

**问题：** `runs.flow_id` 是每次不同的 flow 名称，无法比较"同一任务不同时间"。

**方案：** 在 `agent_specs` 中注入 `goal_id` 字段（如果目标匹配 `benchmarks/tasks.yaml` 关键词）→ 轻量级 10 行改动。

### 缺口 2: 产出物质量评分

**问题：** artifact 文件质量无人审查。

**方案：** 在 `capture_run_metrics()` 中添加 `llm_judge` 字段 (单次 LLM 调用按 3 分制评分)。不同之处：其他 benchmark 把 judge 作为主要指标，这里它只是辅助——结构化数据是主信号。

### 缺口 3: 人类信号收集

**问题：** 当前所有指标都是系统自评。

**方案：** 在每个 `debate` 完成后提示用户："本次 run 是否成功？[y/n/score]"，写入 `runs.user_score`。轻量级（1 次交互），10 个 run 后即可用于校准 LLM judge。

### 优先级

| 序 | 缺口 | 改量 | 影响 |
|---|---|---|---|
| P0 | goal_id 注入 | +0 行（keyword 匹配方式） | ✅ 已完成（eval_suite.py Report 1）|
| P1 | eval_suite.py 脚本 | +80 行 | 3 份报告，今天就能跑 |
| P2 | 产出物 LLM judge | +30 行 | 补充质量维度 |
| P3 | 人类信号 | +15 行 | 校准自评准确度 |

## 5. 与外部框架的对比

| 框架 | 匹配度 | 差距 |
|---|---|---|
| BFCL (Berkeley) | 低 — 单轮工具调用 | 不涵盖 FSM 或 agent-agent |
| SWE-bench | 中 — 任务完成 | 不涵盖 per-state 分析 |
| hermes-bench-tool-call | 高 — 工具调用正确性 | 不涵盖多 agent 流程 |
| IBM/vakra | 中 — 多步多源 | 不涵盖演化 |
| **本方案** | — | **唯一涵盖 per-state 效率 + 演化有效性** |

关键区分：这些框架都是 **外部评估**（第三方跑你的模型）。本系统是 **运行时内省**——评估信息在运行过程中自动收集，无需额外环境。
