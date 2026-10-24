"""Periodic sampler: health status, API latency, GPU memory/utilization, residency, disk, and new problems in the
server logs (context shift, CPU offload, GPU errors, 5xx and latency of real traffic). Rotating JSONL + alerts.

On Linux/vLLM, Prometheus scraping /metrics would replace most of this (not set up yet).
"""
import shutil
import subprocess
import time

from .health import check
from .logs import compact, json_logger

THRESHOLDS = {"api_seconds": 2.0, "gpu_memory_used_fraction": 0.95, "disk_free_gib": 10.0, "error_rate_5xx": 0.05, "chat_p95_seconds": 60.0}
LOG_ALERTS = ("context_shift", "truncated", "cpu_offload", "gpu_error", "runner_exit", "queue_full", "gpu_warning")


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout.strip()
        used, total, util, temp = [float(x) for x in out.splitlines()[0].split(",")]
        return {"memory_used_mib": used, "memory_total_mib": total, "utilization_pct": util, "temperature_c": temp}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


class LogWatch:
    """Remembers how far the server logs were read, so each sample reports only new lines."""

    def __init__(self, launch_fn):
        self.launch_fn, self.key, self.err, self.out = launch_fn, None, 0, 0

    def delta(self):
        from . import ollama_log
        rec = self.launch_fn() if self.launch_fn else None
        if not rec:
            return None
        err, out = ollama_log.log_pair(rec)
        if self.key is None:  # first sample: ignore what happened before monitoring started
            self.key, self.err, self.out = str(err), ollama_log.line_count(err), ollama_log.line_count(out)
        elif self.key != str(err):  # server restarted with a new log file: read it from the first line
            self.key, self.err, self.out = str(err), 0, 0
        res = ollama_log.scan(rec, self.err, self.out)
        self.err = res["stderr"]["lines"]
        self.out = ollama_log.line_count(out)
        chat = (res.get("access") or {}).get("by_route", {}).get("/v1/chat/completions")
        return {"counts": res["stderr"]["counts"], "chat": chat}


def sample(base_url, model, pid, disk_path, golden, ollama=True, logwatch=None):
    h = check(base_url, model, pid=pid, golden=golden, disk_path=disk_path, model_timeout=60, ollama=ollama)
    g = gpu()
    s = {**compact(h), "gpu": g, "disk_free_gib": round(shutil.disk_usage(disk_path).free / 2**30, 1)}
    logs = logwatch.delta() if logwatch else None
    if logs:
        s["log"] = logs
    alerts = []
    if h["status"] != "healthy":
        alerts.append(f"status={h['status']}")
    if (s.get("api_seconds") or 0) > THRESHOLDS["api_seconds"]:
        alerts.append(f"api_seconds>{THRESHOLDS['api_seconds']}")
    if "memory_used_mib" in g and g["memory_used_mib"] / g["memory_total_mib"] > THRESHOLDS["gpu_memory_used_fraction"]:
        alerts.append("gpu_memory>95%")
    if s["disk_free_gib"] < THRESHOLDS["disk_free_gib"]:
        alerts.append("disk_free<10GiB")
    if logs:
        alerts += [f"log:{k}+{logs['counts'][k]}" for k in LOG_ALERTS if logs["counts"].get(k)]
        chat = logs.get("chat")
        if chat and chat["error_rate"] > THRESHOLDS["error_rate_5xx"]:
            alerts.append(f"chat_5xx_rate={chat['error_rate']}")
        if chat and (chat["p95_s"] or 0) > THRESHOLDS["chat_p95_seconds"]:
            alerts.append(f"chat_p95_s={chat['p95_s']}")
    return s, alerts


def run(base_url, model, log_path, disk_path, pid_fn=lambda: None, interval=10.0, duration=60.0, golden_every=6, ollama=True, launch_fn=None):
    log = json_logger(log_path, "monitor")
    logwatch = LogWatch(launch_fn) if launch_fn else None
    end, i, rows = time.monotonic() + duration, 0, []
    while time.monotonic() < end:
        s, alerts = sample(base_url, model, pid_fn(), disk_path, golden=(i % golden_every == 0), ollama=ollama, logwatch=logwatch)
        rows.append(log("sample", n=i, **s))
        for a in alerts:
            rows.append(log("alert", n=i, reason=a))
        i += 1
        time.sleep(interval)
    return rows
