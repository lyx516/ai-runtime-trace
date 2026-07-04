"""文件修补工具 — 精确查找替换，支持 3 种模式。"""
import os
import re
from pathlib import Path

def run(args: dict) -> dict:
    mode = args.get("mode", "replace")
    path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)
    patch_content = args.get("patch", "")

    # Reject empty-arg calls that waste time
    if mode in ("replace",) and not old_string and not path:
        return {
            "ok": False,
            "error": "patch: old_string and path are both empty. "
                     "Provide both 'path' and 'old_string' to perform a replacement. "
                     "Do not retry this call with empty arguments.",
        }
    if mode in ("patch", "verified") and not patch_content:
        return {
            "ok": False,
            "error": f"patch: 'patch' content is empty for mode='{mode}'. "
                     "Provide the 'patch' argument with valid V4A patch content. "
                     "Do not retry this call with empty arguments.",
        }

    try:
        if mode == "replace":
            return _mode_replace(path, old_string, new_string, replace_all)
        elif mode == "patch":
            return _mode_v4a(patch_content)
        elif mode == "verified":
            return _mode_verified(patch_content)
        else:
            return {"ok": False, "error": f"Unknown mode: {mode}. Supported: replace, patch, verified"}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}


def _resolve_path(path: str) -> Path:
    """Resolve a file path within workspace scope."""
    from tools._scope import resolve_path as scope_resolve
    return scope_resolve(path)


def _read_file(path: Path) -> tuple:
    """Read a file, return (content, error)."""
    if not path.exists():
        return "", f"File not found: {path}"
    if not path.is_file():
        return "", f"Not a file: {path}"
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return "", str(e)


def _unified_diff(old: str, new: str, filepath: str) -> str:
    """Generate a simple unified diff string."""
    old_lines = old.splitlines(True)
    new_lines = new.splitlines(True)
    diff = []
    diff.append(f"--- {filepath}")
    diff.append(f"+++ {filepath}")
    # Simple line-by-line diff
    import difflib
    for line in difflib.unified_diff(old_lines, new_lines, fromfile=filepath, tofile=filepath, n=3):
        diff.append(line.rstrip("\n"))
    return "\n".join(diff)


def _check_lint(path: Path, content: str):
    """Run basic syntax check on known file types."""
    ext = path.suffix.lower()
    if ext == ".py":
        try:
            compile(content, str(path), "exec")
            return None  # no errors
        except SyntaxError as e:
            return {"file": str(path), "line": e.lineno, "message": str(e)}
    return None


def _mode_replace(path: str, old_string: str, new_string: str, replace_all: bool) -> dict:
    """Replace mode: find unique string and replace it."""
    if not path:
        return {"ok": False, "error": "patch: missing required field 'path' for mode='replace'"}
    if not old_string:
        return {"ok": False, "error": "patch: missing required field 'old_string' for mode='replace'"}

    full_path = _resolve_path(path)
    content, err = _read_file(full_path)
    if err:
        return {"ok": False, "error": err}

    from tools.fuzzy_match import fuzzy_find_and_replace

    new_content, match_count, strategy, error = fuzzy_find_and_replace(
        content, old_string, new_string, replace_all
    )

    if match_count == 0:
        return {
            "ok": False,
            "error": f"Could not find '{old_string[:60]}' in '{path}'. {error or ''}",
        }

    # Generate diff before writing
    diff = _unified_diff(content, new_content, str(full_path))

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"Failed to write: {e}"}

    lint_result = _check_lint(full_path, new_content)

    return {
        "ok": True,
        "diff": diff,
        "files_modified": [str(full_path)],
        "match_count": match_count,
        "strategy": strategy or "none",
        "lint": lint_result,
    }


