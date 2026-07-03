#!/usr/bin/env python3
"""
auto-debate — 一句话启动多 Agent 辩论。

用法:
    python auto-debate.py <任务描述>

示例:
    python auto-debate.py "设计一个兼顾速度和准确率的向量数据库"
    python auto-debate.py "讨论缓存淘汰策略 LRU vs ARC 的取舍"

管理 Agent 自动分析任务、从池中选择合适的 Agent、生成 flow 并驱动辩论。
每个 Agent 定义在 agents/<id>/meta.yaml 中，包括灵魂、技能、角色元信息。
"""

import json
import os
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

PROJECT_ROOT = "/Users/liyuxuan/ai-runtime-trace"
AGENTS_DIR = Path(PROJECT_ROOT) / "experiments" / "agent-pool" / "agents"
SHARED_SKILLS_DIR = Path(PROJECT_ROOT) / "experiments" / "agent-pool" / "shared" / "skills"
OUTPUT_DIR = Path(PROJECT_ROOT) / "experiments" / "agent-pool" / "generated"


def load_agents() -> dict:
    """Load all agents from agents/<id>/meta.yaml."""
    import yaml
    agents = {}
    if not AGENTS_DIR.exists():
        print("❌ Agent 池目录不存在", file=sys.stderr)
        sys.exit(1)
    for d in sorted(AGENTS_DIR.iterdir()):
        meta = d / "meta.yaml"
        if meta.exists():
            with open(meta) as f:
                info = yaml.safe_load(f)
                info["_path"] = str(d)
                # Resolve assigned skills from shared/skills/
                assigned = info.get("assigned_skills", [])
                resolved = []
                if SHARED_SKILLS_DIR.exists():
                    for sid in assigned:
                        sp = SHARED_SKILLS_DIR / sid / "SKILL.md"
                        if sp.exists():
                            text = sp.read_text(encoding="utf-8")
                            desc = sid
                            if text.startswith("---"):
                                parts = text.split("---", 2)
                                if len(parts) >= 3:
                                    import yaml as y2
                                    fm = y2.safe_load(parts[1])
                                    desc = fm.get("description", sid)
                            resolved.append({"id": sid, "description": desc, "content": text[:1000]})
                info["_assigned_skills"] = resolved
                agents[info["agent_id"]] = info
    return agents


