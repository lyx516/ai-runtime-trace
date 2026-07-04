"""文件修补工具 — 支持 create / replace / patch / verified 四种模式。

create   — 创建新文件（文件已存在则报错）
replace  — 精确查找替换（必须匹配到目标）
patch    — V4A 多文件批量补丁（支持 Add / Update / Delete File）
verified — 带行号锚点的安全替换（合并冲突检测）
"""

import os
import re
from pathlib import Path


def run(args: dict) -> dict:
    mode = args.get("mode", "replace")
    path = args.get("path", "")
    content = args.get("content", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)
    patch_content = args.get("patch", "")

    # ── Empty-arg fast-fail ──
    if mode == "create":
        if not path:
            return {
                "ok": False,
                "error": "patch: missing required field 'path' for mode='create'. "
                         "Provide 'path' (file path) and 'content' (file contents).",
            }
        if not content:
            return {
                "ok": False,
                "error": "patch: missing required field 'content' for mode='create'. "
                         "The 'content' field must contain the full file content to write. "
                         "Do not retry this call with empty content.",
            }
    elif mode == "replace":
        if not old_string and not path:
            return {
                "ok": False,
                "error": "patch: old_string and path are both empty. "
                         "Provide both 'path' and 'old_string' to perform a replacement. "
                         "Do not retry this call with empty arguments.",
            }
    elif mode in ("patch", "verified"):
        if not patch_content:
            return {
                "ok": False,
                "error": f"patch: 'patch' content is empty for mode='{mode}'. "
                         "Provide the 'patch' argument with valid V4A patch content. "
                         "Do not retry this call with empty arguments.",
            }

    # ── Dispatch ──
    try:
        if mode == "create":
            return _mode_create(path, content)
        elif mode == "replace":
            return _mode_replace(path, old_string, new_string, replace_all)
        elif mode == "patch":
            return _mode_v4a(patch_content)
        elif mode == "verified":
            return _mode_verified(patch_content)
        else:
            return {
                "ok": False,
                "error": f"Unknown mode: {mode}. Supported: create, replace, patch, verified",
            }
    except PermissionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"patch({mode}): unexpected error — {e}"}


# ── Shared helpers ──

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
        return "", f"Failed to read {path}: {e}"


def _unified_diff(old: str, new: str, filepath: str) -> str:
    """Generate a simple unified diff string."""
    import difflib
    old_lines = old.splitlines(True)
    new_lines = new.splitlines(True)
    diff = [f"--- {filepath}", f"+++ {filepath}"]
    for line in difflib.unified_diff(old_lines, new_lines, fromfile=filepath, tofile=filepath, n=3):
        diff.append(line.rstrip("\n"))
    return "\n".join(diff)


def _check_lint(path: Path, content: str):
    """Run basic syntax check on known file types."""
    ext = path.suffix.lower()
    if ext == ".py":
        try:
            compile(content, str(path), "exec")
            return None
        except SyntaxError as e:
            return {"file": str(path), "line": e.lineno, "message": str(e)}
    return None


# ── Mode implementations ──

def _mode_create(path: str, content: str) -> dict:
    """Create a new file. Fails if the file already exists."""
    full_path = _resolve_path(path)

    if full_path.exists():
        return {
            "ok": False,
            "error": f"patch(create): file already exists — '{path}'. "
                     "Use mode='replace' to edit existing files, or choose a different path.",
        }

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    except PermissionError as e:
        return {"ok": False, "error": f"patch(create): permission denied — {e}"}
    except OSError as e:
        return {"ok": False, "error": f"patch(create): cannot write — {e}"}

    lint_result = _check_lint(full_path, content)

    return {
        "ok": True,
        "diff": f"Created file: {path}",
        "files_modified": [str(full_path)],
        "match_count": 1,
        "strategy": "create",
        "lint": lint_result,
    }


def _mode_replace(path: str, old_string: str, new_string: str, replace_all: bool) -> dict:
    """Replace mode: find unique string and replace it."""
    if not path:
        return {"ok": False, "error": "patch(replace): missing required field 'path'"}
    if not old_string:
        return {"ok": False, "error": "patch(replace): missing required field 'old_string'"}

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
            "error": f"patch(replace): could not find '{old_string[:80]}' in '{path}'. {error or ''}",
        }

    diff = _unified_diff(content, new_content, str(full_path))

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(new_content, encoding="utf-8")
    except PermissionError as e:
        return {"ok": False, "error": f"patch(replace): permission denied — {e}"}
    except OSError as e:
        return {"ok": False, "error": f"patch(replace): cannot write — {e}"}

    lint_result = _check_lint(full_path, new_content)

    return {
        "ok": True,
        "diff": diff,
        "files_modified": [str(full_path)],
        "match_count": match_count,
        "strategy": strategy or "none",
        "lint": lint_result,
    }


