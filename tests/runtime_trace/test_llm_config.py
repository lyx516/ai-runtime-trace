"""Regression tests for agent-pool LLM provider resolution."""

import sys
from pathlib import Path

import pytest


_AGENT_POOL_DIR = Path(__file__).resolve().parents[2] / "experiments" / "agent-pool"
if str(_AGENT_POOL_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_POOL_DIR))

from engine import llm_config


def _write_runtime_trace_config(path: Path, siliconflow_model: str | None = None) -> None:
    model_line = f"\n    model: {siliconflow_model}" if siliconflow_model else ""
    path.write_text(
        f"""model:
  provider: openai-codex
  default: gpt-5.6-terra
providers:
  openai-codex:
    oauth: true
  siliconflow:
    base_url: https://api.siliconflow.cn/v1
    api_key: test-key{model_line}
""",
        encoding="utf-8",
    )


def test_fallback_provider_requires_its_own_model(tmp_path, monkeypatch):
    """An API-key fallback must not inherit an OAuth provider's model name."""
    config_path = tmp_path / "config.yaml"
    _write_runtime_trace_config(config_path)
    monkeypatch.setattr(llm_config, "_RUNTIME_TRACE_CONFIG_PATH", config_path)
    monkeypatch.setattr(llm_config, "LLM_CONFIG_PATH", tmp_path / "missing.json")

    with pytest.raises(llm_config.ProviderConfigError, match="providers\\.siliconflow\\.model"):
        llm_config.load_config()


def test_fallback_provider_uses_its_configured_model(tmp_path, monkeypatch):
    """A configured fallback keeps its provider-specific endpoint and model."""
    config_path = tmp_path / "config.yaml"
    _write_runtime_trace_config(config_path, "deepseek-ai/DeepSeek-V4-Flash")
    monkeypatch.setattr(llm_config, "_RUNTIME_TRACE_CONFIG_PATH", config_path)
    monkeypatch.setattr(llm_config, "LLM_CONFIG_PATH", tmp_path / "missing.json")

    resolved = llm_config.load_config()

    assert resolved.model == "deepseek-ai/DeepSeek-V4-Flash"
    assert resolved.api_url == "https://api.siliconflow.cn/v1/chat/completions"
