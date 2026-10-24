"""Runner for evaluation contract chip_final_yield/rev2 (qwen_agent/contracts/chip_final_yield/rev2.json).

    python -m qwen_ops.chip_rev2 equivalence                 # rev-1 request replayed through the rev-2 transport
    python -m qwen_ops.chip_rev2 run --arm A                 # proposals until approval is needed or the 3-proposal budget is used
    python -m qwen_ops.chip_rev2 decide --arm A --digest D --reviewer R   # after a human approved the shown diff
    python -m qwen_ops.chip_rev2 vram --model qwen2.5-coder:14b           # arm C precondition

Every agent call goes through the operator CLI in a child process. calls.jsonl records each call with the server-log
line window it produced, so context shifts and effective sampler values can be attributed to one proposal.
Nothing here approves or executes model code; `decide` only forwards a decision a human already made.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from . import ollama_log, release
from .health import check, http_json, now
from .monitor import gpu
from .service import ROOT, OllamaWindows

OUT = ROOT / "evidence" / "chip-rev2"
CONTRACT = ROOT / "qwen_agent" / "contracts" / "chip_final_yield" / "rev2.json"
RELEASE = "r2-7b-ctx8192-np1"
BASE = "http://127.0.0.1:11437/v1"


def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def service():
    return OllamaWindows(11437)


def append(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def server_check():
    """The arms run on release r2: pins, settings and the per-request context must match."""
    svc = service()
    manifest = release.load(RELEASE)
    problems = release.verify_pins(manifest, release.service_for(manifest))
    res = next((m for m in http_json(BASE[:-3] + "/api/ps", timeout=10).get("models", [])), None)
    return {"at_utc": now(), "active": release.active_name(), "pin_problems": problems, "loaded": res and {k: res.get(k) for k in ("name", "size", "size_vram", "context_length")},
            "launch_record": svc.launch_record().get("started_at_utc"), "ok": not problems}


def cli(arm, args, timeout=1800):
    """One operator command; records the server-log line window it produced."""
    svc = service()
    err, out = ollama_log.log_pair(svc.launch_record())
    start = ollama_log.line_count(err)
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-m", "qwen_agent", *map(str, args)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=timeout)
    rec = {"at_utc": now(), "arm": arm, "command": "python -m qwen_agent " + " ".join(map(str, args)), "exit_code": p.returncode,
           "seconds": round(time.monotonic() - t0, 2), "stdout_tail": p.stdout[-1500:], "stderr_tail": p.stderr[-800:],
           "server_log": {"file": Path(err).name, "start_line": start, "end_line": ollama_log.line_count(err)}}
    append(OUT / arm / "calls.jsonl", rec)
    keep_log(err)
    return rec


def keep_log(err):
    logs = OUT / "server-logs"
    logs.mkdir(parents=True, exist_ok=True)
    for path in (Path(err), Path(str(err).replace(".err.log", ".out.log"))):
        if path.exists():
            (logs / path.name).write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def run_dir(arm):
    runs = sorted((OUT / arm / "runs").glob("*")) if (OUT / arm / "runs").exists() else []
    return runs[-1] if runs else None


def state(run):
    return json.loads((run / "state.json").read_text(encoding="utf-8"))


def advance(arm):
    """Retry model errors inside the 3-proposal budget (policy blocks re-propose by themselves); stop at a human decision."""
    run = run_dir(arm)
    while True:
        s = state(run)
        if s["status"] != "model_error" or s.get("stop_reason") or len(s["attempts"]) >= s["config"]["max_attempts"]:
            return s
        cli(arm, ["retry", run.relative_to(ROOT)])


def run_arm(arm):
    if run_dir(arm):
        raise SystemExit(f"arm {arm} already has a run ({run_dir(arm)}); continue it with decide, do not start another")
    spec = contract()["arms"][arm]
    pre = append(OUT / arm / "prechecks.jsonl", {"server": server_check(), "model": spec["model"]})
    if not pre["server"]["ok"]:
        raise SystemExit(f"server is not release {RELEASE}: {pre['server']['pin_problems']}")
    cli(arm, ["start", "--task", "chip_final_yield", "--contract", CONTRACT.relative_to(ROOT).as_posix(), "--arm", arm, "--base-url", BASE,
              "--sandbox", "restricted", "--runs", (OUT / arm / "runs").relative_to(ROOT).as_posix()])
    return advance(arm)


def decide(arm, digest, reviewer):
    run = run_dir(arm)
    cli(arm, ["decide", run.relative_to(ROOT), "approve", "--digest", digest, "--reviewer", reviewer])
    return advance(arm)


def equivalence():
    """Replay the recorded revision-1 chip request (r2 server, /v1) through /v1 again and through the revision-2 transport with
    the control profile. Same request bytes; if the native control reproduces /v1, the transport is not an extra variable."""
    from qwen_agent.client import Client
    from qwen_agent.workflow import snapshot
    run = ROOT / "evidence" / "context-validation" / "r2-7b-ctx8192-np1" / "runs" / "20261023T213445Z-chip_final_yield-c1329f74"
    s = state(run)
    files = snapshot(run / "workspace")
    client = Client(BASE, "qwen2.5-coder:7b")
    out = OUT / "00-transport-equivalence"
    out.mkdir(parents=True, exist_ok=True)
    err, _ = ollama_log.log_pair(service().launch_record())
    start = ollama_log.line_count(err)
    args = (s["task"], files["solution.py"], files["test_visible.py"], s["feedback"])
    responses = {"recorded_rev1_v1": json.loads((run / "attempt-1" / "model-response.json").read_text(encoding="utf-8")),
                 "replay_v1": client.propose(*args), "replay_native_control": client.propose(*args, profile=contract()["arms"]["control"]["generation"])}
    for name, r in responses.items():
        (out / f"{name}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    texts = {k: r["choices"][0]["message"]["content"] for k, r in responses.items()}
    first_diff = lambda a, b: next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None if len(a) == len(b) else min(len(a), len(b)))
    result = {"at_utc": now(), "source_run": run.relative_to(ROOT).as_posix(),
              "usage": {k: r.get("usage") for k, r in responses.items()}, "finish_reason": {k: r["choices"][0]["finish_reason"] for k, r in responses.items()},
              "identical_text": {"replay_v1 vs recorded": texts["replay_v1"] == texts["recorded_rev1_v1"],
                                 "native_control vs replay_v1": texts["replay_native_control"] == texts["replay_v1"],
                                 "native_control vs recorded": texts["replay_native_control"] == texts["recorded_rev1_v1"]},
              "first_differing_char": {"native_control vs replay_v1": first_diff(texts["replay_native_control"], texts["replay_v1"]),
                                       "replay_v1 vs recorded": first_diff(texts["replay_v1"], texts["recorded_rev1_v1"])},
              "server_log": {"file": Path(err).name, "start_line": start, "end_line": ollama_log.line_count(err)}}
    (out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    keep_log(err)
    return result


def vram(model):
    """Arm C precondition: free VRAM with nothing loaded, the model's size and KV need, then a load probe that must be 100% GPU."""
    origin = BASE[:-3]
    out = {"at_utc": now(), "model": model}
    for m in http_json(origin + "/api/ps", timeout=10).get("models", []):  # unload whatever is resident first
        body = json.dumps({"model": m["name"], "keep_alive": 0}).encode()
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(origin + "/api/generate", data=body), timeout=60).read()
    for _ in range(30):
        if not http_json(origin + "/api/ps", timeout=10).get("models"):
            break
        time.sleep(1)
    out["gpu_idle"] = gpu()
    rec = service().launch_record()
    out["ollama_inference_compute"] = next((l for l in rec.get("startup_log_lines", []) if "inference compute" in l), None)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="qwen_ops.chip_rev2")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--arm", required=True)
    d = sub.add_parser("decide"); d.add_argument("--arm", required=True); d.add_argument("--digest", required=True); d.add_argument("--reviewer", required=True)
    v = sub.add_parser("vram"); v.add_argument("--model", required=True)
    sub.add_parser("check")
    sub.add_parser("equivalence")
    args = p.parse_args(argv)
    if args.cmd == "run":
        res = run_arm(args.arm)
    elif args.cmd == "decide":
        res = decide(args.arm, args.digest, args.reviewer)
    elif args.cmd == "vram":
        res = vram(args.model)
    elif args.cmd == "equivalence":
        res = equivalence()
    else:
        res = server_check()
    print(json.dumps(res if args.cmd in ("vram", "check", "equivalence") else {"status": res["status"], "attempts": [(a["attempt"], a["status"], a.get("error", "")[:160]) for a in res["attempts"]],
                                                                  "digest": res["attempts"][-1].get("digest") if res["status"] == "awaiting_approval" else None},
                     indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
