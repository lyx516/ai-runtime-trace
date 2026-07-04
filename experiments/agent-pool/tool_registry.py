#!/usr/bin/env python3
"""Tool Registry — auto-generate OpenAI tool schemas from tools/<id>/__init__.py.

Each tool module exports run(args: dict) -> dict. This registry:
1. Discovers all tools in tools/<id>/
2. Reads meta.yaml per agent for tools_allowed + universal tools
3. Generates OpenAI-compatible function-calling schemas
4. Executes tools via the existing tools_runner
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
    "agent_inbox_read",
    "agent_submit_decision",
    "agent_summarize",
    "human_clarifier",
}


def _add_paths():
    """Ensure tools/ is importable."""
    tools_path = str(TOOLS_DIR)
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)


def _load_tool_module(tool_id: str):
    """Dynamically import tools.<tool_id> and return the module."""
    _add_paths()
    try:
        return importlib.import_module(f"tools.{tool_id}")
    except (ImportError, ModuleNotFoundError) as e:
        return None


def discover_all_tools() -> dict[str, dict]:
    """Scan tools/ directory and return {tool_id: {module, run_fn, doc}}."""
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


def _infer_type_from_default(default: Any) -> str:
    """Infer JSON Schema type from a Python default value."""
    if default is None:
        return "string"
    if isinstance(default, bool):
        return "boolean"
    if isinstance(default, int):
        return "integer"
    if isinstance(default, float):
        return "number"
    if isinstance(default, str):
        return "string"
    if isinstance(default, list):
        return "array"
    if isinstance(default, dict):
        return "object"
    return "string"


def _infer_type_from_name(name: str) -> str:
    """Infer JSON Schema type from parameter name heuristics."""
    name_lower = name.lower()
    if any(kw in name_lower for kw in ("count", "limit", "offset", "size", "timeout", "max", "min", "port", "index")):
        return "integer"
    if any(kw in name_lower for kw in ("enable", "disabled", "verbose", "flag", "recursive")):
        return "boolean"
    return "string"


def _generate_parameter_schema(run_fn) -> dict:
    """Given a run(args: dict) function, infer the JSON Schema of the 'args' dict.

    Uses the docstring to extract parameter descriptions, and the function body's
    .get() calls to infer parameter names and defaults.
    """
    # Try to get signature
    try:
        sig = inspect.signature(run_fn)
    except (ValueError, TypeError):
        return {"type": "object", "properties": {}, "description": "Arbitrary key-value arguments."}

    params = list(sig.parameters.values())
    if not params:
        return {"type": "object", "properties": {}, "description": "No parameters."}

    first_param = params[0]
    if first_param.name != "args":
        # If the function takes named args directly, use those
        properties = {}
        required = []
        for p in params:
            if p.name == "self" or p.name == "cls":
                continue
            default = None if p.default is inspect.Parameter.empty else p.default
            has_default = p.default is not inspect.Parameter.empty
            ptype = _infer_type_from_default(default) if has_default else _infer_type_from_name(p.name)
            prop = {"type": ptype}
            if not has_default:
                required.append(p.name)
            properties[p.name] = prop
        return {"type": "object", "properties": properties, "required": required}

    # First param is 'args' (dict) — extract from docstring
    # The docstring format expected:
    #   Args:
    #     key_name (type): description
    doc = (run_fn.__doc__ or "") + (run_fn.__module__ and (getattr(inspect.getmodule(run_fn), "__doc__", "") or ""))

    # Also check for .get("key", default) calls in source
    properties = {}
    required = []

    try:
        source = inspect.getsource(run_fn)
    except (OSError, TypeError):
        source = ""

    # Find .get("key", default) or .get('key', default) patterns
    import re
    get_calls = re.findall(r'\.get\s*\(\s*["\']([^"\']+)["\']\s*(?:,\s*([^)]+))?\s*\)', source)

    seen = set()
    for key, default_str in get_calls:
        if key in seen:
            continue
        seen.add(key)
        default_str = default_str.strip() if default_str else ""
        if default_str:
            # Try to infer type from default value string
            try:
                default_val = eval(default_str, {"__builtins__": {}}, {})
                ptype = _infer_type_from_default(default_val)
                # Empty defaults ("", 0, []) still mean the param is required
                is_empty_default = (
                    default_val == "" or default_val == 0 or
                    default_val == [] or default_val == {} or
                    default_val is None
                )
                if is_empty_default:
                    required.append(key)
            except Exception:
                ptype = _infer_type_from_name(key)
        else:
            ptype = _infer_type_from_name(key)
            required.append(key)

        properties[key] = {
            "type": ptype,
            "description": key.replace("_", " ").capitalize(),
        }

    # Fallback: if no .get() calls found, use signature of the module docstring
    if not properties:
        # Default generic schema
        properties = {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "File content"},
        }

    result = {"type": "object", "properties": properties}
    if required:
        result["required"] = list(dict.fromkeys(required))  # unique, preserve order
    return result



def _patch_tool_schema() -> dict:
    """Hand-crafted schema for patch tool — simpler without create mode."""
    return {
        "type": "function",
        "function": {
            "name": "patch",
            "description": (
                "Edit existing files. "
                "mode='replace': find old_string and replace with new_string in a file. Requires path, old_string, new_string. "
                "mode='patch': V4A multi-file batch edit. Requires patch (multi-file patch text). "
                "To CREATE a new file, use the terminal tool: terminal(command='cat > path/file.md << '\''EOF'\''\\ncontent\\nEOF')"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "patch", "verified"],
                        "description": "replace (edit a file) or patch (V4A multi-file batch) or verified (safe anchored edit)"
                    },
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace. Required for replace mode."
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Text to find. Required for replace mode."
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text. Required for replace mode."
                    },
                    "patch": {
                        "type": "string",
                        "description": "V4A patch content. Required for patch/verified mode."
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences. Default: false."
                    }
                },
                "required": ["mode"]
            }
        }
    }

def build_tool_schema(tool_id: str, tool_info: dict) -> dict:
    """Build a single OpenAI-compatible tool schema entry."""
    run_fn = tool_info["run_fn"]
    doc = tool_info["doc"]

    if tool_id == "patch":
        return _patch_tool_schema()

    parameters = _generate_parameter_schema(run_fn)

    # Build description: module docstring + parameter hints
    description_parts = [doc] if doc else [f"Tool: {tool_id}"]
    props = parameters.get("properties", {})
    if props:
        param_desc = "; ".join(
            f"{k}: {v.get('description', k)} ({v.get('type', 'string')})"
            for k, v in props.items()
        )
        if param_desc:
            description_parts.append(f"Parameters: {param_desc}")

    return {
        "type": "function",
        "function": {
            "name": tool_id,
            "description": " | ".join(description_parts),
            "parameters": parameters,
        },
    }


# ── Agent tool resolution ──────────────────────────────────────────────

def _load_agent_meta(agent_id: str) -> dict:
    """Load an agent's meta.yaml."""
    import yaml
    meta = AGENTS_DIR / agent_id / "meta.yaml"
    if not meta.exists():
        return {}
    with open(meta) as f:
        return yaml.safe_load(f) or {}


