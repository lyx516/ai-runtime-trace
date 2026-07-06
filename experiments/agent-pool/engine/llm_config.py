"""LLM configuration — default model, API URL, API key.

Resolution priority (high → low):
  1. CLI runtime overrides (--model, --api-url, --api-key) — session only
  2. JSON config file (~/.hermes-flow/llm_config.json) — persistent
  3. Environment variables (DEEPSEEK_API_KEY / OPENAI_API_KEY) — backward compat
  4. Hardcoded defaults (deepseek-v4-flash @ api.deepseek.com)

Per-agent model: if an agent's meta.yaml has a ``model:`` field, that model
name is used for LLM calls made on behalf of that agent.  Agents without the
field fall back to the default model from the config above.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from engine.config import LLM_CONFIG_PATH, LLM_CONFIG_DIR


# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULT_MODEL = "deepseek-v4-flash"
_DEFAULT_API_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_MAX_TOKENS = 8192


@dataclass
class LLMConfig:
    """Resolved LLM configuration."""
    model: str = _DEFAULT_MODEL
    api_url: str = _DEFAULT_API_URL
    api_key: str = ""
    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS


# ── Load / save ──────────────────────────────────────────────────────────────

def load_config() -> LLMConfig:
    """Load merged config: JSON file → env vars → defaults.

    Priority (high → low):
      1. CLI runtime override env vars (HERMES_LLM_MODEL / HERMES_LLM_API_URL / HERMES_LLM_API_KEY)
      2. JSON config file (~/.hermes-flow/llm_config.json)
      3. Legacy env vars (DEEPSEEK_API_KEY / OPENAI_API_KEY)
      4. Hardcoded defaults
    """
    cfg = LLMConfig()

    # 1. JSON config file (persistent)
    if LLM_CONFIG_PATH.exists():
        try:
            data = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.model = data.get("model", cfg.model)
            cfg.api_url = data.get("api_url", cfg.api_url)
            cfg.api_key = data.get("api_key", cfg.api_key)
            cfg.temperature = data.get("temperature", cfg.temperature)
            cfg.max_tokens = data.get("max_tokens", cfg.max_tokens)
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Legacy env vars (backward compat — only fill gaps)
    env_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if env_key and not cfg.api_key:
        cfg.api_key = env_key

    # 3. CLI runtime overrides (highest priority, set by --model/--api-url/--api-key)
    cli_model = os.environ.get("HERMES_LLM_MODEL", "")
    cli_url = os.environ.get("HERMES_LLM_API_URL", "")
    cli_key = os.environ.get("HERMES_LLM_API_KEY", "")
    if cli_model:
        cfg.model = cli_model
    if cli_url:
        cfg.api_url = cli_url
    if cli_key:
        cfg.api_key = cli_key

    return cfg


def save_config(
    model: Optional[str] = None,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> LLMConfig:
    """Partial-update the persistent config file and return the new config."""
    LLM_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    current = load_config()
    if model is not None:
        current.model = model
    if api_url is not None:
        current.api_url = api_url
    if api_key is not None:
        current.api_key = api_key
    if temperature is not None:
        current.temperature = temperature
    if max_tokens is not None:
        current.max_tokens = max_tokens

    LLM_CONFIG_PATH.write_text(
        json.dumps(asdict(current), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # Restrict permissions — file contains API key
    try:
        LLM_CONFIG_PATH.chmod(0o600)
    except OSError:
        pass
    return current


# ── Per-agent model ──────────────────────────────────────────────────────────

def get_agent_model(agents: dict, agent_id: str) -> str:
    """Return the model for *agent_id*, falling back to the default config."""
    agent_info = agents.get(agent_id, {})
    agent_model = agent_info.get("model", "")
    if agent_model:
        return agent_model
    return load_config().model


def redact_key(key: str) -> str:
    """Mask an API key for display: show first 4 and last 4 chars."""
    if not key or len(key) <= 12:
        return "***"
    return f"{key[:4]}...{key[-4:]}"