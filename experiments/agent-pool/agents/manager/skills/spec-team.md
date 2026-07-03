---
name: 规格流水线班底
description: 从需求到规格→方案→任务→实现→审查的完整开发流程
agents:
- spec-writer
- plan-maker
- task-breaker
- implementer
- code-reviewer
flow:
- state: SPEC
  description: 编写规格文档
  actors: spec-writer
  gate:
    type: product
    file: spec.md
    pass: PLAN
    fail: SPEC
    max: 3
- state: PLAN
  description: 制定技术方案
  actors: plan-maker
  gate:
    type: product
    file: plan.md
    pass: TASKS
    fail: PLAN
    max: 3
- state: TASKS
  description: 分解任务清单
  actors: task-breaker
  gate:
    type: product
    file: tasks.md
    pass: IMPLEMENT
    fail: TASKS
    max: 3
- state: IMPLEMENT
  description: 编写实现代码
  actors: implementer
  gate:
    type: decision
    pass: REVIEW
    fail: IMPLEMENT
    max: 4
- state: REVIEW
  description: 审查代码 vs spec
  actors: code-reviewer
  gate:
    type: product
    file: review.md
    pass: DONE
    fail: IMPLEMENT
    max: 2
---

# 规格流水线班底

从需求到规格→方案→任务→实现→审查的完整开发流程

## 适用场景
（由管理 Agent 根据任务类型判断是否匹配）

## 班底成员
- `spec-writer`
- `plan-maker`
- `task-breaker`
- `implementer`
- `code-reviewer`

## 流程拓扑
1. **SPEC**: 编写规格文档
   - 执行: `spec-writer`
   - Pass → PLAN
   - 产物检查: `spec.md` 存在且非空
   - Fail → SPEC（最多 3 轮）
2. **PLAN**: 制定技术方案
   - 执行: `plan-maker`
   - Pass → TASKS
   - 产物检查: `plan.md` 存在且非空
   - Fail → PLAN（最多 3 轮）
3. **TASKS**: 分解任务清单
   - 执行: `task-breaker`
   - Pass → IMPLEMENT
   - 产物检查: `tasks.md` 存在且非空
   - Fail → TASKS（最多 3 轮）
4. **IMPLEMENT**: 编写实现代码
   - 执行: `implementer`
   - Pass → REVIEW
   - Fail → IMPLEMENT（最多 4 轮）
5. **REVIEW**: 审查代码 vs spec
   - 执行: `code-reviewer`
   - Pass → DONE
   - 产物检查: `review.md` 存在且非空
   - Fail → IMPLEMENT（最多 2 轮）
