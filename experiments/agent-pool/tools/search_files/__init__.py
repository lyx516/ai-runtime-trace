"""Search file contents or find files by name. Scoped to workspace."""
import os
import subprocess
import shlex

def run(args: dict) -> dict:
    pattern = args.get("pattern", "")
    search_type = args.get("type", "content")
    path = args.get("path", ".")
    file_glob = args.get("file_glob", "")
    limit = args.get("limit", 50)
    offset = args.get("offset", 0)
    output_mode = args.get("output_mode", "content")
    context = args.get("context", 0)

    if not pattern:
        return {"ok": False, "error": "search_files: missing required field 'pattern'"}

    from tools._scope import resolve_path
    try:
        root = resolve_path(path)
    except PermissionError as e:
        return {"ok": False, "error": str(e)}

    full_path = str(root)

    try:
        if search_type == "filename":
            cmd = f"find {shlex.quote(full_path)} -name {shlex.quote(pattern)} -type f 2>/dev/null | tail -n +{offset+1} | head -{limit}"
        elif search_type == "directory":
            cmd = f"find {shlex.quote(full_path)} -name {shlex.quote(pattern)} -type d 2>/dev/null | tail -n +{offset+1} | head -{limit}"
        else:
            includes = "--include='*.py' --include='*.md' --include='*.yaml' --include='*.json' --include='*.toml' --include='*.txt'"
            if file_glob:
                includes = f"--include='{file_glob}'"
            if context > 0:
                cmd = f"grep -r -n -B {context} -A {context} {shlex.quote(pattern)} {shlex.quote(full_path)} {includes} 2>/dev/null | tail -n +{offset+1} | head -{limit}"
            else:
                cmd = f"grep -r -l {shlex.quote(pattern)} {shlex.quote(full_path)} {includes} 2>/dev/null | tail -n +{offset+1} | head -{limit}"

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        
        if output_mode == "count":
            count = len([m for m in result.stdout.strip().split("\n") if m.strip()])
            return {"ok": True, "count": count}
        
        matches = [m for m in result.stdout.strip().split("\n") if m.strip()]
        # Filter results to workspace scope
        from tools._scope import get_workspace_root
        ws = str(get_workspace_root())
        matches = [m for m in matches if m.startswith(ws)]
        
        if output_mode == "files_only":
            return {"ok": True, "matches": matches[:limit], "count": len(matches)}
        
        return {"ok": True, "matches": matches[:limit], "count": len(matches)}
    except Exception as e:
        return {"ok": False, "error": f"search_files: {e}"}
