"""Command line entry. Example:
  python -m chip_analysis ask "分析这个目录里的测试 CSV，按批次汇总，找出失败最多的五个项目，并生成报告" --dir data/synthetic/raw --execute
"""
import argparse
import json
from pathlib import Path
import sys

from . import handcheck, synth
from .engineering import compare_runs, daily_markdown, daily_summary, extract_log_failures, merge, review_list, write_rows
from .loader import load_dir, load_items
from .pipeline import analyze, facts
from .quality import check
from .report import render

DEFAULT_URL = "http://127.0.0.1:11437/v1"
DEFAULT_MODEL = "qwen2.5-coder:7b"
REPRO = """# 在项目目录执行（Windows：$py = "..\\..\\work\\.venv\\Scripts\\python.exe"）
python -m chip_analysis synth --out data/synthetic
python -m chip_analysis analyze data/synthetic/raw --items data/synthetic/items.json --logs data/synthetic/logs --hand-check data/handcheck --out evidence/chip-analysis --explain
#   复用已保存的模型输出（不调用模型）：... --reuse-explanation evidence/chip-analysis/explanation_prompt_v3.json
python -m chip_analysis merge data/synthetic/raw --items data/synthetic/items.json --out evidence/chip-analysis/merged.csv
python -m chip_analysis extract-log data/synthetic/logs/tester_R2_2026-10-22.log --out evidence/chip-analysis/log_failures.csv
python -m chip_analysis daily data/synthetic/raw --items data/synthetic/items.json --date 2026-10-22
python -m chip_analysis compare-runs data/synthetic/raw --items data/synthetic/items.json --base R1 --new R2 --lots LOT-A02
python -m chip_analysis review data/synthetic/raw --items data/synthetic/items.json --min-severity error --out evidence/chip-analysis/review_errors.csv
python -m chip_analysis ask "分析这个目录里的测试 CSV，按批次汇总，找出失败最多的五个项目，并生成报告" --dir data/synthetic/raw --items data/synthetic/items.json --execute
python -m pytest -q tests/test_chip_analysis.py"""


def load(args):
    spec = load_items(args.items)
    records, reports = load_dir(args.dir, spec)
    clean, issues, profile = check(records, reports, spec)
    return spec, clean, issues, profile


