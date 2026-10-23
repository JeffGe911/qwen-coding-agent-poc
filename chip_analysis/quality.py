"""Data-quality checks. Every rule is explicit; each issue points to source_file:source_line."""
from collections import Counter, defaultdict
import statistics

# Rule id -> (severity, human-readable definition). Reports quote these verbatim.
RULES = {
    "empty_file": ("warn", "文件为 0 字节或只有空内容，已跳过"),
    "duplicate_row": ("warn", "与更早一行在全部规范字段上完全相同（批次、晶圆、芯片、项目、值、单位、上下限、状态、时间、轮次、运行、程序），只保留第一行"),
    "conflicting_measurement": ("error", "同一 运行+芯片+项目+重测轮次 出现内容不同的多行；该芯片项目判为无效"),
    "missing_value": ("error", "测量值为空且状态不是 SKIP"),
    "value_not_numeric": ("error", "测量值无法解析为数字"),
    "missing_status": ("error", "状态为空或不在 PASS/FAIL/SKIP（含 P/F/S）中"),
    "unit_converted": ("info", "单位与该项目的规范单位不同，已按 items.json 中的系数换算（值与上下限一起换算）"),
    "unit_unknown": ("error", "单位无法换算到该项目的规范单位；该行不参与数值统计"),
    "unknown_test_item": ("warn", "测试项目不在 items.json 中"),
    "limit_mismatch": ("warn", "换算后的上下限与该项目在全部数据中最常见的上下限不同"),
    "status_inconsistent": ("error", "记录状态与“下限 <= 值 <= 上限”的重新判定不一致"),
    "implausible_value": ("error", "稳健 z 分数 |0.6745*(x-中位数)/MAD| > 8（按项目，基于全部有效首测值）"),
    "incomplete_chip": ("warn", "芯片缺少某个必测项目的有效最终结果（缺行、SKIP、缺状态或无效）"),
}
ROBUST_Z_LIMIT = 8.0
DEDUP_FIELDS = ("lot_id", "wafer_id", "die_id", "test_item", "raw_value", "raw_unit", "raw_lower", "raw_upper",
                "raw_status", "test_time", "retest", "run_id", "test_program")


def issue(rule, record=None, **detail):
    item = {"rule": rule, "severity": RULES[rule][0]}
    if record is not None:
        item.update(source_file=record["source_file"], source_line=record["source_line"], chip_key=record["chip_key"],
                    run_id=record["run_id"], test_item=record["test_item"], raw_line=record["raw_line"])
    item.update(detail)
    return item


def measurement_key(r):
    return (r["run_id"], r["chip_key"], r["test_item"], r["retest"])


def deduplicate(records):
    seen, kept, issues = {}, [], []
    for r in records:
        key = tuple(r[f] for f in DEDUP_FIELDS)
        if key in seen:
            first = seen[key]
            issues.append(issue("duplicate_row", r, duplicate_of=f"{first['source_file']}:{first['source_line']}"))
            continue
        seen[key] = r
        kept.append(r)
    return kept, issues


def robust_bounds(records):
    """Per item: (median, MAD) over valid first-measurement values."""
    values = defaultdict(list)
    for r in records:
        if r["value"] is not None and r["retest"] == 0 and not any(f.startswith("unit_unknown") for f in r["flags"]):
            values[r["test_item"]].append(r["value"])
    out = {}
    for item, vals in values.items():
        median = statistics.median(vals)
        mad = statistics.median(abs(v - median) for v in vals)
        out[item] = (median, mad)
    return out


def check(records, file_reports, spec):
    """Return (clean_records, issues, profile). clean = deduplicated records; nothing else is dropped."""
    issues = [issue("empty_file", file=f["file"]) for f in file_reports if f["status"] == "empty_file"]
    clean, dup_issues = deduplicate(records)
    issues += dup_issues

    groups = defaultdict(list)
    for r in clean:
        groups[measurement_key(r)].append(r)
    conflicts = {k for k, rows in groups.items() if len(rows) > 1}
    for k in conflicts:
        lines = ", ".join(f"{x['source_file']}:{x['source_line']}" for x in groups[k])
        for r in groups[k]:
            r["flags"].append("conflicting_measurement")
            issues.append(issue("conflicting_measurement", r, lines=lines))

    modal = {}
    by_item = defaultdict(Counter)
    for r in clean:
        if r["lower"] is not None or r["upper"] is not None:
            by_item[r["test_item"]][(r["lower"], r["upper"])] += 1
    for item, counter in by_item.items():
        modal[item] = counter.most_common(1)[0][0]

    bounds = robust_bounds(clean)
    for r in clean:
        for flag in r["flags"]:
            if flag.startswith("unit_converted"):
                issues.append(issue("unit_converted", r, conversion=flag.split(":", 1)[1]))
            elif flag.startswith("unit_unknown"):
                issues.append(issue("unit_unknown", r, unit=flag.split(":", 1)[1]))
            elif flag in ("unknown_test_item", "value_not_numeric"):
                issues.append(issue(flag, r))
        if r["status"] is None:
            issues.append(issue("missing_status", r, raw_status=r["raw_status"]))
        if r["value"] is None and r["status"] != "SKIP" and "value_not_numeric" not in r["flags"] and not any(f.startswith("unit_unknown") for f in r["flags"]):
            issues.append(issue("missing_value", r))
        if r["test_item"] in modal and (r["lower"], r["upper"]) != modal[r["test_item"]] and (r["lower"] is not None or r["upper"] is not None):
            issues.append(issue("limit_mismatch", r, limits=[r["lower"], r["upper"]], modal_limits=list(modal[r["test_item"]])))
        if r["value"] is not None and r["status"] in ("PASS", "FAIL") and r["lower"] is not None and r["upper"] is not None:
            expected = "PASS" if r["lower"] <= r["value"] <= r["upper"] else "FAIL"
            if expected != r["status"]:
                r["flags"].append("status_inconsistent")
                issues.append(issue("status_inconsistent", r, recorded=r["status"], by_limits=expected))
        if r["value"] is not None and r["test_item"] in bounds:
            median, mad = bounds[r["test_item"]]
            if mad > 0:
                z = 0.6745 * (r["value"] - median) / mad
                if abs(z) > ROBUST_Z_LIMIT:
                    r["flags"].append("implausible_value")
                    issues.append(issue("implausible_value", r, robust_z=round(z, 1)))

    keys = Counter(measurement_key(r) for r in clean)
    profile = {
        "input_rows": len(records),
        "rows_after_dedup": len(clean),
        "files": file_reports,
        "row_grain": "一行 = 一次测量：某运行中某颗芯片的某个测试项目在某个重测轮次的结果",
        "grain_check": {"distinct_measurement_keys": len(keys), "keys_with_multiple_rows": len(conflicts),
                        "grain_holds": len(conflicts) == 0},
        "chips": len({r["chip_key"] for r in clean}),
        "runs": sorted({r["run_id"] for r in clean}),
        "items_seen": sorted({r["test_item"] for r in clean}),
        "required_items": spec["required_items"],
        "retest_rows": sum(1 for r in clean if (r["retest"] or 0) > 0),
        "modal_limits": {k: list(v) for k, v in modal.items()},
        "robust_center": {k: {"median": round(m, 6), "mad": round(d, 6)} for k, (m, d) in bounds.items()},
        "rules": {k: {"severity": v[0], "definition": v[1]} for k, v in RULES.items()},
    }
    return clean, issues, profile
