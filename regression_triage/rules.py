"""Deterministic rule baseline for regression-log triage (no model).

Per test: result, category, side (design/test vs infrastructure), cited evidence lines, a failure fingerprint and a
suggestion that quotes its evidence. Principles:
- an exit code of 0 is not a pass; a pass needs a verdict line and no failure evidence;
- error-looking words count only in anchored forms (ERROR:/FATAL: at line start, file:line: error, %Error, UVM_ERROR <loc> @);
- the first compile error is the root cause, later ones are treated as follow-on;
- a compiler's own crash ("Assertion failed: ..., file pform.cc") is not a design assertion;
- tool output that imitates runner lines arrives escaped as "#OUT #RUN" and is never trusted;
- missing fields, truncation and unknown formats are reported as such, never guessed.
"""
import hashlib
import re

RULES_VERSION = "rules-v1"
CATEGORIES = ("pass", "compile_error", "test_failure", "timeout", "tool_error", "incomplete_log", "unknown")
RESULTS = ("pass", "fail", "not_run", "unknown")
SIDES = ("none", "design_or_test", "infrastructure", "undetermined")

RUN = re.compile(r"^#RUN (.*)$")
KV = re.compile(r'(\w+)=("([^"]*)"|\S+)')
COMPILE_ERR = re.compile(r"^(?P<src>[\w./\\-]+\.s?v):(?P<line>\d+): (?:syntax error|error:)")
VL_ERR = re.compile(r"^%Error: (?P<src>[^:\s]+\.s?v):(?P<line>\d+)(?::\d+)?: ")
VL_SETUP = re.compile(r"^%Error: Cannot find .*(?:built-in|verilated_)")
TOOL_INTERNAL = re.compile(r"^Assertion failed: .*, file \S+\.(?:cc|cpp|c), line \d+")
GIVE_UP = re.compile(r"^I give up\.")
FATAL = re.compile(r"^FATAL: ")
ERROR = re.compile(r"^ERROR: ")
LOCATED = re.compile(r"^(?:ERROR|FATAL): \S+\.s?v:\d+: ")
WATCHDOG = re.compile(r"timeout|watchdog", re.I)
PASSED = re.compile(r"^TEST PASSED\b:?\s*(?P<name>[A-Za-z_]\w*)?")
FAILED = re.compile(r"^TEST FAILED\b:?\s*(?P<name>[A-Za-z_]\w*)?")
UVM_TEST = re.compile(r"Running test (?P<name>[A-Za-z_]\w*)")
UVM_MSG = re.compile(r"^UVM_(?:ERROR|FATAL) \S+\(\d+\) @ ")
UVM_COUNT = re.compile(r"^UVM_(?:ERROR|FATAL) :\s+(?P<n>\d+)")
UVM_ANY = re.compile(r"^UVM_(?:INFO|WARNING|ERROR|FATAL)\b")
LICENSE = re.compile(r"license checkout failed|without a license", re.I)
STATUS_HINT = re.compile(r"status=\d+|exit(?:ed)? (?:code|status)|returned \d+", re.I)
INJECTION = re.compile(r"ignore (?:all )?(?:previous|prior) instructions|note to the ai|system override|triage model must", re.I)
SIDE = {"pass": "none", "compile_error": "design_or_test", "test_failure": "design_or_test", "timeout": "design_or_test", "tool_error": "infrastructure",
        "incomplete_log": "infrastructure", "unknown": "undetermined"}


def cite(log, n):
    return {"file": log.name, "line": n, "quote": log.line(n).strip()[:200]}


