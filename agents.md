# Runtime Trace Agent Pool — 进展总结

> 2026-07-06

## 架构

```
User: debate "task"
  → manager agent 选人 (动态生成 flow 拓扑)
  → generate_yaml() 生成 flow YAML
  → flow_init() 创建 run + state.sqlite
  → bootstrap_runtime() 注册 Hook handlers + observer bridge
  → run_flow() 驱动 FSM 循环
      while not terminal:
        gate 多 actor 逐一执行 agent session (max 100 turns)
        产物门禁校验 → flow_step() 推进
      → emit(RUN_COMPLETED) → quick_evaluate() 确定性评分
```

## 自训练体系 (v3)

### Step 1: 数据采集 (每次 run 自动完成)
- **`run_performance` 表**: success_score, agent_scores, bottleneck_state, tool_stats
- **`run_agent_feedback` 表**: per-agent 证据驱动反馈 (category: memory/skill/tool/new_agent)
- Manager 评审: 基于 SQLite 证据 (tool_failures, state_retries) 生成具体改进建议

### Step 2: 模式识别
```bash
debate --analyze    # 跨 run 聚合 → 瓶颈分布/agent 排名/工具热力图
debate --feedback   # 查看待改进清单
```

### Step 3: 自动进化
```bash
debate --evolve              # 生成改进方案
debate --evolve-agent <id>   # EvolutionAgent: 基于 feedback 精准修改
debate --evolve-all          # 一键进化所有 agent + 清空清单
```

## v3 核心改动

### Hook Bus 架构
- **`runtime_trace/hooks.py`**: Hook 总线 — agent loop 唯一副作用出口
- **Checkpoint**: 每轮 agent tool 执行后自动保存, submit_decision 后自动清理
- **Resume**: `debate --resume <run_id>` 从断点恢复, `--from-state` 回溯到指定 state
- **Observer**: 自动启动 (端口 8765), 纯 SQLite 只读, 无代码耦合

### Manager 自由编排
- **动态 flow 生成**: Manager LLM 直接生成 flow 拓扑 (不再硬编码选队)
- **团队阵容注入**: agent system prompt 含 `## 团队阵容` (所有 agent + 自我位置标记)
- **无硬编码兜底**: Manager 响应无效 → 汇报错误 + 重试，不做猜测性 fallback
- **Gate 设计指南**: spec-team.md 完整正文注入 Manager prompt 作为参考

### Agent 技能系统
- **按需加载**: `skill_load("speckit-specify")` 工具 → agent 自己决定何时加载
- **元数据暴露**: system prompt 只显示 skill 名称 + 描述, 不注入全文
- **Speckit 套件**: 
  - spec-writer: speckit-specify/plan/tasks (3 个核心, 30KB)
  - implementer: speckit-implement (14KB)
  - reviewer: speckit-analyze (7.6KB)
  - `.specify/` 脚本+模板已复制到项目

### 单 Agent 修复
- 单 agent 模式下移除 `agent_message_send` (防止自说自话)
- 自循环终止检测: DONE→DONE 循环自动检测并完成

## CLI 命令

```bash
debate <任务>                          # 启动新任务
debate --resume <run_id>               # 恢复中断的 run
debate --resume --history              # 历史列表 (含评分)
debate --resume --performance <id>     # run 详细评分
debate --resume <id> --states          # 查看可恢复状态
debate --resume <id> --from-state X    # 回溯到指定 state
debate --analyze                       # 跨 run 模式分析
debate --evolve                        # 生成改进方案
debate --evolve-agent <id>             # 定向进化单个 agent
debate --evolve-all                    # 进化所有 + 清空清单
debate --feedback [agent_id]           # 查看待改进清单
```

## 目录结构

