"""Observer agent-context API tests."""

import json
from pathlib import Path

from hermes_flow.observer import SSEHandler
from hermes_flow.schemas import (
    AgentBinding,
    Decision,
    MemoryMode,
    MessageEnvelope,
    _now,
)
from hermes_flow.storage import RuntimeStore


def test_agent_context_reads_session_packet_and_reconstructs_visible_context(tmp_project_root: Path) -> None:
    run_id = "ctx-test"
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / run_id
    store = RuntimeStore(run_dir)
    states = {
        "PLAN": {
            "description": "Plan the work",
            "actors": ["architect", "implementer"],
            "gate": {"required_roles": ["architect", "implementer"], "pass_values": ["APPROVE"]},
        },
        "DONE": {"terminal": True},
    }
    store.create_run(
        flow_id="test-flow",
        flow_version="1",
        initial_state_id="PLAN",
        agent_bindings=[
            AgentBinding("architect", "fp", "", MemoryMode.RUN_ISOLATED),
            AgentBinding("implementer", "fp", "", MemoryMode.RUN_ISOLATED),
        ],
        memory_modes={"architect": "run_isolated", "implementer": "run_isolated"},
        artifact_root=str(run_dir / "artifacts"),
        states_json=states,
        override_run_id=run_id,
    )

    msg = MessageEnvelope(
        message_id="msg1",
        run_id=run_id,
        state_id="PLAN",
        from_role="architect",
        intended_recipients=["implementer"],
        authorized_recipients=["implementer"],
        kind="proposal",
        content="use existing graph view",
        created_at=_now(),
    )
    store.record_message_attempt(msg)
    store.add_inbox_entries(run_id, "implementer", "PLAN", ["msg1"])
    store.record_decision(Decision(
        decision_id="dec1",
        run_id=run_id,
        state_id="PLAN",
        role_id="implementer",
        value="APPROVE",
        reason="looks good",
        created_at=_now(),
    ))
    store.append_thinking_event(
        run_id,
        "implementer",
        "PLAN",
        "read_inbox",
        inputs={"limit": 20},
        output={"message_ids": ["msg1"]},
    )
    store.append_audit_event(
        run_id,
        "agent_session_scheduled",
        state_id="PLAN",
        actor="implementer",
        payload={"context_file": "sess1.context.json"},
    )
    store.append_llm_input_snapshot(
        run_id=run_id,
        session_id="sess1",
        role_id="implementer",
        state_id="PLAN",
        provider="https://openrouter.ai/api/v1",
        model="test-model",
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "# Flow Run\nreal prompt"},
        ],
        request={"model": "test-model", "messages": [{"role": "system", "content": "system prompt"}]},
        context_packet={"session_id": "sess1", "role_id": "implementer"},
    )

    session_dir = run_dir / "sessions"
    session_dir.mkdir(parents=True)
    packet = {
        "run_id": run_id,
        "session_id": "sess1",
        "role_id": "implementer",
        "state_id": "PLAN",
        "state_description": "Plan the work",
        "inbox_messages": [{"message_id": "msg1", "content": "use existing graph view"}],
        "created_at": _now(),
    }
    (session_dir / "sess1.context.json").write_text(json.dumps(packet))

    handler = object.__new__(SSEHandler)
    handler.runs_dir = tmp_project_root / ".hermes-flow" / "runs"

    data = handler._get_agent_context(run_id, "implementer", "PLAN")

    assert data["context_source"] == "session_file"
    assert data["context_packet"]["session_id"] == "sess1"
    assert data["state_definition"]["description"] == "Plan the work"
    assert data["inbox_messages"][0]["message_id"] == "msg1"
    assert data["visible_messages"][0]["content"] == "use existing graph view"
    assert data["visible_messages"][0]["authorized_recipients"] == ["implementer"]
    assert data["decisions_seen"][0]["reason"] == "looks good"
    assert data["thinking_events"][0]["step_type"] == "read_inbox"
    assert data["audit_events"][0]["event_type"] == "agent_session_scheduled"
    assert data["llm_input"]["source"] == "llm_input_snapshot"
    assert data["llm_input"]["model"] == "test-model"
    assert data["llm_input"]["messages"][0]["content"] == "system prompt"
