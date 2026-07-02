#!/usr/bin/env python3
"""Verify that flow-tools.openapi.yaml parses as valid YAML."""

import sys
import yaml

CONTRACT_PATH = "specs/001-hermes-flow-fsm/contracts/flow-tools.openapi.yaml"

def main() -> int:
    try:
        with open(CONTRACT_PATH) as f:
            doc = yaml.safe_load(f)
        info = doc.get("info", {})
        print(f"OK — loaded '{info.get('title', '?')}' v{info.get('version', '?')}")
        ops = []
        for path, methods in doc.get("paths", {}).items():
            for method, op in methods.items():
                ops.append(op.get("operationId", f"{method} {path}"))
        print(f"  {len(ops)} operations: {', '.join(ops)}")
        return 0
    except Exception as e:
        print(f"FAIL — {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
