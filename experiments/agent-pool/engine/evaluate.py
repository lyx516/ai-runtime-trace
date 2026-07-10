"""Run performance persistence — called by EvolutionAgent after eval.

Originally this module also contained ``manager_evaluate``, a Manager-LLM-based
post-run reviewer. That role has been fully replaced by EvolutionAgent (see
engine/evolve.py), so manager_evaluate was removed as dead code.

persist_performance remains: it takes EvolutionAgent's eval JSON (feedback with
per-agent scores + run_score) and writes run_performance to SQLite.
"""

from __future__ import annotations

import json
from pathlib import Path


def capture_run_metrics(store, run_id: str, goal: str, agent_ids: list[str]) -> dict:
    """Post-run metric capture: aggregate per-state tool_calls, decisions, time.

    Called from _run_fsm_loop on every normal exit (completed or aborted).
    Writes run_performance with real SQLite-aggregated data.
    Returns the same dict for inline use.
    """
    conn = store.connect()

    # Status / outcome
    row = conn.execute("SELECT status, current_state_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return {}
    outcome = f"{row['status']}@{row['current_state_id']}"

    # Per-state tool calls
    by_state: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT state_id, role_id, COUNT(*) as cnt FROM thinking_events "
        "WHERE run_id=? AND step_type NOT IN ('llm_call','submit_decision','agent_message_send') "
        "GROUP BY state_id, role_id ORDER BY state_id",
        (run_id,),
    ).fetchall()
    for r in rows:
        sid = r["state_id"]
        if sid not in by_state:
            by_state[sid] = {}
        by_state[sid][r["role_id"]] = r["cnt"]
    per_state = {}
    for sid, roles in by_state.items():
        per_state[sid] = {"total": sum(roles.values()), "by_role": dict(roles)}

    # Per-state decision counts
    dec_rows = conn.execute(
        "SELECT state_id, COUNT(*) as cnt FROM decisions WHERE run_id=? GROUP BY state_id",
        (run_id,),
    ).fetchall()
    decisions = {}
    for r in dec_rows:
        decisions[r["state_id"]] = r["cnt"]

    # Transitions count
    trans_cnt = conn.execute(
        "SELECT COUNT(*) as c FROM transitions WHERE run_id=?", (run_id,),
    ).fetchone()["c"]

    # Messages count
    msg_cnt = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE run_id=?", (run_id,),
    ).fetchone()["c"]

    # Total runtime in seconds
    times = conn.execute(
        "SELECT min(created_at) as first_ts, max(created_at) as last_ts FROM thinking_events WHERE run_id=?",
        (run_id,),
    ).fetchone()

    def _parse_ts(s):
        if not s:
            return None
        import datetime as dt
        return dt.datetime.fromisoformat(s)

    t1 = _parse_ts(times["first_ts"]) if times else None
    t2 = _parse_ts(times["last_ts"]) if times else None
    total_seconds = (t2 - t1).total_seconds() if t1 and t2 else 0

    tool_stats = {
        "outcome": outcome,
        "total_seconds": round(total_seconds, 1),
        "by_state": per_state,
        "decisions": decisions,
        "transitions": trans_cnt,
        "messages": msg_cnt,
    }

    # Write to run_performance table
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    # Inject goal_id from benchmarks keyword matching
    _gid = "other"
    try:
        _bmp = Path(__file__).resolve().parent.parent / "benchmarks" / "tasks.yaml"
        if _bmp.exists():
            import yaml as _by
            for _bt in _by.safe_load(_bmp.read_text()) or []:
                if any(kw.lower() in goal.lower() for kw in _bt.get("keywords", [])):
                    _gid = _bt["id"]; break
    except Exception:
        pass

    conn.execute(
        "INSERT OR REPLACE INTO run_performance "
        "(run_id, success_score, summary, agent_scores, bottleneck_state, "
        " tool_stats, suggestions, evaluated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            85 if row["status"] == "completed" else 40,
            f"Task: {goal[:90]} [goal_id:{_gid}]. {outcome}. {sum(d['total'] for d in per_state.values())} tool calls.",
            json.dumps({}),
            max(per_state, key=lambda k: per_state[k]["total"]) if per_state else "?",
            json.dumps(tool_stats),
            "",
            now,
        ),
    )
    conn.commit()
    print(f"  📊 Metrics: outcome={outcome} states={list(per_state.keys())} runtime={total_seconds:.0f}s")
    return tool_stats


