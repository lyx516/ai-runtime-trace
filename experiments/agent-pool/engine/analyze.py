"""Cross-run analysis and run inspection commands."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from engine.config import PROJECT_ROOT, _SCRIPT_DIR


def _run_dirs() -> list[Path]:
    """Both possible run storage locations."""
    return [
        Path(PROJECT_ROOT) / ".hermes-flow" / "runs",
        _SCRIPT_DIR / ".hermes-flow" / "runs",
    ]


def analyze_all_runs():
    """Cross-run pattern recognition. Aggregates performance data and generates suggestions."""
    from hermes_flow.storage import RuntimeStore

    dirs = _run_dirs()
    seen = set()
    all_perf = []

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

    scores = [p["success_score"] for p in all_perf]
    avg_score = sum(scores) / len(scores)
    print(f"\n📈 Scores: avg={avg_score:.0f}  min={min(scores)}  max={max(scores)}  range={max(scores)-min(scores)}")
    if avg_score < 60:
        print(f"   ⚠️  Average below 60 — systematic issues present")

    bottlenecks = Counter(p["bottleneck_state"] for p in all_perf if p["bottleneck_state"])
    print(f"\n🔴 Bottleneck states:")
    for state, count in bottlenecks.most_common():
        pct = count / len(all_perf) * 100
        bar = "█" * int(pct / 10)
        print(f"   {state:<15} {count}/{len(all_perf)} ({pct:.0f}%) {bar}")

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

    tool_all: dict[str, int] = {}
    for p in all_perf:
        for tool, count in p.get("tool_stats", {}).items():
            tool_all[tool] = tool_all.get(tool, 0) + count
    if tool_all:
        print(f"\n🔧 Tool usage (total across {len(all_perf)} runs):")
        for tool, count in sorted(tool_all.items(), key=lambda x: -x[1]):
            print(f"   {tool:<20} {count:>5} calls")

    print(f"\n{'='*60}")
    print(f"🔍 LLM-Generated Insights")
    print(f"{'='*60}")

    # Prepare compact stats summary for LLM
    _agent_summary = ", ".join(
        f"{aid}:avg={sum(s)/len(s):.0f}(n={len(s)})"
        for aid, s in sorted(agent_all.items(), key=lambda x: sum(x[1])/len(x[1]))
    ) if agent_all else "no agent data"
    _bn_summary = ", ".join(f"{s}:{c}" for s, c in bottlenecks.most_common()) or "none"
    _tool_summary = ", ".join(f"{t}:{c}" for t, c in sorted(tool_all.items(), key=lambda x: -x[1])[:5]) or "none"
    _single_state_count = sum(1 for p in all_perf if p["bottleneck_state"] in ("DONE", "?"))
    _score_dist = f"avg={avg_score:.0f},min={min(scores)},max={max(scores)},single_state={_single_state_count}/{len(all_perf)}"

    from engine.llm_client import call_llm
    from engine.llm_config import load_config
    _cfg = load_config()
    _llm_system = "你是多 Agent 系统的运行分析专家。基于跨 run 的统计数据，识别系统性模式并给出具体的改进建议。只输出最终结果，不要多余解释。"
    _llm_user = f"""## 跨 Run 统计数据 ({len(all_perf)} runs)

分数分布: {_score_dist}
瓶颈状态: {_bn_summary}
Agent 表现: {_agent_summary}
工具使用 top5: {_tool_summary}

请输出：
1. 发现的系统性模式（2-3 条，每条带数据支撑）
2. 改进建议（2-3 条，具体可执行，指向 agent/gate/tool 层面）
格式：直接输出 markdown 文本，不要 JSON。"""
    try:
        _insight = call_llm(_llm_system, _llm_user, model=_cfg.model, temperature=0.4, max_tokens=1500)
        if isinstance(_insight, dict):
            # call_llm returns {"raw_content": ...} when LLM output isn't JSON
            _insight_text = _insight.get("raw_content") or _insight.get("content", "") or _insight.get("reason", "")
        else:
            _insight_text = str(_insight)
        print(_insight_text[:2000])
    except Exception as e:
        print(f"   ⚠️ LLM insight generation failed: {e}")
        print(f"   (raw stats: scores={_score_dist}, bottlenecks={_bn_summary})")

    return all_perf


def show_performance(run_id: str):
    """Display run performance evaluation."""
    from hermes_flow.storage import RuntimeStore

    for base in _run_dirs():
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


def list_runs():
    """Scan runs directories and display a summary table."""
    from hermes_flow.storage import RuntimeStore

    dirs = _run_dirs()
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


def show_feedback(agent_id: str | None = None):
    """Show pending feedback for an agent or all agents."""
    from hermes_flow.storage import RuntimeStore

    all_fb = []
    for base in _run_dirs():
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