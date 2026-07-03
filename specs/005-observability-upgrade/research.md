# Research: 可观测性升级

**Phase**: 0 — Outline & Research
**Date**: 2026-07-03
**Spec**: specs/005-observability-upgrade/spec.md

## Decision Log

### D1: Dashboard 架构 — 单入口 SPA

**Decision**: 单入口 SPA，JS 按功能分文件（dashboard/graph.js, timeline.js 等），observer serve dashboard/index.html
**Rationale**: 与现有 observer 的单 HTML 文件模式兼容（observer 已有 SSE + REST API），不需要前端构建工具链，用户双击 HTML 即可在浏览器打开。JS 分文件而不是全量内联，便于维护和多人协作。
**Alternatives considered**:
- 多 HTML 页面：需要 observer 多路由支持，页面间切换体验不如 SPA 流畅
- 单 HTML 内联所有 JS：文件会 >500 行，不可维护

### D2: 告警持久化 — EventBus + audit_events 双写

**Decision**: EventBus 实时推送 + 写入 audit_events 表持久化
**Rationale**: EventBus 保证实时性（dashboard 打开时即时显示），audit_events 表保证可靠性（dashboard 断开后不丢告警）。重连时回放历史告警。
**Alternatives considered**:
- 纯 EventBus：dashboard 断开后告警丢失
- SQLite-only polling：增加 observer 复杂度，且实时性差

### D3: Agent thinking 粒度 — 每次工具调用

**Decision**: agent 每次工具调用（read_inbox / send_message / submit_decision）发布一次 agent_thinking 事件
**Rationale**: 粒度适中，覆盖所有关键决策点，事件体积可控（<1KB）。如果改为每行推理文本，一次 decision 可能产生数十个事件。
**Alternatives considered**:
- 每次 LLM 调用：粒度太粗，忽略中间推理
- 每行推理文本：粒度太细，trace 体积膨胀数十倍

### D4: CLI 入口 — 独立 python -m

**Decision**: python -m hermes_flow.cli.analyze 独立入口
**Rationale**: 不侵入 Hermes Agent 的 CLI 系统，保持独立可测试。后期如果需要可以包装为 hermes flow 子命令。
**Alternatives considered**:
- 直接做成 hermes flow 插件：需要修改 Hermes 本身 CLI 注册

## Technology Choices

### Mermaid CDN
- 用于仪表盘状态机图渲染
- CDN URL: https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js
- 本地 fallback: dashboard/mermaid.min.js（预下载）

### TraceQueryEngine
- 不引入 ORM，直接使用 storage.py 已有的 sqlite3 连接
- 纯查询类（只读），0 写操作
- 方法签名源自 trace.py 已有的 TraceSpan 和 Span 树结构

### AlertEngine
- 独立线程 + EventBus 订阅
- 不使用 cron/scheduler 框架，time.sleep 轮询即可
- 告警规则硬编码为 config dict，不引入规则引擎 DSL

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Dashboard 中 Mermaid CDN 不可用 | Low | Medium | 预下载 mermaid.min.js 到 dashboard/ 目录 |
| Agent thinking 事件过多撑爆 EventBus | Low | Medium | EventBus 已有队列满丢弃逻辑（observer.py 中 dead subscriber 清理） |
| Trace 查询在大量 span 时变慢 | Medium | Low | 限制返回 top-N，支持分页参数 |
| CLI 与 Hermes Agent 的 hermes 命令冲突 | Low | Low | 独立入口，不做命令注册 |
