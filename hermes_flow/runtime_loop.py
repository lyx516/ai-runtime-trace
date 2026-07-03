"""Runtime Loop — event-driven daemon that drives the FSM forward automatically.

The RuntimeLoop polls the RuntimeStore every tick_interval seconds and performs:
1. Inbox dispatch: check each actor role for unread inbox entries → schedule sessions
2. Session collection: check for completed session result files → process decisions
3. Gate evaluation: if all required roles have submitted decisions → evaluate_gate → advance_state
4. Idle timeout detection: if state has idle_timeout_seconds exceeded → advance_state
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from hermes_flow.agent_runner import build_agent_prompt, run_session as run_agent_session
from hermes_flow.agent_session import prepare_context, write_context_file, parse_result
from hermes_flow.delegate_spawner import (
    add_session_to_manifest,
    mark_session_completed,
    get_pending_sessions,
)
from hermes_flow.engine import advance_state, detect_idle_timeout, evaluate_gate
from hermes_flow.errors import RuntimeStateError
from hermes_flow.observer import get_event_bus
from hermes_flow.alerts import AlertEngine
from hermes_flow.schemas import Decision, FlowStatus, RunStatus, _now
from hermes_flow.storage import RuntimeStore
from hermes_flow.trace import get_tracer

logger = logging.getLogger(__name__)

# Session files live under .hermes-flow/runs/<run_id>/sessions/
SESSION_DIR_NAME = "sessions"


class RuntimeLoop:
    """Per-run event loop that drives the FSM forward automatically.

    Usage:
        loop = RuntimeLoop(run_id, store, tick_interval=1.0)
        loop.start()  # blocks until run reaches terminal state
    """

    def __init__(
        self,
        run_id: str,
        store: RuntimeStore,
        tick_interval: float = 1.0,
        session_dir: str | None = None,
        spawn_mode: str = "subprocess",
    ):
        self.run_id = run_id
        self._store = store
        self.tick_interval = tick_interval
        self.spawn_mode = spawn_mode  # "subprocess" or "delegate"
        self._running = False

        # Thread-local store: each thread opens its own connection
        self._thread_store: RuntimeStore | None = None

        # Session file directory
        if session_dir:
            self.session_dir = Path(session_dir)
        else:
            self.session_dir = Path(self.store.run_dir) / SESSION_DIR_NAME
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Active session tracking: role_id -> session_info
        self._active_sessions: dict[str, dict[str, Any]] = {}

        # Track the last-entered state so we can dispatch on first entry
        self._last_state_id: str | None = None
        self._roles_dispatched_for_state: set[str] = set()

        # Alert engine (optional, lazy init)
        self._alert_engine: AlertEngine | None = None

    @property
    def store(self) -> RuntimeStore:
        """Get a thread-safe store instance.

        Returns the thread-local store if running in a background thread,
        otherwise the original store.
        """
        if self._thread_store is not None:
            return self._thread_store
        return self._store

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the event loop. Blocks until the run reaches a terminal state."""

        # Initialize thread-local store if this is a new thread
        import threading
        if threading.current_thread() is not threading.main_thread():
            from hermes_flow.storage import RuntimeStore as RS
            self._thread_store = RS(self._store.run_dir)
            self._thread_store.init_schema()
            # Reset tracer for background thread — SqliteTracer isn't thread-safe
            from hermes_flow.trace import NoOpTracer as NOT, set_tracer as st
            st(NOT())

        tracer = get_tracer()
        with tracer.span("runtime_loop", inputs={"run_id": self.run_id, "tick_interval": self.tick_interval}) as span:
            self._running = True
            tick_count = 0
            while self._running:
                tick_count += 1
                tick_start = time.time()
                self._tick()
                elapsed = time.time() - tick_start
                sleep_time = max(0, self.tick_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            span.outputs = {"ticks": tick_count, "final_status": "terminal"}

    def stop(self) -> None:
        """Signal the loop to stop after the current tick."""
        self._running = False

    # ── Per-tick logic ────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Execute one iteration of the runtime loop."""
        tracer = get_tracer()
        with tracer.span("loop_tick", inputs={"run_id": self.run_id}) as span:
            try:
                run = self.store.load_status(self.run_id)
            except (RuntimeStateError, Exception) as e:
                logger.warning("load_status failed: %s", e)
                span.outputs = {"error": str(e)}
                self._running = False
                return

            # Stop if terminal
            if run.status in (RunStatus.COMPLETED, RunStatus.ABORTED):
                self._running = False
                span.outputs = {"status": run.status.value, "state": run.current_state_id}
                return

            actions = []

            # 0. Detect state change — dispatch actors on first entry
            if run.current_state_id != self._last_state_id:
                self._last_state_id = run.current_state_id
                self._roles_dispatched_for_state = set()
                first_entry = self._dispatch_first_entry(run)
                if first_entry:
                    actions.append(f"first_entry:{','.join(first_entry)}")

            # Alert check — lazy init AlertEngine
            if self._alert_engine is None:
                try:
                    self._alert_engine = AlertEngine(self.store)
                except Exception:
                    pass
            if self._alert_engine is not None:
                try:
                    self._alert_engine.check(self.run_id)
                except Exception:
                    pass

            # 1. Inbox dispatch
            dispatched = self._dispatch_from_inboxes(run)
            if dispatched:
                actions.append(f"dispatched:{','.join(dispatched)}")

            # 2. Collect completed session results
            collected = self._collect_session_results(run)
            if collected:
                actions.append(f"collected:{','.join(collected)}")

            # 3. Gate evaluation
            gate_advanced = self._try_evaluate_gate(run)
            if gate_advanced:
                actions.append("gate_advanced")

            # 4. Idle timeout
            timeout_advanced = self._check_idle_timeout(run)
            if timeout_advanced:
                actions.append("timeout_advanced")

            span.outputs = {"actions": actions, "state": run.current_state_id}

            # Publish observable event
            try:
                bus = get_event_bus()
                bus.publish("loop_tick", {
                    "run_id": self.run_id,
                    "state": run.current_state_id,
                    "status": run.status.value,
                    "actions": actions,
                })
            except Exception:
                pass

    # ── State entry dispatch ────────────────────────────────────────────

    def _dispatch_first_entry(self, run: FlowStatus) -> list[str]:
        """When entering a new state for the first time, dispatch all actors.

        Returns list of role_ids that were scheduled.
        """
        actors = self._get_state_actors(run.current_state_id)
        scheduled = []

        for role_id in actors:
            if role_id in self._active_sessions:
                continue

            session_id = uuid.uuid4().hex[:12]
            session = self._schedule_session(session_id, role_id, run)
            if session:
                self._active_sessions[role_id] = session
                scheduled.append(role_id)
                self._roles_dispatched_for_state.add(role_id)

        return scheduled

    # ── Inbox dispatch ────────────────────────────────────────────────────

    def _get_state_actors(self, state_id: str) -> list[str]:
        """Get the list of actor role IDs for a state."""
        conn = self.store.connect()
        row = conn.execute(
            "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
            (self.run_id, state_id),
        ).fetchone()
        if row is None:
            return []
        state_dict = json.loads(row["state_json"])
        return state_dict.get("actors", [])

    def _get_agent_soul(self, role_id: str) -> str:
        """Get the soul/personality from the agent bindings."""
        conn = self.store.connect()
        run_row = conn.execute(
            "SELECT agent_bindings FROM runs WHERE run_id = ?",
            (self.run_id,),
        ).fetchone()
        if run_row and run_row["agent_bindings"]:
            try:
                agents = json.loads(run_row["agent_bindings"])
                for a in agents:
                    if a.get("role_id") == role_id:
                        profile = a.get("profile_name", "")
                        if profile:
                            return profile
            except (json.JSONDecodeError, KeyError):
                pass
        # Fallback: return role_id as identity
        return f"Agent {role_id}"

    def _has_unread_inbox(self, role_id: str) -> bool:
        """Check if a role has any unread inbox entries."""
        conn = self.store.connect()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM inboxes WHERE run_id = ? AND role_id = ?",
            (self.run_id, role_id),
        ).fetchone()
        return row["cnt"] > 0

    def _schedule_session(self, session_id: str, role_id: str,
                          run: FlowStatus) -> dict[str, Any] | None:
        """Create context packet, write file, and (optionally) spawn the session.

        Returns session info dict, or None if scheduling fails.
        """
        # Build rich context packet using agent_session module
        try:
            context = prepare_context(
                run_id=self.run_id,
                role_id=role_id,
                store=self.store,
                state_id=run.current_state_id,
            )
            context["session_id"] = session_id
            # Inject round counter for the delegate goal
            context["_round_counter"] = run.round_counters.get(run.current_state_id, 0)
        except (ValueError, Exception) as e:
            logger.warning("Failed to prepare context for %s: %s", role_id, e)
            return None

        # Add soul from agent bindings
        context["soul"] = self._get_agent_soul(role_id)

        # Build the agent prompt (FR-005) and embed it
        context["agent_prompt"] = build_agent_prompt(context)

        # Write context file
        context_file = self.session_dir / f"{session_id}.context.json"
        try:
            write_context_file(context, str(self.store.run_dir))
        except Exception as e:
            logger.warning("Failed to write context file for %s: %s", role_id, e)
            return None

        result_file = self.session_dir / f"{session_id}.result.json"

        session_info = {
            "session_id": session_id,
            "role_id": role_id,
            "context_file": str(context_file),
            "result_file": str(result_file),
            "started_at": _now(),
        }

        self.store.append_audit_event(
            run_id=self.run_id,
            event_type="agent_session_scheduled",
            state_id=run.current_state_id,
            actor=role_id,
            payload={
                "session_id": session_id,
                "context_file": str(context_file),
                "result_file": str(result_file),
            },
        )

        # Spawn the session
        if self.spawn_mode == "subprocess":
            try:
                import threading
                t = threading.Thread(
                    target=run_agent_session,
                    args=(str(context_file), str(result_file)),
                    daemon=True,
                )
                t.start()
            except Exception as e:
                logger.warning("Failed to spawn agent session for %s: %s", role_id, e)
        elif self.spawn_mode == "delegate":
            # Don't spawn — write to manifest for Hermes agent to pick up
            add_session_to_manifest(
                run_dir=str(self.store.run_dir),
                run_id=self.run_id,
                session_id=session_id,
                role_id=role_id,
                state_id=run.current_state_id,
                context_file=str(context_file),
                result_file=str(result_file),
            )

        return session_info

    def _dispatch_from_inboxes(self, run: FlowStatus) -> list[str]:
        """Check each actor role for unread inbox. Schedule sessions for roles that need them.

        Returns list of role_ids that were scheduled.
        """
        actors = self._get_state_actors(run.current_state_id)
        scheduled = []

        for role_id in actors:
            # Skip if already has an active session
            if role_id in self._active_sessions:
                continue

            if self._has_unread_inbox(role_id):
                session_id = uuid.uuid4().hex[:12]
                session = self._schedule_session(session_id, role_id, run)
                if session:
                    self._active_sessions[role_id] = session
                    scheduled.append(role_id)

        return scheduled

    # ── Session result collection ─────────────────────────────────────────

    def _collect_session_results(self, run: FlowStatus) -> list[str]:
        """Poll for completed session result files and process actions.

        Returns list of role_ids whose results were processed.
        """
        completed = []
        to_remove = []

        for role_id, session in self._active_sessions.items():
            result_file = Path(session["result_file"])
            if result_file.exists():
                try:
                    with open(result_file) as f:
                        result = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to parse result for %s: %s", role_id, e)
                    to_remove.append(role_id)
                    continue

                # Process actions from the result
                actions = result.get("actions_taken", [])
                consumed_message_ids: list[str] = []
                for action in actions:
                    action_type = action.get("type")
                    if action_type == "submit_decision":
                        self._process_submit_decision(action, role_id, run)
                    elif action_type == "message_send":
                        self._process_message_send(action, role_id, run)
                    elif action_type == "inbox_read":
                        mid = action.get("message_id", "")
                        if mid:
                            consumed_message_ids.append(mid)
                    # Other action types (read_artifact, write_artifact) are no-ops

                # Remove consumed inbox entries so they don't trigger re-dispatch
                if consumed_message_ids:
                    conn2 = self.store.connect()
                    placeholders = ",".join("?" * len(consumed_message_ids))
                    conn2.execute(
                        f"DELETE FROM inboxes WHERE run_id = ? AND message_id IN ({placeholders})",
                        (self.run_id, *consumed_message_ids),
                    )
                    conn2.commit()

                self.store.append_audit_event(
                    run_id=self.run_id,
                    event_type="agent_session_completed",
                    state_id=run.current_state_id,
                    actor=role_id,
                    payload={"session_id": session["session_id"], "actions": len(actions)},
                )

                completed.append(role_id)
                to_remove.append(role_id)

                # Mark completed in manifest for delegate mode
                if self.spawn_mode == "delegate":
                    try:
                        mark_session_completed(
                            str(self.store.run_dir), session["session_id"]
                        )
                    except Exception:
                        pass

        for role_id in to_remove:
            del self._active_sessions[role_id]

        return completed

    def _process_submit_decision(self, action: dict, role_id: str, run: FlowStatus) -> None:
        """Process a submit_decision action from a session result."""
        from hermes_flow.schemas import Decision as DecisionSchema

        now = _now()
        decision = DecisionSchema(
            decision_id=uuid.uuid4().hex[:12],
            run_id=self.run_id,
            state_id=run.current_state_id,
            role_id=role_id,
            value=action.get("value", ""),
            reason=action.get("reason", ""),
            artifacts=[],
            created_at=now,
        )
        self.store.record_decision(decision)
        self.store.append_audit_event(
            run_id=self.run_id,
            event_type="decision_recorded",
            state_id=run.current_state_id,
            actor=role_id,
            payload={"decision_value": decision.value, "reason": decision.reason},
        )

    def _process_message_send(self, action: dict, role_id: str, run: FlowStatus) -> None:
        """Process a message_send action from a session result."""
        from hermes_flow.tools import flow_send

        flow_send(
            run_id=self.run_id,
            state_id=run.current_state_id,
            from_role=role_id,
            intended_recipients=action.get("recipients", []),
            kind=action.get("kind", "message"),
            content=action.get("content", ""),
        )

    # ── Gate evaluation ───────────────────────────────────────────────────

    def _try_evaluate_gate(self, run: FlowStatus) -> bool:
        """Check if all required roles have submitted decisions and evaluate gate.

        Returns True if a state transition occurred.
        """
        conn = self.store.connect()
        state_row = conn.execute(
            "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
            (self.run_id, run.current_state_id),
        ).fetchone()
        if state_row is None:
            return False

        state_dict = json.loads(state_row["state_json"])
        gate = state_dict.get("gate")
        if gate is None:
            return False  # No gate — no automatic transition (Clarify Q2)

        required_roles = gate.get("required_roles", [])
        if not required_roles:
            return False

        # Load decisions for the current round group
        from hermes_flow.engine import evaluate_gate

        try:
            result = evaluate_gate(self.run_id, run.current_state_id, self.store)
        except RuntimeStateError:
            return False

        if result.next_state_id:
            from hermes_flow.engine import advance_state

            # Check if target is a human escalation state
            target_row = conn.execute(
                "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
                (self.run_id, result.next_state_id),
            ).fetchone()
            target_human = False
            if target_row:
                target_dict = json.loads(target_row["state_json"])
                target_human = target_dict.get("human", False)

            advance_state(
                self.run_id,
                run.current_state_id,
                result.next_state_id,
                result.reason,
                result.round,
                self.store,
            )
            # Clear active sessions since we've left the state
            self._active_sessions.clear()
            self._roles_dispatched_for_state.clear()
            # Force re-dispatch on next tick (handles self-loop on_fail)
            self._last_state_id = None

            if target_human:
                logger.info(
                    "Flow '%s' reached human escalation state '%s' (reason: %s). "
                    "Loop paused. Use flow_resume() to continue.",
                    self.run_id, result.next_state_id, result.reason,
                )
                self.store.append_audit_event(
                    run_id=self.run_id,
                    event_type="human_escalation",
                    state_id=run.current_state_id,
                    actor="system",
                    payload={
                        "from_state": run.current_state_id,
                        "to_state": result.next_state_id,
                        "reason": result.reason,
                        "round": result.round,
                    },
                )
                self._running = False  # Pause loop — human must intervene

            return True

        return False

    # ── Idle timeout ──────────────────────────────────────────────────────

    def _check_idle_timeout(self, run: FlowStatus) -> bool:
        """Check idle timeout and advance if exceeded. Returns True if advanced."""
        from hermes_flow.engine import advance_state, detect_idle_timeout

        timeout_result = detect_idle_timeout(self.run_id, run.current_state_id, self.store)
        if timeout_result and timeout_result.timeout_exceeded and timeout_result.next_state_id:
            from hermes_flow.engine import advance_state

            # Check if target is a human escalation state
            conn = self.store.connect()
            target_row = conn.execute(
                "SELECT state_json FROM states WHERE run_id = ? AND state_id = ?",
                (self.run_id, timeout_result.next_state_id),
            ).fetchone()
            target_human = False
            if target_row:
                target_dict = json.loads(target_row["state_json"])
                target_human = target_dict.get("human", False)

            round_counter = run.round_counters.get(run.current_state_id, 1)
            advance_state(
                self.run_id,
                run.current_state_id,
                timeout_result.next_state_id,
                "idle_timeout",
                round_counter,
                self.store,
            )
            self._active_sessions.clear()
            # Force re-dispatch on next tick (handles self-loop on_fail)
            self._last_state_id = None

            if target_human:
                logger.info(
                    "Flow '%s' reached human escalation via idle timeout. "
                    "Loop paused. Use flow_resume() to continue.",
                    self.run_id,
                )
                self.store.append_audit_event(
                    run_id=self.run_id,
                    event_type="human_escalation",
                    state_id=run.current_state_id,
                    actor="system",
                    payload={
                        "from_state": run.current_state_id,
                        "to_state": timeout_result.next_state_id,
                        "reason": "idle_timeout",
                        "round": round_counter,
                    },
                )
                self._running = False

            return True

        return False
