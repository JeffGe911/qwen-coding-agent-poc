"""python -m regression_triage <command>

run       run one regression manifest (hdl/regressions/...) through the restricted executor
triage    triage one log with the rule baseline (and optionally the local model); writes JSON + a Markdown report
review    record an engineer's decision for one test of a triage and re-render the report
eval      score an engine on a frozen dataset split (refuses when the data, gold or code differ from the contract)
demo      end to end: run a mixed regression, triage it, write the report pending review
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from . import backend, evaluate, logio, model, regress, report, rules

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence" / "regression-triage"
CODE = ("regression_triage/rules.py", "regression_triage/model.py", "regression_triage/evaluate.py", "regression_triage/logio.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def model_settings(args):
    return backend.load(args.backend)


def run_engine(engine, log, settings):
    if engine == "rules":
        t0 = time.monotonic()
        result = rules.triage(log)
        return {"status": "ok", "seconds": round(time.monotonic() - t0, 4)}, result, None
    call, raw = model.triage(log, settings)
    return {k: v for k, v in call.items() if k != "triage"}, call.get("triage"), raw


def cmd_triage(args):
    root = Path(args.root).resolve()
    log = logio.read_log(args.log, root)
    out = Path(args.out)
    for engine in (["rules", "qwen"] if args.engine == "both" else [args.engine]):
        call, result, raw = run_engine(engine, log, model_settings(args))
        if result is None:
            result = {"engine": engine, "file": log.name, "log_status": "unknown_format", "tests": [], "flags": [], "notes": [f"model call {call['status']}: {call.get('problems') or call.get('error')}"]}
        doc = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "log": {"name": log.name, "sha256": log.sha256, "root": str(root)},
               "triage": result, "model_call": call if engine != "rules" else None, "reviews": []}
        stem = Path(log.name).stem + f".{engine}"
        write(out / f"{stem}.json", doc)
        if raw is not None:
            write(out / f"{stem}.model-response.json", raw)
        (out / f"{stem}.md").write_text(report.render(doc), encoding="utf-8", newline="\n")
        print(out / f"{stem}.md")


def cmd_review(args):
    path = Path(args.triage)
    doc = json.loads(path.read_text(encoding="utf-8"))
    report.add_review(doc, args.test, args.decision, args.reviewer, args.note)
    write(path, doc)
    path.with_suffix(".md").write_text(report.render(doc), encoding="utf-8", newline="\n")
    print(path.with_suffix(".md"))


def check_contract(contract, split):
    problems = []
    for s in contract["dataset"][split]:
        if sha(EV / s["file"]) != s["sha256"]:
            problems.append(f"{s['file']} changed")
        if sha(EV / s["gold"]) != s["gold_sha256"]:
            problems.append(f"{s['gold']} changed")
    for rel, digest_ in contract["code_sha256"].items():
        if sha(ROOT / rel) != digest_:
            problems.append(f"{rel} changed since the contract was frozen")
    return problems


def cmd_eval(args):
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    problems = check_contract(contract, args.split)
    if problems:
        raise SystemExit("refusing to run: " + "; ".join(problems) + ". Freeze a new contract version instead.")
    if args.engine not in contract.get("engines", ["rules", "qwen"]):
        raise SystemExit(f"contract {contract['version']} does not cover engine {args.engine}; freeze a contract version that does")
    if args.engine == "qwen":
        settings = contract["qwen"]["backend"]
        if model.prompt_sha256() != contract["qwen"]["prompt_sha256"]:
            raise SystemExit("prompt/schema differ from the contract; freeze a new contract version")
        problems = backend.identity_problems(settings, backend.identity(settings))
        if problems:
            raise SystemExit(f"backend {settings['name']} does not match the contract: " + "; ".join(problems))
    else:
        settings = None
    out = EV / "results" / f"{contract['version']}-{args.engine}" / args.split
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} already has results; a split is evaluated once per contract version")
    scores = []
    for s in contract["dataset"][args.split]:
        log = logio.read_log(s["file"], EV)
        gold = json.loads((EV / s["gold"]).read_text(encoding="utf-8"))
        call, result, raw = run_engine(args.engine, log, settings)
        score = evaluate.score_sample(result, gold, log) if result is not None else None
        write(out / f"{s['sample_id']}.json", {"sample_id": s["sample_id"], "call": call, "triage": result, "score": score})
        if raw is not None:
            write(out / f"{s['sample_id']}.model-response.json", raw)
        scores.append((s["sample_id"], call, score, gold))
        print(s["sample_id"], call["status"], "" if score is None else sum(t["category_ok"] for t in score["tests"]), "/", len(gold["tests"]), flush=True)
    valid = [x[2] for x in scores if x[2] is not None]
    agg = evaluate.aggregate(valid)
    calls = [x[1] for x in scores]
    agg.update(requests=len(calls), request_failed=sum(c["status"] == "request_failed" for c in calls), invalid_output=sum(c["status"] == "invalid_output" for c in calls),
               scored_samples=len(valid), unscored_samples=[x[0] for x in scores if x[2] is None],
               seconds_total=round(sum(c.get("seconds") or 0 for c in calls), 3),
               prompt_tokens=sum((c.get("usage") or {}).get("prompt_tokens") or 0 for c in calls),
               completion_tokens=sum((c.get("usage") or {}).get("completion_tokens") or 0 for c in calls))
    # A sample the engine could not answer still has gold tests: count them as wrong for the whole-split accuracy.
    gold_tests = sum(len(x[3]["tests"]) for x in scores)
    agg["category_accuracy_all_samples"] = round(sum(t["category_ok"] for x in valid for t in x["tests"]) / gold_tests, 4) if gold_tests else None
    write(out / "metrics.json", {"contract": contract["version"], "engine": args.engine, "split": args.split, "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **agg})
    print(json.dumps(agg, indent=1))


def cmd_run(args):
    out = regress.run_regression(args.manifest, args.out)
    print(out / "regression.log")


def cmd_demo(args):
    out = Path(args.out)
    reg = regress.run_regression(ROOT / "hdl" / "regressions" / "dev" / "d07_mixed.json", out / "runs")
    ns = argparse.Namespace(log=(reg / "regression.log").relative_to(out).as_posix(), root=str(out), out=str(out / "triage"),
                            engine="both" if args.with_model else "rules", backend=args.backend)
    cmd_triage(ns)


def main(argv=None):
    p = argparse.ArgumentParser(prog="regression_triage")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--manifest", required=True); r.add_argument("--out", required=True)
    t = sub.add_parser("triage"); t.add_argument("log"); t.add_argument("--root", required=True, help="folder the log must be inside of")
    t.add_argument("--out", required=True); t.add_argument("--engine", choices=["rules", "qwen", "both"], default="rules")
    v = sub.add_parser("review"); v.add_argument("triage"); v.add_argument("--test", required=True); v.add_argument("--decision", required=True)
    v.add_argument("--reviewer", required=True); v.add_argument("--note", default="")
    e = sub.add_parser("eval"); e.add_argument("--contract", required=True); e.add_argument("--split", choices=["dev", "holdout"], required=True)
    e.add_argument("--engine", choices=["rules", "qwen"], required=True)
    d = sub.add_parser("demo"); d.add_argument("--out", required=True); d.add_argument("--with-model", action="store_true")
    for sp in (t, d):
        sp.add_argument("--backend", default=str(ROOT / "deploy" / "backends" / "ollama-r2.json"),
                        help="backend profile (deploy/backends/*.json): endpoint, model, auth, timeout, context, output budget, sampling")
    args = p.parse_args(argv)
    {"run": cmd_run, "triage": cmd_triage, "review": cmd_review, "eval": cmd_eval, "demo": cmd_demo}[args.cmd](args)


if __name__ == "__main__":
    main()
