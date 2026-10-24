"""Layered health check.

L1 process  : the recorded server PID is alive (skipped when no PID is known, e.g. Docker)
L1 port     : TCP connect to host:port succeeds
L2 api      : GET /v1/models answers within a short timeout and lists the model
L3 model    : fixed golden prompts (temperature 0) return the exact expected answers
L4 residency: Ollama /api/ps shows the model fully in VRAM (CPU offload = degraded)
     disk   : free space on the model drive is above a floor

Status is the first failing layer, so "process up but API stuck" and
"API up but model not answering" are reported as different problems.
"""
from datetime import datetime, timezone
import json
import math
import os
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GOLDEN = [
    {"id": "arith", "messages": [{"role": "user", "content": "What is 17 * 23? Reply with the number only."}],
     "max_tokens": 8, "expect_regex": r"^\s*391\.?\s*$"},
    {"id": "json_schema", "messages": [{"role": "user", "content": "Return JSON whose field answer equals 12 * 12."}],
     "max_tokens": 40, "expect_json": {"answer": 144},
     "response_format": {"type": "json_schema", "json_schema": {"name": "golden", "strict": True, "schema": {
         "type": "object", "additionalProperties": False, "properties": {"answer": {"type": "integer"}}, "required": ["answer"]}}}},
]
EXIT = {"healthy": 0, "down": 1, "api_unresponsive": 2, "model_wrong_or_slow": 3, "degraded_cpu_offload": 4, "disk_low": 5}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def pct(values, p):
    """Nearest-rank percentile (p in 0..1); None for no values."""
    values = sorted(values)
    return values[max(0, math.ceil(p * len(values)) - 1)] if values else None


def pid_alive(pid):
    """True if the process exists. Never sends a signal (os.kill(pid, 0) terminates processes on Windows)."""
    if not pid:
        return None
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    return os.path.exists(f"/proc/{int(pid)}")


def http_json(url, body=None, timeout=5, headers=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read(1_000_000))


def auth_headers():
    key = os.environ.get("LOCAL_MODEL_API_KEY")
    return {"Authorization": "Bearer " + key} if key else {}


def check(base_url, model, pid=None, api_timeout=5.0, model_timeout=90.0, ollama=True, disk_path=None, min_disk_gb=10.0, golden=True):
    parsed = urllib.parse.urlsplit(base_url)
    origin = base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url
    result = {"at_utc": now(), "base_url": base_url, "model": model, "checks": {}}
    c = result["checks"]

    alive = pid_alive(pid)
    c["process"] = {"pid": pid, "ok": alive} if pid else {"ok": None, "note": "no PID tracked (e.g. container)"}
    started = time.monotonic()
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=2):
            c["port"] = {"ok": True, "seconds": round(time.monotonic() - started, 3)}
    except OSError as exc:
        c["port"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if c["port"]["ok"]:
        started = time.monotonic()
        try:
            models = http_json(base_url + "/models", timeout=api_timeout, headers=auth_headers())
            ids = [m.get("id") for m in models.get("data", [])]
            c["api"] = {"ok": model in ids, "seconds": round(time.monotonic() - started, 3), "models": ids}
        except (OSError, ValueError) as exc:
            c["api"] = {"ok": False, "seconds": round(time.monotonic() - started, 3), "error": f"{type(exc).__name__}: {exc}"}

    if c.get("api", {}).get("ok") and golden:
        results = []
        for g in GOLDEN:
            body = {"model": model, "messages": g["messages"], "temperature": 0, "max_tokens": g["max_tokens"], "stream": False}
            if "response_format" in g:
                body["response_format"] = g["response_format"]
            started = time.monotonic()
            item = {"id": g["id"]}
            try:
                response = http_json(base_url + "/chat/completions", body, timeout=model_timeout, headers=auth_headers())
                text = response["choices"][0]["message"]["content"]
                item.update(seconds=round(time.monotonic() - started, 3), answer=text[:200], usage=response.get("usage"))
                if "expect_regex" in g:
                    item["ok"] = bool(re.match(g["expect_regex"], text))
                else:
                    try:
                        item["ok"] = json.loads(text) == g["expect_json"]
                    except ValueError:
                        item["ok"] = False
            except (OSError, ValueError, KeyError, IndexError) as exc:
                item.update(ok=False, seconds=round(time.monotonic() - started, 3), error=f"{type(exc).__name__}: {exc}")
            results.append(item)
        c["model"] = {"ok": all(r["ok"] for r in results), "golden": results}

    if ollama and c.get("api", {}).get("ok"):
        try:
            loaded = [m for m in http_json(origin + "/api/ps", timeout=api_timeout).get("models", []) if m.get("name") == model]
            if loaded:
                m = loaded[0]
                fraction = m["size_vram"] / m["size"] if m.get("size") else None
                c["residency"] = {"ok": fraction is not None and fraction >= 0.999, "gpu_fraction": round(fraction, 4) if fraction is not None else None,
                                  "size_bytes": m.get("size"), "size_vram_bytes": m.get("size_vram"), "context_length": m.get("context_length")}
            else:
                c["residency"] = {"ok": None, "note": "model not loaded right now (loads on first request)"}
        except (OSError, ValueError) as exc:
            c["residency"] = {"ok": None, "error": f"{type(exc).__name__}: {exc}"}

    if disk_path:
        free = shutil.disk_usage(disk_path).free / 2**30
        c["disk"] = {"ok": free >= min_disk_gb, "free_gib": round(free, 1), "path": str(disk_path), "floor_gib": min_disk_gb}

    if c["process"]["ok"] is False or not c["port"]["ok"]:
        status = "down"
    elif not c.get("api", {}).get("ok"):
        status = "api_unresponsive"
    elif golden and not c.get("model", {}).get("ok"):
        status = "model_wrong_or_slow"
    elif c.get("residency", {}).get("ok") is False:
        status = "degraded_cpu_offload"
    elif c.get("disk", {}).get("ok") is False:
        status = "disk_low"
    else:
        status = "healthy"
    result["status"] = status
    return result
