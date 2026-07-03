# Implementation Plan: 可观测性升级

**Branch**: `005-observability-upgrade` | **Date**: 2026-07-03 | **Spec**: specs/005-observability-upgrade/spec.md

**Input**: Feature specification from `/specs/005-observability-upgrade/spec.md`

## Summary

在 Hermes Flow 现有三层架构（Storage + FSM Engine + Runtime Loop）基础上新增 Observability Layer，提供五个增量能力：(1) Trace 查询引擎（span 树聚合+分析+diff），(2) 独立前端仪表盘（SPA，Mermaid 状态图+时间线+实时日志），(3) Agent 决策透明化（source_references + thinking 事件），(4) 运行时告警引擎，(5) CLI 分析工具。

所有改动对现有三层架构零侵入——只增加新模块和新 hook，不修改核心引擎逻辑。

## Technical Context

**Language/Version**: Python 3.13（项目已有）

**Primary Dependencies**:
- 存量依赖：sqlite3（stdlib）、json、http.server（stdlib）— 无需新增
- 新增外部依赖：无（全部基于标准库 + 现有代码）
- Mermaid 在 HTML dashboard 中通过 CDN 加载（`<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js">`）

**Storage**: 已存在 SQLite（storage.py 的 RuntimeStore）+ trace_events / audit_events 表。新增 TraceQueryEngine 封装查询聚合，无需表迁移。

**Testing**: pytest（已安装，74 tests passing）

**Target Platform**: macOS/Linux（CLI + 浏览器 HTML dashboard）

**Project Type**: CLI工具 + 本地 HTTP 仪表盘（已有 observer 模式）

**Performance Goals**:
- trace 树查询 < 1s（单 run 上万 span）
- Agent thinking 事件大小 < 1KB/事件（防止 EventBus 队列撑爆）
- 仪表盘初始加载 < 2s

**Constraints**:
- 不引入前端构建工具链（无 npm/webpack/vite）
- 不修改现有 storage.py / engine.py / runtime_loop.py 的核心逻辑
- 所有新增代码在 `hermes_flow/` 下独立文件或目录

**Scale/Scope**:
- 单进程/单 run 粒度的可观测性（非分布式追踪）
- 仪表盘面向开发者本地调试，非生产部署

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Minimal Useful Scope**: ✅ 5 个 User Story 各自独立可测试。P1 的 3 个（CLI trace 查询、仪表盘、agent 审计）构成最小可用集；P2 的 2 个（告警、基准测试）明确标记为延伸。
- **Reusable Core Only**: ✅ TraceQueryEngine 是唯一新增抽象，其两个方法（trace_tree + trace_analyze）均由 FR-001 和 FR-002 驱动，有两个以上使用场景。AlertEngine 是独立模块，无多余抽象层。
- **Readability**: ✅ 产物命名（TraceQueryEngine / AlertEngine / AgentDecisionLog）描述领域意图，不使用缩写缩写。
- **Evidence Before Expansion**: ✅ 所有设计选择来自 spec 中明确的功能需求，无推测性基础设施。Dashboard SPA 架构选择在 clarifications 中用户确认。
- **宁缺毋滥 Quality Bar**: ✅ 告警只检测不干预（out-of-scope 已声明）。Agent thinking 粒度钳制在每次工具调用，不尝试全量推理捕获。Benchmark 只测量不自动修复。

## Project Structure

### Documentation (this feature)

```text
specs/005-observability-upgrade/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (API schemas)
└── tasks.md             # Phase 2 output (speckit-tasks)
```

### Source Code (repository root)

```text
hermes_flow/
├── engine.py / storage.py / schemas.py / trace.py       # 现有，0 修改
├── runtime_loop.py / agent_runner.py / observer.py       # 现有，+ hook
├── cli/                          # 新增目录
│   ├── __init__.py
│   └── analyze.py                # hermes flow analyze/diff/budget CLI
├── trace_query.py                # 新增: TraceQueryEngine
├── alerts.py                     # 新增: AlertEngine
├── benchmark.py                  # 新增: 性能基准脚本

dashboard/                        # 仪表盘源码目录（observer serve 此目录）
├── index.html                    # SPA 入口
├── graph.js                      # Mermaid 状态图
├── timeline.js                   # 时间线瀑布图
├── stream.js                     # 实时 agent 日志流
├── analysis.js                   # 统计聚合页
├── diff.js                       # 对比页
├── mermaid.min.js                # 预下载或 CDN

tests/hermes_flow/
├── test_trace_query.py           # 新增测试
├── test_alerts.py                # 新增测试
├── test_cli_analyze.py           # 新增测试
└── test_benchmark.py             # 新增测试（可选）
```

## Complexity Tracking

（无。Constitution Check 全部通过，无需 justify 任何违规。）
