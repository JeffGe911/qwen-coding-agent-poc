"""Run one split of a frozen triage contract against the local model, with a resource watchdog.

Before: refuses unless available RAM, commit headroom and free VRAM are above the thresholds. Page-file growth is not
counted as headroom, because relying on it means paging the operator's other programs out.
During: samples memory and GPU every 2 s into resources.csv. If available RAM or commit headroom falls below the abort
thresholds, it stops the eval process it started, and nothing else.
After: records /api/ps and nvidia-smi. With --unload it asks the server to unload the model (keep_alive 0) and checks
that it is gone.
Evidence goes to evidence/regression-triage/model-runs/<contract>/<split>/.

Usage: python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v2.json --split dev
       python scripts/triage_model_session.py --contract ... --split holdout --unload
       python scripts/triage_model_session.py --contract ... --preflight-only | --unload-only
"""
import argparse
import csv
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence" / "regression-triage"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# The 7B Q4_K_M at context 8192 held 5090 MiB of VRAM (evidence/context-validation/report.json, r2); host-side buffers are
# about 365 MiB (CUDA_Host model + compute buffers in the r2 server log). The thresholds leave room for the operator's programs.
THRESHOLDS = {"min_available_mb": 4096, "min_commit_headroom_mb": 4096, "min_free_vram_mb": 6500, "abort_available_mb": 2048, "abort_commit_headroom_mb": 2048}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    """Available RAM and commit headroom (current commit limit minus committed bytes), in MiB. Windows only."""
    s = MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(s)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
        raise OSError("GlobalMemoryStatusEx failed")
    mb = 2**20
    return {"total_mb": s.ullTotalPhys // mb, "available_mb": s.ullAvailPhys // mb, "commit_limit_mb": s.ullTotalPageFile // mb,
            "commit_headroom_mb": s.ullAvailPageFile // mb}


def gpu():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
    used, total, util, temp = (int(float(x)) for x in out.split(","))
    return {"vram_used_mb": used, "vram_total_mb": total, "vram_free_mb": total - used, "gpu_util_pct": util, "gpu_temp_c": temp}


def problems(mem, g, t=THRESHOLDS):
    """Reasons not to load a model now (empty list = go)."""
    out = []
    if mem["available_mb"] < t["min_available_mb"]:
        out.append(f"available RAM {mem['available_mb']} MiB < {t['min_available_mb']}")
    if mem["commit_headroom_mb"] < t["min_commit_headroom_mb"]:
        out.append(f"commit headroom {mem['commit_headroom_mb']} MiB < {t['min_commit_headroom_mb']} (page-file growth not counted)")
    if g["vram_free_mb"] < t["min_free_vram_mb"]:
        out.append(f"free VRAM {g['vram_free_mb']} MiB < {t['min_free_vram_mb']}")
    return out


def must_abort(mem, t=THRESHOLDS):
    return mem["available_mb"] < t["abort_available_mb"] or mem["commit_headroom_mb"] < t["abort_commit_headroom_mb"]


def http_json(url, body=None, timeout=30):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def processes():
    """Private and working-set MiB of the Ollama server and its runner processes (snapshot)."""
    ps = ("Get-Process ollama*, llama* -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{pid=$_.Id; name=$_.ProcessName; "
          "private_mb=[int]($_.PrivateMemorySize64/1MB); working_set_mb=[int]($_.WorkingSet64/1MB)} } | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60).stdout.strip()
    data = json.loads(out) if out else []
    return data if isinstance(data, list) else [data]


def snapshot(origin):
    try:
        ps = http_json(origin + "/api/ps", timeout=10)
    except OSError as e:
        ps = {"error": str(e)}
    return {"at_utc": now(), "memory": memory(), "gpu": gpu(), "api_ps": ps, "processes": processes()}


def unload(origin, model):
    http_json(origin + "/api/generate", {"model": model, "keep_alive": 0}, timeout=60)
    for _ in range(30):
        if not http_json(origin + "/api/ps", timeout=10).get("models"):
            return True
        time.sleep(1)
    return False


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--contract", required=True)
    p.add_argument("--split", choices=["dev", "holdout"])
    p.add_argument("--unload", action="store_true", help="unload the model after the run")
    p.add_argument("--preflight-only", action="store_true")
    p.add_argument("--unload-only", action="store_true")
    args = p.parse_args()
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    q = contract["qwen"]["backend"] if "backend" in contract["qwen"] else contract["qwen"]  # eval-v3+ profile, or the eval-v2 shape
    if q.get("kind", "ollama") != "ollama":
        raise SystemExit("this session wrapper measures Ollama on Windows (memory counters, /api/ps, keep_alive unload); "
                         "for vLLM on Linux use deploy/linux-vllm/migrate.sh, which records resources with nvidia-smi and docker stats")
    origin = q["base_url"][: -len("/v1")]
    if args.unload_only:
        before = snapshot(origin)
        ok = unload(origin, q["model"])
        out = EV / "model-runs" / contract["version"]
        out.mkdir(parents=True, exist_ok=True)
        write(out / "unload.json", {"model": q["model"], "unloaded": ok, "before": before, "after": snapshot(origin)})
        print("unloaded" if ok else "model still resident", out / "unload.json")
        return 0 if ok else 1
    mem, g = memory(), gpu()
    blockers = problems(mem, g)
    if args.preflight_only or blockers:
        print(json.dumps({"at_utc": now(), "memory": mem, "gpu": g, "thresholds": THRESHOLDS, "problems": blockers}, indent=1))
        if blockers:
            print("not starting: " + "; ".join(blockers), file=sys.stderr)
        return 1 if blockers else 0
    if not args.split:
        p.error("--split is required")

    out = EV / "model-runs" / contract["version"] / args.split
    if out.exists():
        raise SystemExit(f"{out} exists; a split is run once per contract version")
    out.mkdir(parents=True)
    session = {"contract": contract["version"], "split": args.split, "thresholds": THRESHOLDS, "started_utc": now(), "before": snapshot(origin)}
    write(out / "session.json", session)
    stop = threading.Event()
    state = {"aborted": None, "min_available_mb": None, "min_commit_headroom_mb": None, "max_vram_used_mb": None, "samples": 0}
    log = open(out / "eval-stdout.txt", "w", encoding="utf-8", newline="\n")
    proc = subprocess.Popen([sys.executable, "-m", "regression_triage", "eval", "--contract", args.contract, "--split", args.split, "--engine", "qwen"],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)

    def watch():
        with open(out / "resources.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["utc", "available_mb", "commit_headroom_mb", "commit_limit_mb", "vram_used_mb", "gpu_util_pct", "gpu_temp_c"])
            while not stop.is_set():
                m, gg = memory(), gpu()
                w.writerow([now(), m["available_mb"], m["commit_headroom_mb"], m["commit_limit_mb"], gg["vram_used_mb"], gg["gpu_util_pct"], gg["gpu_temp_c"]])
                f.flush()
                state["samples"] += 1
                for key, val, pick in (("min_available_mb", m["available_mb"], min), ("min_commit_headroom_mb", m["commit_headroom_mb"], min), ("max_vram_used_mb", gg["vram_used_mb"], max)):
                    state[key] = val if state[key] is None else pick(state[key], val)
                if must_abort(m) and proc.poll() is None:
                    state["aborted"] = {"at_utc": now(), "memory": m}
                    proc.terminate()  # only the eval process this script started
                stop.wait(2)

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    code = proc.wait()
    stop.set()
    t.join(10)
    log.close()
    session.update(finished_utc=now(), eval_exit_code=code, watch=state, after_run=snapshot(origin))
    if args.unload:
        session["unloaded"] = unload(origin, q["model"])
        session["after_unload"] = snapshot(origin)
    write(out / "session.json", session)
    print(json.dumps({k: session[k] for k in ("eval_exit_code", "watch")} | {"unloaded": session.get("unloaded")}, indent=1))
    return 0 if code == 0 and not state["aborted"] else 1


if __name__ == "__main__":
    sys.exit(main())
