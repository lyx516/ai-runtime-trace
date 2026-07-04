"""Read a text file with line numbers and pagination. scoped to workspace."""
import os
from pathlib import Path

def run(args: dict) -> dict:
    path = args.get("path", "")
    offset = args.get("offset", 1)
    limit = args.get("limit", 500)

    if not path:
        return {"ok": False, "error": "read_file: missing required field 'path'"}

    from tools._scope import safe_read_path
    full, err = safe_read_path(path)
    if err:
        return {"ok": False, "error": err}

    if not full.exists():
        return {"ok": False, "error": f"read_file: file not found: {path}"}
    if not full.is_file():
        return {"ok": False, "error": f"read_file: not a file: {path}"}

    try:
        lines = full.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        numbered = [f"{i+1}|{lines[i]}" for i in range(start, end)]
        return {
            "ok": True,
            "content": "\n".join(numbered),
            "total_lines": total,
            "offset": offset,
            "lines_returned": end - start,
        }
    except Exception as e:
        return {"ok": False, "error": f"read_file: {e}"}
