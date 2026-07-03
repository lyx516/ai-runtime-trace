"""Delegate Spawner — bridges RuntimeLoop (Python) with Hermes delegate_task.

When spawn_mode='delegate', the RuntimeLoop writes a _manifest.json listing
pending sessions. This module provides the bridge:

1. Manifest file I/O (pending → spawned → completed)
2. delegated_goal() — builds the goal string for delegate_task subagent
3. The goal EMBEDS the full context (soul, inbox, gate) so the LLM
   subagent can reason about the situation without extra I/O

After the subagent thinks, it uses its terminal tool to:
  python -c "from hermes_flow.agent_tools import agent_submit_decision; ..."
  python -c "from hermes_flow.agent_tools import agent_message_send; ..."
  python -c "import json; json.dump(result, open('result.json','w'))"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_flow.agent_runner import build_agent_prompt

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "_manifest.json"


# ── Manifest I/O ─────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_manifest(run_dir: str | Path) -> dict[str, Any]:
    """Read the delegate session manifest from a run directory.

    Returns dict with {"run_id": str, "sessions": [...]}.
    Returns empty manifest if file doesn't exist.
    """
    manifest_path = Path(run_dir) / "sessions" / MANIFEST_FILENAME
    if not manifest_path.exists():
        return {"run_id": "", "sessions": []}
    with open(manifest_path) as f:
        return json.load(f)


def write_manifest(run_dir: str | Path, manifest: dict[str, Any]) -> None:
    """Write the delegate session manifest."""
    manifest_path = Path(run_dir) / "sessions" / MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)


def add_session_to_manifest(
    run_dir: str | Path,
    run_id: str,
    session_id: str,
    role_id: str,
    state_id: str,
    context_file: str,
    result_file: str,
) -> None:
    """Add a pending session to the manifest."""
    manifest = read_manifest(run_dir)
    manifest["run_id"] = run_id
    existing = [s for s in manifest["sessions"] if s["session_id"] == session_id]
    if existing:
        return
    manifest["sessions"].append({
        "session_id": session_id,
        "role_id": role_id,
        "state_id": state_id,
        "context_file": str(context_file),
        "result_file": str(result_file),
        "status": "pending",
        "created_at": _now(),
    })
    write_manifest(run_dir, manifest)


def mark_session_spawned(run_dir: str | Path, session_id: str) -> None:
    """Mark a session as having been spawned via delegate_task."""
    manifest = read_manifest(run_dir)
    for s in manifest["sessions"]:
        if s["session_id"] == session_id and s["status"] == "pending":
            s["status"] = "spawned"
            s["spawned_at"] = _now()
    write_manifest(run_dir, manifest)


def mark_session_completed(run_dir: str | Path, session_id: str) -> None:
    """Mark a session as completed (result.json observed)."""
    manifest = read_manifest(run_dir)
    for s in manifest["sessions"]:
        if s["session_id"] == session_id and s["status"] == "spawned":
            s["status"] = "completed"
            s["completed_at"] = _now()
    write_manifest(run_dir, manifest)


def get_pending_sessions(run_dir: str | Path) -> list[dict[str, Any]]:
    """Get all sessions with status='pending' that haven't been spawned."""
    manifest = read_manifest(run_dir)
    return [s for s in manifest["sessions"] if s["status"] == "pending"]


# ── Self-hosting broker ──────────────────────────────────────────────────

def broker_tick(run_dir: str | Path) -> list[str]:
    """Execute one broker tick: scan pending sessions and spawn each one.

    This makes delegate mode self-hosting (no external Hermes agent needed).
    For each pending session, spawns agent_runner.run_session in a background
    thread, then marks the session as 'spawned'.

    When a real Hermes agent is available, it can use build_delegate_goal()
    instead and call delegate_task directly.

    Returns list of session_ids that were spawned this tick.
    """
    import threading
    from hermes_flow.agent_runner import run_session

    pending = get_pending_sessions(run_dir)
    spawned: list[str] = []

    for session in pending:
        session_id = session["session_id"]
        context_file = session["context_file"]
        result_file = session["result_file"]

        # Mark as spawned
        mark_session_spawned(run_dir, session_id)

        # Spawn agent_runner in background thread (simulates delegate_task)
        t = threading.Thread(
            target=run_session,
            args=(context_file, result_file),
            daemon=True,
        )
        t.start()
        spawned.append(session_id)

    if spawned:
        logger.info("broker_tick: spawned %d session(s): %s", len(spawned), spawned)

    return spawned


# ── Goal string generation ──────────────────────────────────────────────

