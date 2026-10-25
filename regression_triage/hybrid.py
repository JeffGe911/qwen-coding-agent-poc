"""Rules first, the model only where the rules cannot decide, and program-enforced guards on what the model may say.

Why (evidence/regression-triage/REPORT-eval-v3.md): the rules never passed a failing test but answered "unknown" for
most logs written in another team's style; the model covered those logs but reported pass twice when the log had no
verdict line, although the prompt forbids it. So a convention that matters for safety is enforced in code, not asked for:
- guard_pass: a pass needs a valid cited line (not a runner line) with a pass word, and no non-zero exit or timeout
  recorded by the runner for that test; otherwise the answer becomes unknown;
- normalize_result: a simulation test whose compile or tool start failed did not run (not_run), lint tests excepted.
combine() keeps every definite rule verdict and fills in rule "unknown"s with the guarded model verdict, marked as
coming from the model and needing review. The model is only needed when the rules leave something unknown.
"""
import copy
import re

from .model import structure

HYBRID_VERSION = "hybrid-v1"
PASS_WORD = re.compile(r"\b(?:pass(?:ed|es)?|ok|success(?:ful|fully)?)\b", re.I)
RUNNER_LINE = re.compile(r"^#(?:RUN|OUT)\b")


def _stages(log):
    return {t["test_id"]: t["stages"] for t in structure(log)["tests"]}


def guard_pass(t, log, stages):
    """Downgrade a model pass that has no verdict evidence or that the runner's own records contradict."""
    if t["result"] != "pass" and t["category"] != "pass":
        return t
    reasons = []
    if not any(PASS_WORD.search(log.line(c["line"]) or "") and not RUNNER_LINE.match(log.line(c["line"]) or "") for c in t["evidence"]):
        reasons.append("没有引用到写明通过的结论行")
    bad = [s for s in stages.get(t["test_id"], []) if str(s.get("exit", "0")) not in ("0", "None") or s.get("timed_out") == "true" or s.get("tool_error")]
    if bad:
        reasons.append(f"runner 记录的 {bad[0]['stage']} 阶段退出码为 {bad[0].get('exit')}，或已超时")
    if reasons:
        t = dict(t, result="unknown", category="unknown", side="undetermined", guard=f"模型判为通过，但{'；'.join(reasons)}，已降为无法判断")
    return t


def normalize_result(t, stages):
    st = stages.get(t["test_id"])
    if st and t["category"] in ("compile_error", "tool_error") and t["result"] == "fail" and not any(s["stage"] == "lint" for s in st):
        t = dict(t, result="not_run", normalized="仿真测试没有运行起来，结果按约定记为 not_run")
    return t


def guard(model_triage, log):
    """The model's answer with the guards applied (a copy; the raw answer stays in the record)."""
    if not model_triage:
        return None
    out = copy.deepcopy(model_triage)
    stages = _stages(log)
    out["tests"] = [normalize_result(guard_pass(t, log, stages), stages) for t in out["tests"]]
    return out


def combine(rules_triage, model_triage, log):
    """One triage in the business format: rule verdicts where definite, guarded model verdicts where the rules say unknown."""
    guarded = guard(model_triage, log)
    out = copy.deepcopy(rules_triage)
    out["engine"] = f"hybrid({rules_triage['engine']} + {model_triage['engine'] if model_triage else 'no model answer'})"
    out["hybrid_version"] = HYBRID_VERSION
    known = {t["test_id"] for t in structure(log)["tests"]}
    mt = {t["test_id"]: t for t in (guarded or {}).get("tests", []) if not t.get("unmatched") and (not known or t["test_id"] in known)}
    if len(out["tests"]) == 1 and len(mt) == 1 and not known:  # raw tool output: one test, named differently by each engine
        mt = {out["tests"][0]["test_id"]: next(iter(mt.values()))}
    for i, t in enumerate(out["tests"]):
        t["source"] = "rules"
        m = mt.get(t["test_id"])
        if t["category"] == "unknown" and m and m["category"] != "unknown":
            out["tests"][i] = {**m, "test_id": t["test_id"], "source": "model",
                               "notes": t.get("notes", []) + ["规则无法判断，采用模型的判断，需工程师复核"]}
    if out["log_status"] == "unknown_format" and guarded and guarded["log_status"] != "unknown_format":
        out["log_status"] = guarded["log_status"]
    out["model_needed"] = any(t["source"] == "model" for t in out["tests"]) or any(t["category"] == "unknown" for t in rules_triage["tests"])
    return out
