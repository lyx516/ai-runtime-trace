"""文件读取工具"""
import os
from pathlib import Path

PROJECT_ROOT = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or os.getcwd()

def run(args: dict) -> dict:
    path = args.get("path", "")
    offset = args.get("offset", 1)
    limit = args.get("limit", 200)

    if not path:
        return {"ok": False, "error": "path required"}

    full = Path(PROJECT_ROOT) / path if not path.startswith("/") else Path(path)
    if not full.exists():
        return {"ok": False, "error": f"file not found: {full}"}
    if not full.is_file():
        return {"ok": False, "error": f"not a file: {full}"}

    try:
        lines = full.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        end = min(total, start + limit)
        content = "\n".join(lines[start:end])
        return {
            "ok": True,
            "content": content,
            "total_lines": total,
            "offset": offset,
            "lines_returned": end - start,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
