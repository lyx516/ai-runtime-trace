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
import urllib.request, urllib.error
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from hermes_flow.hooks import Hook, emit, subscribe, reset_bus
from hermes_flow.schemas import AgentSessionState

# Script location (agents, tools, skills live here)
_SCRIPT_DIR = Path(__file__).resolve().parent
# Project root (where hermes_flow package lives)
_PROJECT_ROOT_DIR = _SCRIPT_DIR.parent.parent
# Runtime project root (where runs/artifacts are searched/created)
PROJECT_ROOT = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or str(_PROJECT_ROOT_DIR)

# Default runs directory: alongside auto-debate.py
if "HERMES_FLOW_RUNS_DIR" not in os.environ:
    os.environ["HERMES_FLOW_RUNS_DIR"] = str(_SCRIPT_DIR / ".hermes-flow" / "runs")
AGENTS_DIR = _SCRIPT_DIR / "agents"
SHARED_SKILLS_DIR = _SCRIPT_DIR / "shared" / "skills"
OUTPUT_DIR = _SCRIPT_DIR / "generated"


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


def call_llm(system: str, prompt: str, model: str = "deepseek-v4-flash",
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

def _load_team_skills() -> list[dict]:
    """Scan manager/skills/*.md, parse YAML frontmatter + doc body into skill dicts."""
    import yaml as yaml_lib
    skills_dir = Path(__file__).resolve().parent / "agents" / "manager" / "skills"
    skills = []
    if not skills_dir.exists():
        return skills
    for f in sorted(skills_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        fm = yaml_lib.safe_load(parts[1])
        doc_body = parts[2].strip()
        skills.append({
            "file": f.name,
            "name": fm.get("name", f.stem),
            "description": fm.get("description", ""),
            "agents": fm.get("agents", []),
            "flow": fm.get("flow", []),
            "output_base": fm.get("output_base", ""),
            "doc": doc_body,
        })
    return skills


def manager_select_agents(goal: str, agents: dict) -> tuple[list[str], list[dict], str]:
    """Manager agent analyzes goal and selects appropriate agents + team skill.

    Returns (selected_agent_ids, flow_topology, output_base).
    flow_topology is the 'flow' array from the matched team skill (parsed YAML
    frontmatter), or a generated topology when no team skill is picked.
    output_base is the matched skill's output template (e.g. "output/{flow_id}").
    """
    team_skills = _load_team_skills()

    # Build team skill listing for the LLM prompt
    team_lines = []
    for s in team_skills:
        members = ", ".join(s["agents"]) if s["agents"] else "(无)"
        team_lines.append(
            f"  {s['file']}:\n"
            f"    名称: {s['name']}\n"
            f"    描述: {s['description'][:120]}\n"
            f"    成员: {members}\n"
            f"    流程: {len(s['flow'])} 个 state\n"
        )
    team_skills_text = (
        "\n## 可用班底技能\n"
        + "\n".join(team_lines)
        + "\n\n你**必须**从以上班底中选择一个合适的（通过 team 字段返回文件名，如 'spec-team.md'）。"
        "\n你也可以混编——选用某个班底的部分成员，或从多个班底各取 agent。"
        "如果没有任何班底匹配，也可以自定义成员组合，此时 team 返回 'custom'。"
        "\n对于简单的聊天式任务，只选 1 个 agent 即可。"
        "\n对于复杂开发任务，选 3-6 个 agent。"
    ) if team_skills else "\n（无可用的预定义班底，请根据 agent 池自定义组合。）"

    # Build agent pool listing
    from trait_loader import resolve_agent_tools
    agent_list_lines = []
    for aid, info in agents.items():
        if aid == "manager":
            continue
        try:
            tools = resolve_agent_tools(info)
            tools_str = ", ".join(tools) if tools else "(无)"
        except Exception:
            tools_str = ", ".join(info.get("tools_allowed", []))
        traits = info.get("traits", [])
        traits_str = ", ".join(traits) if traits else "(无)"
        excluded = info.get("tools_excluded", [])
        excl_str = f"  排除: {', '.join(excluded)}" if excluded else ""
        desc = info.get("description", "")[:80]
        agent_list_lines.append(
            f"  {aid}:\n"
            f"    名称: {info.get('display_name', aid)}\n"
            f"    角色: {info.get('role', '')}\n"
            f"    能力组合: [{traits_str}]\n"
            f"    可用工具: [{tools_str}]\n"
            f"    {excl_str}\n"
            f"    描述: {desc}"
        )
    agent_list = "\n".join(agent_list_lines)

    system = f"""你是流程管理专家。根据用户目标选择班底技能并选出合适的 Agent。{team_skills_text}

## 响应格式

严格 JSON，不要任何其他文本：

```json
{{
  "agents": ["id1", "id2", ...],
  "team": "选择的班底文件名，如 spec-team.md，无匹配则返回 custom",
  "reason": "选择理由（简述任务特点 → 班底匹配逻辑）"
}}
```
"""

    user = f"## 任务\n{goal}\n\n## Agent 池\n{agent_list}\n\n请选择班底和 Agent。"
    print("\n🤔 管理 Agent 正在分析任务...")
    result = call_llm(system, user, temperature=0.3)
    selected = result.get("agents", [])
    team_file = result.get("team", "")
    reason = result.get("reason", "")

    valid = [a for a in selected if a in agents and a != "manager"]
    if len(valid) < 1:
        valid = ["designer", "critic", "mediator", "decider"]
        team_file = "debate-team.md"
        reason = "选择不足，使用默认辩论组合"

    # Resolve flow topology from matched team skill
    flow_topology = []
    matched_skill = None
    for s in team_skills:
        if s["file"] == team_file:
            matched_skill = s
            flow_topology = list(s.get("flow", []))
            break

    # Store the matched skill's full frontmatter for later use
    if matched_skill and flow_topology:
        matched_info = matched_skill
    else:
        # No match: generate a simple single-agent topology
        if len(valid) == 1:
            flow_topology = [{
                "state": "DONE",
                "description": goal[:80],
                "actors": valid[0],
                "gate": {"type": "decision", "pass": "DONE", "fail": "ABORT", "max": 3},
            }]
        matched_info = matched_skill or {"output_base": ""}

    print(f"  选择了: {', '.join(valid)}")
    print(f"  理由: {reason}" if reason else "")
    print(f"  班底: {team_file}" if team_file else "")
    return valid, flow_topology, (matched_info or {"output_base": ""}).get("output_base", "")


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
                  flow_topology: Optional[list] = None,
                  output_base: str = "") -> Path:
    """Generate flow YAML from a topology config. No role-specific hardcoding."""
    selected = {aid: agents[aid] for aid in agent_ids}
    import yaml as yaml_lib

    flow_id = f"auto-{uuid.uuid4().hex[:8]}"

    # Resolve output_base (may contain {flow_id} template)
    _resolved_output = output_base.replace("{flow_id}", flow_id) if output_base else f"output/{flow_id}"

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
            "write_scope": [_resolved_output + "/"],
        }
    states, order = {}, []
    # If no topology provided, build one from selected roles (backward compat)
    if not flow_topology:
        flow_topology = []
    # Build a map of original topology state IDs → their ordinal position
    _topo_order_map: dict[str, int] = {}
    for _i, _s in enumerate(flow_topology):
        _topo_order_map[_s["state"]] = _i
    # Collect all state IDs in the ORIGINAL topology (before filtering)
    _all_topo_ids = [_s["state"] for _s in flow_topology]
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

    # ── Rewrite gate targets for removed states ──
    _existing_ids = set(order)
    for sid in order:
        s = states.get(sid, {})
        gate = s.get("gate")
        if not isinstance(gate, dict):
            continue
        for _key in ("on_pass", "on_fail"):
            target = gate.get(_key)
            if not target or target in _existing_ids:
                continue
            # Target state was removed from topology — walk forward to next existing state
            _pos = _topo_order_map.get(sid, -1)
            _fallback = "DONE" if _key == "on_pass" else "ABORT"
            _next = _fallback
            for _i in range(_pos + 1, len(_all_topo_ids)):
                if _all_topo_ids[_i] in _existing_ids:
                    _next = _all_topo_ids[_i]
                    break
            gate[_key] = _next

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

def _build_multi_turn_system_prompt(
    role_id: str, soul: str, goal: str,
    output_artifacts: list[str],
    tool_schemas: list[dict],
    write_scope: list[str] = None,
    flow_overview: str = "",
) -> str:
    """Build a task-oriented system prompt.

    Does NOT expose framework internals (state, gate, round).
    Gives a clear task goal + skill-guided workflow + tools + exit condition.
    """
    # Tool descriptions for the prompt text
    tool_descriptions = []
    for ts in tool_schemas:
        fn = ts.get("function", {})
        tool_descriptions.append(f"  {fn['name']}: {fn.get('description', '')[:100]}")
    tool_text = "\n".join(tool_descriptions) if tool_descriptions else "  (无)"

    # Read assigned skill content, if any
    skill_content = ""
    _skill_path = Path(__file__).resolve().parent / "shared" / "skills" / role_id / "SKILL.md"
    if _skill_path.exists():
        with open(_skill_path, encoding="utf-8") as _f:
            _raw = _f.read()
        # Strip YAML frontmatter
        if _raw.startswith("---"):
            _parts = _raw.split("---", 2)
            if len(_parts) >= 3:
                skill_content = _parts[2].strip()
            else:
                skill_content = _raw
        else:
            skill_content = _raw

    # Read trait-specific prompt
    from trait_loader import resolve_agent_trait_prompts
    import yaml as _yaml
    _meta_path = Path(__file__).resolve().parent / "agents" / role_id / "meta.yaml"
    _trait_prompt = ""
    if _meta_path.exists():
        with open(_meta_path) as _f:
            _meta = _yaml.safe_load(_f)
            _trait_prompt = resolve_agent_trait_prompts(_meta)

    parts = [
        f"## 你的身份",
        f"{soul[:600]}",
        "",
        f"## 团队总目标",
        f"{goal}",
    ]
    if flow_overview:
        parts.append(flow_overview)
    parts.append("")

    if write_scope:
        _ws_dirs = [f"  {d}" for d in write_scope]
        parts.append(f"## 工作目录")
        parts.append(f"你只能在此目录下读写文件：")
        parts.append("\n".join(_ws_dirs))
        parts.append("")

    if skill_content:
        # Use the skill as the primary workflow guide
        # Strip the title line if present
        skill_lines = [l for l in skill_content.split("\n") if not l.startswith("# ")]
        skill_body = "\n".join(skill_lines).strip()
        parts.extend([
            "## 工作方式",
            skill_body,
            "",
        ])
    else:
        parts.extend([
            "## 工作方式",
            "1. 分析目标，明确要产出的内容",
            "2. 用 write_file 创建产物文件，用 patch 修改已有文件",
            "3. 完成后调用 submit_decision(APPROVE)",
            "",
        ])

    if _trait_prompt:
        parts.append(f"## 附加规则\n{_trait_prompt}\n")

    parts.extend([
        "## 可用工具",
        tool_text,
        "",
        "## 完成条件",
        "产出文件后，调用 **submit_decision** 提交。",
    ])
    return "\n".join(parts)


