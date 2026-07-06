"""Hook wiring — register persistent handlers on the hook bus.

Connects agent-loop events (emit) to RuntimeStore persistence.
Called once at the start of run_flow() / resume_flow().
"""

from __future__ import annotations

import json
from uuid import uuid4 as _uuid4

from hermes_flow.hooks import Hook, subscribe
from hermes_flow.tools import flow_decide as _flow_decide


def make_hook_handlers(store, run_id: str):
    """Register hook handlers that close over a RuntimeStore.

    Agent loop emits hooks — these handlers do the actual persistence.
    Called once at the start of run_flow().
    """

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
        """Save decision from submit_decision tool call via flow_decide.

        Uses flow_decide (not raw INSERT) so audit events are recorded and
        the decision path is unified.  fsm.py does NOT call flow_decide
        separately — this hook is the single write path.
        """
        try:
            _flow_decide(
                run_id=payload.get("run_id", run_id),
                state_id=payload.get("state_id", ""),
                role_id=payload.get("role_id", ""),
                value=payload.get("value", ""),
                reason=payload.get("reason", ""),
            )
        except Exception:
            pass

    subscribe(Hook.LLM_DONE, on_llm_done)
    subscribe(Hook.TOOL_DONE, on_tool_done)
    subscribe(Hook.TURN_END, on_turn_end)
    subscribe(Hook.SESSION_DECIDE, on_session_decide)
    subscribe(Hook.SESSION_DONE, on_session_done)