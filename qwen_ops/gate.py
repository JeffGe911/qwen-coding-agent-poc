"""Regression gate run before promoting a model/server change and after any rollback.

Automated part (no model code is executed):
  1. health: process, port, API, golden answers, full GPU residency
  2. proposal contract on the frozen tasks: the model returns valid JSON {code, explanation},
     the code passes the AST policy, it is not identical to the buggy original, and the
     request stayed inside the server context window (no silent context shift)
Executing proposals against the frozen pytest stays behind human approval (python -m qwen_agent start/decide).
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from qwen_agent.client import Client
from qwen_agent.policy import PolicyError, validate
from qwen_agent.runner import execute
from qwen_agent.workflow import FILES, TASKS, check_context, visible_feedback

from .health import check, now

GATE_TASKS = ("report_pass_rate", "chip_final_yield")


def proposal_contract(base_url, model, task_id, context_tokens=None):
    task_dir = TASKS / task_id
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    original = (task_dir / "solution.py").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="gate-") as tmp:
        for name in FILES:  # baseline runs only the trusted original code
            shutil.copy(task_dir / name, Path(tmp) / name)
        baseline = execute(tmp, "restricted")
    item = {"task": task_id, "baseline": f"{baseline['passed']}/{baseline['tests']}", "context_tokens": context_tokens}
    started = time.monotonic()
    try:
        response = Client(base_url, model).propose(task, original, (task_dir / "test_visible.py").read_text(encoding="utf-8"), visible_feedback(baseline))
        item["seconds"] = round(time.monotonic() - started, 2)
        item["usage"] = response.get("usage")
        choice = response["choices"][0]
        item["finish_reason"] = choice.get("finish_reason")
        try:
            check_context(response.get("usage"), context_tokens)
            item["context_ok"] = True
        except ValueError as exc:
            item["context_ok"] = False
            item["context_error"] = str(exc)
        proposal = json.loads(choice["message"]["content"])
        item["json_ok"] = isinstance(proposal, dict) and set(proposal) == {"code", "explanation"} and all(isinstance(v, str) for v in proposal.values())
        code = proposal.get("code", "") if isinstance(proposal, dict) else ""
        item["code_sha256"] = hashlib.sha256(code.encode()).hexdigest()
        item["changed"] = code.strip() != original.strip()
        try:
            validate(code)
            item["policy_ok"] = True
        except PolicyError as exc:
            item["policy_ok"] = False
            item["policy_error"] = str(exc)[:200]
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        item.update(seconds=round(time.monotonic() - started, 2), json_ok=False, policy_ok=False, changed=False, error=f"{type(exc).__name__}: {exc}"[:300])
    item["ok"] = bool(item.get("json_ok") and item.get("policy_ok") and item.get("changed") and item.get("context_ok", True))
    return item


def run(base_url, model, pid=None, tasks=GATE_TASKS, ollama=True):
    health = check(base_url, model, pid=pid, ollama=ollama)
    context = health["checks"].get("residency", {}).get("context_length")
    proposals = [proposal_contract(base_url, model, t, context) for t in tasks] if health["checks"].get("api", {}).get("ok") else []
    checks = {"health_status": health["status"], "golden_all_ok": bool(health["checks"].get("model", {}).get("ok")),
              "gpu_fraction": health["checks"].get("residency", {}).get("gpu_fraction"), "context_tokens": context,
              "proposals_ok": all(p["ok"] for p in proposals) if proposals else False,
              "proposals": {p["task"]: p["ok"] for p in proposals}}
    passed = checks["health_status"] == "healthy" and checks["proposals_ok"]
    return {"at_utc": now(), "base_url": base_url, "model": model, "passed": passed, "checks": checks, "health": health, "proposals": proposals,
            "note": "Gate does not execute model code; pytest on proposals needs human approval via the agent."}
