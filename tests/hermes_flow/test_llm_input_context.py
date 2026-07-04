"""Tests for capturing exact LLM input payloads."""

import json
from pathlib import Path

from hermes_flow.agent_runner import _llm_decide_actions
from hermes_flow.storage import RuntimeStore


class _FakeResponse:
    def read(self) -> bytes:
        return json.dumps({
            "choices": [{"message": {"content": json.dumps({"value": "APPROVE", "reason": "ok"})}}]
        }).encode()


def test_llm_decide_actions_persists_real_request_before_call(tmp_project_root: Path, monkeypatch) -> None:
    """The LLM decision path must snapshot the actual messages sent to the provider."""
    run_id = "llm-capture"
    run_dir = tmp_project_root / ".hermes-flow" / "runs" / run_id
    run_dir.mkdir(parents=True)
    store = RuntimeStore(run_dir)
    store.init_schema()
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("AGENT_LLM_MODEL", "test-model")
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=30: _FakeResponse())

    context = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "session_id": "sess1",
        "role_id": "planner",
        "state_id": "PLAN",
        "state_description": "Plan the work",
        "soul": "Plan with evidence.",
        "gate_info": {"required_roles": ["planner"], "pass_values": ["APPROVE"]},
        "available_tools": ["inbox_read"],
    }

    actions = _llm_decide_actions(context, [], {})
    snapshots = store.load_llm_input_snapshots(run_id, role_id="planner", state_id="PLAN")

    assert actions is not None
    assert snapshots[0]["source"] == "llm_input_snapshot"
    assert snapshots[0]["model"] == "test-model"
    assert snapshots[0]["messages"][0]["role"] == "system"
    assert "autonomous agent" in snapshots[0]["messages"][0]["content"]
    assert snapshots[0]["messages"][1]["role"] == "user"
    assert "# Flow Run: llm-capture" in snapshots[0]["messages"][1]["content"]
