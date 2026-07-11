"""Runtime Trace analysis CLI — analyze, diff, budget, and export commands.

Usage:
    python -m runtime_trace.cli.analyze <run_id> [--json]
    python -m runtime_trace.cli.analyze diff <run_id_a> <run_id_b>
    python -m runtime_trace.cli.analyze budget <run_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_trace.observer import _find_runs_dir, _get_store
from runtime_trace.trace_query import TraceQueryEngine


def _resolve_store(run_id: str) -> tuple:
    """Resolve a run_id to (RuntimeStore, runs_dir)."""
    runs_dir = _find_runs_dir()
    store = _get_store(run_id, runs_dir)
    if store is None:
        print(f"Error: run '{run_id}' not found in {runs_dir}", file=sys.stderr)
        sys.exit(1)
    return store, runs_dir


def cmd_analyze(args: argparse.Namespace) -> None:
    """Render a text DAG of the trace span tree with per-state timing."""
    store, _ = _resolve_store(args.run_id)
    engine = TraceQueryEngine(store)

    if args.json:
        result = _build_json_output(engine, args.run_id)
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return

    summary = engine.trace_analyze(args.run_id)
    _print_text_dag(engine, summary)


def cmd_diff(args: argparse.Namespace) -> None:
    """Compare two runs' decision sequences and timeline."""
    store_a, _ = _resolve_store(args.run_id_a)
    store_b, _ = _resolve_store(args.run_id_b)
    engine_a = TraceQueryEngine(store_a)
    engine_b = TraceQueryEngine(store_b)

    summary_a = engine_a.trace_analyze(args.run_id_a)
    summary_b = engine_b.trace_analyze(args.run_id_b)

    print(f"=== Diff: {args.run_id_a} vs {args.run_id_b} ===\n")

    # Compare wall time
    diff_ms = summary_b["wall_time_ms"] - summary_a["wall_time_ms"]
    sign = "+" if diff_ms >= 0 else ""
    print(f"Wall time: {summary_a['wall_time_ms']}ms → {summary_b['wall_time_ms']}ms ({sign}{diff_ms}ms)")
    print(f"Span count: {summary_a['trace_span_count']} → {summary_b['trace_span_count']}")
    print(f"Round count: {summary_a['round_count']} → {summary_b['round_count']}")
    print()

    # Compare decisions
    all_values = set(list(summary_a["decision_summary"].keys()) +
                     list(summary_b["decision_summary"].keys()))
    for v in sorted(all_values):
        ca = summary_a["decision_summary"].get(v, 0)
        cb = summary_b["decision_summary"].get(v, 0)
        if ca != cb:
            print(f"  {v}: {ca} → {cb}")

    print()
    if summary_a.get("suggestions") or summary_b.get("suggestions"):
        print("Suggestions:")
        for s in summary_b.get("suggestions", []):
            print(f"  [B] {s}")
        for s in summary_a.get("suggestions", []):
            print(f"  [A] {s}")


def cmd_budget(args: argparse.Namespace) -> None:
    """Report round count, per-round timing, and optimization suggestions."""
    store, _ = _resolve_store(args.run_id)
    engine = TraceQueryEngine(store)
    summary = engine.trace_analyze(args.run_id)

    print(f"=== Budget: {args.run_id} ===\n")
    print(f"Round count: {summary['round_count']}")
    print(f"Wall time: {summary['wall_time_ms']}ms")
    print(f"Total spans: {summary['trace_span_count']}")
    print(f"Transitions: {summary['transition_count']}")
    print()

    if summary["decision_summary"]:
        print("Decision distribution:")
        for v, c in sorted(summary["decision_summary"].items()):
            print(f"  {v}: {c}")
        print()

    if summary.get("suggestions"):
        print("Optimization suggestions:")
        for s in summary["suggestions"]:
            print(f"  {s}")

    # Average timing per round
    if summary["round_count"] > 0:
        avg_ms = summary["wall_time_ms"] / summary["round_count"]
        print(f"\nAverage time per round: {avg_ms:.0f}ms")


