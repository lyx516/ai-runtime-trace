# 代码审查 + 测试技能（code-reviewer / reviewer）

## 执行流程

### 1. 对照 spec 分析（speckit-analyze）

```bash
# 对比 spec.md 与实现产出
diff <(grep -E '^## |FR-|SC-' spec.md) <(grep -E '^## |FR-|SC-' implementation-report.md)
```

检查点：
- spec.md 中的 Functional Requirements 是否全部实现
- Success Criteria 是否全部满足
- 是否有 spec 未覆盖的实现（scope creep）

### 2. 对比最初目标与实现

三向对比：

| 维度 | spec.md | plan.md | 实际代码 | 判定 |
|---|---|---|---|---|
| 功能完整性 | 列出 FR | 对照方案 | 检查文件 | ✓/✗ |
| 接口一致性 | 接口定义 | 对照方案 | grep 代码 | ✓/✗ |
| 数据流 | 数据流图 | 对照方案 | trace 代码 | ✓/✗ |

差异记录下来写入 `review.md`。

### 3. 运行测试

```bash
# 标准测试
python -m pytest tests/ -v 2>&1 | tee test-results.txt

# 如果没有 tests 目录，检查是否有其他测试方式
# 如果完全没有测试，REVIEW.md 中标记为 BLOCKING ISSUE
```

### 4. 产出 review.md

- [ ] 所有 spec FR 实现状态
- [ ] 对比差异表
- [ ] 测试结果摘要
- [ ] 阻塞问题（如有）
- [ ] 建议改进项

## 完成信号

全部检查完成 → **submit_decision(APPROVE)**。
有阻塞问题 → **submit_decision(REQUEST_CHANGES)** 并写明具体问题。
