"""LLM configuration — default model, API URL, API key.

Resolution priority (high → low):
  1. CLI runtime overrides (--model, --api-url, --api-key) — session only
  2. JSON config file (~/.hermes-flow/llm_config.json) — persistent
  3. Hermes config (~/.hermes/config.yaml), including named providers
  4. Environment variables (DEEPSEEK_API_KEY / OPENAI_API_KEY) — backward compat
  5. Hardcoded defaults (deepseek-v4-flash @ api.deepseek.com)

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
_HERMES_CONFIG_PATH = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "config.yaml"


@dataclass
class LLMConfig:
    """Resolved LLM configuration."""
    model: str = _DEFAULT_MODEL
    api_url: str = _DEFAULT_API_URL
    api_key: str = ""
    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS


# ── Load / save ──────────────────────────────────────────────────────────────

def _chat_completions_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL to its chat completions URL."""
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _load_hermes_config() -> LLMConfig | None:
    """Resolve a directly callable OpenAI-compatible Hermes provider.

    Hermes itself can use OAuth-backed providers, but this standalone runtime
    cannot safely reuse those credentials. Prefer the configured active provider
    when it has a base URL and API key; otherwise use the explicitly configured
    ``siliconflow`` provider, then another complete named provider.
    """
    try:
        import yaml

        raw = yaml.safe_load(_HERMES_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except (ImportError, OSError, ValueError):
        return None

    model_raw = raw.get("model")
    providers_raw = raw.get("providers")
    model_cfg: dict[str, Any] = dict(model_raw) if isinstance(model_raw, dict) else {}
    providers: dict[str, Any] = dict(providers_raw) if isinstance(providers_raw, dict) else {}
    active_provider = str(model_cfg.get("provider") or "")

    candidates: list[dict[str, Any]] = []
    active_entry = providers.get(active_provider)
    if isinstance(active_entry, dict):
        candidates.append({**active_entry, **{k: v for k, v in model_cfg.items() if v}})
    else:
        candidates.append(model_cfg)

    if active_provider != "siliconflow" and isinstance(providers.get("siliconflow"), dict):
        candidates.append(providers["siliconflow"])
    candidates.extend(
        entry for name, entry in providers.items()
        if name not in {active_provider, "siliconflow"} and isinstance(entry, dict)
    )

    for entry in candidates:
        base_url = str(entry.get("base_url") or "").strip()
        api_key = str(entry.get("api_key") or "").strip()
        if base_url and api_key:
            return LLMConfig(
                model=str(entry.get("model") or model_cfg.get("default") or _DEFAULT_MODEL),
                api_url=_chat_completions_url(base_url),
                api_key=api_key,
                temperature=float(entry.get("temperature") or _DEFAULT_TEMPERATURE),
                max_tokens=int(entry.get("max_tokens") or _DEFAULT_MAX_TOKENS),
            )
    return None

def load_config() -> LLMConfig:
    """Load merged config: Hermes → JSON → env vars → CLI overrides.

    Priority (high → low):
      1. CLI runtime override env vars (HERMES_LLM_MODEL / HERMES_LLM_API_URL / HERMES_LLM_API_KEY)
      2. JSON config file (~/.hermes-flow/llm_config.json)
      3. Hermes config provider resolution
      4. Legacy env vars (DEEPSEEK_API_KEY / OPENAI_API_KEY)
      5. Hardcoded defaults
    """
    cfg = _load_hermes_config() or LLMConfig()

    # 1. JSON config file (persistent)
    if LLM_CONFIG_PATH.exists():
        try:
            data = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.model = data.get("model") or cfg.model
            cfg.api_url = data.get("api_url") or cfg.api_url
            cfg.api_key = data.get("api_key") or cfg.api_key
            cfg.temperature = data.get("temperature") or cfg.temperature
            cfg.max_tokens = data.get("max_tokens") or cfg.max_tokens
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