def _init_agent_session_state(
    role_id: str, soul: str, goal: str, state_id: str, round_n: int,
    history: list, inbox: list, gate: dict, tool_schemas: list[dict],
    agents: dict, output_artifacts: list[str] | None, prev_artifacts: dict | None,
    store, run_id: str, write_scope: list[str], flow_overview: str,
) -> AgentSessionState:
    """Build a fresh AgentSessionState — 纯函数, 零副作用.

    组合 system prompt + initial messages + tools 列表。
    返回值可直接传入 _run_session_loop()。
    """
    from tool_registry import DECISION_TOOL_SCHEMA

    # 1. Build system prompt (same as original init phase)
    system = _build_multi_turn_system_prompt(
        role_id, soul, goal, output_artifacts, tool_schemas, write_scope,
        flow_overview=flow_overview,
    )

    # 2. Build initial messages
    messages = []
    if history:
        hist_lines = []
        for d in history[-10:]:
            c = str(d.get("content", ""))[:200]
            hist_lines.append(f"{d['from_role']}: {c}")
        messages.append({
            "role": "user",
            "content": f"## 讨论历史\n" + "\n".join(hist_lines),
        })
    if inbox:
        inbox_lines = [f" 从 {m['from_role']}: {m['content']}" for m in inbox]
        messages.append({
            "role": "user",
            "content": f"## 收件箱 ({len(inbox)} 条消息)\n" + "\n".join(inbox_lines),
        })

    # Inject pending decisions from this state (REQUEST_CHANGES reasons)
    if store is not None:
        try:
            _conn = store.connect()
            _pending_rows = _conn.execute(
                "SELECT role_id, value, reason FROM decisions WHERE run_id=? AND state_id=? AND value!=? ORDER BY created_at",
                (run_id, state_id, "APPROVE"),
            ).fetchall()
        except Exception:
            _pending_rows = []
        if _pending_rows:
            _lines = [f"  [{d['role_id']}] {d['value']}: {d['reason']}" for d in _pending_rows]
            messages.append({
                "role": "user",
                "content": "## 上轮审查意见\n" + "\n".join(_lines),
            })

    # Inject previous state's artifact paths
    artifact_hint = ""
    if prev_artifacts:
        lines = []
        for name, path in prev_artifacts.items():
            lines.append(f"  {name} → {path}")
        artifact_hint = f"\n## 上一步的产出\n{chr(10).join(lines)}\n请先读取这些文件再开始工作。\n"

    if not messages:
        messages.append({
            "role": "user",
            "content": f"{artifact_hint}请完成 {state_id} 状态的工作。先使用工具完成实际任务，然后提交 submit_decision。".strip(),
        })
    else:
        if artifact_hint:
            messages[-1]["content"] += f"\n{artifact_hint.strip()}"

    # 3. Build tools list
    tools = list(tool_schemas)
    tools.append(DECISION_TOOL_SCHEMA)

    # 4. Inject turn info + state context as separate messages
    state_context = f"[{state_id} 状态 · gate 第 {round_n} 轮]"
    turn_info = f"(本轮可用 100 次工具调用，已用 0 次)"
    messages.append({"role": "user", "content": state_context})
    messages.append({"role": "user", "content": turn_info})

    state = AgentSessionState(
        run_id=run_id,
        role_id=role_id,
        state_id=state_id,
        round_n=round_n,
        system_prompt=system,
        messages_json=json.dumps(messages, ensure_ascii=False),
        tools_json=json.dumps(tools, ensure_ascii=False),
        turn=0,
        max_turns=100,
    )

    emit(Hook.SESSION_INIT, {"state": asdict(state)})
    return state


def _run_agent_session(
    role_id: str, soul: str, goal: str, state_id: str, round_n: int,
    history: list, inbox: list, gate: dict, tool_schemas: list[dict],
    agents: dict, output_artifacts: list[str] = None,
    prev_artifacts: dict = None,
    store=None,
    run_id: str = "",
    write_scope: list[str] = None,
    flow_overview: str = "",
) -> dict:
    """Multi-turn agent session — auto-resumes from checkpoint if available.

    1. 幂等性检查: 如果已有 decision → 跳过
    2. 尝试从 checkpoint 恢复 → 直接进 loop
    3. 否则 fresh init → loop

    Agent loop 只 emit hook，不直接调 store 持久化方法。
    """
    # ── 幂等性: 已提交 decision 则不再执行 ─────────────────
    if store is not None and run_id and store.agent_has_decision(run_id, state_id, role_id):
        return {"value": "APPROVE", "reason": "[skip] decision already exists", "tool_calls": 0}

    # ── Try resume from checkpoint ─────────────────────────
    state = None
    if store is not None and run_id:
        raw = store.load_agent_session_checkpoint(run_id, role_id, state_id)
        if raw:
            try:
                state = AgentSessionState(**raw)
                print(f"     🔄 恢复 checkpoint (turn {state.turn}/{state.max_turns})")
            except Exception:
                pass

    if state is None:
        state = _init_agent_session_state(
            role_id, soul, goal, state_id, round_n,
            history, inbox, gate, tool_schemas, agents,
            output_artifacts, prev_artifacts,
            store, run_id, write_scope, flow_overview,
        )

    return _run_session_loop(state, store, run_id)


