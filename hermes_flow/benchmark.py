"""Benchmark — measure trace framework overhead and performance characteristics.

Usage:
    python -m hermes_flow.benchmark
    python -m hermes_flow.benchmark --agent-count 5
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_agent_session_simulated(
    store: Any,
    run_id: str,
    role_id: str,
    state_id: str,
    trace_enabled: bool,
) -> float:
    """Simulate an agent session with or without tracing to measure overhead."""
    from hermes_flow.trace import get_tracer, set_tracer, SqliteTracer, NoOpTracer
    from hermes_flow.observer import get_event_bus

    if trace_enabled:
        set_tracer(SqliteTracer(store))
    else:
        set_tracer(NoOpTracer())

    tracer = get_tracer()
    bus = get_event_bus()

    start = time.time()
    # Simulate: read_inbox, send_message, submit_decision
    with tracer.span("agent_inbox_read", inputs={"role_id": role_id}):
        bus.publish("agent_thinking", {"role_id": role_id, "step_type": "read_inbox"})
        time.sleep(0.001)  # 1ms I/O simulation

    with tracer.span("agent_message_send", inputs={"role_id": role_id}):
        bus.publish("agent_thinking", {"role_id": role_id, "step_type": "send_message"})
        time.sleep(0.001)

    with tracer.span("agent_submit_decision", inputs={"role_id": role_id, "value": "APPROVE"}):
        bus.publish("agent_thinking", {"role_id": role_id, "step_type": "submit_decision"})
        time.sleep(0.001)

    elapsed = time.time() - start
    return elapsed


def run_benchmark(agent_count: int = 3) -> dict[str, Any]:
    """Run a benchmark comparing trace-enabled vs trace-disabled performance.

    Returns a dict with overhead percentage and timing distributions.
    """
    import tempfile
    from pathlib import Path

    from hermes_flow.storage import RuntimeStore

    # Create a temp run directory
    tmpdir = tempfile.mkdtemp(prefix="hermes-benchmark-")
    run_dir = Path(tmpdir) / "runs" / "benchmark-run"
    run_dir.mkdir(parents=True, exist_ok=True)

    store = RuntimeStore(run_dir)
    store.init_schema()
    conn = store.connect()

    # Create a mock run in the store
    conn.execute(
        "INSERT OR IGNORE INTO runs (run_id, flow_id, flow_version, status, current_state_id, "
        "created_at, updated_at, artifact_root) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("benchmark-run", "benchmark", "1.0", "active", "BENCH",
         _now(), _now(), str(run_dir)),
    )
    conn.commit()

    run_id = "benchmark-run"
    results: dict[str, list[float]] = {"trace_enabled": [], "trace_disabled": []}

    # Warm-up
    run_agent_session_simulated(store, run_id, "warmup", "BENCH", trace_enabled=True)
    run_agent_session_simulated(store, run_id, "warmup", "BENCH", trace_enabled=False)

    # Trace-disabled runs
    for i in range(agent_count):
        dur = run_agent_session_simulated(
            store, run_id, f"agent-{i}", "BENCH", trace_enabled=False
        )
        results["trace_disabled"].append(dur)

    # Trace-enabled runs
    for i in range(agent_count):
        dur = run_agent_session_simulated(
            store, run_id, f"agent-{i}", "BENCH", trace_enabled=True
        )
        results["trace_enabled"].append(dur)

    # Compute stats
    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {"min": 0, "max": 0, "avg": 0, "total": 0}
        return {
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "avg": round(sum(vals) / len(vals), 4),
            "total": round(sum(vals), 4),
        }

    stats_disabled = _stats(results["trace_disabled"])
    stats_enabled = _stats(results["trace_enabled"])

    # Overhead calculation
    avg_disabled = stats_disabled["avg"] or 0.001
    overhead_pct = round(
        (stats_enabled["avg"] - avg_disabled) / avg_disabled * 100, 2
    )

    benchmark_result = {
        "timestamp": _now(),
        "agent_count": agent_count,
        "trace_disabled": stats_disabled,
        "trace_enabled": stats_enabled,
        "trace_overhead_pct": overhead_pct,
        "status": "pass" if overhead_pct < 5 else "warn",
    }

    # Clean up
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    return benchmark_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes Flow Benchmark")
    parser.add_argument(
        "--agent-count", type=int, default=3,
        help="Number of simulated agent sessions (default: 3)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = run_benchmark(agent_count=args.agent_count)

    if args.json:
        import json as j
        print(j.dumps(result, indent=2, default=str))
        return

    print("=== Hermes Flow Benchmark ===\n")
    print(f"  Agent sessions: {result['agent_count']}")
    print(f"  Trace disabled: avg={result['trace_disabled']['avg']*1000:.1f}ms "
          f"total={result['trace_disabled']['total']*1000:.1f}ms")
    print(f"  Trace enabled:  avg={result['trace_enabled']['avg']*1000:.1f}ms "
          f"total={result['trace_enabled']['total']*1000:.1f}ms")
    print(f"  Trace overhead:  {result['trace_overhead_pct']}% "
          f"({'PASS' if result['status'] == 'pass' else 'WARN'})")
    print(f"\n  Status: {'✓ < 5% target' if result['status'] == 'pass' else '⚠ > 5%'}")


if __name__ == "__main__":
    main()
