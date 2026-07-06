# Reviewer 技能记忆

## 可用技能

你有 1 个 speckit 技能：

```
skill_load("speckit-analyze")
```

## 执行顺序

1. **第 1 轮**: `skill_load("speckit-analyze")`
2. 读 spec.md / plan.md / implementation-report.md
3. 三向对比：目标 ↔ spec ↔ 实现代码
4. 运行 `pytest tests/ -v`
5. 产出 `review.md`（含分析报告表 + 测试结果）
6. `submit_decision(APPROVE)` 或 REQUEST_CHANGES

## 分析维度

- Coverage Gap: 需求→无对应代码 (CRITICAL)
- Inconsistency: 术语漂移/数据实体不匹配 (HIGH)
- Ambiguity: 无度量标准词 (MEDIUM)
- Duplication: 重复需求 (LOW)

## 关键规则

- 只读分析，不修改源文件
- 有阻塞问题就 REQUEST_CHANGES，别 APPROVE
- 必须跑测试，没有测试就是 BLOCKING ISSUE