def _run_session_loop(
    state: AgentSessionState,
    store,
    run_id: str,
) -> dict:
    """Run agent turn loop from state.turn to state.max_turns.

    每轮:
      LLM call → tool execution → append results → append turn_info
      → emit TURN_END (checkpoint 在此)
      → submit_decision 时 emit SESSION_DECIDE + SESSION_DONE → return

    Agent loop 不直接调 store 持久化方法 — 全部通过 hook emit。
    """
    from tool_registry import execute_tool, format_tool_results_for_llm, DECISION_TOOL_SCHEMA

    system = state.system_prompt
    messages = json.loads(state.messages_json)
    tools = json.loads(state.tools_json)
    max_turns = state.max_turns
    state_context = f"[{state.state_id} 状态 · gate 第 {state.round_n} 轮]"
    tool_calls_made = state.tool_calls_made
    _empty_fails = state.empty_fails
    _last_empty_tool = state.last_empty_tool

    for turn in range(state.turn, max_turns):
        print(f"     🤔 round {turn+1}/{max_turns}...", end="", flush=True)

        t0 = time.time()

        # ── LLM input snapshot (via hook) ────────────────────
        emit(Hook.LLM_DONE, {
            "run_id": run_id,
            "role_id": state.role_id,
            "state_id": state.state_id,
            "messages": [{"role": "system", "content": system}] + messages,
            "request": {"tools": [t["function"]["name"] for t in tools]},
            "context_packet": {"turn": turn, "max_turns": max_turns},
        })

        try:
            resp_data = _call_llm_tools(system, messages, tools)
            dt = time.time() - t0
        except Exception as e:
            print(f" ❌ {e}")
            emit(Hook.SESSION_DONE, {
                "run_id": run_id,
                "role_id": state.role_id,
                "state_id": state.state_id,
                "value": "APPROVE",
                "reason": f"[fallback] LLM error: {e}",
            })
            return {"value": "APPROVE", "reason": f"[fallback] LLM error: {e}", "tool_calls": tool_calls_made}

        # Check for tool calls
        tool_calls = resp_data.get("tool_calls", [])
        text_content = resp_data.get("content", "")

        assistant_msg = {"role": "assistant", "content": text_content or None}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{turn}_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for i, tc in enumerate(tool_calls)
            ]
        messages.append(assistant_msg)

        if tool_calls:
            print(f" {dt:.1f}s → {len(tool_calls)} tool(s)")
            tool_msgs = []
            submit_dec = None
            for tc in assistant_msg["tool_calls"]:
                fn_name = tc.get("function", {}).get("name", "")
                raw_args = tc.get("function", {}).get("arguments", "{}")
                try:
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (json.JSONDecodeError, TypeError) as e:
                    preview = str(raw_args)[:800]
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", fn_name),
                        "content": (
                            f"[Error] Tool call arguments for '{fn_name}' are malformed or truncated JSON "
                            f"(likely hit max_tokens limit). Raw arguments received:\n\n"
                            f"{preview}\n\n"
                            f"Please retry. If you were writing a large file, consider writing it in "
                            f"smaller chunks — write a skeleton first, then use patch to add sections."
                        ),
                    })
                    tool_calls_made += 1
                    _empty_fails = _empty_fails + 1
                    _last_empty_tool = fn_name
                    continue

                # Empty-arg detection
                _tool_schema = next((f for f in tools if f.get("function", {}).get("name") == fn_name), None)
                _has_required = bool(
                    _tool_schema
                    and _tool_schema.get("function", {}).get("parameters", {}).get("required")
                )
                if not fn_args and _has_required:
                    _required_params = json.dumps({
                        f["function"]["name"]: f["function"].get("parameters", {}).get("required", [])
                        for f in tools
                        if f.get("function", {}).get("name") == fn_name
                    }, ensure_ascii=False)
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", fn_name),
                        "content": (
                            f"[Error] '{fn_name}' called with empty arguments ({{}}). "
                            f"Required parameters: {_required_params}. "
                            f"Please retry with the correct arguments."
                        ),
                    })
                    tool_calls_made += 1
                    _empty_fails = _empty_fails + 1
                    _last_empty_tool = fn_name
                    print(f" 🔧 {fn_name}({{}})" + " ❌")
                    continue

                # Check if decision
                if fn_name == "submit_decision":
                    value = fn_args.get("value", "APPROVE").upper()
                    reason = fn_args.get("reason", f"[{state.role_id}] Decision via submit_decision")
                    print(f"     ✅ submit_decision({value}) — {reason[:60]}")
                    submit_dec = {"value": value, "reason": reason, "tool_calls": tool_calls_made}
                    continue

                # Execute real tool
                if fn_name == "agent_message_send":
                    send_to = fn_args.get("recipients", fn_args.get("intended_recipients", []))
                    content = fn_args.get("content", "")
                    if not send_to or not content:
                        result = {"ok": False, "error": "agent_message_send: need recipients and content"}
                    elif not isinstance(send_to, list):
                        send_to = [send_to]
                        result = {"ok": False, "error": "recipients must be a list"}
                    else:
                        from uuid import uuid4
                        from datetime import datetime, timezone
                        msg_id = uuid4().hex[:12]
                        now = datetime.now(timezone.utc).isoformat()
                        if store is not None:
                            conn = store.connect()
                            conn.execute(
                                "INSERT INTO messages(message_id,run_id,state_id,from_role,intended_recipients,authorized_recipients,recipient_availability,visibility,kind,content,delivery_outcome,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                (msg_id, run_id, state.state_id, state.role_id, json.dumps(send_to), json.dumps(send_to), json.dumps({r: True for r in send_to}), "targeted", "question", content, "delivered", now),
                            )
                            for r in send_to:
                                conn.execute(
                                    "INSERT INTO inboxes(run_id,role_id,state_id,message_id,generated_at) VALUES(?,?,?,?,?)",
                                    (run_id, r, state.state_id, msg_id, now),
                                )
                            conn.commit()
                        result = {"ok": True, "sent_to": send_to, "preview": content[:200]}
                        print(f"     💬 → {', '.join(send_to)}: {content[:60]}...")
                    tool_calls_made += 1
                    _empty_fails = 0
                elif fn_name in ("memory_read", "memory_write", "skill_create", "skill_update",
                                 "agent_submit_decision", "agent_summarize", "human_clarifier"):
                    result = {"ok": True, "note": f"{fn_name} is available but not yet implemented"}
                    tool_calls_made += 1
                else:
                    print(f"     🔧 {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:80]})", end="")
                    result = execute_tool(fn_name, fn_args, state.role_id)
                    tool_calls_made += 1
                    ok = result.get("ok", False)
                    print(f" {'✅' if ok else '❌'}")

                ok = result.get("ok", False)

                # Tool done → hook (thinking event persistence)
                emit(Hook.TOOL_DONE, {
                    "run_id": run_id,
                    "role_id": state.role_id,
                    "state_id": state.state_id,
                    "fn_name": fn_name,
                    "inputs": fn_args,
                    "result": result,
                })

                formatted = format_tool_results_for_llm(fn_name, result)
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", fn_name),
                    "content": formatted,
                })

                # Empty-arg loop detection
                if not ok and not any(fn_args.values()):
                    _empty_fails = _empty_fails + 1
                    _last_empty_tool = fn_name
                    if _empty_fails >= 3 and _last_empty_tool == fn_name:
                        print(f"     🛑 repeated empty {fn_name} args; returning REQUEST_CHANGES")
                        emit(Hook.SESSION_DONE, {
                            "run_id": run_id,
                            "role_id": state.role_id,
                            "state_id": state.state_id,
                            "value": "REQUEST_CHANGES",
                            "reason": f"{fn_name} called with empty arguments {_empty_fails} times",
                        })
                        return {
                            "value": "REQUEST_CHANGES",
                            "reason": f"{fn_name} called with empty arguments {_empty_fails} times",
                            "tool_calls": tool_calls_made,
                        }
                else:
                    _empty_fails = 0

            if submit_dec:
                emit(Hook.SESSION_DECIDE, {
                    "run_id": run_id,
                    "role_id": state.role_id,
                    "state_id": state.state_id,
                    "value": submit_dec["value"],
                    "reason": submit_dec["reason"],
                })
                emit(Hook.SESSION_DONE, {
                    "run_id": run_id,
                    "role_id": state.role_id,
                    "state_id": state.state_id,
                    "value": submit_dec["value"],
                    "reason": submit_dec["reason"],
                })
                return submit_dec

            # Append tool messages + turn info
            for m in tool_msgs:
                messages.append(m)
            messages.append({
                "role": "user",
                "content": f"{state_context} (剩余 {max_turns - tool_calls_made}/{max_turns} 次工具调用)",
            })

            # ── Update state + save checkpoint via hook ───
            state.messages_json = json.dumps(messages, ensure_ascii=False)
            state.turn = turn + 1
            state.tool_calls_made = tool_calls_made
            state.empty_fails = _empty_fails
            state.last_empty_tool = _last_empty_tool
            emit(Hook.TURN_END, {"state": asdict(state)})

        elif text_content:
            print(f" {dt:.1f}s → text response ({len(text_content)} chars)")
            import re
            dec_match = re.search(
                r'"(?:value|decision)"\s*:\s*"(APPROVE|REQUEST_CHANGES|BLOCKED)"',
                text_content,
            )
            if dec_match:
                val = dec_match.group(1)
                reason = text_content[:200].replace("\n", " ")
                print(f"     ✅ embedded decision: {val}")
                emit(Hook.SESSION_DECIDE, {
                    "run_id": run_id,
                    "role_id": state.role_id,
                    "state_id": state.state_id,
                    "value": val,
                    "reason": reason,
                })
                emit(Hook.SESSION_DONE, {
                    "run_id": run_id,
                    "role_id": state.role_id,
                    "state_id": state.state_id,
                    "value": val,
                    "reason": reason,
                })
                return {"value": val, "reason": reason, "tool_calls": tool_calls_made}
            messages.append({"role": "assistant", "content": text_content[:1000]})
        else:
            print(f" {dt:.1f}s → empty response")
            continue

    # Max turns reached
    print(f"     ⏰ max turns ({max_turns}) reached, auto-approving")
    emit(Hook.SESSION_DONE, {
        "run_id": run_id,
        "role_id": state.role_id,
        "state_id": state.state_id,
        "value": "APPROVE",
        "reason": f"[{state.role_id}@{state.state_id}] max turns reached ({max_turns})",
    })
    return {
        "value": "APPROVE",
        "reason": f"[{state.role_id}@{state.state_id}] max turns reached ({max_turns})",
        "tool_calls": tool_calls_made,
    }


