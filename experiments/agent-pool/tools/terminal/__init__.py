"""Terminal command execution — sandboxed to WORKSPACE_ROOT + write_scope.

All commands run with:
- workdir forced within write_scope
- HOME set to workspace root (so ~/ expands in-scope)
- SENSITIVE env vars stripped (*_API_KEY, *_TOKEN, *_SECRET, etc.)
- PATH sanitized to a minimal safe set
"""

import os
import subprocess
import shlex

# Env var substrings that indicate secrets — stripped from child env
_SECRET_SUBSTRINGS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL", "DSN")
# Safe prefixes kept in child env
_SAFE_PREFIXES = ("PATH", "HOME", "USER", "LANG", "LC_", "TERM", "SHELL", "LOGNAME",
                  "TMPDIR", "TMP", "TEMP", "XDG_", "PYTHONPATH", "VIRTUAL_ENV",
                  "HERMES_WORKSPACE", "HERMES_WRITE", "HERMES_READ", "HERMES_FLOW")


def _scrub_env(raw: dict) -> dict:
    """Return a copy of env with secrets stripped."""
    clean = {}
    for k, v in raw.items():
        if any(s in k.upper() for s in _SECRET_SUBSTRINGS):
            continue
        if not any(k.startswith(p) for p in _SAFE_PREFIXES):
            continue
        clean[k] = v
    return clean


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

    # ── Resolve and scope workdir ──
    from tools._scope import resolve_write_path, get_workspace_root

    try:
        if workdir:
            cwd = str(resolve_write_path(workdir))
        else:
            cwd = str(get_workspace_root())
    except PermissionError as e:
        return {
            "ok": False,
            "error": f"terminal: workdir is outside allowed scope — {e}",
        }

    # ── Build sandboxed environment ──
    # Auto-create workdir if it doesn't exist
    os.makedirs(cwd, exist_ok=True)

    env = _scrub_env(os.environ)
    env["HOME"] = str(get_workspace_root())
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env=env,
        )
        return {
            "ok": True,
            "stdout": result.stdout[-3000:],
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
