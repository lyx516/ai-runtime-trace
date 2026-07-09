"""Agent session — system prompt construction, session init, and turn loop.

This is the core of the agent execution: build a system prompt, init session
state, then run the multi-turn LLM ↔ tool loop until submit_decision or max
turns.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from hermes_flow.hooks import Hook, emit
from hermes_flow.schemas import AgentSessionState


# ═══════════════════════════════════════════════════════════════════════
#  System prompt builder
# ═══════════════════════════════════════════════════════════════════════

def _build_multi_turn_system_prompt(
    role_id: str, soul: str, goal: str,
    output_artifacts: list[str],
    tool_schemas: list[dict],
    write_scope: list[str] = None,
    flow_overview: str = "",
    team_lineup: str = "",
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

    # Read assigned skill METADATA — only names + descriptions, not full content
    # Agents must call skill_load() to load full content on demand
    skill_content = ""
    _skill_dir = Path(__file__).resolve().parent.parent / "shared" / "skills" / role_id
    _skill_meta_parts = []
    if _skill_dir.is_dir():
        for _sf in sorted(_skill_dir.glob("*.md")):
            with open(_sf, encoding="utf-8") as _f:
                _raw = _f.read()
            _desc = ""
            if _raw.startswith("---"):
                _yparts = _raw.split("---", 2)
                if len(_yparts) >= 3:
                    import yaml as _y2
                    _fm = _y2.safe_load(_yparts[1]) or {}
                    _desc = _fm.get("description", "")[:120]
            _skill_meta_parts.append(f"  skill_load('{_sf.stem}') — {_desc or _sf.stem}")
    if _skill_meta_parts:
        skill_content = "## 可用技能（调用 skill_load 加载完整内容）\n" + "\n".join(_skill_meta_parts)

    # Read trait-specific prompt
    from trait_loader import resolve_agent_trait_prompts
    import yaml as _yaml
    _meta_path = Path(__file__).resolve().parent.parent / "agents" / role_id / "meta.yaml"
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
    if team_lineup:
        parts.append(f"\n## 团队阵容\n{team_lineup}")
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
            "3. 完成后调用 submit_decision(APPROVE)。分配给其他角色的验证/审查/测试不属于你的职责范围",
            "",
        ])

    if _trait_prompt:
        parts.append(f"## 附加规则\n{_trait_prompt}\n")

    parts.extend([
        "## 可用工具",
        tool_text,
        "",
        "## 持久记忆",
        "- memory_read(key): 读取你之前存的经验",
        "- memory_write(key, value): 存储本次学到的经验，下次 run 可复用",
        "",
        "## 完成条件",
        "产出文件后，调用 **submit_decision** 提交。",
    ])
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════
#  Session state init
# ═══════════════════════════════════════════════════════════════════════

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
    # Build team lineup from agents dict
    _lineup_parts = []
    for aid, ainfo in sorted(agents.items()):
        if aid == "manager":
            continue
        _role = ainfo.get("role", "") or ainfo.get("display_name", aid)
        _mark = "👤 你" if aid == role_id else "   "
        _desc = ainfo.get("description", "")[:60]
        _lineup_parts.append(f"  {_mark} {aid} ({_role}) — {_desc}")
    team_lineup = "\n".join(_lineup_parts) if len(agents) > 1 else ""
    system = _build_multi_turn_system_prompt(
        role_id, soul, goal, output_artifacts, tool_schemas, write_scope,
        flow_overview=flow_overview,
        team_lineup=team_lineup,
    )

    # 2. Build initial messages
    messages = []
    if history:
        hist_lines = []
        for d in history[-10:]:
            c = str(d["content"] or "")[:200]
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

    # Auto-inject persisted memory for this agent
    try:
        from hermes_flow.memory import MemoryStore
        _mem = MemoryStore().list_keys(role_id)
        if _mem:
            _mem_lines = [f"- {e['key']}: {e['value'][:150]}" for e in _mem[-10:]]
            messages.append({"role": "user", "content": "## 你的持久记忆\n" + "\n".join(_mem_lines)})
    except Exception:
        pass

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


# ═══════════════════════════════════════════════════════════════════════
#  Agent session entry (idempotent + checkpoint resume)
# ═══════════════════════════════════════════════════════════════════════

def _run_agent_session(
    role_id: str, soul: str, goal: str, state_id: str, round_n: int,
    history: list, inbox: list, gate: dict, tool_schemas: list[dict],
    agents: dict, output_artifacts: list[str] = None,
    prev_artifacts: dict = None,
    store=None,
    run_id: str = "",
    write_scope: list[str] = None,
    flow_overview: str = "",
    clarify_fn=None,
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

    return _run_session_loop(state, store, run_id, agents, clarify_fn=clarify_fn)


# ═══════════════════════════════════════════════════════════════════════
#  agent_recall tool
# ═══════════════════════════════════════════════════════════════════════

def _handle_agent_recall(fn_args: dict, store, run_id: str) -> dict:
    """agent_recall tool — pure SQLite reads, Hermes session_search style.

    Five shapes inferred from query type, no mode parameter:
      overview    — run summary
      transitions — state path with retry detection
      decisions   — agent decisions, filterable by state/agent
      thinking    — tool call log, filterable by agent, paginated
      messages    — agent messages, filterable by state/agent, paginated
    """
    query = fn_args.get("query", "")
    agent = fn_args.get("agent", "") if isinstance(fn_args.get("agent"), str) else ""
    state = fn_args.get("state", "") if isinstance(fn_args.get("state"), str) else ""
    limit = min(int(fn_args.get("limit", 20) or 20), 50)
    offset = int(fn_args.get("offset", 0) or 0)

    conn = store.connect()

    try:
        if query == "overview":
            run_row = conn.execute(
                "SELECT status, flow_id, created_at FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not run_row:
                return {"ok": False, "error": "run not found"}
            dec_cnt = conn.execute("SELECT COUNT(*) as c FROM decisions WHERE run_id=?", (run_id,)).fetchone()["c"]
            trans_cnt = conn.execute("SELECT COUNT(*) as c FROM transitions WHERE run_id=?", (run_id,)).fetchone()["c"]
            msg_cnt = conn.execute("SELECT COUNT(*) as c FROM messages WHERE run_id=?", (run_id,)).fetchone()["c"]
            state_rows = conn.execute("SELECT state_id FROM states WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            agent_rows = conn.execute("SELECT DISTINCT role_id FROM decisions WHERE run_id=?", (run_id,)).fetchall()
            return {
                "ok": True, "query": "overview",
                "status": run_row["status"],
                "flow_id": run_row["flow_id"],
                "created_at": run_row["created_at"],
                "agents": [r["role_id"] for r in agent_rows],
                "states": [r["state_id"] for r in state_rows],
                "decision_count": dec_cnt,
                "transition_count": trans_cnt,
                "message_count": msg_cnt,
            }

        elif query == "transitions":
            rows = conn.execute(
                "SELECT from_state_id, to_state_id FROM transitions WHERE run_id=? ORDER BY rowid", (run_id,)
            ).fetchall()
            path = " → ".join([f"{r['from_state_id']}→{r['to_state_id']}" for r in rows])
            # Detect retries: same to_state appearing more than once
            to_counts: dict = {}
            for r in rows:
                to_counts[r["to_state_id"]] = to_counts.get(r["to_state_id"], 0) + 1
            retries = {k: v for k, v in to_counts.items() if v > 1}
            return {
                "ok": True, "query": "transitions",
                "path": path,
                "steps": [{"from": r["from_state_id"], "to": r["to_state_id"]} for r in rows],
                "total_steps": len(rows),
                "retry_states": retries or None,
            }

        elif query == "decisions":
            where = ["run_id = ?"]
            params: list = [run_id]
            if agent:
                where.append("role_id = ?"); params.append(agent)
            if state:
                where.append("state_id = ?"); params.append(state)
            sql = f"SELECT state_id, role_id, value, reason, created_at FROM decisions WHERE {' AND '.join(where)} ORDER BY rowid LIMIT ? OFFSET ?"
            params.extend([limit + 1, offset])
            rows = conn.execute(sql, params).fetchall()
            results = [{"state": r["state_id"], "agent": r["role_id"], "value": r["value"],
                         "reason": (r["reason"] or "")[:200], "at": r["created_at"]} for r in rows]
            has_more = len(results) > limit
            if has_more:
                results = results[:limit]
            return {"ok": True, "query": "decisions", "results": results, "count": len(results),
                    "has_more": has_more, "offset": offset, "limit": limit}

        elif query == "thinking":
            where = ["run_id = ?"]
            params = [run_id]
            if agent:
                where.append("role_id = ?"); params.append(agent)
            sql = f"SELECT role_id, state_id, step_type, output_json, created_at FROM thinking_events WHERE {' AND '.join(where)} ORDER BY rowid LIMIT ? OFFSET ?"
            params.extend([limit + 1, offset])
            rows = conn.execute(sql, params).fetchall()
            results = []
            for r in rows:
                ok_flag = "true" in (r["output_json"] or "").lower() if r["output_json"] else None
                results.append({"agent": r["role_id"], "state": r["state_id"], "tool": r["step_type"],
                                "ok": ok_flag, "at": r["created_at"]})
            has_more = len(results) > limit
            if has_more:
                results = results[:limit]
            return {"ok": True, "query": "thinking", "results": results, "count": len(results),
                    "has_more": has_more, "offset": offset, "limit": limit,
                    "message": f"Showing {len(results)} of {len(results) + offset}+ tool calls. Use offset={offset + limit} for next page." if has_more else "All results shown."}

        elif query == "messages":
            where = ["run_id = ?"]
            params = [run_id]
            if agent:
                where.append("from_role = ?"); params.append(agent)
            if state:
                where.append("state_id = ?"); params.append(state)
            sql = f"SELECT state_id, from_role, kind, content, created_at FROM messages WHERE {' AND '.join(where)} ORDER BY rowid LIMIT ? OFFSET ?"
            params.extend([limit + 1, offset])
            rows = conn.execute(sql, params).fetchall()
            results = [{"state": r["state_id"], "from": r["from_role"], "kind": r["kind"],
                         "content": (r["content"] or "")[:300], "at": r["created_at"]} for r in rows]
            has_more = len(results) > limit
            if has_more:
                results = results[:limit]
            return {"ok": True, "query": "messages", "results": results, "count": len(results),
                    "has_more": has_more, "offset": offset, "limit": limit}

        elif query == "baseline":
            kw = fn_args.get("goal_kw", "")
            like = f"%{kw}%" if kw else "%"
            rows = conn.execute(
                "SELECT run_id, summary, success_score, tool_stats, evaluated_at "
                "FROM run_performance WHERE summary LIKE ? AND success_score >= 40 ORDER BY evaluated_at DESC LIMIT 5",
                (like,),
            ).fetchall()
            if not rows:
                return {"ok": True, "query": "baseline", "results": [], "message": "No completed runs with baseline data yet."}
            import json as _json
            stats = []
            avg_seconds = 0.0
            avg_calls = 0.0
            for r in rows:
                ts = _json.loads(r["tool_stats"] or "{}")
                stats.append({
                    "run_id": r["run_id"][:12],
                    "outcome": ts.get("outcome", "?"),
                    "total_seconds": ts.get("total_seconds", 0),
                    "by_state": ts.get("by_state", {}),
                })
                avg_seconds += ts.get("total_seconds", 0)
                avg_calls += sum(
                    d.get("total", 0) for d in ts.get("by_state", {}).values()
                )
            n = len(stats)
            return {
                "ok": True, "query": "baseline", "results": stats,
                "avg_total_seconds": round(avg_seconds / n, 1) if n else 0,
                "avg_tool_calls": round(avg_calls / n, 1) if n else 0,
                "count": n,
                "message": f"Baseline from {n} completed runs. avg runtime={avg_seconds/n:.0f}s, avg tool_calls={avg_calls/n:.0f}.",
            }


        else:
            return {"ok": False, "error": f"Unknown recall query: '{query}'. Valid: overview, transitions, decisions, thinking, messages, baseline"}

    except Exception as e:
        return {"ok": False, "error": f"recall failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════
#  Session turn loop
# ═══════════════════════════════════════════════════════════════════════

def _run_session_loop(
    state: AgentSessionState,
    store,
    run_id: str,
    agents: dict | None = None,
    clarify_fn=None,
) -> dict:
    """Run agent turn loop from state.turn to state.max_turns.

    每轮:
      LLM call → tool execution → append results → append turn_info
      → emit TURN_END (checkpoint 在此)
      → submit_decision 时 emit SESSION_DECIDE + SESSION_DONE → return

    Agent loop 不直接调 store 持久化方法 — 全部通过 hook emit。
    """
    from tool_registry import execute_tool, format_tool_results_for_llm, DECISION_TOOL_SCHEMA
    from engine import llm_client
    from engine.llm_config import get_agent_model, load_config

    system = state.system_prompt
    messages = json.loads(state.messages_json)
    tools = json.loads(state.tools_json)
    max_turns = state.max_turns
    state_context = f"[{state.state_id} 状态 · gate 第 {state.round_n} 轮]"
    tool_calls_made = state.tool_calls_made
    _empty_fails = state.empty_fails
    _last_empty_tool = state.last_empty_tool

    # Resolve model for this agent
    _agents = agents or {}
    agent_model = get_agent_model(_agents, state.role_id)
    _cfg = load_config()

    for turn in range(state.turn, max_turns):
        print(f"     🤔 round {turn+1}/{max_turns}...", end="", flush=True)

        t0 = time.time()

        # ── LLM input snapshot (via hook) ────────────────────
        emit(Hook.LLM_DONE, {
            "run_id": run_id,
            "role_id": state.role_id,
            "state_id": state.state_id,
            "provider": _cfg.api_url,
            "model": agent_model,
            "messages": [{"role": "system", "content": system}] + messages,
            "request": {"tools": [t["function"]["name"] for t in tools]},
            "context_packet": {"turn": turn, "max_turns": max_turns},
        })

        try:
            resp_data = llm_client.call_llm_tools(system, messages, tools, model=agent_model)
            dt = time.time() - t0
        except Exception as e:
            print(f" ❌ {e}")
            emit(Hook.SESSION_DONE, {
                "run_id": run_id,
                "role_id": state.role_id,
                "state_id": state.state_id,
                "value": "REQUEST_CHANGES",
                "reason": f"[fallback] LLM error: {e}",
            })
            return {"value": "REQUEST_CHANGES", "reason": f"[fallback] LLM error: {e}", "tool_calls": tool_calls_made}

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
                elif fn_name == "skill_load":
                    _sn = fn_args.get("skill_name", "")
                    _skill_dir = Path(__file__).resolve().parent.parent / "shared" / "skills" / state.role_id
                    _found = None
                    if _skill_dir.is_dir():
                        for _sf in _skill_dir.glob("*.md"):
                            if _sf.stem == _sn:
                                _found = _sf
                                break
                    if _found:
                        _raw = _found.read_text(encoding="utf-8")
                        _body = _raw
                        if _raw.startswith("---"):
                            _yparts = _raw.split("---", 2)
                            _body = _yparts[2].strip() if len(_yparts) >= 3 else _raw
                        result = {"ok": True, "skill": _sn, "content": _body[:8000]}
                        print(f"     📚 skill_load({_sn}) → {_found.name} ({len(_body)}B)")
                    else:
                        result = {"ok": False, "error": f"skill '{_sn}' not found in shared/skills/"}
                    tool_calls_made += 1
                elif fn_name == "agent_recall":
                    result = _handle_agent_recall(fn_args, store, run_id)
                    print(f"     🧠 recall({fn_args.get('query','?')}, agent={fn_args.get('agent','-')}, state={fn_args.get('state','-')})")
                    tool_calls_made += 1
                elif fn_name == "memory_read":
                    from hermes_flow.memory import MemoryStore
                    _mval = MemoryStore().read(state.role_id, fn_args.get("key", ""))
                    result = {"ok": True, "value": _mval}
                    print(f"     📖 memory_read({fn_args.get('key','?')}) → {'found' if _mval else 'empty'}")
                    tool_calls_made += 1
                elif fn_name == "memory_write":
                    from hermes_flow.memory import MemoryStore
                    MemoryStore().write(state.role_id, fn_args.get("key", ""), fn_args.get("value", ""), run_id)
                    result = {"ok": True}
                    print(f"     💾 memory_write({fn_args.get('key','?')})")
                    tool_calls_made += 1
                elif fn_name == "clarify":
                    question = fn_args.get("question", "?")
                    choices = fn_args.get("choices", [])
                    print(f"     💬 clarify: {question[:80]}")
                    if not callable(clarify_fn):
                        result = {"ok": False, "error": "No stdin available for clarify"}
                    else:
                        answer = clarify_fn(question, choices)
                        tool_calls_made += 1
                        result = {"ok": True, "answer": answer, "question": question}
                        print(f"       → {answer[:80]}")
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

                # Empty-arg loop detection — track but let max_turns handle termination
                if not ok and not any(fn_args.values()):
                    _empty_fails = _empty_fails + 1
                    _last_empty_tool = fn_name
                    if _empty_fails >= 3 and _last_empty_tool == fn_name:
                        print(f"     ⚠️  repeated empty {fn_name} args ({_empty_fails}x) — will rely on max_turns")
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
            # LLM returned text instead of tool calls — prompt it to use submit_decision
            messages.append({"role": "assistant", "content": text_content[:1000]})
            messages.append({
                "role": "user",
                "content": "请使用 submit_decision 工具提交你的决策（value: APPROVE/REQUEST_CHANGES/BLOCKED，reason: 决策理由）。不要用纯文本回复决策。",
            })
        else:
            print(f" {dt:.1f}s → empty response")
            continue

    # Max turns reached
    print(f"     ⏰ max turns ({max_turns}) reached, returning REQUEST_CHANGES")
    emit(Hook.SESSION_DONE, {
        "run_id": run_id,
        "role_id": state.role_id,
        "state_id": state.state_id,
        "value": "REQUEST_CHANGES",
        "reason": f"[{state.role_id}@{state.state_id}] max turns reached ({max_turns})",
    })
    return {
        "value": "REQUEST_CHANGES",
        "reason": f"[{state.role_id}@{state.state_id}] max turns reached ({max_turns})",
        "tool_calls": tool_calls_made,
    }