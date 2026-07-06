"""Agent pool loader — reads agents/<id>/meta.yaml into a dict.

Reads the optional ``model:`` field from meta.yaml for per-agent LLM model
configuration.  Agents without the field use the default model.
"""

from __future__ import annotations

import sys
from pathlib import Path

from engine.config import AGENTS_DIR, SHARED_SKILLS_DIR


def load_agents() -> dict:
    """Load all agents from agents/<id>/meta.yaml."""
    import yaml
    agents: dict[str, dict] = {}
    if not AGENTS_DIR.exists():
        print("❌ Agent 池目录不存在", file=sys.stderr)
        sys.exit(1)
    for d in sorted(AGENTS_DIR.iterdir()):
        meta = d / "meta.yaml"
        if meta.exists():
            with open(meta) as f:
                info = yaml.safe_load(f)
                info["_path"] = str(d)
                # Resolve assigned skills from shared/skills/
                assigned = info.get("assigned_skills", [])
                resolved = []
                if SHARED_SKILLS_DIR.exists():
                    for sid in assigned:
                        sp = SHARED_SKILLS_DIR / sid / "SKILL.md"
                        if sp.exists():
                            text = sp.read_text(encoding="utf-8")
                            desc = sid
                            if text.startswith("---"):
                                parts = text.split("---", 2)
                                if len(parts) >= 3:
                                    import yaml as y2
                                    fm = y2.safe_load(parts[1])
                                    desc = fm.get("description", sid)
                            resolved.append({"id": sid, "description": desc, "content": text[:1000]})
                info["_assigned_skills"] = resolved
                agents[info["agent_id"]] = info
    return agents


def load_team_skills() -> list[dict]:
    """Scan manager/skills/*.md, parse YAML frontmatter + doc body into skill dicts."""
    import yaml as yaml_lib
    skills_dir = AGENTS_DIR / "manager" / "skills"
    skills: list[dict] = []
    if not skills_dir.exists():
        return skills
    for f in sorted(skills_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        fm = yaml_lib.safe_load(parts[1])
        doc_body = parts[2].strip()
        skills.append({
            "file": f.name,
            "name": fm.get("name", f.stem),
            "description": fm.get("description", ""),
            "agents": fm.get("agents", []),
            "flow": fm.get("flow", []),
            "output_base": fm.get("output_base", ""),
            "doc": doc_body,
        })
    return skills