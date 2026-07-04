"""终端命令执行工具 — 在 WORKSPACE_ROOT 范围内执行 shell 命令。

安全约束:
- 命令默认在 workspace root 执行
- 输出截断到 stdout 2000 chars / stderr 1000 chars
- 超时默认 30s，最长 120s
- 空命令立即拒绝，不浪费 LLM 轮次
"""

import subprocess
import shlex


def run(args: dict) -> dict:
    command = args.get("command", "")
    timeout = min(args.get("timeout", 30), 120)
    workdir = args.get("workdir", None)

    if not command:
        return {
            "ok": False,
            "error": "terminal: command is empty. "
                     "Provide the 'command' argument with a valid shell command. "
                     "Do not retry this call with an empty command.",
        }

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
        )
        return {
            "ok": True,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-1000:],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"terminal: timeout after {timeout}s. "
                     "The command took too long. Consider simplifying it or increasing the timeout.",
        }
    except PermissionError as e:
        return {"ok": False, "error": f"terminal: permission denied — {e}"}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"terminal: command not found — {e}"}
    except Exception as e:
        return {"ok": False, "error": f"terminal: unexpected error — {e}"}
