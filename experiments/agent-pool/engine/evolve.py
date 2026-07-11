"""Evolution — EvolutionAgent self-improvement loop.

evolve()     — scan un-evaluated runs, investigate via agent_recall, produce feedback
evolve_agent() — process pending feedback for a single agent with LLM
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Optional

PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent.parent.parent  # ai-runtime-trace/

# ── Framework patch whitelist ───────────────────────────────────────────
# Only these files may be modified via EvolutionAgent's patch_framework action.
_FRAMEWORK_WHITELIST = {
    "experiments/agent-pool/engine/session.py",
    "experiments/agent-pool/agents/manager/skills/spec-team.md",
    "experiments/agent-pool/agents/manager/skills/spec-clarify-team.md",
}
from runtime_trace.hooks import reset_bus
from runtime_trace.schemas import AgentSessionState

from engine.config import PROJECT_ROOT, _SCRIPT_DIR
from engine.agent_loader import load_agents
from engine.session import _run_session_loop
from engine.llm_client import call_llm
from engine.llm_config import get_agent_model


def _run_dirs() -> list[Path]:
    return [
        Path(PROJECT_ROOT) / ".runtime-trace" / "runs",
        _SCRIPT_DIR / ".runtime-trace" / "runs",
    ]


def extract_eval_json(conn, run_id: str, role_id: str) -> dict | None:
    """Extract evaluation JSON from EvolutionAgent's thinking_events.

    Searches the last 30 thinking events for JSON containing 'feedback' or
    'evolution_actions'. Tries: (1) code-fenced JSON, (2) bare JSON objects,
    (3) submit_decision reason field.
    """
    import re
    rows = conn.execute(
        "SELECT step_type, output_json FROM thinking_events WHERE run_id=? AND role_id=? ORDER BY rowid DESC LIMIT 30",
        (run_id, role_id),
    ).fetchall()

    contents_to_search = []

    # 1. Collect all assistant text contents
    for r in rows:
        if r["step_type"] == "llm_call" and r["output_json"]:
            try:
                output = json.loads(r["output_json"])
                content = output.get("content", "")
                if content:
                    contents_to_search.append(content)
            except Exception:
                pass

    # 2. Also check submit_decision reason
    dec_row = conn.execute(
        "SELECT reason FROM decisions WHERE run_id=? AND role_id=? ORDER BY rowid DESC LIMIT 1",
        (run_id, role_id),
    ).fetchone()
    if dec_row and dec_row["reason"]:
        contents_to_search.append(dec_row["reason"])

    # 3. Try to extract JSON from each content
    for content in contents_to_search:
        m = re.search(r'```(?:json)?\s*(\{.*"feedback".*\})\s*```', content, re.DOTALL)
        if not m:
            m = re.search(r'\{.*"feedback".*\}', content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1) if m.lastindex else m.group(0))
            except Exception:
                pass

    return None


def evolve():
    """EvolutionAgent: scan all un-evaluated runs, investigate via agent_recall, produce feedback + actions.

    Finds runs that have no run_performance entry (not yet evaluated).
    For each run, starts an EvolutionAgent session with agent_recall tool
    to investigate, produce per-agent feedback, and generate evolution actions.
    """
    from runtime_trace.storage import RuntimeStore

    dirs = _run_dirs()

    unevaluated: list[tuple[str, RuntimeStore]] = []
    for base in dirs:
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            try:
                store = RuntimeStore(d)
                store.init_schema()
                perf = store.load_run_performance(d.name)
                if perf is not None:
                    continue
                run_row = store.connect().execute(
                    "SELECT status, flow_id FROM runs WHERE run_id=?", (d.name,)
                ).fetchone()
                if run_row and run_row["status"] in ("completed", "active"):
                    unevaluated.append((d.name, store))
            except Exception:
                pass

    if not unevaluated:
        print("✅ All runs evaluated. No pending runs.")
        return

    print(f"\n{'='*60}")
    print(f"🧬 EvolutionAgent: evaluating {len(unevaluated)} un-evaluated run(s)")
    print(f"{'='*60}")

    # Load EvolutionAgent SOUL
    evo_soul_path = _SCRIPT_DIR / "agents" / "evolution-agent" / "SOUL.md"
    evo_soul = evo_soul_path.read_text() if evo_soul_path.exists() else ""

    # Load agent pool (for agent_id info + model resolution)
    agents = load_agents()

    # Build EvolutionAgent's tool schemas — use the unified registry
    from tool_registry import get_agent_tools_schemas, DECISION_TOOL_SCHEMA
    evo_tool_schemas = get_agent_tools_schemas("evolution-agent") + [DECISION_TOOL_SCHEMA]

    total_feedback = 0
    total_actions = 0

    for run_id, store in unevaluated:
        print(f"\n{'─'*50}")
        print(f"📊 Evaluating run: {run_id}")
        print(f"{'─'*50}")

        conn = store.connect()
        run_row = conn.execute("SELECT status, flow_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not run_row:
            print(f"  ⚠️  Run not found, skipping")
            continue
        goal = run_row["flow_id"]

        system_prompt = f"""{evo_soul}

