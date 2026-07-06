"""LLM client — single point of LLM API calls.

Both ``call_llm`` (plain JSON) and ``call_llm_tools`` (function-calling) read
their API URL, key, and default model from :mod:`engine.llm_config`.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from typing import Any, Optional

from engine.llm_config import load_config


def call_llm(
    system: str,
    prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1000,
) -> dict:
    """Call LLM API, return parsed JSON response."""
    cfg = load_config()
    api_key = cfg.api_key
    api_url = cfg.api_url
    effective_model = model or cfg.model

    if not api_key:
        print("❌ 未配置 API key。使用 debate --set-key <key> 或设置 DEEPSEEK_API_KEY 环境变量", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({
        "model": effective_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    resp = urllib.request.urlopen(req, timeout=60)
    content = json.loads(resp.read())["choices"][0]["message"]["content"].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to find {...} block (handles multi-line and nested objects)
        brace_depth = 0
        start = -1
        for i, ch in enumerate(content):
            if ch == '{':
                if start == -1:
                    start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and start != -1:
                    try:
                        return json.loads(content[start:i+1])
                    except json.JSONDecodeError:
                        pass
                    start = -1
        # Last resort — return raw content for caller to handle
        return {"raw_content": content}


def call_llm_tools(
    system: str,
    messages: list[dict],
    tools: list[dict],
    model: Optional[str] = None,
) -> dict:
    """Call LLM with OpenAI function-calling tools format.

    Returns: {"content": str, "tool_calls": [{"id": str, "function": {"name": ..., "arguments": ...}}]}
    """
    cfg = load_config()
    api_key = cfg.api_key
    api_url = cfg.api_url
    effective_model = model or cfg.model

    if not api_key:
        return {"content": "{}", "tool_calls": []}

    # Count token budget roughly
    system_len = len(system)
    msgs_len = sum(len(str(m)) for m in messages)
    tools_str = json.dumps(tools, ensure_ascii=False)
    total_chars = system_len + msgs_len + len(tools_str)

    body = {
        "model": effective_model,
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": cfg.temperature,
        "max_tokens": max(300, min(cfg.max_tokens, 32000 - total_chars // 4)),
    }

    # Only send tools if we have any
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    body_bytes = json.dumps(body, ensure_ascii=False).encode()

    req = urllib.request.Request(
        api_url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    # ── Retry loop for transient network errors ──
    _max_retries = 2
    _last_err = None
    for _attempt in range(_max_retries + 1):
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            result = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"LLM API {e.code}: {err_body}") from e
        except (IOError, ConnectionError, urllib.error.URLError) as e:
            _last_err = e
            if _attempt < _max_retries:
                _delay = [2, 5][_attempt]
                print(f"     ⚠️ LLM retry {_attempt+1}/{_max_retries}: {type(e).__name__} — waiting {_delay}s")
                time.sleep(_delay)
                # Rebuild request — urlopen consumed the previous one
                req = urllib.request.Request(
                    api_url,
                    data=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                )
                continue
            raise
    else:
        raise _last_err or RuntimeError("LLM call failed after retries")

    choice = result["choices"][0]["message"]
    text_content = choice.get("content", "") or ""
    raw_tool_calls = choice.get("tool_calls", [])

    tool_calls = []
    for tc in raw_tool_calls:
        tool_calls.append({
            "id": tc.get("id", ""),
            "type": "function",
            "function": {
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
            },
        })

    return {"content": text_content, "tool_calls": tool_calls}