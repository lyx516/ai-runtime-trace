# 自我进化闭环 — 演进路线图

> 从「能写改进建议但不一定生效」到「改框架 → 验证 → 保留或回滚」

## 核心差距

| 维度 | 现状（Phase 1 上线前） | 目标 |
|---|---|---|
| 数据感知 | 单 run 视角，无对比基准 | 跨 run 模式识别，异常值自动标记 |
| 修改权限 | 仅能改 SKILL.md / Memory.md | 能改 session.py、班底 YAML、fsm.py 配置 |
| 验证闭环 | append-only，不重跑不回滚 | A/B 重跑 → 对比 metric → 保留或回滚 |

## Phase 1：基线采集管道（已完成 ✅）

**目标：** 每个 run 完成后自动采集 per-state metric，EvolutionAgent 能跨 run 查询趋势。

### 改动

| 文件 | 改动 | 状态 |
|---|---|---|
| `evaluate.py` | 新增 `capture_run_metrics()` — 从 thinking_events 聚合 per-state tool_calls、decisions、runtime | ✅ |
| `fsm.py` | `_run_fsm_loop` 退出点调用 `capture_run_metrics()` | ✅ |
| `tools/agent_recall/__init__.py` | schema 新增 `baseline` 查询模式 + `goal_kw` 参数 | ✅ |
| `engine/session.py` | `_handle_agent_recall()` 新增 `baseline` 分支 — 跨 run 聚合 run_performance.tool_stats | ✅ |
| `agents/evolution-agent/SOUL.md` | 新增第 5 条评审原则「先查基线再判断」 | ✅ |

### 验证方式

```bash
# 跑一次 E2E（自动采集 baseline）
debate "使用 spec-clarify-team 班底。任务：写一个简单的 Shell 脚本..."

# 手动验证 run_performance 表有真实数据
sqlite3 experiments/agent-pool/.hermes-flow/runs/<run_id>/state.sqlite \
  "SELECT run_id, tool_stats FROM run_performance"
# 应看到类似：
# {"outcome": "completed@DONE", "total_seconds": 424.4,
#  "by_state": {"SPEC": {...}, "IMPLEMENT": {...}, ...},
#  "decisions": {"SPEC": 1, "IMPLEMENT": 2, ...}, ...}
```

---

## Phase 2：框架修改权限（待实现 🚧）

**目标：** EvolutionAgent 能改 session.py prompt 模板、班底 YAML gate 参数、fsm.py max_turns，改完自动 pytest 验证。

### 改动清单

#### 2.1 `evolve.py` — 新增 2 种 action 类型

```python
action type: "patch_framework"
  target_file — 白名单中的文件路径
  old_string  — 精确匹配的旧文本
  new_string  — 替换文本
  patch_summary — 改动摘要

action type: "revert_framework"
  backup_key  — 进化备份表的 ID
  target_file — 要恢复的文件
```

**白名单：**

```python
FRAMEWORK_WHITELIST = {
    "experiments/agent-pool/engine/session.py",
    "experiments/agent-pool/agents/manager/skills/spec-team.md",
    "experiments/agent-pool/agents/manager/skills/spec-clarify-team.md",
}
```

**约束：**

- 每次 patch 不超过 5 行 diff
- `old_string` 必须精确匹配（防止误改）
- 同一 run 最多 3 次 patch_framework
- 改完自动跑 `pytest tests/hermes_flow/ -q`，不通过则自动回滚

#### 2.2 `storage.py` — 新增 `evolution_backups` 表

```sql
CREATE TABLE IF NOT EXISTS evolution_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_content TEXT NOT NULL,
    patch_summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reverted INTEGER DEFAULT 0
);
```

**方法：** `save_evolution_backup()` / `get_evolution_backup()` / `list_evolution_backups()`

#### 2.3 `SOUL.md` — 新增「框架修改权限」段

完工后需添加约束说明让 LLM 理解边界。

### 工作量

| 文件 | 改动量 |
|---|---|
| `evolve.py` | ~60 行 |
| `storage.py` | ~30 行 |
| `evolution-agent/SOUL.md` | ~10 行 |

**预估：** 1.5 小时

---

## Phase 3：A/B 对比闭环（待实现 🚧）

**目标：** patch_framework 改完框架后，自动重跑同一任务，对比 metric，决定保留或回滚。

### 改动清单

#### 3.1 基准任务套件 — `experiments/agent-pool/benchmarks/tasks.yaml`

```yaml
- id: wc-shell
  goal: "使用 spec-clarify-team 班底。任务：写一个简单的 Shell 脚本..."
- id: word-freq-python
  goal: "使用 spec-clarify-team 班底。任务：写一个Python脚本读取文本文件并统计词频"
- id: todo-cli
  goal: "使用 spec-clarify-team 班底。任务：写一个命令行 TODO 管理工具"
```

#### 3.2 `evaluate.py` — 新增 `compare_runs()`

```python
def compare_runs(store, run_a: str, run_b: str) -> dict:
    """对比两个 run 的 tool_stats，返回 delta + regression 判定。"""
```

返回结构：

```json
{
  "delta": {"SPEC": -2, "IMPLEMENT": -15, "REVIEW": -5},
  "total_seconds_delta": -87.3,
  "regression": false
}
```

#### 3.3 `evolve.py` — A/B 流程

在 `run_evolution()` 末尾，如果执行了 `patch_framework`：

```python
if any(a["type"] == "patch_framework" for a in applied_actions):
    benchmark = select_benchmark(original_goal)
    new_run_id = run_debate(benchmark["goal"])
    comparison = compare_runs(store, original_run_id, new_run_id)
    if comparison["regression"]:
        revert_all_framework_patches(original_run_id)
```

#### 3.4 判定阈值

| Delta | 判定 |
|---|---|
| tool_calls 减少 >15% | 有效改进，保留 |
| 变化 ±15% | 无明显效果，保留 |
| tool_calls 增加 >15% | 回归，回滚 |
| 重跑失败 (aborted) | 回归，回滚 |
| pytest 不通过 | 回滚（Phase 2 已覆盖） |

### 工作量

| 文件 | 改动量 |
|---|---|
| `benchmarks/tasks.yaml` | 新建 |
| `evaluate.py` | ~30 行 |
| `evolve.py` | ~40 行 |

**预估：** 1 小时

---

## 时间线

```
Phase 1（基线采集）     ─── ✅ 已上线
                            ↓
Phase 2（框架修改权限）  ─── 〰️ 下一个
                            ↓
Phase 3（A/B 对比闭环）  ─── 🎯 最终形态
```

**总计工作量：** ~3.5 小时（3 个独立可验证里程碑）

## 风险

| 风险 | 规避措施 |
|---|---|
| Phase 2 白名单文件被改坏 | pytest gate + 自动回滚 + backup 表 |
| LLM 生成错误 patch | old_string 精确匹配 + SOUL 约束 + 5 行上限 |
| Phase 3 重跑成本高（~7min/run） | 只对 patch_framework 触发的进化做 A/B |
| Phase 2 白名单太窄不够用 | 后续可加，初始只放 3 个最关键的 |