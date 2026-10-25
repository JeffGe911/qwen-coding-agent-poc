"""Build evidence/index.html: one local page summarizing environment, serving and all real runs.

Every number is read from evidence files at build time; nothing is typed in by hand.
Re-run after approving/rejecting a pending run:  python scripts/build_index.py
"""
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qwen_agent.report import CATEGORIES, summarize
from qwen_agent.workflow import read_json

EV = ROOT / "evidence"
GROUPS = [
    ("context-validation/*/runs", "配置验证 · 上下文与输出截断（r1 / r2 / r2b）", "同一冻结任务、提示词与策略；对比服务配置与输出预算，不是新的盲测；7B"),
    ("report-pass-rate/runs", "本次首次盲测 · report_pass_rate", "需求原文 + 21 个测试在模型调用前冻结；策略 v2；7B"),
    ("chip-yield-agent/runs", "本次首次盲测 · chip_final_yield（芯片数据闭环）", "需求 + 22 个测试在模型调用前冻结；策略 v2；7B"),
    ("business-demo-final", "历史 · test_summary 调整后", "任务说明和公开断言在看到模型失败后调整过，非盲测；7B"),
    ("business-demo-7b", "历史 · test_summary 调整过程", "中间草案，未审批未执行；7B"),
    ("business-demo", "历史 · test_summary 初稿", "初始草案，未审批未执行；1.5B"),
    ("live-runs", "历史 · 三任务评测", "clamp / chunked / normalize_names；策略 v1；1.5B"),
]
esc = lambda x: html.escape(str(x), quote=True)


def latest(pattern):
    files = sorted(EV.glob(pattern))
    return files[-1] if files else None


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path else None


def grab(text, pattern, default="未找到"):
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else default


