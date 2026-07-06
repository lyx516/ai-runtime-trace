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
    "memory_read",
    "memory_write",
    "skill_create",
    "skill_update",
    "agent_message_send",
    "skill_load",
    "agent_recall",
    "agent_submit_decision",
    "agent_summarize",
    "human_clarifier",
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
#  Hand-crafted tool schemas (inspired by Hermes Agent)
# ═══════════════════════════════════════════════════════════════════════

_HAND_CRAFTED_SCHEMAS: dict[str, dict] = {
    # ── write_file ─────────────────────────────────────────────────────
    "write_file": {
        "name": "write_file",
        "description": (
            "Create a new file or completely overwrite an existing file. "
            "Creates parent directories automatically. Both 'path' and 'content' are REQUIRED. "
            "Use this for creating deliverable files (spec.md, plan.md, tasks.md, etc.). "
            "For editing existing files, use the 'patch' tool instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace. Example: 'output/auto-xxx/spec.md'",
                },
                "content": {
                    "type": "string",
                    "description": "Complete file content as a string.",
                },
            },
            "required": ["path", "content"],
        },
    },
    # ── file_read ───────────────────────────────────────────────────────
    "file_read": {
        "name": "file_read",
        "description": (
            "Read a text file with line numbers and pagination. "
            "Use offset and limit for large files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to workspace.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed, default: 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default: 50, max: 500).",
                },
            },
            "required": ["path"],
        },
    },
    # ── patch ───────────────────────────────────────────────────────────
    "patch": {
        "name": "patch",
        "description": (
            "Edit existing files with targeted find-and-replace. "
            "mode='replace': find old_string in a file and replace with new_string. "
            "Requires path, old_string, new_string. "
            "mode='patch': apply a V4A multi-file batch edit. "
            "To CREATE a new file, use write_file instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["replace", "patch"],
                    "description": "'replace' for single-file edit, 'patch' for V4A multi-file batch.",
                },
                "path": {
                    "type": "string",
                    "description": "File path. Required for replace mode.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Text to find. Required for replace mode.",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text. Required for replace mode.",
                },
                "patch": {
                    "type": "string",
                    "description": "V4A patch content. Required for patch mode.",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences. Default: false.",
                },
            },
            "required": ["mode"],
        },
    },
    # ── search_files ────────────────────────────────────────────────────
    "search_files": {
        "name": "search_files",
        "description": (
            "Search file contents (grep) or find files by name. "
            "Use type='content' to search inside files, type='files' to list filenames."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["content", "files"],
                    "description": "'content' to grep, 'files' to list filenames.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Search pattern — regex for content, glob for files.",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory).",
                },
                "file_glob": {
                    "type": "string",
                    "description": "Filter files by extension pattern, e.g. '*.py'.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip first N results (default: 0).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 50, max: 200).",
                },
                "context": {
                    "type": "integer",
                    "description": "Lines of context around matches (default: 0).",
                },
            },
            "required": ["pattern"],
        },
    },
    # ── web_search ──────────────────────────────────────────────────────
    "web_search": {
        "name": "web_search",
        "description": (
            "Search the web for information. Use curl to fetch search results. "
            "Returns a summary of top results. Use for research and fact-checking."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string.",
                },
            },
            "required": ["query"],
        },
    },
    # ── code_exec ───────────────────────────────────────────────────────
    "code_exec": {
        "name": "code_exec",
        "description": (
            "Execute a Python script in an isolated environment. "
            "The script can use the Python standard library. "
            "Use for data processing, computation, or file manipulation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute.",
                },
            },
            "required": ["code"],
        },
    },
    # ── terminal ────────────────────────────────────────────────────────
    "terminal": {
        "name": "terminal",
        "description": (
            "Execute a shell command. Use for system operations — "
            "mkdir, mv, cp, git, pip install, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for the command.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max execution time in seconds.",
                },
            },
            "required": ["command"],
        },
    },
}

# ── Universal tool schemas ─────────────────────────────────────────────

_UNIVERSAL_TOOL_SCHEMAS: dict[str, dict] = {
    "memory_read": {
        "name": "memory_read",
        "description": "Read agent's persistent memory (key-value store). Use to recall context from previous sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key to read."},
            },
            "required": ["key"],
        },
    },
    "memory_write": {
        "name": "memory_write",
        "description": "Write a value to agent's persistent memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key."},
                "value": {"type": "string", "description": "Value to store."},
            },
            "required": ["key", "value"],
        },
    },
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
    "agent_recall": {
        "name": "agent_recall",
        "description": (
            "Recall runtime data from a flow run's SQLite database — "
            "decisions, tool usage, state transitions, and agent messages. "
            "Pure SQLite reads — no LLM processing, returns raw data.\n\n"
            "FIVE CALLING SHAPES (inferred from query parameter):\n\n"
            "  OVERVIEW — agent_recall(query=\"overview\"): run status, agents, state/decision/msg counts.\n"
            "  TRANSITIONS — agent_recall(query=\"transitions\"): state path with retry detection.\n"
            "  DECISIONS — agent_recall(query=\"decisions\", agent=\"x\"): who approved/rejected what.\n"
            "  THINKING — agent_recall(query=\"thinking\", agent=\"x\", limit=20, offset=0): tool call log with pagination.\n"
            "  MESSAGES — agent_recall(query=\"messages\", state=\"IMPLEMENT\"): agent-to-agent messages.\n\n"
            "PAGINATION: when has_more=true, use offset + limit for next page. "
            "Use to investigate agent behavior BEFORE making judgments."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "enum": ["overview", "transitions", "decisions", "thinking", "messages"],
                    "description": "What data to recall.",
                },
                "agent": {
                    "type": "string",
                    "description": "Filter by agent_id (e.g. 'implementer').",
                },
                "state": {
                    "type": "string",
                    "description": "Filter by state_id (e.g. 'IMPLEMENT').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Rows per page (default 20, max 50).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Row offset for pagination (default 0).",
                },
            },
            "required": ["query"],
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

    Prefers hand-crafted schemas; falls back to a minimal auto-generated
    schema when the tool does not have a hand-crafted entry.
    """
    # Hand-crafted schema
    if tool_id in _HAND_CRAFTED_SCHEMAS:
        return {"type": "function", "function": _HAND_CRAFTED_SCHEMAS[tool_id]}

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
        tools[tool_id] = {
            "module": mod,
            "run_fn": run_fn,
            "doc": doc,
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
        if uid in _UNIVERSAL_TOOL_SCHEMAS:
            schemas.append({"type": "function", "function": _UNIVERSAL_TOOL_SCHEMAS[uid]})
        elif uid in all_tools:
            schemas.append(build_tool_schema(uid, all_tools[uid]))
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
