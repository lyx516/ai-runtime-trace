"""Hook bus — 轻量事件总线，agent session loop 的唯一副作用出口。

Agent loop 不直接触碰 RuntimeStore。所有持久化、观测、checkpoint
都通过 emit(hook_name, payload) 触发。Handler 通过 subscribe() 注册。

设计原则：
- Agent loop 只管 emit，不管谁在听
- 所有持久化逻辑集中在 handler 中
- 测试时可替换 handler（NoOpHandler）
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Hook 名称常量 ──────────────────────────────────────────────────────────

class Hook:
    SESSION_INIT   = "session.init"     # payload: AgentSessionState
    TURN_START     = "turn.start"       # payload: {turn, state_id, role_id}
    LLM_DONE       = "llm.done"         # payload: {turn, duration_ms, tool_calls_count}
    TOOL_DONE      = "tool.done"        # payload: {fn_name, ok, state_id, role_id}
    TURN_END       = "turn.end"         # payload: AgentSessionState  ← checkpoint point
    SESSION_DECIDE = "session.decide"   # payload: {value, reason, tool_calls}
    SESSION_DONE   = "session.done"     # payload: {value, reason, tool_calls}

    # For run_flow level
    STATE_ENTER    = "state.enter"      # payload: {run_id, state_id, round}
    STATE_EXIT     = "state.exit"       # payload: {run_id, state_id, next_state}


# ── Bus ─────────────────────────────────────────────────────────────────────

HookHandler = Callable[[str, dict[str, Any]], None]


class HookBus:
    """事件总线：subscribe / emit。

    单例模式：模块级 _bus 实例，各 handler 在启动时注册。
    """

    def __init__(self):
        self._handlers: dict[str, list[HookHandler]] = {}

    def subscribe(self, hook: str, handler: HookHandler) -> None:
        """注册 handler 到指定 hook。"""
        self._handlers.setdefault(hook, []).append(handler)

    def emit(self, hook: str, payload: dict[str, Any]) -> None:
        """触发 hook — 同步调用所有已注册 handler。

        单个 handler 异常不中断其他 handler。
        """
        for h in self._handlers.get(hook, []):
            try:
                h(hook, payload)
            except Exception:
                logger.warning("Hook handler failed for %s", hook, exc_info=True)

    def clear(self) -> None:
        """清空所有 handler（测试用）。"""
        self._handlers.clear()


# ── 模块级单例 ─────────────────────────────────────────────────────────────

_bus = HookBus()


def subscribe(hook: str, handler: HookHandler) -> None:
    """注册全局 hook handler。"""
    _bus.subscribe(hook, handler)


def emit(hook: str, payload: dict[str, Any]) -> None:
    """触发全局 hook。"""
    _bus.emit(hook, payload)


def get_bus() -> HookBus:
    """获取全局 bus（测试用）。"""
    return _bus


def reset_bus() -> None:
    """重置全局 bus（测试用）。"""
    _bus.clear()
