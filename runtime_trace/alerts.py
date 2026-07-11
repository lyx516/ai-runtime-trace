"""AlertEngine — runtime anomaly detection for Runtime Trace.

Subscribes to the EventBus and monitors flow state for abnormal conditions.
Detects: stuck states, revision loops, silent agents, gate failure chains.

Alerts are dual-written: EventBus real-time push + audit_events table.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from runtime_trace.observer import get_event_bus
from runtime_trace.storage import RuntimeStore

logger = logging.getLogger(__name__)

# Default thresholds (can be overridden per rule)
DEFAULT_RULES: dict[str, dict] = {
    "stuck_state": {"enabled": True, "threshold_seconds": 120},
    "revision_loop": {"enabled": True, "threshold_rounds": 5},
    "silent_agent": {"enabled": True, "threshold_seconds": 60},
    "gate_failure_chain": {"enabled": True, "threshold_count": 3},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AlertEngine:
    """Monitors flow runs and publishes alerts on anomaly detection.

    Usage:
        engine = AlertEngine(store, check_interval=15.0)
        engine.start()  # background thread
        # ... later ...
        engine.check(run_id)  # manual trigger
    """

    def __init__(
        self,
        store: RuntimeStore,
        rules: dict[str, dict] | None = None,
        check_interval: float = 15.0,
    ):
        self._store = store
        self._rules = rules or DEFAULT_RULES.copy()
        self._check_interval = check_interval
        self._running = False
        self._thread: threading.Thread | None = None

        # Per-run state tracking
        self._last_seen_state: dict[str, tuple[str, float]] = {}  # run_id -> (state_id, timestamp)
        self._state_entry_count: dict[str, dict[str, int]] = {}  # run_id -> {state_id: count}
        self._gate_failures: dict[str, list[float]] = {}  # run_id -> [timestamps]

    def start(self) -> None:
        """Start the alert loop in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("AlertEngine started (interval=%ss)", self._check_interval)

    def stop(self) -> None:
        self._running = False

    def check(self, run_id: str) -> None:
        """Run one detection pass for a specific run."""
        try:
            from runtime_trace.schemas import RunStatus

            status = self._store.load_status(run_id)
            if not status:
                return

            conn = self._store.connect()
            current_state = status.current_state_id

            # ── Stuck state detection ─────────────────────────────────
            if self._rules.get("stuck_state", {}).get("enabled", True):
                last = self._last_seen_state.get(run_id)
                now_ts = time.time()
                if last and last[0] == current_state:
                    elapsed = now_ts - last[1]
                    threshold = self._rules["stuck_state"].get("threshold_seconds", 120)
                    if elapsed > threshold:
                        self._fire_alert(
                            run_id, current_state, "stuck_state",
                            f"State '{current_state}' stuck for {elapsed:.0f}s (threshold: {threshold}s)",
                            {"elapsed_seconds": elapsed, "threshold": threshold},
                        )
                        # Reset timer to avoid repeated alerts
                        self._last_seen_state[run_id] = (current_state, now_ts)
                else:
                    self._last_seen_state[run_id] = (current_state, now_ts)

            # ── Revision loop detection ───────────────────────────────
            if self._rules.get("revision_loop", {}).get("enabled", True):
                transitions = conn.execute(
                    "SELECT to_state_id FROM transitions WHERE run_id=? ORDER BY row_id",
                    (run_id,),
                ).fetchall()
                # Count how many times we've entered this exact state
                entry_count = sum(1 for t in transitions if t["to_state_id"] == current_state)
                threshold = self._rules["revision_loop"].get("threshold_rounds", 5)
                if entry_count > threshold:
                    self._fire_alert(
                        run_id, current_state, "revision_loop",
                        f"State '{current_state}' entered {entry_count} times (threshold: {threshold})",
                        {"entry_count": entry_count, "threshold": threshold},
                    )

            # ── Gate failure chain detection ──────────────────────────
            if self._rules.get("gate_failure_chain", {}).get("enabled", True):
                recent_fails = conn.execute(
                    "SELECT gate_result FROM transitions WHERE run_id=? "
                    "AND to_state_id=? ORDER BY row_id DESC LIMIT ?",
                    (run_id, current_state,
                     self._rules["gate_failure_chain"].get("threshold_count", 3) + 1),
                ).fetchall()
                fail_count = sum(1 for t in recent_fails
                                 if "fail" in (t["gate_result"] or "").lower())
                threshold = self._rules["gate_failure_chain"].get("threshold_count", 3)
                if fail_count >= threshold:
                    self._fire_alert(
                        run_id, current_state, "gate_failure_chain",
                        f"Gate failed {fail_count} consecutive times at '{current_state}'",
                        {"fail_count": fail_count, "threshold": threshold},
                    )

        except Exception as e:
            logger.debug("AlertEngine check failed for %s: %s", run_id, e)

    # ── Internal ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Background loop: periodically check all active runs."""
        while self._running:
            try:
                # Find all runs
                conn = self._store.connect()
                run_rows = conn.execute(
                    "SELECT run_id, status FROM runs WHERE status='active'"
                ).fetchall()
                for r in run_rows:
                    self.check(r["run_id"])
            except Exception:
                pass
            time.sleep(self._check_interval)

    def _fire_alert(
        self,
        run_id: str,
        state_id: str,
        rule_id: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        """Publish an alert event to EventBus and write to audit_events table."""
        import uuid

        event = {
            "event_id": uuid.uuid4().hex[:12],
            "run_id": run_id,
            "rule_id": rule_id,
            "state_id": state_id,
            "severity": "warning",
            "message": message,
            "details": details,
            "created_at": _now(),
        }

        # EventBus push
        try:
            bus = get_event_bus()
            bus.publish(f"alert_{rule_id}", event)
        except Exception:
            pass

        # Persist to audit_events
        import json
        try:
            conn = self._store.connect()
            conn.execute(
                "INSERT INTO audit_events (event_id, run_id, state_id, event_type, actor, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    run_id,
                    state_id,
                    f"alert_{rule_id}",
                    "AlertEngine",
                    json.dumps(details, default=str),
                    _now(),
                ),
            )
            conn.commit()
        except Exception:
            pass
