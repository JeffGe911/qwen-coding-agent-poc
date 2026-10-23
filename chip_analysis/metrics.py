"""Metric definitions. Every choice that is not dictated by the data is listed in ASSUMPTIONS."""
from collections import Counter, defaultdict
import statistics

ASSUMPTIONS = [
    "A1 记录口径：测试记录通过率 = PASS 行数 / (PASS + FAIL 行数)，基于去重后的全部行（含重测行）；SKIP 和缺状态行不进分母，单独计数。",
    "A2 最终结果：同一 运行+芯片+项目 取重测轮次最大的那一行；若该轮次存在内容冲突的多行，则判为 INVALID。首测结果取轮次 0。",
    "A3 判定依据：使用测试机记录的状态（status）。状态与上下限不一致的行在质量检查中列出，但不改写状态。",
    "A4 芯片通过：items.json 中每个必测项目在该运行中都有最终 PASS。任一必测项目最终 FAIL → 芯片 FAIL；否则若缺行、SKIP、缺状态或 INVALID → 芯片 INCOMPLETE。",
    "A5 良率给出两个分母：良率(全部) = PASS 芯片 / 全部芯片（INCOMPLETE 算作未通过）；良率(仅完整) = PASS / (PASS + FAIL)。没有给定公司口径，不自行选定其中一个为“官方良率”。",
    "A6 不同运行分开统计。R2 对 LOT-A02 的复测不与 R1 合并成一个良率，而是用运行对比展示变化。",
    "A7 上下限以每行自带的上下限为准（测试机就是这样判定的）；不同文件上下限不一致时在质量检查中报出，跨批次比较时需注意。",
    "A8 分布与趋势只用首测（轮次 0）、数值有效、未被判为不可信或冲突的值，避免重测样本偏向边缘芯片。",
    "A9 异常集中判定（启发式，不是统计检验）：某批次/晶圆在某项目上最终 FAIL 芯片数 >= 5，且失败率 >= 其他所有批次/晶圆合计失败率的 2 倍。",
    "A10 相关不等于因果：报告中的差异只描述数据，不推断芯片失效根因。",
]
CONCENTRATION_MIN_FAILS = 5
CONCENTRATION_RATIO = 2.0


def results(clean, which="final"):
    """(run, chip_key, item) -> {status, record}. status in PASS/FAIL/SKIP/NO_STATUS/INVALID."""
    groups = defaultdict(list)
    for r in clean:
        if which == "first" and r["retest"] != 0:
            continue
        groups[(r["run_id"], r["chip_key"], r["test_item"])].append(r)
    out = {}
    for key, rows in groups.items():
        top = max((x["retest"] or 0) for x in rows)
        chosen = [x for x in rows if (x["retest"] or 0) == top]
        if len(chosen) > 1 or "conflicting_measurement" in chosen[0]["flags"]:
            out[key] = {"status": "INVALID", "record": chosen[0], "retest": top}
        else:
            out[key] = {"status": chosen[0]["status"] or "NO_STATUS", "record": chosen[0], "retest": top}
    return out


def chip_outcomes(clean, spec, which="final"):
    res = results(clean, which)
    chips = {}
    for r in clean:
        chips.setdefault((r["run_id"], r["chip_key"]), {"run_id": r["run_id"], "chip_key": r["chip_key"], "lot_id": r["lot_id"],
                                                         "wafer_id": r["wafer_id"], "die_id": r["die_id"], "test_program": r["test_program"]})
    for (run, chip), info in chips.items():
        failed, missing = [], []
        for item in spec["required_items"]:
            entry = res.get((run, chip, item))
            if entry is None or entry["status"] in ("SKIP", "NO_STATUS", "INVALID"):
                missing.append(item if entry is None else f"{item}:{entry['status']}")
            elif entry["status"] == "FAIL":
                failed.append(item)
        info["failed_items"], info["missing_items"] = failed, missing
        info["outcome"] = "FAIL" if failed else "INCOMPLETE" if missing else "PASS"
    return sorted(chips.values(), key=lambda c: (c["run_id"], c["chip_key"]))


def ratio(a, b, digits=4):
    return round(a / b, digits) if b else None


def yield_table(final_chips, first_chips, keys):
    first_by = {(c["run_id"], c["chip_key"]): c["outcome"] for c in first_chips}
    groups = defaultdict(Counter)
    for c in final_chips:
        g = tuple(c[k] for k in keys)
        groups[g][c["outcome"]] += 1
        groups[g]["chips"] += 1
        groups[g]["first_pass"] += first_by.get((c["run_id"], c["chip_key"])) == "PASS"
    rows = []
    for g, n in sorted(groups.items()):
        rows.append({**dict(zip(keys, g)), "chips": n["chips"], "pass": n["PASS"], "fail": n["FAIL"], "incomplete": n["INCOMPLETE"],
                     "yield_all": ratio(n["PASS"], n["chips"]), "yield_complete_only": ratio(n["PASS"], n["PASS"] + n["FAIL"]),
                     "first_pass_yield_all": ratio(n["first_pass"], n["chips"])})
    return rows


def record_pass_rate(clean, keys):
    groups = defaultdict(Counter)
    for r in clean:
        groups[tuple(r[k] for k in keys)][r["status"] or "NO_STATUS"] += 1
    return [{**dict(zip(keys, g)), "pass_rows": n["PASS"], "fail_rows": n["FAIL"], "skip_rows": n["SKIP"], "no_status_rows": n["NO_STATUS"],
             "record_pass_rate": ratio(n["PASS"], n["PASS"] + n["FAIL"])} for g, n in sorted(groups.items())]


