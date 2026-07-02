"""Contract schema loading tests — verify flow-tools.openapi.yaml parses and has expected operations."""

from pathlib import Path

import pytest
import yaml

CONTRACT_PATH = Path(__file__).parents[2] / "specs" / "001-hermes-flow-fsm" / "contracts" / "flow-tools.openapi.yaml"
EXPECTED_OPERATIONS = [
    "flow_init",
    "flow_status",
    "flow_step",
    "flow_send",
    "flow_decide",
    "flow_pause",
    "flow_resume",
    "flow_abort",
]


@pytest.fixture(scope="module")
def contract() -> dict:
    assert CONTRACT_PATH.exists(), f"Contract not found at {CONTRACT_PATH}"
    with open(CONTRACT_PATH) as f:
        return yaml.safe_load(f)


def test_contract_parses_as_valid_yaml(contract: dict) -> None:
    """The contract file must be valid YAML with an info section."""
    assert "info" in contract
    assert contract["info"]["title"] == "Hermes Flow Tool Contracts"


def test_expected_operation_ids_exist(contract: dict) -> None:
    """Every expected operationId must be present in the paths."""
    found = set()
    for path, methods in contract.get("paths", {}).items():
        for method, op in methods.items():
            if "operationId" in op:
                found.add(op["operationId"])
    for op_id in EXPECTED_OPERATIONS:
        assert op_id in found, f"Missing operationId: {op_id}"


def test_flow_init_request(contract: dict) -> None:
    """flow_init must accept project_root and flow_path as required fields."""
    init_schema = _get_request_schema(contract, "flow_init")
    required = init_schema.get("required", [])
    assert "project_root" in required
    assert "flow_path" in required


def test_flow_decide_value_enum(contract: dict) -> None:
    """flow_decide value field must have the approved enum values."""
    decide_schema = _get_request_schema(contract, "flow_decide")
    value_prop = decide_schema["properties"]["value"]
    assert "enum" in value_prop
    approved = {"APPROVE", "PASS", "REQUEST_CHANGES", "FAIL", "BLOCKED", "ACK"}
    assert approved.issubset(set(value_prop["enum"]))


def test_flow_status_response_flowstatus(contract: dict) -> None:
    """flow_status must return a FlowStatus schema with required fields."""
    status_resp = contract["paths"]["/flow/status"]["post"]["responses"]["200"]
    schema_ref = status_resp["content"]["application/json"]["schema"]["$ref"]
    assert "#/components/schemas/FlowStatus" in schema_ref


def test_flow_send_schema_has_intended_recipients(contract: dict) -> None:
    """SendRequest must have intended_recipients as a required array."""
    send_schema = _get_request_schema(contract, "flow_send")
    required = send_schema.get("required", [])
    assert "intended_recipients" in required
    assert send_schema["properties"]["intended_recipients"]["type"] == "array"


def test_flow_status_pending_gate_nullable(contract: dict) -> None:
    """FlowStatus.pending_gate must allow null for terminal states."""
    flow_status = contract["components"]["schemas"]["FlowStatus"]
    required = flow_status.get("required", [])
    assert "pending_gate" not in required, "pending_gate should not be required (nullable for terminal states)"
    pg = flow_status["properties"]["pending_gate"]
    assert "anyOf" in pg or "oneOf" in pg or "nullable" in pg, (
        "pending_gate must be nullable or use anyOf with null type"
    )


def test_flow_init_dry_run_contract(contract: dict) -> None:
    """flow_init must support dry_run parameter that never creates runtime state."""
    init_schema = _get_request_schema(contract, "flow_init")
    props = init_schema.get("properties", {})
    assert "dry_run" in props
    assert props["dry_run"].get("default") is False


def test_flow_init_result_has_run_id(contract: dict) -> None:
    """FlowInitResult must include run_id, current_state_id, agents, artifact_root."""
    result = contract["components"]["schemas"]["FlowInitResult"]
    required = set(result.get("required", []))
    for field in ("run_id", "current_state_id", "agents", "artifact_root"):
        assert field in required, f"FlowInitResult missing required field: {field}"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_request_schema(contract: dict, operation_id: str) -> dict:
    for path, methods in contract.get("paths", {}).items():
        for method, op in methods.items():
            if op.get("operationId") == operation_id:
                schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                # Resolve top-level $ref
                ref = schema.get("$ref", "")
                if ref:
                    ref_path = ref.lstrip("#/").split("/")
                    for part in ref_path:
                        contract = contract.get(part, {})
                    return contract
                return schema
    raise AssertionError(f"Operation {operation_id} not found in contract")