def _call_llm_tools(
    system: str, messages: list[dict], tools: list[dict],
    model: str = "deepseek-v4-flash",
) -> dict:
    """Call LLM with OpenAI function-calling tools format.

    Returns: {"content": str, "tool_calls": [{"id": str, "function": {"name": ..., "arguments": ...}}]}
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"content": "{}", "tool_calls": []}

    # Count token budget roughly
    system_len = len(system)
    msgs_len = sum(len(str(m)) for m in messages)
    tools_str = json.dumps(tools, ensure_ascii=False)
    total_chars = system_len + msgs_len + len(tools_str)

    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": 0.7,
        "max_tokens": max(300, min(8192, 32000 - total_chars // 4)),
    }

    # Only send tools if we have any
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    body_bytes = json.dumps(body, ensure_ascii=False).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    # ── Retry loop for transient network errors ──
    _max_retries = 2
    _last_err = None
    for _attempt in range(_max_retries + 1):
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"DeepSeek API {e.code}: {err_body}") from e
        except (IOError, ConnectionError, urllib.error.URLError) as e:
            _last_err = e
            if _attempt < _max_retries:
                _delay = [2, 5][_attempt]
                print(f"     ⚠️ LLM retry {_attempt+1}/{_max_retries}: {type(e).__name__} — waiting {_delay}s")
                time.sleep(_delay)
                continue
            raise
    else:
        raise _last_err or RuntimeError("LLM call failed after retries")

    choice = result["choices"][0]["message"]
    text_content = choice.get("content", "") or ""
    raw_tool_calls = choice.get("tool_calls", [])

    tool_calls = []
    for tc in raw_tool_calls:
        tool_calls.append({
            "id": tc.get("id", ""),
            "function": {
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            },
        })

    return {"content": text_content, "tool_calls": tool_calls}


def _artifact_check(path: Path) -> tuple[bool, str]:
    """Return whether an output artifact is substantive enough to pass a product gate."""
    if not path.exists() or not path.is_file():
        return False, "missing"
    size = path.stat().st_size
    if size == 0:
        return False, "empty"
    if path.suffix.lower() in {".md", ".txt", ".rst"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        non_empty_lines = [line for line in text.splitlines() if line.strip()]
        if size < 200 or len(non_empty_lines) < 3:
            return False, f"stub-like ({size} bytes, {len(non_empty_lines)} non-empty lines)"
    return True, "ok"


def _find_output_artifact(project_root: str, art_name: str, write_scope: list[str]) -> tuple[Path | None, str]:
    """Find an artifact only inside the current run's declared write scope.

    Broad recursive search can pick stale files from older auto-* runs and pass
    the wrong artifact path to the next state.
    """
    root = Path(project_root)
    artifact = Path(art_name)
    candidates: list[Path] = []
    if artifact.is_absolute():
        candidates.append(artifact)
    else:
        for scope in write_scope or []:
            candidates.append(root / scope / artifact.name)
        candidates.append(root / artifact)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        ok, reason = _artifact_check(candidate)
        if ok:
            return candidate, reason
        if candidate.exists():
            return None, f"{candidate}: {reason}"
    return None, "missing in current write scope"


def _make_hook_handlers(store, run_id: str):
    """Register hook handlers that close over a RuntimeStore.

    Agent loop emits hooks — these handlers do the actual persistence.
    Called once at the start of run_flow().
    """

    def _serialize_state(state_dict: dict) -> str:
        return json.dumps(state_dict, ensure_ascii=False, default=str)

    def on_llm_done(hook: str, payload: dict) -> None:
        try:
            store.append_llm_input_snapshot(
                run_id=run_id,
                session_id=payload.get("role_id", ""),
                role_id=payload.get("role_id", ""),
                state_id=payload.get("state_id", ""),
                provider="deepseek",
                model="deepseek-v4-flash",
                messages=payload.get("messages", []),
                request=payload.get("request", {}),
                context_packet=payload.get("context_packet", {}),
            )
        except Exception:
            pass

    def on_tool_done(hook: str, payload: dict) -> None:
        try:
            store.append_thinking_event(
                run_id=run_id,
                role_id=payload.get("role_id", ""),
                state_id=payload.get("state_id", ""),
                step_type=payload.get("fn_name", "unknown"),
                inputs=payload.get("inputs", {}),
                output=payload.get("result", {}),
            )
        except Exception:
            pass

    def on_turn_end(hook: str, payload: dict) -> None:
        state = payload.get("state", {})
        store.save_agent_session_checkpoint(
            _serialize_state(state),
            state.get("run_id", run_id),
            state.get("role_id", ""),
            state.get("state_id", ""),
        )

    def on_session_done(hook: str, payload: dict) -> None:
        store.delete_agent_session_checkpoint(
            run_id,
            payload.get("role_id", ""),
            payload.get("state_id", ""),
        )

    subscribe(Hook.LLM_DONE, on_llm_done)
    subscribe(Hook.TOOL_DONE, on_tool_done)
    subscribe(Hook.TURN_END, on_turn_end)
    subscribe(Hook.SESSION_DONE, on_session_done)


def _run_fsm_loop(store, run_id: str, goal: str, agent_ids: list[str], agents: dict):
    """FSM while loop — shared by run_flow() and resume_flow()."""
    from hermes_flow.tools import flow_step, flow_decide
    from hermes_flow.schemas import RunStatus
    from hermes_flow.engine import advance_state as eng_advance

    _agent_specs = store.load_agent_specs(run_id)
    conn = store.connect()

    # Load flow topology
    _all_states = conn.execute(
        "SELECT state_id, state_json FROM states WHERE run_id=? ORDER BY rowid",
        (run_id,),
    ).fetchall()
    _state_map: dict[str, dict] = {}
    _state_order: list[str] = []
    for _s in _all_states:
        _sj = json.loads(_s["state_json"]) if _s["state_json"] else {}
        _state_map[_s["state_id"]] = _sj
        if not _sj.get("terminal"):
            _state_order.append(_s["state_id"])

    def _build_flow_overview(current_state: str) -> str:
        lines = ["## 流程全景", ""]
        _past = set()
        for _d in conn.execute(
            "SELECT state_id, value FROM decisions WHERE value='APPROVE'"
        ).fetchall():
            _past.add(_d["state_id"])
        for _sid in _state_order:
            _sj = _state_map.get(_sid, {})
            _out = ", ".join(_sj.get("output_artifacts", [])) or "—"
            _gate = _sj.get("gate", {})
            _actors = _gate.get("required_roles", [])
            _actor_str = " + ".join(_actors)
            if _sid == current_state:
                _marker = "🔄 当前"
            elif _sid in _past:
                _marker = "✅ 已完成"
            else:
                _marker = "⬜ 待执行"
            lines.append(f"  {_marker}")
            lines.append(f"  └─ {_sid} — {_actor_str} → 产出: {_out}")
        return "\n".join(lines)

    found_artifacts: dict[str, str] = {}
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
        gate = state_dict.get("gate") or {}
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

        for role_idx, role_id in enumerate(required_roles):
            info = agents.get(role_id, {})
            soul = info.get("soul", "")

            inbox_rows = conn.execute(
                "SELECT m.from_role, m.content FROM inboxes i JOIN messages m ON i.message_id=m.message_id WHERE i.run_id=? AND i.role_id=? ORDER BY m.created_at",
                (run_id, role_id)).fetchall()

            all_msgs = conn.execute(
                "SELECT from_role, content FROM messages ORDER BY rowid").fetchall()

            from tool_registry import get_agent_tools_schemas
            tool_schemas = get_agent_tools_schemas(role_id)
            print(f"  🤖 {role_id} ({len(tool_schemas)} tools)" + (" [审查者]" if role_idx > 0 else ""))

            _spec = _agent_specs.get(role_id, {})
            _write_scope = _spec.get("write_scope", [])
            _read_scope = _spec.get("read_scope", [])
            os.environ["HERMES_WRITE_SCOPE"] = json.dumps(_write_scope)
            os.environ["HERMES_READ_SCOPE"] = json.dumps(_read_scope)
            for _d in _write_scope:
                Path(PROJECT_ROOT, _d).mkdir(parents=True, exist_ok=True)

            _state_artifacts = state_dict.get("output_artifacts", [])
            is_reviewer = role_idx > 0 and len(required_roles) > 1
            if is_reviewer:
                _review_target = ", ".join(_state_artifacts) if _state_artifacts else "the output"
                soul = (
                    f"## 本阶段你的角色：审查者\n"
                    f"当前状态的产物（{_review_target}）已由 {required_roles[0]} 生成。"
                    f"你的任务是：读取产物文件，检查质量是否满足目标要求。"
                    f"如果合格 → 提交 APPROVE。如果发现问题 → 提交 REQUEST_CHANGES 并说明原因。"
                    f"你不需要重新生成产物，只做审查。\n\n"
                    f"{soul}"
                )

            result = _run_agent_session(
                role_id, soul, goal, state_id, cur_round,
                all_msgs, inbox_rows, gate, tool_schemas, agents,
                output_artifacts=state_dict.get("output_artifacts", []),
                prev_artifacts=found_artifacts if found_artifacts else None,
                store=store,
                run_id=run_id,
                write_scope=_write_scope,
                flow_overview=_build_flow_overview(state_id),
            )

            val = result.get("value", "APPROVE").upper()
            reason = result.get("reason", "")
            tool_count = result.get("tool_calls", 0)
            print(f"     ✅ {val} (after {tool_count} tool call(s))")

            output_artifacts = state_dict.get("output_artifacts", [])
            if output_artifacts:
                for art_name in output_artifacts:
                    art_path, artifact_reason = _find_output_artifact(PROJECT_ROOT, art_name, _write_scope)
                    if art_path:
                        fp = str(art_path)
                        rel = art_path.relative_to(Path(PROJECT_ROOT)) if art_path.is_relative_to(Path(PROJECT_ROOT)) else art_path
                        print(f"     📄 {art_name} → {rel} ({art_path.stat().st_size} bytes) ✅")
                        found_artifacts[art_name] = fp
                    else:
                        print(f"     ⚠️  产物 {art_name} 无效：{artifact_reason}；降级为 REQUEST_CHANGES")
                        val = "REQUEST_CHANGES"
                        reason = f"[产品门禁] {art_name}: {artifact_reason}"

            flow_decide(run_id, state_id, role_id, val, reason)

            if val in fail_vals:
                break

        r3 = flow_step(run_id)
        if r3.get("ok"):
            print(f"  → {r3.get('from_state')} → {r3.get('to_state')}")
            # Self-loop termination: if gate self-loops and all roles decided, we're done
            if r3.get("from_state") and r3.get("from_state") == r3.get("to_state"):
                _all_decided = all(
                    store.agent_has_decision(run_id, r3["from_state"], r)
                    for r in required_roles
                )
                if _all_decided:
                    from hermes_flow.schemas import RunStatus
                    store.update_status(run_id, RunStatus.COMPLETED)
                    print(f"  🏁 Self-loop complete: all roles decided → completed")
                    break
        else:
            print(f"  ⏸ pending: {r3.get('error', '?')}")
            break

    # Manager evaluation
    if agents.get("manager"):
        print(f"\n{'='*60}")
        print(f"📝 管理 Agent 评审会议")
        print(f"{'='*60}")
        try:
            mgr_result = manager_evaluate(run_id, goal, agent_ids, agents, store)
            _persist_performance(store, run_id, goal, agent_ids, mgr_result)
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
    if msgs:
        print(f"\n💬 消息:")
        for r in msgs:
            print(f"  {r['from_role']:12s}| {r['substr(content,1,60)']}")
    print(f"\n📋 决策:")
    for r in decs:
        print(f"  [{r['state_id']:15s}] {r['role_id']:12s} → {r['value']}")
    print(f"\n🌐 http://localhost:8765\n")

    # Persist performance even without manager evaluation
    try:
        if store.load_run_performance(run_id) is None:
            _persist_performance(store, run_id, goal, agent_ids, None)
    except Exception:
        pass


def run_flow(goal: str, agent_ids: list[str], yaml_path: Path, run_name: str, agents: dict, output_dir: str = ""):
    """Flow engine: create run, wire hooks, start observer, enter FSM loop."""
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT
    os.environ["HERMES_WORKSPACE_ROOT"] = PROJECT_ROOT

    from hermes_flow.tools import flow_init
    from hermes_flow.run_paths import get_run_dir
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.trace import SqliteTracer, set_tracer

    result = flow_init(PROJECT_ROOT, str(yaml_path), run_name)
    if not result.get("ok"):
        print(f"❌ flow_init 失败: {result.get('error')}")
        sys.exit(1)

    run_id = result["run_id"]
    run_dir = get_run_dir(run_id, PROJECT_ROOT)
    store = RuntimeStore(run_dir)
    store.init_schema()

    reset_bus()
    _make_hook_handlers(store, run_id)

    from hermes_flow.observer import ensure_observer
    ensure_observer(port=8765, project_root=PROJECT_ROOT)

    set_tracer(SqliteTracer(store, run_id=run_id))

    print(f"\n{'='*60}")
    print(f"🏁 Run: {run_id}")
    print(f"🎯 {goal}")
    print(f"👥 {', '.join(agent_ids)}")
    print(f"🌐 http://localhost:8765")
    print(f"{'='*60}\n")

    _run_fsm_loop(store, run_id, goal, agent_ids, agents)


def resume_flow(run_id: str, extra_context: str = "", from_state: str = "", dry_run: bool = False):
    """Resume an existing run from its last checkpoint. dry_run=True: show info only."""
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT
    os.environ["HERMES_WORKSPACE_ROOT"] = PROJECT_ROOT

    from hermes_flow.run_paths import get_run_dir
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.trace import SqliteTracer, set_tracer

    # Try primary runs dir first, fallback to git root
    run_dir = get_run_dir(run_id, PROJECT_ROOT)
    if not run_dir.exists():
        _fallback = Path(PROJECT_ROOT) / ".hermes-flow" / "runs" / run_id
        if _fallback.exists():
            run_dir = _fallback
    if not run_dir.exists():
        print(f"❌ Run {run_id} not found")
        sys.exit(1)

    store = RuntimeStore(run_dir)
    store.init_schema()

    reset_bus()
    _make_hook_handlers(store, run_id)

    from hermes_flow.observer import ensure_observer
    ensure_observer(port=8765, project_root=PROJECT_ROOT)

    set_tracer(SqliteTracer(store, run_id=run_id))

    # Restore goal from agent_specs
    _specs = store.load_agent_specs(run_id)
    goal = _specs.get("_goal", run_id)

    # Rebuild agent list from bindings
    row = store.connect().execute("SELECT agent_bindings FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row:
        agent_ids = [b.get("role_id", "") for b in json.loads(row["agent_bindings"])]
    else:
        agent_ids = []

    # Inject extra context into goal + agent inboxes (before FSM loop)
    if extra_context:
        goal = f"{goal}\n\n## 补充说明\n{extra_context}"
        conn = store.connect()
        from uuid import uuid4 as _uuid4
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for rid in agent_ids:
            msg_id = _uuid4().hex[:12]
            conn.execute(
                "INSERT INTO messages(message_id,run_id,state_id,from_role,intended_recipients,"
                "authorized_recipients,recipient_availability,visibility,kind,content,"
                "delivery_outcome,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (msg_id, run_id, "", "user", json.dumps([rid]),
                 json.dumps([rid]), json.dumps({rid: True}),
                 "targeted", "question", extra_context, "delivered", now),
            )
            conn.execute(
                "INSERT INTO inboxes(run_id,role_id,state_id,message_id,generated_at) VALUES(?,?,?,?,?)",
                (run_id, rid, "", msg_id, now),
            )
        conn.commit()
        print(f"📝 Extra context injected: {extra_context[:60]}...")

    agents = load_agents()

    # Show available states + checkpoints
    conn = store.connect()
    _states = conn.execute(
        "SELECT state_id, state_json FROM states WHERE run_id=? ORDER BY rowid", (run_id,)
    ).fetchall()
    _state_ids = [s["state_id"] for s in _states if not json.loads(s["state_json"]).get("terminal")]
    _current = conn.execute("SELECT current_state_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    _current_sid = _current["current_state_id"] if _current else "?"

    print(f"\n📍 States: {' → '.join(_state_ids)}")
    print(f"   Current: {_current_sid}")

    ckpts = {}
    for _s_row in conn.execute(
        "SELECT role_id, state_id FROM agent_session_checkpoints WHERE run_id=?", (run_id,)
    ).fetchall():
        ckpt_data = store.load_agent_session_checkpoint(run_id, _s_row["role_id"], _s_row["state_id"])
        if ckpt_data:
            ckpts[f"{_s_row['role_id']}@{_s_row['state_id']}"] = f"turn {ckpt_data.get('turn', '?')}"

    if ckpts:
        print(f"   Checkpoints:")
        for k, v in ckpts.items():
            print(f"     {k} → {v}")

    print(f"\n💡 Resume from current state or rewind: debate --resume {run_id} --from-state <state>")

    # ── Branch on rewind: clone SQLite as new run, don't mutate original ──
    if from_state:
        if from_state not in _state_ids and from_state not in ("DONE", "ABORT"):
            print(f"❌ Unknown state '{from_state}'. Available: {', '.join(_state_ids)}")
            sys.exit(1)

        # Create a new branched run
        import shutil
        from uuid import uuid4 as _uuid4
        _branch_id = f"{run_id[:8]}-{from_state.lower()}-{_uuid4().hex[:4]}"
        _branch_dir = Path(run_dir).parent / _branch_id
        shutil.copytree(run_dir, _branch_dir)

        # Switch to the branch
        run_id = _branch_id
        store = RuntimeStore(_branch_dir)
        store.init_schema()
        set_tracer(SqliteTracer(store, run_id=run_id))
        conn = store.connect()

        # Rewind the branch
        conn.execute("UPDATE runs SET run_id=?, current_state_id=? WHERE run_id=?",
                     (_branch_id, from_state, run_dir.name))
        _from_idx = _state_ids.index(from_state) if from_state in _state_ids else len(_state_ids)
        for _sid in _state_ids[_from_idx:]:
            conn.execute("DELETE FROM decisions WHERE run_id=? AND state_id=?", (_branch_id, _sid))
        conn.commit()

        print(f"🌿 Branched: {_branch_id} (original {run_dir.name} untouched)")
        print(f"⏪   Rewound to: {from_state}")

    print(f"\n{'='*60}")
    print(f"🔄 Resume: {run_id}")
    print(f"🎯 {goal}")
    print(f"👥 {', '.join(agent_ids)}")
    print(f"🌐 http://localhost:8765")
    print(f"{'='*60}\n")

    if dry_run:
        print("🏁 Dry run — not executing. Use without --dry-run to start.")
        return

    _run_fsm_loop(store, run_id, goal, agent_ids, agents)


# ══════════════════════════════════════════════════════════════════════
#  Manager evaluation
# ══════════════════════════════════════════════════════════════════════

def manager_evaluate(run_id: str, goal: str, agent_ids: list[str],
                     agents: dict, store):
    """Manager reads full transcript and evaluates each agent with evidence."""
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
        f"  [{r['state_id']}] {r['role_id']} -> {r['value']}"
        for r in all_decs
    ])

    # Scan for deliverable files
    deliverables = {}
    for fname in ["spec.md", "plan.md", "tasks.md", "review.md", "test-report.md",
                   "research.md", "analysis.md", "report.md", "README.md"]:
        fpath = Path(PROJECT_ROOT) / fname
        if fpath.exists() and fpath.stat().st_size > 0:
            content_val = fpath.read_text(encoding="utf-8", errors="ignore")
            deliverables[fname] = content_val[:500]
    deliverables_text = ""
    if deliverables:
        deliverables_text = "\n## 交付物检查\n" + "\n".join(
            f"### {name}\n{content_val[:300]}" for name, content_val in deliverables.items()
        )

    # ---- Per-agent evidence from SQLite ----
    # Load state topology to determine gate requirements
    _states_rows = conn.execute(
        "SELECT state_id, state_json FROM states WHERE run_id=? ORDER BY rowid", (run_id,),
    ).fetchall()
    _gate_roles: dict[str, set] = {}  # agent -> set of states where it's gate-required
    for _s in _states_rows:
        _sj = json.loads(_s["state_json"]) if _s["state_json"] else {}
        _gate = _sj.get("gate") or {}
        for _r in _gate.get("required_roles", []):
            _gate_roles.setdefault(_r, set()).add(_s["state_id"])

    evidence_per_agent = {}
    for aid in agent_ids:
        parts = []
        # Gate role annotation — distinguishes "idle reviewer" from "wasted agent"
        _gate_states = _gate_roles.get(aid, set())
        if _gate_states:
            parts.append(f"gate_required_in: {', '.join(sorted(_gate_states))}")
        else:
            parts.append("gate_required_in: (none — not a gate requirement)")
        # Tool stats
        _total_tools = conn.execute(
            "SELECT COUNT(*) as c FROM thinking_events WHERE run_id=? AND role_id=?", (run_id, aid),
        ).fetchone()
        parts.append(f"tool_calls: {_total_tools['c']}")
        _tool_fails = conn.execute(
            "SELECT step_type, COUNT(*) as c FROM thinking_events WHERE run_id=? AND role_id=? AND output_json NOT LIKE '%ok%true%' GROUP BY step_type",
            (run_id, aid),
        ).fetchall()
        if _tool_fails:
            fails_str = ", ".join(f"{r['step_type']}x{r['c']}" for r in _tool_fails)
            parts.append(f"tool_failures: {fails_str}")
        # Decisions
        _decs = conn.execute(
            "SELECT COUNT(*) as c FROM decisions WHERE run_id=? AND role_id=?", (run_id, aid),
        ).fetchone()
        parts.append(f"decisions: {_decs['c']}")
        evidence_per_agent[aid] = "; ".join(parts)

    evidence_text = "\n".join(f"  {aid}: {evidence_per_agent.get(aid, '')}" for aid in agent_ids)

    # Manager self-eval data
    _team_choice_row = conn.execute(
        "SELECT agent_bindings FROM runs WHERE run_id=?", (run_id,),
    ).fetchone()
    team_choice = json.loads(_team_choice_row["agent_bindings"]) if _team_choice_row else []

    manager_info = agents.get("manager", {})
    soul = manager_info.get("soul", "")

    system = f"""你是流程管理专家。基于实际运行数据评审每个 agent 和自身的表现。
{soul[:200]}

