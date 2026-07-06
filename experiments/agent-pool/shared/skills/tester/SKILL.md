# 测试执行技能（tester / code-reviewer 共用）

## 适用场景

在 REVIEW 或 TEST 阶段执行自动化测试，验证代码质量。

## 执行流程

### 1. 发现测试

```bash
find . -name "test_*.py" -o -name "*_test.py" -o -name "test*.py" | head -20
find . -name "Makefile" -o -name "CMakeLists.txt" | head -5
```

### 2. 运行测试

```bash
# Python
python -m pytest tests/ -v --tb=short 2>&1

# 如果没有 tests 目录
python -m pytest . -v --tb=short 2>&1
```

### 3. 记录结果

将测试输出写入 `test-report.md`：
- 通过/失败数量
- 失败用例详情
- 覆盖率（如有）

### 4. 判断

- 全部通过 → APPROVE
- 有失败 → 记录到 review.md，REQUEST_CHANGES
- 无测试 → BLOCKING ISSUE，REQUEST_CHANGES并说明需要补充测试

## 完成信号

测试执行完毕 → 产出 `test-report.md` → submit_decision
