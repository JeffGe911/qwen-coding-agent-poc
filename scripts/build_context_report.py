"""Build evidence/context-validation/REPORT.md + report.json from the raw evidence of the context/output validation.

Numbers are recomputed from summary.json, run state, model responses, release manifests and server logs.
Sources outside evidence/context-validation: evidence/chip-yield-agent/ (original blind run) and evidence/serving/logs/.
Usage: python scripts/build_context_report.py
"""
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qwen_ops import ollama_log
from qwen_ops.validate import attempt_facts

EV = ROOT / "evidence" / "context-validation"
REL = ROOT / "deploy" / "releases"
CONFIGS = ["r1-7b-ctx4096", "r2-7b-ctx8192-np1", "r2b-7b-ctx8192-np1-out4096", "r1-restore"]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def truncated_output(run, attempt):
    """Diagnostics of a cut-off response. The code is decoded only to describe the failure; it is never offered as a proposal."""
    content = load(run / f"attempt-{attempt}" / "model-response.json")["choices"][0]["message"]["content"]
    i = content.find('"explanation"')
    out = {"explanation_offset_in_raw_json": i}
    try:
        code = json.loads(content[:i].rstrip().rstrip(",") + "}")["code"]
        out["decoded_code_chars"] = len(code)
        try:
            ast.parse(code)
            out["code_parses"] = True
        except SyntaxError as exc:
            out["code_parses"], out["code_error"] = False, f"{exc.msg}（code 第 {exc.lineno} 行）"
    except (ValueError, KeyError):
        out["decoded_code_chars"] = None
    text = content[i:].replace("\\n", " ")
    words = re.findall(r"[A-Za-z_'][A-Za-z_'-]*", text)
    grams = [" ".join(words[k:k + 8]) for k in range(max(0, len(words) - 7))]
    top = Counter(grams).most_common(1)
    out.update(explanation_words=len(words), distinct_8gram_ratio=round(len(set(grams)) / len(grams), 3) if grams else None)
    if top:
        phrase = top[0][0]
        out.update(top_phrase=phrase, top_phrase_non_overlapping=len(re.findall(re.escape(phrase), " ".join(words))))
    return out


def log_block(log, prompt_tokens):
    """Server-log lines of the request whose prompt had exactly prompt_tokens tokens (llama-server task.n_tokens)."""
    lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    starts = [k for k, line in enumerate(lines) if "new prompt" in line and f"task.n_tokens = {prompt_tokens}" in line]
    if len(starts) != 1:
        return {"found": len(starts)}
    task = re.search(r"task (\d+)", lines[starts[0]]).group(1)
    block = []
    for line in lines[starts[0]:]:
        if f"task {task} " in line:
            block.append(line)
            if "stop processing" in line:
                break
    text = "\n".join(block)
    speed = re.search(r"(?<!prompt )eval time =\s+[\d.]+ ms /\s+\d+ tokens \(\s*[\d.]+ ms per token,\s+([\d.]+) tokens per second\)", text)
    return {"found": 1, "task": int(task), "context_shift": text.count("slot context shift"), "truncated": "truncated = 1" in text,
            "eval_tokens_per_s": float(speed.group(1)) if speed else None}


def run_facts(cfg, task, gen, log):
    run = ROOT / gen["run"]
    state = load(run / "state.json")
    ctx = state["config"].get("context_tokens")
    budget = state["config"].get("max_tokens", 1600)
    attempts = [attempt_facts(run, a, ctx, budget) for a in state["attempts"]]
    for a in attempts:
        if a.get("finish_reason") == "length":
            a["truncated_output"] = truncated_output(run, a["attempt"])
        if a.get("prompt_tokens"):
            a["server_log"] = log_block(log, a["prompt_tokens"])
    last = state["attempts"][-1] if state["attempts"] else {}
    result = last.get("result")
    return {"config": cfg, "task": task, "run": gen["run"].replace("\\", "/"), "status": state["status"], "contract": state["config"]["contract"],
            "context_tokens": ctx, "max_tokens": budget, "max_tokens_recorded": "max_tokens" in state["config"], "attempts": attempts,
            "reviewer": last.get("reviewer"), "pytest": {k: result[k] for k in ("tests", "passed", "failures", "errors", "skipped")} if result else None,
            "approval_digest": last.get("digest") if state["status"] in ("awaiting_approval", "succeeded", "failed") else None,
            "peak_gpu_mib": (gen.get("gpu_during_run") or {}).get("peak_memory_used_mib")}


