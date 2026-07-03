#!/usr/bin/env python3
"""Agent Session Runner — executes an agent session with dynamic decision-making.

The agent reads its context, calls agent_tools.py functions via subprocess
to check inbox and flow state, then dynamically decides what actions to take
based on the actual messages and gate conditions.

In subprocess mode (testing): runs locally via subprocess.
In delegate mode (production): designed to be run inside a Hermes
delegate_task subagent via its terminal tool.

Usage:
    python -m hermes_flow.agent_runner \\
        --context /path/to/session.context.json \\
        --result /path/to/session.result.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Agent tool invocations via subprocess ───────────────────────────────

def _tool_call(tool_expr: str) -> dict[str, Any]:
    """Call an agent_tools function via python -c subprocess.

    This is the same pattern a Hermes subagent uses with its terminal tool.
    Returns the JSON output from the tool call.
    """
    code = (
        f"import json, sys; {tool_expr}; "
        f"print(json.dumps(result)); sys.stdout.flush()"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return {"error": proc.stderr.strip()}
        output = proc.stdout.strip()
        if not output:
            return {"error": "empty output"}
        return json.loads(output)
    except json.JSONDecodeError:
        return {"error": "parse error"}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)}


def agent_inbox_read(run_id: str, role_id: str) -> list[dict[str, Any]]:
    """Read actual inbox from the flow store."""
    result = _tool_call(
        f"from hermes_flow.agent_tools import agent_inbox_read; "
        f"result = agent_inbox_read(run_id={json.dumps(run_id)}, "
        f"role_id={json.dumps(role_id)})"
    )
    if isinstance(result, dict) and "error" in result:
        return []
    return result if isinstance(result, list) else []


def agent_query_status(run_id: str) -> dict[str, Any]:
    """Query actual flow status."""
    result = _tool_call(
        f"from hermes_flow.agent_tools import agent_query_status; "
        f"result = agent_query_status(run_id={json.dumps(run_id)})"
    )
    return result if isinstance(result, dict) else {}


def agent_submit_decision(
    run_id: str, role_id: str, state_id: str,
    value: str, reason: str,
) -> dict[str, Any]:
    """Submit a decision via agent_tools."""
    return _tool_call(
        f"from hermes_flow.agent_tools import agent_submit_decision; "
        f"result = agent_submit_decision("
        f"run_id={json.dumps(run_id)}, "
        f"role_id={json.dumps(role_id)}, "
        f"state_id={json.dumps(state_id)}, "
        f"value={json.dumps(value)}, "
        f"reason={json.dumps(reason)})"
    )


def agent_send_message(
    run_id: str, role_id: str, state_id: str,
    recipients: list[str], kind: str, content: str,
) -> dict[str, Any]:
    """Send a message via agent_tools."""
    return _tool_call(
        f"from hermes_flow.agent_tools import agent_message_send; "
        f"result = agent_message_send("
        f"run_id={json.dumps(run_id)}, "
        f"role_id={json.dumps(role_id)}, "
        f"state_id={json.dumps(state_id)}, "
        f"intended_recipients={json.dumps(recipients)}, "
        f"kind={json.dumps(kind)}, "
        f"content={json.dumps(content)})"
    )


# ── Context packet building ─────────────────────────────────────────────

def build_agent_prompt(context: dict[str, Any]) -> str:
    """Build a structured prompt from the context packet.

    This is the FR-005 "context packet" — the complete instructions
    given to an agent when it enters a state.
    """
    role_id = context.get("role_id", "unknown")
    soul = context.get("soul", "")
    state_id = context.get("state_id", "")
    state_desc = context.get("state_description", "")
    gate_info = context.get("gate_info")
    inbox = context.get("inbox_messages", [])
    pending = context.get("pending_decisions", [])
    tools = context.get("available_tools", [])

    lines = [
        f"# Flow Run: {context.get('run_id', '')}",
        f"## Your Role: {role_id}\n",
    ]
    if soul:
        lines.append(f"### Personality\n{soul}\n")

    lines.append(f"## Current State: {state_id}")
    if state_desc:
        lines.append(f"_{state_desc}_\n")

    if gate_info:
        lines.append("### Gate (evaluation conditions)")
        lines.append(f"- Required roles: {gate_info.get('required_roles', [])}")
        lines.append(f"- Pass values: {gate_info.get('pass_values', [])}")
        lines.append(f"- Fail values: {gate_info.get('fail_values', [])}")
        lines.append(f"- Max rounds: {gate_info.get('max_rounds', 0)}\n")

    if inbox:
        lines.append(f"### Inbox ({len(inbox)} message(s))")
        for m in inbox:
            lines.append(f"- From {m.get('from_role','?')}: {m.get('content','')}")
        lines.append("")

    if pending:
        lines.append("### Pending Decisions This Round")
        for d in pending:
            lines.append(f"- {d.get('role_id','?')}: {d.get('value','')} ({d.get('reason','')})")
        lines.append("")

    lines.append("### Available Tools")
    for t in tools:
        lines.append(f"- `{t}`")
    lines.append("")

    lines.append("## Your Task")
    if state_id and "review" in state_id.lower():
        lines.append("Review the current state's artifacts and inbox messages.")
        lines.append(
            "Send any questions or feedback to other agents via message_send. "
            "When satisfied, submit your decision. "
            "If revisions are needed, submit REQUEST_CHANGES."
        )
    elif state_id and ("plan" in state_id.lower() or "design" in state_id.lower()):
        lines.append("Produce the required artifacts and send them to the next role.")
        lines.append("When done, submit your decision (APPROVE) to advance.")
    else:
        lines.append("Read your inbox, process any requests from other agents, and submit your decision.")

    lines.append(
        "\n## How to Complete This Session\n"
        "1. Read your inbox and artifacts\n"
        "2. Send messages to other agents if discussion is needed\n"
        "3. Submit your decision when ready\n\n"
        "Write your actions to the result file as JSON array."
    )

    return "\n".join(lines)


# ── LLM-powered decision engine ─────────────────────────────────────────

def _llm_decide_actions(
    context: dict[str, Any],
    inbox_msgs: list[dict[str, Any]],
    status: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Call a real LLM to decide actions.

    Returns actions list, or None if LLM is unavailable (falls back to rule-based).
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None

    role_id = context.get("role_id", "agent")
    state_id = context.get("state_id", "?")
    soul = context.get("soul", "You are a helpful agent.")
    gate_info = context.get("gate_info", {})
    prompt = build_agent_prompt(context)

    system_prompt = (
        "You are an autonomous agent in a multi-agent workflow. "
        "Respond in JSON only with this exact format:\n"
        '{"value": "APPROVE|REQUEST_CHANGES|BLOCKED", "reason": "brief explanation (1-2 sentences)"}\n'
        "Choose APPROVE when work is satisfactory. "
        "Choose REQUEST_CHANGES when revisions are needed. "
        "Choose BLOCKED only if the process cannot continue."
    )

    try:
        import urllib.request
        import json as _json

        base_url = os.environ.get(
            "OPENAI_BASE_URL",
            "https://openrouter.ai/api/v1",
        )
        model = os.environ.get("AGENT_LLM_MODEL", "openai/gpt-4o-mini")

        body = _json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 300,
        }).encode()

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/hermes-flow",
                "X-Title": "Hermes Flow Agent",
            },
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = _json.loads(resp.read())
        content = result["choices"][0]["message"]["content"].strip()

        # Parse JSON from response
        try:
            parsed = _json.loads(content)
        except _json.JSONDecodeError:
            # Try to extract JSON from markdown
            import re as _re
            m = _re.search(r'\{[^}]+\}', content)
            if m:
                parsed = _json.loads(m.group())
            else:
                raise

        value = parsed.get("value", "APPROVE").upper()
        reason = parsed.get("reason", "Decision made by LLM.")

        # Validate value
        valid = {"APPROVE", "REQUEST_CHANGES", "BLOCKED", "PASS", "FAIL"}
        if value not in valid:
            value = "APPROVE"

        actions = [{
            "type": "submit_decision",
            "value": value,
            "reason": f"[{role_id}@{state_id}] {reason}",
        }]

        print(f"[agent_runner] LLM decision: {value} — {reason[:60]}")
        return actions

    except Exception as e:
        print(f"[agent_runner] LLM call failed: {e}, falling back to rule-based")
        return None



# ── Decision engine ─────────────────────────────────────────────────────

def _decide_actions(
    context: dict[str, Any],
    inbox_msgs: list[dict[str, Any]],
    status: dict[str, Any],
) -> list[dict[str, Any]]:
    """Make a dynamic decision based on actual flow state.

    This simulates what a Hermes delegate_task subagent (LLM) would do.
    The agent:
    1. Reads inbox messages from other agents
    2. Considers the state, gate, and round
    3. Decides APPROVE, REQUEST_CHANGES, or BLOCKED

    The LLM version (delegate mode) gets a richer goal via build_delegate_goal().
    """
    actions: list[dict[str, Any]] = []
    role_id = context.get("role_id", "")
    run_id = context.get("run_id", "")
    state_id = context.get("state_id", "")
    gate_info = context.get("gate_info", {})
    required_roles = gate_info.get("required_roles", [])
    round_counter = context.get("_round_counter", 0)

    # ── Read and log each inbox message ──
    for msg in inbox_msgs:
        actions.append({
            "type": "inbox_read",
            "message_id": msg.get("message_id", ""),
            "from_role": msg.get("from_role", "unknown"),
            "content_preview": (msg.get("content") or "")[:60],
        })

    # ── Check if we already made a decision this round ──
    pending = context.get("pending_decisions", [])
    already_decided = any(p.get("role_id") == role_id for p in pending)

    if role_id not in required_roles:
        return actions  # Not a required role, nothing more to do

    # If inbox has messages, always reconsider — don't use stale decisions
    if already_decided:
        # Check if this is a re-entry: decisions from OTHER roles exist
        other_decisions = [p for p in pending if p.get("role_id") != role_id]
        is_reentry = bool(other_decisions) or inbox_msgs or round_counter > 0
        if is_reentry:
            already_decided = False  # Re-entry, need fresh decision
        else:
            return actions  # Old decision still stands

    # ── Dynamic decision based on inbox + state ──
    if inbox_msgs:
        # Combine all message content
        all_content = " ".join(m.get("content", "") for m in inbox_msgs).lower()

        # Check for keywords suggesting (a) changes needed or (b) discussion
        change_signals = ["revise", "change", "fix", "issue", "problem",
                          "wrong", "incorrect", "not good", "redo",
                          "rework", "quality", "concern", "improve",
                          "defect", "error", "bug", "flaw", "missing"]
        block_signals = ["block", "cannot proceed", "stop", "halt",
                         "escalate", "unacceptable", "reject"]
        question_signals = ["?", "question", "clarify", "explain",
                            "why", "how", "please elaborate"]

        should_change = any(
            any(kw in m.get("content", "").lower() for kw in change_signals)
            for m in inbox_msgs
        )
        should_block = any(
            any(kw in m.get("content", "").lower() for kw in block_signals)
            for m in inbox_msgs
        )
        has_question = any(
            any(kw in m.get("content", "").lower() for kw in question_signals)
            for m in inbox_msgs
        )

        if should_block:
            actions.append({
                "type": "submit_decision",
                "value": "BLOCKED",
                "reason": f"Blocked after reviewing {len(inbox_msgs)} message(s) with blocking concerns.",
            })
        elif should_change:
            actions.append({
                "type": "submit_decision",
                "value": "REQUEST_CHANGES",
                "reason": f"Changes requested after reviewing {len(inbox_msgs)} message(s). Issues identified.",
            })
        elif has_question and round_counter < 2:
            # Early round with questions → respond with request for more info
            # In a real LLM discussion, the agent would send a message here.
            # For simulation: mark as discussion and request changes to prompt
            # the other agent to clarify.
            actions.append({
                "type": "submit_decision",
                "value": "REQUEST_CHANGES",
                "reason": f"Clarification needed. Responding to questions in inbox.",
            })
        else:
            actions.append({
                "type": "submit_decision",
                "value": "APPROVE",
                "reason": f"Reviewed {len(inbox_msgs)} message(s). No blocking issues found.",
            })
    else:
        # First entry into state (empty inbox)
        if round_counter > 1:
            # Re-entering after revision — acknowledge and approve
            actions.append({
                "type": "submit_decision",
                "value": "APPROVE",
                "reason": f"Revisions complete (round {round_counter}). Approving to advance.",
            })
        else:
            # Build a context-rich reason with state info
            state_actors = ", ".join(context.get("state_actors", []))
            gate_info = context.get("gate", {})
            pass_vals = ", ".join(gate_info.get("pass_values", ["APPROVE"]))
            msg_hint = f" Inbox: {len(inbox_msgs)} messages waiting." if inbox_msgs else ""
            actions.append({
                "type": "submit_decision",
                "value": "APPROVE",
                "reason": (
                    f"[{role_id}@{state_id}] Task completed for state '{state_id}'. "
                    f"Actors: {state_actors}. "
                    f"Gate expects: pass={pass_vals}.{msg_hint}"
                ),
            })

    return actions


# ── Session execution ──────────────────────────────────────────────────

def read_context(context_path: str) -> dict[str, Any]:
    """Read the context packet from a JSON file."""
    with open(context_path) as f:
        return json.load(f)


def run_session(context_path: str, result_path: str) -> int:
    """Execute an agent session: read context → query store → decide → write result.

    This is the entry point called by the Hermes subagent or test harness.
    The agent uses two sources of truth:
    - context.json: pre-packaged state info
    - agent_tools.py functions: live store queries (inbox, status, decisions)

    By querying the store directly, the agent makes REAL decisions based on
    what's actually in the flow database — not just what the context packet
    says. This is how a Hermes delegate_task subagent would operate.
    """
    context = read_context(context_path)
    session_id = context.get("session_id", _new_id())
    role_id = context.get("role_id", "unknown")
    run_id = context.get("run_id", "")
    state_id = context.get("state_id", "")

    print(f"[agent_runner] Session {session_id}")
    print(f"[agent_runner] Role: {role_id} | Run: {run_id} | State: {state_id}")

    # Step 1: Query the actual flow store for inbox messages
    inbox_msgs = agent_inbox_read(run_id, role_id)
    print(f"[agent_runner] Inbox: {len(inbox_msgs)} messages (from store)")

    # Step 2: Query actual flow status
    status = agent_query_status(run_id)
    print(f"[agent_runner] Status: {status.get('status','?')} @ {status.get('current_state_id','?')}")

    # Step 3: Make dynamic decisions — try LLM first, fall back to rule-based
    actions = _llm_decide_actions(context, inbox_msgs, status)
    if actions is None:
        actions = _decide_actions(context, inbox_msgs, status)
    print(f"[agent_runner] Decision: {len(actions)} action(s)")

    # Step 4: Write actions to result (DON'T execute via agent_tools —
    # the RuntimeLoop will process the actions from result.json)
    for action in actions:
        atype = action.get("type")
        if atype == "submit_decision":
            print(f"  → record submit_decision({action.get('value')})")
        elif atype == "message_send":
            print(f"  → record message_send(to {action.get('recipients')})")
        elif atype == "inbox_read":
            print(f"  → record inbox_read({action.get('from_role','?')})")

    # Step 5: Write the result file (RuntimeLoop will process actions from here)
    result = {
        "session_id": session_id,
        "actions_taken": actions,
        "exited_early": False,
        "error": None,
        "completed_at": _now(),
    }
    result_file = Path(result_path)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"[agent_runner] Result written to {result_path}")
    print(f"[agent_runner] Actions taken: {[a.get('type','') + '(' + str(a.get('value') or a.get('kind') or '') + ')' for a in actions]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an agent session")
    parser.add_argument("--context", required=True, help="Path to context packet JSON")
    parser.add_argument("--result", required=True, help="Path to write result JSON")
    args = parser.parse_args()
    return run_session(args.context, args.result)


if __name__ == "__main__":
    sys.exit(main())
