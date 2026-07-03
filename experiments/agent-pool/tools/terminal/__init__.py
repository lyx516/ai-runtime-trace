"""终端命令执行工具"""
import subprocess
import shlex

def run(args: dict) -> dict:
    command = args.get("command", "")
    timeout = args.get("timeout", 30)
    workdir = args.get("workdir", None)
    if not command:
        return {"ok": False, "error": "command required"}
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
        return {"ok": False, "error": f"timeout ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
