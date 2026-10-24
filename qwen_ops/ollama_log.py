"""Scan the Ollama server logs for problems an HTTP health check cannot see.

stderr (server + llama-server runner):
  context_shift   "slot context shift": the slot filled up during generation and the runner discarded
                  part of the prompt; the API still returns finish_reason=stop, so callers never notice
  truncated       "stop processing ... truncated = 1": a request finished with a truncated context
  cpu_offload     "offloaded N/M layers to GPU" with N < M: part of the model runs on the CPU
  gpu_error       CUDA errors / out of memory / failed allocations
  runner_exit     the runner process terminated
stdout ([GIN] access log): status codes and latency per route, no request bodies.

At the default log level they are not expected to contain prompts or completions; check with a unique marker before relying on that.
"""
from collections import Counter
from datetime import datetime
from pathlib import Path
import re

from .health import pct

PATTERNS = {
    "context_shift": re.compile(r"slot context shift"),
    "truncated": re.compile(r"stop processing: .*truncated = 1"),
    "gpu_error": re.compile(r"CUDA error|out of memory|cudaMalloc failed|failed to allocate", re.I),
    "runner_exit": re.compile(r"runner process (has )?terminated|llama-server.* exited|signal arrived during cgo execution"),
    "queue_full": re.compile(r"server busy|maximum pending requests exceeded", re.I),
    # Startup warnings that the model still loaded through, but that point at driver/GPU discovery trouble.
    "gpu_warning": re.compile(r"GPU discovery watchdog timed out|failure during .*GPU discovery|unable to refresh free memory"),
}
OFFLOAD = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")
GIN = re.compile(r'^\[GIN\] (\d{4}/\d\d/\d\d - \d\d:\d\d:\d\d) \| (\d{3}) \|\s*([\d.]+)(ns|µs|us|ms|s|m[\d.]+s)\s*\|\s*(\S+)\s*\|\s*(\w+)\s+"([^"]+)"')
UNITS = {"ns": 1e-9, "µs": 1e-6, "us": 1e-6, "ms": 1e-3, "s": 1.0}


def seconds(value, unit):
    if unit.startswith("m") and unit not in UNITS:  # e.g. "1" + "m2.5s" -> 1 minute 2.5 seconds
        return float(value) * 60 + float(unit[1:-1])
    return float(value) * UNITS[unit]


def log_pair(launch_record):
    """(stderr, stdout) log paths for a launch record written by scripts/start_ollama.ps1."""
    err = Path(launch_record["stderr_log"])
    return err, err.with_name(err.name.replace(".err.log", ".out.log"))


def scan_err(path, start_line=0):
    found = {k: [] for k in PATTERNS}
    found["cpu_offload"] = []
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    for n, line in enumerate(lines[start_line:], start_line + 1):
        for key, rx in PATTERNS.items():
            if rx.search(line):
                found[key].append({"line": n, "text": line[:240]})
        m = OFFLOAD.search(line)
        if m and int(m.group(1)) < int(m.group(2)):
            found["cpu_offload"].append({"line": n, "text": line[:240]})
    return {"path": str(path), "lines": len(lines), "counts": {k: len(v) for k, v in found.items()},
            "examples": {k: v[-3:] for k, v in found.items() if v}}


def scan_access(path, start_line=0, since=None):
    rows = []
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[start_line:]:
        m = GIN.match(line)
        if not m:
            continue
        at = datetime.strptime(m.group(1), "%Y/%m/%d - %H:%M:%S")
        if since and at < since:
            continue
        rows.append({"at": at, "status": int(m.group(2)), "seconds": seconds(m.group(3), m.group(4)), "method": m.group(6), "route": m.group(7)})
    by_route = {}
    for route in sorted({r["route"] for r in rows}):
        rs = [r for r in rows if r["route"] == route]
        lat = [r["seconds"] for r in rs]
        errors = sum(r["status"] >= 500 for r in rs)
        by_route[route] = {"requests": len(rs), "status": dict(Counter(str(r["status"]) for r in rs)), "errors_5xx": errors,
                           "error_rate": round(errors / len(rs), 4), "p50_s": pct(lat, 0.5), "p95_s": pct(lat, 0.95), "max_s": max(lat)}
    return {"path": str(path), "requests": len(rows), "by_route": by_route}


def scan(launch_record, err_start=0, out_start=0):
    err, out = log_pair(launch_record)
    return {"stderr": scan_err(err, err_start), "access": scan_access(out, out_start) if out.exists() else None}


def line_count(path):
    try:
        return len(Path(path).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0
