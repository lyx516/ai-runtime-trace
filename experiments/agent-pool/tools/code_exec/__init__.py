"""代码执行工具 — 在独立子进程中运行 Python 代码。

安全约束:
- 临时文件写入后立即执行、执行后删除
- 超时默认 15s，最长 60s
- 空代码块立即拒绝
- 返回值截断: stdout 3000 chars, stderr 1000 chars
"""

import subprocess
import tempfile
import os


def run(args: dict) -> dict:
    code = args.get("code", "")
    timeout = min(args.get("timeout", 15), 60)

    if not code:
        return {
            "ok": False,
            "error": "code_exec: 'code' argument is required and must not be empty. "
                     "Provide the Python code to execute. Do not retry with empty code.",
        }

    try:
        tmp = ""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp = f.name
        result = subprocess.run(
            ["python3", tmp],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        os.unlink(tmp)
        return {
            "ok": True if result.returncode == 0 else False,
            "stdout": result.stdout[-3000:],
            "stderr": result.stderr[-1000:],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return {
            "ok": False,
            "error": f"code_exec: timeout after {timeout}s. "
                     "The code took too long. Consider simplifying it or increasing the timeout.",
        }
    except PermissionError as e:
        return {"ok": False, "error": f"code_exec: permission denied — {e}"}
    except Exception as e:
        return {"ok": False, "error": f"code_exec: unexpected error — {e}"}
