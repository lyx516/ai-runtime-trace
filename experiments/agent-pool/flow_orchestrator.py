#!/usr/bin/env python3
"""
Flow Orchestrator — AI-driven multi-agent flow generator.

Manager agent calls this via terminal tool:
    python experiments/agent-pool/flow_orchestrator.py list
    python experiments/agent-pool/flow_orchestrator.py generate <goal> --agents designer,implementer,reviewer
    python experiments/agent-pool/flow_orchestrator.py run <yaml_path>

The manager agent does NOT modify this file. It calls it as a CLI tool.
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = "/Users/liyuxuan/ai-runtime-trace"
POOL_PATH = Path(PROJECT_ROOT) / "experiments" / "agent-pool" / "pool.yaml"
OUTPUT_DIR = Path(PROJECT_ROOT) / "experiments" / "agent-pool" / "generated"


def _load_pool() -> dict[str, Any]:
    """Load the agent pool YAML."""
    import yaml
    if not POOL_PATH.exists():
        print(json.dumps({"ok": False, "error": f"Pool not found: {POOL_PATH}"}))
        sys.exit(1)
    with open(POOL_PATH) as f:
        return yaml.safe_load(f)


def cmd_list(_args: argparse.Namespace | None = None) -> None:
    """List all agents in the pool with their capabilities."""
    pool = _load_pool()
    agents = pool.get("agents", {})
    result = []
    for aid, info in agents.items():
        result.append({
            "agent_id": aid,
            "name": info.get("display_name", aid),
            "role": info.get("default_meta_role", ""),
            "soul_summary": info.get("soul", "")[:100],
            "skills": info.get("skills", []),
            "toolsets": info.get("toolsets", []),
            "description": info.get("description", ""),
        })
    print(json.dumps({"ok": True, "agents": result}, indent=2, ensure_ascii=False))


def cmd_generate(goal: str, agent_ids: list[str], run_name: str = "") -> None:
    """
    Generate a flow YAML based on a goal and selected agents.
    
    The manager agent passes:
      --goal "设计一个向量数据库" --agents designer,critic,implementer,reviewer
    
    This function designs an appropriate flow topology based on the agent roles.
    """
    pool = _load_pool()
    agents_in_pool = pool.get("agents", {})

    # Validate all requested agents exist
    missing = [a for a in agent_ids if a not in agents_in_pool]
    if missing:
        print(json.dumps({"ok": False, "error": f"Unknown agents: {missing}"}))
        sys.exit(1)

    selected = {aid: agents_in_pool[aid] for aid in agent_ids}

    # Detect roles for flow topology design
    roles = {aid: info.get("default_meta_role", "") for aid, info in selected.items()}
    has_designer = "designer" in roles.values()
    has_implementer = "implementer" in roles.values()
    has_reviewer = "reviewer" in roles.values()
    has_critic = "critic" in roles.values()
    has_researcher = "researcher" in roles.values()
    has_mediator = "mediator" in roles.values()
    has_decider = "decider" in roles.values()
    has_tester = "tester" in roles.values()
    has_writer = "writer" in roles.values()

    # ── Build flow YAML based on roles ──────────────────────────────────
    flow_id = f"auto-{uuid.uuid4().hex[:8]}"
    yaml_data = {
        "flow_id": flow_id,
        "name": run_name or goal[:60],
        "version": 1,
        "initial_state_id": "",
        "terminal_state_ids": ["DONE", "ABORT"],
        "agents": {},
        "states": {},
    }

    # Map agent_id → role info for YAML
    for aid, info in selected.items():
        yaml_data["agents"][aid] = {
            "profile_name": f"pool-{aid}",
            "soul": info.get("soul", ""),
            "skills": info.get("skills", []),
            "toolsets": info.get("toolsets", []),
            "memory_mode": "run_isolated",
            "read_scope": [],
            "write_scope": [f"experiments/agent-pool/output/{flow_id}/"],
        }

    # ── Design flow topology ────────────────────────────────────────────
    # The topology depends on which agent roles are selected.
    # Priority: designer/implementer/reviewer core, with optional critic/mediator debate.

    states = {}
    state_order = []
    terminal_ids = ["DONE", "ABORT"]

    # Check if debate flow (designer + critic + mediator + decider pattern)
    is_debate = has_critic or has_mediator or has_decider

    if has_researcher:
        # Research phase first
        researchers = [aid for aid, r in roles.items() if r == "researcher"]
        state_id = "RESEARCH"
        states[state_id] = _make_state(
            state_id, "调研和收集信息", actors=researchers,
            gate=self_gate(researchers, on_pass="DESIGN")
        )
        state_order.append(state_id)

    # DESIGN phase
    designers = [aid for aid, r in roles.items() if r == "designer"]
    implementers = [aid for aid, r in roles.items() if r == "implementer"]
    reviewers = [aid for aid, r in roles.items() if r in ("reviewer", "tester")]
    critics = [aid for aid, r in roles.items() if r == "critic"]

    if designers:
        state_id = "DESIGN"
        if is_debate:
            states[state_id] = _make_state(
                state_id, goal, actors=designers,
                gate=self_gate(designers, on_pass="CRITIQUE")
            )
        else:
            states[state_id] = _make_state(
                state_id, goal, actors=designers,
                gate=self_gate(designers, on_pass="IMPLEMENT")
            )
        state_order.append(state_id)

    # CRITIQUE phase (debate)
    if is_debate and critics:
        state_id = "CRITIQUE"
        next_state = "REVISION"
        if has_mediator:
            next_state = "MEDIATE"
        elif has_decider:
            next_state = "FINAL_DECISION"
        states[state_id] = _make_state(
            state_id, "审查设计师方案，提出批评", actors=critics,
            gate=_make_gate(
                required_roles=critics,
                pass_values=["APPROVE"],
                fail_values=["REQUEST_CHANGES"],
                on_pass=next_state,
                on_fail="REVISION",
                max_rounds=3,
            )
        )
        state_order.append(state_id)

        # REVISION phase
        revision_state = "REVISION"
        states[revision_state] = _make_state(
            revision_state, "回应批评，修改方案", actors=designers,
            gate=self_gate(designers, on_pass="CRITIQUE", on_fail="MEDIATE", max_rounds=3)
        )
        state_order.append(revision_state)

        # MEDIATE phase
        if has_mediator:
            mediators = [aid for aid, r in roles.items() if r == "mediator"]
            state_id = "MEDIATE"
            states[state_id] = _make_state(
                state_id, "调解双方分歧，提出折中方案", actors=mediators,
                gate=self_gate(mediators, on_pass="FINAL_DECISION", on_fail="ABORT", max_rounds=2)
            )
            state_order.append(state_id)

        # FINAL_DECISION phase
        if has_decider:
            deciders = [aid for aid, r in roles.items() if r == "decider"]
            state_id = "FINAL_DECISION"
            states[state_id] = _make_state(
                state_id, "阅读全部讨论，做出最终决策", actors=deciders,
                gate=self_gate(deciders, on_pass="DONE", on_fail="ABORT", max_rounds=2)
            )
            state_order.append(state_id)
        else:
            state_order.append("DONE")

    else:
        # Simple flow: DESIGN → IMPLEMENT → REVIEW → DONE
        if implementers:
            impl_next = "REVIEW" if reviewers else "DONE"
            state_id = "IMPLEMENT"
            states[state_id] = _make_state(
                state_id, "根据设计实现代码", actors=implementers,
                gate=self_gate(implementers, on_pass=impl_next, on_fail="IMPLEMENT", max_rounds=3)
            )
            state_order.append(state_id)

        if reviewers:
            state_id = "REVIEW"
            if has_writer:
                next_state = "DOCUMENT"
            else:
                next_state = "DONE"
            states[state_id] = _make_state(
                state_id, "审查实现代码", actors=reviewers,
                gate=_make_gate(
                    required_roles=reviewers,
                    pass_values=["APPROVE"],
                    fail_values=["REQUEST_CHANGES"],
                    on_pass=next_state,
                    on_fail="IMPLEMENT",
                    max_rounds=3,
                )
            )
            state_order.append(state_id)

        # DOCUMENT phase (if writer present)
        if has_writer:
            writers = [aid for aid, r in roles.items() if r == "writer"]
            state_id = "DOCUMENT"
            states[state_id] = _make_state(
                state_id, "编写文档和README", actors=writers,
                gate=self_gate(writers, on_pass="DONE")
            )
            state_order.append(state_id)

    # Terminal states
    for tid in terminal_ids:
        states[tid] = {
            "terminal": True,
            "actors": [],
        }
        if tid not in state_order:
            state_order.append(tid)

    # Set initial state
    yaml_data["initial_state_id"] = state_order[0] if state_order else "DONE"

    # Build states in order
    yaml_data["states"] = {}
    for sid in state_order:
        if sid in states:
            yaml_data["states"][sid] = states[sid]

    # ── Write YAML ──────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yaml_path = OUTPUT_DIR / f"{flow_id}.yaml"
    import yaml as yaml_lib
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml_lib.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    result = {
        "ok": True,
        "flow_id": flow_id,
        "yaml_path": str(yaml_path),
        "initial_state": yaml_data["initial_state_id"],
        "agent_count": len(selected),
        "state_count": len(states),
        "state_order": state_order,
        "agents": list(selected.keys()),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_run(yaml_path: str, run_name: str = "") -> None:
    """Call flow_init then start RuntimeLoop (subprocess mode)."""
    sys.path.insert(0, PROJECT_ROOT)
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT

    from hermes_flow.tools import flow_init
    from hermes_flow.runtime_loop import RuntimeLoop
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.trace import SqliteTracer, set_tracer

    # Resolve path
    path = Path(yaml_path)
    if not path.is_absolute():
        path = Path(PROJECT_ROOT) / yaml_path

    result = flow_init(
        project_root=PROJECT_ROOT,
        flow_path=str(path),
        run_name=run_name,
    )
    if not result.get("ok"):
        print(json.dumps({"ok": False, "error": result.get("error", "flow_init failed")}))
        sys.exit(1)

    run_id = result["run_id"]
    run_dir = Path(PROJECT_ROOT) / ".hermes-flow" / "runs" / run_id
    store = RuntimeStore(run_dir)
    store.init_schema()
    set_tracer(SqliteTracer(store, run_id=run_id))

    # Set up LLM env for agent subprocesses
    os.environ["OPENAI_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")
    os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"
    os.environ["AGENT_LLM_MODEL"] = "deepseek-chat"

    loop = RuntimeLoop(
        run_id=run_id,
        store=store,
        tick_interval=1.0,
        spawn_mode="subprocess",
    )

    start = time.time()
    loop.start()
    elapsed = time.time() - start

    conn = store.connect()
    status = conn.execute("SELECT status, current_state_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    decisions = conn.execute("SELECT state_id, role_id, value FROM decisions ORDER BY rowid").fetchall()
    transitions = conn.execute("SELECT from_state_id, to_state_id FROM transitions ORDER BY rowid").fetchall()

    print(json.dumps({
        "ok": True,
        "run_id": run_id,
        "elapsed_seconds": round(elapsed, 1),
        "final_status": status["status"] if status else "unknown",
        "final_state": status["current_state_id"] if status else "unknown",
        "decisions": [dict(d) for d in decisions],
        "transitions": [dict(t) for t in transitions],
    }, indent=2, ensure_ascii=False))


def _make_state(state_id: str, description: str, actors: list[str],
                gate: dict | None = None) -> dict:
    s = {
        "description": description,
        "actors": actors,
    }
    if gate:
        s["gate"] = gate
    return s


def self_gate(roles: list[str], on_pass: str, on_fail: str = "",
              max_rounds: int = 1) -> dict:
    """Simple gate where the role approves and passes."""
    return _make_gate(
        required_roles=roles,
        pass_values=["APPROVE"],
        fail_values=["REQUEST_CHANGES"] if on_fail else [],
        on_pass=on_pass,
        on_fail=on_fail,
        max_rounds=max_rounds,
    )


def _make_gate(required_roles: list[str], pass_values: list[str],
               fail_values: list[str], on_pass: str,
               on_fail: str = "", on_blocked: str = "",
               max_rounds: int = 0) -> dict:
    gate = {
        "type": "decision",
        "required_roles": required_roles,
        "pass_values": pass_values,
        "fail_values": fail_values,
        "blocked_values": ["BLOCKED"],
        "on_pass": on_pass,
    }
    if on_fail:
        gate["on_fail"] = on_fail
        gate["max_rounds"] = max_rounds if max_rounds > 0 else 3
    if on_blocked:
        gate["on_blocked"] = on_blocked
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description="Flow Orchestrator CLI")
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser("list", help="List all agents in the pool")
    p_list.set_defaults(func=cmd_list)

    # generate
    p_gen = sub.add_parser("generate", help="Generate flow YAML from goal + agents")
    p_gen.add_argument("goal", help="The task goal / description")
    p_gen.add_argument("--agents", required=True, help="Comma-separated agent IDs")
    p_gen.add_argument("--name", default="", help="Optional run name")
    p_gen.set_defaults(func=lambda a: cmd_generate(a.goal, a.agents.split(","), a.name))

    # run
    p_run = sub.add_parser("run", help="Run a generated flow YAML")
    p_run.add_argument("yaml_path", help="Path to the flow YAML")
    p_run.add_argument("--name", default="", help="Optional run name")
    p_run.set_defaults(func=lambda a: cmd_run(a.yaml_path, a.name))

    # generate-and-run (convenience)
    p_gr = sub.add_parser("go", help="Generate AND run in one command")
    p_gr.add_argument("goal", help="The task goal")
    p_gr.add_argument("--agents", required=True, help="Comma-separated agent IDs")
    p_gr.add_argument("--name", default="", help="Optional run name")
    p_gr.set_defaults(func=lambda a: _generate_and_run(a.goal, a.agents, a.name))

    # debate (autonomous debate flow with real LLM prompts)
    p_db = sub.add_parser("debate", help="Generate + run a debate flow autonomously (direct DeepSeek API)")
    p_db.add_argument("goal", help="The task goal")
    p_db.add_argument("--agents", required=True, help="Comma-separated agent IDs")
    p_db.add_argument("--name", default="", help="Optional run name")
    p_db.add_argument("--model", default="deepseek-chat", help="LLM model")
    p_db.set_defaults(func=lambda a: cmd_debate(a.goal, a.agents, a.name, a.model))

    ns = parser.parse_args()
    if ns.command:
        ns.func(ns)
    else:
        parser.print_help()


def cmd_debate(goal: str, agents_str: str, name: str, model: str = "deepseek-chat") -> None:
    """Autonomous debate flow: generate YAML → create run → drive debate via DeepSeek API → report."""
    import urllib.request
    import time
    from pathlib import Path

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(json.dumps({"ok": False, "error": "DEEPSEEK_API_KEY not set"}))
        sys.exit(1)

    # ── 1. Generate flow YAML inline (not via cmd_generate to avoid flow_id mismatch) ──
    pool = _load_pool()
    agent_ids = agents_str.split(",")
    agent_ids = [a.strip() for a in agent_ids if a.strip() in pool.get("agents", {})]
    if not agent_ids:
        print(json.dumps({"ok": False, "error": "No valid agents specified"}))
        sys.exit(1)

    flow_id = f"auto-{uuid.uuid4().hex[:8]}"
    yaml_path = OUTPUT_DIR / f"{flow_id}.yaml"
    run_name = name or goal[:60]

    # Generate YAML inline (same logic as cmd_generate but with controlled flow_id)
    import yaml as yaml_lib
    agents_in_pool = pool.get("agents", {})
    selected = {aid: agents_in_pool[aid] for aid in agent_ids}
    roles = {aid: info.get("default_meta_role", "") for aid, info in selected.items()}
    has_designer = "designer" in roles.values()
    has_critic = "critic" in roles.values()
    has_mediator = "mediator" in roles.values()
    has_decider = "decider" in roles.values()

    yaml_data = {
        "flow_id": flow_id,
        "name": run_name,
        "version": 1,
        "initial_state_id": "",
        "terminal_state_ids": ["DONE", "ABORT"],
        "agents": {},
        "states": {},
    }
    for aid, info in selected.items():
        yaml_data["agents"][aid] = {
            "profile_name": f"pool-{aid}",
            "soul": info.get("soul", ""),
            "skills": info.get("skills", []),
            "toolsets": info.get("toolsets", []),
            "memory_mode": "run_isolated",
            "read_scope": [],
            "write_scope": [f"experiments/agent-pool/output/{flow_id}/"],
        }

    is_debate = has_critic or has_mediator or has_decider
    states = {}
    state_order = []

    # DESIGN
    designers = [aid for aid, r in roles.items() if r == "designer"]
    critics = [aid for aid, r in roles.items() if r == "critic"]
    if designers:
        sid = "DESIGN"
        if is_debate:
            states[sid] = _make_state(sid, goal, actors=designers, gate=self_gate(designers, on_pass="CRITIQUE"))
        else:
            states[sid] = _make_state(sid, goal, actors=designers, gate=self_gate(designers, on_pass="DONE"))
        state_order.append(sid)

    # CRITIQUE / REVISION / MEDIATE / DECIDE debate chain
    if is_debate and critics:
        sid = "CRITIQUE"
        next_ok = "MEDIATE" if has_mediator else ("FINAL_DECISION" if has_decider else "REVISION")
        states[sid] = _make_state(sid, "审查方案，指出问题", actors=critics,
            gate=_make_gate(critics, ["APPROVE"], ["REQUEST_CHANGES"], on_pass=next_ok, on_fail="REVISION", max_rounds=3))
        state_order.append(sid)

        sid = "REVISION"
        states[sid] = _make_state(sid, "回应批评，修改方案", actors=designers,
            gate=self_gate(designers, on_pass="CRITIQUE", on_fail="MEDIATE", max_rounds=3))
        state_order.append(sid)

        if has_mediator:
            meds = [aid for aid, r in roles.items() if r == "mediator"]
            sid = "MEDIATE"
            states[sid] = _make_state(sid, "调解分歧，提出折中", actors=meds,
                gate=self_gate(meds, on_pass="FINAL_DECISION", on_fail="ABORT", max_rounds=2))
            state_order.append(sid)

        if has_decider:
            decs = [aid for aid, r in roles.items() if r == "decider"]
            sid = "FINAL_DECISION"
            states[sid] = _make_state(sid, "阅读全部讨论，做最终决策", actors=decs,
                gate=self_gate(decs, on_pass="DONE", on_fail="ABORT", max_rounds=2))
            state_order.append(sid)

    # Terminal states
    for tid in ["DONE", "ABORT"]:
        if tid not in states:
            states[tid] = {"terminal": True, "actors": []}
        if tid not in state_order:
            state_order.append(tid)

    yaml_data["initial_state_id"] = state_order[0] if state_order else "DONE"
    yaml_data["states"] = {sid: states[sid] for sid in state_order}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml_lib.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(json.dumps({"ok": True, "flow_id": flow_id, "yaml_path": str(yaml_path), "state_order": state_order}))

    # ── 2. Create run ─────────────────────────────────────────────────
    sys.path.insert(0, PROJECT_ROOT)
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = PROJECT_ROOT
    from hermes_flow.tools import flow_init, flow_step, flow_send
    from hermes_flow.storage import RuntimeStore
    from hermes_flow.schemas import Decision, RunStatus
    from hermes_flow.trace import SqliteTracer, set_tracer, NoOpTracer

    result = flow_init(
        project_root=PROJECT_ROOT,
        flow_path=str(yaml_path),
        run_name=run_name,
    )
    if not result.get("ok"):
        print(json.dumps({"ok": False, "error": result.get("error", "flow_init failed")}))
        sys.exit(1)

    run_id = result["run_id"]
    run_dir = Path(PROJECT_ROOT) / ".hermes-flow" / "runs" / run_id
    store = RuntimeStore(run_dir)
    store.init_schema()
    set_tracer(SqliteTracer(store, run_id=run_id))

    # ── 3. Debate loop ────────────────────────────────────────────────
    base_url = "https://api.deepseek.com"
    conn = store.connect()

    def _call_llm(system: str, prompt: str) -> dict:
        """Call DeepSeek API, return parsed decision."""
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 500,
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        resp = urllib.request.urlopen(req, timeout=60)
        content = json.loads(resp.read())["choices"][0]["message"]["content"].strip()
        # Parse JSON from response
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{[^}]+\}', content)
            if m:
                return json.loads(m.group())
            return {"value": "APPROVE", "reason": content[:200]}

    def _insult_role(role_id: str) -> str:
        """Generate a debate-instigating system prompt fragment."""
        prompts = {
            "designer": "你是一位激进的架构师。你的方案必须是最优的，你不轻易让步。引用论文和数据支撑你的论点。",
            "critic": "你是一位尖锐的批评者。你的工作是指出所有方案的漏洞和缺陷。你坚决反对平庸的方案，即使对方让步你也要踩一脚表示这是你的施舍。",
            "mediator": "你是一位中立的技术总监。你认可双方论点中的合理之处，提出融合双方优点的折中方案。",
            "decider": "你是最终决策者。你引用所有参与者的观点，说明你采纳了什么、拒绝了什么以及原因。",
            "researcher": "你是一位严谨的研究员。你引用具体的数据、论文和行业实践来支撑你的结论。",
            "implementer": "你是一位务实的工程师。你关注方案的可实现性和工程成本。",
            "reviewer": "你是一位严格的审查者。你检查边界情况、错误处理和性能瓶颈。",
        }
        return prompts.get(role_id, "你是一位专业的技术人员，基于数据和逻辑做判断。")

    print(f"\n{'='*60}")
    print(f"🏁 辩论启动: {run_id}")
    print(f"🎯 目标: {goal}")
    print(f"👥 Agent: {', '.join(agent_ids)}")
    print(f"{'='*60}\n")

    all_decisions = []
    max_rounds_per_state = {"CRITIQUE": 3, "REVISION": 3, "MEDIATE": 2, "FINAL_DECISION": 2}
    round_counters: dict[str, int] = {}

    while True:
        # Load current state
        row = conn.execute("SELECT status, current_state_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            break
        status_str, state_id = row["status"], row["current_state_id"]
        status_enum = RunStatus(status_str)

        if status_enum in (RunStatus.COMPLETED, RunStatus.ABORTED):
            print(f"\n{'='*60}")
            print(f"✅ 辩论完成！最终状态: {status_enum.value} @ {state_id}")
            break

        # Load state definition
        srow = conn.execute("SELECT state_json FROM states WHERE run_id=? AND state_id=?", (run_id, state_id)).fetchone()
        if not srow:
            print(f"State {state_id} not found, aborting")
            break
        state_dict = json.loads(srow["state_json"])
        actors = state_dict.get("actors", [])
        gate = state_dict.get("gate", {})

        # Handle states with no gate (unconditional transitions)
        if not gate:
            from hermes_flow.engine import advance_state
            advance_state(run_id, state_id, state_dict.get("transitions", [{}])[0].get("target_state_id", "DONE"), "auto", 1, store)
            continue

        required_roles = gate.get("required_roles", [])
        pass_vals = gate.get("pass_values", ["APPROVE"])
        fail_vals = gate.get("fail_values", [])
        on_pass = gate.get("on_pass", "DONE")
        on_fail = gate.get("on_fail", "")
        max_r = gate.get("max_rounds", 3)

        # Track round
        round_counters[state_id] = round_counters.get(state_id, 0) + 1
        current_round = round_counters[state_id]
        print(f"\n── [{state_id}] Round {current_round} — Actors: {actors}")

        # Check exhaustion
        if current_round > max_r and on_fail:
            print(f"  ⚠️ Max rounds ({max_r}) exceeded, routing to {on_fail}")
            from hermes_flow.engine import advance_state
            advance_state(run_id, state_id, on_fail, f"max_rounds_exceeded ({current_round})", current_round, store)
            continue

        for role_id in required_roles:
            # Find agent info in pool
            agent_info = pool.get("agents", {}).get(role_id, {})
            soul = agent_info.get("soul", f"You are a {role_id}.")

            # Read inbox messages for this role
            inbox_rows = conn.execute(
                "SELECT m.from_role, m.content, m.kind, m.created_at FROM inboxes i JOIN messages m ON i.message_id=m.message_id WHERE i.run_id=? AND i.role_id=? ORDER BY m.created_at",
                (run_id, role_id),
            ).fetchall()

            # Read all discussion history
            all_msgs = conn.execute(
                "SELECT from_role, substr(content,1,200) FROM messages ORDER BY rowid"
            ).fetchall()

            # Build the prompt
            inbox_text = "\n".join([f"  从 {r['from_role']}: {r['content']}" for r in inbox_rows]) if inbox_rows else "  (空)"
            history_text = "\n".join([f"  [{i+1}] {r['from_role']}: {r['substr(content,1,200)']}" for i, r in enumerate(all_msgs)]) if all_msgs else "  (无)"

            system_prompt = f"""{_insult_role(role_id)}

