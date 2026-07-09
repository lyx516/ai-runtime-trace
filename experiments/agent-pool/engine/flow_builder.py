"""Flow builder — manager agent selection + flow YAML generation."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

from engine.config import OUTPUT_DIR
from engine.agent_loader import load_team_skills
from engine.llm_client import call_llm, call_llm_tools
from engine.llm_config import get_agent_model


# ═══════════════════════════════════════════════════════════════════════
#  Phase 1: Manager selects agents + team skill
# ═══════════════════════════════════════════════════════════════════════

def manager_select_agents(goal: str, agents: dict) -> tuple[list[str], list[dict], str]:
    """Manager agent analyzes goal and selects appropriate agents + team skill.

    Returns (selected_agent_ids, flow_topology, output_base).
    flow_topology is the 'flow' array from the matched team skill (parsed YAML
    frontmatter), or a generated topology when no team skill is picked.
    output_base is the matched skill's output template (e.g. "output/{flow_id}").
    """
    team_skills = load_team_skills()
    _team_skill_map = {s["file"]: s for s in team_skills}

    # Build team skill listing — METADATA ONLY (name + description + members + state count)
    # Full doc body is loaded on demand via team_skill_load tool
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
        "\n## 可用班底技能（调用 team_skill_load 加载完整 flow + gate 设计指南）\n"
        + "\n".join(team_lines)
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

    system = f"""你是流程管理专家。根据用户目标，选择合适的 Agent 并生成完整的 flow 拓扑。

**如果任务描述中明确指定了团队组成或流程结构（如"必须使用 X+Y+Z"、"流程为 A→B→C"），你必须严格遵循。**

{team_skills_text}

## 响应格式

严格 JSON，不要任何其他文本：

{{
  "agents": ["id1", "id2", ...],
  "reason": "选择理由（简述任务特点 → 匹配逻辑）",
  "flow": [
    {{
      "state": "SPEC",
      "description": "编写规格文档",
      "actors": "spec-writer",
      "gate": {{"type": "product", "file": "spec.md", "pass": "PLAN", "fail": "SPEC", "max": 3}},
      "output_artifacts": ["spec.md"]
    }},
    ...
  ]
}}

flow 字段说明：
- actors: 用 "+" 连接多个 agent（如 "implementer+code-reviewer"），后者为审查者
- gate.type: "product"（文件门禁）、"decision"（人工审核）
- gate.file: product gate 要求的文件名
- gate.pass/fail: 状态转换目标
- gate.max: 最大轮次
- output_artifacts: 本状态产出文件列表

