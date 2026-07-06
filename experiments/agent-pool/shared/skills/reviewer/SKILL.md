# Reviewer Skill

基于 speckit-analyze 的代码审查流程。**只读分析，不修改源文件。**

## 前置条件

`spec.md`, `plan.md`, `tasks.md`, 实现代码已产出。

## 流程

### 1. 加载上下文

```
file_read spec.md
file_read plan.md
file_read tasks.md
file_read implementation-report.md
```

### 2. 交叉一致性分析（speckit-analyze）

对比三个核心产物：spec.md ↔ plan.md ↔ 实现代码

**检测维度**：

| 维度 | 检查方式 |
|---|---|
| Duplication | 重复/近似需求 → 标记合并 |
| Ambiguity | "fast"/"scalable"/"secure" 等无度量标准词 → HIGH |
| Underspecification | 需求缺可度量产出 → MEDIUM |
| Coverage Gap | 需求→无对应任务 OR 任务→无对应需求 → CRITICAL |
| Inconsistency | 术语不一致、数据实体漂移、任务顺序矛盾 → HIGH |

### 3. 严重程度

- **CRITICAL**：需求零覆盖 or 阻塞基线功能
- **HIGH**：重复/冲突需求、模糊的安全属性
- **MEDIUM**：术语漂移、无对应非功能任务
- **LOW**：风格/措辞改进

### 4. 运行测试

```bash
python -m pytest tests/ -v
```

### 5. 产出 `review.md`

分析报告格式：
```
| ID | Category | Severity | Location | Summary | Recommendation |
|---|---|---|---|---|---|
| C1 | Coverage | HIGH | spec.md:L42 | "性能指标"无对应任务 | 添加 benchmark 任务 |
```

含：覆盖率摘要表、Constitution 对齐问题（如有）、Next Actions。

## 完成信号

无 CRITICAL 问题 → **APPROVE**。有阻塞 → **REQUEST_CHANGES**。
