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
                  flow_topology: Optional[list] = None) -> Path:
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

def _build_multi_turn_system_prompt(
    role_id: str, soul: str, goal: str,
    output_artifacts: list[str],
    tool_schemas: list[dict],
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
            "2. 用 file_write 写入产物",
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
        role_id, soul, goal, output_artifacts, tool_schemas,
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

    # Inject turn info into the very first message so agent knows the limit
    turn_info = f"\n(本轮可用 {max_turns} 次工具调用，已用 0 次)"
    if messages:
        messages[-1]["content"] += turn_info
    else:
        messages.append({
            "role": "user",
            "content": turn_info.strip(),
        })

    for turn in range(max_turns):
        # Print thinking indicator
        print(f"     🤔 round {turn+1}/{max_turns}...", end="", flush=True)

        t0 = time.time()
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
                except json.JSONDecodeError:
                    fn_args = {}

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
                    if send_to and content:
                        print(f"     💬 → {send_to[0]}: {content[:60]}...")
                        tools_runner_dir = Path(__file__).resolve().parent
                        run_id = goal
                else:
                    print(f"     🔧 {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:80]})", end="")

                result = execute_tool(fn_name, fn_args, role_id)
                tool_calls_made += 1
                ok = result.get("ok", False)
                print(f" {'✅' if ok else '❌'}")

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
                    if _empty_fails >= 2 and _last_empty_tool == fn_name:
                        tool_msgs.append({
                            "role": "user",
                            "content": (
                                f"⚠️  You have called '{fn_name}' with empty arguments "
                                f"{_empty_fails} times and it failed each time. "
                                f"Stop retrying this call. Proceed with submit_decision "
                                f"or try a different approach."
                            ),
                        })
                        _empty_fails = 0
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
                "content": f"(剩余 {max_turns - tool_calls_made}/{max_turns} 次工具调用)",
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
        "max_tokens": max(300, min(4000, 32000 - total_chars // 4)),
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
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"DeepSeek API {e.code}: {err_body}") from e
    result = json.loads(resp.read())

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


def run_flow(goal: str, agent_ids: list[str], yaml_path: Path, run_name: str, agents: dict):
    """Flow engine: drive Hermes Flow state machine until completion. Not manager's job."""
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT
    os.environ["HERMES_WORKSPACE_ROOT"] = PROJECT_ROOT

    from hermes_flow.tools import flow_init, flow_step, flow_send, flow_decide
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

        for role_id in required_roles:
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
            print(f"  🤖 {role_id} ({len(tool_schemas)} tools)")

            # Run multi-turn session: think → tool → feedback → think → ... → decision
            result = _run_agent_session(
                role_id, soul, goal, state_id, cur_round,
                all_msgs, inbox_rows, gate, tool_schemas, agents,
                output_artifacts=state_dict.get("output_artifacts", []),
                prev_artifacts=found_artifacts if found_artifacts else None,
            )

            val = result.get("value", "APPROVE").upper()
            reason = result.get("reason", "")
            tool_count = result.get("tool_calls", 0)
            print(f"     ✅ {val} (after {tool_count} tool call(s))")

            # Product gate enforcement: verify output artifacts exist
            # Search recursively — agent may write to a subdirectory
            output_artifacts = state_dict.get("output_artifacts", [])
            if output_artifacts:
                for art_name in output_artifacts:
                    # Check project root first
                    art_path = Path(PROJECT_ROOT) / art_name
                    if art_path.exists() and art_path.stat().st_size > 0:
                        print(f"     📄 {art_name} ({art_path.stat().st_size} bytes) ✅")
                        found_artifacts[art_name] = str(art_path)
                        continue
                    # Search recursively as fallback
                    found = list(Path(PROJECT_ROOT).rglob(art_name))
                    found = [f for f in found if f.is_file() and f.stat().st_size > 0]
                    if found:
                        fp = str(found[0])
                        print(f"     📄 {art_name} → {found[0].relative_to(Path(PROJECT_ROOT))} ({found[0].stat().st_size} bytes) ✅")
                        found_artifacts[art_name] = fp
                    else:
                        print(f"     ⚠️  产物 {art_name} 未找到！降级为 REQUEST_CHANGES")
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
        print(f"  采用班底: {fm.get('name', skill_file.stem)} ({len(flow_topology)} 个状态, 匹配度 {best_overlap}/{len(selected_set)})")
    else:
        print(f"  ⚠️ 未找到匹配班底 (最佳: {best_overlap}/{len(selected_set)})")
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
    yaml_path = generate_yaml(goal, agent_ids, run_name, agents, flow_topology)
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

    # Phase 4: Manager records decision pattern for future reference
    pattern = f"## 团队搭配经验\n目标: {goal[:80]} | 团队: {', '.join(agent_ids)} | 班底: 自动决策"
    from agent_tools import memory_write
    memory_write("manager", pattern, mode="append")
    print(f"  ✅ manager: 决策模式已记录到 Memory.md")


if __name__ == "__main__":
    main()
