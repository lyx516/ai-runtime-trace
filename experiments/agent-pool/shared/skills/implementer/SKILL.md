# Speckit Implement 执行技能（implementer）

你使用 speckit-implement 流程完成代码实现。

## 前置条件

确认以下文件存在（由 spec-writer/plan-maker/task-breaker 产出）：
- `spec.md` — 功能规格
- `plan.md` — 技术方案
- `tasks.md` — 任务清单

如果文件不存在，先用 file_read 确认，缺失则 REQUEST_CHANGES。

## 执行流程

### 1. 读取上下文
```
file_read spec.md
file_read plan.md
file_read tasks.md
```

### 2. 按 tasks.md 逐任务实现

每个任务：
1. 创建必要的目录结构
2. 编写代码文件（write_file）
3. 编写测试文件（write_file）
4. 运行测试验证（terminal）
5. 记录完成状态到 implementation-report.md

### 3. 编译/测试

```bash
# Python 项目
pip install -r requirements.txt 2>/dev/null || true
python -m pytest tests/ -v

# C 项目
make && make test
```

### 4. 产出 implementation-report.md

报告必须包含：
- 完成的任务列表（对照 tasks.md）
- 测试结果摘要（通过/失败数量）
- 已知问题（如有）
- 文件清单

## 完成信号

实现完成 + 测试通过后调用 **submit_decision(APPROVE)**。