def build_delegate_goal(context_file: str, result_file: str) -> str:
    """Build the goal string for a delegate_task subagent.

    Reads the context file and embeds its content into the goal so the
    LLM sees everything upfront. The subagent then:
    1. Reasons about its role, inbox, and gate
    2. Calls agent_tools via terminal tool to act
    3. Writes result.json via terminal tool

    This is the key interface between the RuntimeLoop and the LLM subagent.
    """
    # Read actual context
    try:
        with open(context_file) as f:
            context = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return f"[Error: cannot read context file {context_file}: {e}]"

    run_id = context.get("run_id", "?")
    role_id = context.get("role_id", "?")
    session_id = context.get("session_id", "?")
    state_id = context.get("state_id", "?")
    state_desc = context.get("state_description", "")
    soul = context.get("soul", "")
    prompt = context.get("agent_prompt", build_agent_prompt(context))
    gate_info = context.get("gate_info", {})
    inbox = context.get("inbox_messages", [])
    pending = context.get("pending_decisions", [])
    available_tools = context.get("available_tools", [])
    discussion_history = context.get("discussion_history", [])

    # Count how many rounds this state has seen
    round_count = context.get("_round_counter", 0)

    goal = f"""# Hermes Flow Agent Session

## Identity
- **Flow Run**: {run_id}
- **Your Role**: {role_id}
- **State**: {state_id}
- **Session**: {session_id}

## Your Personality
{soul if soul else "You are a helpful agent participating in a collaborative workflow."}

## Current Situation

You are in the **{state_id}** state{f' — {state_desc}' if state_desc else ''}.

### Gate Conditions
- Required roles for gate: {gate_info.get('required_roles', [])}
- Pass values: {gate_info.get('pass_values', [])}
- Fail values: {gate_info.get('fail_values', [])}
- Max revision rounds: {gate_info.get('max_rounds', 3)}
- Current round: {round_count + 1}
"""

    if inbox:
        goal += f"\n### Your Inbox ({len(inbox)} messages)\n"
        for i, msg in enumerate(inbox, 1):
            goal += f"{i}. From **{msg.get('from_role', '?')}** ({msg.get('kind', 'message')}): {msg.get('content', '')}\n"
    else:
        goal += "\n### Your Inbox\n(empty — you are entering this state for the first time)\n"

    if pending:
        goal += "\n### Decisions Already Submitted This Round\n"
        for d in pending:
            goal += f"- **{d.get('role_id', '?')}**: {d.get('value', '?')} — {d.get('reason', '')}\n"

    if discussion_history:
        goal += f"\n### Discussion History ({len(discussion_history)} exchanges)\n"
        for msg in discussion_history:
            goal += f"- {msg.get('role_id', '?')}: {msg.get('content', '')}\n"

    goal += f"""
## Your Task

Read the above context carefully. You are an autonomous agent in a multi-agent workflow.

### What you must do

1. **Analyze the situation**: What state are you in? What messages are in your inbox?
   What are the gate conditions? What decisions have other agents made?

2. **Decide what action to take**:
"""

    if state_id and "review" in state_id.lower():
        goal += """   - If you are a **reviewer**: Review the work done in the previous state.
     - If the work is correct and complete, submit **APPROVE**.
     - If changes are needed, submit **REQUEST_CHANGES** and explain why.
     - If there's a serious issue, submit **BLOCKED**.
     - Send messages to other agents to ask questions or request clarification.
"""
    elif state_id and ("plan" in state_id.lower() or "design" in state_id.lower()):
        goal += """   - If you are a **planner/designer**: Produce your work and approve it to advance.
     - If someone requested changes, read their feedback carefully and respond.
     - Submit **APPROVE** when you're done, or **REQUEST_CHANGES** if you need more input.
"""
    else:
        goal += """   - Read your inbox and process any requests.
   - Submit **APPROVE** if everything is in order.
   - Submit **REQUEST_CHANGES** if you need revisions from other agents.
   - Submit **BLOCKED** if the process cannot continue.
"""

    goal += f"""
### How to act

You have access to `hermes_flow.agent_tools`. Use your **terminal tool** to run these commands:

**1. Read inbox (live data)**:
```bash
cd {Path(result_file).parent} && python -c "from hermes_flow.agent_tools import agent_inbox_read; import json; print(json.dumps(agent_inbox_read(run_id='{run_id}', role_id='{role_id}')))"
```

**2. Submit a decision** (replace APPROVE with REQUEST_CHANGES or BLOCKED as needed):
```bash
cd {Path(result_file).parent} && python -c "from hermes_flow.agent_tools import agent_submit_decision; import json; r=agent_submit_decision(run_id='{run_id}', role_id='{role_id}', state_id='{state_id}', value='APPROVE', reason='Your reasoning'); print(json.dumps(r))"
```

**3. Send a message to another agent** (for discussion):
```bash
cd {Path(result_file).parent} && python -c "from hermes_flow.agent_tools import agent_message_send; import json; r=agent_message_send(run_id='{run_id}', role_id='{role_id}', state_id='{state_id}', intended_recipients=['other_role'], kind='feedback', content='Your message'); print(json.dumps(r))"
```

**4. Write the result file** (REQUIRED — do this last):
```python
import json
result = {{
    "session_id": "{session_id}",
    "actions_taken": [
        {{"type": "submit_decision", "value": "APPROVE", "reason": "Your reasoning"}}
    ],
    "exited_early": false,
    "error": null,
    "completed_at": "{_now()}"
}}
with open("{result_file}", "w") as f:
    json.dump(result, f, indent=2)
print("Done")
```
Save this to a Python file and run it, or run it inline with `python -c`.

### CRITICAL
- You MUST write `{result_file}` when done.
- `session_id` MUST be `{session_id}`.
- If you submit REQUEST_CHANGES, the flow routes back for revisions.
- If you submit BLOCKED, the flow escalates.
- Be thorough. Have a real discussion if the situation is complex.
"""

    return goal
