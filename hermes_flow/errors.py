"""Typed exception classes for the Hermes Flow FSM."""

from typing import Optional


class FlowError(Exception):
    """Base exception for all Hermes Flow errors."""

    def __init__(self, message: str, details: Optional[list[str]] = None):
        self.message = message
        self.details = details or []
        super().__init__(message)


class FlowValidationError(FlowError):
    """Raised when a flow definition fails validation."""


class RuntimeStateError(FlowError):
    """Raised when a runtime operation is invalid for the current state."""


class RoutingError(FlowError):
    """Raised when message routing fails (invalid recipients, unavailable nodes)."""


class GateEvaluationError(FlowError):
    """Raised when a gate evaluation encounters an unexpected condition."""


class ContextPolicyError(FlowError):
    """Raised when an agent attempts to read/write outside its permitted scope."""


class WorkerExecutionError(FlowError):
    """Raised when a Hermes worker session/profile execution fails."""
