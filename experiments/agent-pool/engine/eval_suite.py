#!/usr/bin/env python3
"""eval_suite — cross-run evaluation reports from all state.sqlite databases.

Usage: .venv/bin/python experiments/agent-pool/engine/eval_suite.py [--json]

Three reports:
  1. Run completion rate by flow type
  2. Per-agent tool usage distribution
  3. Bottleneck state heatmap (by stage)
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RUNS_ROOT = PROJECT_ROOT / "experiments" / "agent-pool" / ".hermes-flow" / "runs"


def _connect_all_runs():
    dbs = []
    if not RUNS_ROOT.exists():
        return dbs
    for d in sorted(RUNS_ROOT.iterdir()):
        sqlite = d / "state.sqlite"
        if sqlite.exists():
            conn = sqlite3.connect(str(sqlite))
            conn.row_factory = sqlite3.Row
            dbs.append((d.name, conn))
    return dbs


def report_1_completion():
    """Report 1: Run completion rate by flow type."""
    rows = []
    for run_id, conn in _connect_all_runs():
        r = conn.execute(
            "SELECT status, COALESCE(flow_id,'?') as flow FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not r:
            continue
        perf = conn.execute(
            "SELECT tool_stats FROM run_performance WHERE run_id=?", (run_id,)
        ).fetchone()
        seconds = 0
        if perf:
            try:
                seconds = json.loads(perf["tool_stats"]).get("total_seconds", 0)
            except Exception:
                pass
        rows.append({"flow": r["flow"][:30], "status": r["status"], "seconds": seconds})

    by_flow = defaultdict(lambda: {"total": 0, "completed": 0, "seconds": 0.0})
    for r in rows:
        by_flow[r["flow"]]["total"] += 1
        if r["status"] == "completed":
            by_flow[r["flow"]]["completed"] += 1
        by_flow[r["flow"]]["seconds"] += r["seconds"]

    print("\n" + "=" * 70)
    print("📊 Report 1: Run Completion Rate by Flow Type")
    print("=" * 70)
    print(f"{'Flow':<30s} {'Total':>6s} {'Done':>6s} {'%':>6s} {'Avg s':>8s}")
    print("-" * 70)
    for flow, stats in sorted(by_flow.items(), key=lambda x: -x[1]["total"]):
        rate = stats["completed"] / stats["total"] * 100 if stats["total"] else 0
        avg = stats["seconds"] / stats["total"] if stats["total"] else 0
        print(f"{flow:<30s} {stats['total']:>6d} {stats['completed']:>6d} {rate:>5.0f}% {avg:>7.0f}s")

    return [{**stats, "flow": flow} for flow, stats in by_flow.items()]


def report_2_agent_tools():
    """Report 2: Per-agent tool usage distribution."""
    agents = defaultdict(lambda: defaultdict(int))
    for run_id, conn in _connect_all_runs():
        run_status = conn.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not run_status or run_status["status"] != "completed":
            continue
        for r in conn.execute(
            "SELECT role_id, step_type, COUNT(*) as cnt FROM thinking_events "
            "WHERE step_type NOT IN ('llm_call','submit_decision','agent_message_send') "
            "GROUP BY role_id, step_type ORDER BY cnt DESC"
        ):
            agents[r["role_id"]][r["step_type"]] += r["cnt"]

    print("\n" + "=" * 70)
    print("📊 Report 2: Per-Agent Tool Usage Distribution")
    print("=" * 70)
    for agent_id in sorted(agents.keys()):
        tools = agents[agent_id]
        total = sum(tools.values())
        top3 = sorted(tools.items(), key=lambda x: -x[1])[:4]
        print(f"\n  🤖 {agent_id} ({total} total calls)")
        for tool, count in top3:
            pct = count / total * 100 if total else 0
            print(f"      {tool:<20s} {count:>5d} ({pct:>4.0f}%)")

    return {agent: dict(tools) for agent, tools in agents.items()}


def report_3_bottleneck():
    """Report 3: Bottleneck state heatmap."""
    state_calls = defaultdict(int)
    state_count = defaultdict(int)
    for run_id, conn in _connect_all_runs():
        perf = conn.execute(
            "SELECT tool_stats, success_score FROM run_performance WHERE run_id=?", (run_id,)
        ).fetchone()
        if not perf or perf["success_score"] < 40:
            continue
        try:
            ts = json.loads(perf["tool_stats"])
            for state, data in ts.get("by_state", {}).items():
                if isinstance(data, dict):
                    state_calls[state] += data.get("total", 0)
                    state_count[state] += 1
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("📊 Report 3: Bottleneck State Heatmap")
    print("=" * 70)
    print(f"{'State':<20s} {'Runs':>6s} {'Total calls':>14s} {'Avg/run':>10s}")
    print("-" * 70)
    sorted_states = sorted(state_calls.items(), key=lambda x: -x[1])
    for state, calls in sorted_states[:10]:
        runs = state_count.get(state, 1)
        avg = calls / runs if runs else 0
        bar = "█" * max(1, int(calls / max(1, sorted_states[0][1]) * 30))
        print(f"{state:<20s} {runs:>6d} {calls:>14d} {avg:>9.0f}  {bar}")

    return [{"state": s, "total_calls": c, "runs": state_count.get(s, 0)} for s, c in sorted_states]


def main():
    import sys
    as_json = "--json" in sys.argv

    r1 = report_1_completion()
    r2 = report_2_agent_tools()
    r3 = report_3_bottleneck()

    if as_json:
        print(json.dumps({"completion": r1, "agent_tools": r2, "bottleneck": r3}, indent=2, ensure_ascii=False))

    print(f"\n✅ eval_suite complete. {len(_connect_all_runs())} run databases scanned.")
    # Cleanup
    for _, conn in _connect_all_runs():
        conn.close()


if __name__ == "__main__":
    main()
