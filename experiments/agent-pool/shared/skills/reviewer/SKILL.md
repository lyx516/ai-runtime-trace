# Reviewer Skill

基于 Hermes 内置 speckit-analyze 的代码审查流程。

## 流程

### 1. 对照 spec 分析

检查 spec.md 的 Functional Requirements 是否全部实现。

### 2. 三向对比

| 维度 | spec.md | plan.md | 实际代码 |
|---|---|---|---|
| 功能完整性 | FR 列表 | 方案对照 | 检查文件 |
| 接口一致性 | 接口定义 | 方案对照 | grep 代码 |
| 数据流 | 数据流图 | 方案对照 | trace 代码 |

差异记录到 `review.md`。

### 3. 运行测试

```bash
python -m pytest tests/ -v
```

### 4. 产出 `review.md`

- [ ] FR 实现状态
- [ ] 对比差异表
- [ ] 测试结果
- [ ] 阻塞问题

## 完成信号

全部通过 → **APPROVE**。有阻塞 → **REQUEST_CHANGES** 并写明问题。