你的身份: {role_id}
你的性格: {soul[:300]}

响应格式（严格 JSON）:
{{"value": "APPROVE|REQUEST_CHANGES|BLOCKED", "reason": "你的理由", "send_to": ["recipient_role"], "message": "你想发给对方的消息（留空字符串则不发送）"}}

- APPROVE: 你同意当前方案
- REQUEST_CHANGES: 你要求修改（仅 critic 可用）
- BLOCKED: 你阻止该方案
- send_to: 你想把 message 发给谁（设计师/批评者/调解者/决策者）
- message: 你想说的话（用于辩论）

你必须在发送消息和提交决策之间做出权衡。发送消息可以展开讨论，但最终需要提交决策来推进流程。"""

            user_prompt = f"""## 辩论上下文

**当前状态**: {state_id}（第 {current_round} 轮）
**目标**: {goal}

## 完整的讨论历史
{history_text}

## 你的收件箱
{inbox_text}

## Gate 条件
- 你需要提交的值: {pass_vals} (通过) / {fail_vals} (拒绝)
- 如果通过: → {on_pass}
- 如果拒绝: → {on_fail}
- 最大轮数: {max_r}

## 你的任务
1. 阅读讨论历史和收件箱
2. 如果你有话要说，设置 "send_to" 和 "message" 来发送消息
3. 提交你的决策值 (value)
4. 用 "reason" 解释你的理由

