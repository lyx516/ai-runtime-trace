"""Shared security checks for terminal, code_exec, and file-system tools."""

import os
import re
from pathlib import Path

# ── Project root for path boundary enforcement ──────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # ai-runtime-trace/
_SANDBOX_ROOT: Path | None = None  # set by --self mode

# ── Allowed read roots — anything outside these is denied for file_read/search_files ──
_ALLOWED_READ_ROOTS: set[Path] = {
    _PROJECT_ROOT,
    Path("/usr/bin"),
    Path("/bin"),
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
}

# ── Protected directories — writes here trigger auto-backup before mutation ──
_PROTECTED_DIRS = {
    _PROJECT_ROOT / "hermes_flow",
    _PROJECT_ROOT / "experiments" / "agent-pool" / "engine",
    _PROJECT_ROOT / "experiments" / "agent-pool" / "tools",
}

def set_sandbox_root(path: Path | None) -> None:
    global _SANDBOX_ROOT
    _SANDBOX_ROOT = path

def get_sandbox_root() -> Path | None:
    return _SANDBOX_ROOT

# ── Shell command blacklist ────────────────────────────────────────────────
_BLOCKED_CMD_PATTERNS = [
    (re.compile(r"\brm\s+-rf\s+/(?:\s|$)", re.IGNORECASE), "rm -rf / is blocked"),
    (re.compile(r"\brm\s+-rf\s+~", re.IGNORECASE), "rm -rf ~ is blocked"),
    (re.compile(r"\brm\s+-rf\s+\*(?:\s|$)", re.IGNORECASE), "rm -rf * is blocked"),
    (re.compile(r"\brm\s+-rf\s+\.(?:\s|$)", re.IGNORECASE), "rm -rf . is blocked"),
    (re.compile(r"\bsudo\b", re.IGNORECASE), "sudo is blocked"),
    (re.compile(r"\bmkfs\b", re.IGNORECASE), "mkfs is blocked"),
    (re.compile(r"\bdd\b\s+if=", re.IGNORECASE), "dd is blocked"),
    (re.compile(r"\bchmod\s+(-R\s+)?777\b", re.IGNORECASE), "chmod 777 is blocked"),
    (re.compile(r"\bgit\s+push\b.*(--force(?!-)|-f\b)", re.IGNORECASE), "git push --force/-f is blocked"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE), "git reset --hard is blocked"),
    (re.compile(r":\(\)\s*\{", re.IGNORECASE), "fork bomb is blocked"),
    (re.compile(r"\bcurl\b.*\|\s*sh", re.IGNORECASE), "curl | sh is blocked"),
    (re.compile(r"\bwget\b.*\|\s*sh", re.IGNORECASE), "wget | sh is blocked"),
]

# ── Python code banned patterns ────────────────────────────────────────────
_BLOCKED_CODE_PATTERNS = [
    (re.compile(r"\bos\.system\s*\("), "os.system() is blocked in code_exec"),
    (re.compile(r"\bos\.popen\s*\("), "os.popen() is blocked in code_exec"),
    (re.compile(r"\bsubprocess\.\w+\s*\("), "subprocess is blocked in code_exec"),
    (re.compile(r"\b__import__\s*\("), "__import__() is blocked in code_exec"),
    (re.compile(r"\bshutil\.rmtree\s*\(\s*['\"]/", re.IGNORECASE), "shutil.rmtree('/') is blocked"),
    (re.compile(r"\bshutil\.rmtree\s*\(\s*['\"]~", re.IGNORECASE), "shutil.rmtree('~') is blocked"),
    (re.compile(r"\beval\s*\(\s*['\"]"), "eval() with string literal is blocked"),
    (re.compile(r"\bexec\s*\(\s*['\"]"), "exec() with string literal is blocked"),
]


def check_command_blocked(command: str) -> str | None:
    """Return error message if a shell command is blocked, None if safe."""
    for pattern, msg in _BLOCKED_CMD_PATTERNS:
        if pattern.search(command):
            return msg
    return None


def check_code_blocked(code: str) -> str | None:
    """Return error message if Python code contains blocked patterns, None if safe."""
    for pattern, msg in _BLOCKED_CODE_PATTERNS:
        if pattern.search(code):
            return msg
    return None


def check_read_allowed(path: str | Path) -> str | None:
    """Return error message if *path* is outside allowed read roots, None if safe."""
    resolved = Path(path).resolve()

    # Always allow reading anywhere under project root (agents need SOUL/SKILL, tools, etc.)
    if str(resolved).startswith(str(_PROJECT_ROOT)):
        return None

    # Allow reading system paths (for terminal introspection, tool discovery)
    for root in _ALLOWED_READ_ROOTS:
        if str(resolved).startswith(str(root)):
            return None
    return f"read denied: {path} is outside allowed read roots"


def check_write_sandboxed(path: str | Path) -> Path | None:
    """In sandbox mode, return redirected absolute path. Else return None (not in sandbox)."""
    if not _SANDBOX_ROOT:
        return None
    resolved = Path(path).resolve()
    if str(resolved).startswith(str(_PROJECT_ROOT)):
        relative = resolved.relative_to(_PROJECT_ROOT)
        return _SANDBOX_ROOT / relative
    return None  # outside project → deny


def check_write_backup(path: str | Path) -> Path | None:
    """Return absolute path if write needs pre-backup (in protected dir), else None."""
    if _SANDBOX_ROOT:
        return None  # sandbox handles safety separately
    resolved = Path(path).resolve()
    for protected in _PROTECTED_DIRS:
        if str(resolved).startswith(str(protected)):
            return resolved  # needs backup before write
    return None  # safe, no backup needed
