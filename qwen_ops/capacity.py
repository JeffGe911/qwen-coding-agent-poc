"""Capacity probe: concurrency/queueing, peak GPU memory, residency, and long-context behaviour.

Requests are streamed so each one records time-to-first-token (TTFT) as well as the total time:
with more concurrent requests than server slots, the extra requests wait in the server queue,
which shows up as TTFT growing while the per-token speed stays flat.
Prompts are synthetic; nothing from repositories is sent.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import statistics
import threading
import time
import urllib.error
import urllib.request

from .health import auth_headers, http_json, now, pct
from .monitor import gpu

SECRET = "ZEBRA-4417"


class GpuSampler(threading.Thread):
    def __init__(self, every=0.5):
        super().__init__(daemon=True)
        self.every, self.samples, self.stop_flag = every, [], threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            g = gpu()
            if "memory_used_mib" in g:
                self.samples.append(g)
            self.stop_flag.wait(self.every)

    def summary(self):
        self.stop_flag.set()
        self.join(timeout=5)
        if not self.samples:
            return {}
        return {"peak_memory_used_mib": max(s["memory_used_mib"] for s in self.samples),
                "mean_utilization_pct": round(statistics.fmean(s["utilization_pct"] for s in self.samples), 1), "samples": len(self.samples)}


def _open(url, body, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **auth_headers()})
    return opener.open(req, timeout=timeout)


def post(url, body, timeout):
    """One non-streaming request; never raises."""
    started = time.monotonic()
    try:
        with _open(url, body, timeout) as r:
            data = json.loads(r.read(1_000_000))
            return {"ok": True, "status": r.status, "seconds": round(time.monotonic() - started, 3), "usage": data.get("usage"),
                    "finish_reason": data["choices"][0].get("finish_reason"), "text": data["choices"][0]["message"]["content"]}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "seconds": round(time.monotonic() - started, 3), "error": exc.read(300).decode(errors="replace")}
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "status": None, "seconds": round(time.monotonic() - started, 3), "error": f"{type(exc).__name__}: {exc}"}


def post_stream(url, body, timeout):
    """One streamed request (SSE). Records TTFT, total time, usage and finish_reason; never raises."""
    body = {**body, "stream": True, "stream_options": {"include_usage": True}}
    started = time.monotonic()
    ttft, parts, usage, finish, done = None, [], None, None, False
    try:
        with _open(url, body, timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                chunk = json.loads(data)
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if piece and ttft is None:
                        ttft = time.monotonic() - started
                    parts.append(piece)
                    finish = choice.get("finish_reason") or finish
            status = r.status
        if not (done or finish):  # the connection closed mid-stream
            return {"ok": False, "status": status, "seconds": round(time.monotonic() - started, 3), "error": "stream ended without finish_reason or [DONE]",
                    "ttft_s": round(ttft, 3) if ttft is not None else None, "usage": usage}
        return {"ok": True, "status": status, "ttft_s": round(ttft, 3) if ttft is not None else None, "seconds": round(time.monotonic() - started, 3),
                "usage": usage, "finish_reason": finish, "text": "".join(parts)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "seconds": round(time.monotonic() - started, 3), "error": exc.read(300).decode(errors="replace")}
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "status": None, "seconds": round(time.monotonic() - started, 3), "error": f"{type(exc).__name__}: {exc}"}


def concurrency(base_url, model, levels=(1, 2, 4, 8), count=8, max_tokens=128, timeout=300):
    rows = []
    for level in levels:
        def one(i):
            body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": f"Request {level}-{i}. Count from 1 to 60, separated by single spaces. Output only the numbers."}]}
            r = post_stream(base_url + "/chat/completions", body, timeout)
            r.pop("text", None)
            return r
        sampler = GpuSampler()
        sampler.start()
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=level) as pool:
            reqs = list(pool.map(one, range(count)))
        wall = time.monotonic() - started
        ok = [r for r in reqs if r["ok"]]
        lat = [r["seconds"] for r in ok]
        ttft = [r["ttft_s"] for r in ok if r.get("ttft_s") is not None]
        toks = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in ok)
        rows.append({"client_concurrency": level, "requests": count, "ok": len(ok), "failed": count - len(ok),
                     "failure_statuses": sorted({str(r["status"]) for r in reqs if not r["ok"]}),
                     "ttft_p50_s": pct(ttft, 0.5), "ttft_p95_s": pct(ttft, 0.95), "ttft_max_s": max(ttft) if ttft else None,
                     "p50_s": pct(lat, 0.5), "p95_s": pct(lat, 0.95), "max_s": max(lat) if lat else None, "wall_s": round(wall, 3),
                     "output_tokens_per_s": round(toks / wall, 1) if wall else None, "gpu": sampler.summary(), "per_request": reqs})
    return rows


def long_context(base_url, model, target_tokens, timeout=600):
    """Secret at the very start, ~target_tokens of filler, question at the end. Truncation drops the secret."""
    line = "Record {:04d}: sensor reading nominal, no action required."
    n = max(1, int(target_tokens / 14))
    prompt = (f"The access code is {SECRET}. Remember it.\n" + "\n".join(line.format(i) for i in range(n)) +
              "\nQuestion: what is the access code given at the very beginning? Reply with the code only.")
    body = {"model": model, "temperature": 0, "max_tokens": 16, "stream": False, "messages": [{"role": "user", "content": prompt}]}
    sampler = GpuSampler()
    sampler.start()
    r = post(base_url + "/chat/completions", body, timeout)
    r["gpu"] = sampler.summary()
    r["target_tokens"] = target_tokens
    r["prompt_chars"] = len(prompt)
    r["answer_correct"] = bool(r.get("ok") and SECRET in r.get("text", ""))
    r["answer"] = (r.pop("text", "") or "")[:80]
    return r


def residency(base_url, model):
    origin = base_url[: -len("/v1")]
    try:
        for m in http_json(origin + "/api/ps", timeout=5).get("models", []):
            if m.get("name") == model:
                return {"size_bytes": m["size"], "size_vram_bytes": m["size_vram"], "gpu_fraction": round(m["size_vram"] / m["size"], 4),
                        "context_length": m.get("context_length")}
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}
    return {"note": "model not loaded"}


def run(base_url, model, levels, count, max_tokens, long_tokens):
    out = {"at_utc": now(), "base_url": base_url, "model": model, "gpu_idle": gpu()}
    out["concurrency"] = concurrency(base_url, model, levels, count, max_tokens)
    out["residency_after_load"] = residency(base_url, model)
    out["long_context"] = [long_context(base_url, model, t) for t in long_tokens]
    out["residency_end"] = residency(base_url, model)
    return out