def service(summary, log):
    s = summary["service"]
    eff = s["effective"]
    compute = eff.get("inference_compute") or ""
    scan = ollama_log.scan_err(log)
    return {"status": s["status"], "ok": s["ok"], "golden": s["golden"], "residency": s["residency"],
            "gpu_at_health_mib": s["gpu_after_load"].get("memory_used_mib"), "restarted": "skipped" not in summary["restart"],
            "backend": re.search(r"library=(\w+)", compute).group(1) if "library=" in compute else None,
            "requested": summary["requested"], "effective": {k: eff[k] for k in ("llama_server_ctx_total", "llama_server_parallel", "n_ctx_seq", "n_seq_max", "offloaded_layers")},
            "log_counts": scan["counts"], "log_examples": scan["examples"]}


def verdict(a):
    if "prompt_tokens" not in a:
        return "无模型响应"
    parts = ["上下文溢出" if a["context_overflow"] else "上下文未溢出",
             "输出被截断（达到 max_tokens）" if a["finish_reason"] == "length" else f"输出正常结束（{a['finish_reason']}）",
             "JSON 合法" if a.get("json_ok") else "JSON 不完整"]
    if a.get("python_ok") is not None:
        parts.append("Python 可解析" if a["python_ok"] else f"Python 不可解析：{a.get('python_error')}")
    if a.get("policy_ok") is not None:
        parts.append("策略通过" if a["policy_ok"] else "策略拦截")
    return "；".join(parts)


def pre_restore():
    d = EV / "00-state-before-restore"
    rec = load(d / "ollama-launch-11437-20261023T210900Z.json")
    log = (EV / "server-logs" / "ollama-11437-20261023T210900Z.err.log").read_text(encoding="utf-8", errors="replace")
    compute = re.findall(r'msg="inference compute" .*?library=(\w+).*?description="([^"]+)"', log)
    smi = (d / "nvidia-smi.txt").read_text(encoding="utf-8", errors="replace")
    return {"pid": rec["pid"], "started_at_utc": rec["started_at_utc"], "extra_env": {k: v for k, v in rec["environment"].items() if not k.startswith("OLLAMA_")},
            "inference_compute": compute, "api_ps": load(d / "api-ps.json"), "nvidia_smi_used": re.findall(r"^(\d+) MiB, \d+ MiB, \d+ MiB", smi, re.M),
            "port_11435": (d / "port-11435-check.txt").read_text(encoding="utf-8").strip().splitlines()}


