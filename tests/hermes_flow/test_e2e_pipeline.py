"""End-to-end pipeline test — drives the REAL _run_fsm_loop, not a hand-rolled copy.

Tests the multi-state IMPLEMENT→REVIEW→DONE pipeline with a reviewer
rejecting work once, forcing the implementer to re-execute.

Root cause (to be confirmed): agent_has_decision doesn't filter by round/cutoff,
so on re-entry the implementer sees stale decisions and skips execution.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Ensure agent-pool modules are importable ──────────────────────────────────
_agent_pool_dir = str(Path(__file__).resolve().parents[2] / "experiments" / "agent-pool")
if _agent_pool_dir not in sys.path:
    sys.path.insert(0, _agent_pool_dir)

from hermes_flow.hooks import reset_bus
from hermes_flow.storage import RuntimeStore
from hermes_flow.tools import flow_init


def _load_auto_debate():
    import importlib.util
    path = Path(_agent_pool_dir) / "auto-debate.py"
    spec = importlib.util.spec_from_file_location("auto_debate_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FLOW_ID = "test-pipeline"

_FLOW_YAML = f"""flow_id: {_FLOW_ID}
name: e2e-pipeline-test
version: 1
initial_state_id: IMPLEMENT
terminal_state_ids: [DONE, ABORT]
agents:
  implementer:
    profile_name: pool-implementer
    soul: "You write code."
    write_scope: [output/{_FLOW_ID}/]
  code-reviewer:
    profile_name: pool-code-reviewer
    soul: "You review code."
    write_scope: [output/{_FLOW_ID}/]
states:
  IMPLEMENT:
    description: Write the code
    actors: [implementer]
    write_scope: [output/test-pipeline/]
    gate:
      type: decision
      required_roles: [implementer]
      pass_values: [APPROVE]
      fail_values: [REQUEST_CHANGES]
      blocked_values: [BLOCKED]
      on_pass: REVIEW
      on_fail: IMPLEMENT
      max_rounds: 3
    output_artifacts: [code.py]
  REVIEW:
    description: Review the code
    actors: [code-reviewer]
    gate:
      type: decision
      required_roles: [code-reviewer]
      pass_values: [APPROVE]
      fail_values: [REQUEST_CHANGES]
      blocked_values: [BLOCKED]
      on_pass: DONE
      on_fail: IMPLEMENT
      max_rounds: 3
  DONE:
    terminal: true
    actors: []
  ABORT:
    terminal: true
    actors: []
