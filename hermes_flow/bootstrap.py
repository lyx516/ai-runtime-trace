"""Runtime bootstrap — centralizes hook handler registration and observer bridge.

Centralizes hook persistence so every entry point (run_flow, resume_flow,
EvolutionAgent session, tests) gets identical behavior.

Design:
- bootstrap_runtime() registers persistence handlers + observer bridge
- Idempotent within a single bus lifecycle (safe to call multiple times)
- Does NOT call reset_bus() — caller controls bus lifecycle
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4 as _uuid4

from hermes_flow.hooks import (
    Hook,
    HookHandler,
    install_observer_bridge,
    subscribe,
)
from hermes_flow.schemas import Decision
from hermes_flow.storage import RuntimeStore

logger = logging.getLogger(__name__)


def _register_persistence_handlers(store: RuntimeStore, run_id: str) -> None:
    """Register the shared hook-to-SQLite persistence handlers.

    Idempotent: skips if already registered in the current bus lifecycle
    (checked via _is_persistence flag on on_run_completed).
    """

    # Skip if already registered (prevent duplicate handlers on re-bootstrap
    # without reset_bus in between)
    from hermes_flow.hooks import get_bus as _get_bus
    existing = _get_bus()._handlers.get(Hook.RUN_COMPLETED, [])
    if any(getattr(h, "_is_persistence", False) for h in existing):
        return

    def _serialize_state(state_dict: dict) -> str:
        return json.dumps(state_dict, ensure_ascii=False, default=str)

    def on_llm_done(hook: str, payload: dict) -> None:
        try:
            store.append_llm_input_snapshot(
                run_id=run_id,
                session_id=payload.get("role_id", ""),
                role_id=payload.get("role_id", ""),
                state_id=payload.get("state_id", ""),
                provider=payload.get("provider", ""),
                model=payload.get("model", ""),
                messages=payload.get("messages", []),
                request=payload.get("request", {}),
                context_packet=payload.get("context_packet", {}),
            )
        except Exception:
            pass

    def on_tool_done(hook: str, payload: dict) -> None:
        try:
            store.append_thinking_event(
                run_id=run_id,
                role_id=payload.get("role_id", ""),
                state_id=payload.get("state_id", ""),
                step_type=payload.get("fn_name", "unknown"),
                inputs=payload.get("inputs", {}),
                output=payload.get("result", {}),
            )
        except Exception:
            pass

    def on_turn_end(hook: str, payload: dict) -> None:
        state = payload.get("state", {})
        store.save_agent_session_checkpoint(
            _serialize_state(state),
            state.get("run_id", run_id),
            state.get("role_id", ""),
            state.get("state_id", ""),
        )

    def on_session_done(hook: str, payload: dict) -> None:
        store.delete_agent_session_checkpoint(
            run_id,
            payload.get("role_id", ""),
            payload.get("state_id", ""),
        )

    def on_session_decide(hook: str, payload: dict) -> None:
        """Save decision from submit_decision tool call."""
        try:
            store.record_decision(Decision(
                decision_id=_uuid4().hex[:12],
                run_id=payload.get("run_id", run_id),
                state_id=payload.get("state_id", ""),
                role_id=payload.get("role_id", ""),
                value=payload.get("value", ""),
                reason=payload.get("reason", ""),
                artifacts=[],
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
        except Exception:
            pass

    def on_message_sent(hook: str, payload: dict) -> None:
        """Persist message + inbox entries via store API."""
        try:
            msg_id = payload.get("message_id") or _uuid4().hex[:12]
            store.save_message(
                message_id=msg_id,
                run_id=payload.get("run_id", run_id),
                state_id=payload.get("state_id", ""),
                from_role=payload.get("from_role", ""),
                intended_recipients=payload.get("recipients", []),
                authorized_recipients=payload.get("recipients", []),
                recipient_availability={r: True for r in payload.get("recipients", [])},
                visibility=payload.get("visibility", "targeted"),
                kind=payload.get("kind", "question"),
                content=payload.get("content", ""),
                delivery_outcome=payload.get("delivery_outcome", "delivered"),
                rejection_reason=payload.get("rejection_reason", ""),
            )
        except Exception:
            logger.warning("on_message_sent handler failed", exc_info=True)

    def on_run_completed(hook: str, payload: dict) -> None:
        """Trigger deterministic quick evaluation when a run completes."""
        try:
            from hermes_flow.evaluator import quick_evaluate
            quick_evaluate(store, payload.get("run_id", run_id))
        except Exception:
            logger.warning("quick_evaluate failed", exc_info=True)

    on_run_completed._is_persistence = True  # type: ignore[attr-defined]

    subscribe(Hook.LLM_DONE, on_llm_done)
    subscribe(Hook.TOOL_DONE, on_tool_done)
    subscribe(Hook.TURN_END, on_turn_end)
    subscribe(Hook.SESSION_DECIDE, on_session_decide)
    subscribe(Hook.SESSION_DONE, on_session_done)
    subscribe(Hook.MESSAGE_SENT, on_message_sent)
    subscribe(Hook.RUN_COMPLETED, on_run_completed)


def bootstrap_runtime(
    store: RuntimeStore,
    run_id: str,
    *,
    enable_observer: bool = True,
    observer_port: int = 8765,
    project_root: str = "",
) -> None:
    """Wire up runtime infrastructure: persistence handlers + observer bridge.

    Call after reset_bus(). Does NOT call reset_bus() itself — caller
    controls bus lifecycle.

    Parameters:
        store: RuntimeStore for this run
        run_id: Run identifier
        enable_observer: Start observer HTTP server + install SSE bridge.
            Set False for EvolutionAgent sessions (no SSE needed).
        observer_port: Port for observer (default 8765)
        project_root: Project root for observer run discovery
    """
    _register_persistence_handlers(store, run_id)

    if enable_observer:
        from hermes_flow.observer import ensure_observer, get_event_bus
        ensure_observer(port=observer_port, project_root=project_root)
        install_observer_bridge(get_event_bus())