def history_split(hist):
    """Output tokens generated before/after the context shift of each original blind proposal.

    Where in the output the shift fell is estimated by character share (no tokenizer on this host).
    """
    rows = []
    run = ROOT / "evidence" / "chip-yield-agent" / "runs" / "20261023T200053Z-chip_final_yield-3d2bde61"
    for a in hist["attempts"]:
        shift = next(b["text"] for b in a["log"] if "context shift" in b["text"])
        stop = next(b["text"] for b in a["log"] if "stop processing" in b["text"])
        keep, left, discard = (int(re.search(rf"{k} = (\d+)", shift).group(1)) for k in ("n_keep", "n_left", "n_discard"))
        final = int(re.search(r"n_tokens = (\d+)", stop).group(1))
        at = keep + left
        before = at - a["prompt_tokens"]
        content = load(run / f"attempt-{a['attempt']}" / "model-response.json")["choices"][0]["message"]["content"]
        code_end = content.find('"explanation"')
        est = round(len(content) * before / a["completion_tokens"])
        row = {**{k: a[k] for k in ("attempt", "status", "prompt_tokens", "completion_tokens", "total", "finish_reason")},
               "n_discard": discard, "before_shift": before, "after_shift": final - (at - discard),
               "output_chars": len(content), "code_field_end_char": code_end, "shift_char_estimate": est}
        code = json.loads(content)["code"]
        try:
            ast.parse(code)
        except SyntaxError as exc:  # where the syntax error sits in the raw output, to compare with the shift estimate
            line = code.splitlines()[exc.lineno - 1]
            row["syntax_error"] = f"code 第 {exc.lineno} 行：{exc.msg}"
            row["syntax_error_char"] = content.find(json.dumps(line)[1:-1][:40])
        rows.append(row)
    return rows