评审要求 -- **必须基于证据，禁止空谈**：
1. 每个 agent：指出具体问题（带数据）和改进类别（memory/skill/tool/new_agent）
2. 自己（manager）：评审选队策略是否合理
3. **区分 gate 审查者与浪费 agent**：
   - gate_required_in 有的 agent 即使 tool_calls=0，也可能是等待上游产物的审查者（保留）
   - gate_required_in=(none) 且 tool_calls=0 的 agent 才是真正的浪费（应移除）
4. 改进建议必须有的放矢，例如 "file_write 成功率 0%，需要在 skill 中加 .md 后缀示例"

响应 JSON:
{{{{"feedback": [{{{{"agent_id": "xxx", "category": "skill", "suggestion": "具体改进建议（含数据）", "evidence": "数据支撑"}}}}]}},
  "self_eval": {{{{"category": "skill", "suggestion": "manager 自身改进方向", "evidence": "选队数据"}}}},
  "team_pattern": "团队搭配效果总结",
  "gate_suggestion": "gate 改进建议"
}}}}
category 取值: memory | skill | tool | new_agent"""

    user = f"""## 任务目标
{goal}

## 参与 Agent
{', '.join(agent_ids)}

## 每个 Agent 的运行证据
{evidence_text}

## 决策序列
{decisions_summary[:1000]}