"""

# Path where the artifact should be created (relative to project_root)
_ARTIFACT_RELPATH = f"output/{_FLOW_ID}/code.py"


def _setup_run(tmp_path: Path):
    """Initialize flow and return (run_id, store, project_root).

    Must run BEFORE _load_auto_debate() so PROJECT_ROOT binds to tmp_path.
    """
    yaml_path = tmp_path / "test-flow.yaml"
    yaml_path.write_text(_FLOW_YAML)

    project_root = str(tmp_path)
    os.environ["HERMES_FLOW_PROJECT_ROOT"] = project_root
    os.environ["HERMES_FLOW_RUNS_DIR"] = str(tmp_path / ".hermes-flow" / "runs")
    os.environ["HERMES_WORKSPACE_ROOT"] = project_root

    result = flow_init(project_root, str(yaml_path), "test-run")
    assert result.get("ok"), f"flow_init failed: {result}"
    run_id = result["run_id"]

    from hermes_flow.run_paths import get_run_dir
    run_dir = get_run_dir(run_id, project_root)
    store = RuntimeStore(run_dir)
    store.init_schema()

    return run_id, store, project_root


class TestPipelineE2E:
    """Drive the REAL _run_fsm_loop with a truthful mock LLM.

    The mock LLM emits write_file + submit_decision in one response for
    IMPLEMENT rounds (write_file MUST come before submit_decision in
    tool_calls, because submit_decision triggers `continue` in the loop).
    """

    def test_review_reject_then_implementer_retries(self, tmp_path):
        """IMPLEMENT(ok)→REVIEW(reject)→IMPLEMENT(retry)→REVIEW(ok)→DONE.

        Setup order: _setup_run FIRST (binds PROJECT_ROOT to tmp_path),
        THEN _load_auto_debate (imports engine.config).
        """
        run_id, store, project_root = _setup_run(tmp_path)         # ← FIRST
        mod = _load_auto_debate()                                   # ← SECOND
        reset_bus()

        agents = {
            "implementer": {"soul": "write code", "role": "coder"},
            "code-reviewer": {"soul": "review code", "role": "reviewer"},
        }

        # ── Deterministic LLM: write_file THEN submit_decision ──
        # IMPLEMENT rounds return 2 tool_calls (write before decide).
        # REVIEW rounds return 1 tool_call (decide only).
        _seq = [0]

        def _tools_write_then_decide(value: str, reason: str, content: str = "# test") -> dict:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": json.dumps({
                                "path": _ARTIFACT_RELPATH,
                                "content": content,
                            }),
                        },
                    },
                    {
                        "id": "call_decide",
                        "type": "function",
                        "function": {
                            "name": "submit_decision",
                            "arguments": json.dumps({"value": value, "reason": reason}),
                        },
                    },
                ],
            }

        def _mock_llm(system, messages, tools, **kwargs):
            _seq[0] += 1
            n = _seq[0]
            if n == 1:   # IMPLEMENT round 1: write + approve
                return _tools_write_then_decide("APPROVE", "code written")
            elif n == 2: # REVIEW: reject
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_decide",
                        "type": "function",
                        "function": {
                            "name": "submit_decision",
                            "arguments": json.dumps({"value": "REQUEST_CHANGES", "reason": "needs fixes"}),
                        },
                    }],
                }
            elif n == 3: # IMPLEMENT round 2: write + approve (retry)
                return _tools_write_then_decide("APPROVE", "fixed the issues", "# fixed")
            else:        # REVIEW: approve
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_decide",
                        "type": "function",
                        "function": {
                            "name": "submit_decision",
                            "arguments": json.dumps({"value": "APPROVE", "reason": "looks good"}),
                        },
                    }],
                }

        # ── Realistic tool mock: write_file actually creates files ──
        _workspace_root = Path(project_root)

        def _smart_execute_tool(tool_id, args, agent_id=""):
            if tool_id == "write_file":
                fp = Path(args.get("path", ""))
                if not fp.is_absolute():
                    fp = _workspace_root / fp
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(args.get("content", "pass\n"), encoding="utf-8")
                return {"ok": True, "tool": tool_id}
            if tool_id == "search_files":
                return {"ok": True, "tool": tool_id, "matches": []}
            if tool_id == "file_read":
                return {"ok": True, "tool": tool_id, "content": "ok"}
            if tool_id == "terminal":
                return {"ok": True, "tool": tool_id, "output": ""}
            if tool_id == "skill_load":
                return {"ok": True, "tool": tool_id, "content": "# Skill\n\nUse write_file to create code."}
            return {"ok": True, "tool": tool_id}

        def _format_results(tool_id, result):
            return str(result.get("content", result.get("output", "ok")))

        # Pre-create artifact directory so product gate passes
        _artifact_dir = Path(project_root) / "output" / "test-pipeline"
        _artifact_dir.mkdir(parents=True, exist_ok=True)
        (_artifact_dir / "code.py").write_text("# placeholder", encoding="utf-8")
        _artifact_path = str(_artifact_dir / "code.py")

        with patch("engine.llm_client.call_llm_tools", _mock_llm):
            with patch("tool_registry.execute_tool", _smart_execute_tool):
                with patch("tool_registry.format_tool_results_for_llm", _format_results):
                    with patch("engine.evaluate.capture_run_metrics"):
                        with patch("engine.fsm.find_output_artifact",
                                   return_value=(_artifact_dir / "code.py", "ok")):
                            # Wire hook handlers — required for SESSION_DECIDE persistence
                            from engine.hooks_wiring import make_hook_handlers
                            make_hook_handlers(store, run_id)
                            mod._run_fsm_loop(store, run_id, "test goal",
                                             ["implementer", "code-reviewer"], agents)

        # ── Assertions ──
        conn = store.connect()

        # 0. LLM was called — actual count depends on whether implementer
        #    re-enters or gets skipped. After fix: >=4 (2 impl + 2 review).
        assert _seq[0] >= 3, f"Expected >=3 LLM calls, got {_seq[0]}"

        # 1. Run completed successfully
        row = conn.execute(
            "SELECT status, current_state_id FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        assert row is not None, "Run not found"
        assert row["status"] == "completed", f"Expected completed, got {row['status']}"
        assert row["current_state_id"] == "DONE", f"Expected DONE, got {row['current_state_id']}"

        # 2. Transition path includes the retry
        trans = conn.execute(
            "SELECT from_state_id, to_state_id FROM transitions WHERE run_id=? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        path = [(t["from_state_id"], t["to_state_id"]) for t in trans]
        assert ("IMPLEMENT", "REVIEW") in path, f"Missing IMPLEMENT→REVIEW in {path}"
        assert ("REVIEW", "IMPLEMENT") in path, f"Missing REVIEW→IMPLEMENT (retry) in {path}"

        # 3. Both agents decided at least twice
        decs = conn.execute(
            "SELECT state_id, role_id, value FROM decisions WHERE run_id=? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        impl_decs = [d for d in decs if d["role_id"] == "implementer"]
        rev_decs = [d for d in decs if d["role_id"] == "code-reviewer"]
        assert len(impl_decs) >= 2, f"Expected >=2 implementer decisions, got {len(impl_decs)}: {impl_decs}"
        assert len(rev_decs) >= 2, f"Expected >=2 reviewer decisions, got {len(rev_decs)}: {rev_decs}"
        assert rev_decs[0]["value"] == "REQUEST_CHANGES", \
            f"Expected first review REQUEST_CHANGES, got {rev_decs[0]['value']}"
