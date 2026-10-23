"""Small real API concurrency probe. Measures whole-request latency, not TTFT."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_agent.client import Client


def gpu():
    if not shutil.which("nvidia-smi"):
        return {"available": False}
    output = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    return {"exit_code": output.returncode, "columns": ["name", "driver_version", "memory_total_MiB", "memory_used_MiB", "utilization_percent", "temperature_C"], "csv": output.stdout.strip()}


def probe(client, count=4, levels=(1, 2)):
    def one(index):
        started = time.monotonic()
        try:
            response = client.request("/chat/completions", {"model": client.model, "messages": [{"role": "user", "content": f"Write a Python function that adds two integers. No explanation. Request {index}."}], "temperature": 0, "max_tokens": 64, "stream": False})
            return {"ok": True, "seconds": time.monotonic() - started, "usage": response.get("usage", {}), "finish_reason": response["choices"][0].get("finish_reason")}
        except (OSError, ValueError, KeyError) as exc:
            return {"ok": False, "seconds": time.monotonic() - started, "error": type(exc).__name__}
    cold = one(-1)
    results = []
    for concurrency in levels:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            requests = list(pool.map(one, range(count)))
        elapsed = time.monotonic() - started
        latencies = sorted(r["seconds"] for r in requests)
        tokens = sum(r.get("usage", {}).get("completion_tokens", 0) for r in requests if r["ok"])
        results.append({"client_concurrency": concurrency, "requests": requests, "wall_seconds": elapsed, "success_count": sum(r["ok"] for r in requests), "request_latency_p50_seconds": statistics.median(latencies), "request_latency_p95_seconds": latencies[math.ceil(0.95 * len(latencies)) - 1], "aggregate_output_tokens_per_second": tokens / elapsed})
    return {"warmup_request": cold, "warm_batches": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11437/v1")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--levels", default="1,2,4", help="client concurrency levels, comma separated")
    parser.add_argument("--count", type=int, default=8, help="warm requests per level")
    parser.add_argument("--backend", choices=["ollama", "vllm"], default="ollama")
    parser.add_argument("--output", type=Path, default=Path("evidence/serving.json"))
    args = parser.parse_args()
    client = Client(args.base_url, args.model)
    result = {"at_utc": datetime.now(timezone.utc).isoformat(), "base_url": client.base_url, "model": client.model, "gpu_before": gpu(), "models": client.models(), "measurement": f"{args.count} warm requests per client concurrency level {args.levels}; whole response latency, not streaming TTFT. Server-side parallel slots are set by OLLAMA_NUM_PARALLEL (see the launch record); extra client concurrency queues. Smoke benchmark, not a capacity test."}
    result.update(probe(client, args.count, tuple(int(x) for x in args.levels.split(","))))
    result["gpu_after"] = gpu()
    origin = args.base_url.removesuffix("/v1")
    if args.backend == "ollama":
        for name, path in [("version", "/api/version"), ("loaded_models", "/api/ps")]:
            with client.opener.open(urllib.request.Request(origin + path), timeout=10) as response:
                result[name] = json.loads(response.read(262144))
    else:
        for name, path in [("health", "/health"), ("metrics", "/metrics")]:
            with client.opener.open(urllib.request.Request(origin + path), timeout=10) as response:
                result[name] = response.read(262144).decode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