## 评审任务

你正在评审 run `{run_id}`（goal: {goal}）。

使用 `agent_recall` 调查数据，按 evaluate-flow skill 流程操作。
完成后**用 submit_decision 的 reason 字段提交 JSON 报告**：
- 不写自然语言解释——reason 字段只放纯 JSON 字符串
- value 设为 APPROVE（完成）或 REQUEST_CHANGES（数据不足需更多调查）

JSON 格式：
{{"feedback":[{{"agent_id":"x","category":"memory|skill|tool","suggestion":"...","evidence":"..."}}],"evolution_actions":[{{"type":"update_memory|update_skill|dismiss","agent_id":"x","detail":"- 纯改进条目"}},{{"type":"patch_framework","target_file":"experiments/agent-pool/engine/session.py","old_string":"精确原文","new_string":"替换后文本","patch_summary":"改动摘要"}},{{"type":"revert_framework","backup_id":123,"target_file":"experiments/agent-pool/engine/session.py"}}]}}

无改进时 feedback 和 evolution_actions 均用空数组 []。"""

        messages_json = json.dumps([{
            "role": "user",
            "content": f"开始评审 run {run_id}。先加载评审流程 skill_load(\"evaluate-flow\")，然后用 agent_recall 调查。",
        }], ensure_ascii=False)
        tools_json = json.dumps(evo_tool_schemas, ensure_ascii=False)

        _evo_role_id = "evolution-agent"
        _evo_state_id = "EVALUATE"
        state = AgentSessionState(
            run_id=run_id,
            role_id=_evo_role_id,
            state_id=_evo_state_id,
            round_n=1,
            system_prompt=system_prompt,
            messages_json=messages_json,
            tools_json=tools_json,
            turn=0,
            max_turns=20,
        )

        print(f"  🤖 EvolutionAgent investigating...")
        reset_bus()
        from runtime_trace.bootstrap import bootstrap_runtime
        bootstrap_runtime(store, run_id, enable_observer=False)
        session_result = _run_session_loop(state, store, run_id, agents,
                                  clarify_fn=lambda q, c: "")
        print(f"  ✅ Evaluation complete: {session_result.get('value', '?')}")

        conn = store.connect()
        eval_result = extract_eval_json(conn, run_id, _evo_role_id)

        if eval_result:
            print(f"  📋 Found evaluation output")

            for fb in eval_result.get("feedback", []):
                if fb.get("agent_id") and fb.get("suggestion"):
                    store.save_agent_feedback(
                        run_id=run_id,
                        agent_id=fb["agent_id"],
                        category=fb.get("category", "skill"),
                        suggestion=fb["suggestion"],
                        evidence=fb.get("evidence", ""),
                    )
                    total_feedback += 1
                    print(f"     📝 feedback: [{fb['agent_id']}] {fb['suggestion'][:80]}")

            evo_actions = eval_result.get("evolution_actions", [])
            _patch_count = 0  # limit framework patches to 3 per run
            for act in evo_actions:
                atype = act.get("type", "")
                detail = act.get("detail", "")
                target_agent = act.get("agent_id", "")
                if atype == "dismiss":
                    pending = store.load_agent_feedback(target_agent)
                    for fb in pending:
                        store.mark_feedback_dismissed(fb["row_id"])
                    total_actions += 1
                    print(f"     📋 dismiss: [{target_agent}]")
                elif atype in ("update_memory", "update_skill") and target_agent and detail:
                    target_file = _SCRIPT_DIR / "agents" / target_agent / ("SKILL.md" if atype == "update_skill" else "Memory.md")
                    max_bytes = 8192 if atype == "update_skill" else 4096
                    new_content = f"\n{detail}\n"
                    current_size = target_file.stat().st_size if target_file.exists() else 0
                    if target_file.exists():
                        existing = target_file.read_text()
                        if detail.strip() in existing:
                            print(f"     ⏭  [{target_agent}] skip (already present)")
                            continue
                    if current_size + len(new_content) <= max_bytes:
                        with open(target_file, "a") as f:
                            f.write(new_content)
                        total_actions += 1
                        print(f"     ✅ [{target_agent}] {target_file.name}: +{len(new_content)}B")
                    else:
                        print(f"     ⚠️  [{target_agent}] {target_file.name} 超限, skipped")
                elif atype == "patch_framework" and _patch_count < 3:
                    target_file = act.get("target_file", "")
                    if target_file not in _FRAMEWORK_WHITELIST:
                        print(f"     ⚠️  patch_framework: {target_file} not in whitelist")
                        continue
                    old_s = act.get("old_string", "")
                    new_s = act.get("new_string", "")
                    patch_summary = act.get("patch_summary", "no summary")
                    abs_path = PROJECT_ROOT_PATH / target_file
                    if not abs_path.exists():
                        print(f"     ⚠️  patch_framework: {target_file} does not exist")
                        continue
                    original = abs_path.read_text()
                    if old_s not in original:
                        print(f"     ⚠️  patch_framework: old_string not found in {target_file}")
                        continue
                    # Backup
                    backup_id = store.save_evolution_backup(run_id, target_file, original, patch_summary)
                    # Apply
                    new_content = original.replace(old_s, new_s, 1)
                    assert new_content != original, "replace didn't change content"
                    abs_path.write_text(new_content)
                    # Pytest gate
                    result = subprocess.run(
                        [str(PROJECT_ROOT_PATH / ".venv" / "bin" / "python"), "-m", "pytest",
                         str(PROJECT_ROOT_PATH / "tests" / "runtime_trace"), "-q"],
                        capture_output=True, timeout=30, cwd=str(PROJECT_ROOT_PATH),
                    )
                    if result.returncode != 0:
                        abs_path.write_text(original)
                        print(f"     ❌ patch_framework: pytest failed, rolled back {target_file}")
                        print(f"        {result.stderr.decode()[:200] if result.stderr else ''}")
                    else:
                        _patch_count += 1
                        total_actions += 1
                        print(f"     ✅ patch_framework: {target_file} ({patch_summary})")
                elif atype == "revert_framework":
                    backup_id = act.get("backup_id", 0)
                    if backup_id and store.revert_evolution_backup(backup_id):
                        total_actions += 1
                        print(f"     ↩  revert_framework: backup #{backup_id} restored")
        else:
            print(f"  ⚠️  No evaluation JSON found in EvolutionAgent response")

        # EvolutionAgent sessions do not reach a terminal FSM state, so they
        # explicitly run the same deterministic evaluator after their review.
        try:
            if store.load_run_performance(run_id) is None:
                from runtime_trace.evaluator import quick_evaluate
                quick_evaluate(store, run_id)
        except Exception:
            pass


    print(f"\n{'='*60}")
    print(f"🧬 Evolution complete: {len(unevaluated)} runs, {total_feedback} feedback entries, {total_actions} actions applied")
    print(f"{'='*60}")
    print(f"\n💡 Run debate --evolve to re-evaluate after new runs complete.\n")


def evolve_all():
    """Process all agents with pending feedback."""
    evolve()


def evolve_agent(agent_id: str, apply: bool = False):
    """Process pending feedback for a single agent with EvolutionAgent LLM."""
    from runtime_trace.storage import RuntimeStore

    dirs = _run_dirs()
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

    MAX_MEMORY = 4096
    MAX_SKILL = 8192

    memory_size = len(memory_content)
    size_info = f"Memory: {memory_size}B/{MAX_MEMORY}B"
    if agent_dir.joinpath("SKILL.md").exists():
        skill_size = agent_dir.joinpath("SKILL.md").stat().st_size
        size_info += f", SKILL: {skill_size}B/{MAX_SKILL}B"

    system = f"""你是 EvolutionAgent——一个精确、谨慎的 agent 修改执行者。
