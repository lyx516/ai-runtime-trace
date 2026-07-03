# Quickstart: 可观测性升级

**Date**: 2026-07-03

## 环境要求

- Python 3.13（项目已有）
- 现代浏览器（Chrome/Firefox/Safari 支持 Mermaid）
- 已安装 pytest（`pip install pytest`）

## 快速验证

### 1. CLI 分析命令

```python
# 对一个已完成的 flow run 执行分析
from hermes_flow.trace_query import TraceQueryEngine

engine = TraceQueryEngine(run_dir=".hermes-flow/runs/<run_id>")
tree = engine.trace_tree(trace_id="abc123")
summary = engine.trace_analyze(run_id="a1b2c3")
```

```bash
# 或通过 CLI
python -m hermes_flow.cli.analyze <run_id>
python -m hermes_flow.cli.analyze --json <run_id>
python -m hermes_flow.cli.diff <run_id_a> <run_id_b>
python -m hermes_flow.cli.budget <run_id>
```

### 2. 仪表盘

```python
from hermes_flow.observer import FlowObserver

# 启动 observer（serve dashboard 目录 + REST API + SSE）
obs = FlowObserver(port=8080, project_root=".")
obs.start()

# 浏览器打开 http://localhost:8080
# 输入 run_id 即可查看 Mermaid 状态图、时间线、实时 agent 日志
```

### 3. 性能基准

```bash
python -m hermes_flow.benchmark --agent-count 5
# 输出: trace_overhead_pct < 5, session_timing_distribution, sqlite_io_latency
```

### 4. 运行测试

```bash
pytest tests/ -q
# 应包含新增的 test_trace_query.py, test_alerts.py, test_cli_analyze.py
```

## 项目结构变更

### 新增文件

```
hermes_flow/
├── cli/
│   ├── __init__.py
│   └── analyze.py
├── trace_query.py          # TraceQueryEngine
├── alerts.py               # AlertEngine
├── benchmark.py            # 性能基准

dashboard/                  # 独立目录，observer serve 静态文件
├── index.html              # SPA 入口
├── graph.js                # Mermaid 状态图
├── timeline.js             # 时间线瀑布图
├── stream.js               # 实时 agent 日志流
├── analysis.js             # 统计聚合页
├── diff.js                 # 对比页
├── mermaid.min.js          # 预下载

tests/hermes_flow/
├── test_trace_query.py
├── test_alerts.py
├── test_cli_analyze.py
└── test_benchmark.py
```

### 修改文件

```
hermes_flow/
├── observer.py     # 新增 serve dashboard 目录、新增 REST API 端点
├── trace.py        # 新增 trace_tree() / trace_analyze() 方法
├── agent_tools.py  # 在每个工具调用中发布 agent_thinking 事件
└── runtime_loop.py # 在 tick 中调用 AlertEngine
```
