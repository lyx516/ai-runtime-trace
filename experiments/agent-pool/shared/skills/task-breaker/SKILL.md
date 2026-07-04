---
name: task-breaker
description: 基于 plan.md 将技术方案拆解为可执行的任务清单 tasks.md
---

# Task Breaker Skill

适用于 plan.md 已就绪，需要生成可执行任务清单的场景。

## 输入
- `plan.md`

## 工作流

1. 阅读 plan.md，提取技术步骤和依赖关系
2. 拆解任务 tasks.md，每条任务包含：
   - 任务 ID（T001, T002...）
   - 文件路径
   - 前置依赖
   - 产出描述
   - [P] 标记并行任务
3. 确保无循环依赖、标注关键路径
4. **必须使用 terminal 创建 tasks.md**，才提交 APPROVE

## 产物
- `tasks.md`