如果任务简单只需 1 个 agent，flow 可以只有 1 个 DONE 状态：
[{{"state": "DONE", "description": "...", "actors": "writer", "gate": {{"type": "decision", "pass": "DONE", "fail": "ABORT", "max": 3}}}}]"""

    # team_skill_load tool — lets Manager pull full flow + doc for a specific team on demand
    _team_load_tool = {
        "type": "function",
        "function": {
            "name": "team_skill_load",
            "description": "Load a team skill's full flow topology + gate design guide by file name. Call this when you need the detailed flow definition or gate design guidance for a specific team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Team skill file name (e.g. 'spec-team', 'quick-fix-team')",
                    },
                },
                "required": ["team_name"],
            },
        },
    }

    user = f"## 任务\n{goal}\n\n## Agent 池\n{agent_list}\n\n请选择班底和 Agent。如果需要某个班底的完整 flow 定义，调用 team_skill_load。"
    print("\n🤔 管理 Agent 正在分析任务...")
    manager_model = get_agent_model(agents, "manager")

    # Lightweight multi-turn loop: Manager can call team_skill_load a few times,
    # then must return final JSON (no tool_calls).
    messages = [{"role": "user", "content": user}]
    _max_tool_rounds = 4
    result = {}
    for _round in range(_max_tool_rounds + 1):
        resp = call_llm_tools(system, messages, [_team_load_tool], model=manager_model)
        tool_calls = resp.get("tool_calls") or []

        if not tool_calls:
            # Manager returned plain text — try to extract JSON (may be in ```json block or plain)
            content = resp.get("content", "{}")
            _extracted = content
            # Try ```json block first
            if "```json" in content:
                _parts = content.split("```json", 1)
                if len(_parts) > 1:
                    _extracted = _parts[1].split("```", 1)[0].strip()
            elif "{" in content and content.rstrip().endswith("}"):
                # Extract the outermost JSON object
                _start = content.index("{")
                _end = content.rindex("}")
                _extracted = content[_start:_end + 1]
            try:
                result = json.loads(_extracted)
            except Exception:
                try:
                    # One more try: some LLMs return trailing text after JSON
                    _end = _extracted.rindex("}")
                    result = json.loads(_extracted[:_end + 1])
                except Exception:
                    result = {}
            break

        # Execute tool calls
        messages.append({"role": "assistant", "content": resp.get("content", ""), "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            fn_args_raw = fn.get("arguments", "{}")
            try:
                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except Exception:
                fn_args = {}
            if fn_name == "team_skill_load":
                _tn = fn_args.get("team_name", "")
                _skill = _team_skill_map.get(_tn) or _team_skill_map.get(f"{_tn}.md")
                if _skill:
                    _flow_yaml = json.dumps(_skill["flow"], ensure_ascii=False, indent=2)
                    _doc = _skill.get("doc", "")[:2000]
                    _payload = f"## 班底: {_skill['name']}\n\n### flow 定义\n{_flow_yaml}\n\n### gate 设计指南\n{_doc}"
                else:
                    _payload = f"❌ 班底 '{_tn}' 不存在。可用: {', '.join(_team_skill_map.keys())}"
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": _payload})
                print(f"  📚 team_skill_load({_tn}) → {len(_payload)}B")

    selected = result.get("agents", [])
    reason = result.get("reason", "")

    valid = [a for a in selected if a in agents and a != "manager"]
    flow_topology = result.get("flow", [])

    if len(valid) < 1 or not flow_topology:
        # Report error back to manager for self-correction
        _err_parts = []
        if len(valid) < 1:
            _err_parts.append(f"agents 为空或所选 agent 不存在（selected={selected}）")
        if not flow_topology:
            _err_parts.append("flow 为空")
        _err_msg = "；".join(_err_parts)
        print(f"  ⚠️ Manager 响应无效: {_err_msg}")
        print(f"  🔄 要求 Manager 重新生成...")

        _retry_user = f"{user}\n\n## ❌ 上次响应错误\n{_err_msg}\n请修正后重新返回完整的 JSON，包含 agents 和 flow 字段。"
        result = call_llm(system, _retry_user, model=manager_model, temperature=0.3, max_tokens=4000)

    # Final fallback — only after retry also fails
    valid = [a for a in result.get("agents", []) if a in agents and a != "manager"]
    flow_topology = result.get("flow", []) or flow_topology

    if len(valid) < 1:
        print("  ❌ Manager 连续响应无效，中止")
        sys.exit(1)
    print(f"  选择了: {', '.join(valid)}")
    print(f"  理由: {reason}" if reason else "")
    print(f"  流程: {' → '.join(s.get('state','?') for s in flow_topology)}")
    return valid, flow_topology, ""


# ═══════════════════════════════════════════════════════════════════════
#  Phase 2: Generate Flow YAML
# ═══════════════════════════════════════════════════════════════════════

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

    # Sanitize: Manager LLM sometimes hallucinates product gates on IMPLEMENT/REVIEW.
    # These states should always be decision gates per all team skill templates.
    for sid in list(states.keys()):
        if sid in ("IMPLEMENT", "REVIEW"):
            gate = states[sid].get("gate", {})
            if gate.get("type") == "product":
                print(f"  ⚠️ Sanitized: {sid} product gate → decision gate (LLM hallucination)")
                states[sid]["gate"] = self_gate(
                    gate.get("required_roles", ["implementer", "code-reviewer"]),
                    "REVIEW" if sid == "IMPLEMENT" else "DONE",
                    "IMPLEMENT" if sid == "REVIEW" else sid,
                    4
                )
                # Clear output_artifacts — product gate artifact validation runs
                # independent of gate type in fsm.py; leaving stale artifacts here
                # causes the same "missing" failure loop.
                states[sid].pop("output_artifacts", None)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{flow_id}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml_lib.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return path