# Implementer Skill

基于 speckit-implement 的代码实现流程。

## 前置条件

`spec.md`, `plan.md`, `tasks.md` 已由上游 agent 产出。

## 流程

### 1. 读上下文

```
file_read spec.md
file_read plan.md
file_read tasks.md
```

### 2. 项目设置

根据 plan.md 技术栈创建项目结构：
- 创建目录结构
- 初始化包管理文件（requirements.txt / pyproject.toml / Makefile）
- 创建 ignore 文件（.gitignore）

### 3. 按 tasks.md 执行

Phase-by-phase 执行：
- **Setup first**：初始化项目结构、依赖、配置
- **Tests before code**：先写测试，再写实现（TDD）
- **Core development**：模型 → 服务 → CLI/端点
- **Respect [P] markers**：标记 [P] 的任务可并行
- **Same-file rule**：操作同一文件的任务不能同时 [P]

### 4. 进度跟踪

每完成一个任务，调用 patch 将其标记为 `[x]`。

### 5. 验证

每次写代码文件后，运行验证命令：
```bash
python -m pytest tests/ -v
```

### 6. 产出 `implementation-report.md`

- 已完成任务对照
- 测试结果
- 已知问题

## 完成信号

全部任务完成 + 测试通过 → **submit_decision(APPROVE)**。
