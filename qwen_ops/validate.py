"""Evidence-backed validation of one serving configuration for the frozen agent tasks.

    python -m qwen_ops validate --label r2-7b-ctx8192-np1 --context 8192 --parallel 1 [--max-tokens N] [--no-tasks]

Writes evidence/context-validation/<label>/ with three separately reported layers:
  service    : model loaded, API answers golden prompts, backend/residency on GPU, effective settings
               (launch record, llama-server -c/-np, n_ctx_seq, /api/ps context_length), free VRAM
  generation : per proposal: prompt/completion tokens vs context window and output budget, finish_reason,
               context shift / truncation in the server log, JSON validity, Python parse, policy result
  business   : filled in later from the run state, only after a human approved and pytest ran
Agent runs use the frozen tasks, prompt and policy unchanged and stop at awaiting_approval.
"""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from qwen_agent.client import DEFAULT_MAX_TOKENS
from qwen_agent.policy import PolicyError, validate as policy_validate

from . import ollama_log
from .capacity import GpuSampler
from .health import check, now
from .monitor import gpu
from .service import ROOT, OllamaWindows, runtime_dir

OUT = ROOT / "evidence" / "context-validation"
TASKS = ("report_pass_rate", "chip_final_yield")
MODEL = "qwen2.5-coder:7b"


