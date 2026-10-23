"""Local-Qwen assistance. The model never computes metrics and never sees raw rows.

explain(): the model receives a compact JSON of already-computed facts and must cite fact keys
           as evidence; every number it writes is checked against the facts afterwards.
route():   the model maps a natural-language request to ONE fixed command + parameters
           (JSON schema, allowlisted values). Paths are never chosen by the model.
Both go through qwen_agent.client.Client, which only accepts loopback URLs (no cloud fallback).
"""
import json
import re
import time

from qwen_agent.client import Client

EXPLAIN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "properties": {"claim": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
                                                 "required": ["claim", "evidence"]}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "next_checks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "findings", "uncertainties", "next_checks"],
}
# Prompt history (2026-10-23), every output kept in evidence/chip-analysis/explanation_prompt_v*.json:
#   v1: two generic findings, no numbers, missed the wafer-level concentration.
#   v2: + required topics -> the model echoed the topic headings as claims, still no numbers.
#   v3: + one format example unrelated to this dataset (placeholder lot names/values). Final revision.
EXPLAIN_PROMPT_REVISION = 3
EXPLAIN_SYSTEM = (
    "你是芯片测试数据分析助手。用户给你的 facts 是程序已经算好的结果，数据是合成数据。"
    "只能使用 facts 中出现的数字，不要自己重新计算或编造数字。每条 finding 的 evidence 必须列出支撑它的 facts 键路径，例如 yield_by_lot[1].yield_all。"
    "findings 至少 5 条，依次覆盖：(1) 各运行各批次的良率，以及 yield_all 与 yield_complete_only 两个分母为何不同（incomplete 芯片）；"
    "(2) 失败最多的测试项目；(3) concentration_wafer 中的异常集中；(4) version_compare 与 run_diff 显示的变化；(5) quality_counts 中会影响结论的数据质量问题。"
    "每条 claim 必须写出 facts 中的具体数字，不要只复述主题。"
    "格式示例（与本数据无关）：{\"claim\": \"运行 RX 的批次 LOT-X 有 4 颗 incomplete 芯片，因此 yield_all 为 0.9 而 yield_complete_only 为 0.95\", \"evidence\": [\"yield_by_lot[0].incomplete\", \"yield_by_lot[0].yield_all\", \"yield_by_lot[0].yield_complete_only\"]}。"
    "测试记录通过率是按测试行计算的，芯片良率是按芯片计算的，二者不可混用。"
    "只描述相关性和差异，不要断言芯片失效根因；测试程序版本、测试条件和芯片本身的变化在这份数据中无法区分。"
    "在 uncertainties 中写出口径假设、样本量和数据质量带来的不确定性；在 next_checks 中写出需要人工确认的事项。用中文，返回 JSON。"
)
COMMANDS = ["analyze", "daily", "compare_runs", "extract_log", "review"]
ROUTE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "command": {"type": "string", "enum": COMMANDS},
        "top_n": {"type": "integer"},
        "date": {"type": "string"},
        "base_run": {"type": "string"},
        "new_run": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["command", "top_n", "date", "base_run", "new_run", "reason"],
}
ROUTE_SYSTEM = (
    "把用户的中文请求映射为一个固定命令。可选命令：analyze=完整分析并生成报告（按批次/晶圆/项目汇总、失败最多的项目、异常集中、分布、比较）；"
    "daily=某一天的每日汇总；compare_runs=对比两次运行的新增失败和已修复项目；extract_log=从测试日志提取失败项目；review=按规则导出待复核异常清单。"
    "top_n 默认 5；date 用 YYYY-MM-DD，不需要时为空字符串；base_run/new_run 不需要时为空字符串。只返回 JSON。"
)


def chat(client, system, user, schema, name, max_tokens):
    body = {"model": client.model, "temperature": 0, "max_tokens": max_tokens, "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    started = time.monotonic()
    response = client.request("/chat/completions", body)
    return body, response, round(time.monotonic() - started, 3)


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE]-?\d+)?%?")


def close(a, b):
    return abs(a - b) <= max(0.0006, abs(b) * 0.001)


