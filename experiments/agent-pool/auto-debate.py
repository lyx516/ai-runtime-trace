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
        "max_rounds": max_r,
    }


def make_state(sid, desc, actors, gate=None):
    s = {"description": desc, "actors": actors}
    if gate:
        s["gate"] = gate
    return s


def generate_yaml(goal: str, agent_ids: list[str], run_name: str, agents: dict) -> Path:
    """Generate flow YAML with debate + optional CLARIFY state."""
    selected = {aid: agents[aid] for aid in agent_ids}
    import yaml as yaml_lib

    flow_id = f"auto-{uuid.uuid4().hex[:8]}"
    roles = {aid: info.get("role", "") for aid, info in selected.items()}
    has_critic = "critic" in roles.values()
    has_mediator = "mediator" in roles.values()
    has_decider = "decider" in roles.values()
    has_clarifier = "human_clarifier" in agent_ids

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
    designers = [a for a, r in roles.items() if r == "designer"]
    critics = [a for a, r in roles.items() if r == "critic"]

    # DESIGN
    if designers:
        sid = "DESIGN"
        nxt = "CLARIFY" if has_clarifier and not has_critic else ("CRITIQUE" if has_critic else "DONE")
        states[sid] = make_state(sid, goal, designers, self_gate(designers, nxt))
        order.append(sid)

    # CRITIQUE / REVISION debate chain
    if has_critic and critics:
        nxt_ok = "CLARIFY" if has_clarifier else ("MEDIATE" if has_mediator else "FINAL_DECISION" if has_decider else "REVISION")
        states["CRITIQUE"] = make_state("CRITIQUE", "审查方案", critics,
            make_gate(critics, ["APPROVE"], ["REQUEST_CHANGES"], nxt_ok, "REVISION", 3))
        order.append("CRITIQUE")

        revision_fail = "CLARIFY" if has_clarifier else ("MEDIATE" if has_mediator else "FINAL_DECISION" if has_decider else "ABORT")
        states["REVISION"] = make_state("REVISION", "回应批评", designers,
            self_gate(designers, "CRITIQUE", revision_fail, 3))
        order.append("REVISION")

        if has_mediator:
            meds = [a for a, r in roles.items() if r == "mediator"]
            nxt = "CLARIFY" if has_clarifier else "FINAL_DECISION"
            states["MEDIATE"] = make_state("MEDIATE", "调解分歧", meds,
                self_gate(meds, nxt, "ABORT", 2))
            order.append("MEDIATE")

        if has_decider:
            decs = [a for a, r in roles.items() if r == "decider"]
            states["FINAL_DECISION"] = make_state("FINAL_DECISION", "最终决策", decs,
                self_gate(decs, "DONE", "ABORT", 2))
            order.append("FINAL_DECISION")

    # Speckit pipeline: SPEC → PLAN → TASKS → IMPLEMENT → REVIEW → DONE
    speckit_writers = [a for a, r in roles.items() if r == "spec-writer"]
    speckit_planners = [a for a, r in roles.items() if r == "plan-maker"]
    speckit_breakers = [a for a, r in roles.items() if r == "task-breaker"]
    speckit_implementers = [a for a, r in roles.items() if r in ("implementer",)]
    speckit_reviewers = [a for a, r in roles.items() if r in ("code-reviewer", "reviewer")]

    if speckit_writers:
        next_s = "PLAN" if speckit_planners else ("TASKS" if speckit_breakers else "IMPLEMENT")
        states["SPEC"] = make_state("SPEC", "编写规格文档 → 必须产出 spec.md", speckit_writers,
            product_gate(speckit_writers, "spec.md", next_s, "ABORT", 3))
        order.append("SPEC")

    if speckit_planners:
        next_s = "TASKS" if speckit_breakers else "IMPLEMENT"
        states["PLAN"] = make_state("PLAN", "制定技术方案 → 必须产出 plan.md", speckit_planners,
            product_gate(speckit_planners, "plan.md", next_s, "ABORT", 3))
        order.append("PLAN")

    if speckit_breakers:
        next_s = "IMPLEMENT" if speckit_implementers else "DONE"
        states["TASKS"] = make_state("TASKS", "分解任务 → 必须产出 tasks.md", speckit_breakers,
            product_gate(speckit_breakers, "tasks.md", next_s, "ABORT", 3))
        order.append("TASKS")

    # Non-debate flow: DESIGN → IMPLEMENT → REVIEW → DONE
    if not (has_critic and critics):
        implementers = [a for a, r in roles.items() if r in ("implementer", "tester")]
        reviewers = [a for a, r in roles.items() if r in ("reviewer", "tester")]
        if implementers:
            impl_next = "REVIEW" if reviewers else "DONE"
            states["IMPLEMENT"] = make_state("IMPLEMENT", "实现方案", implementers,
                self_gate(implementers, impl_next, "ABORT", 3))
            order.append("IMPLEMENT")
        if reviewers:
            states["REVIEW"] = make_state("REVIEW", "审查实现", reviewers,
                make_gate(reviewers, ["APPROVE"], ["REQUEST_CHANGES"], "DONE", "IMPLEMENT", 3))
            order.append("REVIEW")

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
    """Build system + user prompts for an agent."""
    role_instructions = {
        "designer": "你是激进的架构师，捍卫你的方案，引用数据和论文。可以在有说服力的反对下让步。",
        "critic": "你是尖锐的批评者。质疑一切方案。对方让步时也要踩一脚。",
        "mediator": "你是中立的技术总监。认可双方合理之处，提出折中方案。",
        "decider": "你是最终决策者。引用所有参与者观点。",
        "researcher": "你是严谨的研究员。引用具体数据和行业实践。",
        "implementer": "你是务实的工程师。关注可实现性和工程成本。",
        "reviewer": "你是严格审查者。检查边界情况和性能瓶颈。",
        "analyst": "你是数据分析师。关注可量化指标和实验验证。",
        "writer": "你是文档专家。关注表达清晰度和完整性。",
        "spec-writer": "你基于需求编写结构化规格文档（spec）。包含边界条件、错误处理、验收标准。",
        "plan-maker": "你基于 spec 制定技术方案。架构设计、接口定义、依赖分析、工时估算。",
        "task-breaker": "你将技术方案拆解为可执行的任务清单。每个任务有前置依赖、产出和验收标准。",
        "code-reviewer": "你对照 spec 审查代码实现。检查边界条件、安全漏洞、一致性和性能。",
    }
    instruction = role_instructions.get(role_id, "你是专业技术人员，基于数据和逻辑做判断。")
    pass_vals = gate.get("pass_values", ["APPROVE"])
    fail_vals = gate.get("fail_values", [])
    on_pass = gate.get("on_pass", "DONE")
    on_fail = gate.get("on_fail", "")

    hist_text = "\n".join([f"  [{i+1}] {d['from_role']}: {str(d['content'])[:200]}"
                          for i, d in enumerate(history)]) if history else "  (无)"
    inbox_text = "\n".join([f"  从 {d['from_role']}: {d['content']}"
                          for d in inbox]) if inbox else "  (空)"

    system = f"""{instruction}

你的身份: {role_id}
你的性格: {soul[:300]}

响应格式（严格 JSON）:
{{"value": "APPROVE|REQUEST_CHANGES|BLOCKED", "reason": "理由", "send_to": ["recipient"], "message": "消息（空则不发送）", "tool": "tool_id", "tool_args": {{"key": "value"}}}}

- tool: 可选，你要调用的工具 ID（从以下可用工具中选择）
- tool_args: 工具参数

|{tools_list}

注意：最多调用 1 个工具。先调工具（写记忆/查资料），再提交决策。

⚠️ **skill_create 使用指南**（仅在满足以下任一条件时使用）:
- 你发现了一个**可复现的模式/技巧**（不止解决当前问题，下次还会用到）
- 场景有**足够的复杂度**（不是"用requests发HTTP"这种单行常识）
- 你刚对**某个经常写的模块/项目**完成了有价值的总结（架构决策、踩坑记录、配置模板）

不满足以上条件时，用 memory_write 记录一次性信息即可，别滥用 skill_create。

⚠️ **产物要求**：如果 gate 指定了 required_file，你必须用 file_write 写入，否则 gate 会退回。"""

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

        if cur_round > max_r and on_fail:
            print(f"  ⏰ 超限({max_r}) → {on_fail}")
            eng_advance(run_id, state_id, on_fail, f"round_exhausted({cur_round})", cur_round, store)
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

            sys_p, usr_p = agent_prompt(role_id, soul, goal, state_id, cur_round,
                                         all_msgs, inbox_rows, gate, tools_list)

            print(f"  🤖 {role_id}...", end="", flush=True)
            t0 = time.time()
            try:
                resp = call_llm(sys_p, usr_p, temperature=0.8, max_tokens=600)
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

                # Product gate enforcement: verify required file exists
                gate_type = gate.get("type", "decision")
                required_file = gate.get("required_file", "")
                if gate_type == "product" and required_file:
                    file_path = Path(PROJECT_ROOT) / required_file
                    if file_path.exists() and file_path.stat().st_size > 0:
                        print(f"     📄 产物 {required_file} 存在 ({(file_path.stat().st_size)} bytes) ✅")
                    else:
                        print(f"     ⚠️  产物 {required_file} 缺失！降级为 REQUEST_CHANGES")
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

    # Use LLM as manager to evaluate
    manager_info = agents.get("manager", {})
    soul = manager_info.get("soul", "")

    # Build evaluation system prompt
    system = f"""你是流程管理专家，负责评审辩论中各个 agent 的表现。

{soul[:300]}

为每个 agent 写一段简短的评语（中文，50-100字），指出：
1. 该 agent 是否有效履行了其角色职责
2. 表现亮点或需要改进之处
3. 是否展示了有用的技巧（可保存为 skill）

响应 JSON:
{{"evaluations": {{"agent_id": "评语", ...}},
  "team_pattern": "这个团队搭配在这次任务中的效果总结（30-50字）",
  "gate_suggestion": "关于 gate 设置的改进建议"}}"""

    user = f"""## 任务目标
{goal}

## 参与 Agent
{', '.join(agent_ids)}

## 完整消息记录
{transcript[:2000]}

## 决策序列
{decisions_summary[:1000]}"""

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

    # Phase 2: Manager generates flow YAML
    print("\n📄 生成 Flow YAML...")
    yaml_path = generate_yaml(goal, agent_ids, run_name, agents)
    print(f"   → {yaml_path}")

    # Phase 3: Flow engine runs (NOT manager)
    run_flow(goal, agent_ids, yaml_path, run_name, agents)

    # Phase 4: Manager evaluates


if __name__ == "__main__":
    main()
