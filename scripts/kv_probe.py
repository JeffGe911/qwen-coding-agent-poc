"""Ollama context-size experiment. No repository code is included in requests."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_agent.client import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--model", default="qwen2.5-coder:1.5b")
    parser.add_argument("--output", type=Path, default=Path("evidence/kv-context.json"))
    args = parser.parse_args()
    client = Client(args.base_url, args.model)
    origin = client.base_url[:-3]
    def request(path, body=None):
        req = urllib.request.Request(origin + path, headers={"Content-Type": "application/json"}, data=None if body is None else json.dumps(body).encode())
        with client.opener.open(req, timeout=180) as response:
            return json.loads(response.read(262144))
    result = {"model": args.model, "model_details": request("/api/show", {"model": args.model}), "measurements": []}
    for context in (4096, 8192, 4096):
        response = request("/api/generate", {"model": args.model, "prompt": "Say READY", "stream": False, "options": {"num_ctx": context, "num_predict": 8, "temperature": 0}})
        result["measurements"].append({"requested_context": context, "loaded_models": request("/api/ps"), "timing": {key: value for key, value in response.items() if key.endswith("duration") or key.endswith("count")}})
    result["note"] = "Measured allocated resident model memory, not direct KV allocation. Context returned to 4096. Different graph/workspace allocations can contribute to the delta."
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