def fingerprint(category, text):
    s = text.lower()
    s = re.sub(r"0x[0-9a-f]+", "H", s)
    s = re.sub(r"\d+", "N", s)
    s = re.sub(r"[\w.-]*[/\\]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return f"{category}:{hashlib.sha1(s.encode()).hexdigest()[:8]}"


def verdict(test_id, category, result, evidence, log, kind=None, notes=(), certainty="confirmed", side=None):
    first = log.line(evidence[0]["line"]) if evidence else ""
    return {"test_id": test_id, "result": result, "category": category, "side": side or SIDE[category], "kind": kind,
            "evidence": evidence, "fingerprint": fingerprint(category, first) if evidence and category != "pass" else None,
            "certainty": certainty, "notes": list(notes)}


def judge_output(test_id, log, nums, exit_code=None, exit_known=True, timed_out=False, stage_end=None):
    """Verdict for simulation output lines nums (physical line numbers)."""
    fatal = [n for n in nums if FATAL.match(log.line(n))]
    errors = [n for n in nums if ERROR.match(log.line(n))]
    failed = [n for n in nums if FAILED.match(log.line(n))]
    passed = [n for n in nums if PASSED.match(log.line(n))]
    notes = []
    if passed and (errors or fatal or failed):
        notes.append("contradictory verdict lines: TEST PASSED is printed but failure evidence follows; failure evidence wins")
    if timed_out:
        ev = [cite(log, stage_end)] if stage_end else []
        return verdict(test_id, "timeout", "fail", ev, log, kind="wallclock", side="undetermined",
                       notes=notes + ["killed by the runner's wall-clock limit; output written before the kill may be lost"])
    watch = [n for n in errors if WATCHDOG.search(log.line(n))]
    if watch:
        return verdict(test_id, "timeout", "fail", [cite(log, n) for n in watch + failed[:1]], log, kind="watchdog", notes=notes)
    if fatal or errors or failed:
        first = (fatal or errors or failed)
        kind = "assertion" if fatal or any(LOCATED.match(log.line(n)) for n in errors) else "self_check"
        lines = (fatal + errors)[:3] + failed[:1]
        return verdict(test_id, "test_failure", "fail", [cite(log, n) for n in sorted(set(lines))], log, kind=kind,
                       notes=notes + ([f"{len(errors)} ERROR lines"] if len(errors) > 3 else []))
    if exit_known and exit_code not in (0, None):
        return verdict(test_id, "unknown", "fail", [cite(log, stage_end)] if stage_end else [], log, certainty="insufficient_evidence",
                       notes=[f"simulator exited {exit_code} without an error or verdict line"])
    if passed:
        return verdict(test_id, "pass", "pass", [cite(log, passed[0])], log,
                       notes=[] if exit_known else ["exit code not recorded; pass based on the testbench verdict line"])
    ev = [cite(log, n) for n in nums[-2:]] + ([cite(log, stage_end)] if stage_end else [])
    return verdict(test_id, "unknown", "unknown", ev, log, certainty="insufficient_evidence",
                   notes=["no TEST PASSED/FAILED line and no error line" + ("; exit code missing" if not exit_known else "; exit code 0 alone is not a pass")])


def judge_compile(test_id, log, nums, exit_code, stage_end, lint=False):
    design = [n for n in nums if COMPILE_ERR.match(log.line(n)) or VL_ERR.match(log.line(n))]
    setup = [n for n in nums if VL_SETUP.match(log.line(n))]
    internal = [n for n in nums if TOOL_INTERNAL.match(log.line(n))]
    flags = (["tool_setup_error"] if setup else []) + (["tool_internal_assertion"] if internal else [])
    notes = []
    if internal:
        notes.append(f"line {internal[0]}: the compiler itself crashed after the errors (internal assertion), not a design assertion")
    if setup:
        notes.append("the tool could not find its own built-in files (installation/environment problem) - fix that as well")
    if design:
        if len(design) > 1:
            notes.append(f"{len(design) - 1} further errors are probably follow-on errors of the first one")
        v = verdict(test_id, "compile_error", "fail" if lint else "not_run", [cite(log, design[0])], log, notes=notes)
    elif setup:
        v = verdict(test_id, "tool_error", "not_run", [cite(log, n) for n in setup[:2]], log, notes=notes)
    elif not nums:
        v = verdict(test_id, "tool_error", "not_run", [cite(log, stage_end)], log,
                    notes=[f"compiler exited {exit_code} without printing anything - the tool did not run properly"])
    else:
        v = verdict(test_id, "unknown", "not_run", [cite(log, n) for n in nums[:2]], log, certainty="insufficient_evidence",
                    notes=[f"{'lint' if lint else 'compile'} exited {exit_code}; no recognisable error line"])
    v["flags"] = flags
    return v


def parse_runner(log):
    tests, order, flags, header, ended = {}, [], [], None, False
    current = None
    for n, line in enumerate(log.lines, 1):
        if line.startswith("#OUT #RUN"):
            flags.append(("forged_runner_line", n))
        if INJECTION.search(line):
            flags.append(("prompt_injection_text", n))
        m = RUN.match(line)
        if not m:
            if current:
                current["out"].append(n)
            continue
        kv = {k: (q if q is not None and v.startswith('"') else v) for k, v, q in KV.findall(m.group(1))}
        if "regression" in kv and " end " in f" {m.group(1)} ":
            ended, current = True, None
        elif "regression" in kv:
            header = (n, kv)
        elif "test" in kv and "stage" in kv:
            t = tests.setdefault(kv["test"], {"stages": {}})
            if kv["test"] not in order:
                order.append(kv["test"])
            st = t["stages"].setdefault(kv["stage"], {"start": None, "end": None, "out": [], "kv": {}})
            if "cmd" in kv:
                st["start"], current = n, st
            else:
                st["end"], st["kv"], current = n, kv, None
    return tests, order, flags, header, ended


def judge_runner(log):
    tests, order, raw_flags, header, ended = parse_runner(log)
    results, missing = [], []
    if not header or "run_id" not in header[1]:
        missing.append("regression header without run_id")
    for tid in order:
        stages = tests[tid]["stages"]
        comp = stages.get("compile") or stages.get("lint")
        run = stages.get("run")
        lint = "lint" in stages
        tool_err = next((s for s in stages.values() if "tool_error" in s["kv"]), None)
        if tool_err:
            results.append(verdict(tid, "tool_error", "not_run", [cite(log, tool_err["end"])], log, notes=["the simulator executable could not be started"]))
            continue
        if not comp or comp["end"] is None:
            results.append(verdict(tid, "incomplete_log", "unknown", [cite(log, comp["start"])] if comp and comp["start"] else [], log,
                                   certainty="insufficient_evidence", notes=["compile stage has no end record"]))
            continue
        if "exit" not in comp["kv"]:
            missing.append(f"{tid}: compile end without exit code")
        cexit = int(comp["kv"].get("exit", "0"))
        if cexit != 0:
            results.append(judge_compile(tid, log, comp["out"], cexit, comp["end"], lint))
            continue
        if lint:
            results.append(verdict(tid, "pass", "pass", [cite(log, comp["end"])], log, notes=["lint exited 0"]))
            continue
        if not run or run["start"] is None:
            results.append(verdict(tid, "incomplete_log", "unknown", [cite(log, comp["end"])], log, certainty="insufficient_evidence",
                                   notes=["compiled but no run stage recorded"]))
            continue
        if run["end"] is None:
            v = judge_output(tid, log, run["out"], exit_known=False)
            if v["category"] in ("test_failure", "timeout"):
                v["notes"].append("run stage has no end record (log cut off); the failure lines above are conclusive")
                results.append(v)
            else:
                results.append(verdict(tid, "incomplete_log", "unknown", [cite(log, n) for n in run["out"][-1:]] or [cite(log, run["start"])], log,
                                       certainty="insufficient_evidence", notes=["run stage has no end record (log cut off)"]))
            continue
        exit_known = "exit" in run["kv"]
        if not exit_known:
            missing.append(f"{tid}: run end without exit code")
        results.append(judge_output(tid, log, run["out"], int(run["kv"]["exit"]) if exit_known else None, exit_known,
                                    run["kv"].get("timed_out") == "true", run["end"]))
    flags = sorted({f for f, _ in raw_flags})
    if missing:
        flags.append("missing_fields")
    for r in results:
        flags.extend(r.pop("flags", []))
    status = "complete" if ended and not missing and all(r["category"] != "incomplete_log" for r in results) else "incomplete"
    if not ended:
        flags.append("no_regression_end_record")
    notes = [f"missing: {m}" for m in missing]
    return status, results, sorted(set(flags)), notes


def judge_raw(log):
    """Logs without runner annotations: raw compiler/simulator output, UVM-style reports, tool failures, unknown text."""
    nums = list(range(1, len(log.lines) + 1))
    flags = sorted({"prompt_injection_text" for n in nums if INJECTION.search(log.line(n))})
    text = [log.line(n) for n in nums]
    if any(COMPILE_ERR.match(t) or VL_ERR.match(t) or GIVE_UP.match(t) or VL_SETUP.match(t) for t in text):
        v = judge_compile("(log)", log, nums, None, None, lint=any(t.startswith("%Error") for t in text))
        flags += v.pop("flags", [])
        return "complete", [v], sorted(set(flags)), ["raw compiler output: exit code not in the log"]
    if any(UVM_ANY.match(t) for t in text):
        name = next((UVM_TEST.search(t).group("name") for t in text if UVM_TEST.search(t)), "(log)")
        msgs = [n for n in nums if UVM_MSG.match(log.line(n))]
        counts = [n for n in nums if UVM_COUNT.match(log.line(n)) and int(UVM_COUNT.match(log.line(n)).group("n")) > 0]
        if msgs or counts:
            return "complete", [verdict(name, "test_failure", "fail", [cite(log, n) for n in (msgs[:2] + counts[:1])], log, kind="uvm_report")], flags, []
        summary = any("UVM Report Summary" in t for t in text)
        if summary:
            return "complete", [verdict(name, "pass", "pass", [cite(log, n) for n in nums if UVM_COUNT.match(log.line(n))][:1], log,
                                        notes=["UVM summary shows 0 errors and 0 fatals"])], flags, []
        return "incomplete", [verdict(name, "incomplete_log", "unknown", [cite(log, nums[-1])], log, certainty="insufficient_evidence",
                                      notes=["UVM log without a report summary"])], flags, []
    lic = [n for n in nums if LICENSE.search(log.line(n))]
    if lic:
        return "complete", [verdict("(log)", "tool_error", "not_run", [cite(log, n) for n in lic[:2]], log, notes=["license/tool start-up failure"])], flags, []
    markers = [n for n in nums if PASSED.match(log.line(n)) or FAILED.match(log.line(n)) or ERROR.match(log.line(n)) or FATAL.match(log.line(n))]
    if markers:
        name = next(((PASSED.match(log.line(n)) or FAILED.match(log.line(n))).group("name") for n in nums
                     if (PASSED.match(log.line(n)) or FAILED.match(log.line(n))) and (PASSED.match(log.line(n)) or FAILED.match(log.line(n))).group("name")), "(log)")
        v = judge_output(name, log, nums, exit_known=False)
        return "complete", [v], flags, ["raw simulator output: exit code not in the log"]
    hint = [n for n in nums if STATUS_HINT.search(log.line(n))]
    return "unknown_format", [verdict("(log)", "unknown", "unknown", [cite(log, n) for n in hint[:2]], log, certainty="insufficient_evidence",
                                      notes=["no simulator, compiler or test-framework lines recognised"])], flags, []


SUGGEST = {
    "compile_error": "先修第一条编译错误 {loc}：“{quote}”。之后的报错多半是它引起的连锁报错，修完再重新编译。",
    "test_failure": "testbench 检查失败，首条证据 {loc}：“{quote}”。对照期望值与实际值，查看相关信号在报告时刻附近的驱动和时序。",
    "timeout_watchdog": "testbench 的 watchdog 触发 {loc}：“{quote}”。DUT 没有在规定时间内响应，优先检查握手信号、复位和计数器是否推进。",
    "timeout_wallclock": "仿真被 runner 的墙钟时限强制结束 {loc}，没有留下 testbench 输出。可能是 testbench 缺少 $finish/watchdog、DUT 死循环，或时限设置过小；先确认 testbench 会自行结束。",
    "tool_error": "工具没有正常运行 {loc}：“{quote}”。这是环境问题，不是设计问题：检查仿真器安装路径、环境变量和许可证。",
    "incomplete_log": "日志不完整 {loc}，缺少结束记录，不能据此判断结果。请重新运行，或检查日志采集和存储是否中断。",
    "unknown": "证据不足，无法判断 {loc}。需要完整的日志（含退出码和 testbench 结论行）或人工查看。",
    "pass": "通过 {loc}：“{quote}”。",
}


def suggestion(v):
    if not v["evidence"]:
        return SUGGEST[v["category"]].format(loc="（日志中没有可引用的行）", quote="")
    e = v["evidence"][0]
    key = f"timeout_{v['kind']}" if v["category"] == "timeout" else v["category"]
    return SUGGEST[key].format(loc=f"{e['file']}:{e['line']}", quote=e["quote"])


def triage(log):
    if log.empty:
        status, tests, flags, notes = "empty", [verdict("(log)", "incomplete_log", "unknown", [], log, certainty="insufficient_evidence",
                                                        notes=["empty log file"])], [], []
    elif any(RUN.match(line) for line in log.lines):
        status, tests, flags, notes = judge_runner(log)
    else:
        status, tests, flags, notes = judge_raw(log)
    groups = {}
    for t in tests:
        t["suggestion"] = suggestion(t)
        if t["fingerprint"]:
            g = groups.setdefault(t["fingerprint"], {"fingerprint": t["fingerprint"], "category": t["category"], "tests": [], "example": t["evidence"][0]})
            g["tests"].append(t["test_id"])
    dup = [g for g in groups.values() if len(g["tests"]) > 1]
    if dup:
        flags = sorted(set(flags) | {"duplicate_failures"})
    return {"engine": RULES_VERSION, "file": log.name, "sha256": log.sha256, "lines": len(log.lines), "log_status": status,
            "tests": tests, "groups": list(groups.values()), "flags": flags, "notes": notes}
