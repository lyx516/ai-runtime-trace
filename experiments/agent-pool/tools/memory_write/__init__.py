SCHEMA = {
  "name": "memory_write",
  "description": "Write a value to your persistent memory (survives across runs). Use to store facts, patterns, lessons learned, or preferences for future sessions.",
  "parameters": {
    "type": "object",
    "properties": {
      "key": {"type": "string", "description": "Memory key (e.g. 'preferred_test_framework', 'common_pitfalls')."},
      "value": {"type": "string", "description": "Value to store."}
    },
    "required": ["key", "value"]
  }
}

"""memory_write — write to agent's persistent memory (handled inline in session.py)."""
def run(args: dict) -> dict:
    return {"ok": False, "error": "memory_write must be handled via inline dispatch"}