def item_failures(clean, finals):
    """Per (run, item): record-level FAIL rows and final chip-level FAILs."""
    rows = Counter((r["run_id"], r["test_item"]) for r in clean if r["status"] == "FAIL")
    final = defaultdict(Counter)
    for (run, chip, item), e in finals.items():
        final[(run, item)][e["status"]] += 1
    out = []
    for key in sorted(set(rows) | set(final)):
        f = final[key]
        valid = f["PASS"] + f["FAIL"]
        out.append({"run_id": key[0], "test_item": key[1], "fail_rows": rows[key], "final_fail_chips": f["FAIL"],
                    "final_valid_chips": valid, "final_fail_rate": ratio(f["FAIL"], valid), "final_not_valid": sum(f.values()) - valid})
    return out


def top_items(item_rows, n):
    total = defaultdict(lambda: Counter())
    for r in item_rows:
        total[r["test_item"]]["final_fail_chips"] += r["final_fail_chips"]
        total[r["test_item"]]["fail_rows"] += r["fail_rows"]
        total[r["test_item"]]["final_valid_chips"] += r["final_valid_chips"]
    ranked = sorted(total.items(), key=lambda kv: (-kv[1]["final_fail_chips"], -kv[1]["fail_rows"], kv[0]))
    return [{"rank": i + 1, "test_item": item, "final_fail_chips": c["final_fail_chips"], "fail_rows_incl_retests": c["fail_rows"],
             "final_valid_chips": c["final_valid_chips"], "final_fail_rate": ratio(c["final_fail_chips"], c["final_valid_chips"])}
            for i, (item, c) in enumerate(ranked[:n])]


def concentration(finals, clean, level=("lot_id",)):
    meta = {(r["run_id"], r["chip_key"]): r for r in clean}
    counts = defaultdict(Counter)
    for (run, chip, item), e in finals.items():
        if e["status"] in ("PASS", "FAIL"):
            g = (run,) + tuple(meta[(run, chip)][k] for k in level) + (item,)
            counts[g]["n"] += 1
            counts[g]["fail"] += e["status"] == "FAIL"
    flagged = []
    for g, c in counts.items():
        item = g[-1]
        rest_fail = sum(v["fail"] for k, v in counts.items() if k[-1] == item and k != g)
        rest_n = sum(v["n"] for k, v in counts.items() if k[-1] == item and k != g)
        rate, rest_rate = ratio(c["fail"], c["n"]), ratio(rest_fail, rest_n)
        hit = c["fail"] >= CONCENTRATION_MIN_FAILS and (rest_rate in (None, 0) or rate >= CONCENTRATION_RATIO * rest_rate)
        if hit:
            flagged.append({"run_id": g[0], **dict(zip(level, g[1:-1])), "test_item": item, "fail_chips": c["fail"], "valid_chips": c["n"],
                            "fail_rate": rate, "rest_fail_rate": rest_rate, "ratio_vs_rest": ratio(rate, rest_rate, 2) if rest_rate else None})
    return sorted(flagged, key=lambda x: -x["fail_chips"])


def usable(r):
    return r["value"] is not None and r["retest"] == 0 and not any(f in r["flags"] for f in ("implausible_value", "conflicting_measurement")) \
        and not any(f.startswith("unit_unknown") for f in r["flags"])


def describe(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    q = lambda p: values[min(len(values) - 1, int(round(p * (len(values) - 1))))]
    return {"n": len(values), "mean": round(statistics.fmean(values), 5), "sd": round(statistics.stdev(values), 5) if len(values) > 1 else 0.0,
            "min": values[0], "p05": q(0.05), "median": round(statistics.median(values), 5), "p95": q(0.95), "max": values[-1]}


def distributions(clean, keys=("test_item", "run_id", "lot_id")):
    groups = defaultdict(list)
    for r in clean:
        if usable(r):
            groups[tuple(r[k] for k in keys)].append(r["value"])
    return [{**dict(zip(keys, g)), **describe(v)} for g, v in sorted(groups.items())]


def trend(clean, item, minutes=5):
    """Median of first-measurement values for one item per time bucket of `minutes`."""
    groups = defaultdict(list)
    lots = defaultdict(set)
    for r in clean:
        if r["test_item"] == item and usable(r) and r["test_time"]:
            minute = int(r["test_time"][14:16]) // minutes * minutes
            bucket = f"{r['test_time'][:13]}:{minute:02d}"
            groups[bucket].append(r["value"])
            lots[bucket].add(f"{r['run_id']}:{r['lot_id']}")
    return [{"bucket": b, "n": len(v), "median": round(statistics.median(v), 4), "lots": sorted(lots[b])} for b, v in sorted(groups.items())]


def compare(clean, item_list, a, b, paired=False):
    """Compare two selections (dicts of field -> value). Paired = same chips, per-chip difference b - a."""
    pick = lambda sel: {(r["chip_key"], r["test_item"]): r for r in clean if usable(r) and all(r[k] == v for k, v in sel.items())}
    A, B = pick(a), pick(b)
    out = []
    for item in item_list:
        av = [r["value"] for (c, i), r in A.items() if i == item]
        bv = [r["value"] for (c, i), r in B.items() if i == item]
        row = {"test_item": item, "a": describe(av), "b": describe(bv)}
        if av and bv:
            row["mean_diff_b_minus_a"] = round(statistics.fmean(bv) - statistics.fmean(av), 5)
            pooled = statistics.pstdev(av + bv)
            row["std_diff"] = round(row["mean_diff_b_minus_a"] / pooled, 3) if pooled else None
        if paired:
            diffs = [B[(c, i)]["value"] - r["value"] for (c, i), r in A.items() if i == item and (c, i) in B]
            row["paired"] = {"n": len(diffs), "mean_diff": round(statistics.fmean(diffs), 5) if diffs else None,
                             "median_diff": round(statistics.median(diffs), 5) if diffs else None}
        out.append(row)
    return out