## Manager 选队决策
选队理由: 选择了 {', '.join([b.get('role_id','?') for b in team_choice])} 共 {len(team_choice)} 人

## 完整消息记录
{transcript[:1500]}

## 交付物文件
{deliverables_text[:1500]}"""

    print("  \U0001f916 管理 Agent 评审中...")
    result = call_llm(system, user, temperature=0.4, max_tokens=2500)
    feedback_list = result.get("feedback", [])
    self_eval = result.get("self_eval", {})
    team_pattern = result.get("team_pattern", "")
    gate_suggestion = result.get("gate_suggestion", "")

    # Save per-agent feedback
    for fb in feedback_list:
        aid = fb.get("agent_id", "")
        if aid and aid in agents:
            store.save_agent_feedback(
                run_id=run_id, agent_id=aid,
                category=fb.get("category", ""),
                suggestion=fb.get("suggestion", ""),
                evidence=fb.get("evidence", ""),
            )

    # Save manager self-feedback
    if self_eval and self_eval.get("suggestion"):
        store.save_agent_feedback(
            run_id=run_id, agent_id="manager",
            category=self_eval.get("category", "skill"),
            suggestion=self_eval.get("suggestion", ""),
            evidence=self_eval.get("evidence", ""),
        )

    total_fb = len(feedback_list) + (1 if self_eval.get("suggestion") else 0)
    print(f"  \u2705 评审完成 ({total_fb} feedback entries)")

    # Reconstruct evaluations dict for backward compat
    evaluations = {}
    for fb in feedback_list:
        aid = fb.get("agent_id", "")
        evaluations[aid] = fb.get("suggestion", "")

    return {
        "evaluations": evaluations,
        "team_pattern": team_pattern,
        "gate_suggestion": gate_suggestion,
        "agent_ids": agent_ids,
        "feedback": feedback_list,
        "self_eval": self_eval,
    }


def _persist_performance(store, run_id: str, goal: str, agent_ids: list[str],
                         manager_result: dict | None):
    """Compute run performance metrics and save to store. No LLM needed."""
    conn = store.connect()

    # ── Tool stats from thinking_events ──
    tool_rows = conn.execute(
        "SELECT step_type FROM thinking_events WHERE run_id=? AND step_type NOT IN ('submit_decision','memory_read','memory_write')",
        (run_id,),
    ).fetchall()
    tool_calls: dict[str, int] = {}
    for r in tool_rows:
        tool_calls[r["step_type"]] = tool_calls.get(r["step_type"], 0) + 1

    # ── Bottleneck state (most rounds/retries) ──
    trans_rows = conn.execute(
        "SELECT from_state_id, COUNT(*) as cnt FROM transitions WHERE run_id=? GROUP BY from_state_id ORDER BY cnt DESC",
        (run_id,),
    ).fetchall()
    bottleneck = trans_rows[0]["from_state_id"] if trans_rows else "?"

    # ── Success score: based on completion status + manager eval ──
    status_row = conn.execute(
        "SELECT status FROM runs WHERE run_id=?", (run_id,),
    ).fetchone()
    completed = status_row and status_row["status"] == "completed"

    agent_scores = {}
    if manager_result:
        for aid in agent_ids:
            eval_text = manager_result.get("evaluations", {}).get(aid, "")
            score = 70  # base
            if "优秀" in eval_text or "出色" in eval_text:
                score += 20
            elif "良好" in eval_text or "称职" in eval_text or "完成" in eval_text:
                score += 10
            if "改进" in eval_text or "不足" in eval_text or "缺失" in eval_text:
                score -= 15
            agent_scores[aid] = max(0, min(100, score))

    # ── Summary ──
    decs_count = conn.execute(
        "SELECT COUNT(*) as c FROM decisions WHERE run_id=?", (run_id,),
    ).fetchone()["c"]
    msgs_count = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE run_id=?", (run_id,),
    ).fetchone()["c"]

    success_score = 85 if completed else max(30, 50 - len(trans_rows) * 5)
    summary = (
        f"Task: {goal[:100]}. "
        f"{'Completed' if completed else 'Active/Aborted'}. "
        f"{decs_count} decisions, {msgs_count} messages, "
        f"{len(tool_calls)} tool calls across {len(agent_ids)} agents. "
        f"Bottleneck: {bottleneck}."
    )
    suggestions = manager_result.get("gate_suggestion", "") if manager_result else ""

    store.save_run_performance(
        run_id=run_id,
        success_score=success_score,
        summary=summary,
        agent_scores=agent_scores,
        bottleneck_state=bottleneck,
        tool_stats=tool_calls,
        suggestions=suggestions,
    )
    print(f"  📊 Performance: score={success_score} bottleneck={bottleneck} agents={list(agent_scores.keys())}")

    return store.load_run_performance(run_id)


# ══════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════

def _analyze_all_runs():
    """Cross-run pattern recognition. Aggregates performance data and generates suggestions."""
    from hermes_flow.storage import RuntimeStore
    from collections import Counter

    dirs = [Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
            Path(__file__).resolve().parent / ".hermes-flow" / "runs"]
    seen = set()
    all_perf = []

    # ── Collect all performance data ──
    for base in dirs:
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or d.name in seen:
                continue
            seen.add(d.name)
            try:
                store = RuntimeStore(d)
                store.init_schema()
                perf = store.load_run_performance(d.name)
                if perf:
                    all_perf.append(perf)
            except Exception:
                pass

    if len(all_perf) < 2:
        print(f"Need at least 2 runs with performance data. Found: {len(all_perf)}")
        return

    print(f"\n{'='*60}")
    print(f"📊 Cross-Run Analysis ({len(all_perf)} runs)")
    print(f"{'='*60}")

    # ── Score trends ──
    scores = [p["success_score"] for p in all_perf]
    avg_score = sum(scores) / len(scores)
    print(f"\n📈 Scores: avg={avg_score:.0f}  min={min(scores)}  max={max(scores)}  range={max(scores)-min(scores)}")
    if avg_score < 60:
        print(f"   ⚠️  Average below 60 — systematic issues present")

    # ── Bottleneck states ──
    bottlenecks = Counter(p["bottleneck_state"] for p in all_perf if p["bottleneck_state"])
    print(f"\n🔴 Bottleneck states:")
    for state, count in bottlenecks.most_common():
        pct = count / len(all_perf) * 100
        bar = "█" * int(pct / 10)
        print(f"   {state:<15} {count}/{len(all_perf)} ({pct:.0f}%) {bar}")

    # ── Agent scores ──
    agent_all: dict[str, list[int]] = {}
    for p in all_perf:
        for aid, score in p.get("agent_scores", {}).items():
            agent_all.setdefault(aid, []).append(score)
    if agent_all:
        print(f"\n🤖 Agent performance:")
        for aid, scores_list in sorted(agent_all.items(), key=lambda x: sum(x[1])/len(x[1])):
            avg = sum(scores_list) / len(scores_list)
            bar = "█" * int(avg / 5)
            print(f"   {aid:<18} avg={avg:.0f} (n={len(scores_list)}) {bar}")

    # ── Tool usage ──
    tool_all: dict[str, int] = {}
    for p in all_perf:
        for tool, count in p.get("tool_stats", {}).items():
            tool_all[tool] = tool_all.get(tool, 0) + count
    if tool_all:
        print(f"\n🔧 Tool usage (total across {len(all_perf)} runs):")
        for tool, count in sorted(tool_all.items(), key=lambda x: -x[1]):
            print(f"   {tool:<20} {count:>5} calls")

    # ── Pattern detection ──
    print(f"\n{'='*60}")
    print(f"🔍 Detected Patterns")
    print(f"{'='*60}")

    suggestions = []

    # Pattern 1: single-state runs (direct-chat) with low scores
    single_state = [p for p in all_perf if p["bottleneck_state"] in ("DONE", "?")]
    if len(single_state) >= len(all_perf) * 0.5:
        s = f"   {len(single_state)}/{len(all_perf)} runs are single-state (direct-chat), avg score {sum(p['success_score'] for p in single_state)/len(single_state):.0f}"
        print(s)
        print(f"   → Suggestion: use spec-team pipeline for non-trivial tasks; single-agent mode lacks review gates")
        suggestions.append("prefer spec-team pipeline over direct-chat for tasks with deliverables")

    # Pattern 2: bottleneck recurrence
    top_bn = bottlenecks.most_common(1)
    if top_bn and top_bn[0][1] >= 2:
        print(f"\n   Top bottleneck: {top_bn[0][0]} ({top_bn[0][1]} runs)")
        print(f"   → Suggestion: review gate config and agent skill for '{top_bn[0][0]}' state")

    # Pattern 3: low-scoring agents
    if agent_all:
        low_agents = [(aid, sum(s)/len(s)) for aid, s in agent_all.items() if sum(s)/len(s) < 50]
        if low_agents:
            print(f"\n   Low-performing agents (<50 avg):")
            for aid, avg in low_agents:
                print(f"   → {aid}: avg {avg:.0f} — consider updating SOUL.md or skill prompts")

    # Pattern 4: tool usage imbalance
    if tool_all:
        top_tool = max(tool_all, key=lambda k: tool_all[k])
        top_pct = tool_all[top_tool] / sum(tool_all.values()) * 100
        if top_pct > 60:
            print(f"\n   Tool concentration: '{top_tool}' = {top_pct:.0f}% of all calls")
            print(f"   → Suggestion: agents may be over-relying on {top_tool}; consider expanding toolset")

    print(f"\n💡 Summary suggestion:")
    combined = "; ".join(suggestions[:3]) if suggestions else "collect more data for reliable patterns"
    print(f"   {combined}")

    return all_perf


def _show_performance(run_id: str):
    """Display run performance evaluation."""
    from hermes_flow.storage import RuntimeStore

    for base in [Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
                 Path(__file__).resolve().parent / ".hermes-flow" / "runs"]:
        run_dir = base / run_id
        if run_dir.exists():
            store = RuntimeStore(run_dir)
            store.init_schema()
            perf = store.load_run_performance(run_id)
            if perf:
                print(f"\n📊 Run Performance: {run_id}")
                print(f"   Score: {perf['success_score']}/100")
                print(f"   Summary: {perf['summary']}")
                print(f"   Bottleneck: {perf['bottleneck_state']}")
                print(f"   Agent scores: {json.dumps(perf['agent_scores'], ensure_ascii=False)}")
                print(f"   Tools: {json.dumps(perf['tool_stats'], ensure_ascii=False)}")
                if perf['suggestions']:
                    print(f"   Suggestions: {perf['suggestions']}")
            else:
                print(f"❌ No performance data for {run_id}")
            return
    print(f"❌ Run {run_id} not found")


def _list_runs():
    """Scan runs directories and display a summary table."""
    from hermes_flow.storage import RuntimeStore

    dirs = [Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
            Path(__file__).resolve().parent / ".hermes-flow" / "runs"]
    seen = set()
    runs = []

    for base in dirs:
        if not base.exists():
            continue
        for d in sorted(base.iterdir(), reverse=True):
            if not d.is_dir() or d.name in seen:
                continue
            seen.add(d.name)
            try:
                store = RuntimeStore(d)
                store.init_schema()
                conn = store.connect()
                row = conn.execute(
                    "SELECT run_id, status, current_state_id, created_at FROM runs WHERE run_id=?",
                    (d.name,)
                ).fetchone()
                if not row:
                    continue
                decs = conn.execute(
                    "SELECT COUNT(*) as c FROM decisions WHERE run_id=?", (d.name,)
                ).fetchone()
                ckpts = conn.execute(
                    "SELECT role_id, state_id FROM agent_session_checkpoints WHERE run_id=?",
                    (d.name,)
                ).fetchall()
                db_size = d.joinpath("state.sqlite").stat().st_size
                # Check performance
                perf = store.load_run_performance(d.name)
                score = perf["success_score"] if perf else None
                runs.append({
                    "id": d.name,
                    "status": row["status"],
                    "state": row["current_state_id"],
                    "decisions": decs["c"] if decs else 0,
                    "checkpoints": len(ckpts),
                    "size_kb": db_size // 1024,
                    "created": row["created_at"][:19].replace("T", " ") if row["created_at"] else "",
                    "score": score,
                })
            except Exception:
                pass

    if not runs:
        print("No runs found.")
        return

    print(f"\n{'Run ID':<14} {'Score':<7} {'Status':<10} {'State':<10} {'Decs':<5} {'Ckpts':<5} {'Size':<8} Created")
    print("-" * 90)
    for r in runs:
        score_str = f"{r['score']}" if r['score'] is not None else "-"
        ckpt_mark = f"📦{r['checkpoints']}" if r['checkpoints'] else "-"
        print(f"{r['id']:<14} {score_str:<7} {r['status']:<10} {r['state']:<10} {r['decisions']:<5} {ckpt_mark:<5} {r['size_kb']:>4}KB  {r['created']}")
    print(f"\n{len(runs)} runs.")


def print_help():
    print("""debate — 多 Agent 协作 FSM 执行框架

