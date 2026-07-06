"""FSM driver — state machine loop, run creation, and resume."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4 as _uuid4

from hermes_flow.hooks import reset_bus

from engine.config import PROJECT_ROOT
from engine.agent_loader import load_agents
from engine.artifacts import find_output_artifact
from engine.hooks_wiring import make_hook_handlers
from engine.session import _run_agent_session


def _run_fsm_loop(store, run_id: str, goal: str, agent_ids: list[str], agents: dict):
    """FSM while loop — shared by run_flow() and resume_flow()."""
    from hermes_flow.tools import flow_step
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
        if status_str and RunStatus(status_str) in (RunStatus.COMPLETED, RunStatus.ABORTED):
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
            # Single-agent mode: no one to send messages to - remove message tool
            if len(agents) == 1:
                tool_schemas = [t for t in tool_schemas if t.get("function", {}).get("name") != "agent_message_send"]
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

            def _clarify_handler(question, choices):
                print(f"\n  💬 [{role_id}@{state_id}] {question}")
                if choices:
                    for i, c in enumerate(choices, 1):
                        print(f"     [{i}] {c}")
                    print(f"     [t]  自由输入")
                while True:
                    answer = input("  > ").strip()
                    if choices and answer in ("t", "T"):
                        answer = input("  > ").strip()
                        break
                    if choices and answer.isdigit():
                        idx = int(answer) - 1
                        if 0 <= idx < len(choices):
                            answer = choices[idx]
                            break
                    if not choices:
                        break
                    print(f"  请输入 1-{len(choices)} 或 t")
                return answer

            result = _run_agent_session(
                role_id, soul, goal, state_id, cur_round,
                all_msgs, inbox_rows, gate, tool_schemas, agents,
                output_artifacts=state_dict.get("output_artifacts", []),
                prev_artifacts=found_artifacts if found_artifacts else None,
                store=store,
                run_id=run_id,
                write_scope=_write_scope,
                flow_overview=_build_flow_overview(state_id),
                clarify_fn=_clarify_handler,
            )

            val = result.get("value", "APPROVE").upper()
            reason = result.get("reason", "")
            tool_count = result.get("tool_calls", 0)
            print(f"     ✅ {val} (after {tool_count} tool call(s))")

            # Product gate: if artifact is invalid, override the agent's decision.
            # The hook already recorded the agent's original decision via flow_decide;
            # here we UPDATE it in-place rather than appending a second row.
            output_artifacts = state_dict.get("output_artifacts", [])
            if output_artifacts:
                for art_name in output_artifacts:
                    art_path, artifact_reason = find_output_artifact(PROJECT_ROOT, art_name, _write_scope)
                    if art_path:
                        fp = str(art_path)
                        rel = art_path.relative_to(Path(PROJECT_ROOT)) if art_path.is_relative_to(Path(PROJECT_ROOT)) else art_path
                        print(f"     📄 {art_name} → {rel} ({art_path.stat().st_size} bytes) ✅")
                        found_artifacts[art_name] = fp
                    else:
                        print(f"     ⚠️  产物 {art_name} 无效：{artifact_reason}；降级为 REQUEST_CHANGES")
                        val = "REQUEST_CHANGES"
                        reason = f"[产品门禁] {art_name}: {artifact_reason}"
                        conn.execute(
                            "UPDATE decisions SET value=?, reason=? WHERE run_id=? AND state_id=? AND role_id=?",
                            (val, reason, run_id, state_id, role_id),
                        )
                        conn.commit()

            if val in fail_vals:
                break

        r3 = flow_step(run_id)
        if r3.get("ok"):
            print(f"  → {r3.get('from_state')} → {r3.get('to_state')}")
            # Self-loop termination: all roles must have passed, not just decided
            if r3.get("from_state") and r3.get("from_state") == r3.get("to_state"):
                _pass_vals = gate.get("pass_values", ["APPROVE"])
                _all_approved = all(
                    store.agent_has_decision(run_id, r3["from_state"], r)
                    and (store.conn.execute(
                        "SELECT value FROM decisions WHERE run_id=? AND state_id=? AND role_id=? ORDER BY created_at DESC LIMIT 1",
                        (run_id, r3["from_state"], r),
                    ).fetchone() or {}).get("value", "") in _pass_vals
                    for r in required_roles
                )
                if _all_approved:
                    from hermes_flow.schemas import RunStatus
                    store.update_status(run_id, RunStatus.COMPLETED)
                    print(f"  🏁 Self-loop complete: all roles decided → completed")
                    break
        else:
            print(f"  ⏸ pending: {r3.get('error', '?')}")
            break

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
    make_hook_handlers(store, run_id)

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
    make_hook_handlers(store, run_id)

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

    # Reset run status to active — the old status may have been
    # prematurely set to completed by a previous self-loop bug.
    conn.execute("UPDATE runs SET status=? WHERE run_id=?", ("active", run_id))
    conn.commit()

    _run_fsm_loop(store, run_id, goal, agent_ids, agents)