def _build_json_output(engine: TraceQueryEngine, run_id: str) -> dict:
    """Build full JSON output with trace_tree, summary, decisions, messages."""
    summary = engine.trace_analyze(run_id)
    store = engine._store
    conn = store.connect()

    # Try to get a trace_id from the first trace event
    trace_row = conn.execute(
        "SELECT trace_id FROM trace_events WHERE run_id=? LIMIT 1", (run_id,)
    ).fetchone()
    trace_tree = engine.trace_tree(trace_row["trace_id"]) if trace_row else None

    # Fetch decisions and messages
    dec_rows = conn.execute(
        "SELECT * FROM decisions WHERE run_id=? ORDER BY created_at", (run_id,)
    ).fetchall()
    msg_rows = conn.execute(
        "SELECT * FROM messages WHERE run_id=? ORDER BY created_at", (run_id,)
    ).fetchall()

    return {
        "run_id": run_id,
        "trace_tree": trace_tree,
        "summary": {
            "wall_time_ms": summary["wall_time_ms"],
            "trace_span_count": summary["trace_span_count"],
            "round_count": summary["round_count"],
            "transition_count": summary["transition_count"],
        },
        "decisions": [dict(r) for r in dec_rows],
        "messages": [dict(r) for r in msg_rows],
    }


def _print_text_dag(engine: TraceQueryEngine, summary: dict) -> None:
    """Render a human-readable text DAG from the analysis summary."""
    run_id = summary["run_id"]
    print(f"=== Trace Analysis: {run_id} ===\n")
    print(f"Wall time: {summary['wall_time_ms']}ms")
    print(f"Spans: {summary['trace_span_count']}")
    print(f"Rounds: {summary['round_count']}")
    print()

    # Print event type timing as a pseudo-DAG
    timing = summary.get("event_type_timing", {})
    if timing:
        print("Span timing by event type:")
        for et, t in sorted(timing.items(), key=lambda x: -x[1]["total_ms"]):
            bar = "█" * max(1, t["total_ms"] // 100)
            print(f"  {et:30s} {bar} {t['count']}x ({t['total_ms']}ms)")
        print()

    # Decisions
    if summary["decision_summary"]:
        print("Decisions:")
        for v, c in sorted(summary["decision_summary"].items()):
            print(f"  {v}: {c}")
        print()

    # Suggestions
    if summary.get("suggestions"):
        print("Suggestions:")
        for s in summary["suggestions"]:
            print(f"  - {s}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Runtime Trace analysis CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m runtime_trace.cli.analyze <run_id>
  python -m runtime_trace.cli.analyze <run_id> --json
  python -m runtime_trace.cli.analyze diff <run_id_a> <run_id_b>
  python -m runtime_trace.cli.analyze budget <run_id>
        """,
    )
    sub = parser.add_subparsers(dest="command")

    # analyze (default)
    p_analyze = sub.add_parser("analyze", help="Analyze a flow run trace")
    p_analyze.add_argument("run_id", help="Run ID to analyze")
    p_analyze.add_argument("--json", action="store_true", help="Output as JSON")
    p_analyze.set_defaults(func=cmd_analyze)

    # diff
    p_diff = sub.add_parser("diff", help="Compare two flow runs")
    p_diff.add_argument("run_id_a", help="First run ID")
    p_diff.add_argument("run_id_b", help="Second run ID")
    p_diff.set_defaults(func=cmd_diff)

    # budget
    p_budget = sub.add_parser("budget", help="Report budget and optimization suggestions")
    p_budget.add_argument("run_id", help="Run ID to analyze")
    p_budget.set_defaults(func=cmd_budget)

    # Default: if no subcommand, try analyze with positional
    ns, remaining = parser.parse_known_args()
    if ns.command:
        ns.func(ns)
    elif remaining:
        # Legacy mode: python -m runtime_trace.cli.analyze <run_id>
        ns = parser.parse_args(["analyze"] + remaining)
        ns.func(ns)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
