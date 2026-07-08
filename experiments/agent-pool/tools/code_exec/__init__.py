SCHEMA = {
  "name": "code_exec",
  "description": "Execute a Python script in an isolated environment. The script can use the Python standard library. Use for data processing, computation, or file manipulation.",
  "parameters": {
    "type": "object",
    "properties": {
      "code": {
        "type": "string",
        "description": "Python code to execute."
      }
    },
    "required": [
      "code"
    ]
  }
}

"""Code execution tool — runs Python in a sandboxed subprocess.

Sandbox:
- cwd forced to workspace root
- HOME set to workspace root
- SENSITIVE env vars stripped (*_API_KEY, *_TOKEN, *_SECRET, etc.)
- PYTHONDONTWRITEBYTECODE=1 (no .pyc pollution)
- PATH sanitized
- Temp file auto-deleted after execution
"""

import os
import subprocess
import tempfile

# Env var substrings that indicate secrets — stripped from child env
_SECRET_SUBSTRINGS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL", "DSN")
_SAFE_PREFIXES = ("PATH", "HOME", "USER", "LANG", "LC_", "TERM", "SHELL", "LOGNAME",
                  "TMPDIR", "TMP", "TEMP", "XDG_", "PYTHONPATH", "VIRTUAL_ENV",
                  "HERMES_WORKSPACE", "HERMES_WRITE", "HERMES_READ", "HERMES_FLOW")


def _scrub_env(raw: dict) -> dict:
    clean = {}
    for k, v in raw.items():
        if any(s in k.upper() for s in _SECRET_SUBSTRINGS):
            continue
        if not any(k.startswith(p) for p in _SAFE_PREFIXES):
            continue
        clean[k] = v
    return clean


def run(args: dict) -> dict:
    code = args.get("code", "")
    timeout = min(args.get("timeout", 15), 60)

    if not code:
        return {
            "ok": False,
            "error": "code_exec: 'code' argument is required and must not be empty. "
                     "Provide the Python code to execute. Do not retry with empty code.",
        }

    # ── Code blacklist ──
    from tools._security import check_code_blocked
    blocked = check_code_blocked(code)
    if blocked:
        return {"ok": False, "error": f"code_exec: {blocked}"}

    from tools._scope import get_workspace_root

    ws_root = str(get_workspace_root())

    env = _scrub_env(os.environ)
    env["HOME"] = ws_root
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    # Inject scope env vars so scope-aware code inside code_exec respects boundaries
    env["HERMES_WORKSPACE_ROOT"] = ws_root
    env["HERMES_WRITE_SCOPE"] = os.environ.get("HERMES_WRITE_SCOPE", "")
    env["HERMES_READ_SCOPE"] = os.environ.get("HERMES_READ_SCOPE", "")

    tmp = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp = f.name
        result = subprocess.run(
            ["python3", tmp],
            capture_output=True, text=True, timeout=timeout,
            cwd=ws_root, env=env,
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
