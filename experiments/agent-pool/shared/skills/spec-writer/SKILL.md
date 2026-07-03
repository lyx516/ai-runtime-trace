---
name: spec-writer
description: 将模糊需求转化为结构化规格文档 spec.md
---

# Spec Writer Skill

适用于需要将模糊需求转化为结构化规格文档的场景。

## 输入
- 用户任务目标
- 已有代码/项目上下文（如有）

## 工作流

1. 分析需求，提取核心概念：用户角色、操作、数据、约束
2. 对模糊处做合理假设，最多 3 处 [NEEDS CLARIFICATION]
3. 编写 spec.md，包含：
   - 功能需求（可测试的条目）
   - 边界条件
   - 输入输出定义
   - 错误处理
   - 验收标准（可量化）
4. **必须使用 file_write 工具写入 spec.md**，才提交 APPROVE

## 产物
- `spec.md`
