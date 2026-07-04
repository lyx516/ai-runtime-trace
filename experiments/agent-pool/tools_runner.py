#!/usr/bin/env python3
"""
tools_runner — 工具调度中心。
每个 agent 调用工具前，先检查其 tools_allowed 权限（max 5 non-universal）。
"""

import importlib
import os
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent / "tools"
AGENTS_DIR = Path(__file__).resolve().parent / "agents"

# 通用工具 — 不计入 5 个限制
UNIVERSAL_TOOLS = {
    "memory_read",
    "memory_write",
    "skill_create",
    "skill_update",
    "agent_message_send",
    "agent_inbox_read",
    "agent_submit_decision",
    "agent_summarize",
}


def load_tool(tool_id: str):
    """动态加载 tools/<id>/__init__.py 的 run() 函数"""
    try:
        mod = importlib.import_module(f"tools.{tool_id}")
        return getattr(mod, "run", None)
    except (ImportError, AttributeError):
        return None


def check_permission(agent_id: str, tool_id: str) -> tuple[bool, str]:
    """检查 agent 是否有权使用该工具（支持 trait 组合）"""
    if tool_id in UNIVERSAL_TOOLS:
        return True, ""

    meta = AGENTS_DIR / agent_id / "meta.yaml"
    if not meta.exists():
        return False, f"agent {agent_id} 不存在"

    import yaml
    with open(meta) as f:
        info = yaml.safe_load(f)

    # Resolve effective tools via trait system (or legacy tools_allowed)
    try:
        from trait_loader import resolve_agent_tools
        allowed = resolve_agent_tools(info)
    except Exception:
        allowed = info.get("tools_allowed", [])

    max_tools = info.get("max_tools", 90)

    if tool_id not in allowed:
        return False, f"{agent_id} 无权使用工具 '{tool_id}'，允许的: {allowed}"

    if len(allowed) > max_tools:
        return False, f"{agent_id} 工具超限 ({len(allowed)} > {max_tools})"

    return True, ""


def register_tool_call(agent_id: str, tool_id: str, args: dict, result: dict):
    """记录工具调用（后续可写入 trace）"""
    from pathlib import Path
    log_dir = Path("/tmp/agent-tool-logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{agent_id}.log"
    import json, time
    with open(log_file, "a") as f:
        f.write(json.dumps({
            "ts": time.time(),
            "agent": agent_id,
            "tool": tool_id,
            "args_summary": str(args)[:100],
            "ok": result.get("ok", False),
        }, ensure_ascii=False) + "\n")


def execute(agent_id: str, tool_id: str, args: dict) -> dict:
    """执行工具调用（权限检查 + 调度）"""
    ok, err = check_permission(agent_id, tool_id)
    if not ok:
        return {"ok": False, "error": err, "tool": tool_id}

    if tool_id in UNIVERSAL_TOOLS:
        # 通用工具由 auto-debate.py 的 agent_tools 模块处理
        return {"ok": True, "delegated": True, "tool": tool_id}

    run_fn = load_tool(tool_id)
    if run_fn is None:
        return {"ok": False, "error": f"工具 '{tool_id}' 未实现", "tool": tool_id}

    try:
        result = run_fn(args)
        if not isinstance(result, dict):
            result = {"ok": True, "output": str(result)}
        result["tool"] = tool_id
        register_tool_call(agent_id, tool_id, args, result)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e), "tool": tool_id}


def list_available(agent_id: str) -> dict:
    """列出 agent 可用的所有工具（通用 + 专用，支持 trait 组合）"""
    import yaml
    meta = AGENTS_DIR / agent_id / "meta.yaml"
    if not meta.exists():
        return {"universal": list(UNIVERSAL_TOOLS), "allowed": []}

    with open(meta) as f:
        info = yaml.safe_load(f)

    try:
        from trait_loader import resolve_agent_tools
        allowed = resolve_agent_tools(info)
    except Exception:
        allowed = info.get("tools_allowed", [])

    return {
        "universal": sorted(UNIVERSAL_TOOLS),
        "allowed": allowed,
        "max_non_universal": info.get("max_tools", 90),
    }
