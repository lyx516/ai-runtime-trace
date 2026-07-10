# Code-Reviewer 技能记忆

## 可用技能

```
skill_load("speckit-analyze")
```

与 reviewer 共用 speckit-analyze。重点检查代码质量和安全性。

## 执行顺序

1. `skill_load("speckit-analyze")
2. 读 spec.md / plan.md / tasks.md / 实现代码
3. 复现审查流程（见 speckit-analyze）
4. 运行 `pytest tests/ -v`
5. 产出 `review.md`
6. submit_decision

## 关键规则

- 必须在 IMPLEMENT 完成后才进入
- 检查 implementation-report.md 是否覆盖所有 tasks.md 任务
- 所有 APPROVE 的 task 必须有对应的代码文件
