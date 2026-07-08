SCHEMA = {
  "name": "agent_recall",
  "description": "Recall runtime data from a flow run's SQLite database — decisions, tool usage, state transitions, and agent messages. Pure SQLite reads — no LLM processing, returns raw data.\n\nFIVE CALLING SHAPES (inferred from query parameter):\n\n  OVERVIEW — agent_recall(query=\"overview\"): run status, agents, state/decision/msg counts.\n  TRANSITIONS — agent_recall(query=\"transitions\"): state path with retry detection.\n  DECISIONS — agent_recall(query=\"decisions\", agent=\"x\"): who approved/rejected what.\n  THINKING — agent_recall(query=\"thinking\", agent=\"x\", limit=20, offset=0): tool call log with pagination.\n  MESSAGES — agent_recall(query=\"messages\", state=\"IMPLEMENT\"): agent-to-agent messages.\n\nPAGINATION: when has_more=true, use offset + limit for next page. Use to investigate agent behavior BEFORE making judgments.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "enum": ["overview", "transitions", "decisions", "thinking", "messages"], "description": "What data to recall."},
      "agent": {"type": "string", "description": "Filter by agent_id (e.g. 'implementer')."},
      "state": {"type": "string", "description": "Filter by state_id (e.g. 'IMPLEMENT')."},
      "limit": {"type": "integer", "description": "Rows per page (default 20, max 50)."},
      "offset": {"type": "integer", "description": "Row offset for pagination (default 0)."}
    },
    "required": ["query"]
  }
}

"""agent_recall — recall runtime data from a flow run's SQLite database (handled inline in session.py)."""
def run(args: dict) -> dict:
    # The actual handling is in session.py's inline dispatch.
    # This module exists only for tool schema discovery.
    return {"ok": False, "error": "agent_recall must be handled via inline dispatch"}
