"""Shared security checks for terminal and code_exec tools."""

import re

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
    (re.compile(r"\bgit\s+push\b.*(--force(?!-)|\s-f\b)", re.IGNORECASE), "git push --force/-f is blocked"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE), "git reset --hard is blocked"),
    (re.compile(r":\(\)\s*\{", re.IGNORECASE), "fork bomb is blocked"),
    (re.compile(r"\bcurl\b.*\|\s*sh", re.IGNORECASE), "curl | sh is blocked"),
    (re.compile(r"\bwget\b.*\|\s*sh", re.IGNORECASE), "wget | sh is blocked"),
]

# ── Python code banned patterns ────────────────────────────────────────────
# These prevent code_exec from bypassing terminal blacklist via os.system().
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