def agent(args, timeout=900):
    """Run the agent CLI exactly as an operator would, in a child process."""
    started = time.monotonic()
    p = subprocess.run([sys.executable, "-m", "qwen_agent", *map(str, args)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=timeout)
    return {"command": "python -m qwen_agent " + " ".join(str(a) if " " not in str(a) else f'"{a}"' for a in args).replace(str(ROOT) + os.sep, ""),
            "exit_code": p.returncode, "seconds": round(time.monotonic() - started, 2), "stdout": p.stdout[-8000:], "stderr": p.stderr[-3000:]}


def running_matches(svc):
    rec = svc.launch_record()
    if not rec:
        return False
    from .health import pid_alive
    env = rec.get("environment", {})
    wanted = {"OLLAMA_CONTEXT_LENGTH": str(svc.context), "OLLAMA_NUM_PARALLEL": str(svc.parallel), "OLLAMA_MAX_QUEUE": str(svc.max_queue)}
    extra = set(env) - set(wanted) - {"OLLAMA_HOST", "OLLAMA_MODELS", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE", "OLLAMA_NO_CLOUD"}
    return bool(pid_alive(rec["pid"])) and all(env.get(k) == v for k, v in wanted.items()) and not extra


def effective_settings(rec):
    """What the server actually ran with, read from its own log (not from what was requested)."""
    err, _ = ollama_log.log_pair(rec)
    text = Path(err).read_text(encoding="utf-8", errors="replace")
    runner = re.findall(r'msg="starting llama-server" cmd="([^"]+)"', text)
    last = runner[-1] if runner else ""
    flag = lambda name: (re.search(rf"(?:^|\s){name} (\S+)", last) or [None, None])[1]
    grab = lambda rx: (re.findall(rx, text) or [None])[-1]
    return {
        "launch_environment": {k: v for k, v in rec.get("environment", {}).items() if k != "OLLAMA_MODELS"},
        "inherited_environment": rec.get("inherited_environment"),
        "inference_compute": grab(r'msg="inference compute" (.+)'),
        "llama_server_ctx_total": flag("-c"), "llama_server_parallel": flag("-np"), "context_shift_enabled": "--context-shift" in last,
        "n_ctx_seq": grab(r"n_ctx_seq\s+=\s+(\d+)"), "n_seq_max": grab(r"n_seq_max\s+=\s+(\d+)"),
        "offloaded_layers": grab(r"offloaded (\d+/\d+) layers to GPU"),
    }


def timings(err_path, start_line):
    lines = Path(err_path).read_text(encoding="utf-8", errors="replace").splitlines()[start_line:]
    out = []
    for line in lines:
        m = re.search(r"task (\d+) \|\s+(prompt eval time|eval time|total time)\s+=\s+([\d.]+) ms /\s+(\d+) tokens", line)
        if m:
            out.append({"task": int(m.group(1)), "phase": m.group(2), "ms": float(m.group(3)), "tokens": int(m.group(4))})
    return out


def attempt_facts(run, attempt, context, max_tokens):
    """Raw facts of one proposal, recomputed from the saved model response (independent of the agent's own checks)."""
    folder = run / f"attempt-{attempt['attempt']}"
    facts = {"attempt": attempt["attempt"], "agent_status": attempt["status"], "agent_error": attempt.get("error"),
             "generation_seconds": attempt.get("generation_seconds")}
    path = folder / "model-response.json"
    if not path.exists():
        facts["model_response"] = None
        return facts
    resp = json.loads(path.read_text(encoding="utf-8"))
    usage = resp.get("usage") or {}
    choice = resp["choices"][0]
    total = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    facts.update(prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"), total_tokens=total,
                 context_window=context, context_overflow=total >= context, output_budget=max_tokens,
                 hit_output_budget=(usage.get("completion_tokens") or 0) >= max_tokens, finish_reason=choice.get("finish_reason"))
    content = choice["message"].get("content") or ""
    try:
        proposal = json.loads(content)
        facts["json_ok"] = isinstance(proposal, dict) and set(proposal) == {"code", "explanation"} and all(isinstance(v, str) for v in proposal.values())
    except ValueError as exc:
        proposal, facts["json_ok"], facts["json_error"] = None, False, str(exc)[:160]
    code = proposal.get("code") if isinstance(proposal, dict) else None
    if isinstance(code, str):
        try:
            ast.parse(code)
            facts["python_ok"] = True
        except SyntaxError as exc:
            facts["python_ok"], facts["python_error"] = False, f"{exc.msg} (line {exc.lineno})"
        try:
            policy_validate(code)
            facts["policy_ok"] = True
        except PolicyError as exc:
            facts["policy_ok"], facts["policy_error"] = False, str(exc)[:200]
    else:
        facts["python_ok"] = facts["policy_ok"] = None
    return facts


def run_task(task, svc, context, max_tokens, runs):
    rec = svc.launch_record()
    err, _ = ollama_log.log_pair(rec)
    start = ollama_log.line_count(err)
    runs = Path(runs)
    before = set(runs.glob("*")) if runs.exists() else set()
    sampler = GpuSampler()
    sampler.start()
    args = ["start", "--task", task, "--base-url", svc.base_url, "--model", MODEL, "--sandbox", "restricted", "--runs", runs.relative_to(ROOT),
            "--context-tokens", context]
    if max_tokens != DEFAULT_MAX_TOKENS:
        args += ["--max-tokens", max_tokens]
    r = agent(args)
    r["gpu_during_run"] = sampler.summary()
    new = sorted(set(runs.glob("*")) - before)
    r["run"] = str(new[-1].relative_to(ROOT)) if new else None
    return finish_task(r, err, start, context, max_tokens)


def finish_task(r, err, start, context, max_tokens):
    run = ROOT / r["run"] if r.get("run") else None
    if not run:
        return r
    state = json.loads((run / "state.json").read_text(encoding="utf-8"))
    scan = ollama_log.scan_err(err, start)
    r.update(status=state["status"], error=state.get("error"), stop_reason=state.get("stop_reason"),
             config={k: v for k, v in state["config"].items() if k != "contract"}, contract=state["config"]["contract"],
             attempts=[attempt_facts(run, a, context, max_tokens) for a in state["attempts"]],
             log_counts=scan["counts"], log_examples=scan["examples"], server_timings=timings(err, start))
    last = state["attempts"][-1] if state["attempts"] else {}
    if state["status"] == "awaiting_approval":
        r["approval_digest"] = last.get("digest")
    r.pop("stdout", None)
    return r


def run(label, context, parallel, max_queue=512, max_tokens=DEFAULT_MAX_TOKENS, tasks=TASKS, port=11437, note="", out_root=None):
    root = Path(out_root).resolve() if out_root else OUT
    out = root / label
    out.mkdir(parents=True, exist_ok=True)
    svc = OllamaWindows(port, context, parallel, max_queue)
    doc = {"label": label, "at_utc": now(), "note": note,
           "requested": {"model": MODEL, "context": context, "parallel": parallel, "max_queue": max_queue, "max_tokens": max_tokens},
           "gpu_before": gpu()}
    if running_matches(svc):
        doc["restart"] = {"skipped": "server already running with exactly these settings"}
    else:
        doc["restart"] = svc.restart()
    rec = svc.launch_record()
    health = check(svc.base_url, MODEL, pid=svc.pid(), disk_path=runtime_dir())  # the drive holding models and logs
    (out / "health.json").write_text(json.dumps(health, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    eff = effective_settings(rec)
    res = health["checks"].get("residency", {})
    doc["service"] = {
        "status": health["status"], "layers": {k: v.get("ok") for k, v in health["checks"].items()},
        "golden": [(g["id"], g.get("answer"), g["ok"], g["seconds"]) for g in health["checks"].get("model", {}).get("golden", [])],
        "residency": res, "gpu_after_load": gpu(),
        "launch_record_file": next((str(p.relative_to(ROOT)) for p in sorted(svc.evidence_dir.glob(f"ollama-launch-{port}-*.json"))[-1:]), None),
        "effective": eff,
        "ok": health["status"] == "healthy" and str(res.get("context_length")) == str(context) and eff["n_ctx_seq"] == str(context)
              and eff["n_seq_max"] == str(parallel) and "library=CUDA" in (eff["inference_compute"] or ""),
    }
    doc["generation"] = {}
    for task in tasks:
        doc["generation"][task] = run_task(task, svc, context, max_tokens, out / "runs")
    doc["gpu_end"] = gpu()
    doc["server_log"] = ollama_log.log_pair(rec)[0].name
    (out / "summary.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    # Keep the server logs with the evidence (the runtime prunes old logs); one shared copy per server launch.
    logs = root / "server-logs"
    logs.mkdir(exist_ok=True)
    for path in ollama_log.log_pair(rec):
        if Path(path).exists():
            (logs / Path(path).name).write_text(Path(path).read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return doc
