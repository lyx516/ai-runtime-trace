"""Write content to a file, overwriting if it exists. Scoped to workspace.

Use this to create new files or completely rewrite existing ones.
For targeted edits, use the patch tool instead.
"""

import os
from pathlib import Path


def run(args: dict) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")

    if not path:
        return {
            "ok": False,
            "error": "write_file: missing required field 'path'."
        }
    if not content:
        return {
            "ok": False,
            "error": "write_file: missing required field 'content'. "
                     "Do not retry with empty content."
        }

    from tools._scope import resolve_write_path

    try:
        full = resolve_write_path(path)
    except PermissionError as e:
        return {"ok": False, "error": str(e)}

    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    except PermissionError as e:
        return {"ok": False, "error": f"write_file: permission denied — {e}"}
    except OSError as e:
        return {"ok": False, "error": f"write_file: cannot write — {e}"}

    return {
        "ok": True,
        "path": str(full),
    }
