"""Full Hermes worker session/profile dispatch and resume adapter."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from hermes_flow.errors import WorkerExecutionError
from hermes_flow.schemas import AgentBinding


class WorkerAdapter:
    """Adapter for dispatching agent roles to full Hermes worker sessions.

    Uses an injectable command runner so tests can verify the adapter
    receives the correct profile/session identity and context packet path
    without launching a real external model.
    """

    def __init__(
        self,
        hermes_cli: str = "hermes",
        run_command: Callable[..., Any] | None = None,
    ):
        self.hermes_cli = hermes_cli
        self._run_command = run_command or subprocess.run

    def prepare_session_binding(self, binding: AgentBinding) -> dict[str, str]:
        """Return the profile/session identity for a role binding.

        Currently returns the binding data; actual profile creation
        will be implemented when Hermes profile CLI integration is wired.
        """
        return {
            "role_id": binding.role_id,
            "profile_name": binding.profile_name,
            "session_id": binding.session_id,
        }

    def write_context_packet(self, packet: dict[str, Any]) -> str:
        """Write the context packet to a temp file and return its path."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix=f"ctx_{packet.get('role_id', 'unknown')}_",
            delete=False,
        )
        json.dump(packet, tmp, indent=2, default=str)
        tmp_path = tmp.name
        tmp.close()
        return tmp_path

    def run_role_action(
        self,
        binding: AgentBinding,
        context_packet_path: str,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        """Dispatch the role to a full Hermes worker session.

        The canonical execution unit is a Hermes worker session/profile.
        The adapter invokes the hermes CLI with the role's profile and
        context packet, captures output, and returns structured results.

        Args:
            binding: Agent role binding with profile/session identity.
            context_packet_path: Path to the prepared JSON context packet.
            timeout_seconds: Max execution budget for one action.

        Returns:
            Dict with keys: ok, role_id, output, artifacts, execution_seconds.

        Raises:
            WorkerExecutionError: If the worker fails or times out.
        """
        cmd = [
            self.hermes_cli,
            "session",
            "--profile", binding.profile_name,
            "--context", context_packet_path,
        ]

        try:
            result = self._run_command(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise WorkerExecutionError(
                f"Worker timeout after {timeout_seconds}s for role '{binding.role_id}'",
            )
        except FileNotFoundError:
            raise WorkerExecutionError(
                f"Hermes CLI '{self.hermes_cli}' not found. Install Hermes Agent or use a mock runner in tests.",
            )

        if result.returncode != 0:
            raise WorkerExecutionError(
                f"Worker '{binding.role_id}' exited with code {result.returncode}",
                details=[result.stderr[:2000]] if result.stderr else [],
            )

        return {
            "ok": True,
            "role_id": binding.role_id,
            "output": result.stdout,
            "artifacts": [],
            "execution_seconds": timeout_seconds,
        }
