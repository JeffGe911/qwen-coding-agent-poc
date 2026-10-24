"""Markdown triage report for engineers. Suggestions are displayed only; nothing in a report is executed.

A report starts as "pending review"; `python -m regression_triage review` records an engineer's decision per test
and re-renders it. Reviewer names come only from that command, never from the model or the log.
"""
from datetime import datetime, timezone

LABEL = {"pass": "通过", "compile_error": "编译失败", "test_failure": "测试/断言失败", "timeout": "超时", "tool_error": "工具/环境失败",
         "incomplete_log": "日志不完整", "unknown": "无法判断"}
SIDE = {"none": "—", "design_or_test": "设计或测试问题", "infrastructure": "基础设施问题", "undetermined": "无法判定归属"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def render(doc):
    t = doc["triage"]
    reviews = {r["test_id"]: r for r in doc.get("reviews", [])}
    pending = [x["test_id"] for x in t["tests"] if x["test_id"] not in reviews]
    md = [f"# 回归日志分诊：{t['file']}", "",
          f"- 引擎：{t['engine']}；生成于 {doc['created_utc']}；日志 {t.get('lines', '?')} 行，sha256 {t.get('sha256', '')[:16]}…",
          f"- 日志状态：{t['log_status']}" + (f"；标记：{', '.join(t['flags'])}" if t.get("flags") else ""),
          f"- 复核状态：{'全部已复核' if not pending else '待工程师复核：' + ', '.join(pending)}",
          "- 建议只供参考，不会自动执行任何命令或修改 RTL/测试。", ""]
    if doc.get("model_call"):
        m = doc["model_call"]
        md.append(f"- 模型调用：状态 {m['status']}，耗时 {m.get('seconds')} s，token {m.get('usage', {})}；" + "；".join(m.get("problems", [])))
        md.append("")
    md += ["| 测试 | 结果 | 类别 | 归属 | 证据 | 指纹 | 复核 |", "|---|---|---|---|---|---|---|"]
    for x in t["tests"]:
        ev = "<br>".join(f"`{e['file']}:{e['line']}` {e['quote'][:90]}" for e in x["evidence"]) or "（无可引用的行）"
        r = reviews.get(x["test_id"])
        rv = f"{r['decision']}（{r['reviewer']}，{r['at_utc'][:10]}）" if r else "待复核"
        md.append(f"| {x['test_id']} | {x['result']} | {LABEL.get(x['category'], x['category'])} | {SIDE.get(x['side'], x['side'])} | {ev} | "
                  f"{x.get('fingerprint') or '—'} | {rv} |")
    md += ["", "## 排查建议", ""]
    for x in t["tests"]:
        if x["category"] == "pass":
            continue
        extra = []
        if x.get("certainty") == "insufficient_evidence":
            extra.append("证据不足")
        extra += x.get("notes", [])
        if x.get("rejected_citations"):
            extra.append(f"{len(x['rejected_citations'])} 条模型引用与日志不符，已拦截")
        if x.get("unmatched"):
            extra.append("该测试名不在日志中，可能是模型编造")
        md.append(f"- **{x['test_id']}**：{x['suggestion']}" + (f"（{'；'.join(extra)}）" if extra else ""))
        r = reviews.get(x["test_id"])
        if r and r.get("note"):
            md.append(f"  - 复核意见（{r['reviewer']}）：{r['note']}")
    groups = [g for g in t.get("groups", []) if len(g["tests"]) > 1]
    if groups:
        md += ["", "## 重复失败分组", ""] + [f"- 指纹 `{g['fingerprint']}`（{LABEL.get(g['category'], g['category'])}）：{', '.join(g['tests'])}；例：`{g['example']['file']}:{g['example']['line']}` {g['example']['quote'][:90]}" for g in groups]
    if t.get("notes"):
        md += ["", "## 输入问题", ""] + [f"- {n}" for n in t["notes"]]
    return "\n".join(md) + "\n"


def add_review(doc, test_id, decision, reviewer, note=""):
    if decision not in ("accept", "reject", "needs_more_info"):
        raise ValueError("decision must be accept, reject or needs_more_info")
    if not reviewer.strip():
        raise ValueError("a reviewer name is required")
    if test_id not in {x["test_id"] for x in doc["triage"]["tests"]}:
        raise ValueError(f"{test_id} is not in this triage")
    doc.setdefault("reviews", []).append({"test_id": test_id, "decision": decision, "reviewer": reviewer, "note": note, "at_utc": now()})
    return doc
