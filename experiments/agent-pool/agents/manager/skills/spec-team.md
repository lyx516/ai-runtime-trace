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
  description: 编写实现代码和报告（由 code-reviewer 审查）
  actors: implementer+code-reviewer
  gate:
    type: product
    file: implementation-report.md
    pass: REVIEW
    fail: IMPLEMENT
    max: 4
  output_artifacts:
  - implementation-report.md
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

从需求到规格→方案→任务→实现→审查的完整开发流程，**每阶段由下阶段 agent 交叉审查**.

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

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
