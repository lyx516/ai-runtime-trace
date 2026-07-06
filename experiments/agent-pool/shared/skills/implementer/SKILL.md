# Implementer Skill

基于 Hermes 内置 speckit-implement 流程的代码实现。

## 前置条件

存在 `spec.md`, `plan.md`, `tasks.md`。

## 流程

### 1. 读上下文

```
file_read spec.md
file_read plan.md
file_read tasks.md
```

### 2. 按 tasks.md 逐任务实现

每个任务：创建文件 → 写代码 → 写测试 → 跑测试 → 记录到 `implementation-report.md`

### 3. 编译/测试

```bash
pip install -r requirements.txt 2>/dev/null || true
python -m pytest tests/ -v
```

### 4. 产出 `implementation-report.md`

包含：已完成任务对照、测试结果、已知问题、文件清单。

## 完成信号

实现 + 测试通过 → **submit_decision(APPROVE)**。
