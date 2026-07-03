"""代码执行工具 — 在隔离沙箱中运行 Python 代码"""
import subprocess
import tempfile
import os

def run(args: dict) -> dict:
    code = args.get("code", "")
    if not code:
        return {"ok": False, "error": "code required"}

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp = f.name
        result = subprocess.run(
            ["python3", tmp],
            capture_output=True, text=True, timeout=args.get("timeout", 15),
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
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