def get_agent_tools_schemas(agent_id: str) -> list[dict]:
    """Get OpenAI tool schemas for all tools available to an agent.

    Uses the trait system: resolves tools from agent's declared traits
    + per-agent overrides, then generates OpenAI schemas.
    Falls back to legacy tools_allowed for backward compatibility.
    """
    from trait_loader import resolve_agent_tools

    meta = _load_agent_meta(agent_id)

    # Use trait system; fall back to legacy tools_allowed
    if meta.get("traits"):
        allowed = resolve_agent_tools(meta)
    else:
        allowed = meta.get("tools_allowed", [])

    allowed_set = set(allowed)
    all_tools = discover_all_tools()

    schemas = []

    # Universal tools that exist in the tools/ directory
    for uid in sorted(UNIVERSAL_TOOLS):
        if uid in all_tools:
            schemas.append(build_tool_schema(uid, all_tools[uid]))

    # Allowed tools (from traits + per-agent overrides)
    for tool_id in sorted(allowed_set):
        if tool_id in all_tools:
            schemas.append(build_tool_schema(tool_id, all_tools[tool_id]))

    return schemas


def execute_tool(tool_id: str, args: dict, agent_id: str = "") -> dict:
    """Execute a tool by ID. Loads tools/<id>/__init__.py dynamically."""
    import importlib.util
    from pathlib import Path

    tools_dir = Path(__file__).resolve().parent / "tools"
    mod_path = tools_dir / tool_id / "__init__.py"

    if not mod_path.exists():
        return {"ok": False, "error": f"Tool '{tool_id}' not found", "tool": tool_id}

    try:
        spec = importlib.util.spec_from_file_location(f"tools_{tool_id}", str(mod_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        run_fn = getattr(mod, "run", None)
        if run_fn is None:
            return {"ok": False, "error": f"Tool '{tool_id}' has no run()", "tool": tool_id}
        result = run_fn(args)
        if not isinstance(result, dict):
            result = {"ok": True, "output": str(result)}
        result["tool"] = tool_id
        return result
    except Exception as e:
        return {"ok": False, "error": str(e), "tool": tool_id}


def format_tool_results_for_llm(tool_id: str, result: dict) -> str:
    """Format tool execution result for LLM consumption."""
    ok = result.get("ok", False)
    error = result.get("error", "")
    if not ok:
        return f"[Tool {tool_id} failed: {error}]"
    # Strip internal keys
    display = {k: v for k, v in result.items() if k not in ("ok", "tool")}
    return f"[Tool {tool_id} result: {json.dumps(display, ensure_ascii=False)[:2000]}]"


# ── Decision tool — special, not in tools/ dir ─────────────────────────

DECISION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_decision",
        "description": "Submit your final decision to advance the flow. Call this when you have completed your work and are ready to move to the next state.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "enum": ["APPROVE", "REQUEST_CHANGES", "BLOCKED"],
                    "description": "APPROVE = work done, advance. REQUEST_CHANGES = need revision. BLOCKED = cannot continue.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of your decision (1-2 sentences in Chinese or English).",
                },
            },
            "required": ["value", "reason"],
        },
    },
}
