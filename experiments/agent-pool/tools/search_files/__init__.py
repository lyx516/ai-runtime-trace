"""文件搜索工具 — 搜索文件名或内容"""
import os
import subprocess
import shlex

PROJECT_ROOT = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or os.getcwd()

def run(args: dict) -> dict:
    pattern = args.get("pattern", "")
    search_type = args.get("type", "content")  # content or filename
    path = args.get("path", ".")
    limit = args.get("limit", 20)

    if not pattern:
        return {"ok": False, "error": "pattern required"}

    full_path = path if path.startswith("/") else f"{PROJECT_ROOT}/{path}"

    try:
        if search_type == "filename":
            cmd = f"find {shlex.quote(full_path)} -name {shlex.quote(pattern)} -type f 2>/dev/null | head -{limit}"
        else:
            cmd = f"grep -r -l {shlex.quote(pattern)} {shlex.quote(full_path)} --include='*.py' --include='*.md' --include='*.yaml' --include='*.json' --include='*.toml' --include='*.txt' 2>/dev/null | head -{limit}"

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        matches = [m for m in result.stdout.strip().split("\n") if m.strip()]
        return {"ok": True, "matches": matches[:limit], "count": len(matches)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