def call_llm(system: str, prompt: str, model: str = "deepseek-chat",
             temperature: float = 0.7, max_tokens: int = 1000) -> dict:
    """Call DeepSeek API, return parsed JSON response."""
    api_key = os.environ.get("DEEPSEEK_API_KEY") or ""
    if not api_key:
        print("❌ 请设置 DEEPSEEK_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    resp = urllib.request.urlopen(req, timeout=60)
    content = json.loads(resp.read())["choices"][0]["message"]["content"].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to find {...} block (handles multi-line and nested objects)
        import re
        brace_depth = 0
        start = -1
        for i, ch in enumerate(content):
            if ch == '{':
                if start == -1:
                    start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and start != -1:
                    try:
                        return json.loads(content[start:i+1])
                    except json.JSONDecodeError:
                        pass
                    start = -1
        # Last resort
        return {"value": "APPROVE", "reason": content[:200]}


# ══════════════════════════════════════════════════════════════════════
#  Phase 1: 管理 Agent 分析任务并选择 Agent
# ══════════════════════════════════════════════════════════════════════

def manager_select_agents(goal: str, agents: dict) -> list[str]:
    """Manager agent analyzes goal and selects appropriate agents."""
    # Read manager's team skills
    manager_skills_dir = Path(__file__).resolve().parent / "agents" / "manager" / "skills"
    team_skills_text = ""
    if manager_skills_dir.exists():
        team_lines = []
        for f in sorted(manager_skills_dir.iterdir()):
            if f.suffix == ".md":
                name = f.stem
                content = f.read_text(encoding="utf-8")
                descline = [l for l in content.split("\n") if l.strip() and not l.startswith("#")]
                desc = descline[1] if len(descline) > 1 else name
                members = [l.strip("- `") for l in content.split("\n") if "`" in l]
                team_lines.append(f"  {name}: {desc} | 成员: {', '.join(members[:6])}")
        if team_lines:
            team_skills_text = "\n可用班底技能:\n" + "\n".join(team_lines)

    agent_list = "\n".join([
        f"  - {aid}: {info.get('display_name', aid)} | 角色: {info.get('role', '')} | "
        f"{info.get('description', '')}"
        for aid, info in agents.items() if aid != "manager"
    ])

    system = f"""你是流程管理专家。根据用户目标从 Agent 池中选择 3-6 个。{team_skills_text}

选择原则：
- 纯方案推演/辩论 → debate-team (designer + critic + mediator + decider)
- 完整开发流水线 → spec-team (spec-writer + plan-maker + task-breaker + implementer + code-reviewer)
- 调研分析 → research-team (researcher + analyst + writer)
- 全栈（辩论→实现→文档） → fullstack-team
- 简单修复 → quick-fix-team (implementer + tester)
- 也可以混编多个班底

响应格式（严格 JSON）：
{{"agents": ["id1","id2",...], "reason": "选择理由", "team": "使用的班底名称"}}
"""

    user = f"## 任务\n{goal}\n\n## Agent 池\n{agent_list}\n\n请选择。"
    print("\n🤔 管理 Agent 正在分析任务...")
    result = call_llm(system, user, temperature=0.3)
    selected = result.get("agents", [])
    reason = result.get("reason", "")

    valid = [a for a in selected if a in agents and a != "manager"]
    if len(valid) < 2:
        valid = ["designer", "critic", "mediator", "decider"]
        reason = "选择不足，使用默认辩论组合"

    print(f"  选择了: {', '.join(valid)}")
    print(f"  理由: {reason}")
    return valid


# ══════════════════════════════════════════════════════════════════════
#  Phase 2: 生成 Flow YAML
# ══════════════════════════════════════════════════════════════════════

def make_gate(roles, pass_vals, fail_vals, on_pass, on_fail="", max_r=0):
    g = {"type": "decision", "required_roles": roles,
         "pass_values": pass_vals, "fail_values": fail_vals,
         "blocked_values": ["BLOCKED"], "on_pass": on_pass}
    if on_fail:
        g["on_fail"] = on_fail
        g["max_rounds"] = max_r if max_r > 0 else 3
    return g


def self_gate(roles, on_pass, on_fail="", max_r=1):
    return make_gate(roles, ["APPROVE"], ["REQUEST_CHANGES"] if on_fail else [],
                     on_pass, on_fail, max_r)


def product_gate(roles, required_file: str, on_pass: str, on_fail: str = "", max_r: int = 2):
    """Product gate: checks delivered file exists. No LLM subjectivity."""
    return {
        "type": "product",
        "required_roles": roles,
        "required_file": required_file,
        "pass_values": ["APPROVE"],
        "fail_values": ["REQUEST_CHANGES"],
        "blocked_values": ["BLOCKED"],
        "on_pass": on_pass,
        "on_fail": on_fail,
        "on_exhausted": "ABORT",
        "max_rounds": max_r,
    }


def make_state(sid, desc, actors, gate=None, output_artifacts=None):
    s = {"description": desc, "actors": actors}
    if gate:
        s["gate"] = gate
    if output_artifacts:
        s["output_artifacts"] = output_artifacts
    return s


def generate_yaml(goal: str, agent_ids: list[str], run_name: str, agents: dict,
                  flow_topology: list[dict] | None = None) -> Path:
    """Generate flow YAML from a topology config. No role-specific hardcoding."""
    selected = {aid: agents[aid] for aid in agent_ids}
    import yaml as yaml_lib

    flow_id = f"auto-{uuid.uuid4().hex[:8]}"

    yaml_data = {
        "flow_id": flow_id, "name": run_name, "version": 1,
        "initial_state_id": "", "terminal_state_ids": ["DONE", "ABORT"],
        "agents": {}, "states": {},
    }
    for aid, info in selected.items():
        yaml_data["agents"][aid] = {
            "profile_name": f"pool-{aid}", "soul": info.get("soul", ""),
            "skills": info.get("skills", []), "toolsets": info.get("toolsets", []),
            "memory_mode": "run_isolated", "read_scope": [],
            "write_scope": [f"experiments/agent-pool/output/{flow_id}/"],
        }

    states, order = {}, []

    # If no topology provided, build one from selected roles (backward compat)
    if not flow_topology:
        flow_topology = []
    # Filter topology to only include states where all actors are in agent_ids
    for step in flow_topology:
        sid = step["state"]
        raw_actors = step.get("actors", "")
        if isinstance(raw_actors, str):
            expected = raw_actors.replace(" ", "").split("+")
            actors = [a for a in agent_ids if a in expected]
        elif isinstance(raw_actors, list):
            actors = [a for a in agent_ids if a in raw_actors]
        else:
            actors = []
        if not actors:
            continue
        g = step.get("gate", {})
        gt = g.get("type", "decision")
        outputs = step.get("output_artifacts", [])
        if not outputs and gt == "product" and g.get("file"):
            outputs = [g["file"]]

        if gt == "product":
            gate = product_gate(actors, outputs[0] if outputs else f"{sid.lower()}.md",
                                g["pass"], g.get("fail", "ABORT"), g.get("max", 3))
        else:
            gate = self_gate(actors, g["pass"], g.get("fail", "ABORT"), g.get("max", 3))

        states[sid] = make_state(sid, step.get("description", sid), actors, gate,
                                 output_artifacts=outputs)
        order.append(sid)

    for tid in ["DONE", "ABORT"]:
        if tid not in states:
            states[tid] = {"terminal": True, "actors": []}
        if tid not in order:
            order.append(tid)

    yaml_data["initial_state_id"] = order[0] if order else "DONE"
    yaml_data["states"] = {s: states[s] for s in order}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{flow_id}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml_lib.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return path


# ══════════════════════════════════════════════════════════════════════
#  Phase 3: Flow Engine Runtime
#  NOT manager responsibility — pure Hermes Flow state machine driver.
# ══════════════════════════════════════════════════════════════════════

def agent_prompt(role_id: str, soul: str, goal: str, state_id: str, round_n: int,
                 history: list, inbox: list, gate: dict, tools_list: str = "") -> tuple[str, str]:
    """Build system + user prompts for an agent, following Hermes prompt architecture."""
    pass_vals = gate.get("pass_values", ["APPROVE"])
    fail_vals = gate.get("fail_values", [])
    on_pass = gate.get("on_pass", "DONE")
    on_fail = gate.get("on_fail", "")

    hist_text = "\n".join([f"  [{i+1}] {d['from_role']}: {str(d['content'])[:200]}"
                          for i, d in enumerate(history)]) if history else "  (无)"
    inbox_text = "\n".join([f"  从 {d['from_role']}: {d['content']}"
                          for d in inbox]) if inbox else "  (空)"

    # ── System prompt (Hermes architecture) ──────────────────────────────────
    system = f"""## 你的身份
你是 {role_id}，{soul[:400]}

## 工具使用规范（必须遵守）
你必须使用工具来执行实际操作 —— 不能只描述你将要做什么而不真正去做。
当你说要执行某个操作时（例如"我将写文件"、"让我查一下"、"我来实现"），
你必须立即在同一轮调用对应的工具。不允许在承诺未来行动后结束本轮。

持续工作直到任务真正完成。不要写完一个框架或一段计划就提交 APPROVE。
如果你手头有可以完成任务的工具，直接使用它们，而不是描述你打算怎么做。

每一轮响应要么（a）包含推进工作的工具调用，要么（b）提交决策。
只描述意图而不行动是不可接受的。

## 可用工具
{tools_list}

## 响应格式（严格 JSON）
{{"value": "APPROVE|REQUEST_CHANGES|BLOCKED", "reason": "理由",
  "send_to": ["recipient"], "message": "消息内容",
  "tool": "工具ID", "tool_args": {{"参数名": "参数值"}}}}

- value: 你的决策
- tool/tool_args: 可选，先调工具干活，再提交决策
- send_to/message: 可选，给其他 agent 发消息"""

    user = f"""## 辩论上下文
**状态**: {state_id}（第{round_n}轮） **目标**: {goal}

## 讨论历史
{hist_text}

## 收件箱
{inbox_text}

## Gate
通过: {pass_vals}  拒绝: {fail_vals}
通过→ {on_pass}  拒绝→ {on_fail}

## 任务
1. 阅读历史和收件箱
2. 如有话说，设 send_to+message
3. 提交决策"""
    return system, user


def run_flow(goal: str, agent_ids: list[str], yaml_path: Path, run_name: str, agents: dict):
    """Flow engine: drive Hermes Flow state machine until completion. Not manager's job."""
    sys.path.insert(0, PROJECT_ROOT)
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT

    from hermes_flow.tools import flow_init, flow_step, flow_send, flow_decide
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.schemas import RunStatus
    from hermes_flow.trace import SqliteTracer, set_tracer
    from hermes_flow.engine import advance_state as eng_advance

    result = flow_init(PROJECT_ROOT, str(yaml_path), run_name)
    if not result.get("ok"):
        print(f"❌ flow_init 失败: {result.get('error')}")
        print(f"   {result.get('details', [])}")
        # Clean up empty database left by failed init
        failed_run_id = result.get("run_id", "")
        if failed_run_id:
            failed_dir = Path(PROJECT_ROOT) / ".hermes-flow" / "runs" / failed_run_id
            if failed_dir.exists():
                import shutil
                shutil.rmtree(failed_dir, ignore_errors=True)
        sys.exit(1)

    run_id = result["run_id"]
    run_dir = Path(PROJECT_ROOT) / ".hermes-flow" / "runs" / run_id
    store = RuntimeStore(run_dir)
    store.init_schema()
    set_tracer(SqliteTracer(store, run_id=run_id))
    conn = store.connect()

    print(f"\n{'='*60}")
    print(f"🏁 Run: {run_id}")
    print(f"🎯 {goal}")
    print(f"👥 {', '.join(agent_ids)}")
    print(f"🌐 http://localhost:8765")
    print(f"{'='*60}\n")

    round_counter: dict[str, int] = {}

    while True:
        row = conn.execute("SELECT status, current_state_id FROM runs WHERE run_id=?",
                          (run_id,)).fetchone()
        if not row:
            break
        status_str, state_id = row["status"], row["current_state_id"]
        if RunStatus(status_str) in (RunStatus.COMPLETED, RunStatus.ABORTED):
            print(f"\n✅ 完成！最终状态: {status_str} @ {state_id}\n")
            break

        srow = conn.execute("SELECT state_json FROM states WHERE run_id=? AND state_id=?",
                           (run_id, state_id)).fetchone()
        if not srow:
            break
        state_dict = json.loads(srow["state_json"])
        gate = state_dict.get("gate", {})
        required_roles = gate.get("required_roles", [])
        pass_vals = gate.get("pass_values", ["APPROVE"])
        fail_vals = gate.get("fail_values", [])
        on_pass = gate.get("on_pass", "DONE")
        on_fail = gate.get("on_fail", "")
        max_r = gate.get("max_rounds", 3)

        if not gate:
            targets = state_dict.get("transitions", [])
            target = targets[0].get("target_state_id", "DONE") if targets else "DONE"
            eng_advance(run_id, state_id, target, "auto", 1, store)
            continue

        round_counter[state_id] = round_counter.get(state_id, 0) + 1
        cur_round = round_counter[state_id]
        print(f"\n── [{state_id}] 第{cur_round}轮 — {required_roles}")

        if cur_round > max_r:
            exhausted = gate.get("on_exhausted", on_fail)
            print(f"  ⏰ 超限({max_r}) → {exhausted}")
            eng_advance(run_id, state_id, exhausted, f"round_exhausted({cur_round})", cur_round, store)
            continue

        for role_id in required_roles:
            # ── Standard LLM agent ─────────────────────────────────
            info = agents.get(role_id, {})
            soul = info.get("soul", "")

            inbox_rows = conn.execute(
                "SELECT m.from_role, m.content FROM inboxes i JOIN messages m ON i.message_id=m.message_id WHERE i.run_id=? AND i.role_id=? ORDER BY m.created_at",
                (run_id, role_id)).fetchall()

            all_msgs = conn.execute(
                "SELECT from_role, content FROM messages ORDER BY rowid").fetchall()

            from tools_runner import list_available
            tool_info = list_available(role_id)
            uni = "\\n".join([f"    {t} — 通用工具（不计入限制）" for t in tool_info.get("universal", [])])
            allowed = "\\n".join([f"    {t}" for t in tool_info.get("allowed", [])])
            tools_list = f"## 可用工具\\n\\n### 通用工具（始终可用）:\\n{uni}\\n\\n### 专用工具（max {tool_info.get('max_non_universal', 5)}）:\\n{allowed}" if tool_info.get("allowed") else f"## 可用工具\\n{uni}"

            # Append usage examples for key tools
            usage_hints = "\\n\\n**工具参数说明**:\\n"
            usage_hints += "  file_write: tool_args = {\"path\": \"文件名\", \"content\": \"文件内容\"}\\n"
            usage_hints += "  file_read:  tool_args = {\"path\": \"文件名\"}\\n"
            usage_hints += "  web_search: tool_args = {\"query\": \"搜索关键词\"}\\n"
            usage_hints += "  memory_write: tool_args = {\"content\": \"记忆内容\", \"mode\": \"append|overwrite\"}\\n"
            tools_list += usage_hints

            sys_p, usr_p = agent_prompt(role_id, soul, goal, state_id, cur_round,
                                         all_msgs, inbox_rows, gate, tools_list)

            print(f"  🤖 {role_id}...", end="", flush=True)
            t0 = time.time()
            try:
                resp = call_llm(sys_p, usr_p, temperature=0.8, max_tokens=2000)
                dt = time.time() - t0
                val = resp.get("value", "APPROVE").upper()
                print(f" {dt:.1f}s → {val}")

                msg = resp.get("message", "")
                send_to = resp.get("send_to", [])
                if msg and send_to:
                    r2 = flow_send(run_id, state_id, role_id, send_to, "debate", msg)
                    if r2.get("ok"):
                        print(f"     💬 → {send_to[0]}: {msg[:60]}...")

                # Execute tool if specified
                tool_name = resp.get("tool", "")
                tool_args = resp.get("tool_args", {})
                if tool_name:
                    from tools_runner import execute as exec_tool
                    from agent_tools import dispatch as dispatch_universal
                    if tool_name in ("memory_read", "memory_write", "skill_create", "skill_list", "agent_summarize"):
                        tool_result = dispatch_universal(role_id, tool_name, tool_args)
                    else:
                        tool_result = exec_tool(role_id, tool_name, tool_args)
                    print(f"     🔧 {tool_name}: {'✅' if tool_result.get('ok') else '❌'} {str(tool_result)[:80]}")

                # Product gate enforcement: verify output artifacts exist
                output_artifacts = state_dict.get("output_artifacts", [])
                if output_artifacts:
                    for art_name in output_artifacts:
                        art_path = Path(PROJECT_ROOT) / art_name
                        if art_path.exists() and art_path.stat().st_size > 0:
                            print(f"     📄 {art_name} ({art_path.stat().st_size} bytes) ✅")
                        else:
                            print(f"     ⚠️  产物 {art_name} 缺失！降级为 REQUEST_CHANGES")
                            val = "REQUEST_CHANGES"

                flow_decide(run_id, state_id, role_id, val, resp.get("reason", ""))

                if val in fail_vals:
                    break
            except Exception as e:
                print(f" ❌ {e}")
                flow_decide(run_id, state_id, role_id, "APPROVE", f"fallback: {e}")

        r3 = flow_step(run_id)
        if r3.get("ok"):
            print(f"  → {r3.get('from_state')} → {r3.get('to_state')}")
        else:
            print(f"  ⏸ pending: {r3.get('error', '?')}")
            break

    # ── Manager evaluation phase ──────────────────────────────────
    if agents.get("manager"):
        print(f"\n{'='*60}")
        print(f"📝 管理 Agent 评审会议")
        print(f"{'='*60}")
        try:
            manager_evaluate(run_id, goal, agent_ids, agents, store)
        except Exception as e:
            print(f"  ⚠️ 评审异常: {e}")

    # Final report
    trans = conn.execute("SELECT from_state_id, to_state_id FROM transitions ORDER BY rowid").fetchall()
    msgs = conn.execute("SELECT from_role, substr(content,1,60) FROM messages ORDER BY rowid").fetchall()
    decs = conn.execute("SELECT state_id, role_id, value FROM decisions ORDER BY rowid").fetchall()

    print(f"\n{'='*60}")
    print(f"📊 结果")
    print(f"{'='*60}")
    print(f"Run: {run_id}")
    print(f"决策: {len(decs)} | 消息: {len(msgs)} | 转换: {len(trans)}")
    print(f"\n💬 消息:")
    for r in msgs:
        print(f"  {r['from_role']:12s}| {r['substr(content,1,60)']}")
    print(f"\n📋 决策:")
    for r in decs:
        print(f"  [{r['state_id']:15s}] {r['role_id']:12s} → {r['value']}")
    print(f"\n🌐 http://localhost:8765\n")


# ══════════════════════════════════════════════════════════════════════
#  Manager evaluation
# ══════════════════════════════════════════════════════════════════════

def manager_evaluate(run_id: str, goal: str, agent_ids: list[str],
                     agents: dict, store) -> None:
    """Manager reads full transcript and evaluates each agent."""
    conn = store.connect()

    # Read full transcript
    all_msgs = conn.execute(
        "SELECT from_role, content FROM messages ORDER BY rowid"
    ).fetchall()
    all_decs = conn.execute(
        "SELECT state_id, role_id, value, reason FROM decisions ORDER BY rowid"
    ).fetchall()

    transcript = "\n".join([
        f"[{r['from_role']}] {r['content'][:200]}"
        for r in all_msgs
    ])
    decisions_summary = "\n".join([
        f"  [{r['state_id']}] {r['role_id']} → {r['value']}"
        for r in all_decs
    ])

    # Scan for deliverable files produced by agents
    deliverables = {}
    for fname in ["spec.md", "plan.md", "tasks.md", "review.md", "test-report.md",
                   "research.md", "analysis.md", "report.md", "README.md"]:
        fpath = Path(PROJECT_ROOT) / fname
        if fpath.exists() and fpath.stat().st_size > 0:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
            deliverables[fname] = content[:500]
    deliverables_text = ""
    if deliverables:
        deliverables_text = "\n## 交付物检查\n" + "\n".join(
            f"### {name}\n{content[:300]}" for name, content in deliverables.items()
        )

    # Use LLM as manager to evaluate
    manager_info = agents.get("manager", {})
    soul = manager_info.get("soul", "")

    # Build evaluation system prompt
    system = f"""你是流程管理专家，负责评审辩论中各个 agent 的表现。

{soul[:300]}

评审要求：
1. 逐一检查每个 agent 是否产出了应有的交付物文件
2. 交付物内容是否与任务目标一致
3. 该 agent 是否有效履行了角色职责
4. 表现亮点或需要改进之处
5. 是否展示了有用的技巧（可保存为 skill）

响应 JSON:
{{"evaluations": {{"agent_id": "评语（含交付物评价）", ...}},
  "team_pattern": "团队搭配效果总结（30-50字）",
  "gate_suggestion": "gate 改进建议"}}"""

    user = f"""## 任务目标
{goal}

## 参与 Agent
{', '.join(agent_ids)}

## 完整消息记录
{transcript[:2000]}

## 决策序列
{decisions_summary[:1000]}

## 交付物文件
{deliverables_text[:2000]}"""

    print("  🤖 管理 Agent 评审中...")
    result = call_llm(system, user, temperature=0.4, max_tokens=2000)
    evaluations = result.get("evaluations", {})
    team_pattern = result.get("team_pattern", "")
    gate_suggestion = result.get("gate_suggestion", "")

    # Write evaluation results to each agent's Memory.md
    from agent_tools import memory_write, skill_create
    for aid, comment in evaluations.items():
        if aid in agents:
            memory_write(aid, f"## 管理评审\n{comment}", mode="append")
            print(f"  ✅ {aid}: 评审已写入 Memory.md")

    # Write team pattern to manager's Memory.md
    pattern = f"## 团队搭配经验\n目标: {goal[:60]} | 团队: {', '.join(agent_ids)} | 效果: {team_pattern}"
    if gate_suggestion:
        pattern += f"\nGate建议: {gate_suggestion}"
    memory_write("manager", pattern, mode="append")
    print(f"  ✅ manager: 团队搭配模式已记录")

    # Check if any agent demonstrated a useful technique worth saving as skill
    all_decisions = {r['role_id']: r for r in all_decs}
    for aid in agent_ids:
        if aid in evaluations:
            comment = evaluations[aid]
            # If evaluation mentions a positive technique, auto-create skill
            for keyword in ["有效策略", "亮点", "技巧", "方法", "最佳实践"]:
                if keyword in comment:
                    # Extract a skill name from the first sentence
                    import re
                    lines = comment.split("。")
                    skill_name = re.sub(r'[^\w\u4e00-\u9fff]', '', lines[0])[:20]
                    if skill_name:
                        skill_create(aid, f"辩论技巧-{skill_name}", f"# {skill_name}\n\n{comment}\n\n源自辩论: {goal[:60]}")
                        print(f"  📚 {aid}: skill '{skill_name}' 已保存")
                    break

    print("  ✅ 评审完成")


# ══════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    goal = " ".join(sys.argv[1:])
    run_name = goal[:60]

    print(f"\n{'='*60}")
    print(f"🤖 Auto-Debate v2")
    print(f"{'='*60}")
    print(f"任务: {goal}")

    # Load agents from individual meta.yaml files
    agents = load_agents()
    print(f"Agent 池: {len(agents)} 个智能体")
    for aid, info in sorted(agents.items()):
        has_refs = Path(info["_path"]) / "references"
        ref_count = len(list(has_refs.iterdir())) if has_refs.exists() and has_refs.is_dir() else 0
        print(f"  📁 {aid:20s} | {info.get('role',''):15s} | refs={ref_count}")

    # Phase 1: Manager selects agents + team skill
    agent_ids = manager_select_agents(goal, agents)

    # Read team flow topology from manager/skills/ (YAML frontmatter)
    import yaml as yaml_lib
    team_skills_dir = Path(__file__).resolve().parent / "agents" / "manager" / "skills"
    flow_topology = []
    # Pick first matching team skill based on selected agents
    for skill_file in sorted(team_skills_dir.glob("*.md")):
        text = skill_file.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm = yaml_lib.safe_load(parts[1])
                team_agents = set(fm.get("agents", []))
                if team_agents and team_agents.issubset(set(agent_ids)):
                    flow_topology = fm.get("flow", [])
                    print(f"  采用班底: {fm.get('name', skill_file.stem)} ({len(flow_topology)} 个状态)")
                    break
    if not flow_topology:
        print("  ⚠️ 未匹配到班底，使用默认空拓扑")

    # Phase 2: Manager generates flow YAML + briefs agents
    print("\n📄 生成 Flow YAML...")
    yaml_path = generate_yaml(goal, agent_ids, run_name, agents, flow_topology)
    print(f"   → {yaml_path}")

    # Manager briefs each agent via inbox
    print("\n📨 管理者发送任务简报...")
    sys.path.insert(0, PROJECT_ROOT)
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT
    from hermes_flow.tools import flow_send
    # We need a run_id to send messages. Use YAML's flow_id or init a placeholder.
    # Actually, inbox is only available after flow_init. Let's write briefing to
    # each agent's Memory.md instead via agent_tools.
    from agent_tools import memory_write
    for aid in agent_ids:
        info = agents.get(aid, {})
        role = info.get("role", aid)
        # Build concise briefing
        briefing = f"## 任务简报\n目标: {goal[:120]}\n"
        # Add deliverable expectations from flow topology
        for step in flow_topology:
            raw_actors = step.get("actors", "")
            expected = raw_actors.replace(" ", "").split("+")
            if aid in expected:
                arts = step.get("output_artifacts", [])
                if arts:
                    briefing += f"你需要产出: {', '.join(arts)}\n"
                briefing += f"阶段: {step['state']} — {step.get('description', '')}\n"
        briefing += f"\n请仔细阅读你的 SOUL.md 中的不可违反规则，完成任务后提交 APPROVE。"
        memory_write(aid, briefing, mode="append")
        print(f"  ✅ {aid}: 已收到任务简报")

    # Phase 3: Flow engine runs (NOT manager)
    run_flow(goal, agent_ids, yaml_path, run_name, agents)

    # Phase 4: Manager evaluates


if __name__ == "__main__":
    main()
