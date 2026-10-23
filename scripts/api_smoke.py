"""One real request through the OpenAI-compatible endpoint, plus model metadata and residency.

Loopback-only (enforced by qwen_agent.client). Never falls back to any cloud API.
Usage: python scripts/api_smoke.py --base-url http://127.0.0.1:11437/v1 --model qwen2.5-coder:7b
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_agent.client import Client


def nvidia_smi():
    if not shutil.which("nvidia-smi"):
        return {"available": False}
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
    apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"],
                          capture_output=True, text=True, timeout=15)
    return {"columns": "name,memory_total_MiB,memory_used_MiB,util_percent,driver", "gpu": out.stdout.strip(),
            "compute_apps": apps.stdout.strip() or "(WDDM on Windows often hides per-process GPU memory)"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11437/v1")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/serving"))
    args = parser.parse_args()
    client = Client(args.base_url, args.model)
    origin = client.base_url[: -len("/v1")]

    def native(path, body=None):
        req = urllib.request.Request(origin + path, headers={"Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        with client.opener.open(req, timeout=60) as response:
            return json.loads(response.read(2_000_000))

    record = {"at_utc": datetime.now(timezone.utc).isoformat(), "base_url": client.base_url, "model": args.model,
              "server_version": native("/api/version"), "gpu_before": nvidia_smi(), "v1_models": client.models()}
    show = native("/api/show", {"model": args.model})
    record["model_metadata"] = {
        "details": show.get("details"),
        "architecture_context_length": next((v for k, v in show.get("model_info", {}).items() if k.endswith(".context_length")), None),
        "parameter_count": show.get("model_info", {}).get("general.parameter_count"),
        "parameters": show.get("parameters"),
    }
    body = {"model": args.model, "temperature": 0, "max_tokens": 120, "stream": False,
            "messages": [{"role": "user", "content": "Write a one-line Python expression that computes 2 / (2 + 1) rounded to 4 decimals. Reply with code only."}]}
    started = time.monotonic()
    response = client.request("/chat/completions", body)
    record["chat_completion"] = {"request": body, "latency_seconds_including_cold_load": round(time.monotonic() - started, 3), "raw_response": response}
    loaded = native("/api/ps")
    record["residency"] = [{"name": m["name"], "size_bytes": m["size"], "size_vram_bytes": m["size_vram"],
                            "gpu_fraction": round(m["size_vram"] / m["size"], 4) if m["size"] else None,
                            "context_length": m.get("context_length")} for m in loaded.get("models", [])]
    record["gpu_after"] = nvidia_smi()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"api-smoke-{args.model.replace(':', '_')}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"file": str(path), "answer": response["choices"][0]["message"]["content"],
                      "usage": response.get("usage"), "residency": record["residency"],
                      "gpu_before": record["gpu_before"].get("gpu"), "gpu_after": record["gpu_after"].get("gpu"),
                      "details": record["model_metadata"]["details"],
                      "arch_ctx": record["model_metadata"]["architecture_context_length"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