```
ai-runtime-trace/
├── runtime_trace/            # FSM engine, observer, tools
│   ├── hooks.py            # ⭐ Hook 总线 (v3)
│   ├── observer.py         # HTTP Server (8765) — auto-start
│   ├── storage.py          # SQLite + run_performance + run_agent_feedback
│   └── debate_cli.py       # `debate` CLI entry
├── experiments/agent-pool/
│   ├── auto-debate.py      # ⭐ 核心: manager→flow→run_flow→evaluate
│   ├── cli.py              # debate 命令
│   ├── tool_registry.py    # ⭐ 手写 Schema + skill_load
│   ├── agents/             # 17 agent (含 evolution-agent)
│   ├── shared/skills/      # 按 agent 组织的 speckit 技能
│   └── traits/             # Trait 定义
├── .specify/               # Speckit 脚本 + 模板
├── dashboard/              # 前端 (纯 HTML/JS/CSS)
├── tests/runtime_trace/      # 54 项测试
```

## 运行时

- **Observer**: 自动启动 `http://localhost:8765`
- **Runs 目录**: `experiments/agent-pool/.runtime-trace/runs/`
- **CLI**: `debate "task"`
- **LLM 配置**: `~/.runtime-trace/config.yaml` (独立项目配置)
- **Model**: deepseek-ai/DeepSeek-V4-Flash @ SiliconFlow, max_tokens=8192

## 当前任务

- [x] Hook bus + checkpoint/resume
- [x] Manager 自由编排 + 动态 flow 生成
- [x] 自训练 3-step (data collection → analysis → evolution)
- [x] Speckit 技能套件 + skill_load 按需加载
- [x] 项目独立化: 旧包名 → runtime_trace (54 pass, 零遗留引用)
- [x] E2E 实验验证: Lorenz 混沌预测 5 阶段流水线通过
- [ ] E2E 测试扩展: 补齐 flow_builder / llm_client / fsm gate 路径覆盖
- [ ] Agent 元数据 (SOUL/skills) 暴露给 Manager 用于更精准选队

## 设计原则

- 系统 prompt 零硬编码: 所有提示词从 meta.yaml/SOUL.md/Memory.md/SKILL.md 运行时加载
- Manager 全权负责: 无代码层硬编码兜底, 响应无效 → 错误回报 + LLM 重试
- 证据驱动: feedback 必须引用 SQLite 具体数据, 不空谈
- Skill 按需加载: agent 初始化只暴露元数据, 调用 skill_load 才加载全文

## E2E 测试漏洞 (2026-07-11 审计)

源码 ~11,500 行 / 测试 ~1,500 行 = 覆盖度 ~13%。54 项测试中仅 1 项真正的 FSM 管道场景。

### 致命漏洞

| # | 模块 | 行数 | 问题 | agent 重试能否解决? |
|---|---|---|---|---|
| 1 | `flow_builder.py` | 382 | Manager 返回非法 JSON → 流程崩溃 | ✅ 能。已有 LLM 重试, 缺的是测试 |
| 2 | `llm_client.py` | 171 | HTTP 超时/400/5xx 无行为验证 | ⚠️ 超时可重试, 400 永久错误须改配置 |
| 3 | `fsm.py` gates | 446 | 门禁耗尽/产品门禁/自循环无验证 | ❌ 不能。引擎层安全边界, 不该 agent 重试 |

### 关键洞察: agent 重试 vs 引擎安全边界

**agent 重试**处理 LLM 输出质量问题: 非法 JSON、语法错误、遗漏步骤。这些是非确定性的，重试大概率修复。

**引擎安全边界**防止系统性故障: 自循环检测（`from_state==to_state`）、门禁耗尽（max retries）、产品门禁 stub 检测（0 字节文件）。agent 不知道这些概念——它不知道什么叫"状态没推进"，也不知道自己产出了空文件。交给 agent 重试等于放棄防御。

### 零测试的关键模块

| 模块 | 行数 | 缺失 |
|---|---|---|
| `observer.py` | 1,583 | HTTP/SSE 零请求级测试 |
| `session.py` | 808 | Agent 循环仅间接覆盖 |
| `tool_registry.py` | 403 | 工具发现/沙箱/dispatch 未验证 |
| `flow_builder.py` | 382 | 零测试 |
| `debate_cli.py` | 66 | CLI 参数解析未验证 |
