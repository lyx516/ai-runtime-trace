---
name: plan-maker
description: 基于 spec.md 制定技术方案 plan.md
---

# Plan Maker Skill

适用于 spec.md 已就绪，需要制定技术方案的场景。

## 输入
- `spec.md`

## 工作流

1. 阅读 spec.md，提取功能需求
2. 制定技术方案 plan.md，包含：
   - 架构设计（组件划分）
   - 接口定义
   - 数据流
   - 技术选型理由
   - 替代方案
3. **必须使用 file_write 工具写入 plan.md**，才提交 APPROVE

## 产物
- `plan.md`