**记住**: 如果你是批评者(critic)，你应该质疑和挑战！如果你是设计师(designer)，你应捍卫你的方案但可以在有数据支撑时让步！"""

            print(f"\n  🤖 调用 LLM [{role_id}]...")
            llm_start = time.time()
            try:
                response = _call_llm(system_prompt, user_prompt)
                llm_elapsed = time.time() - llm_start
                print(f"     ⏱ {llm_elapsed:.1f}s → {response.get('value', '?')}")

                value = response.get("value", "APPROVE").upper()
                reason = response.get("reason", "")
                send_to = response.get("send_to", [])
                message = response.get("message", "")

                # Send message if provided
                if message and send_to:
                    from hermes_flow.tools import flow_send
                    msg_result = flow_send(
                        run_id=run_id, state_id=state_id,
                        from_role=role_id,
                        intended_recipients=send_to,
                        kind="debate",
                        content=message,
                    )
                    if msg_result.get("ok"):
                        print(f"     💬 消息 -> {send_to}: {message[:60]}...")
                    else:
                        print(f"     ⚠️ 消息投递失败: {msg_result.get('error', '')}")

                # Submit decision
                from hermes_flow.tools import flow_decide
                dec_result = flow_decide(
                    run_id=run_id, state_id=state_id,
                    role_id=role_id, value=value,
                    reason=reason,
                )
                if dec_result.get("ok"):
                    all_decisions.append({"role": role_id, "state": state_id, "value": value, "reason": reason[:80]})
                    print(f"     ✅ 决策提交: {value}")

                # If REQUEST_CHANGES, break early and advance
                if value in fail_vals:
                    break

            except Exception as e:
                print(f"     ❌ LLM调用失败: {e}")
                # Fall back to auto-approve
                from hermes_flow.tools import flow_decide
                flow_decide(run_id=run_id, state_id=state_id, role_id=role_id, value="APPROVE", reason=f"Auto-approve (LLM failed: {e})")

        # Advance state
        print(f"  🔄 推进 state...")
        step_result = flow_step(run_id=run_id)
        if step_result.get("ok", False):
            print(f"     → {step_result.get('from_state')} → {step_result.get('to_state')}")
        else:
            print(f"     ⚠️ 无转换 (gate未满足): {step_result.get('error', 'pending')}")
            break

    # ── 4. Results ────────────────────────────────────────────────────
    final = conn.execute("SELECT status, current_state_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    trans = conn.execute("SELECT from_state_id, to_state_id FROM transitions ORDER BY rowid").fetchall()
    msgs = conn.execute("SELECT from_role, substr(content,1,60) FROM messages ORDER BY rowid").fetchall()

    print(f"\n{'='*60}")
    print(f"📊 辩论结果")
    print(f"{'='*60}")
    print(f"Run ID: {run_id}")
    print(f"状态:   {final['status']} @ {final['current_state_id']}")
    print(f"转换:   {len(trans)} 次")
    print(f"消息:   {len(msgs)} 条")
    print(f"决策:   {len(all_decisions)} 个")
    print()
    print("💬 消息记录:")
    for r in msgs:
        print(f"  {r['from_role']:12s}| {r['substr(content,1,60)']}")
    print()
    print("📋 决策序列:")
    for d in all_decisions:
        print(f"  [{d['state']:15s}] {d['role']:12s} → {d['value']:20s} | {d['reason'][:60]}")
    print()
    print(f"🌐 Dashboard: http://localhost:8765")
    print(f"{'='*60}\n")


def _generate_and_run(goal: str, agents_str: str, name: str) -> None:
    """Generate then run in sequence."""
    agent_ids = agents_str.split(",")
    # Generate
    cmd_generate(goal, agent_ids, name)
    # The result is printed as JSON by cmd_generate; we need to capture it
    # But since we're in the same process, we use a different approach:
    pool = _load_pool()
    agents_in_pool = pool.get("agents", {})
    selected = {aid: agents_in_pool[aid] for aid in agent_ids if aid in agents_in_pool}
    # Generate YAML inline
    flow_id = f"auto-{uuid.uuid4().hex[:8]}"
    run_name = name or goal[:60]

    # ... we'd duplicate the generate logic here, but instead let's:
    # Save goal to a temp file and call generate + run via subprocess
    import subprocess
    python = sys.executable
    script = Path(__file__).resolve()
    gen_cmd = [python, str(script), "generate", goal, "--agents", agents_str]
    if name:
        gen_cmd += ["--name", name]
    gen_result = subprocess.run(gen_cmd, capture_output=True, text=True)
    try:
        gen_data = json.loads(gen_result.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": f"Generate failed:\n{gen_result.stdout}\n{gen_result.stderr}"}))
        return

    if not gen_data.get("ok"):
        print(json.dumps(gen_data))
        return

    yaml_path = gen_data["yaml_path"]

    # Now run
    run_cmd = [python, str(script), "run", yaml_path, "--name", name]
    run_result = subprocess.run(run_cmd, capture_output=True, text=True)
    print(run_result.stdout)
    if run_result.stderr:
        print(run_result.stderr, file=sys.stderr)


if __name__ == "__main__":
    main()