你**不能自由发挥**，只能基于 feedback 中的具体证据进行定向修改。

当前 agent: {agent_id}
文件大小限制: {size_info}

你的能力：
- update_memory: 追加 Memory.md（纯改进条目，硬上限 {MAX_MEMORY}B）
- update_skill: 追加 SKILL.md（纯改进条目，硬上限 {MAX_SKILL}B）
- dismiss: feedback 不适用或 run 特定时标记为 dismissed

写入规则 — 严格遵守：
1. detail 必须是纯改进条目，格式: "- 具体改进点"（列表项格式）
2. 禁止写 "## Evolution Update"、run_id、evidence、元指令（"追加"、"修改"、"建议"）
3. 禁止写 run 特定观察（团队搭配、具体任务名、某次运行教训）
4. 只写通用可复用的技能/流程改进
5. 如果 feedback 描述的是 run 特定现象 → dismiss

响应 JSON:
{{"actions": [{{"type": "update_memory|update_skill|dismiss", "detail": "- 纯改进条目内容"}}]}}"""

    user = f"""## Agent: {agent_id}

### 当前 Memory
{memory_content[:800]}

### Pending Feedback ({len(all_fb)} items)
{feedback_text}

请生成修改计划。"""

    print(f"  🧬 EvolutionAgent analyzing {agent_id} ({len(all_fb)} feedback items)...")
    # Load agents for model resolution
    agents = load_agents()
    evo_model = get_agent_model(agents, "evolution-agent")
    result = call_llm(system, user, model=evo_model, temperature=0.3, max_tokens=2000)
    actions = result.get("actions", [])

    if not actions:
        print("  ℹ️  No actions generated")
        return

    print(f"\n  📋 Evolution Plan for {agent_id}:\n")
    for i, act in enumerate(actions, 1):
        atype = act.get("type", "?")
        detail = act.get("detail", "")[:200]
        print(f"  {i}. [{atype}] {detail}")

    if apply:
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

                new_content = f"\n{detail}\n"

                if target_file.exists():
                    existing = target_file.read_text()
                    if detail.strip() in existing:
                        print(f"  ⏭  Skipped {target_file.name} (already present)")
                        continue

                if current_size + len(new_content) > max_bytes:
                    _msg = f"❌ {target_file.name} 超限 ({current_size}B/{max_bytes}B)"
                    print(f"  ⚠️  {_msg}")
                    _retry_result = call_llm(
                        system, f"{user}\n\n{_msg}\n请精简或替换旧条目，重新生成 detail（需 < {max_bytes - current_size}B）。",
                        model=evo_model, temperature=0.3, max_tokens=2000)
                    _retry_actions = _retry_result.get("actions", [])
                    if _retry_actions:
                        detail = _retry_actions[0].get("detail", "")
                        new_content = f"\n{detail}\n"
                        if current_size + len(new_content) <= max_bytes:
                            with open(target_file, "a") as f:
                                f.write(new_content)
                            applied += 1
                            print(f"  ✅ Updated {target_file.name} (retry, {current_size}B → {current_size + len(new_content)}B)")
                        else:
                            print(f"  ⚠️  Retry still over limit, skipped")
                    continue

                if store and all_fb:
                    _ckpt_run = all_fb[0].get("run_id", "?")
                    _rel = str(target_file.relative_to(PROJECT_ROOT_PATH))
                    store.save_evolution_backup(_ckpt_run, _rel, target_file.read_text(), f"checkpoint before {target_file.name}")
                with open(target_file, "a") as f:
                    f.write(new_content)
                applied += 1
                print(f"  ✅ Updated {target_file.name} ({current_size}B → {current_size + len(new_content)}B)")

        for fb in all_fb:
            store.mark_feedback_applied(fb["row_id"])
        print(f"\n  🧬 Applied {applied} changes, cleared {len(all_fb)} feedback items")
    else:
        print(f"\n  ⚠️  Review the plan above. Use --apply to execute:")
        print(f"     debate --evolve-agent {agent_id} --apply")

    return actions