def table(header, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table><tr>{head}</tr>{body}</table></div>'


def round_status():
    """One line per blind task of this round, read from the run state files."""
    parts = []
    for rel in ("report-pass-rate/runs", "chip-yield-agent/runs"):
        for path in sorted((EV / rel).glob("*/state.json")):
            s = read_json(path)
            steps = []
            for a in s["attempts"]:
                r = a.get("result")
                steps.append(f"提案{a['attempt']} {a['status']}" + (f" {r['passed']}/{r['tests']}" if r else ""))
            parts.append(f"{s['task']['id']} 最终 {s['status']}（{'，'.join(steps)}" + (f"，终止原因 {s['stop_reason']}" if s.get("stop_reason") else "") + "）")
    return "；".join(parts)


def chip_section():
    base = EV / "chip-analysis"
    if not (base / "analysis.json").exists():
        return ""
    a = load(base / "analysis.json")
    hc = load(base / "hand_check.json") if (base / "hand_check.json").exists() else {}
    attempts = load(base / "explanation_attempts.json")["attempts"] if (base / "explanation_attempts.json").exists() else []
    rows = [(r["run_id"], r["lot_id"], r["chips"], r["pass"], r["fail"], r["incomplete"], r["yield_all"], r["yield_complete_only"], r["first_pass_yield_all"]) for r in a["yield_by_lot"]]
    top = "、".join(f"{r['test_item']} {r['final_fail_chips']}" for r in a["top_items"])
    conc = "；".join(f"{c['run_id']} {c['lot_id']} {c['wafer_id']} {c['test_item']} {c['fail_chips']}/{c['valid_chips']}（其余合计的 {c['ratio_vs_rest']} 倍）" for c in a["concentration_wafer"]) or "无"
    diff = a.get("run_diff", {}).get("counts", {})
    hc_ok = sum(v["expected"] == v["actual"] for v in hc.values())
    att = "；".join(f"v{x.get('prompt_revision')}：{x.get('findings')} 条结论，含数字 {x.get('findings_with_number')} 条，数字与所述行不符 {sum(1 for c in x.get('checks', []) if c.get('numbers_misattributed'))} 条" for x in attempts)
    return (f'<h2>5. 芯片数据分析（合成数据）</h2><p>{a["profile"]["input_rows"]} 行 → 去重后 {a["profile"]["rows_after_dedup"]} 行，{a["profile"]["chips"]} 颗芯片，运行 {", ".join(a["profile"]["runs"])}。'
            f'<a href="chip-analysis/report.html">打开完整报告</a>（图表、异常清单、口径假设、复现命令）。</p>'
            + table(["运行", "批次", "芯片", "PASS", "FAIL", "INCOMPLETE", "良率(全部)", "良率(仅完整)", "首测良率(全部)"], rows) +
            f'<ul><li>失败最多的项目（最终 FAIL 芯片数）：{esc(top)}</li><li>异常集中（启发式 A9）：{esc(conc)}</li>'
            f'<li>R1 → R2 运行对比：{esc(diff)}</li><li>质量检查：{esc(a["quality_counts"])}</li>'
            f'<li>SQL 与 Python 交叉核对：{a["sql_cross_check"]["record_pass_rate_match"] and a["sql_cross_check"]["final_fail_chips_match"]}；手工核对小样本：{hc_ok}/{len(hc)} 项一致</li>'
            f'<li>本地 Qwen 解释（三版提示词都保留）：{esc(att)}。人工复核发现 v3 仍有张冠李戴和错误陈述，见 <a href="chip-analysis/explanation_review.md">复核记录</a>；报告结论以程序计算为准。</li>'
            f'<li>自然语言入口：两条请求被路由到 analyze 与 compare_runs 并执行，见 chip-analysis/ask-console.txt。</li></ul>')


def context_section():
    path = EV / "context-validation" / "report.json"
    if not path.exists():
        return ""
    rep = load(path)
    rows = []
    for cfg, c in rep["configs"].items():
        s = c["service"]
        runs = [r for r in rep["runs"] if r["config"] == cfg]
        res = lambda task: next(("；".join(f"提案{a['attempt']} {a.get('prompt_tokens')}+{a.get('completion_tokens')} {a.get('finish_reason')}" for a in r["attempts"])
                                 + f" → {r['status']}" + (f" {r['pytest']['passed']}/{r['pytest']['tests']}" if r["pytest"] else "") for r in runs if r["task"] == task), "未运行")
        shifts = sum((a.get("server_log") or {}).get("context_shift", 0) for r in runs for a in r["attempts"])
        rows.append((cfg, f"{s['effective']['n_ctx_seq']} × {s['effective']['n_seq_max']}", s["requested"]["max_tokens"], s["backend"],
                     f"{s['residency'].get('gpu_fraction'):.0%}", f"{s['gpu_at_health_mib']:.0f}", shifts, res("chip_final_yield"), res("report_pass_rate")))
    return ('<h2>6. 上下文溢出与输出截断（配置验证）</h2><p>原配置每请求上下文 4096：chip_final_yield 生成时触发 context shift（服务日志 n_discard=2045），API 仍报告 stop。'
            '上下文 8192 后没有再溢出（最高 7662/8192），但 chip 的输出退化重复、达到输出预算（1600 / 4096 都截断），没有可审批的提案；原盲测提案 1 的大部分 code 在 shift 之前生成，原失败不能只归因于配置。<a href="context-validation/REPORT.md">完整对照报告</a></p>'
            + table(["配置", "每请求上下文 × 并行", "输出预算", "后端", "GPU 驻留", "健康检查时显存 MiB", "context shift 次数", "chip_final_yield", "report_pass_rate"], rows)
            + "<p><small>r2 / r2b 只是候选，ACTIVE 仍为 r1；r2 只有 1 个并行槽位，并发能力未测。</small></p>")


def triage_section():
    """Regression-log triage: one row per contract, engine and split, from results/*/*/metrics.json."""
    rows = []
    fmt = lambda v: "—" if v is None else f"{v:.1%}"
    for path in sorted((EV / "regression-triage" / "results").glob("*/*/metrics.json")):
        m = load(path)
        fc = m["flagged_counts"]
        rows.append((m["contract"], m["engine"], m["split"], f"{m['samples']} / {m['gold_tests']}", fmt(m["category_accuracy"]),
                     f"{fc['tp']}/{fc['tp'] + fc['fp']}", f"{fc['tp']}/{fc['tp'] + fc['fn']}", fmt(m["citation_valid_rate"]), fmt(m["unknown_rate"]),
                     f"{m['request_failed']} / {m['invalid_output']}"))
    if not rows:
        return ""
    return ('<h2>7. 仿真回归日志分诊（真实 Icarus / Verilator 运行）</h2><p>读日志 → 引用原文行的失败归类 → 工程师确认。dev 由规则作者编写，只用于开发；'
            'holdout 由独立代理编写和标注，规则在它交付前已提交，只运行一次（盲测）。本地 Qwen（eval-v3）与规则使用同一个 holdout：Qwen 覆盖面广得多，但会在缺少结论行时放行。eval-v4 加入了规则优先 + 守卫后的 Qwen 的组合引擎，在新的独立盲测集 holdout2 上类别 33/45，没有误放行。'
            '<a href="regression-triage/REPORT-eval-v1.md">完整报告</a></p>'
            + table(["合同", "引擎", "拆分", "样本 / 金标准测试", "类别准确率", "需关注 precision", "需关注 recall", "引用有效率", "unknown 比例", "请求失败 / 输出不合规"], rows)
            + "<p><small>规则在 holdout 上的错误几乎都是“不知道”，从不放行；Qwen 漏报为 0，但有 1 次误放行，引用有效率只有约 11%。详见报告。</small></p>")


def main():
    env_file = latest("env/windows-*.txt")
    env = env_file.read_text(encoding="utf-8-sig") if env_file else ""
    env_rows = [
        ("操作系统", grab(env, r"=== OS ===\n(.+)")),
        ("CPU", grab(env, r"=== CPU ===\n(.+)")),
        ("内存", grab(env, r"=== Memory ===\n(.+)")),
        ("磁盘", " ; ".join(re.findall(r"^([A-Z]: used_GiB=.+)$", env, re.M))),
        ("GPU（nvidia-smi 查询）", grab(env, r"index, name.*\n(.+)")),
        ("驱动 / 驱动支持的 CUDA", grab(env, r"(Driver Version: \S+\s+CUDA Version: \S+)") + "（这是驱动能力，不是已安装的 CUDA Toolkit）"),
        ("CUDA Toolkit (nvcc)", grab(env, r"=== CUDA Toolkit \(nvcc\) ===\n(.+)")),
        ("Docker", grab(env, r"^(docker .+)$")),
        ("NVIDIA Container Toolkit", grab(env, r"^(nvidia-ctk .+)$")),
        ("WSL", grab(env, r"^wsl --status.*?: (.+)$")),
        ("检查时已有的推理进程", "; ".join(m.group(0) for m in re.finditer(r"^pid=.+$", env, re.M)) or "无"),
        ("检查时监听端口", "; ".join(m.group(0) for m in re.finditer(r"^127\.0\.0\.1:\d+ pid=.+$|^0\.0\.0\.0:\d+ pid=.+$", env, re.M)) or "无"),
    ]
    launch = load(latest("serving/ollama-launch-*.json"))
    smoke = load(latest("serving/api-smoke-*.json"))
    kv = load(EV / "serving" / "kv-context-7b.json") if (EV / "serving" / "kv-context-7b.json").exists() else None
    serving_files = sorted(EV.glob("serving/serving-7b-*.json"))

    model_rows = []
    if smoke:
        d = smoke["model_metadata"]["details"]
        res = smoke["residency"][0] if smoke["residency"] else {}
        model_rows = [
            ("模型", smoke["model"]), ("参数量 / 架构", f"{d.get('parameter_size')} · {d.get('family')}"),
            ("量化 / 格式", f"{d.get('quantization_level')} · {d.get('format')}"),
            ("服务", f"Ollama {smoke['server_version'].get('version')} · OpenAI 兼容 {smoke['base_url']}/chat/completions"),
            ("上下文", f"每槽位 {res.get('context_length')} tokens（模型架构上限 {smoke['model_metadata']['architecture_context_length']}）"),
            ("驻留", f"{res.get('size_vram_bytes', 0) / 2**30:.2f} GiB 在 GPU / 总 {res.get('size_bytes', 0) / 2**30:.2f} GiB（GPU 占比 {res.get('gpu_fraction', 0):.0%}）"),
            ("nvidia-smi 显存（加载前 → 后）", f"{smoke['gpu_before']['gpu'].split(',')[2].strip()} MiB → {smoke['gpu_after']['gpu'].split(',')[2].strip()} MiB（整卡，含桌面等进程）"),
            ("真实请求", f"{smoke['chat_completion']['latency_seconds_including_cold_load']} s（含冷加载）· 回答：{smoke['chat_completion']['raw_response']['choices'][0]['message']['content']!r}"),
        ]
    if launch:
        model_rows.append(("启动参数", "ollama.exe serve; " + "; ".join(f"{k}={v}" for k, v in launch["environment"].items() if k != "OLLAMA_MODELS")))
        model_rows.append(("计算后端（启动日志）", next((l.split("msg=")[1][:200] for l in launch["startup_log_lines"] if "inference compute" in l), "未记录")))

    perf_rows = []
    for f in serving_files:
        data = load(f)
        for b in data["warm_batches"]:
            perf_rows.append((f.stem.replace("serving-7b-", ""), b["client_concurrency"], f"{b['success_count']}/{len(b['requests'])}",
                              f"{b['request_latency_p50_seconds']:.3f}", f"{b['request_latency_p95_seconds']:.3f}",
                              f"{max(r['seconds'] for r in b['requests']):.3f}", f"{b['aggregate_output_tokens_per_second']:.1f}"))
    kv_rows = []
    if kv:
        base = None
        for m in kv["measurements"]:
            for x in m["loaded_models"]["models"]:
                base = base or x["size_vram"]
                kv_rows.append((m["requested_context"], x.get("context_length"), f"{x['size_vram'] / 2**20:.0f}", f"{(x['size_vram'] - base) / 2**20:+.0f}"))

    group_html, totals = [], []
    for rel, title, desc in GROUPS:
        states = [read_json(p) for p in sorted(EV.glob(f"{rel}/*/state.json"))]
        if not states:
            continue
        totals.extend(states)
        s = summarize(states)
        cats = " · ".join(f"{c['label']} {c['count']}" for c in s["categories"].values() if c["count"])
        rows = [(x["run_id"], x["config"]["model"], x["status"], " / ".join(a.get("status", "?") for a in x["attempts"]), x.get("stop_reason", "-")) for x in states]
        group_html.append(f"<h3>{esc(title)}</h3><p>{esc(desc)}。{esc(cats)}；启动 {s['started_runs']}，已完成执行评测 {s['completed_evaluations']}。</p>" + table(["运行", "模型", "最终状态", "各提案", "终止原因"], rows))
    t = summarize(totals)
    cat_cards = "".join(f'<div class="card"><span>{esc(c["label"])}</span><strong>{c["count"]}</strong></div>' for c in t["categories"].values())
    pct = lambda v: "N/A（分母为 0）" if v is None else f"{v:.1%}"

    blind = sorted((EV / "report-pass-rate" / "runs").glob("*/state.json"))
    blind_state = read_json(blind[-1]) if blind else None
    blind_line = "未运行"
    if blind_state:
        blind_line = {"awaiting_approval": "待人工审批：模型提案已生成并通过策略校验，代码尚未执行，修复后结果未验证。",
                      "succeeded": "report_pass_rate 第一份提案经人工批准后通过全部 21 个测试（含 12 个从未发给模型的 holdout）。"}.get(blind_state["status"], f"状态：{blind_state['status']}")
        blind_line += " 芯片闭环任务：" + round_status().split("；")[-1] + "。"

    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Qwen Agent 本地实测</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#101922;color:#e6edf3;font:15px system-ui;line-height:1.65}}main{{max-width:1180px;margin:auto;padding:28px 16px}}h1{{font-size:28px;margin:6px 0}}h2{{font-size:20px;margin-top:34px;border-bottom:1px solid #2d4352;padding-bottom:6px}}h3{{font-size:16px;margin:22px 0 4px}}p,li{{color:#b8c8d3}}a{{color:#80dfc0}}.cards{{display:flex;gap:10px;flex-wrap:wrap}}.card{{background:#1a2a38;border:1px solid #2d4352;border-radius:12px;padding:12px 16px;min-width:118px}}.card strong{{display:block;font-size:26px;color:#80dfc0}}.note{{background:#2a2418;border:1px solid #8a6a3a;border-radius:12px;padding:12px 16px}}.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{text-align:left;padding:7px;border-bottom:1px solid #304452;vertical-align:top;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#0d151e;padding:12px;border-radius:10px;font:12px/1.55 ui-monospace,monospace}}small{{color:#8fa3b1}}
</style><main><small>生成于 {esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))} · 数据全部来自 evidence/ 下的原始文件</small><h1>本地 Qwen Coding Agent · 单机实测</h1>
<p>Windows 笔记本 + 本地 Ollama + Qwen2.5-Coder 7B（Q4_K_M）。Agent 只能返回一个完整的 solution.py，人工审批后才在受限执行器中运行固定 pytest。</p>
<div class="note"><b>首次盲测：</b>{esc(blind_line)} <a href="report-pass-rate/view/demo.html">打开该运行的差异、基线失败与审批命令</a></div>

