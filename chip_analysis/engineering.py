"""Daily engineering tasks: merge files, extract log failures, daily summary, run diff, review list."""
from collections import Counter
import csv
import re
from pathlib import Path

from .metrics import chip_outcomes, record_pass_rate, results, yield_table

MERGED_FIELDS = ["source_file", "source_line", "lot_id", "wafer_id", "die_id", "chip_key", "test_item", "value", "unit", "lower", "upper",
                 "status", "test_time", "retest", "run_id", "test_program", "raw_value", "raw_unit", "flags"]
LOG_FAIL = re.compile(r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\w+\s+(?P<lot>\S+)\s+(?P<wafer>W\d+)\s+(?P<die>D\d+)\s+"
                      r"retest=(?P<retest>\d+)\s+(?P<item>[A-Z_]+)=(?P<value>-?[\d.]+)(?P<unit>\S*?)\s+FAIL(?:\s+limit=\[(?P<lo>[^,\]]*),(?P<hi>[^\]]*)\])?\s*$")


def write_rows(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (";".join(str(x) for x in v) if isinstance(v, list) else v) for k, v in row.items()})
    return path


def merge(clean, out_csv):
    """Unified, unit-normalized table; every row keeps source_file + source_line."""
    return write_rows(out_csv, MERGED_FIELDS, clean)


def extract_log_failures(log_path):
    failures, unparsed = [], []
    for line_no, line in enumerate(Path(log_path).read_text(encoding="utf-8").splitlines(), start=1):
        if " FAIL" not in line:
            continue
        m = LOG_FAIL.match(line)
        if m:
            d = m.groupdict()
            failures.append({"source_file": Path(log_path).name, "source_line": line_no, "time": d["time"], "lot_id": d["lot"], "wafer_id": d["wafer"],
                             "die_id": d["die"], "retest": int(d["retest"]), "test_item": d["item"], "value": float(d["value"]), "unit": d["unit"],
                             "lower": d["lo"], "upper": d["hi"], "raw_line": line})
        else:
            unparsed.append({"source_file": Path(log_path).name, "source_line": line_no, "raw_line": line, "reason": "FAIL line does not match the expected format"})
    by_item = Counter(f["test_item"] for f in failures)
    return {"failures": failures, "unparsed": unparsed, "fail_lines_by_item": dict(by_item.most_common())}


def daily_summary(clean, spec, date, top_n=5):
    day = [r for r in clean if (r["test_time"] or "").startswith(date)]
    finals = results(day, "final")
    final_chips, first_chips = chip_outcomes(day, spec, "final"), chip_outcomes(day, spec, "first")
    fails = Counter(item for (run, chip, item), e in finals.items() if e["status"] == "FAIL")
    return {"date": date, "rows": len(day), "runs": sorted({r["run_id"] for r in day}), "programs": sorted({r["test_program"] for r in day}),
            "lots": sorted({r["lot_id"] for r in day}), "record_pass_rate": record_pass_rate(day, ("run_id",)),
            "chip_yield": yield_table(final_chips, first_chips, ("run_id", "lot_id")),
            "top_failing_items": [{"test_item": k, "final_fail_chips": v} for k, v in fails.most_common(top_n)]}


def daily_markdown(summary):
    lines = [f"# 每日测试汇总 {summary['date']}（合成数据）", "", f"- 行数：{summary['rows']}；运行：{', '.join(summary['runs']) or '无'}；程序：{', '.join(summary['programs']) or '无'}；批次：{', '.join(summary['lots']) or '无'}", ""]
    lines += ["| 运行 | 批次 | 芯片 | PASS | FAIL | INCOMPLETE | 良率(全部) | 良率(仅完整) | 首测良率(全部) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    lines += [f"| {r['run_id']} | {r['lot_id']} | {r['chips']} | {r['pass']} | {r['fail']} | {r['incomplete']} | {r['yield_all']} | {r['yield_complete_only']} | {r['first_pass_yield_all']} |" for r in summary["chip_yield"]]
    lines += ["", "失败最多的项目（最终结果 FAIL 的芯片数）：" + ("、".join(f"{x['test_item']} {x['final_fail_chips']}" for x in summary["top_failing_items"]) or "无")]
    lines += ["", "口径见报告“指标假设”。良率未采用任何公司官方定义。"]
    return "\n".join(lines) + "\n"


def compare_runs(clean, base_run, new_run, lots=None):
    """Chip-item final status diff between two runs, restricted to chip-items present in both."""
    finals = results(clean, "final")
    base = {(c, i): e for (r, c, i), e in finals.items() if r == base_run and (not lots or c.split("/")[0] in lots)}
    new = {(c, i): e for (r, c, i), e in finals.items() if r == new_run and (not lots or c.split("/")[0] in lots)}
    rows = []
    for key in sorted(set(base) | set(new)):
        b, n = base.get(key), new.get(key)
        bs, ns = (b or {}).get("status", "ABSENT"), (n or {}).get("status", "ABSENT")
        if bs == ns:
            continue
        change = ("new_failure" if ns == "FAIL" and bs == "PASS" else "fixed" if bs == "FAIL" and ns == "PASS"
                  else "only_in_new" if bs == "ABSENT" else "only_in_base" if ns == "ABSENT" else "other_change")
        rows.append({"chip_key": key[0], "test_item": key[1], "change": change, f"{base_run}_status": bs, f"{new_run}_status": ns,
                     f"{base_run}_value": b["record"]["value"] if b else None, f"{new_run}_value": n["record"]["value"] if n else None,
                     f"{base_run}_source": f"{b['record']['source_file']}:{b['record']['source_line']}" if b else "",
                     f"{new_run}_source": f"{n['record']['source_file']}:{n['record']['source_line']}" if n else ""})
    counts = Counter(r["change"] for r in rows)
    return {"base_run": base_run, "new_run": new_run, "lots": lots, "overlap_chip_items": len(set(base) & set(new)), "counts": dict(counts), "rows": rows}


def review_list(issues, rules=None, min_severity="warn"):
    """Rows needing human review, filtered by explicit rule ids or by severity."""
    order = {"info": 0, "warn": 1, "error": 2}
    picked = [i for i in issues if "source_line" in i and (i["rule"] in rules if rules else order[i["severity"]] >= order[min_severity])]
    return sorted(picked, key=lambda i: (-order[i["severity"]], i["source_file"], i["source_line"], i["rule"]))