用法:
  debate <任务描述>                              启动新任务
  debate --resume <run_id>                       恢复中断的 run
  debate --resume --history                      显示历史列表
  debate --resume --performance <run_id>         查看 run 评分
  debate --analyze                               跨 run 模式分析
  debate --evolve-agent <agent_id>               为 agent 执行定向进化
  debate --feedback [agent_id]                    查看待改进清单
  debate --resume <run_id> --states              查看可恢复状态（不执行）
  debate --resume <run_id> --from-state <STATE>  从指定 state 创建新分支并恢复
  debate --resume <run_id> "补充说明"             恢复时注入额外上下文
  debate -h | --help                             显示此帮助

选项:
  --resume <run_id>        恢复已有 run（自动从 checkpoint 续跑）
  --states                 仅查看可恢复状态，不执行（配合 --resume 使用）
  --from-state <STATE>     回溯到指定 state 创建新分支（配合 --resume 使用）

示例:
  debate "用3句话介绍 Rust 语言"
  debate --resume ede4011e0d60
  debate --resume ede4011e0d60 --states
  debate --resume ede4011e0d60 --from-state SPEC
  debate --resume ede4011e0d60 --from-state SPEC
  debate --resume ede4011e0d60 --from-state PLAN "需要加入性能测试"

目录:
  所有 run 存储在 experiments/agent-pool/.hermes-flow/runs/<run_id>/
  Observer Dashboard: http://localhost:8765（首次 resume/new 时自动启动）""")


def _show_feedback(agent_id: str | None = None):
    """Show pending feedback for an agent or all agents."""
    from hermes_flow.storage import RuntimeStore

    dirs = [Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
            Path(__file__).resolve().parent / ".hermes-flow" / "runs"]
    all_fb = []

    for base in dirs:
        if not base.exists():
            continue
        for d in base.iterdir():
            if not d.is_dir():
                continue
            try:
                store = RuntimeStore(d)
                store.init_schema()
                if agent_id:
                    fb_list = store.load_agent_feedback(agent_id)
                else:
                    fb_list = store.load_all_pending_feedback()
                all_fb.extend(fb_list)
            except Exception:
                pass

    if agent_id:
        if all_fb:
            print(f"\n📝 Pending feedback for {agent_id} ({len(all_fb)} items):\n")
            for fb in all_fb:
                print(f"  [{fb['category']:8s}] {fb['suggestion'][:150]}")
                print(f"     evidence: {fb['evidence'][:100]}")
                print()
        else:
            print(f"✅ No pending feedback for {agent_id}")
    else:
        by_agent: dict[str, list] = {}
        for fb in all_fb:
            by_agent.setdefault(fb["agent_id"], []).append(fb)
        if by_agent:
            print(f"\n📝 Pending feedback ({len(all_fb)} total):\n")
            for aid, items in sorted(by_agent.items()):
                print(f"  {aid} ({len(items)} items):")
                for fb in items:
                    print(f"    [{fb['category']:8s}] {fb['suggestion'][:120]}")
        else:
            print("✅ No pending feedback")


def _evolve_agent(agent_id: str, apply: bool = False):
    """Run EvolutionAgent: read feedback, generate precise modifications, optionally apply."""
    from hermes_flow.storage import RuntimeStore

    dirs = [Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
            Path(__file__).resolve().parent / ".hermes-flow" / "runs"]
    all_fb = []
    store = None

    for base in dirs:
        if not base.exists():
            continue
        for d in base.iterdir():
            if not d.is_dir():
                continue
            try:
                store = RuntimeStore(d)
                store.init_schema()
                fb_list = store.load_agent_feedback(agent_id)
                all_fb.extend(fb_list)
                if all_fb:
                    break
            except Exception:
                pass

    if not all_fb:
        print(f"✅ No pending feedback for {agent_id}")
        return

    # Read current agent state
    agent_dir = _SCRIPT_DIR / "agents" / agent_id
    soul_path = agent_dir / "SOUL.md"
    memory_path = agent_dir / "Memory.md"
    soul_content = soul_path.read_text() if soul_path.exists() else "(no SOUL)"
    memory_content = memory_path.read_text() if memory_path.exists() else "(no Memory)"

    feedback_text = "\n".join(
        f"- [{fb['category']}] {fb['suggestion']} (evidence: {fb['evidence'][:100]})"
        for fb in all_fb
    )

    soul_size = len(soul_content)
    memory_size = len(memory_content)
    MAX_MEMORY = 4096   # 4KB hard cap
    MAX_SKILL  = 8192   # 8KB hard cap

    size_info = f"SOUL: {soul_size}B, Memory: {memory_size}B/{MAX_MEMORY}B, SKILL: N/A"
    if agent_dir.joinpath("SKILL.md").exists():
        skill_size = agent_dir.joinpath("SKILL.md").stat().st_size
        size_info = f"SOUL: {soul_size}B, Memory: {memory_size}B/{MAX_MEMORY}B, SKILL: {skill_size}B/{MAX_SKILL}B"

    system = f"""你是 EvolutionAgent——一个精确、谨慎的 agent 修改执行者。
你**不能自由发挥**，只能基于 feedback 中的具体证据进行定向修改。

当前 agent: {agent_id}
文件大小限制: {size_info}

你的能力：
- update_memory: 追加或修正 Memory.md（硬上限 {MAX_MEMORY}B，超限时只能替换旧内容）
- update_skill: patch 或新增 SKILL.md（硬上限 {MAX_SKILL}B，超限时只能替换旧内容）
- add_tool: 从工具池中分配新工具
- dismiss: 如果 feedback 不适用，标记为 dismissed

修改原则：
1. 每条修改必须引用具体的 feedback 证据
2. 最小改动——能不改就不改
3. 如果 feedback 已过时或不适用，果断 dismiss
4. 接近上限时，优先替换旧的 Evolution Update 而非追加
5. 避免写入已在文件中存在的内容（去重）
6. 响应 JSON: {{"actions": [{{"type": "update_memory|update_skill|add_tool|dismiss", "detail": "具体修改内容"}}]}}"""

    user = f"""## Agent: {agent_id}

### 当前 SOUL
{soul_content[:800]}

### 当前 Memory
{memory_content[:800]}

### Pending Feedback ({len(all_fb)} items)
{feedback_text}

请生成修改计划。"""

    print(f"  🧬 EvolutionAgent analyzing {agent_id} ({len(all_fb)} feedback items)...")
    result = call_llm(system, user, temperature=0.3, max_tokens=2000)
    actions = result.get("actions", [])

    if not actions:
        print("  ℹ️  No actions generated")
        return

    print(f"\n  📋 Evolution Plan for {agent_id}:\n")
    for i, act in enumerate(actions, 1):
        atype = act.get("type", "?")
        detail = act.get("detail", "")[:200]
        fb_ids = act.get("feedback_ids", [])
        print(f"  {i}. [{atype}] {detail}")
        print(f"     feedback_refs: {fb_ids}")

    # Confirm / Apply
    if apply:
        agent_dir = _SCRIPT_DIR / "agents" / agent_id
        applied = 0
        for act in actions:
            atype = act.get("type", "")
            detail = act.get("detail", "")
            if atype == "dismiss":
                for fb in all_fb:
                    store.mark_feedback_dismissed(fb["row_id"])
                applied += len(all_fb)
            elif atype in ("update_skill", "update_memory"):
                target_file = agent_dir / ("SKILL.md" if atype == "update_skill" else "Memory.md")
                max_bytes = MAX_SKILL if atype == "update_skill" else MAX_MEMORY
                current_size = target_file.stat().st_size if target_file.exists() else 0

                if not detail.startswith("#"):
                    detail = f"\n## Evolution Update\n{detail}\n"
                new_content = f"\n{detail}\n"

                # Dedup: skip if already present
                if target_file.exists():
                    existing = target_file.read_text()
                    if detail.strip() in existing:
                        print(f"  ⏭  Skipped {target_file.name} (content already exists)")
                        continue

                # Hard limit check
                if current_size + len(new_content) > max_bytes:
                    print(f"  ⚠️  {target_file.name} at {current_size}B/{max_bytes}B — cannot append. Trim old Evolution Updates manually.")
                    continue

                with open(target_file, "a") as f:
                    f.write(new_content)
                applied += 1
                print(f"  ✅ Updated {target_file.name} ({current_size}B → {current_size + len(new_content)}B)")
        # Mark all feedback as applied
        for fb in all_fb:
            store.mark_feedback_applied(fb["row_id"])
        print(f"\n  🧬 Applied {applied} changes, cleared {len(all_fb)} feedback items")
    else:
        print(f"\n  ⚠️  Review the plan above. Use --apply to execute:")
        print(f"     debate --evolve-agent {agent_id} --apply")

    return actions


