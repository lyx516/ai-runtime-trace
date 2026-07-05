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
from pathlib import Path
from typing import Any, Optional

# Script location (agents, tools, skills live here)
_SCRIPT_DIR = Path(__file__).resolve().parent
# Project root (where hermes_flow package lives)
_PROJECT_ROOT_DIR = _SCRIPT_DIR.parent.parent
# Runtime project root (where runs/artifacts are searched/created)
PROJECT_ROOT = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or str(_PROJECT_ROOT_DIR)
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

    from trait_loader import resolve_agent_tools
    agent_list_lines = []
    for aid, info in agents.items():
        if aid == "manager":
            continue
        # Resolve effective tools via trait system
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

    system = f"""你是流程管理专家。根据用户目标从 Agent 池中选择 1-6 个。{team_skills_text}

选择原则：
- 闲聊、简单问答（讲笑话、问好、天气） → direct-chat (任意1个 agent, 如 writer 或 designer)
- 纯方案推演/辩论 → debate-team (designer + critic + mediator + decider)
- 完整开发流水线 → spec-team (spec-writer + plan-maker + task-breaker + implementer + code-reviewer)
- 调研分析 → research-team (researcher + analyst + writer)
- 全栈（辩论→实现→文档） → fullstack-team
- 简单修复 → quick-fix-team (implementer + tester)
- 也可以混编多个班底

对于简单的聊天式任务，只选 1 个 agent 即可，team 用 "direct-chat"。
对于复杂开发任务，选 3-6 个 agent。

响应格式（严格 JSON）：
{{"agents": ["id1","id2",...], "reason": "选择理由", "team": "使用的班底名称"}}
"""

    user = f"## 任务\n{goal}\n\n## Agent 池\n{agent_list}\n\n请选择。"
    print("\n🤔 管理 Agent 正在分析任务...")
    result = call_llm(system, user, temperature=0.3)
    selected = result.get("agents", [])
    reason = result.get("reason", "")
    team = result.get("team", "")

    valid = [a for a in selected if a in agents and a != "manager"]
    if len(valid) < 1:
        valid = ["designer", "critic", "mediator", "decider"]
        reason = "选择不足，使用默认辩论组合"

    print(f"  选择了: {', '.join(valid)}")
    print(f"  理由: {reason}" if reason else "")
    print(f"  班底: {team}" if team else "")
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
        f"## 你的任务",
        f"目标: {goal}",
    ]
    if output_artifacts:
        parts.append(f"你需要产出: {', '.join(output_artifacts)}")
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
    """Multi-turn agent session: think → tool → feedback → think → ... → decision.

    Uses OpenAI function calling natively. The LLM can:
    - Call any tool from tool_schemas (file_read, patch, etc.)
    - Call submit_decision when done (a pseudo-tool defined in tool_registry)
    - All tool results are fed back as subsequent messages
    - Loop continues until submit_decision or max turns

    Returns: {"value": "APPROVE|REQUEST_CHANGES|BLOCKED", "reason": "...", "tool_calls": N}
    """
    from tool_registry import execute_tool, format_tool_results_for_llm, DECISION_TOOL_SCHEMA

    # Build system prompt
    system = _build_multi_turn_system_prompt(
        role_id, soul, goal, output_artifacts, tool_schemas, write_scope,
        flow_overview=flow_overview,
    )

    # Build initial messages
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

    # Inject previous state's artifact paths so this agent knows where to find them
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
        # Append to the last message
        if artifact_hint:
            messages[-1]["content"] += f"\n{artifact_hint.strip()}"

    # OpenAI tools format: real tools + submit_decision pseudo-tool
    tools = list(tool_schemas)
    tools.append(DECISION_TOOL_SCHEMA)

    max_turns = 20
    tool_calls_made = 0
    _empty_fails = 0
    _last_empty_tool = ""

    # Inject turn info + state context as separate messages.
    # State context is appended to the end so the agent always sees it freshest.
    state_context = f"[{state_id} 状态 · gate 第 {round_n} 轮]"
    turn_info = f"(本轮可用 {max_turns} 次工具调用，已用 0 次)"
    messages.append({"role": "user", "content": state_context})
    messages.append({"role": "user", "content": turn_info})

    for turn in range(max_turns):
        # Print thinking indicator
        print(f"     🤔 round {turn+1}/{max_turns}...", end="", flush=True)

        t0 = time.time()

        # Persist LLM input snapshot for observability
        if store is not None:
            try:
                store.append_llm_input_snapshot(
                    run_id=run_id,
                    session_id=role_id,
                    role_id=role_id,
                    state_id=state_id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    messages=[{"role": "system", "content": system}] + messages,
                    request={"tools": [t["function"]["name"] for t in tools]},
                    context_packet={"turn": turn, "max_turns": max_turns},
                )
            except Exception:
                pass

        try:
            resp_data = _call_llm_tools(system, messages, tools)
            dt = time.time() - t0
        except Exception as e:
            print(f" ❌ {e}")
            return {"value": "APPROVE", "reason": f"[fallback] LLM error: {e}", "tool_calls": tool_calls_made}

        # Check for tool calls
        tool_calls = resp_data.get("tool_calls", [])
        text_content = resp_data.get("content", "")

        # ── IMPORTANT: save assistant's response (with tool_calls) to message history ──
        # OpenAI/DeepSeek format requires: assistant(tool_calls) → tool(result) → ...
        assistant_msg = {"role": "assistant", "content": text_content or None}
        if tool_calls:
            # Store tool_calls in OpenAI format: [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}]
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
                    # Truncated or malformed JSON — report to LLM so it can continue from where it stopped
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
                    # Track empty-fail for loop detection
                    _empty_fails = _empty_fails + 1
                    _last_empty_tool = fn_name
                    continue

                # Empty-arg detection: if fn_args is empty AND the tool requires params
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
                    reason = fn_args.get("reason", f"[{role_id}] Decision via submit_decision")
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
                                (msg_id, run_id, state_id, role_id, json.dumps(send_to), json.dumps(send_to), json.dumps({r: True for r in send_to}), "targeted", "question", content, "delivered", now),
                            )
                            for r in send_to:
                                conn.execute(
                                    "INSERT INTO inboxes(run_id,role_id,state_id,message_id,read_status) VALUES(?,?,?,?,?)",
                                    (run_id, r, state_id, msg_id, "unread"),
                                )
                            conn.commit()
                        result = {"ok": True, "sent_to": send_to, "preview": content[:200]}
                        print(f"     💬 → {', '.join(send_to)}: {content[:60]}...")
                    tool_calls_made += 1
                    _empty_fails = 0
                elif fn_name == "agent_inbox_read":
                    # Read inbox from DB — already loaded as inbox_rows
                    if inbox:
                        inbox_preview = "\n".join(
                            f"  from {r.get('from_role', '?')}: {str(r.get('content', ''))[:120]}"
                            for r in inbox[-5:]
                        )
                        result = {"ok": True, "messages": len(inbox), "preview": inbox_preview}
                    else:
                        result = {"ok": True, "messages": 0, "preview": "(收件箱为空)"}
                    tool_calls_made += 1
                    _empty_fails = 0
                elif fn_name in ("memory_read", "memory_write", "skill_create", "skill_update",
                                 "agent_submit_decision", "agent_summarize", "human_clarifier"):
                    # Stub for universal tools that don't have modules yet
                    result = {"ok": True, "note": f"{fn_name} is available but not yet implemented"}
                    tool_calls_made += 1
                else:
                    print(f"     🔧 {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:80]})", end="")
                    result = execute_tool(fn_name, fn_args, role_id)
                    tool_calls_made += 1
                    ok = result.get("ok", False)
                    print(f" {'✅' if ok else '❌'}")

                ok = result.get("ok", False)  # Normalize for empty-arg detection below

                # Persist thinking event
                if store is not None:
                    try:
                        store.append_thinking_event(
                            run_id=run_id,
                            role_id=role_id,
                            state_id=state_id,
                            step_type=fn_name,
                            inputs=fn_args,
                            output=result,
                        )
                    except Exception:
                        pass

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
                        return {
                            "value": "REQUEST_CHANGES",
                            "reason": f"{fn_name} called with empty arguments {_empty_fails} times",
                            "tool_calls": tool_calls_made,
                        }
                else:
                    _empty_fails = 0

            if submit_dec:
                return submit_dec

            # Append ALL tool messages contiguously (DeepSeek requires this)
            # THEN append one turn info message
            for m in tool_msgs:
                messages.append(m)
            messages.append({
                "role": "user",
                "content": f"{state_context} (剩余 {max_turns - tool_calls_made}/{max_turns} 次工具调用)",
            })
        elif text_content:
            print(f" {dt:.1f}s → text response ({len(text_content)} chars)")
            # Check if text contains a decision marker
            import re
            dec_match = re.search(
                r'"(?:value|decision)"\s*:\s*"(APPROVE|REQUEST_CHANGES|BLOCKED)"',
                text_content,
            )
            if dec_match:
                val = dec_match.group(1)
                reason = text_content[:200].replace("\n", " ")
                print(f"     ✅ embedded decision: {val}")
                return {"value": val, "reason": reason, "tool_calls": tool_calls_made}
            # Otherwise treat as thinking and continue
            messages.append({"role": "assistant", "content": text_content[:1000]})
        else:
            # Empty response — might be thinking-only; continue
            print(f" {dt:.1f}s → empty response")
            continue

    # Max turns reached — auto-approve as fallback
    print(f"     ⏰ max turns ({max_turns}) reached, auto-approving")
    return {
        "value": "APPROVE",
        "reason": f"[{role_id}@{state_id}] max turns reached ({max_turns})",
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


def run_flow(goal: str, agent_ids: list[str], yaml_path: Path, run_name: str, agents: dict, output_dir: str = ""):
    """Flow engine: drive Hermes Flow state machine until completion. Not manager's job."""
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT
    os.environ["HERMES_WORKSPACE_ROOT"] = PROJECT_ROOT

    from hermes_flow.tools import flow_init, flow_step, flow_send, flow_decide
    from hermes_flow.run_paths import get_run_dir
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.schemas import RunStatus
    from hermes_flow.trace import SqliteTracer, set_tracer
    from hermes_flow.engine import advance_state as eng_advance

    result = flow_init(PROJECT_ROOT, str(yaml_path), run_name)
    if not result.get("ok"):
        print(f"❌ flow_init 失败: {result.get('error')}")
        print(f"   {result.get('details', [])}")
        failed_run_id = result.get("run_id", "")
        if failed_run_id:
            failed_dir = get_run_dir(failed_run_id, PROJECT_ROOT)
            if failed_dir.exists():
                import shutil
                shutil.rmtree(failed_dir, ignore_errors=True)
        sys.exit(1)

    run_id = result["run_id"]
    run_dir = get_run_dir(run_id, PROJECT_ROOT)
    store = RuntimeStore(run_dir)
    store.init_schema()

    # Load agent_specs for scope enforcement
    _agent_specs = store.load_agent_specs(run_id)

    set_tracer(SqliteTracer(store, run_id=run_id))
    conn = store.connect()

    # ── Load flow topology for overview ───────────────────────────────
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
        """Build a flow topology snapshot (round-invariant for cache)."""
        lines = ["## 流程全景", ""]
        _past = set()
        # Determine completed states from decisions
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

    # Track artifacts found across states for passing to next agent
    found_artifacts: dict[str, str] = {}

    # ── Flow engine loop ────────────────────────────────────────────
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

        for role_idx, role_id in enumerate(required_roles):
            # ── Multi-turn agent session ────────────────────────────
            info = agents.get(role_id, {})
            soul = info.get("soul", "")

            inbox_rows = conn.execute(
                "SELECT m.from_role, m.content FROM inboxes i JOIN messages m ON i.message_id=m.message_id WHERE i.run_id=? AND i.role_id=? ORDER BY m.created_at",
                (run_id, role_id)).fetchall()

            all_msgs = conn.execute(
                "SELECT from_role, content FROM messages ORDER BY rowid").fetchall()

            # Get tool schemas auto-generated from meta.yaml + tools/<id>/
            from tool_registry import get_agent_tools_schemas
            tool_schemas = get_agent_tools_schemas(role_id)
            print(f"  🤖 {role_id} ({len(tool_schemas)} tools)" + (" [审查者]" if role_idx > 0 else ""))

            # Set write/read scope env vars from agent_specs
            _spec = _agent_specs.get(role_id, {})
            _write_scope = _spec.get("write_scope", [])
            _read_scope = _spec.get("read_scope", [])
            os.environ["HERMES_WRITE_SCOPE"] = json.dumps(_write_scope)
            os.environ["HERMES_READ_SCOPE"] = json.dumps(_read_scope)
            # Pre-create workspace directories so tools work immediately
            for _d in _write_scope:
                Path(PROJECT_ROOT, _d).mkdir(parents=True, exist_ok=True)

            # For multi-actor gates, the first agent produces the artifact;
            # subsequent agents (reviewers) check it rather than re-producing it.
            _state_artifacts = state_dict.get("output_artifacts", [])
            is_reviewer = role_idx > 0 and len(required_roles) > 1
            if is_reviewer:
                # Reviewer prompt: read the artifact, check quality, decide
                _review_target = ", ".join(_state_artifacts) if _state_artifacts else "the output"
                soul = (
                    f"## 本阶段你的角色：审查者\n"
                    f"当前状态的产物（{_review_target}）已由 {required_roles[0]} 生成。"
                    f"你的任务是：读取产物文件，检查质量是否满足目标要求。"
                    f"如果合格 → 提交 APPROVE。如果发现问题 → 提交 REQUEST_CHANGES 并说明原因。"
                    f"你不需要重新生成产物，只做审查。\n\n"
                    f"{soul}"
                )

            # Run multi-turn session: think → tool → feedback → think → ... → decision
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

            # Product gate enforcement: verify current-state artifacts only.
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

            flow_decide(run_id, state_id, role_id, val, reason)

            if val in fail_vals:
                break

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

    # Find the skill whose agent set best overlaps with selected agents
    selected_set = set(agent_ids)
    best_match = None
    best_overlap = 0
    for skill_file in sorted(team_skills_dir.glob("*.md")):
        text = skill_file.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        fm = yaml_lib.safe_load(parts[1])
        team_agents = set(fm.get("agents", []))
        if not team_agents:
            continue
        overlap = len(team_agents & selected_set)
        # Pick the skill with highest agent overlap
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = (skill_file, fm)

    if best_match and best_overlap >= max(2, len(selected_set) * 0.6):
        skill_file, fm = best_match
        flow_topology = fm.get("flow", [])
        output_base = fm.get("output_base", "")
        print(f"  采用班底: {fm.get('name', skill_file.stem)} ({len(flow_topology)} 个状态, 匹配度 {best_overlap}/{len(selected_set)})")
    else:
        print(f"  ⚠️ 未找到匹配班底 (最佳: {best_overlap}/{len(selected_set)})")
        output_base = ""
    if not flow_topology:
        if len(agent_ids) == 1:
            # Single agent: one DONE state, no gate
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