def _parse_v4a(patch_content: str) -> list[dict]:
    """Parse V4A format patch into operations list.
    
    Format:
        *** Begin Patch
        *** Update File: path/to/file
        @@ context hint @@
         context line
        -removed line
        +added line
        *** End Patch
    
    Also supports:
        *** Add File: path/to/newfile
        content here
        *** End Patch
        
        *** Delete File: path/to/file
    """
    operations = []
    current_op = None
    current_hunks = []
    current_hunk = None

    for line in patch_content.split("\n"):
        # File header
        header_match = re.match(r'^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s+(.+)$', line.strip())
        if header_match:
            if current_op:
                if current_hunk:
                    current_hunks.append(current_hunk)
                current_op["hunks"] = current_hunks
                operations.append(current_op)
            action = line.strip().split()[1]  # Update, Add, Delete
            current_op = {"action": action, "file_path": header_match.group(1).strip()}
            current_hunks = []
            current_hunk = None
            continue

        # Hunk header
        hunk_match = re.match(r'^@@\s+(.+?)\s+@@$', line.strip())
        if hunk_match and current_op:
            if current_hunk:
                current_hunks.append(current_hunk)
            current_hunk = {
                "context_hint": hunk_match.group(1).strip(),
                "lines": [],
            }
            continue

        # Raw content for Add mode (no @@ header)
        if current_op and current_op["action"] == "Add" and current_hunk is None:
            if "raw_content" not in current_op:
                current_op["raw_content"] = ""
            strip_line = line.strip()
            if strip_line == "*** End Patch":
                if current_op:
                    current_op["hunks"] = current_hunks
                    operations.append(current_op)
                    current_op = None
                    current_hunks = []
                continue
            current_op["raw_content"] += line + "\n"
            continue

        # Content lines within a hunk
        if current_hunk is not None:
            if line.startswith("+") and not line.startswith("+++"):
                current_hunk["lines"].append({"prefix": "+", "content": line[1:]})
            elif line.startswith("-") and not line.startswith("---"):
                current_hunk["lines"].append({"prefix": "-", "content": line[1:]})
            elif line.startswith(" "):
                current_hunk["lines"].append({"prefix": " ", "content": line[1:]})
            elif line.strip() == "*** End Patch":
                if current_hunk:
                    current_hunks.append(current_hunk)
                    current_hunk = None
                if current_op:
                    current_op["hunks"] = current_hunks
                    operations.append(current_op)
                    current_op = None
                    current_hunks = []

    # Flush remaining
    if current_hunk:
        current_hunks.append(current_hunk)
    if current_op:
        current_op["hunks"] = current_hunks
        operations.append(current_op)

    return operations


def _mode_v4a(patch_content: str) -> dict:
    """Apply a V4A format patch."""
    if not patch_content:
        return {"ok": False, "error": "patch: missing required field 'patch' for mode='patch'"}

    from tools.fuzzy_match import fuzzy_find_and_replace

    operations = _parse_v4a(patch_content)
    if not operations:
        return {"ok": False, "error": "Failed to parse patch: no operations found"}

    files_modified = []
    combined_diff_parts = []

    for op in operations:
        action = op["action"]
        file_path = op["file_path"]
        full_path = _resolve_path(file_path)

        if action == "Add":
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                hunks = op.get("hunks", [])
                if hunks:
                    # Content from hunk lines (with @@ header)
                    new_content = ""
                    for hunk in hunks:
                        for line in hunk.get("lines", []):
                            new_content += line["content"] + "\n"
                else:
                    # Raw content (no @@ header) collected during parse
                    new_content = op.get("raw_content", "")
                if new_content and new_content.endswith("\n\n"):
                    new_content = new_content[:-1]
                full_path.write_text(new_content, encoding="utf-8")
                files_modified.append(str(full_path))
                combined_diff_parts.append(f"Added file: {file_path}")
            except Exception as e:
                return {"ok": False, "error": f"Failed to create {file_path}: {e}"}
            continue

        if action == "Delete":
            if full_path.exists():
                try:
                    full_path.unlink()
                    files_modified.append(str(full_path))
                    combined_diff_parts.append(f"Deleted file: {file_path}")
                except Exception as e:
                    return {"ok": False, "error": f"Failed to delete {file_path}: {e}"}
            continue

        if action == "Update":
            content, err = _read_file(full_path)
            if err:
                return {"ok": False, "error": err}

            # Apply each hunk
            new_content = content
            for hunk in op.get("hunks", []):
                lines = hunk.get("lines", [])
                old_block = "\n".join(
                    l["content"] for l in lines if l["prefix"] == "-"
                )
                new_block_lines = [l["content"] for l in lines if l["prefix"] == "+"]
                new_block = "\n".join(new_block_lines)

                if old_block:
                    new_content, count, _, err = fuzzy_find_and_replace(
                        new_content, old_block, new_block, replace_all=False
                    )
                    if count == 0:
                        return {
                            "ok": False,
                            "error": f"V4A hunk failed: could not find target in {file_path}",
                        }

            if new_content != content:
                diff = _unified_diff(content, new_content, str(full_path))
                try:
                    full_path.write_text(new_content, encoding="utf-8")
                    files_modified.append(str(full_path))
                    combined_diff_parts.append(diff)
                except Exception as e:
                    return {"ok": False, "error": f"Failed to write {file_path}: {e}"}

    return {
        "ok": True,
        "diff": "\n".join(d for d in combined_diff_parts if d),
        "files_modified": files_modified,
    }


