"""Regression tests for typed OpenAI schemas of file tools."""

import importlib.util
from pathlib import Path


_TOOLS_DIR = Path(__file__).resolve().parents[2] / "experiments" / "agent-pool" / "tools"



def _parameters(tool_id: str) -> dict:
    path = _TOOLS_DIR / tool_id / "__init__.py"
    spec = importlib.util.spec_from_file_location(f"{tool_id}_schema_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCHEMA["parameters"]


def test_file_read_schema_declares_pagination_as_integers():
    properties = _parameters("file_read")["properties"]

    assert properties["offset"]["type"] == "integer"
    assert properties["limit"]["type"] == "integer"


def test_search_files_schema_declares_numeric_arguments_as_integers():
    properties = _parameters("search_files")["properties"]

    assert properties["limit"]["type"] == "integer"
    assert properties["offset"]["type"] == "integer"
    assert properties["context"]["type"] == "integer"
