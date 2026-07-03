#!/usr/bin/env python3
"""
agent_tools — 每个 agent 可调用的通用工具（不计入 5 个限制）。
参考 Hermes 的 agent_tools 设计，独立实现。
"""

import os
import json
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent / "agents"
MEMORY_MAX = 3000


def _agent_dir(agent_id: str) -> Path:
    return AGENTS_DIR / agent_id


def memory_read(agent_id: str) -> dict:
    """读取 agent 的 Memory.md"""
    path = _agent_dir(agent_id) / "Memory.md"
    if not path.exists():
        return {"ok": True, "content": "", "char_count": 0}
    content = path.read_text(encoding="utf-8")
    return {"ok": True, "content": content, "char_count": len(content), "max_chars": MEMORY_MAX}


def memory_write(agent_id: str, content: str, mode: str = "append") -> dict:
    """写入 agent 的 Memory.md，自动截断到 3K"""
    path = _agent_dir(agent_id) / "Memory.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    header = existing.split("\n\n-----\n")[0] if mode == "append" else f"# Memory: {agent_id}\n> Max length: {MEMORY_MAX} chars. Write runtime experience here.\n"

    if mode == "overwrite":
        new_content = content
    else:
        new_content = f"\n-----\n{content}"

    full = header + "\n" + new_content
    # Truncate to 3K
    if len(full) > MEMORY_MAX:
        full = full[:MEMORY_MAX] + "\n\n[truncated]"

    path.write_text(full, encoding="utf-8")
    return {"ok": True, "char_count": len(full), "max_chars": MEMORY_MAX, "truncated": len(full) >= MEMORY_MAX}


def skill_create(agent_id: str, name: str, content: str) -> dict:
    """在 agent 的 skills/ 目录创建 skill 文件"""
    skills_dir = _agent_dir(agent_id) / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path), "bytes": len(content)}


def skill_list(agent_id: str) -> dict:
    """列出 agent 的所有 skill"""
    skills_dir = _agent_dir(agent_id) / "skills"
    if not skills_dir.exists():
        return {"ok": True, "skills": []}
    files = sorted(skills_dir.iterdir())
    return {"ok": True, "skills": [f.name for f in files if f.suffix == ".md"]}


def agent_summarize(agent_id: str, transcript: str) -> dict:
    """Agent 写自己的辩论总结（辩论结束后调用）"""
    path = _agent_dir(agent_id) / "Memory.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    summary = f"\n\n## 辩论总结\n{transcript[:2500]}"
    full = existing + summary
    if len(full) > MEMORY_MAX:
        full = full[:MEMORY_MAX] + "\n\n[truncated]"
    path.write_text(full, encoding="utf-8")
    return {"ok": True, "char_count": len(full)}


def dispatch(agent_id: str, tool_id: str, args: dict) -> dict:
    """Dispatch universal tool by name"""
    if tool_id == "memory_read":
        return memory_read(agent_id)
    elif tool_id == "memory_write":
        return memory_write(agent_id, args.get("content", ""), args.get("mode", "append"))
    elif tool_id == "skill_create":
        return skill_create(agent_id, args.get("name", ""), args.get("content", ""))
    elif tool_id == "skill_list":
        return skill_list(agent_id)
    elif tool_id == "agent_summarize":
        return agent_summarize(agent_id, args.get("transcript", ""))
    return {"ok": False, "error": f"unknown universal tool: {tool_id}"}