def _mode_verified(patch_content: str) -> dict:
    """Apply verified anchored V4A-style update hunks."""
    if not patch_content:
        return {"ok": False, "error": "patch: missing required field 'patch' for mode='verified'"}

    from tools.verified_patch_core import (
        VerifiedPatchError, VerifiedOperation, apply_operations,
    )
    from tools import fuzzy_match

    operations = _parse_v4a(patch_content)
    if not operations:
        return {"ok": False, "error": "Failed to parse verified patch: no operations found"}

    for op in operations:
        if op["action"] != "Update":
            return {
                "ok": False,
                "error": "verified mode currently supports update hunks only; use mode='patch' for add/delete operations",
            }

    resolved = {}  # file_path -> current content
    grouped_ops = {}  # file_path -> list of VerifiedOperation

    for op in operations:
        file_path = op["file_path"]
        full_path = _resolve_path(file_path)

        if file_path not in resolved:
            content, err = _read_file(full_path)
            if err:
                return {"ok": False, "error": err}
            if "\x00" in content:
                return {"ok": False, "error": f"{file_path}: binary file, verified patch not applicable"}
            resolved[file_path] = content

        for hunk in op.get("hunks", []):
            hint = hunk.get("context_hint", "")
            range_match = re.fullmatch(r"(?:replace\s+)?(\d+)(?:\.\.(\d+))?", hint.strip())
            if not range_match:
                return {
                    "ok": False,
                    "error": f"{file_path}: verified hunk requires a numeric snapshot range in the @@ hint, e.g. @@ 12..14 @@",
                }

            start = int(range_match.group(1))
            old_lines = [line["content"] for line in hunk["lines"] if line["prefix"] == "-"]
            if not old_lines:
                return {
                    "ok": False,
                    "error": f"{file_path}: verified hunk requires at least one '-' precondition line",
                }

            end = int(range_match.group(2)) if range_match.group(2) else start + len(old_lines) - 1
            if end - start + 1 != len(old_lines):
                return {
                    "ok": False,
                    "error": f"{file_path}: @@ range {start}..{end} covers {end - start + 1} lines but hunk has {len(old_lines)} '-' lines",
                }

            change_indexes = [
                i for i, line in enumerate(hunk["lines"])
                if line["prefix"] in ("-", "+")
            ]
            if not change_indexes:
                continue
            first_change = min(change_indexes)
            last_change = max(change_indexes)

            before = [
                line["content"] for line in hunk["lines"][:first_change]
                if line["prefix"] == " "
            ]
            after = [
                line["content"] for line in hunk["lines"][last_change + 1:]
                if line["prefix"] == " "
            ]
            new_lines = [line["content"] for line in hunk["lines"] if line["prefix"] == "+"]

            grouped_ops.setdefault(file_path, []).append(
                VerifiedOperation(
                    kind="replace",
                    start=start,
                    end=end,
                    old=tuple(old_lines),
                    new=tuple(new_lines),
                    before=tuple(before),
                    after=tuple(after),
                )
            )

    staged = {}
    try:
        for file_path, edits in grouped_ops.items():
            staged[file_path] = apply_operations(resolved[file_path], edits)
    except VerifiedPatchError as e:
        return {"ok": False, "error": f"verified patch rejected: {e}"}

    files_modified = []
    combined_diff_parts = []
    for file_path, new_content in staged.items():
        full_path = _resolve_path(file_path)
        content = resolved[file_path]
        diff = _unified_diff(content, new_content, str(full_path))
        try:
            full_path.write_text(new_content, encoding="utf-8")
            files_modified.append(str(full_path))
            combined_diff_parts.append(diff)
        except Exception as e:
            return {"ok": False, "error": f"Failed to write {file_path}: {e}"}

    return {
        "ok": True,
        "diff": "\n".join(d for d in combined_diff_parts if d),
        "files_modified": files_modified,
    }
