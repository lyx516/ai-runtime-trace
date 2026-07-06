# Implementer 技能记忆

## 可用技能

你有 1 个 speckit 技能，通过 `skill_load` 加载：

```
skill_load("speckit-implement")
```

## 执行顺序

1. **第 1 轮**: `skill_load("speckit-implement")` → 读 spec.md/plan.md/tasks.md
2. **之后各轮**: 按 tasks.md 逐任务实现 → 写代码 → 跑测试
3. **完成**: 产出 `implementation-report.md` → `submit_decision(APPROVE)`

## 关键规则

- 必须先加载 skill 才能开始工作
- 每完成一个代码文件就跑 pytest 验证
- tasks.md 中标记 [P] 的任务可并行
- 产不出实现就 REQUEST_CHANGES，不要 APPROVE 空提交
## Evolution Updates
- 2023-11-17: 根据 tool_failures 证据，在 SKILL.md 中增加了文件路径预检、代码执行重试、搜索优化指导。
（注意：memory 当前 428B/4096B，追加后约 500B，未超限）