def main():
    doc = {"configs": {}, "runs": []}
    for cfg in CONFIGS:
        summary = load(EV / cfg / "summary.json")
        log = EV / "server-logs" / summary["server_log"]
        doc["configs"][cfg] = {"note": summary.get("note"), "at_utc": summary["at_utc"], "server_log": summary["server_log"], "service": service(summary, log)}
        for task, gen in summary["generation"].items():
            if gen.get("run"):
                doc["runs"].append(run_facts(cfg, task, gen, log))
    manifests = {p.stem: load(p) for p in sorted(REL.glob("*.json"))}
    events = [json.loads(line) for line in (REL / "history.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    doc["releases"] = {"active": (REL / "ACTIVE").read_text(encoding="utf-8").strip(), "events": [(e["event"], e["name"]) for e in events if "name" in e],
                       "model_digests": sorted({m["model"]["digest"] for m in manifests.values()}), "quantization": sorted({m["model"]["quantization"] for m in manifests.values()})}
    doc["contracts"] = {"prompt_policy": sorted({(r["contract"]["prompt_sha256"], r["contract"]["policy_revision"], r["contract"]["policy_sha256"]) for r in doc["runs"]}),
                        "task_files_per_task": {t: len({json.dumps(r["contract"]["task_files_sha256"], sort_keys=True) for r in doc["runs"] if r["task"] == t})
                                                for t in sorted({r["task"] for r in doc["runs"]})}}
    doc["pre_restore"] = pre_restore()
    hist = load(ROOT / "evidence" / "chip-yield-agent" / "context-shift.json")
    doc["history"] = history_split(hist)
    gate_r1 = load(EV / "gate-r1-7b-ctx4096-adopted.json")
    doc["gate_r1"] = {"at_utc": gate_r1["at_utc"], "passed": gate_r1["passed"], "checks": gate_r1["checks"],
                      "proposals": [{k: p.get(k) for k in ("task", "usage", "context_ok", "json_ok", "policy_ok", "finish_reason")} for p in gate_r1["proposals"]]}
    doc["restore_verify"] = load(EV / "r1-restore" / "release-verify.json")
    (EV / "report.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rel = doc["releases"]
    one = lambda xs: xs[0] if len(xs) == 1 else f"不一致：{xs}"
    pp, tf = doc["contracts"]["prompt_policy"], doc["contracts"]["task_files_per_task"]
    same = len(pp) == 1 and all(n == 1 for n in tf.values())
    md = ["# 上下文溢出与输出截断：配置验证报告", "",
          "由 `python scripts/build_context_report.py` 从原始证据生成：本目录（各配置 summary.json、运行目录、server-logs/、logscan/、审批记录），"
          "以及 evidence/chip-yield-agent/（原盲测）和 evidence/serving/logs/（原服务日志）。", "",
          f"- 模型：qwen2.5-coder:7b，量化 {one(rel['quantization'])}，digest {one(rel['model_digests'])[:16]}…（各发布清单相同）",
          f"- 评测合同：本轮所有运行的 prompt_sha256 与策略{'相同' if len(pp) == 1 else '**不一致**'}"
          + (f"（prompt_sha256 {pp[0][0][:16]}…，策略修订 {pp[0][1]}）" if len(pp) == 1 else "")
          + f"，同一任务的冻结文件摘要{'相同' if all(n == 1 for n in tf.values()) else '**不一致**'}{'' if same else '（见 report.json）'}" +
          "。prompt_sha256 只覆盖系统提示词和输出 schema；用户消息里包含运行目录的绝对路径和 pytest 输出，所以各次 chip 提示词的 token 数不同，配置之间的对比不是逐字相同的输入。",
          f"- 发布：ACTIVE = {rel['active']}；历史事件 {rel['events']}（没有 activate 事件，即没有切换过）。", ""]

    pr = doc["pre_restore"]
    md += ["## 0. 本轮开始时的服务状态与恢复", "",
           f"- 11437 上运行的是隐藏 CUDA 的探索实例：pid {pr['pid']}，启动于 {pr['started_at_utc']}，额外环境 {pr['extra_env']}；服务日志选中的后端 {pr['inference_compute']}；"
           f"`/api/ps` = {json.dumps(pr['api_ps'])}（未加载模型）；nvidia-smi 已用 {pr['nvidia_smi_used']} MiB。没有在它上面跑过推理。",
           "- 处理：用 stop_ollama.ps1 停止，按 r1 设置重新启动（见 01-restore-gpu/）。第一次启动的调用方因句柄继承挂起、被强制结束，修复启动脚本后再次启动，正常返回。",
           f"- 旧的 11435 实例：00-state-before-restore/processes.txt（查询 11434–11437 端口，与同目录 nvidia-smi.txt 同时采集）中只有 11437 在监听；{pr['port_11435'][0].lstrip('# ').split(' ')[0]} 的只读检查结果为“{'；'.join(pr['port_11435'][1:])}”。退出原因未查明。", "",
           f"- 注意：§4 中“r1 门禁”是在隐藏 CUDA 实验之前（{doc['gate_r1']['at_utc']}，原实例 pid 60424，CUDA）跑的。", ""]

    md += ["## 1. 服务可用", "",
           "| 配置 | 请求的设置 | 实际生效（llama-server 日志 / `/api/ps`） | 后端 | GPU 驻留 | 固定答案 | 健康检查时显存 MiB | 运行期间峰值显存 MiB | 启动告警 | 结论 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for cfg, c in doc["configs"].items():
        s = c["service"]
        r, e = s["requested"], s["effective"]
        peaks = [x["peak_gpu_mib"] for x in doc["runs"] if x["config"] == cfg and x["peak_gpu_mib"]]
        warn = s["log_counts"].get("gpu_warning", 0)
        md.append(f"| {cfg} | 上下文 {r['context']} × 并行 {r['parallel']}，max_tokens {r['max_tokens']} | -c {e['llama_server_ctx_total']} -np {e['llama_server_parallel']}，"
                  f"n_ctx_seq {e['n_ctx_seq']}，n_seq_max {e['n_seq_max']}，context_length {s['residency'].get('context_length')}，层 {e['offloaded_layers']} | "
                  f"{s['backend']} | {s['residency'].get('gpu_fraction'):.0%} | {sum(1 for g in s['golden'] if g[2])}/{len(s['golden'])} 正确 | "
                  f"{s['gpu_at_health_mib']:.0f}{'' if s['restarted'] else '（未重启，模型已驻留）'} | {max(peaks):.0f} | "
                  f"{f'{warn} 行 GPU 发现告警' if warn else '无'} | {'正常' if s['ok'] else '**异常**'} |" if peaks else
                  f"| {cfg} | 上下文 {r['context']} × 并行 {r['parallel']}，max_tokens {r['max_tokens']} | -c {e['llama_server_ctx_total']} -np {e['llama_server_parallel']}，"
                  f"n_ctx_seq {e['n_ctx_seq']}，n_seq_max {e['n_seq_max']}，context_length {s['residency'].get('context_length')}，层 {e['offloaded_layers']} | "
                  f"{s['backend']} | {s['residency'].get('gpu_fraction'):.0%} | {sum(1 for g in s['golden'] if g[2])}/{len(s['golden'])} 正确 | "
                  f"{s['gpu_at_health_mib']:.0f} | — | {f'{warn} 行 GPU 发现告警' if warn else '无'} | {'正常' if s['ok'] else '**异常**'} |")
    cpu = [cfg for cfg, c in doc["configs"].items() if c["service"]["log_counts"]["cpu_offload"] or c["service"]["residency"].get("gpu_fraction") != 1.0]
    for cfg, c in doc["configs"].items():
        for line in c["service"]["log_examples"].get("gpu_warning", [])[:1]:
            md.append(f"\n{cfg} 的启动告警（第 {line['line']} 行）：`{line['text'][:200]}`；之后模型仍以 CUDA 加载 {c['service']['effective']['offloaded_layers']} 层。")
    md += ["", f"CPU 卸载：{'无' if not cpu else cpu}（按各配置日志的 offloaded 层数、cpu_offload 计数和 `/api/ps` 驻留比例）。"
           "r1 与 r2 的 KV 总量相同（4096 × 2 = 8192 × 1 = 8192 token），显存基本不变。r2 只有 1 个并行槽位，同时到达的第二个请求要排队；本轮没有做并发测试，"
           "表 2 中单请求耗时的差异不能只归因于上下文。", ""]

    md += ["## 2. 生成可用（每个提案单独判断）", "",
           "| 配置 | 任务 | 提案 | 提示词 + 输出 = 合计 / 上下文 | 输出预算 | finish_reason | 服务日志 context shift / truncated | 生成耗时 s | 生成速度 tok/s | 判断 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in doc["runs"]:
        for a in r["attempts"]:
            lb = a.get("server_log") or {}
            shift = f"{lb['context_shift']} / {'是' if lb['truncated'] else '否'}" if lb.get("found") == 1 else "未定位"
            md.append(f"| {r['config']} | {r['task']} | {a['attempt']} | {a.get('prompt_tokens')} + {a.get('completion_tokens')} = {a.get('total_tokens')} / {r['context_tokens']} | "
                      f"{r['max_tokens']}{'' if r['max_tokens_recorded'] else '（默认，未写入运行配置）'} | {a.get('finish_reason')} | {shift} | {a.get('generation_seconds')} | "
                      f"{lb.get('eval_tokens_per_s')} | {verdict(a)} |")
    md += ["", "r2b 的提案 2、3 是同一运行在 3 次提案预算内用 `python -m qwen_agent retry` 重新请求的结果，反馈里带上一次的截断错误，所以提示词每次多约 45 token。", "",
           "被截断的输出（JSON 不完整，不作为提案提取、不人工补写；下面对其中 code 字符串的解码和语法检查只用于描述失败）：", ""]
    for r in doc["runs"]:
        for a in r["attempts"]:
            t = a.get("truncated_output")
            if t:
                code = f"code 字符串已闭合，解码后 {t['decoded_code_chars']} 字符，" + ("可解析" if t.get("code_parses") else f"语法错误：{t.get('code_error')}")
                md.append(f"- {r['config']} 提案 {a['attempt']}：{code}；之后 explanation {t['explanation_words']} 词，不同 8 词片段占比 {t['distinct_8gram_ratio']}，"
                          f"最常见片段“{t['top_phrase']}”不重叠出现 {t['top_phrase_non_overlapping']} 次")
    md += ["", "本轮只有这一个任务、温度 0：在 1600 和 4096 两个预算下都退化成重复，没有证据表明继续加预算能解决。", ""]

    md += ["## 3. 业务正确（人工批准后的 pytest）", "", "| 配置 | 任务 | 最终状态 | 审批人 | pytest | 审批摘要 |", "|---|---|---|---|---|---|"]
    for r in doc["runs"]:
        py = r["pytest"]
        md.append(f"| {r['config']} | {r['task']} | {r['status']} | {r['reviewer'] or '—'} | "
                  f"{str(py['passed']) + '/' + str(py['tests']) if py else '未执行（没有可审批的提案）'} | {(r['approval_digest'] or '—')[:16]} |")
    md += ["", "批准在对话中给出，展示的差异、摘要和提问原文见 [approval-record.md](approval-record.md)，decide 命令随后代为执行（[approval-console.txt](approval-console.txt)）。"
           "report_pass_rate 的 21 个测试中有 12 个 holdout（任务说明；holdout 失败详情从不发给模型）。", ""]

    md += ["## 4. 历史失败的重新解读", "", "| 原盲测提案 | 提示词 + 输出 | finish_reason | context shift 前生成 | 丢弃 | shift 后生成 |", "|---|---|---|---|---|---|"]
    for h in doc["history"]:
        md.append(f"| {h['attempt']}（{h['status']}） | {h['prompt_tokens']} + {h['completion_tokens']} = {h['total']} | {h['finish_reason']} | {h['before_shift']} | {h['n_discard']} | {h['after_shift']} |")
    gp = {p["task"]: p for p in doc["gate_r1"]["proposals"]}
    md += [""]
    for h in doc["history"]:
        err = (f"；语法错误（{h['syntax_error']}）位于第 {h['syntax_error_char']} 字符，在估计的 shift 位置之{'后' if h['syntax_error_char'] > h['shift_char_estimate'] else '前'}"
               if h.get("syntax_error") else "")
        md.append(f"- 提案 {h['attempt']}：输出 {h['output_chars']} 字符，code 字段结束于第 {h['code_field_end_char']} 字符；按字符比例估计 shift 发生在第 {h['shift_char_estimate']} 字符附近{err}。")
    md += ["- 三份提案都没有达到输出预算，都在生成中途触发 context shift（丢弃提示词第 5 个 token 起的 2045 个 token）。按上面的估计，提案 1 的 code 字段大部分在 shift 之前生成，"
           "所以它 8/22 的结果主要不能用 context shift 解释。结论：原证据被 context shift 部分污染，不足以单独支持“7B 能力不够”，也不能反过来说失败只是配置问题（估计基于字符比例，本机没有分词器）。",
           f"- r1 门禁（{doc['gate_r1']['at_utc']}）：report_pass_rate 生成检查通过（上下文、JSON、策略；门禁不执行代码，没有跑 pytest）；chip_final_yield 提示词 "
           f"{gp['chip_final_yield']['usage']['prompt_tokens']} + 输出 {gp['chip_final_yield']['usage']['completion_tokens']}，context_ok={gp['chip_final_yield']['context_ok']}，"
           f"json_ok={gp['chip_final_yield']['json_ok']}（服务日志 evidence/serving/logs/ollama-11437-20261023T192809Z.err.log 中有对应的 context shift）。", ""]
    md += ["## 5. 恢复原配置", "",
           f"候选验证结束后按 r1 的设置重启：`python -m qwen_ops release verify --name r1-7b-ctx4096` 的差异为 {json.dumps(doc['restore_verify']['problems'], ensure_ascii=False)}；"
           f"实际生效 {json.dumps(doc['configs']['r1-restore']['service']['effective'], ensure_ascii=False)}。ACTIVE = {rel['active']}。", ""]
    (EV / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(EV / "REPORT.md")


if __name__ == "__main__":
    main()