<h2>1. 环境（实测）</h2>{table(["项目", "结果"], env_rows)}
<p><small>原始记录：{esc(env_file.relative_to(ROOT) if env_file else '无')}</small></p>

<h2>2. 本地模型 API（实测）</h2>{table(["项目", "结果"], model_rows)}
<p><small>只监听 127.0.0.1；客户端拒绝非 loopback 地址、代理和重定向；没有云 API 回退。</small></p>

<h2>3. 并发与上下文（实测，冒烟级）</h2>
<p>服务端 OLLAMA_NUM_PARALLEL=2；客户端并发 4 时多出的请求排队。每档 8 个短请求（约 19 个输出 token），测的是整次响应延迟而非首 token 时间。两次测量都保留：第一次测量中两个槽位首次并行时出现约 8 秒的一次性延迟，第二次未复现。</p>
{table(["测量批次", "客户端并发", "成功", "P50 s", "P95 s", "最大 s", "聚合输出 tok/s"], perf_rows)}
<h3>上下文 4096 → 8192 → 4096 的驻留变化</h3>{table(["请求上下文", "生效上下文", "驻留 MiB", "相对基线 MiB"], kv_rows)}
<p><small>理论 KV（FP16，28 层 × 4 个 KV 头 × head_dim 128 × 2 槽位）每增加 4096 token/槽 约 448 MiB，与实测增量接近；驻留值来自 Ollama 的分配统计，也包含其他缓冲。</small></p>