def table_rows(facts):
    """Every dict that is an element of a list in facts (one table row each)."""
    rows = []
    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    rows.append(item)
                walk(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
    walk(facts)
    return rows


def misattributed_numbers(text, facts):
    """Numbers that only exist in table rows whose run/lot/wafer/item labels contradict the labels named in the claim.

    Example caught: claim names R1 + LOT-A02 but quotes 0.9571, which only exists in the R2 / LOT-B01 row.
    """
    rows = table_rows(facts)
    label_values = {}
    for r in rows:
        for k, v in r.items():
            if isinstance(v, str):
                label_values.setdefault(k, set()).add(v)
    # ASCII boundaries: Chinese characters count as \w, and "R1的" must still name R1.
    named = {k: {v for v in vals if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(v)}(?![A-Za-z0-9_-])", text)} for k, vals in label_values.items()}
    outside = [v for path, v in flatten(facts).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and "[" not in path]
    bad = []
    for token in NUMBER.findall(text):
        if token.endswith("%"):
            continue
        x = float(token)
        hits = [r for r in rows if any(isinstance(v, (int, float)) and not isinstance(v, bool) and close(x, v) for v in r.values())]
        if not hits or any(close(x, v) for v in outside):
            continue
        consistent = any(all(not named.get(k) or r[k] in named[k] for k, v in r.items() if isinstance(v, str)) for r in hits)
        if not consistent:
            bad.append(token)
    return bad


def verify_numbers(text, facts):
    """Every number in the model text must match some fact value (as-is, or as a percentage of it)."""
    values = [v for v in flatten(facts).values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    labels = " ".join(str(v) for v in flatten(facts).values() if isinstance(v, str))
    unmatched = []
    for token in NUMBER.findall(text):
        pct = token.endswith("%")
        x = float(token.rstrip("%"))
        candidates = [x / 100] if pct else [x, x / 100]
        ok = any(close(c, v) for c in candidates for v in values) or (not pct and token in labels)
        if not ok:
            unmatched.append(token)
    return unmatched


def evidence_exists(key, paths):
    """Exact fact path, or a prefix of one (e.g. yield_by_lot[1] or quality_counts)."""
    return key in paths or any(p.startswith(key + ".") or p.startswith(key + "[") for p in paths)


def check_explanation(parsed, facts):
    """Mechanical checks only: cited keys exist, numbers come from facts and from the row the claim names,
    claims contain a number at all. Passing these checks does NOT make a statement correct; humans review."""
    paths = set(flatten(facts))
    checks = []
    for f in parsed.get("findings", []):
        evidence = f.get("evidence", [])
        missing = [e for e in evidence if not evidence_exists(e, paths)]
        claim = f.get("claim", "")
        checks.append({"claim": claim, "evidence": evidence, "evidence_keys_found": bool(evidence) and not missing,
                       "missing_evidence_keys": missing, "claim_has_number": bool(NUMBER.search(claim)),
                       "numbers_not_in_facts": verify_numbers(claim, facts),
                       "numbers_misattributed": misattributed_numbers(claim, facts)})
    return checks, verify_numbers(parsed.get("summary", ""), facts)


def explain(facts, base_url, model):
    client = Client(base_url, model)
    user = json.dumps({"facts": facts}, ensure_ascii=False, separators=(",", ":"))
    body, response, seconds = chat(client, EXPLAIN_SYSTEM, user, EXPLAIN_SCHEMA, "analysis_explanation", 1400)
    record = {"prompt_revision": EXPLAIN_PROMPT_REVISION, "request": body, "raw_response": response, "latency_seconds": seconds}
    choice = response["choices"][0]
    try:
        parsed = json.loads(choice["message"]["content"])
    except (ValueError, KeyError) as exc:
        record["error"] = f"model output is not valid JSON: {exc}"
        return record
    checks, summary_unmatched = check_explanation(parsed, facts)
    record.update(parsed=parsed, finish_reason=choice.get("finish_reason"), checks=checks, summary_numbers_not_in_facts=summary_unmatched)
    return record


def route(request, base_url, model):
    client = Client(base_url, model)
    body, response, seconds = chat(client, ROUTE_SYSTEM, request, ROUTE_SCHEMA, "route", 200)
    plan = json.loads(response["choices"][0]["message"]["content"])
    if plan.get("command") not in COMMANDS:
        raise ValueError(f"model chose a command outside the allowlist: {plan.get('command')!r}")
    plan["top_n"] = min(max(int(plan.get("top_n") or 5), 1), 20)
    if plan.get("date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan["date"]):
        raise ValueError(f"model returned an invalid date: {plan['date']!r}")
    for key in ("base_run", "new_run"):
        if plan.get(key) and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", plan[key]):
            raise ValueError(f"model returned an invalid run id: {plan[key]!r}")
    return {"request": body, "raw_response": response, "latency_seconds": seconds, "plan": plan}


def summarize_attempts(files, facts):
    """Re-run the mechanical checks on saved explanation files (raw responses are not modified)."""
    rows = []
    for i, path in enumerate(files, start=1):
        record = json.loads(open(path, encoding="utf-8").read())
        if "parsed" not in record:
            rows.append({"file": str(path), "error": record.get("error")})
            continue
        checks, summary_unmatched = check_explanation(record["parsed"], facts)
        rows.append({"file": str(path), "prompt_revision": record.get("prompt_revision", 1), "findings": len(checks),
                     "findings_with_number": sum(c["claim_has_number"] for c in checks),
                     "findings_with_valid_evidence": sum(c["evidence_keys_found"] for c in checks),
                     "numbers_not_in_facts": sorted({n for c in checks for n in c["numbers_not_in_facts"]} | set(summary_unmatched)),
                     "latency_seconds": record["latency_seconds"], "usage": record["raw_response"].get("usage"), "checks": checks})
    return rows