def run_analyze(directory, items, out, top_n, logs, hand, do_explain, base_url, model, compare_a=None, compare_b=None, paired=False, label="合成数据", reuse=None):
    result = analyze(directory, items, out, top_n, logs, compare_a, compare_b, paired, label)
    hc = handcheck.run(hand) if hand else None
    if hc:
        (Path(out) / "hand_check.json").write_text(json.dumps(hc, indent=2, ensure_ascii=False), encoding="utf-8")
    explanation = None
    if reuse:  # re-check a saved model output with the current checks; no model call
        from .assist import check_explanation
        explanation = json.loads(Path(reuse).read_text(encoding="utf-8"))
        if "parsed" in explanation:
            explanation["checks"], explanation["summary_numbers_not_in_facts"] = check_explanation(explanation["parsed"], facts(result))
        explanation["reused_from"] = str(reuse)
    elif do_explain:
        from .assist import explain
        try:
            explanation = explain(facts(result), base_url, model)
        except (OSError, ValueError) as exc:  # model/API error: report it, never fall back to another service
            explanation = {"error": f"{type(exc).__name__}: {exc}"}
        (Path(out) / "explanation.json").write_text(json.dumps(explanation, indent=2, ensure_ascii=False), encoding="utf-8")
    attempts_file = Path(out) / "explanation_attempts.json"
    attempts = json.loads(attempts_file.read_text(encoding="utf-8"))["attempts"] if attempts_file.exists() else None
    page = render(result, out, explanation, hc, REPRO, attempts)
    summary = {"report": str(page), "yield_by_lot": [{k: r[k] for k in ("run_id", "lot_id", "chips", "yield_all", "yield_complete_only")} for r in result["yield_by_lot"]],
               "top_items": [(r["test_item"], r["final_fail_chips"]) for r in result["top_items"]], "quality_counts": result["quality_counts"],
               "sql_cross_check": {k: result["sql_cross_check"][k] for k in ("record_pass_rate_match", "final_fail_chips_match")}}
    if hc:
        summary["hand_check_all_match"] = all(v["expected"] == v["actual"] for v in hc.values())
    if explanation is not None:
        summary["model_explanation"] = "error: " + explanation["error"] if "error" in explanation else {
            "latency_seconds": explanation["latency_seconds"], "findings": len(explanation["parsed"]["findings"]),
            "numbers_not_in_facts": sorted({n for c in explanation["checks"] for n in c["numbers_not_in_facts"]} | set(explanation["summary_numbers_not_in_facts"]))}
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Chip test-data analysis (local only). Model help is optional and loopback-only.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth", help="generate the SYNTHETIC dataset")
    s.add_argument("--out", default="data/synthetic")
    def data_args(sp, need_dir=True):
        if need_dir:
            sp.add_argument("dir")
        sp.add_argument("--items", default="data/synthetic/items.json")
    a = sub.add_parser("analyze"); data_args(a)
    a.add_argument("--out", default="evidence/chip-analysis"); a.add_argument("--top", type=int, default=5)
    a.add_argument("--logs"); a.add_argument("--hand-check"); a.add_argument("--explain", action="store_true")
    a.add_argument("--compare-a"); a.add_argument("--compare-b"); a.add_argument("--paired", action="store_true")
    a.add_argument("--label", default="合成数据", help="data label printed on every report page")
    a.add_argument("--reuse-explanation", help="saved explanation JSON to re-check and show instead of calling the model")
    a.add_argument("--base-url", default=DEFAULT_URL); a.add_argument("--model", default=DEFAULT_MODEL)
    m = sub.add_parser("merge"); data_args(m); m.add_argument("--out", required=True)
    e = sub.add_parser("extract-log"); e.add_argument("log"); e.add_argument("--out")
    d = sub.add_parser("daily"); data_args(d); d.add_argument("--date", required=True); d.add_argument("--out")
    c = sub.add_parser("compare-runs"); data_args(c); c.add_argument("--base", required=True); c.add_argument("--new", required=True)
    c.add_argument("--lots"); c.add_argument("--out")
    r = sub.add_parser("review"); data_args(r); r.add_argument("--rules"); r.add_argument("--min-severity", default="warn", choices=["info", "warn", "error"]); r.add_argument("--out", required=True)
    h = sub.add_parser("hand-check"); h.add_argument("dir", nargs="?", default="data/handcheck")
    k = sub.add_parser("ask", help="natural-language request -> one fixed command (local Qwen routes, code computes)")
    k.add_argument("request"); k.add_argument("--dir", required=True); k.add_argument("--items", default="data/synthetic/items.json")
    k.add_argument("--logs", default="data/synthetic/logs"); k.add_argument("--out", default="evidence/chip-analysis/ask")
    k.add_argument("--execute", action="store_true", help="run the routed command; without it only the plan is shown")
    k.add_argument("--base-url", default=DEFAULT_URL); k.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args(argv)
    out = lambda obj: print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    try:
        if args.cmd == "synth":
            print(synth.generate(args.out))
        elif args.cmd == "analyze":
            out(run_analyze(args.dir, args.items, args.out, args.top, args.logs, args.hand_check, args.explain, args.base_url, args.model, args.compare_a, args.compare_b, args.paired, args.label, args.reuse_explanation))
        elif args.cmd == "merge":
            spec, clean, issues, profile = load(args)
            print(merge(clean, args.out), f"rows={len(clean)}", f"files={[(f['file'], f['status']) for f in profile['files']]}")
        elif args.cmd == "extract-log":
            res = extract_log_failures(args.log)
            if args.out:
                write_rows(args.out, ["source_file", "source_line", "time", "lot_id", "wafer_id", "die_id", "retest", "test_item", "value", "unit", "lower", "upper", "raw_line"], res["failures"])
            out({"fail_lines": len(res["failures"]), "by_item": res["fail_lines_by_item"], "unparsed": res["unparsed"]})
        elif args.cmd == "daily":
            spec, clean, issues, profile = load(args)
            text = daily_markdown(daily_summary(clean, spec, args.date))
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            print(text)
        elif args.cmd == "compare-runs":
            spec, clean, issues, profile = load(args)
            res = compare_runs(clean, args.base, args.new, args.lots.split(",") if args.lots else None)
            if args.out and res["rows"]:
                write_rows(args.out, list(res["rows"][0]), res["rows"])
            out({k: res[k] for k in ("base_run", "new_run", "lots", "overlap_chip_items", "counts")} | {"rows": res["rows"]})
        elif args.cmd == "review":
            spec, clean, issues, profile = load(args)
            rows = review_list(issues, args.rules.split(",") if args.rules else None, args.min_severity)
            write_rows(args.out, ["severity", "rule", "source_file", "source_line", "run_id", "chip_key", "test_item", "raw_line"], rows)
            out({"rows": len(rows), "file": args.out})
        elif args.cmd == "hand-check":
            res = handcheck.run(args.dir)
            out(res)
            return 0 if all(v["expected"] == v["actual"] for v in res.values()) else 1
        elif args.cmd == "ask":
            from .assist import route
            routed = route(args.request, args.base_url, args.model)
            Path(args.out).mkdir(parents=True, exist_ok=True)
            (Path(args.out) / "route.json").write_text(json.dumps(routed, indent=2, ensure_ascii=False), encoding="utf-8")
            plan = routed["plan"]
            print("Model plan (validated against the command allowlist):")
            out(plan)
            if not args.execute:
                print("Not executed. Re-run with --execute to run this fixed command on", args.dir)
                return 0
            ns = argparse.Namespace(dir=args.dir, items=args.items)
            if plan["command"] == "analyze":
                out(run_analyze(args.dir, args.items, args.out, plan["top_n"], args.logs, None, False, args.base_url, args.model))
            elif plan["command"] == "daily":
                spec, clean, issues, profile = load(ns)
                print(daily_markdown(daily_summary(clean, spec, plan["date"], plan["top_n"])))
            elif plan["command"] == "compare_runs":
                spec, clean, issues, profile = load(ns)
                res = compare_runs(clean, plan["base_run"], plan["new_run"])
                out({k: res[k] for k in ("base_run", "new_run", "overlap_chip_items", "counts")})
            elif plan["command"] == "extract_log":
                for log in sorted(Path(args.logs).glob("*.log")):
                    res = extract_log_failures(log)
                    out({"log": log.name, "fail_lines": len(res["failures"]), "by_item": res["fail_lines_by_item"]})
            elif plan["command"] == "review":
                spec, clean, issues, profile = load(ns)
                rows = review_list(issues)
                write_rows(Path(args.out) / "review_list.csv", ["severity", "rule", "source_file", "source_line", "run_id", "chip_key", "test_item", "raw_line"], rows)
                out({"rows": len(rows), "file": str(Path(args.out) / "review_list.csv")})
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