# ── V4A parser ──

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

        hunk_match = re.match(r'^@@\s+(.+?)\s+@@$', line.strip())
        if hunk_match and current_op:
            if current_hunk:
                current_hunks.append(current_hunk)
            current_hunk = {
                "context_hint": hunk_match.group(1).strip(),
                "lines": [],
            }
            continue

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

    if current_hunk:
        current_hunks.append(current_hunk)
    if current_op:
        current_op["hunks"] = current_hunks
        operations.append(current_op)

    return operations


def _mode_v4a(patch_content: str) -> dict:
    """Apply a V4A format patch (multi-file Add/Update/Delete)."""
    if not patch_content:
        return {"ok": False, "error": "patch(patch): missing required field 'patch'"}

    from tools.fuzzy_match import fuzzy_find_and_replace

    operations = _parse_v4a(patch_content)
    if not operations:
        return {"ok": False, "error": "patch(patch): failed to parse — no operations found"}

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
                    new_content = ""
                    for hunk in hunks:
                        for line in hunk.get("lines", []):
                            new_content += line["content"] + "\n"
                else:
                    new_content = op.get("raw_content", "")
                if new_content and new_content.endswith("\n\n"):
                    new_content = new_content[:-1]
                full_path.write_text(new_content, encoding="utf-8")
                files_modified.append(str(full_path))
                combined_diff_parts.append(f"Added file: {file_path}")
            except PermissionError as e:
                return {"ok": False, "error": f"patch(patch): permission denied creating {file_path} — {e}"}
            except OSError as e:
                return {"ok": False, "error": f"patch(patch): cannot create {file_path} — {e}"}
            continue

        if action == "Delete":
            if full_path.exists():
                try:
                    full_path.unlink()
                    files_modified.append(str(full_path))
                    combined_diff_parts.append(f"Deleted file: {file_path}")
                except PermissionError as e:
                    return {"ok": False, "error": f"patch(patch): permission denied deleting {file_path} — {e}"}
                except OSError as e:
                    return {"ok": False, "error": f"patch(patch): cannot delete {file_path} — {e}"}
            continue

        if action == "Update":
            content, err = _read_file(full_path)
            if err:
                return {"ok": False, "error": err}

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
                            "error": f"patch(patch): V4A hunk failed — could not find target in {file_path}",
                        }

            if new_content != content:
                diff = _unified_diff(content, new_content, str(full_path))
                try:
                    full_path.write_text(new_content, encoding="utf-8")
                    files_modified.append(str(full_path))
                    combined_diff_parts.append(diff)
                except PermissionError as e:
                    return {"ok": False, "error": f"patch(patch): permission denied writing {file_path} — {e}"}
                except OSError as e:
                    return {"ok": False, "error": f"patch(patch): cannot write {file_path} — {e}"}

    return {
        "ok": True,
        "diff": "\n".join(d for d in combined_diff_parts if d),
        "files_modified": files_modified,
    }


def _mode_verified(patch_content: str) -> dict:
    """Apply verified anchored V4A-style update hunks (merge-conflict detection)."""
    if not patch_content:
        return {"ok": False, "error": "patch(verified): missing required field 'patch'"}

    from tools.verified_patch_core import (
        VerifiedPatchError, VerifiedOperation, apply_operations,
    )
    from tools import fuzzy_match

    operations = _parse_v4a(patch_content)
    if not operations:
        return {"ok": False, "error": "patch(verified): failed to parse — no operations found"}

    for op in operations:
        if op["action"] != "Update":
            return {
                "ok": False,
                "error": "patch(verified): only supports Update hunks. "
                         "Use mode='patch' for Add/Delete operations.",
            }

    resolved = {}
    grouped_ops = {}

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
        return {"ok": False, "error": f"patch(verified): rejected — {e}"}

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
        except PermissionError as e:
            return {"ok": False, "error": f"patch(verified): permission denied writing {file_path} — {e}"}
        except OSError as e:
            return {"ok": False, "error": f"patch(verified): cannot write {file_path} — {e}"}

    return {
        "ok": True,
        "diff": "\n".join(d for d in combined_diff_parts if d),
        "files_modified": files_modified,
    }
