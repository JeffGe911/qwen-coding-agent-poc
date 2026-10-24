"""Build evidence/chip-rev2/REPORT.md + report.json for evaluation contract chip_final_yield/rev2.

Every number is recomputed from the raw evidence: run state, model responses, pytest results, the calls.jsonl
server-log windows and the server logs. Only the conclusion (conclusion.md) is written by hand, after the numbers.
Usage: python scripts/build_chip_rev2_report.py
"""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qwen_agent.generation import parse
from qwen_agent.policy import PolicyError, validate

EV = ROOT / "evidence" / "chip-rev2"
CONTRACT = ROOT / "qwen_agent" / "contracts" / "chip_final_yield" / "rev2.json"
ARMS = ["control", "A", "B", "C"]
LABEL = {"control": "rev 1 基线（对照组，rev 2 通道重跑）", "A": "A 输出格式", "B": "B 采样", "C": "C 模型 14b"}
WORD = re.compile(r"[A-Za-z_'][A-Za-z_'-]*")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def repetition(text, threshold):
    words = WORD.findall(text.replace("\\n", " "))
    grams = [" ".join(words[k:k + 8]) for k in range(max(0, len(words) - 7))]
    if not grams:
        return {"detected": False, "top": 0, "distinct_ratio": None, "phrase": None}
    phrase, _ = Counter(grams).most_common(1)[0]
    top = len(re.findall(re.escape(phrase), " ".join(words)))
    return {"detected": top >= threshold, "top": top, "distinct_ratio": round(len(set(grams)) / len(grams), 3), "phrase": phrase}


def log_requests(log, start, end):
    """Generation requests in a server-log window: prompt size, effective sampler values, context shift, truncation."""
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()[start:end]
    reqs, sampler = [], {}
    for k, line in enumerate(lines):
        m = re.search(r"repeat_penalty = ([\d.]+)", line)
        if m:
            sampler["repeat_penalty"] = float(m.group(1))
        m = re.search(r"top_p = ([\d.]+).*temp = ([\d.]+)", line)
        if m:
            sampler.update(top_p=float(m.group(1)), temperature=float(m.group(2)))
        if "sampler chain" in line:
            sampler["chain_end"] = line.strip().split("-> ")[-1]
        m = re.search(r"task (\d+) \| new prompt.*task\.n_tokens = (\d+)", line)
        if m:
            task = m.group(1)
            block = [l for l in lines[k:] if f"task {task} " in l]
            stop = next((i for i, l in enumerate(block) if "stop processing" in l), len(block) - 1)
            block = block[:stop + 1]
            reqs.append({"task": int(task), "prompt_tokens": int(m.group(2)), "sampler": dict(sampler),
                         "context_shift": sum("slot context shift" in l for l in block), "truncated": any("truncated = 1" in l for l in block)})
    return reqs


