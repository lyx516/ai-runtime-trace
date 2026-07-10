#!/usr/bin/env python3
"""Tool Registry — hand-crafted OpenAI tool schemas + unified dispatch.

Each tool module exports run(args: dict) -> dict. This registry:
1. Discovers all tools in tools/<id>/
2. Uses hand-crafted schemas (not auto-generated from docstrings)
3. Generates OpenAI-compatible function-calling schemas
4. Executes tools with result truncation and error sanitization
"""

import importlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Always resolve relative to THIS file, regardless of env vars or cwd
_MODULE_DIR = Path(__file__).resolve().parent
TOOLS_DIR = _MODULE_DIR / "tools"
AGENTS_DIR = _MODULE_DIR / "agents"

# Universal tools available to all agents (not in meta.yaml's tools_allowed)
UNIVERSAL_TOOLS = {
    "agent_message_send",
    "skill_load",
    "memory_read",
    "memory_write",
}

# ── Per-tool max result size (chars) before truncation ─────────────────
# These prevent web_search / file_read output from flooding context.
_TOOL_MAX_RESULT_CHARS: dict[str, int] = {
    "web_search": 3_000,
    "file_read": 8_000,
    "search_files": 4_000,
    "write_file": 500,
    "patch": 1_000,
    "code_exec": 5_000,
    "terminal": 5_000,
}
_DEFAULT_MAX_RESULT_CHARS = 2_000


# ═══════════════════════════════════════════════════════════════════════
#  Hand-crafted tool schemas — each tool module exports its own SCHEMA
# ═══════════════════════════════════════════════════════════════════════

# _HAND_CRAFTED_SCHEMAS removed. Each tool/<id>/__init__.py now exports
# a module-level SCHEMA dict (OpenAI function-calling format).
# Tool schemas are auto-discovered via discover_all_tools().
# Universal tool schemas (memory, skill, message) remain in _UNIVERSAL_TOOL_SCHEMAS.

_EMPTY = {}

# ── Universal tool schemas ─────────────────────────────────────────────

_UNIVERSAL_TOOL_SCHEMAS: dict[str, dict] = {
    "agent_message_send": {
        "name": "agent_message_send",
        "description": "Send a message to another agent. Use for collaboration and clarification.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of agent IDs to send to.",
                },
                "content": {"type": "string", "description": "Message content."},
            },
            "required": ["recipients", "content"],
        },
    },
    "skill_load": {
        "name": "skill_load",
        "description": "Load a skill file by name. Returns full skill content. Use when you need detailed guidance for a specific task.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Skill file name (e.g. 'speckit-specify', 'speckit-implement').",
                },
            },
            "required": ["skill_name"],
        },
    },
}

# ── Decision tool — not in tools/ dir ──────────────────────────────────

DECISION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_decision",
        "description": (
            "Submit your final decision to advance the flow. "
            "Call this when you have completed your work and are ready to move to the next state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "enum": ["APPROVE", "REQUEST_CHANGES", "BLOCKED"],
                    "description": (
                        "APPROVE = work done, advance. "
                        "REQUEST_CHANGES = need revision. "
                        "BLOCKED = cannot continue."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation (1-2 sentences in Chinese or English).",
                },
            },
            "required": ["value", "reason"],
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════
#  Schema building (hand-crafted, minimal fallback)
# ═══════════════════════════════════════════════════════════════════════

def build_tool_schema(tool_id: str, tool_info: dict) -> dict:
    """Return an OpenAI-format tool schema for *tool_id*.

    1. Prefers SCHEMA from the tool's __init__.py (auto-discovered).
    2. Falls back to _UNIVERSAL_TOOL_SCHEMAS for built-in universal tools.
    3. Falls back to a minimal auto-generated schema from the run() signature.
    """
    # SCHEMA from tool module (auto-discovered)
    schema = tool_info.get("SCHEMA")
    if schema is not None:
        return {"type": "function", "function": schema}

    # Universal tools with hand-crafted schemas
    if tool_id in _UNIVERSAL_TOOL_SCHEMAS:
        return {"type": "function", "function": _UNIVERSAL_TOOL_SCHEMAS[tool_id]}

    # Fallback: minimal auto-generated schema
    run_fn = tool_info.get("run_fn")
    doc = tool_info.get("doc", f"Tool: {tool_id}")
    properties = _fallback_properties(run_fn)
    return {
        "type": "function",
        "function": {
            "name": tool_id,
            "description": doc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties.keys()),
            },
        },
    }


