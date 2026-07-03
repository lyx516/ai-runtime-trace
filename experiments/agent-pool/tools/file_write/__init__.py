"""文件写入工具"""
import os
from pathlib import Path

PROJECT_ROOT = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or os.getcwd()

def run(args: dict) -> dict:
    path = args.get("path", "")
    content = args.get("content", "")

    if not path:
        return {"ok": False, "error": "path required"}

    full = Path(PROJECT_ROOT) / path if not path.startswith("/") else Path(path)
    full.parent.mkdir(parents=True, exist_ok=True)
    try:
        full.write_text(content, encoding="utf-8")
        return {"ok": True, "bytes_written": len(content), "path": str(full)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
