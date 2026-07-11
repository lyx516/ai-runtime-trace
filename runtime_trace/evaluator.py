"""Quick evaluator — deterministic run scoring. No LLM needed.

Triggered by Hook.RUN_COMPLETED handler in bootstrap.py.
Reads SQLite telemetry (transitions, thinking_events, decisions, messages)
and writes run_performance via store.save_run_performance().

Deliberately does NOT accept manager_result or any LLM-derived input.
Deep evaluation (EvolutionAgent, LLM-driven) is a separate flow triggered
by `debate --evolve`.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime_trace.storage import RuntimeStore

logger = logging.getLogger(__name__)


def quick_evaluate(store: RuntimeStore, run_id: str) -> dict[str, Any] | None:
    """Compute and persist deterministic run performance metrics.

    Reads:
    - runs.status (completed → 85, otherwise max(30, 50 - transitions×5))
    - thinking_events → tool_stats
    - transitions → bottleneck_state
    - decisions / messages counts → summary

    Writes:
    - store.save_run_performance()
    - Returns the saved performance dict (or None on failure)
    """
    conn = store.connect()

    # ── Tool stats from thinking_events ──
    tool_rows = conn.execute(
        "SELECT step_type FROM thinking_events WHERE run_id=? AND step_type NOT IN ('submit_decision','memory_read','memory_write')",
        (run_id,),
    ).fetchall()
    tool_calls: dict[str, int] = {}
    for r in tool_rows:
        tool_calls[r["step_type"]] = tool_calls.get(r["step_type"], 0) + 1

    # ── Bottleneck state (most transitions from) ──
    trans_rows = conn.execute(
        "SELECT from_state_id, COUNT(*) as cnt FROM transitions WHERE run_id=? GROUP BY from_state_id ORDER BY cnt DESC",
        (run_id,),
    ).fetchall()
    bottleneck = trans_rows[0]["from_state_id"] if trans_rows else "?"

    # ── Completion status ──
    status_row = conn.execute(
        "SELECT status FROM runs WHERE run_id=?", (run_id,),
    ).fetchone()
    completed = status_row and status_row["status"] == "completed"

    # ── Counts for summary ──
    decs_count = conn.execute(
        "SELECT COUNT(*) as c FROM decisions WHERE run_id=?", (run_id,),
    ).fetchone()["c"]
    msgs_count = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE run_id=?", (run_id,),
    ).fetchone()["c"]

    # ── Agent scores (deterministic: based on tool calls + decisions) ──
    agent_rows = conn.execute(
        "SELECT DISTINCT role_id FROM thinking_events WHERE run_id=?", (run_id,),
    ).fetchall()
    agent_scores: dict[str, int] = {}
    for ar in agent_rows:
        aid = ar["role_id"]
        a_tools = conn.execute(
            "SELECT COUNT(*) as c FROM thinking_events WHERE run_id=? AND role_id=? AND step_type NOT IN ('submit_decision','memory_read','memory_write')",
            (run_id, aid),
        ).fetchone()["c"]
        a_decs = conn.execute(
            "SELECT COUNT(*) as c FROM decisions WHERE run_id=? AND role_id=?",
            (run_id, aid),
        ).fetchone()["c"]
        # Deterministic: base 70, +2 per tool call (max +20), +5 per decision (max +10)
        score = 70 + min(a_tools * 2, 20) + min(a_decs * 5, 10)
        agent_scores[aid] = min(100, score)

    # ── Success score ──
    success_score = 85 if completed else max(30, 50 - len(trans_rows) * 5)

    summary = (
        f"{'Completed' if completed else 'Active/Aborted'}. "
        f"{decs_count} decisions, {msgs_count} messages, "
        f"{len(tool_calls)} tool types across {len(agent_scores)} agents. "
        f"Bottleneck: {bottleneck}."
    )

    store.save_run_performance(
        run_id=run_id,
        success_score=success_score,
        summary=summary,
        agent_scores=agent_scores,
        bottleneck_state=bottleneck,
        tool_stats=tool_calls,
        suggestions="",
    )

    logger.info("quick_evaluate: run=%s score=%d bottleneck=%s", run_id, success_score, bottleneck)
    return store.load_run_performance(run_id)