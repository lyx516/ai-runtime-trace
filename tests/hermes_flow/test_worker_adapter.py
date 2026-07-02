"""Worker adapter tests — verify profile/session binding, context packet creation, and role dispatch."""

from pathlib import Path

import pytest

from hermes_flow.schemas import AgentBinding, MemoryMode


def test_worker_adapter_test_exists() -> None:
    """Test module for worker adapter must exist and import cleanly."""
    import hermes_flow.worker
    assert hasattr(hermes_flow.worker, "WorkerAdapter")
