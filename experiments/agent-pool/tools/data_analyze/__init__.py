"""数据分析工具 — 使用 pandas 直接分析数据"""
import subprocess
import tempfile
import os
import json

def run(args: dict) -> dict:
    code = args.get("code", "")
    data = args.get("data", "")

    if not code and not data:
        return {"ok": False, "error": "code or data required"}

    full_code = "import pandas as pd\nimport numpy as np\nimport json\n"
    if data:
        full_code += f"data = {json.dumps(data)}\n"
    full_code += code
    if not full_code.strip().endswith("print"):
        full_code += "\nimport json; print('__RESULT__:' + json.dumps(locals().get('result', 'done')))"

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(full_code)
            tmp = f.name
        result = subprocess.run(
            ["python3", tmp],
            capture_output=True, text=True, timeout=args.get("timeout", 30),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        os.unlink(tmp)
        output = result.stdout
        stderr = result.stderr[-500:]
        # Extract structured result
        if "__RESULT__:" in output:
            parts = output.split("__RESULT__:")
            result_json = parts[1].strip()
            stdout = parts[0].strip() if parts[0].strip() else ""
        else:
            result_json = "none"
            stdout = output.strip()

        return {
            "ok": result.returncode == 0,
            "stdout": stdout[:2000],
            "result": result_json[:500],
            "stderr": stderr if stderr else "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
