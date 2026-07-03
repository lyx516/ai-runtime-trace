"""网络搜索工具 — 使用 curl 搜索网络"""
import subprocess
import json
import urllib.parse

def run(args: dict) -> dict:
    query = args.get("query", "")
    if not query:
        return {"ok": False, "error": "query required"}

    # Use DuckDuckGo lite for simple searches
    encoded = urllib.parse.quote(query)
    try:
        result = subprocess.run(
            ["curl", "-s", "-L", f"https://lite.duckduckgo.com/lite/?q={encoded}"],
            capture_output=True, text=True, timeout=15,
        )
        # Extract text from HTML roughly
        html = result.stdout
        import re
        # Remove tags
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        # Find result snippets
        snippets = text.split("Next")[0] if "Next" in text else text[:2000]
        return {"ok": True, "results": snippets[:2000]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
