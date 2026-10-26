"""Rules first, the model only where the rules cannot decide, and program-enforced guards on what the model may say.

Why (evidence/regression-triage/REPORT-eval-v3.md): the rules never passed a failing test but answered "unknown" for
most logs written in another team's style; the model covered those logs but reported pass twice when the log had no
verdict line, although the prompt forbids it. So a convention that matters for safety is enforced in code, not asked for:
- guard_pass: a pass needs a valid cited line (not a runner line) with a pass word, a run stage the runner saw end
  (when runner lines exist), and no non-zero exit or timeout
  recorded by the runner for that test; otherwise the answer becomes unknown. A lint-only test whose lint stage the
  runner recorded with exit 0 needs no pass word (lint prints statistics, not a verdict);
- normalize_result: a simulation test whose compile or tool start failed did not run (not_run), lint tests excepted;
  a "test_failure" whose own cited lines say watchdog / timeout is a timeout.
combine() keeps every definite rule verdict and fills in the rules' undecided tests (result unknown, which includes
incomplete_log) with the guarded model verdict when that one is definite, marked as coming from the model and needing
review. When the rules found no test at all, the model's tests are used, but only names that occur in the log.

hybrid-v2 changes (from the blind holdout2 run of eval-v4; holdout2 is therefore no longer blind for v2):
undecided = result unknown, not only category unknown; adopt model tests when the rules found none; watchdog/timeout
normalisation; lint exit-0 passes; a pass needs the runner to have recorded the end of the run (added after a
post-hoc check on holdout2 showed per-item "ok" progress lines of a truncated log passing the guard).
"""
import copy
import re

from .model import structure

HYBRID_VERSION = "hybrid-v2"
PASS_WORD = re.compile(r"\b(?:pass(?:ed|es)?|ok|success(?:ful|fully)?)\b", re.I)
TIMEOUT_WORD = re.compile(r"\b(?:watchdog|time-?out|timed out)\b", re.I)
RUNNER_LINE = re.compile(r"^#(?:RUN|OUT)\b")
PLACEHOLDER = "(log)"


def _stages(log):
    return {t["test_id"]: t["stages"] for t in structure(log)["tests"]}


def _clean_lint(stages):
    return bool(stages) and all(s["stage"] == "lint" for s in stages) and all(str(s.get("exit")) == "0" for s in stages)


def guard_pass(t, log, stages):
    """Downgrade a model pass that has no verdict evidence or that the runner's own records contradict."""
    if t["result"] != "pass" and t["category"] != "pass":
        return t
    reasons = []
    st = stages.get(t["test_id"], [])
    if not _clean_lint(st) and not any(PASS_WORD.search(log.line(c["line"]) or "") and not RUNNER_LINE.match(log.line(c["line"]) or "") for c in t["evidence"]):
        reasons.append("没有引用到写明通过的结论行")
    bad = [s for s in st if str(s.get("exit", "0")) not in ("0", "None") or s.get("timed_out") == "true" or s.get("tool_error")]
    if bad:
        reasons.append(f"runner 记录的 {bad[0]['stage']} 阶段退出码为 {bad[0].get('exit')}，或已超时")
    if st and not any(s.get("end_line") for s in st if s["stage"] in ("run", "lint")):
        # a run that never finished cannot have passed; progress lines such as "byte 3 ok" are not a verdict
        reasons.append("runner 没有记录运行阶段结束（日志在测试结束前中断）")
    if reasons:
        t = dict(t, result="unknown", category="unknown", side="undetermined", guard=f"模型判为通过，但{'；'.join(reasons)}，已降为无法判断")
    return t


def normalize_result(t, stages, log=None):
    st = stages.get(t["test_id"])
    if st and t["category"] in ("compile_error", "tool_error") and t["result"] == "fail" and not any(s["stage"] == "lint" for s in st):
        t = dict(t, result="not_run", normalized="仿真测试没有运行起来，结果按约定记为 not_run")
    if log is not None and t["category"] == "test_failure" and any(TIMEOUT_WORD.search(log.line(c["line"]) or "") for c in t["evidence"]):
        t = dict(t, category="timeout", side="design_or_test", normalized="引用的失败行写明是 watchdog / 超时，按约定记为 timeout")
    return t


def guard(model_triage, log):
    """The model's answer with the guards applied (a copy; the raw answer stays in the record)."""
    if not model_triage:
        return None
    out = copy.deepcopy(model_triage)
    stages = _stages(log)
    out["tests"] = [normalize_result(guard_pass(t, log, stages), stages, log) for t in out["tests"]]
    return out


def _from_model(m, test_id, notes):
    return {**m, "test_id": test_id, "source": "model", "notes": notes + ["规则无法判断，采用模型的判断，需工程师复核"]}


def combine(rules_triage, model_triage, log):
    """One triage in the business format: rule verdicts where definite, guarded model verdicts where the rules are undecided."""
    guarded = guard(model_triage, log)
    out = copy.deepcopy(rules_triage)
    out["engine"] = f"hybrid({rules_triage['engine']} + {model_triage['engine'] if model_triage else 'no model answer'})"
    out["hybrid_version"] = HYBRID_VERSION
    known = {t["test_id"] for t in structure(log)["tests"]}
    text = "\n".join(log.lines)
    named = lambda tid: re.search(r"(?<![\w.])" + re.escape(tid) + r"(?![\w])", text) is not None
    # A model test counts only if it is a runner test of this log, or (without runner lines) its name occurs in the log
    # as a whole word, so an invented test name is dropped.
    mt = {t["test_id"]: t for t in (guarded or {}).get("tests", [])
          if not t.get("unmatched") and ((t["test_id"] in known) if known else (t["test_id"] == PLACEHOLDER or named(t["test_id"])))}
    rule_ids = [t["test_id"] for t in out["tests"]]
    found_none = not known and (not out["tests"] or (rule_ids == [PLACEHOLDER] and out["tests"][0]["result"] == "unknown"))
    if found_none and [k for k in mt if k != PLACEHOLDER]:
        # the rules found no test (e.g. runner lines behind CI timestamps): use the model's named tests instead of "(log)"
        notes = out["tests"][0].get("notes", []) if out["tests"] else []
        out["tests"] = [_from_model(m, tid, notes) for tid, m in mt.items() if tid != PLACEHOLDER]
    else:
        if len(out["tests"]) == 1 and len(mt) == 1 and not known:  # raw tool output: one test, named differently by each engine
            mt = {out["tests"][0]["test_id"]: next(iter(mt.values()))}
        for i, t in enumerate(out["tests"]):
            t["source"] = "rules"
            m = mt.get(t["test_id"])
            undecided = t["result"] == "unknown" or t["category"] == "unknown"  # incomplete_log counts; so does unknown/not_run
            if undecided and m and m["category"] != "unknown" and m["result"] != "unknown":
                out["tests"][i] = _from_model(m, t["test_id"], t.get("notes", []))
        for tid in sorted(known - set(rule_ids)):  # a runner test the rules did not report at all
            if tid in mt:
                out["tests"].append(_from_model(mt[tid], tid, []))
    if out["log_status"] == "unknown_format" and guarded and guarded["log_status"] != "unknown_format":
        out["log_status"] = guarded["log_status"]
    out["model_needed"] = any(t["source"] == "model" for t in out["tests"]) or any("unknown" in (t["result"], t["category"]) for t in rules_triage["tests"])
    return out
