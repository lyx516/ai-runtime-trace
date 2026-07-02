"""Domain schemas and dataclasses for the Hermes Flow FSM."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ── Enums & Constants ──────────────────────────────────────────────────────

class RunStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ESCALATED = "escalated"


class MemoryMode(str, Enum):
    RUN_ISOLATED = "run_isolated"
    LONG_TERM = "long_term"


class DeliveryOutcome(str, Enum):
    DELIVERED = "delivered"
    REJECTED = "rejected"


class DecisionValue(str, Enum):
    APPROVE = "APPROVE"
    PASS = "PASS"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    ACK = "ACK"


class GateType(str, Enum):
    DECISION = "decision"
    ACKNOWLEDGEMENT = "acknowledgement"
    ARTIFACT_MARKER = "artifact-marker"
    HUMAN_APPROVAL = "human-approval"
    UNCONDITIONAL = "unconditional"


class MessageKind(str, Enum):
    PROPOSAL = "proposal"
    QUESTION = "question"
    REVIEW = "review"
    DECISION = "decision"
    STATUS = "status"
    ERROR = "error"
    AUDIT = "audit"


class Visibility(str, Enum):
    TARGETED = "targeted"
    GROUP = "group"
    ORCHESTRATOR = "orchestrator"
    HUMAN = "human"
    ALL = "all"


# Idle budget sentinel
IDLE_BUDGET_UNLIMITED = -1


# ── Helpers ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _to_dict(obj: Any) -> dict[str, Any]:
    """Recursively convert a dataclass/enum instance to a plain dict."""
    def _convert(v: Any) -> Any:
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, list):
            return [_convert(x) for x in v]
        if isinstance(v, dict):
            return {k: _convert(v) for k, v in v.items()}
        if hasattr(v, "__dataclass_fields__"):
            return {k: _convert(getattr(v, k)) for k in v.__dataclass_fields__}
        return v
    return _convert(obj)


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    """Reconstruct a dataclass from a plain dict, coercing string values to enums."""
    if not hasattr(cls, "__dataclass_fields__"):
        return data
    field_types = {}
    for fname, fdef in cls.__dataclass_fields__.items():
        field_types[fname] = fdef.type
    kwargs = {}
    for fname, ftype in field_types.items():
        if fname not in data:
            continue
        raw = data[fname]
        # Handle Optional[X]
        origin = getattr(ftype, "__origin__", None)
        args = getattr(ftype, "__args__", ())
        if origin is type(Optional[str]) or origin is type(Optional[None]) or origin is None:
            # plain type or Union
            pass

        # Try enum coerce
        if isinstance(ftype, type) and issubclass(ftype, Enum):
            kwargs[fname] = ftype(raw)
        elif isinstance(raw, list) and args:
            item_type = args[0] if args else None
            if item_type and isinstance(item_type, type) and issubclass(item_type, Enum):
                kwargs[fname] = [item_type(x) for x in raw]
            else:
                kwargs[fname] = raw
        elif isinstance(raw, dict) and args:
            # dict[str, int] etc.
            kwargs[fname] = raw
        else:
            kwargs[fname] = raw
    return cls(**kwargs)


# ── Domain Dataclasses ──────────────────────────────────────────────────────

@dataclass
class Gate:
    gate_id: str = ""
    type: GateType = GateType.DECISION
    required_roles: list[str] = field(default_factory=list)
    pass_values: list[str] = field(default_factory=lambda: ["APPROVE", "PASS"])
    fail_values: list[str] = field(default_factory=lambda: ["REQUEST_CHANGES", "FAIL"])
    blocked_values: list[str] = field(default_factory=lambda: ["BLOCKED"])
    on_pass: str = ""
    on_fail: str = ""
    on_blocked: str = ""
    on_exhausted: str = ""
    max_rounds: int = 0


@dataclass
class Transition:
    target_state_id: str = ""
    condition: str = "on_complete"  # gate result label


@dataclass
class State:
    state_id: str = ""
    description: str = ""
    actors: list[str] = field(default_factory=list)
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    message_acceptance: bool = True
    gate: Optional[Gate] = None
    transitions: list[Transition] = field(default_factory=list)
    max_rounds: int = 0
    on_exhausted: str = ""
    idle_timeout_seconds: Optional[int] = None  # None = no timeout
    terminal: bool = False
    human: bool = False


@dataclass
class AgentRole:
    role_id: str = ""
    display_name: str = ""
    soul: str = ""
    profile_name: str = ""
    skills: list[str] = field(default_factory=list)
    toolsets: list[str] = field(default_factory=list)
    read_scope: list[str] = field(default_factory=list)
    write_scope: list[str] = field(default_factory=list)
    workspace_mode: str = "isolated"
    memory_mode: MemoryMode = MemoryMode.RUN_ISOLATED
    max_action_seconds: Optional[int] = None


@dataclass
class FlowDefinition:
    flow_id: str = ""
    name: str = ""
    version: str = "1"
    agents: dict[str, AgentRole] = field(default_factory=dict)
    states: dict[str, State] = field(default_factory=dict)
    initial_state_id: str = ""
    terminal_state_ids: list[str] = field(default_factory=list)
    routing_policies: dict[str, Any] = field(default_factory=dict)
    loop_defaults: dict[str, Any] = field(default_factory=lambda: {"max_rounds": 3, "idle_timeout": None})


@dataclass
class AgentBinding:
    role_id: str = ""
    profile_name: str = ""
    session_id: str = ""
    memory_mode: MemoryMode = MemoryMode.RUN_ISOLATED


@dataclass
class FlowRun:
    run_id: str = ""
    flow_id: str = ""
    flow_version: str = "1"
    status: RunStatus = RunStatus.ACTIVE
    current_state_id: str = ""
    round_counters: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None
    agent_bindings: list[AgentBinding] = field(default_factory=list)
    memory_modes: dict[str, str] = field(default_factory=dict)
    artifact_root: str = ""


@dataclass
class MessageEnvelope:
    message_id: str = ""
    run_id: str = ""
    state_id: str = ""
    from_role: str = ""
    intended_recipients: list[str] = field(default_factory=list)
    authorized_recipients: list[str] = field(default_factory=list)
    recipient_availability: dict[str, bool] = field(default_factory=dict)
    visibility: str = "targeted"
    kind: str = "proposal"
    content: str = ""
    artifacts: list[str] = field(default_factory=list)
    requires_ack: bool = False
    delivery_outcome: DeliveryOutcome = DeliveryOutcome.DELIVERED
    rejection_reason: str = ""
    created_at: str = ""


@dataclass
class Inbox:
    run_id: str = ""
    role_id: str = ""
    state_id: str = ""
    message_ids: list[str] = field(default_factory=list)
    generated_at: str = ""


@dataclass
class Artifact:
    artifact_id: str = ""
    run_id: str = ""
    state_id: str = ""
    produced_by_role: str = ""
    path: str = ""
    artifact_type: str = ""
    visibility_scope: str = "run"
    created_at: str = ""


@dataclass
class Decision:
    decision_id: str = ""
    run_id: str = ""
    state_id: str = ""
    role_id: str = ""
    value: str = ""
    reason: str = ""
    artifacts: list[str] = field(default_factory=list)
    created_at: str = ""


@dataclass
class GateStatus:
    state_id: str = ""
    satisfied: bool = False
    required_roles: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    next_state_if_ready: str = ""
    blocked_reason: str = ""


@dataclass
class FlowStatus:
    run_id: str = ""
    status: RunStatus = RunStatus.ACTIVE
    current_state_id: str = ""
    pending_gate: Optional[GateStatus] = None
    round_counters: dict[str, int] = field(default_factory=dict)
    memory_modes: dict[str, str] = field(default_factory=dict)
    recent_messages: list[MessageEnvelope] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


@dataclass
class FlowInitResult:
    ok: bool = False
    run_id: str = ""
    current_state_id: str = ""
    agents: list[AgentBinding] = field(default_factory=list)
    artifact_root: str = ""
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    run_id: str = ""
    previous_state_id: str = ""
    current_state_id: str = ""
    actions_taken: list[str] = field(default_factory=list)
    status: Optional[FlowStatus] = None


# ── Public serialization API ───────────────────────────────────────────────

def to_dict(obj: Any) -> dict[str, Any]:
    """Serialize a dataclass/enum instance to a JSON-compatible dict."""
    return _to_dict(obj)


def from_dict(cls: type, data: dict[str, Any]) -> Any:
    """Deserialize a dict into a dataclass instance, with enum coercion."""
    return _from_dict(cls, data)
