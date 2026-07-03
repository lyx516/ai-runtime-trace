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

## Gate 类型
product

## 流程拓扑
1. **SPEC**: 编写规格文档 spec.md
   - 执行: `spec-writer`
   - Pass → PLAN
   - 产物检查: `spec.md` 存在且非空
   - Fail → SPEC（最多重试 3 次）
2. **PLAN**: 制定技术方案 plan.md
   - 执行: `plan-maker`
   - Pass → TASKS
   - 产物检查: `plan.md` 存在且非空
   - Fail → PLAN（最多重试 3 次）
3. **TASKS**: 分解任务清单 tasks.md
   - 执行: `task-breaker`
   - Pass → IMPLEMENT
   - 产物检查: `tasks.md` 存在且非空
   - Fail → TASKS（最多重试 2 次）
4. **IMPLEMENT**: 编写实现代码
   - 执行: `implementer`
   - Pass → REVIEW
   - Fail → IMPLEMENT（最多 4 轮）
5. **REVIEW**: 审查代码 vs spec
   - 执行: `code-reviewer`
   - Pass → DONE
   - 产物检查: `review.md` 存在且非空
   - Fail → IMPLEMENT（最多重试 2 次）
