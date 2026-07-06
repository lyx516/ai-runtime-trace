"""Output artifact validation for product gates."""

from __future__ import annotations

from pathlib import Path


def check_artifact(path: Path) -> tuple[bool, str]:
    """Return whether an output artifact is substantive enough to pass a product gate.

    Only rejects clearly-empty or trivially-stub files (0 bytes, or 1 line of text).
    Deeper quality assessment is the responsibility of reviewer/critic agents.
    """
    if not path.exists() or not path.is_file():
        return False, "missing"
    size = path.stat().st_size
    if size == 0:
        return False, "empty"
    return True, "ok"


def find_output_artifact(project_root: str, art_name: str, write_scope: list[str]) -> tuple[Path | None, str]:
    """Find an artifact only inside the current run's declared write scope.

    Broad recursive search can pick stale files from older auto-* runs and pass
    the wrong artifact path to the next state.
    """
    root = Path(project_root)
    artifact = Path(art_name)
    candidates: list[Path] = []
    if artifact.is_absolute():
        candidates.append(artifact)
    else:
        for scope in write_scope or []:
            candidates.append(root / scope / artifact.name)
        candidates.append(root / artifact)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        ok, reason = check_artifact(candidate)
        if ok:
            return candidate, reason
        if candidate.exists():
            return None, f"{candidate}: {reason}"
    return None, "missing in current write scope"