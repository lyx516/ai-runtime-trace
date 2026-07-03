"""
human_clarifier — 人类澄清工具。

对其他 agent 而言是完全无感的工具调用，和 terminal、web_search 没有区别。
唯一的区别是：全局共享 3 次调用上限。用完后自动返回 fallback。

调用方式（LLM 返回 JSON）:
  {"tool": "human_clarifier", "tool_args": {"question": "您的缓存系统读写比例是多少？"}}

返回值:
  {"ok": true, "answer": "用户输入的回答", "remaining": 2}
  或用尽时: {"ok": true, "answer": "[clarify quota exhausted]", "remaining": 0}
"""

import sys
import threading

# 全局共享计数器 — 所有 agent 共用 3 次
_CLARIFY_LOCK = threading.Lock()
_CLARIFY_REMAINING = 3
_MAX_CLARIFIES = 3


def run(args: dict) -> dict:
    """Execute human clarifier tool. Called by tools_runner."""
    global _CLARIFY_REMAINING

    question = args.get("question", "请提供更多上下文信息。")
    caller = args.get("_caller", "AI")

    with _CLARIFY_LOCK:
        remaining = _CLARIFY_REMAINING

    if remaining <= 0:
        return {
            "ok": True,
            "answer": "[clarify quota exhausted]",
            "remaining": 0,
            "note": "人类澄清配额已用尽，请基于现有信息自行决策。",
        }

    with _CLARIFY_LOCK:
        _CLARIFY_REMAINING -= 1
        remaining = _CLARIFY_REMAINING

    print(f"\n{'='*60}")
    print(f"👤 需要人类澄清（剩余 {remaining}/{_MAX_CLARIFIES} 次）")
    print(f"{'='*60}")
    print(f"来自 [{caller}] 的问题:")
    print(f"📋 {question}")
    print(f"{'='*60}")
    print(f"请输入回答（输入 .done 结束多行，或直接回车跳过）:")

    lines = []
    while True:
        try:
            line = input()
            if line.strip() == ".done":
                break
            if not line.strip() and not lines:
                # Single empty line = skip
                break
            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            break

    answer = "\n".join(lines).strip() if lines else "（人类未提供回答）"
    print(f"✅ 已记录（剩余 {remaining}/{_MAX_CLARIFIES} 次）\n")

    return {
        "ok": True,
        "answer": answer,
        "remaining": remaining,
        "caller": caller,
    }


def reset_counter():
    """Reset counter (for testing)."""
    global _CLARIFY_REMAINING
    with _CLARIFY_LOCK:
        _CLARIFY_REMAINING = _MAX_CLARIFIES