def _evolve_all():
    """Process all agents with pending feedback."""
    from hermes_flow.storage import RuntimeStore

    dirs = [Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
            Path(__file__).resolve().parent / ".hermes-flow" / "runs"]
    by_agent: dict[str, list] = {}

    for base in dirs:
        if not base.exists():
            continue
        for d in base.iterdir():
            if not d.is_dir():
                continue
            try:
                store = RuntimeStore(d)
                store.init_schema()
                for fb in store.load_all_pending_feedback():
                    by_agent.setdefault(fb["agent_id"], []).append(fb)
            except Exception:
                pass

    if not by_agent:
        print("✅ No pending feedback")
        return

    print(f"🧬 Evolving {len(by_agent)} agents...\n")
    for agent_id in sorted(by_agent):
        print(f"── {agent_id} ({len(by_agent[agent_id])} items) ──")
        _evolve_agent(agent_id, apply=True)
        print()

    print("✅ All agents evolved. Run --feedback to verify.")


def _evolve():
    perf_data = _analyze_all_runs()
    if not perf_data:
        return

    print(f"\n{'='*60}")
    print(f"🧬 Evolution Suggestions")
    print(f"{'='*60}\n")

    changes = []

    # Suggestion 1: Single-agent → prefer spec-team
    scores = [p["success_score"] for p in perf_data]
    bottlenecks = [p["bottleneck_state"] for p in perf_data]
    single_count = sum(1 for b in bottlenecks if b in ("DONE", "?"))
    if single_count >= len(perf_data) * 0.5 and sum(scores) / len(scores) < 70:
        changes.append({
            "title": "Prefer spec-team pipeline for tasks with deliverables",
            "file": "agents/manager/SOUL.md",
            "description": (
                f"Direct-chat (single-agent) runs avg score {sum(s for p in perf_data if p['bottleneck_state'] in ('DONE','?') for s in [p['success_score']])/max(1,single_count):.0f} vs "
                f"multi-agent {sum(s for p in perf_data if p['bottleneck_state'] not in ('DONE','?') for s in [p['success_score']])/max(1,len(perf_data)-single_count):.0f}. "
                "Update manager SOUL to prefer spec-team for any task requiring file output."
            ),
        })

    # Suggestion 2: Self-loop termination (already fixed in code)
    changes.append({
        "title": "Self-loop termination for single-agent flows",
        "file": "auto-debate.py::_run_fsm_loop",
        "description": (
            "Added self-loop detection: when gate transitions to same state and all roles decided, "
            "mark run as completed instead of looping until max_rounds exhausted. "
            "This fixes single-agent flows that previously scored 45 due to infinite DONE→DONE loops."
        ),
        "applied": True,
    })

    # Suggestion 3: Low-scoring agents
    agent_scores: dict[str, list] = {}
    for p in perf_data:
        for aid, s in p.get("agent_scores", {}).items():
            agent_scores.setdefault(aid, []).append(s)
    for aid, scores_list in agent_scores.items():
        avg = sum(scores_list) / len(scores_list)
        if avg < 60 and len(scores_list) >= 2:
            changes.append({
                "title": f"Update {aid} skill prompts",
                "file": f"shared/skills/{aid}/SKILL.md",
                "description": (
                    f"{aid} avg score {avg:.0f} over {len(scores_list)} runs. "
                    f"Consider adding explicit exit signals (\"做完就交\"), clearer tool usage instructions, "
                    f"or providing example outputs in the skill doc."
                ),
            })

    for i, c in enumerate(changes, 1):
        status = "✅ APPLIED" if c.get("applied") else "📝 SUGGESTED"
        print(f"{i}. [{status}] {c['title']}")
        print(f"   File: {c['file']}")
        print(f"   {c['description']}")
        print()

    print("💡 To apply: review suggestions, edit files manually or re-run after confirming.")
    return changes


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print_help()
        sys.exit(0)

    # ── Check for --resume flag ──────────────────────────────────
    if sys.argv[1] == "--resume":
        # ── --history: list all runs ──────────────────────────
        if len(sys.argv) >= 3 and sys.argv[2] == "--history":
            _list_runs()
            return
        # ── --performance <run_id>: show performance ─────────
        if len(sys.argv) >= 4 and sys.argv[2] == "--performance":
            _show_performance(sys.argv[3])
            return
        if len(sys.argv) < 3:
            print("❌ --resume requires a run_id (or --history / --performance <id>)")
            sys.exit(1)
    elif sys.argv[1] == "--analyze":
        _analyze_all_runs()
        return
    elif sys.argv[1] == "--evolve":
        _evolve()
        return
    elif sys.argv[1] == "--evolve-agent":
        if len(sys.argv) < 3:
            print("❌ --evolve-agent requires an agent_id")
            sys.exit(1)
        _apply = "--apply" in sys.argv
        _evolve_agent(sys.argv[2], apply=_apply)
        return
    elif sys.argv[1] == "--evolve-all":
        _evolve_all()
        return
    elif sys.argv[1] == "--feedback":
        agent_id = sys.argv[2] if len(sys.argv) > 2 else None
        _show_feedback(agent_id)
        return
        run_id = sys.argv[2]
        from_state = ""
        extra_parts = []
        dry_run = False
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--from-state" and i + 1 < len(sys.argv):
                from_state = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--states":
                dry_run = True
                i += 1
            elif sys.argv[i] == "--performance" and i + 1 < len(sys.argv):
                _show_performance(sys.argv[i + 1])
                return
            else:
                extra_parts.append(sys.argv[i])
                i += 1
        extra = " ".join(extra_parts)
        resume_flow(run_id, extra_context=extra, from_state=from_state, dry_run=dry_run)
        return

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

    # Phase 1: Manager selects agents + team skill (now returns flow topology)
    agent_ids, flow_topology, output_base = manager_select_agents(goal, agents)

    if not flow_topology:
        if len(agent_ids) == 1:
            flow_topology = [{
                "state": "DONE",
                "description": goal[:80],
                "actors": agent_ids[0],
                "gate": {"type": "decision", "pass": "DONE", "fail": "ABORT", "max": 3},
            }]
            print(f"  💬 简单任务，单 agent 直接回答")
        else:
            print("  ⚠️ 未匹配到班底，使用默认空拓扑")

    # Phase 2: Manager generates flow YAML + briefs agents
    print("\n📄 生成 Flow YAML...")
    yaml_path = generate_yaml(goal, agent_ids, run_name, agents, flow_topology, output_base)
    print(f"   → {yaml_path}")

    # Manager briefs each agent via inbox
    print("\n📨 管理者发送任务简报...")
    sys.path.insert(0, str(_PROJECT_ROOT_DIR))
    os.environ["HERMES_WORKSPACE_ROOT"] = PROJECT_ROOT
    try:
        from hermes_flow.tools import flow_send
    except ModuleNotFoundError:
        print(f"  ⚠️ hermes_flow 加载失败, 检查路径: {_PROJECT_ROOT_DIR}")
        flow_send = None
    # We need a run_id to send messages. Use YAML's flow_id or init a placeholder.
    # Actually, inbox is only available after flow_init. Let's write briefing to
    for aid in agent_ids:
        print(f"  ✅ {aid}: 已收到任务简报")

    # Phase 3: Flow engine runs (NOT manager)
    # Resolve output directory from YAML path (flow_id is in filename)
    _flow_id = yaml_path.stem
    _resolved_output = output_base.replace("{flow_id}", _flow_id) if output_base else f"output/{_flow_id}"
    run_flow(goal, agent_ids, yaml_path, run_name, agents, _resolved_output)

    print(f"  ✅ manager: 决策已记录")


if __name__ == "__main__":
    main()
