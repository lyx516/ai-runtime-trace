#!/usr/bin/env python3
"""Trait Loader — load and merge trait definitions from traits/*.yaml.

Trait = composable capability unit (tools + prompt segment).
Agent declares which traits it uses; the loader merges them.
Supports tools_excluded for per-agent overrides.
"""

import os
from pathlib import Path
from typing import Any

TRAITS_DIR = Path(__file__).resolve().parent / "traits"


def _load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _list_traits() -> dict[str, dict]:
    """Load all trait definitions from traits/*.yaml. Returns {trait_id: data}."""
    traits = {}
    if not TRAITS_DIR.exists():
        return traits
    for f in sorted(TRAITS_DIR.glob("*.yaml")):
        data = _load_yaml(f)
        tid = data.get("trait_id", f.stem)
        traits[tid] = data
    return traits


def resolve_agent_tools(meta: dict) -> list[str]:
    """Resolve effective tools_allowed for an agent: traits → merge → exclude.

    Args:
        meta: Parsed agent meta.yaml dict. May contain:
            - traits: list[trait_id]  (composable capabilities)
            - tools_allowed: list[str]  (legacy, per-agent overrides)
            - tools_excluded: list[str]  (remove specific tools)

    Returns:
        Sorted list of resolved tool names.
    """
    all_traits = _list_traits()
    trait_ids = meta.get("traits", [])
    legacy_tools = meta.get("tools_allowed", [])
    excluded = set(meta.get("tools_excluded", []))

    resolved: set[str] = set()

    # 1. Collect tools from traits
    for tid in trait_ids:
        trait = all_traits.get(tid)
        if trait:
            resolved.update(trait.get("tools_allowed", []))

    # 2. Merge legacy per-agent tools (backward compat)
    resolved.update(legacy_tools)

    # 3. Apply exclusions
    resolved -= excluded

    return sorted(resolved)


def resolve_agent_trait_prompts(meta: dict) -> str:
    """Build a trait-specific prompt segment for an agent.

    Returns a string of rule lines to inject into the system prompt.
    """
    all_traits = _list_traits()
    trait_ids = meta.get("traits", [])

    segments = []
    for tid in trait_ids:
        trait = all_traits.get(tid)
        if trait:
            seg = trait.get("prompt_segment", "").strip()
            if seg:
                segments.append(seg)

    return "\n".join(segments)