def _fallback_properties(run_fn) -> dict:
    """Minimal fallback: extract .get() keys from run_fn source."""
    if run_fn is None:
        return {}
    try:
        source = inspect.getsource(run_fn)
    except (OSError, TypeError):
        return {}
    import re
    keys = re.findall(r'\.get\s*\(\s*["\']([^"\']+)["\']', source)
    seen = set()
    props = {}
    for k in keys:
        if k not in seen:
            seen.add(k)
            props[k] = {"type": "string", "description": k.replace("_", " ")}
    return props


# ═══════════════════════════════════════════════════════════════════════
#  Tool discovery (unchanged from original)
# ═══════════════════════════════════════════════════════════════════════

def _add_paths():
    tools_path = str(TOOLS_DIR)
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)


def _load_tool_module(tool_id: str):
    _add_paths()
    try:
        return importlib.import_module(f"tools.{tool_id}")
    except (ImportError, ModuleNotFoundError):
        return None


def discover_all_tools() -> dict[str, dict]:
    if not TOOLS_DIR.exists():
        return {}
    tools = {}
    for d in sorted(TOOLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        init = d / "__init__.py"
        if not init.exists():
            continue
        tool_id = d.name
        mod = _load_tool_module(tool_id)
        if mod is None:
            continue
        run_fn = getattr(mod, "run", None)
        if run_fn is None:
            continue
        doc = (mod.__doc__ or "").strip()
        schema = getattr(mod, "SCHEMA", None)
        tools[tool_id] = {
            "module": mod,
            "run_fn": run_fn,
            "doc": doc,
            "SCHEMA": schema,
            "tool_id": tool_id,
        }
    return tools


# ═══════════════════════════════════════════════════════════════════════
#  Agent tool resolution
# ═══════════════════════════════════════════════════════════════════════

def _load_agent_meta(agent_id: str) -> dict:
    import yaml
    meta = AGENTS_DIR / agent_id / "meta.yaml"
    if not meta.exists():
        return {}
    with open(meta) as f:
        return yaml.safe_load(f) or {}


def get_agent_tools_schemas(agent_id: str) -> list[dict]:
    from trait_loader import resolve_agent_tools
    meta = _load_agent_meta(agent_id)
    if meta.get("traits"):
        allowed = resolve_agent_tools(meta)
    else:
        allowed = meta.get("tools_allowed", [])
    allowed_set = set(allowed)
    all_tools = discover_all_tools()
    schemas = []
    # Universal tools — send schema even without a tool module directory
    for uid in sorted(UNIVERSAL_TOOLS):
        if uid in all_tools:
            schemas.append(build_tool_schema(uid, all_tools[uid]))
        elif uid in _UNIVERSAL_TOOL_SCHEMAS:
            schemas.append({"type": "function", "function": _UNIVERSAL_TOOL_SCHEMAS[uid]})
    for tool_id in sorted(allowed_set):
        if tool_id in all_tools:
            schemas.append(build_tool_schema(tool_id, all_tools[tool_id]))
    return schemas


# ═══════════════════════════════════════════════════════════════════════
#  Unified tool dispatch with result truncation + error sanitization
# ═══════════════════════════════════════════════════════════════════════

def _truncate_str(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars* chars, breaking at the last newline."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[:last_nl]
    return truncated + f"\n... [truncated from {len(text):,} chars]"


def _sanitize_error(exc: Exception) -> str:
    """Return a safe error string, stripping sensitive paths."""
    msg = f"{type(exc).__name__}: {exc}"
    # Strip home directory paths
    home = str(Path.home())
    msg = msg.replace(home, "~")
    return msg[:500]


def execute_tool(tool_id: str, args: dict, agent_id: str = "") -> dict:
    """Execute a tool with unified error handling and result truncation.

    Returns a sanitized dict with shape ``{"ok": bool, "tool": str, ...}``.
    Top-level exceptions are caught and returned as error dicts — the caller
    never receives an unhandled traceback.
    """
    import importlib.util

    tools_dir = Path(__file__).resolve().parent / "tools"
    mod_path = tools_dir / tool_id / "__init__.py"

    if not mod_path.exists():
        return {"ok": False, "error": f"Unknown tool: {tool_id}", "tool": tool_id}

    try:
        spec = importlib.util.spec_from_file_location(f"tools_{tool_id}", str(mod_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        run_fn = getattr(mod, "run", None)
        if run_fn is None:
            return {"ok": False, "error": f"Tool '{tool_id}' has no run()", "tool": tool_id}

        # ── Security enforcement (read/write boundaries) ───────────────
        from tools._security import check_read_allowed, check_write_sandboxed, _PROJECT_ROOT, get_sandbox_root

        def _deny(err_msg: str) -> dict:
            return {"ok": False, "error": err_msg, "tool": tool_id}

        if tool_id in ("file_read", "search_files"):
            path_arg = args.get("path")
            if path_arg:
                err = check_read_allowed(path_arg)
                if err:
                    return _deny(err)

        sandbox_override = False
        if tool_id in ("write_file", "patch"):
            original_path = args.get("path", "")
            if not original_path:
                return _deny(f"{tool_id} requires a path")

            redirected = check_write_sandboxed(original_path)
            if redirected is not None:
                # Sandbox mode: redirect writes to safe sandbox path
                redirected.parent.mkdir(parents=True, exist_ok=True)
                args = {**args, "path": str(redirected)}
                sandbox_override = True
            else:
                # Normal mode: verify this is a legitimate project write
                _resolved = Path(original_path).resolve()
                if not str(_resolved).startswith(str(_PROJECT_ROOT)):
                    return _deny(f"{tool_id} denied: {original_path} is outside project root")
            # TODO: auto-backup protected dirs via check_write_backup()
            #       requires store/run_id, not available in execute_tool layer.

        if sandbox_override:
            sandbox_root = get_sandbox_root()
            old_workspace = os.environ.get("HERMES_WORKSPACE_ROOT", "")
            os.environ["HERMES_WORKSPACE_ROOT"] = str(sandbox_root)
            try:
                result = run_fn(args)
            finally:
                if old_workspace:
                    os.environ["HERMES_WORKSPACE_ROOT"] = old_workspace
                else:
                    os.environ.pop("HERMES_WORKSPACE_ROOT", None)
        else:
            result = run_fn(args)

        # Normalize: ensure result is a dict with standard keys
        if not isinstance(result, dict):
            result = {"ok": True, "output": str(result)}
        result.setdefault("ok", True)
        result["tool"] = tool_id

        # ── Result truncation ──────────────────────────────────────────
        max_chars = _TOOL_MAX_RESULT_CHARS.get(tool_id, _DEFAULT_MAX_RESULT_CHARS)
        for key in ("output", "content", "stdout", "stderr", "results"):
            if key in result and isinstance(result[key], str):
                original_len = len(result[key])
                result[key] = _truncate_str(result[key], max_chars)
                if len(result[key]) < original_len:
                    result["_truncated"] = True
                break

        return result

    except Exception as exc:
        return {
            "ok": False,
            "error": _sanitize_error(exc),
            "tool": tool_id,
        }


def format_tool_results_for_llm(tool_id: str, result: dict) -> str:
    """Format a tool result for LLM consumption, with truncation."""
    ok = result.get("ok", False)
    error = result.get("error", "")
    if not ok:
        return f"[Tool {tool_id} failed: {error}]"

    # Build display dict, stripping internal keys
    skip_keys = {"ok", "tool", "_truncated"}
    display = {k: v for k, v in result.items() if k not in skip_keys}

    # Truncate the formatted output
    max_chars = _TOOL_MAX_RESULT_CHARS.get(tool_id, _DEFAULT_MAX_RESULT_CHARS)
    formatted = json.dumps(display, ensure_ascii=False)
    if len(formatted) > max_chars:
        formatted = formatted[:max_chars] + "..."
    if result.get("_truncated"):
        formatted += " [output was truncated]"

    return f"[Tool {tool_id} result: {formatted}]"
