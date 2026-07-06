---
name: 规格流水线班底
description: 从需求到规格→方案→任务→实现→审查的完整开发流程，每阶段由下阶段 agent 交叉审查
output_base: "output/{flow_id}"
agents:
- spec-writer
- plan-maker
- task-breaker
- implementer
- code-reviewer
flow:
# ── SPEC: spec-writer 写，plan-maker 审查 ──
- state: SPEC
  description: 编写规格文档（由 plan-maker 审查）
  actors: spec-writer+plan-maker
  gate:
    type: product
    file: spec.md
    pass: PLAN
    fail: SPEC
    max: 3
  output_artifacts:
  - spec.md
# ── PLAN: plan-maker 写，task-breaker 审查 ──
- state: PLAN
  description: 制定技术方案（由 task-breaker 审查）
  actors: plan-maker+task-breaker
  gate:
    type: product
    file: plan.md
    pass: TASKS
    fail: PLAN
    max: 3
  output_artifacts:
  - plan.md
# ── TASKS: task-breaker 写，implementer 审查 ──
- state: TASKS
  description: 分解任务清单（由 implementer 审查）
  actors: task-breaker+implementer
  gate:
    type: product
    file: tasks.md
    pass: IMPLEMENT
    fail: TASKS
    max: 3
  output_artifacts:
  - tasks.md
# ── IMPLEMENT: implementer 写代码+报告，code-reviewer 审查 ──
- state: IMPLEMENT
  description: 编写实现代码和报告（由 code-reviewer 审查）。注意：代码写完后最后写 README.md。
  actors: implementer+code-reviewer
  gate:
    type: product
    file: README.md
    pass: REVIEW
    fail: IMPLEMENT
    max: 4
  output_artifacts:
  - README.md
# ── REVIEW: code-reviewer 写最终审查报告 ──
- state: REVIEW
  description: 最终审查报告
  actors: code-reviewer
  gate:
    type: product
    file: review.md
    pass: DONE
    fail: IMPLEMENT
    max: 2
  output_artifacts:
  - review.md
---

# 规格流水线班底

从需求到规格→方案→任务→实现→审查的完整开发流程，**每阶段由下阶段 agent 交叉审查**。

## 适用场景
需要产出可交付物的开发任务：需求分析 → 方案设计 → 任务分解 → 实现编码 → 代码审查。

## 班底成员
- `spec-writer`
- `plan-maker`
- `task-breaker`
- `implementer`
- `code-reviewer`

## 流程拓扑

**审查机制**：每个状态的 gate 包含本阶段执行者和下一阶段执行者（交叉审查）。例如 SPEC 状态由 spec-writer 写、plan-maker 审查 —— spec-writer 写完 spec.md 后 plan-maker 会读它、判断质量、决定能否进入下一阶段。这确保交付物不会"被遗忘"：如果 implementer 忘记写 implementation-report.md，code-reviewer 会发现并 REQUEST_CHANGES。

1. **SPEC**: 编写规格文档
   - 执行: `spec-writer` 写 spec.md
   - 审查: `plan-maker` 读 spec.md 并确认质量
   - Pass → PLAN
   - Fail → SPEC（最多 3 轮）
2. **PLAN**: 制定技术方案
   - 执行: `plan-maker` 写 plan.md
   - 审查: `task-breaker` 读 plan.md 并确认质量
   - Pass → TASKS
   - Fail → PLAN（最多 3 轮）
3. **TASKS**: 分解任务清单
   - 执行: `task-breaker` 写 tasks.md
   - 审查: `implementer` 读 tasks.md 并确认可执行
   - Pass → IMPLEMENT
   - Fail → TASKS（最多 3 轮）
4. **IMPLEMENT**: 编写实现代码和报告
   - 执行: `implementer` 写代码 + implementation-report.md
   - 审查: `code-reviewer` 读代码和报告，检查是否完整
   - Pass → REVIEW
   - Fail → IMPLEMENT（最多 4 轮）
5. **REVIEW**: 最终审查报告
   - 执行: `code-reviewer` 写 review.md
   - Pass → DONE
   - Fail → IMPLEMENT（最多 2 轮）

---

## Gate 设计指南（适用于自行构建新班底）

### gate 的两种类型

此班底使用了两种 gate，所有 gate 都通过 **YAML flow 数组中的 state 节点**配置：

1. **`decision` gate** — LLM 判断式通过。agent 调用 `submit_decision(APPROVE | REQUEST_CHANGES | BLOCKED)` 来决定是否满足条件。
   - 适用于：方案评审、代码审查等需要主观判断的场景。
   - 典型配置:
     ```yaml
     gate:
       type: decision
       pass: NEXT_STATE      # 通过后转移到的 state id
       fail: CURRENT_STATE   # 不通过时返回的 state（形成 revision 循环）
       max: 3                # 最大 revision 轮数
     ```

2. **`product` gate** — 产物存在性检查。系统自动检查指定文件是否存在且非空来决定 pass/fail。
   - 适用于：文件产出环节（spec 写完、报告生成等）。
   - 典型配置:
     ```yaml
     gate:
       type: product
       file: spec.md         # 要检查的产物文件名
       pass: NEXT_STATE
       fail: CURRENT_STATE
       max: 3
     ```

### 从零新建一个 gate 链路的步骤

1. **确定串行或并行**：当前框架支持串行多 actor 审查。如需并行，在 flow 数组中配置多个 state 串联即可（每个 state 独立 gate）。
2. **确定每个 state 的 actors**：写 `actor1+actor2`（执行顺序：actor1 执行，actor2 审查）。
3. **选择 gate 类型**：
   - 需要产出文件 → `type: product` + 指定 `file`
   - 只需 LLM 判断 → `type: decision`
4. **设置 transition 目标**：
   - `pass`: 通过后的目标 state id（或终端 `DONE`）
   - `fail`: 不通过时的重试 state（通常是自身，形成 revision 循环）
   - `max`: 最大 revision 轮数，防止无限循环
5. **添加 output_artifacts**（仅 product gate 需要）：
   ```yaml
   output_artifacts:
     - spec.md
   ```

### 快速开始：新建一个精简版 2-agent 班底

```yaml
---
name: 精简审查班底
description: 写 -> 审查 两步流程
output_base: "output/{flow_id}"
agents:
- writer
- reviewer
flow:
- state: WRITE
  description: 产出文档
  actors: writer+reviewer
  gate:
    type: product
    file: output.md
    pass: DONE
    fail: WRITE
    max: 2
  output_artifacts:
  - output.md
---

# 正文略
```