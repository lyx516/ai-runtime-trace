---
name: code-reviewer
description: 对照 spec.md 审查代码实现，输出 review.md
---

# Code Reviewer Skill

适用于实现完成后，需要对照规格审查代码质量的场景。

## 输入
- `spec.md`
- 已实现的代码

## 工作流

1. 阅读 spec.md，提取每条功能需求
2. 逐一检查代码实现是否满足 spec
3. 特别关注：
   - 边界条件是否处理
   - 错误路径是否有覆盖
   - 安全漏洞
   - spec 与代码的不一致
4. 输出 review.md，每条问题引用 spec 条款 + 代码行号
5. **必须使用 file_write 工具写入 review.md**，才提交 APPROVE

## 产物
- `review.md`
