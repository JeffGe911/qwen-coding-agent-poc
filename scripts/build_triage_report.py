"""Build evidence/regression-triage/REPORT.md from a frozen contract and the raw eval results.

Every number comes from results/<version>-<engine>/<split>/*.json; nothing is typed in by hand except the optional
analysis in evidence/regression-triage/REPORT-notes-<version>.md, which is copied in verbatim. Code tests, triage quality
and service performance are reported in separate sections. Writes REPORT-<version>.md; re-running overwrites only that file.
Usage: python scripts/build_triage_report.py --contract evidence/regression-triage/contract/eval-v1.json
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence" / "regression-triage"
ENGINES = ("rules", "qwen")
SPLITS = ("dev", "holdout")
QUALITY = [("category", "类别准确率"), ("result", "结果准确率（pass/fail/not_run/unknown）"), ("side", "责任方准确率（设计或测试 / 基础设施）")]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def frac(a, b):
    return f"{a}/{b} ({a / b:.1%})" if b else "—"


def results(version):
    """{(engine, split): {"metrics": ..., "samples": [per-sample record, ...]}} for every result folder that exists."""
    found = {}
    for engine in ENGINES:
        for split in SPLITS:
            d = EV / "results" / f"{version}-{engine}" / split
            if (d / "metrics.json").exists():
                samples = [load(p) for p in sorted(d.glob("*.json")) if p.name != "metrics.json" and not p.name.endswith(".model-response.json")]
                found[(engine, split)] = {"metrics": load(d / "metrics.json"), "samples": samples}
    return found


def counts(samples):
    tests = [t for s in samples if s["score"] for t in s["score"]["tests"]]
    gold_total = sum(len(s["score"]["tests"]) for s in samples if s["score"])
    c = {k: sum(t[f"{k}_ok"] for t in tests) for k, _ in QUALITY}
    # The model client drops citations that fail validation before scoring; count them back in, so a rate is over
    # every citation the engine gave, not only the ones that survived (rules never have rejected citations).
    rejected = sum(len(t.get("rejected_citations", [])) for s in samples for t in ((s.get("triage") or {}).get("tests") or []))
    c.update(tests=gold_total, cites=sum(t["citations"] for t in tests) + rejected, rejected=rejected, valid=sum(t["citations_valid"] for t in tests),
             relevant=sum(t["citations_relevant"] for t in tests),
             need=sum(t["has_relevant_citation"] is not None for t in tests), has=sum(bool(t["has_relevant_citation"]) for t in tests))
    for k in ("tp", "fp", "fn"):
        c[k] = sum(len(s["score"]["flagged"][k]) for s in samples if s["score"])
    return c


def quality_table(found):
    cols = sorted(found, key=lambda k: (ENGINES.index(k[0]), SPLITS.index(k[1])))
    head = "| 指标 | " + " | ".join(f"{e} · {s}" for e, s in cols) + " |\n|---|" + "---|" * len(cols) + "\n"
    rows = []
    cs = {k: counts(found[k]["samples"]) for k in cols}
    ms = {k: found[k]["metrics"] for k in cols}
    for key, label in QUALITY:
        rows.append(f"| {label} | " + " | ".join(frac(cs[k][key], cs[k]["tests"]) for k in cols) + " |")
    rows.append("| 需关注测试（fail / not_run）precision | " + " | ".join(frac(cs[k]["tp"], cs[k]["tp"] + cs[k]["fp"]) for k in cols) + " |")
    rows.append("| 需关注测试 recall | " + " | ".join(frac(cs[k]["tp"], cs[k]["tp"] + cs[k]["fn"]) for k in cols) + " |")
    rows.append("| 引用有效率（文件、行号、原文都对得上） | " + " | ".join(frac(cs[k]["valid"], cs[k]["cites"]) for k in cols) + " |")
    rows.append("| 引用相关率（指向人工标注的证据行） | " + " | ".join(frac(cs[k]["relevant"], cs[k]["cites"]) for k in cols) + " |")
    rows.append("| 至少有一条相关引用的测试 | " + " | ".join(frac(cs[k]["has"], cs[k]["need"]) for k in cols) + " |")
    rows.append("| unknown 比例（占金标准测试数） | " + " | ".join(f"{ms[k]['unknown_rate']:.1%}" if ms[k]["unknown_rate"] is not None else "—" for k in cols) + " |")
    rows.append("| 报告了日志中不存在的测试 | " + " | ".join(str(ms[k]["unmatched_tests"]) for k in cols) + " |")
    rows.append("| 日志状态准确率（complete / incomplete / empty / unknown_format） | " + " | ".join(f"{ms[k]['log_status_accuracy']:.1%}" for k in cols) + " |")
    rows.append("| 特殊标记召回（注入、伪造标记、重复失败 …） | " + " | ".join(f"{ms[k]['flag_recall']:.1%}" if ms[k]["flag_recall"] is not None else "—" for k in cols) + " |")
    rows.append("| 全部样本类别准确率（未作答样本按错误计） | " + " | ".join(f"{ms[k]['category_accuracy_all_samples']:.1%}" for k in cols) + " |")
    return head + "\n".join(rows) + "\n"


def service_table(found):
    rows = ["| 引擎 · 拆分 | 调用次数 | 请求失败 | 输出不合规 | 未评分样本 | 总耗时 (s) | 平均每样本 (s) | prompt tokens | completion tokens |", "|---|---|---|---|---|---|---|---|---|"]
    for (engine, split), r in sorted(found.items(), key=lambda kv: (ENGINES.index(kv[0][0]), SPLITS.index(kv[0][1]))):
        m = r["metrics"]
        n = m["requests"] or 1
        tok = (m["prompt_tokens"], m["completion_tokens"]) if engine != "rules" else ("—", "—")
        rows.append(f"| {engine} · {split} | {m['requests']} | {m['request_failed']} | {m['invalid_output']} | {len(m['unscored_samples'])} | {m['seconds_total']} | {m['seconds_total'] / n:.4f} | {tok[0]} | {tok[1]} |")
    return "\n".join(rows) + "\n"


def outcome(t):
    if t["category_ok"]:
        return "correct"
    if t["pred"]["category"] is None:
        return "missing"
    return "abstain" if t["pred"]["category"] == "unknown" else "wrong"


def safety(samples, split):
    """What an engineer would be misled by. Tests of samples the engine could not answer count as missing."""
    c = dict.fromkeys(("tests", "correct", "abstain", "wrong", "missing", "false_release", "false_alarm", "missed", "attention", "rejected_citations"), 0)
    secs = []
    for s in samples:
        gold = load(EV / "gold" / split / f"{s['sample_id']}.json")["tests"]
        rows = s["score"]["tests"] if s["score"] else [{"test_id": tid, "gold": g, "pred": {"category": None, "result": None}, "category_ok": False} for tid, g in gold.items()]
        for t in rows:
            g, p = t["gold"]["result"], t["pred"]["result"]
            c["tests"] += 1
            c[outcome(t)] += 1
            c["false_release"] += g != "pass" and p == "pass"           # reported as passing although it did not pass
            c["false_alarm"] += g == "pass" and p in ("fail", "not_run")
            c["attention"] += g in ("fail", "not_run")
            c["missed"] += g in ("fail", "not_run") and p not in ("fail", "not_run")
        c["rejected_citations"] += sum(len(t.get("rejected_citations", [])) for t in ((s["triage"] or {}).get("tests") or []))
        if s["call"].get("seconds") is not None:
            secs.append(s["call"]["seconds"])
    secs.sort()
    c["seconds"] = {"median": secs[len(secs) // 2] if secs else None, "max": secs[-1] if secs else None, "total": round(sum(secs), 3)}
    return c


def comparison(found):
    out = []
    for split in SPLITS:
        if not all((e, split) in found for e in ENGINES):
            continue
        sf = {e: safety(found[(e, split)]["samples"], split) for e in ENGINES}
        cs = {e: counts(found[(e, split)]["samples"]) for e in ENGINES}
        n = sf["rules"]["tests"]
        row = lambda label, f: f"| {label} | " + " | ".join(f(e) for e in ENGINES) + " |"
        out += [f"### {split}（{n} 个金标准测试）\n", "| | 规则 | Qwen |", "|---|---|---|",
                row("类别正确", lambda e: frac(sf[e]["correct"], n)),
                row("回答“不知道”（unknown）", lambda e: frac(sf[e]["abstain"], n)),
                row("**确信但错误**（给了具体类别且与金标准不同）", lambda e: frac(sf[e]["wrong"], n)),
                row("没有作答（漏掉测试或整份日志调用失败）", lambda e: frac(sf[e]["missing"], n)),
                row("**误放行**（没通过却报成 pass）", lambda e: str(sf[e]["false_release"])),
                row("误报（通过却报成 fail / not_run）", lambda e: str(sf[e]["false_alarm"])),
                row("漏报（需关注测试没被报为 fail / not_run）", lambda e: f"{sf[e]['missed']}/{sf[e]['attention']}"),
                row("引用相关率", lambda e: frac(cs[e]["relevant"], cs[e]["cites"])),
                row("被校验拒绝的引用", lambda e: str(sf[e]["rejected_citations"])),
                row("每样本耗时 中位数 / 最大（s）", lambda e: f"{sf[e]['seconds']['median']} / {sf[e]['seconds']['max']}"), ""]
        both = {}
        for e in ENGINES:
            for s in found[(e, split)]["samples"]:
                for t in (s["score"] or {"tests": []})["tests"]:
                    both.setdefault((s["sample_id"], t["test_id"]), {})[e] = t["category_ok"]
        keys = [k for k in both if len(both[k]) == 2] + [k for k in both if len(both[k]) < 2]
        cell = lambda r, q: sum(1 for k in keys if bool(both[k].get("rules")) is r and bool(both[k].get("qwen")) is q)
        out += ["逐个测试对照（类别是否正确）：\n", "| | Qwen 对 | Qwen 错 |", "|---|---|---|",
                f"| 规则对 | {cell(True, True)} | {cell(True, False)} |", f"| 规则错 | {cell(False, True)} | {cell(False, False)} |", ""]
        only_q = sorted(f"{k[0]}/{k[1]}" for k in keys if both[k].get("qwen") and not both[k].get("rules"))
        only_r = sorted(f"{k[0]}/{k[1]}" for k in keys if both[k].get("rules") and not both[k].get("qwen"))
        out += [f"只有 Qwen 对：{', '.join(only_q) or '无'}\n", f"只有规则对：{', '.join(only_r) or '无'}\n"]
    return "\n".join(out) + "\n" if out else ""


def sample_table(samples, kinds):
    rows = ["| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s in samples:
        sc = s["score"]
        if sc is None:
            rows.append(f"| {s['sample_id']} | {kinds.get(s['sample_id'], '?')} | {s['call']['status']} | — | — | — | — | — | — | — |")
            continue
        t = sc["tests"]
        n = len(t)
        ok = lambda k: f"{sum(x[f'{k}_ok'] for x in t)}/{n}"
        cites = f"{sum(x['citations_valid'] for x in t)}/{sum(x['citations_relevant'] for x in t)}/{sum(x['citations'] for x in t)}"
        rows.append(f"| {s['sample_id']} | {kinds.get(s['sample_id'], '?')} | {s['call']['status']} | {ok('category')} | {ok('result')} | {ok('side')} | "
                    f"{', '.join(sc['flagged']['fn']) or '—'} | {', '.join(sc['flagged']['fp']) or '—'} | {cites} | {'✓' if sc['log_status_ok'] else '✗ ' + str(sc['log_status']['pred'])} |")
    return "\n".join(rows) + "\n"


def misses(samples):
    out = []
    for s in samples:
        sc = s["score"]
        if sc is None:
            call = s["call"]
            out.append(f"- `{s['sample_id']}`：模型调用 {call['status']}，{call.get('problems') or call.get('error') or ''}")
            continue
        for t in sc["tests"]:
            wrong = [k for k, _ in QUALITY if not t[f"{k}_ok"]]
            if wrong or t["has_relevant_citation"] is False:
                g, p = t["gold"], t["pred"]
                what = "、".join(wrong) + ("；" if wrong else "") + ("没有指向证据行的引用" if t["has_relevant_citation"] is False else "")
                out.append(f"- `{s['sample_id']}` / `{t['test_id']}`：金标准 {g['category']}/{g['result']}/{g['side']}，"
                           f"预测 {p['category']}/{p['result']}/{p['side']}（{what.rstrip('；')}）")
        for tid in sc["unmatched_tests"]:
            out.append(f"- `{s['sample_id']}` / `{tid}`：报告了日志中不存在的测试")
        missing = sorted(set(sc["flags_expected"]) - set(sc["flags_found"]))
        if missing:
            out.append(f"- `{s['sample_id']}`：没有给出标记 {', '.join(missing)}")
    return "\n".join(out) + "\n" if out else "没有错误。\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--contract", required=True)
    args = p.parse_args()
    contract = load(args.contract)
    found = results(contract["version"])
    kinds = {r["sample_id"]: r["kind"] for split in contract["dataset"].values() for r in split}
    pytest_file = EV / "pytest-summary.txt"
    pytest_line = pytest_file.read_text(encoding="utf-8").strip().splitlines()[-1] if pytest_file.exists() else "未记录"
    tools = next((load(p)["tools"] for p in sorted((EV / "runs").glob("*/run.json"))), {})
    dc = contract["dataset_counts"]
    q = contract["qwen"]

    md = [f"# 仿真回归日志分诊：评测报告（合同 {contract['version']}）\n",
          f"> 本文件由 `scripts/build_triage_report.py` 根据冻结合同和 `results/` 下的原始结果生成，不要手改。"
          f"合同冻结于 {contract['frozen_utc']}，代码提交 `{contract['git_commit'][:10]}`，冻结时代码有未提交改动：{'是' if contract['code_uncommitted_changes'] else '否'}。\n"]
    notes = EV / f"REPORT-notes-{contract['version']}.md"
    if notes.exists():
        md += ["## 0. 结论与分析（人工撰写）\n", notes.read_text(encoding="utf-8").strip() + "\n"]
    md += ["## 1. 代码与单元测试\n", f"`pytest`：{pytest_line}\n",
           "单元测试只说明代码行为符合预期（执行器限制、日志读取、引用校验、模型输出校验等），不代表分诊质量。\n",
           "## 2. 分诊质量\n",
           "dev 是开发规则和 prompt 时可以反复查看的拆分；holdout 由独立代理在看不到规则、prompt、评分代码和 dev 金标准的情况下编写和标注，"
           "每个合同版本、每个引擎只运行一次。看过 holdout 结果后再改规则或 prompt，就必须开新合同版本，且不能再称为盲测。\n",
           quality_table(found) if found else "尚无评测结果。\n",
           *(["### 规则与 Qwen 的错误类型对比\n", comparison(found)] if comparison(found) else []),
           "## 3. 服务性能\n",
           "规则引擎在本机进程内运行，耗时只是参考。模型耗时是笔记本单卡、单并发下测得的，不能外推到服务器吞吐。\n",
           service_table(found) if found else "尚无评测结果。\n",
           "## 4. 数据集\n",
           "| 拆分 | 样本数 | 真实仿真运行 | 人工构造（synthetic） |\n|---|---|---|---|\n" +
           "".join(f"| {k} | {v['samples']} | {v['real']} | {v['synthetic']} |\n" for k, v in dc.items()),
           "“真实”指由本仓库的受限执行器调用 Icarus Verilog / Verilator 实际运行得到的日志（含故意注入的设计缺陷）；"
           "“synthetic”是为覆盖真实运行难以产生的情况而手写的日志（空文件、截断、UVM 风格、许可证失败等），已在清单中逐条标明。\n",
           f"工具版本：iverilog `{tools.get('iverilog', '?')}`；verilator `{tools.get('verilator', '?')}`。\n"]
    for (engine, split), r in sorted(found.items(), key=lambda kv: (ENGINES.index(kv[0][0]), SPLITS.index(kv[0][1]))):
        md += [f"## 5.{ENGINES.index(engine) * 2 + SPLITS.index(split) + 1} 逐样本：{engine} · {split}\n", sample_table(r["samples"], kinds),
               "错误明细：\n", misses(r["samples"])]
    if not q:
        model_line = "- 本合同只覆盖规则引擎，没有冻结模型设置；模型评测需要另一个合同版本。\n"
    elif "backend" in q:  # eval-v3 and later: a backend profile
        b, w = q["backend"], q["backend"]["weights"]
        model_line = (f"- prompt 版本 `{q['prompt_version']}`，prompt+schema sha256 `{q['prompt_sha256'][:16]}…`\n"
                      f"- 后端 `{b['name']}`（{b['kind']}，`{q['backend_file']}`，sha256 `{q['backend_sha256'][:12]}…`）：{b['server']['software']}；"
                      f"模型 `{b['model']}`，权重 {w['source']}，{w['format']} {w['quantization']}" + (f"，digest `{w['digest'][:16]}…`" if w.get("digest") else f"，revision `{w.get('revision', '?')[:12]}`") +
                      f"；上下文 {b['context_tokens']}，max_tokens {b['max_tokens']}，超时 {b['timeout_s']} s，并发 {b['concurrency']}，鉴权 {b['auth']['type']}\n"
                      f"- 请求中的采样参数 `{json.dumps(b['request_sampling'])}`；服务端实际生效 `{json.dumps({k: v for k, v in b['effective_sampling'].items() if k != 'source'}, ensure_ascii=False)}`\n")
    else:  # eval-v2 shape
        model_line = (f"- prompt 版本 `{q['prompt_version']}`，prompt+schema sha256 `{q['prompt_sha256'][:16]}…`；模型 `{q['model']}`，digest `{q['model_tag']['digest'][:16]}…`，"
                      f"量化 {q['model_tag']['quantization']}，发布 `{q['release']}`，上下文 {q['context_tokens']}，max_tokens {q['max_tokens']}，temperature {q['sampling']['temperature']}\n")
    md += ["## 6. 冻结内容与复现\n",
           f"- 覆盖的引擎：{'、'.join(contract.get('engines', ENGINES))}；规则版本 `{contract['rules']['version']}`\n" + model_line +
           f"- 代码哈希：" + "，".join(f"`{Path(k).name}` {v[:12]}" for k, v in contract["code_sha256"].items()) + "\n",
           "```\n"
           f"python -m regression_triage eval --contract evidence/regression-triage/contract/{contract['version']}.json --split dev --engine rules\n"
           f"python -m regression_triage eval --contract evidence/regression-triage/contract/{contract['version']}.json --split holdout --engine rules\n"
           + (f"python scripts/triage_model_session.py --contract evidence/regression-triage/contract/{contract['version']}.json --split dev\n"
              f"python scripts/triage_model_session.py --contract evidence/regression-triage/contract/{contract['version']}.json --split holdout --unload\n" if q else "") +
           f"python scripts/build_triage_report.py --contract evidence/regression-triage/contract/{contract['version']}.json\n"
           "```\n",
           "`eval` 会先核对数据、金标准和代码哈希，与合同不一致时拒绝运行；同一合同版本的同一拆分已有结果时也拒绝覆盖。\n"]
    out = EV / f"REPORT-{contract['version']}.md"
    out.write_text("\n".join(md), encoding="utf-8", newline="\n")
    print(out)


if __name__ == "__main__":
    main()
