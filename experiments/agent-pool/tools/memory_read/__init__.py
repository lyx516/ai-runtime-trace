SCHEMA = {
  "name": "memory_read",
  "description": "Read a value from your persistent memory (survives across runs). Pass a key to retrieve a stored value. If the key doesn't exist, returns null.",
  "parameters": {
    "type": "object",
    "properties": {
      "key": {"type": "string", "description": "Memory key to read."}
    },
    "required": ["key"]
  }
}

"""memory_read — read from agent's persistent memory (handled inline in session.py)."""
def run(args: dict) -> dict:
    return {"ok": False, "error": "memory_read must be handled via inline dispatch"}