def attempts_of(arm, rule):
    runs = sorted((EV / arm / "runs").glob("*")) if (EV / arm / "runs").exists() else []
    if not runs:
        return None, []
    run = runs[-1]
    state = load(run / "state.json")
    calls = [json.loads(l) for l in (EV / arm / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    reqs = [r for c in calls for r in log_requests(EV / "server-logs" / c["server_log"]["file"], c["server_log"]["start_line"], c["server_log"]["end_line"])]
    fmt = state["config"]["generation"]["format"]
    rows = []
    for a in state["attempts"]:
        folder = run / f"attempt-{a['attempt']}"
        row = {"attempt": a["attempt"], "agent_status": a["status"], "agent_error": a.get("error")}
        resp_path = folder / "model-response.json"
        if resp_path.exists():
            resp = load(resp_path)
            text = resp["choices"][0]["message"]["content"]
            u = resp.get("usage") or {}
            native = resp.get("native") or {}
            row.update(finish_reason=resp["choices"][0]["finish_reason"], prompt_tokens=u.get("prompt_tokens"), completion_tokens=u.get("completion_tokens"),
                       repetition=repetition(text, rule["threshold"]),
                       tokens_per_s=round(native["eval_count"] / (native["eval_duration"] / 1e9), 1) if native.get("eval_duration") else None)
            match = [r for r in reqs if r["prompt_tokens"] == u.get("prompt_tokens")]
            row["server"] = match[0] if len(match) == 1 else {"matches": len(match)}
            try:
                proposal, facts = parse(fmt, text)
                if fmt == "fenced_v1":  # the runtime counter took list markers ("1.") for sentences; recount for the report
                    facts = {**facts, "explanation_sentences_runtime": facts["explanation_sentences"], "explanation_sentences": sentences(proposal["explanation"])}
                    facts["explanation_cap_respected"] = facts["explanation_sentences"] <= 3
                row.update(format_ok=True, format_facts=facts)
                try:
                    ast.parse(proposal["code"])
                    row["python_ok"] = True
                except SyntaxError as exc:
                    row.update(python_ok=False, python_error=f"{exc.msg} (line {exc.lineno})")
                try:
                    validate(proposal["code"])
                    row["policy_ok"] = True
                except PolicyError as exc:
                    row.update(policy_ok=False, policy_error=str(exc)[:160])
            except (ValueError, KeyError) as exc:
                row.update(format_ok=False, format_error=str(exc)[:160])
        result = a.get("result")
        if result:
            row["pytest"] = {"visible": result.get("visible"), "holdout": result.get("holdout"), "total": f"{result['passed']}/{result['tests']}",
                             "reviewer": a.get("reviewer"), "digest": a.get("digest")}
        rows.append(row)
    return {"run": run.relative_to(ROOT).as_posix(), "status": state["status"], "stop_reason": state.get("stop_reason"), "model": state["config"]["model"],
            "generation": state["config"]["generation"], "contract_revision": state["config"].get("contract_revision")}, rows


def sentences(text):
    """Sentences of an explanation; bare list markers such as "1." are not sentences."""
    return len([x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x.strip() and not re.fullmatch(r"\d+\.|[-*]", x.strip())])


VERDICT = {"model_error": "model_error（未进入审批）", "policy_blocked": "策略拦截（自动重新提案）", "no_change": "no_change（与当前代码相同，运行停止）",
           "duplicate": "重复提案（运行停止）", "awaiting_approval": "待审批", "passed": "批准 → pytest 通过", "failed": "批准 → pytest 未通过", "rejected": "人工拒绝"}


def cell(v, ok="✓", bad="✗"):
    return "—" if v is None else ok if v else bad


def main():
    contract = load(CONTRACT)
    rule = {"threshold": 5, "text": contract["repetition_rule"]["definition"]}
    doc = {"contract": {"id": contract["id"], "sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest()}, "arms": {}}
    for arm in ARMS:
        meta, rows = attempts_of(arm, rule)
        doc["arms"][arm] = {"meta": meta, "attempts": rows, "changes": contract["arms"][arm]["changes_vs_rev1"]}
    vram_dir = EV / "C" / "vram-check"
    doc["C_vram"] = {p.name: load(p) for p in sorted(vram_dir.glob("*.json"))} if vram_dir.exists() else None
    doc["transport_equivalence"] = load(EV / "00-transport-equivalence" / "result.json")
    (EV / "report.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    eq = doc["transport_equivalence"]
    md = ["# chip_final_yield 评测合同 rev 2：单变量对照", "",
          f"合同 `{contract['id']}`（qwen_agent/contracts/chip_final_yield/rev2.json，sha256 {doc['contract']['sha256'][:16]}…），在任何一组运行前提交冻结。"
          "任务文件、公开测试、holdout、策略与 rev 1 相同；服务为 r2（每请求上下文 8192，1 个槽位）；每组一个运行，最多 3 次提案，规则同 rev 1。"
          "表中数字由 `python scripts/build_chip_rev2_report.py` 从原始证据计算。", "",
          f"- 通道等价性：同一份 rev 1 请求，经原生接口 + 对照组参数与经 /v1 重发的输出逐字相同（{eq['identical_text']['native_control vs replay_v1']}）；"
          f"与一天前的原记录从第 {eq['first_differing_char']['replay_v1 vs recorded']} 字符起不同（提示词缓存状态不同），温度 0 也不是严格可复现。",
          f"- 重复判定（运行前冻结）：{rule['text']}，阈值 {rule['threshold']} 次。", "",
          "| 组 | 提案 | finish_reason | 提示词 + 输出 | context shift | 重复（最多片段次数） | 格式 | Python | 策略 | Agent 判定 | 公开测试 | holdout | 实际生效 temp / repeat_penalty |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        a = doc["arms"][arm]
        if not a["attempts"]:
            v = doc["C_vram"] or {}
            reason = v.get("06-decision.json", {}).get("decision", "未运行")
            md.append(f"| {LABEL[arm]} | — | 未运行：{reason} | | | | | | | | | | |")
            continue
        for r in a["attempts"]:
            s = r.get("server") or {}
            sam = s.get("sampler", {})
            rep = r.get("repetition") or {}
            py = r.get("pytest") or {}
            fmt = "✓" if r.get("format_ok") else ("✗ " + (r.get("format_error") or "")[:40] if "format_ok" in r else "—")
            if r.get("format_facts", {}).get("explanation_sentences") is not None:
                fmt += f"（解释 {r['format_facts']['explanation_sentences']} 句{'，超过 3 句' if not r['format_facts']['explanation_cap_respected'] else ''}）"
            md.append(f"| {LABEL[arm] if r['attempt'] == 1 else ''} | {r['attempt']} | {r.get('finish_reason')} | "
                      f"{r.get('prompt_tokens')} + {r.get('completion_tokens')} | {s.get('context_shift', '未定位')} | "
                      f"{'是' if rep.get('detected') else '否'}（{rep.get('top')}） | {fmt} | {cell(r.get('python_ok'))}"
                      f"{'（' + r['python_error'] + '）' if r.get('python_error') else ''} | {cell(r.get('policy_ok'))}{'（' + r['policy_error'][:40] + '）' if r.get('policy_error') else ''} | {VERDICT.get(r['agent_status'], r['agent_status'])} | "
                      f"{str(py['visible']['passed']) + '/' + str(py['visible']['tests']) if py.get('visible') else '未执行'} | "
                      f"{str(py['holdout']['passed']) + '/' + str(py['holdout']['tests']) if py.get('holdout') else '未执行'} | "
                      f"{sam.get('temperature')} / {sam.get('repeat_penalty')} |")
    md += ["", "各组只改一个变量（相对 rev 1）：" + "；".join(f"{LABEL[a]} = {doc['arms'][a]['changes']}" for a in ARMS) + "。",
           "“未执行”：该提案没有进入审批（输出截断、格式/策略未通过或与当前代码相同）。holdout 结果只用于评测，从不反馈给模型。"
           "原始有缺陷代码的成绩是 4/22（公开 2/11、holdout 2/11）。", ""]
    md += ["## 各组汇总（由上表计算）", ""]
    for arm in ARMS:
        rows = doc["arms"][arm]["attempts"]
        if not rows:
            continue
        rep = sum(1 for r in rows if (r.get("repetition") or {}).get("detected"))
        stop = sum(1 for r in rows if r.get("finish_reason") == "stop")
        approvable = sum(1 for r in rows if r["agent_status"] in ("awaiting_approval", "passed", "failed", "rejected"))
        speeds = [r["tokens_per_s"] for r in rows if r.get("tokens_per_s")]
        best = max((r["pytest"]["total"] for r in rows if r.get("pytest")), default="—", key=lambda t: int(t.split("/")[0]) if t != "—" else -1)
        md.append(f"- {LABEL[arm]}：{len(rows)} 次提案，重复 {rep} 次，正常结束 {stop} 次，进入审批 {approvable} 次，批准后最好的 pytest {best}；平均生成速度 {round(sum(speeds) / len(speeds), 1) if speeds else '—'} token/s；"
                  f"运行最终状态 {doc['arms'][arm]['meta']['status']}。")
    prev = load(ROOT / "evidence" / "context-validation" / "report.json")
    prev_speeds = [a["server_log"]["eval_tokens_per_s"] for r in prev["runs"] if r["config"] != "r1-restore" for a in r["attempts"]
                   if (a.get("server_log") or {}).get("eval_tokens_per_s")]
    today = [r["tokens_per_s"] for arm in ("control", "A", "B") for r in doc["arms"][arm]["attempts"] if r.get("tokens_per_s")]
    if prev_speeds and today:
        md += ["", f"生成速度口径：本轮取原生响应的 eval_count / eval_duration。本轮 7b 为 {min(today)}–{max(today)} token/s，"
                   f"上一轮（evidence/context-validation，同一模型、同一服务配置）的服务日志是 {min(prev_speeds)}–{max(prev_speeds)} token/s。"
                   "今天的服务日志 eval time 与本轮数值一致，说明是机器状态不同（原因未查明），不是测量口径不同。所以只比较同一天测得的 7b 与 14b。"]
    if doc["C_vram"]:
        md += ["", "C 组显存检查（evidence/chip-rev2/C/vram-check/）：" + json.dumps(doc["C_vram"].get("06-decision.json", {}), ensure_ascii=False)]
    concl = EV / "conclusion.md"
    md += ["", "## 结论（人工撰写，依据上表）", "", concl.read_text(encoding="utf-8").strip() if concl.exists() else "（待写）"]
    (EV / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(EV / "REPORT.md")


if __name__ == "__main__":
    main()