def persist_performance(store, run_id: str, goal: str, agent_ids: list[str],
                        eval_result: dict | None):
    """Compute run performance metrics and save to store.

    ``eval_result`` is EvolutionAgent's JSON output:
      {"feedback": [{"agent_id", "score", ...}], "run_score": int, "gate_suggestion": str}
    When None (no eval), scores fall back to simple heuristics.
    """
    conn = store.connect()

    tool_rows = conn.execute(
        "SELECT step_type FROM thinking_events WHERE run_id=? AND step_type NOT IN ('submit_decision')",
        (run_id,),
    ).fetchall()
    tool_calls: dict[str, int] = {}
    for r in tool_rows:
        tool_calls[r["step_type"]] = tool_calls.get(r["step_type"], 0) + 1

    trans_rows = conn.execute(
        "SELECT from_state_id, COUNT(*) as cnt FROM transitions WHERE run_id=? GROUP BY from_state_id ORDER BY cnt DESC",
        (run_id,),
    ).fetchall()
    bottleneck = trans_rows[0]["from_state_id"] if trans_rows else "?"

    status_row = conn.execute(
        "SELECT status FROM runs WHERE run_id=?", (run_id,),
    ).fetchone()
    completed = status_row and status_row["status"] == "completed"

    # Agent scores from EvolutionAgent feedback
    agent_scores = {}
    if eval_result:
        for fb in eval_result.get("feedback", []):
            aid = fb.get("agent_id", "")
            raw = fb.get("score", 70)
            try:
                score = max(0, min(100, int(raw)))
            except (ValueError, TypeError):
                score = 70
            agent_scores[aid] = score

    decs_count = conn.execute(
        "SELECT COUNT(*) as c FROM decisions WHERE run_id=?", (run_id,),
    ).fetchone()["c"]
    msgs_count = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE run_id=?", (run_id,),
    ).fetchone()["c"]

    # Run-level success score: prefer EvolutionAgent run_score, fall back to heuristic
    raw_run_score = None
    if eval_result:
        raw_run_score = eval_result.get("run_score")
    try:
        success_score = max(0, min(100, int(raw_run_score))) if raw_run_score is not None else (85 if completed else 40)
    except (ValueError, TypeError):
        success_score = 85 if completed else 40
    # Preserve [goal_id:xxx] tag from existing summary if present
    _existing = store.load_run_performance(run_id)
    _goal_tag = ""
    if _existing:
        import re as _re_gid
        _m = _re_gid.search(r"\[goal_id:[a-z0-9\-]+\]", _existing.get("summary", ""))
        if _m:
            _goal_tag = _m.group(0)
    summary = (
        f"Task: {_goal_tag + ' ' if _goal_tag else ''}{goal[:90]}. "
        f"{'Completed' if completed else 'Active/Aborted'}. "
        f"{decs_count} decisions, {msgs_count} messages, "
        f"{len(tool_calls)} tool calls across {len(agent_ids)} agents. "
        f"Bottleneck: {bottleneck}."
    )
    suggestions = eval_result.get("gate_suggestion", "") if eval_result else ""

    # Preserve structured tool_stats from capture_run_metrics if they exist.
    # capture_run_metrics writes per-state detail; persist_performance only adds
    # EvolutionAgent's scores + suggestions. Don't overwrite the good data.
    final_tool_stats = dict(tool_calls)
    existing = store.load_run_performance(run_id)
    if existing:
        try:
            existing_ts = json.loads(existing["tool_stats"]) if isinstance(existing.get("tool_stats"), str) else existing.get("tool_stats", {})
        except (json.JSONDecodeError, TypeError):
            existing_ts = {}
        if isinstance(existing_ts, dict) and "by_state" in existing_ts:
            final_tool_stats = existing_ts

    store.save_run_performance(
        run_id=run_id,
        success_score=success_score,
        summary=summary,
        agent_scores=agent_scores,
        bottleneck_state=bottleneck,
        tool_stats=final_tool_stats,
        suggestions=suggestions,
    )
    print(f"  📊 Performance: score={success_score} bottleneck={bottleneck} agents={list(agent_scores.keys())}")

    return store.load_run_performance(run_id)


def compare_runs(tool_stats_a: dict, tool_stats_b: dict) -> dict:
    """Compare two runs' tool_stats dicts, return delta + regression flag.

    Pure function — no I/O, no store dependency.
    Regression: any state increased >15% & >3 absolute, OR run B aborted.
    """
    states = set(tool_stats_a.get("by_state", {})) | set(tool_stats_b.get("by_state", {}))
    delta: dict[str, int] = {}
    for s in sorted(states):
        a = tool_stats_a.get("by_state", {}).get(s, {}).get("total", 0)
        b = tool_stats_b.get("by_state", {}).get(s, {}).get("total", 0)
        delta[s] = b - a

    seconds_a = tool_stats_a.get("total_seconds", 0)
    seconds_b = tool_stats_b.get("total_seconds", 0)

    regression = False
    if tool_stats_b.get("outcome", "").startswith("abort"):
        regression = True
    else:
        for s, d in delta.items():
            a = tool_stats_a.get("by_state", {}).get(s, {}).get("total", 0)
            if a > 0 and d > max(3, a * 0.15):
                regression = True
                break

    return {
        "delta": delta,
        "seconds_delta": round(seconds_b - seconds_a, 1),
        "regression": regression,
    }