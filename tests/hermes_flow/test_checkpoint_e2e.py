"""End-to-end checkpoint/resume test — simulates full agent session lifecycle.

Tests:
1. Fresh init → tool execution → checkpoint saved
2. Simulated crash → resume from checkpoint
3. Resume → submit_decision → checkpoint deleted
4. Idempotency: agent with decision doesn't re-execute
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Ensure agent-pool modules are importable ──────────────────────────────────

_agent_pool_dir = str(Path(__file__).resolve().parents[2] / "experiments" / "agent-pool")
if _agent_pool_dir not in sys.path:
    sys.path.insert(0, _agent_pool_dir)


def _load_auto_debate():
    import importlib.util
    path = Path(_agent_pool_dir) / "auto-debate.py"
    spec = importlib.util.spec_from_file_location("auto_debate_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Import tool_registry separately (we patch it before auto-debate functions use it)
import tool_registry as _tool_registry_mod

# engine.llm_client is where call_llm_tools actually lives (session.py calls it
# via `llm_client.call_llm_tools(...)`), so patches must target this module.
import engine.llm_client as _llm_client_mod

from hermes_flow.schemas import AgentSessionState
from hermes_flow.storage import RuntimeStore
from hermes_flow.hooks import reset_bus, emit, Hook, subscribe


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store():
    """Create a temporary RuntimeStore with schema."""
    with tempfile.TemporaryDirectory() as td:
        store = RuntimeStore(td)
        store.init_schema()
        yield store


@pytest.fixture
def wired_store(temp_store):
    """Store with hook handlers wired (like run_flow does)."""
    run_id = "test-e2e-001"
    reset_bus()

    def on_turn_end(hook, payload):
        state = payload.get("state", {})
        temp_store.save_agent_session_checkpoint(
            json.dumps(state, ensure_ascii=False, default=str),
            state.get("run_id", run_id),
            state.get("role_id", ""),
            state.get("state_id", ""),
        )

    def on_session_done(hook, payload):
        temp_store.delete_agent_session_checkpoint(
            run_id, payload.get("role_id", ""), payload.get("state_id", ""),
        )

    subscribe(Hook.TURN_END, on_turn_end)
    subscribe(Hook.SESSION_DONE, on_session_done)

    return temp_store, run_id


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tool_call_response(fn_name: str, args: dict) -> dict:
    """Mock LLM response with a single tool call."""
    return {
        "content": "",
        "tool_calls": [{
            "id": "call_test_001",
            "function": {
                "name": fn_name,
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }],
    }


def _make_decision_response(value: str = "APPROVE", reason: str = "done") -> dict:
    """Mock LLM response with submit_decision."""
    return _make_tool_call_response("submit_decision", {"value": value, "reason": reason})


# ── Tests ────────────────────────────────────────────────────────────────────


class TestCheckpointE2E:
    """Full agent session checkpoint/resume cycle."""

    def test_tool_turn_checkpoint_then_decision_cleanup(self, wired_store):
        """Tool execution → checkpoint saved at turn.end → decision → deleted."""
        store, run_id = wired_store
        mod = _load_auto_debate()

        state = mod._init_agent_session_state(
            role_id="test-agent",
            soul="You are a test agent.",
            goal="Test checkpoint",
            state_id="TEST",
            round_n=1,
            history=[],
            inbox=[],
            gate={"required_roles": ["test-agent"], "pass_values": ["APPROVE"]},
            tool_schemas=[],
            agents={},
            output_artifacts=[],
            prev_artifacts=None,
            store=store,
            run_id=run_id,
            write_scope=["output/"],
            flow_overview="",
        )

        assert state.turn == 0

        # Mock LLM: tool call → decision. Since `from tool_registry import execute_tool`
        # runs inside _run_session_loop, patching tool_registry before the call works.
        call_count = [0]

        def mock_llm(system, messages, tools, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_tool_call_response("write_file", {"path": "test.txt", "content": "hello"})
            return _make_decision_response()

        with patch.object(_llm_client_mod, "call_llm_tools", mock_llm):
            with patch.object(_tool_registry_mod, "execute_tool", return_value={"ok": True}):
                with patch.object(_tool_registry_mod, "format_tool_results_for_llm",
                                  return_value="ok: wrote test.txt"):
                    result = mod._run_session_loop(state, store, run_id)

        assert call_count[0] == 2
        assert result["value"] == "APPROVE"
        ckpt = store.load_agent_session_checkpoint(run_id, "test-agent", "TEST")
        assert ckpt is None, "checkpoint deleted after session.done"

    def test_resume_from_checkpoint_mid_session(self, wired_store):
        """Load a synthetic checkpoint → resume and complete."""
        store, run_id = wired_store
        mod = _load_auto_debate()

        # Simulate a checkpoint saved after turn 1 (tool execution completed)
        # This mimics what happens at turn.end when the process crashes before turn 2
        from dataclasses import asdict
        ckpt = AgentSessionState(
            run_id=run_id,
            role_id="test-agent",
            state_id="TEST",
            round_n=1,
            system_prompt="You are a test agent.",
            messages_json=json.dumps([
                {"role": "user", "content": "[TEST 状态 · gate 第 1 轮]"},
                {"role": "user", "content": "(本轮可用 100 次工具调用，已用 0 次)"},
                {"role": "user", "content": "请完成 TEST 状态的工作。"},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "write_file", "arguments": '{"path":"out.txt","content":"x"}'}}
                ]},
                {"role": "tool", "tool_call_id": "c1", "content": "ok: wrote out.txt"},
                {"role": "user", "content": "[TEST 状态 · gate 第 1 轮] (剩余 99/100 次工具调用)"},
            ]),
            tools_json="[]",
            turn=1,
            max_turns=100,
            tool_calls_made=1,
        )
        store.save_agent_session_checkpoint(
            json.dumps(asdict(ckpt), ensure_ascii=False, default=str),
            run_id, "test-agent", "TEST",
        )

        # Verify checkpoint exists
        ckpt_raw = store.load_agent_session_checkpoint(run_id, "test-agent", "TEST")
        assert ckpt_raw is not None
        loaded = AgentSessionState(**ckpt_raw)
        assert loaded.turn == 1, f"expected turn=1, got {loaded.turn}"
        assert loaded.tool_calls_made == 1

        # ── Resume: mock LLM returns decision ──────
        reset_bus()
        subscribe(Hook.SESSION_DONE, lambda h, p: store.delete_agent_session_checkpoint(
            run_id, p.get("role_id", ""), p.get("state_id", ""),
        ))

        def mock_llm(system, messages, tools, **kwargs):
            return _make_decision_response()

        with patch.object(_llm_client_mod, "call_llm_tools", mock_llm):
            result = mod._run_session_loop(loaded, store, run_id)

        assert result["value"] == "APPROVE"
        ckpt_after = store.load_agent_session_checkpoint(run_id, "test-agent", "TEST")
        assert ckpt_after is None, "checkpoint deleted after completion"

    def test_idempotent_skip_when_decision_exists(self, wired_store):
        """Agent with existing decision is skipped."""
        store, run_id = wired_store
        mod = _load_auto_debate()

        # Insert run + decision
        conn = store.connect()
        conn.execute(
            "INSERT INTO runs(run_id,flow_id,flow_version,status,current_state_id,"
            "round_counters,created_at,updated_at,agent_bindings,agent_specs,"
            "memory_modes,artifact_root) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "test-flow", "1", "active", "TEST", "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "[]", "{}", "{}", "output/"),
        )
        conn.execute(
            "INSERT INTO decisions(decision_id,run_id,state_id,role_id,value,reason,artifacts,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("dec-001", run_id, "TEST", "test-agent", "APPROVE", "already decided", "[]",
             "2026-01-01T00:00:00"),
        )
        conn.commit()

        result = mod._run_agent_session(
            role_id="test-agent", soul="You are a test agent.", goal="test",
            state_id="TEST", round_n=1,
            history=[], inbox=[],
            gate={"required_roles": ["test-agent"], "pass_values": ["APPROVE"]},
            tool_schemas=[], agents={}, output_artifacts=[], prev_artifacts=None,
            store=store, run_id=run_id,
            write_scope=["output/"], flow_overview="",
        )

        assert result["value"] == "APPROVE"
        assert result["reason"].startswith("[skip]")
        assert result["tool_calls"] == 0

    def test_checkpoint_state_messages_roundtrip(self):
        """AgentSessionState JSON roundtrip preserves conversation integrity."""
        state = AgentSessionState(
            run_id="test-roundtrip", role_id="writer", state_id="DOC", round_n=3,
            system_prompt="You write docs.",
            messages_json=json.dumps([
                {"role": "user", "content": "write docs"},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "write_file", "arguments": '{"path":"doc.md"}'}}
                ]},
                {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            ]),
            tools_json=json.dumps([{"type": "function", "function": {"name": "write_file"}}]),
            turn=5, max_turns=100, tool_calls_made=3,
            empty_fails=1, last_empty_tool="search_files",
        )

        from dataclasses import asdict
        raw = asdict(state)
        loaded = AgentSessionState(**json.loads(json.dumps(raw, ensure_ascii=False)))

        assert loaded.run_id == "test-roundtrip"
        assert loaded.turn == 5
        assert loaded.tool_calls_made == 3
        assert loaded.empty_fails == 1

        msgs = json.loads(loaded.messages_json)
        assert len(msgs) == 3
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "write_file"
        assert msgs[2]["content"] == "ok"
