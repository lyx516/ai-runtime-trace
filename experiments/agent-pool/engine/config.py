"""Path constants and environment defaults."""

import os
from pathlib import Path

# Script location (agents, tools, skills live alongside engine/)
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
# Project root (where hermes_flow package lives)
_PROJECT_ROOT_DIR = _SCRIPT_DIR.parent.parent
# Runtime project root (where runs/artifacts are searched/created)
PROJECT_ROOT = os.environ.get("HERMES_FLOW_PROJECT_ROOT") or str(_PROJECT_ROOT_DIR)

# Default runs directory: alongside agent-pool/
if "HERMES_FLOW_RUNS_DIR" not in os.environ:
    os.environ["HERMES_FLOW_RUNS_DIR"] = str(_SCRIPT_DIR / ".hermes-flow" / "runs")

AGENTS_DIR = _SCRIPT_DIR / "agents"
SHARED_SKILLS_DIR = _SCRIPT_DIR / "shared" / "skills"
OUTPUT_DIR = _SCRIPT_DIR / "generated"

# LLM config persistence (user home, NOT inside project — avoids key in git)
LLM_CONFIG_DIR = Path.home() / ".hermes-flow"
LLM_CONFIG_PATH = LLM_CONFIG_DIR / "llm_config.json"