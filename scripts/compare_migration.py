"""Compare one engine's results under two frozen contracts: before and after a backend migration.

Reads results/<version>-<engine>/<split>/*.json of both contracts, plus model-runs/<version>/<split>/session.json
(Windows/Ollama watchdog) or resources-summary.json (deploy/linux-vllm/migrate.sh) when present. Writes
evidence/migration/COMPARISON-<before>-vs-<after>.md.
- Weights, quantization, server and sampling differences come from the two backend profiles and are listed first.
- Outputs are not expected to be identical; the comparison is about whether the business result held.
- A split missing on one side is reported as missing, never filled in.
Usage: python scripts/compare_migration.py --before eval-v3 --after eval-v4 [--engine qwen]
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_triage_report import EV, SPLITS, counts, frac, load, safety  # noqa: E402  same scoring helpers as the report


def side(version, engine, split):
    d = EV / "results" / f"{version}-{engine}" / split
    if not (d / "metrics.json").exists():
        return None
    samples = [load(p) for p in sorted(d.glob("*.json")) if p.name != "metrics.json" and not p.name.endswith(".model-response.json")]
    res = None
    for name in ("session.json", "resources-summary.json"):
        f = EV / "model-runs" / version / split / name
        if f.exists():
            r = load(f)
            res = r.get("watch", r)
    calls = [s["call"] for s in samples]
    secs = sorted(c["seconds"] for c in calls if c.get("seconds") is not None)
    pct = lambda q: secs[min(len(secs) - 1, int(q * len(secs)))] if secs else None
    usage = [c.get("usage") or {} for c in calls]
    return {"samples": samples, "safety": safety(samples, split), "counts": counts(samples), "n": len(calls),
            "ok": sum(c["status"] == "ok" for c in calls), "request_failed": sum(c["status"] == "request_failed" for c in calls),
            "invalid_output": sum(c["status"] == "invalid_output" for c in calls),
            "seconds": {"median": pct(0.5), "p90": pct(0.9), "max": secs[-1] if secs else None, "total": round(sum(secs), 1)},
            "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage), "completion_tokens": sum(u.get("completion_tokens") or 0 for u in usage),
            "resources": res}


def describe(contract):
    q = contract.get("qwen") or {}
    b = q.get("backend")
    if not b:
        return {"name": "(rules only)" if not q else q.get("model"), "rows": {}}
    w = b["weights"]
    return {"name": b["name"], "rows": {"服务": b["server"]["software"], "接口": b["base_url"], "鉴权": b["auth"]["type"],
                                        "权重": f"{w['source']}（{w['format']}，{w['quantization']}）",
                                        "权重标识": w.get("digest") or w.get("revision"), "结构化输出": b["server"]["structured_output"],
                                        "请求采样参数": json.dumps(b["request_sampling"]),
                                        "生效采样": json.dumps({k: v for k, v in b["effective_sampling"].items() if k != "source"}, ensure_ascii=False),
                                        "上下文 / 输出预算 / 超时": f"{b['context_tokens']} / {b['max_tokens']} / {b['timeout_s']} s"}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--engine", default="qwen")
    p.add_argument("--out", help="output file (default evidence/migration/COMPARISON-<before>-vs-<after>.md)")
    args = p.parse_args()
    cb, ca = (load(EV / "contract" / f"{v}.json") for v in (args.before, args.after))
    if cb["dataset"] != ca["dataset"]:
        raise SystemExit("the two contracts freeze different datasets or gold labels; their results are not comparable")
    db, da = describe(cb), describe(ca)
    md = [f"# 迁移前后对比：{args.before}（{db['name']}）→ {args.after}（{da['name']}），引擎 {args.engine}\n",
          "> 本文件由 `scripts/compare_migration.py` 根据两个冻结合同的原始结果生成。不要求两边输出逐字相同；判断标准是业务结果是否保持。\n",
          "## 1. 两边的差异（来自后端配置文件）\n", "| 项目 | 迁移前 | 迁移后 |", "|---|---|---|"]
    md += [f"| {k} | {db['rows'].get(k, '—')} | {da['rows'].get(k, '—')} |" for k in dict.fromkeys([*db["rows"], *da["rows"]])]
    md += ["", f"代码哈希相同：{'是' if cb['code_sha256'] == ca['code_sha256'] else '否（两边代码不同，结果差异可能来自代码）'}。数据集与金标准相同。\n"]
    for split in SPLITS:
        b, a = side(args.before, args.engine, split), side(args.after, args.engine, split)
        md.append(f"## {split}\n")
        if not b or not a:
            md.append(f"缺少结果：迁移前 {'有' if b else '无'}，迁移后 {'有' if a else '无'}。不做比较。\n")
            continue
        row = lambda label, f: f"| {label} | {f(b)} | {f(a)} |"
        n = b["safety"]["tests"]
        md += ["| 指标 | 迁移前 | 迁移后 |", "|---|---|---|",
               row("请求成功（未出现连接或 HTTP 错误）", lambda x: frac(x["n"] - x["request_failed"], x["n"])),
               row("结构化输出合规（schema、引用校验通过）", lambda x: frac(x["ok"], x["n"])),
               row("类别正确", lambda x: frac(x["safety"]["correct"], n)),
               row("**误放行**", lambda x: str(x["safety"]["false_release"])),
               row("漏报", lambda x: f"{x['safety']['missed']}/{x['safety']['attention']}"),
               row("误报", lambda x: str(x["safety"]["false_alarm"])),
               row("unknown", lambda x: frac(x["safety"]["abstain"], n)),
               row("引用相关率", lambda x: frac(x["counts"]["relevant"], x["counts"]["cites"])),
               row("每样本耗时 中位数 / p90 / 最大（s）", lambda x: f"{x['seconds']['median']} / {x['seconds']['p90']} / {x['seconds']['max']}"),
               row("prompt / completion tokens 合计", lambda x: f"{x['prompt_tokens']} / {x['completion_tokens']}"),
               row("资源记录", lambda x: json.dumps(x["resources"], ensure_ascii=False) if x["resources"] else "无"), ""]
        same = diff = 0
        flips = []
        cats = lambda x: {(s["sample_id"], t["test_id"]): t["pred"]["category"] for s in x["samples"] if s["score"] for t in s["score"]["tests"]}
        cb_, ca_ = cats(b), cats(a)
        for k in sorted(set(cb_) | set(ca_)):
            if cb_.get(k) == ca_.get(k):
                same += 1
            else:
                diff += 1
                flips.append(f"`{k[0]}/{k[1]}` {cb_.get(k)} → {ca_.get(k)}")
        md += [f"两边预测类别相同的测试：{same}，不同：{diff}。" + ("不同的测试：" + "；".join(flips) if flips else ""), ""]
    out = Path(args.out) if args.out else ROOT / "evidence" / "migration" / f"COMPARISON-{args.before}-vs-{args.after}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    print(out)


if __name__ == "__main__":
    main()
