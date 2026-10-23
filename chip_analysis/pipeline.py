"""End-to-end analysis: raw files -> checks -> metrics -> tables, charts, report. Deterministic."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from . import charts, metrics as M
from .engineering import compare_runs, daily_markdown, daily_summary, extract_log_failures, merge, review_list, write_rows
from .loader import load_dir, load_items
from .quality import RULES, check
from .sqlcheck import cross_check


def parse_selection(text):
    return dict(part.split("=", 1) for part in text.split(",")) if text else None


def analyze(data_dir, items_path, out_dir, top_n=5, logs_dir=None, compare_a=None, compare_b=None, paired=None, data_label="合成数据"):
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = load_items(items_path)
    records, reports = load_dir(data_dir, spec)
    clean, issues, profile = check(records, reports, spec)
    finals = M.results(clean, "final")
    final_chips, first_chips = M.chip_outcomes(clean, spec, "final"), M.chip_outcomes(clean, spec, "first")
    for c in final_chips:
        if c["outcome"] == "INCOMPLETE":
            issues.append({"rule": "incomplete_chip", "severity": RULES["incomplete_chip"][0], "chip_key": c["chip_key"], "run_id": c["run_id"],
                           "missing": c["missing_items"]})
    items = M.item_failures(clean, finals)
    runs = sorted({r["run_id"] for r in clean})
    lots_by_run = {run: sorted({r["lot_id"] for r in clean if r["run_id"] == run}) for run in runs}

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_label": data_label,
        "inputs": {"data_dir": str(data_dir), "items": str(items_path), "dataset_note": spec.get("dataset")},
        "profile": profile, "assumptions": M.ASSUMPTIONS,
        "quality_counts": dict(Counter(i["rule"] for i in issues).most_common()),
        "record_pass_rate_by_lot": M.record_pass_rate(clean, ("run_id", "lot_id")),
        "record_pass_rate_by_item": M.record_pass_rate(clean, ("run_id", "test_item")),
        "yield_by_lot": M.yield_table(final_chips, first_chips, ("run_id", "lot_id")),
        "yield_by_wafer": M.yield_table(final_chips, first_chips, ("run_id", "lot_id", "wafer_id")),
        "item_failures": items, "top_items": M.top_items(items, top_n),
        "concentration_lot": M.concentration(finals, clean, ("lot_id",)),
        "concentration_wafer": M.concentration(finals, clean, ("lot_id", "wafer_id")),
        "distributions": M.distributions(clean), "chip_outcomes": final_chips,
    }
    focus = result["top_items"][0]["test_item"] if result["top_items"] else None
    result["trend_item"] = focus
    result["trend"] = M.trend(clean, focus) if focus else []
    if focus:
        panels = []
        for run in runs:
            for lot in lots_by_run[run]:
                rows = [r for r in clean if r["run_id"] == run and r["lot_id"] == lot and r["test_item"] == focus and M.usable(r)]
                uppers = Counter(r["upper"] for r in rows if r["upper"] is not None)
                panels.append({"label": f"{run} · {lot}", "values": [r["value"] for r in rows], "upper": uppers.most_common(1)[0][0] if uppers else None})
        result["histogram"] = {"item": focus, "unit": spec["items"].get(focus, {}).get("unit", ""), "panels": panels}

    # Comparisons: explicit selections win; otherwise first vs last run on the lots they share (paired, same chips).
    if compare_a and compare_b:
        a, b = parse_selection(compare_a), parse_selection(compare_b)
        result["compare"] = {"a": a, "b": b, "paired": bool(paired), "rows": M.compare(clean, spec["required_items"], a, b, bool(paired))}
    if len(runs) >= 2:
        shared = sorted(set(lots_by_run[runs[0]]) & set(lots_by_run[runs[-1]]))
        if shared:
            a, b = {"run_id": runs[0], "lot_id": shared[0]}, {"run_id": runs[-1], "lot_id": shared[0]}
            programs = lambda run: sorted({r["test_program"] for r in clean if r["run_id"] == run})
            result["version_compare"] = {"a": a, "b": b, "programs": {runs[0]: programs(runs[0]), runs[-1]: programs(runs[-1])}, "paired": True,
                                         "rows": M.compare(clean, spec["required_items"], a, b, True)}
        result["run_diff"] = compare_runs(clean, runs[0], runs[-1], shared or None)

    result["sql_cross_check"] = cross_check(clean, result["record_pass_rate_by_lot"], M.top_items(items, 999))

    # Daily engineering outputs.
    merge(clean, out_dir / "merged.csv")
    review = review_list(issues)
    write_rows(out_dir / "review_list.csv", ["severity", "rule", "source_file", "source_line", "run_id", "chip_key", "test_item", "detail", "raw_line"],
               [{**i, "detail": json.dumps({k: v for k, v in i.items() if k not in ("rule", "severity", "source_file", "source_line", "run_id", "chip_key", "test_item", "raw_line")}, ensure_ascii=False)} for i in review])
    result["review_rows"] = len(review)
    write_rows(out_dir / "summary_by_lot.csv", list(result["yield_by_lot"][0]), result["yield_by_lot"]) if result["yield_by_lot"] else None
    write_rows(out_dir / "summary_by_wafer.csv", list(result["yield_by_wafer"][0]), result["yield_by_wafer"]) if result["yield_by_wafer"] else None
    write_rows(out_dir / "summary_by_item.csv", list(items[0]), items) if items else None
    write_rows(out_dir / "record_pass_rate_by_lot.csv", list(result["record_pass_rate_by_lot"][0]), result["record_pass_rate_by_lot"]) if clean else None
    write_rows(out_dir / "top_items.csv", list(result["top_items"][0]), result["top_items"]) if result["top_items"] else None
    if "run_diff" in result and result["run_diff"]["rows"]:
        write_rows(out_dir / "run_diff.csv", list(result["run_diff"]["rows"][0]), result["run_diff"]["rows"])
    result["daily"] = []
    for date in sorted({(r["test_time"] or "")[:10] for r in clean if r["test_time"]}):
        summary = daily_summary(clean, spec, date, top_n)
        (out_dir / f"daily_{date}.md").write_text(daily_markdown(summary), encoding="utf-8")
        result["daily"].append(summary)
    result["logs"] = []
    if logs_dir and Path(logs_dir).exists():
        for log in sorted(Path(logs_dir).glob("*.log")):
            extracted = extract_log_failures(log)
            write_rows(out_dir / f"log_failures_{log.stem}.csv", ["source_file", "source_line", "time", "lot_id", "wafer_id", "die_id", "retest", "test_item", "value", "unit", "lower", "upper", "raw_line"], extracted["failures"])
            result["logs"].append({"file": log.name, "fail_lines": len(extracted["failures"]), "by_item": extracted["fail_lines_by_item"], "unparsed": extracted["unparsed"]})
    (out_dir / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out_dir / "facts.json").write_text(json.dumps(facts(result), indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def facts(result):
    """Compact, already-computed facts for the model. No raw rows."""
    pick = lambda rows, keys: [{k: r.get(k) for k in keys} for r in rows]
    out = {
        "data_label": result["data_label"],
        "rows": {"input": result["profile"]["input_rows"], "after_dedup": result["profile"]["rows_after_dedup"],
                 "empty_files": [f["file"] for f in result["profile"]["files"] if f["status"] == "empty_file"]},
        "quality_counts": result["quality_counts"],
        "record_pass_rate_by_lot": pick(result["record_pass_rate_by_lot"], ("run_id", "lot_id", "pass_rows", "fail_rows", "record_pass_rate")),
        "yield_by_lot": pick(result["yield_by_lot"], ("run_id", "lot_id", "chips", "pass", "fail", "incomplete", "yield_all", "yield_complete_only", "first_pass_yield_all")),
        "top_items": pick(result["top_items"], ("rank", "test_item", "final_fail_chips", "final_fail_rate")),
        "concentration_wafer": result["concentration_wafer"],
        "assumption_ids": [a.split(" ", 1)[0] + " " + a.split(" ", 1)[1][:40] for a in result["assumptions"]],
    }
    if "version_compare" in result:
        v = result["version_compare"]
        out["version_compare"] = {"a": v["a"], "b": v["b"], "programs": v["programs"],
                                  "paired_mean_diff_b_minus_a": {r["test_item"]: r["paired"]["mean_diff"] for r in v["rows"]}}
    if "run_diff" in result:
        out["run_diff"] = {"base_run": result["run_diff"]["base_run"], "new_run": result["run_diff"]["new_run"], "counts": result["run_diff"]["counts"]}
    return out


def build_charts(result):
    out = {}
    if result["top_items"]:
        out["top_items"] = charts.hbar(result["top_items"], "test_item", "final_fail_chips", "最终 FAIL 芯片数（按测试项目）", fmt=lambda v: f"{v:g}")
    if result["yield_by_lot"]:
        groups = [(f"{r['run_id']} · {r['lot_id']}", [r["first_pass_yield_all"], r["yield_all"]]) for r in result["yield_by_lot"]]
        out["yield"] = charts.grouped_hbar(groups, [("首测良率(全部)", "--series-1"), ("最终良率(全部)", "--series-2")], "按运行与批次的良率", lambda v: "-" if v is None else f"{v:.1%}")
    h = result.get("histogram")
    if h and any(p["values"] for p in h["panels"]):
        out["histogram"] = charts.histograms([(p["label"], p["values"], p["upper"]) for p in h["panels"] if p["values"]],
                                             f"{h['item']} 首测值分布", h["unit"])
    if result.get("trend"):
        points = [(t["bucket"][5:], t["median"], f"{t['bucket']} · 中位数 {t['median']} · n={t['n']} · {', '.join(t['lots'])}") for t in result["trend"]]
        out["trend"] = charts.line(points, f"{result['trend_item']} 首测中位数随时间", result["histogram"]["unit"] if result.get("histogram") else "")
    return out
