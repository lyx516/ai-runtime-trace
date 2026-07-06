"""Run performance persistence — called by EvolutionAgent after eval.

Originally this module also contained ``manager_evaluate``, a Manager-LLM-based
post-run reviewer. That role has been fully replaced by EvolutionAgent (see
engine/evolve.py), so manager_evaluate was removed as dead code.

persist_performance remains: it takes EvolutionAgent's eval JSON (feedback with
per-agent scores + run_score) and writes run_performance to SQLite.
"""

from __future__ import annotations


def persist_performance(store, run_id: str, goal: str, agent_ids: list[str],
                        eval_result: dict | None):
    """Compute run performance metrics and save to store.

    ``eval_result`` is EvolutionAgent's JSON output:
      {"feedback": [{"agent_id", "score", ...}], "run_score": int, "gate_suggestion": str}
    When None (no eval), scores fall back to simple heuristics.
    """
    conn = store.connect()

    tool_rows = conn.execute(
        "SELECT step_type FROM thinking_events WHERE run_id=? AND step_type NOT IN ('submit_decision','memory_read','memory_write')",
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
    summary = (
        f"Task: {goal[:100]}. "
        f"{'Completed' if completed else 'Active/Aborted'}. "
        f"{decs_count} decisions, {msgs_count} messages, "
        f"{len(tool_calls)} tool calls across {len(agent_ids)} agents. "
        f"Bottleneck: {bottleneck}."
    )
    suggestions = eval_result.get("gate_suggestion", "") if eval_result else ""

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