---
name: 规格澄清流水线班底
description: 从需求到规格（含需求澄清）→方案→任务→实现→审查的完整开发流程
output_base: "output/{flow_id}"
agents:
- spec-writer-v2
- spec-clarifier
- plan-maker
- task-breaker
- implementer
- code-reviewer
flow:
# ── SPEC: spec-writer-v2 写 spec（含 [NEED CLARIFY] 标记）──
- state: SPEC
  description: 编写规格文档初稿（遇到模糊需求标记 [NEED CLARIFY]）
  actors: spec-writer-v2
  gate:
    type: product
    file: spec.md
    pass: SPEC_CLARIFY
    fail: SPEC
    max: 2
  output_artifacts:
  - spec.md
# ── SPEC_CLARIFY: clarifier 单角色澄清──
- state: SPEC_CLARIFY
  description: 阅读 spec 中的 [NEED CLARIFY] 标记，问用户，发送答案给 writer
  actors: spec-clarifier
  gate:
    type: decision
    pass: SPEC_REVISE
    fail: SPEC_CLARIFY
    max: 3
  output_artifacts:
  - spec.md
# ── SPEC_REVISE: writer 单角色修订──
- state: SPEC_REVISE
  description: 读收件箱，根据 clarifier 的答案修订 spec，移除 [NEED CLARIFY] 标记
  actors: spec-writer-v2
  gate:
    type: product
    file: spec.md
    pass: PLAN
    fail: SPEC_REVISE
    max: 2
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
# ── IMPLEMENT: implementer 写代码，code-reviewer 审查 ──
- state: IMPLEMENT
  description: 编写实现代码（由 code-reviewer 审查）
  actors: implementer+code-reviewer
  gate:
    type: decision
    pass: REVIEW
    fail: IMPLEMENT
    max: 4
# ── REVIEW: code-reviewer 写最终审查报告 ──
- state: REVIEW
  description: 最终审查报告
  actors: code-reviewer
  gate:
    type: decision
    pass: DONE
    fail: IMPLEMENT
    max: 3
---

# 规格澄清流水线班底

从需求到规格（含需求澄清）→方案→任务→实现→审查的完整开发流程。

## 与规格流水线的区别

相比 `spec-team`，增加了 **spec-clarifier** 角色和 **SPEC_CLARIFY** 阶段。
spec-writer 替换为 **spec-writer-v2**（支持在模糊需求处标记 `[NEED CLARIFY]`）。

## 班底成员

- `spec-writer-v2`
- `spec-clarifier`
- `plan-maker`
- `task-breaker`
- `implementer`
- `code-reviewer`

## 流程拓扑

### SPEC — 编写规格初稿
- 执行: `spec-writer-v2` 写 spec.md
- 遇到模糊需求：用 `[NEED CLARIFY: 问题]` 标记，不猜测
- Pass → SPEC_CLARIFY

### SPEC_CLARIFY — 需求澄清 + 修订（双角色 revision 循环）
- **第1轮**: spec-writer-v2 已写好 spec，无事可做 → APPROVE
- **第1轮**: spec-clarifier 读 spec.md →
  - 无 `[NEED CLARIFY]` 标记 → APPROVE（直接进 PLAN）
  - 有标记 → 调 clarify(≤5次) → 发答案给 writer → REQUEST_CHANGES
- **第2轮**: spec-writer-v2 读收件箱 → 根据答案修订 spec（去掉标记）→ APPROVE
- **第2轮**: spec-clarifier 检查修订版 → 仍有标记? REQUEST_CHANGES / 干净了 → APPROVE
- **双方都 APPROVE** → Pass → PLAN
- **任一 REQUEST_CHANGES** → Fail → SPEC_CLARIFY（最多 4 轮）

### PLAN / TASKS / IMPLEMENT / REVIEW
与 spec-team 相同，由 plan-maker / task-breaker / implementer / code-reviewer 执行。