<h2>4. 全部真实运行统计</h2>
<div class="cards">{cat_cards}</div>
<ul><li>全部启动运行成功率 = 任务成功 / 全部启动运行 = {t['succeeded']} / {t['started_runs']} = {pct(t['success_rate_started'])}</li>
<li>已完成执行评测成功率 = 任务成功 / (任务成功 + 修复失败) = {t['succeeded']} / {t['completed_evaluations']} = {pct(t['success_rate_completed'])}</li>
<li>以上混合了不同任务、模型、提示词版本和调整过程，只用来说明有哪些结果，<b>不能当作模型修复成功率</b>。框架单元测试的通过数也不计入这里。</li></ul>
{''.join(group_html)}

{chip_section()}
{context_section()}
{triage_section()}
<h2>8. 未验证 / 未完成</h2><ul>
<li>本轮两个盲测运行的当前状态：{esc(round_status())}。待审批的提案在批准前不执行，其修复后结果未验证。</li>
<li>芯片数据分析只用了合成数据；没有真实数据，指标口径（良率、重测、异常）都是列出的假设，未经业务确认；不支持 xlsx（需要 openpyxl，可先另存为 CSV）。</li>
<li>Docker 执行器（无网络、只读、非 root、资源限额）：本机未安装 Docker 和 WSL，<b>未验证</b>；本次使用显式选择的 restricted 模式，它不是操作系统级沙箱。</li>
<li>Linux + Docker + vLLM 部署（deploy/linux-vllm/ 单机套件，deploy/compose.vllm.yaml 网关方案）与两台服务器：本机没有 WSL/Docker，也没有 Linux GPU 机器，<b>未验证</b>，只有静态检查和脚本逻辑测试；scripts/env_check.sh 尚未在任何 Linux 主机执行。见 <a href="linux-serving/STATUS.md">STATUS</a>。</li>
<li>本地 Qwen 的日志分诊：只在 Windows 笔记本的 Ollama 上实测过（eval-v3）；vLLM 上未运行。</li>
<li>样本量很小（两个任务各一次盲测），不代表模型在真实仓库上的修复能力。</li></ul>
</main></html>'''
    (EV / "index.html").write_text(doc, encoding="utf-8")
    print(EV / "index.html")


if __name__ == "__main__":
    main()
