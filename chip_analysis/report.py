"""Static HTML + Markdown report from analysis.json (and explanation.json when present)."""
import html
import json
from pathlib import Path

from .charts import CHART_CSS
from .pipeline import build_charts
from .quality import RULES

esc = lambda x: html.escape("" if x is None else str(x), quote=True)


def pct(v):
    return "-" if v is None else f"{v:.2%}"


def table(header, rows, cls=""):
    head = "".join(f"<th>{esc(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="wrap"><table class="{cls}"><tr>{head}</tr>{body}</table></div>'


def section(title, body):
    return f"<section><h2>{esc(title)}</h2>{body}</section>"


def render(result, out_dir, explanation=None, hand_check=None, commands=None, attempts=None):
    out_dir = Path(out_dir)
    c = build_charts(result)
    p = result["profile"]
    label = result["data_label"]
    parts = []
    parts.append(section("数据与字段", "<p>" + esc(result["inputs"].get("dataset_note") or "") + "</p>" + table(
        ["文件", "状态", "行数", "列映射（原列 → 规范字段）", "未映射列"],
        [(f["file"], f["status"], f["rows"], "; ".join(f"{k}→{v}" for k, v in f["column_map"].items() if k != v) or "与规范一致", ", ".join(f["unmapped_columns"]) or "-") for f in p["files"]]) +
        f"<p>行粒度：{esc(p['row_grain'])}。校验：去重后 {p['rows_after_dedup']} 行，不同测量键 {p['grain_check']['distinct_measurement_keys']} 个，"
        f"存在多行的键 {p['grain_check']['keys_with_multiple_rows']} 个（这些是内容冲突的重复测量，已在质量检查中列出）。重测行 {p['retest_rows']} 行。"
        f"芯片 {p['chips']} 颗；运行 {', '.join(p['runs'])}；必测项目 {', '.join(p['required_items'])}。</p>"))
    counts = result["quality_counts"]
    parts.append(section("数据质量检查", table(["规则", "级别", "条数", "定义"], [(k, RULES[k][0], counts.get(k, 0), RULES[k][1]) for k in RULES]) +
        f"<p>需要人工复核的行（warn 及以上、可定位到原始行）共 {result['review_rows']} 条，见 <code>review_list.csv</code>，每条带源文件、行号和原始行文本。</p>"))
    parts.append(section("指标口径与假设（未经业务确认）", "<ol>" + "".join(f"<li>{esc(a)}</li>" for a in result["assumptions"]) + "</ol>"))
    parts.append(section("测试记录通过率（不是良率）", table(["运行", "批次", "PASS 行", "FAIL 行", "SKIP 行", "缺状态行", "记录通过率"],
        [(r["run_id"], r["lot_id"], r["pass_rows"], r["fail_rows"], r["skip_rows"], r["no_status_rows"], pct(r["record_pass_rate"])) for r in result["record_pass_rate_by_lot"]])))
    yield_rows = lambda rows, keys: [tuple(r[k] for k in keys) + (r["chips"], r["pass"], r["fail"], r["incomplete"], pct(r["yield_all"]), pct(r["yield_complete_only"]), pct(r["first_pass_yield_all"])) for r in rows]
    yh = ["芯片", "PASS", "FAIL", "INCOMPLETE", "良率(全部)", "良率(仅完整)", "首测良率(全部)"]
    parts.append(section("芯片良率（按运行与批次 / 晶圆）", c.get("yield", "") + table(["运行", "批次"] + yh, yield_rows(result["yield_by_lot"], ("run_id", "lot_id"))) +
        "<details><summary>按晶圆</summary>" + table(["运行", "批次", "晶圆"] + yh, yield_rows(result["yield_by_wafer"], ("run_id", "lot_id", "wafer_id"))) + "</details>"))
    parts.append(section(f"失败最多的 {len(result['top_items'])} 个测试项目", c.get("top_items", "") + table(["排名", "项目", "最终 FAIL 芯片", "FAIL 行（含重测）", "有效最终结果芯片", "最终失败率"],
        [(r["rank"], r["test_item"], r["final_fail_chips"], r["fail_rows_incl_retests"], r["final_valid_chips"], pct(r["final_fail_rate"])) for r in result["top_items"]]) +
        "<details><summary>按运行 × 项目</summary>" + table(["运行", "项目", "FAIL 行", "最终 FAIL 芯片", "有效芯片", "最终失败率", "无有效结果"],
        [(r["run_id"], r["test_item"], r["fail_rows"], r["final_fail_chips"], r["final_valid_chips"], pct(r["final_fail_rate"]), r["final_not_valid"]) for r in result["item_failures"]]) + "</details>"))
    conc = lambda rows, level: table(["运行"] + level + ["项目", "FAIL 芯片", "有效芯片", "失败率", "其余合计失败率", "倍数"],
        [(r["run_id"],) + tuple(r[k] for k in (["lot_id"] if len(level) == 1 else ["lot_id", "wafer_id"])) + (r["test_item"], r["fail_chips"], r["valid_chips"], pct(r["fail_rate"]), pct(r["rest_fail_rate"]), r["ratio_vs_rest"]) for r in rows]) if rows else "<p>未命中。</p>"
    parts.append(section("异常集中的批次 / 晶圆（启发式规则 A9）", "<h3>批次级</h3>" + conc(result["concentration_lot"], ["批次"]) + "<h3>晶圆级</h3>" + conc(result["concentration_wafer"], ["批次", "晶圆"]) +
        "<p>这是描述性的集中度筛选，不是显著性检验，也不说明失效原因。</p>"))
    dist = [d for d in result["distributions"] if d["test_item"] == result.get("trend_item")]
    parts.append(section(f"测量值分布与随时间变化（{result.get('trend_item')}，仅首测有效值）", c.get("histogram", "") + c.get("trend", "") +
        table(["项目", "运行", "批次", "n", "均值", "标准差", "P5", "中位数", "P95", "最大"], [(d["test_item"], d["run_id"], d["lot_id"], d["n"], d.get("mean"), d.get("sd"), d.get("p05"), d.get("median"), d.get("p95"), d.get("max")) for d in dist]) +
        "<details><summary>全部项目的分布统计</summary>" + table(["项目", "运行", "批次", "n", "均值", "标准差", "最小", "中位数", "最大"],
        [(d["test_item"], d["run_id"], d["lot_id"], d["n"], d.get("mean"), d.get("sd"), d.get("min"), d.get("median"), d.get("max")) for d in result["distributions"]]) + "</details>"))
    for key, title in (("version_compare", "版本对比：同一批芯片在两次运行 / 两个测试程序下（配对）"), ("compare", "指定选择对比")):
        if key in result:
            v = result[key]
            rows = [(r["test_item"], r["a"].get("n"), r["a"].get("mean"), r["b"].get("n"), r["b"].get("mean"), r.get("mean_diff_b_minus_a"), r.get("std_diff"),
                     (r.get("paired") or {}).get("n", "-"), (r.get("paired") or {}).get("mean_diff", "-")) for r in v["rows"]]
            note = f"<p>A = {esc(v['a'])}，B = {esc(v['b'])}" + (f"，程序版本 {esc(v.get('programs'))}" if v.get("programs") else "") + "。差值只描述测量变化；程序版本、测试条件和芯片本身的变化在这份数据里无法区分。</p>"
            parts.append(section(title, note + table(["项目", "A n", "A 均值", "B n", "B 均值", "均值差 B−A", "标准化差", "配对 n", "配对均值差"], rows)))
    if "run_diff" in result:
        d = result["run_diff"]
        rows = [(r["chip_key"], r["test_item"], r["change"], r[f"{d['base_run']}_status"], r[f"{d['new_run']}_status"], r[f"{d['base_run']}_value"], r[f"{d['new_run']}_value"], r[f"{d['base_run']}_source"], r[f"{d['new_run']}_source"]) for r in d["rows"]]
        parts.append(section(f"运行对比 {d['base_run']} → {d['new_run']}（新增失败 / 已修复）", f"<p>范围：批次 {esc(d['lots'])}，两次都有最终结果的芯片项目 {d['overlap_chip_items']} 个；变化计数 {esc(d['counts'])}。</p>" +
            table(["芯片", "项目", "变化", f"{d['base_run']} 状态", f"{d['new_run']} 状态", f"{d['base_run']} 值", f"{d['new_run']} 值", f"{d['base_run']} 来源", f"{d['new_run']} 来源"], rows)))
    if result["logs"]:
        parts.append(section("测试日志失败项提取", table(["日志", "FAIL 行", "按项目", "无法解析的 FAIL 行"],
            [(l["file"], l["fail_lines"], l["by_item"], "; ".join(f"第 {u['source_line']} 行：{u['raw_line']}" for u in l["unparsed"]) or "无") for l in result["logs"]]) +
            "<p>日志是测试机原始输出；CSV 中人为注入的数据问题（如 9999 值）不在日志中，因此两者数字不必相同。</p>"))
    x = result["sql_cross_check"]
    parts.append(section("SQL 交叉核对", f"<p>记录通过率（按运行 × 批次）SQL 与 Python 一致：<b>{x['record_pass_rate_match']}</b>；各项目最终 FAIL 芯片数一致：<b>{x['final_fail_chips_match']}</b>。</p>"
        f"<details><summary>SQL</summary><pre>{esc(x['sql']['record_pass_rate'])}\n\n{esc(x['sql']['final_fails'])}</pre></details>"))
    if hand_check:
        parts.append(section("手工核对小样本", table(["指标", "手算", "程序", "一致"], [(k, v["expected"], v["actual"], "是" if v["expected"] == v["actual"] else "否") for k, v in hand_check.items()]) +
            "<p>手算过程见 <code>data/handcheck/HAND_CHECK.md</code>。</p>"))
    if explanation:
        if "parsed" in explanation:
            e = explanation["parsed"]
            rows = [(ch["claim"], ", ".join(ch["evidence"] or []), "是" if ch["evidence_keys_found"] else "否：" + ", ".join(ch.get("missing_evidence_keys", [])),
                     "是" if ch.get("claim_has_number") else "否", ", ".join(ch["numbers_not_in_facts"]) or "无", ", ".join(ch.get("numbers_misattributed", [])) or "无") for ch in explanation["checks"]]
            body = (f"<p class='warn'>以下是本地 Qwen（{esc(explanation['request']['model'])}）基于 facts.json 生成的解释，属于模型输出，未经人工验证。程序自动核对三项：引用的证据键是否存在、句中数字能否在 facts 中找到、数字是否出自句中所述的运行/批次那一行。</p>"
                    f"<p><b>摘要：</b>{esc(e['summary'])}</p><p><small>摘要中 facts 里找不到的数字：{esc(', '.join(explanation['summary_numbers_not_in_facts']) or '无')}</small></p>" +
                    table(["模型结论", "引用证据", "证据键全部存在", "含具体数字", "facts 中找不到的数字", "与所述运行/批次不对应的数字"], rows) +
                    "<p class='warn'>机械检查只能发现一部分问题：通过检查不代表说法正确。人工复核记录见 <code>explanation_review.md</code>（三版提示词的输出都保留）。</p>" +
                    (table(["提示词版本", "结论条数", "含数字", "证据键有效", "找不到的数字", "耗时 s"], [(a.get("prompt_revision"), a.get("findings"), a.get("findings_with_number"), a.get("findings_with_valid_evidence"), ", ".join(a.get("numbers_not_in_facts", [])) or "无", a.get("latency_seconds")) for a in (attempts or [])]) if attempts else "") +
                    "<h3>模型列出的不确定性</h3><ul>" + "".join(f"<li>{esc(u)}</li>" for u in e["uncertainties"]) + "</ul><h3>建议人工确认</h3><ul>" +
                    "".join(f"<li>{esc(u)}</li>" for u in e["next_checks"]) + f"</ul><p><small>耗时 {explanation['latency_seconds']} s；token：{esc(explanation['raw_response'].get('usage'))}；finish_reason：{esc(explanation.get('finish_reason'))}</small></p>")
        else:
            body = f"<p>模型调用失败：{esc(explanation.get('error'))}</p>"
        parts.append(section("模型辅助解释（本地 Qwen，未经验证）", body))
    if commands:
        parts.append(section("复现命令", f"<pre>{esc(commands)}</pre>"))
    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>芯片测试数据分析</title><style>
{CHART_CSS}
:root{{--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--line:#e1e0d9;--card:#fcfcfb;--warnbg:#fff4e0;--warnline:#e0b060}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--line:#2c2c2a;--card:#1a1a19;--warnbg:#2a2418;--warnline:#8a6a3a}}}}
:root[data-theme="dark"]{{--page:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--line:#2c2c2a;--card:#1a1a19;--warnbg:#2a2418;--warnline:#8a6a3a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--page);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:1080px;margin:auto;padding:28px 16px}}
h1{{font-size:28px;margin:4px 0 8px}}h2{{font-size:19px;margin:34px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}}h3{{font-size:15px;margin:16px 0 6px}}p,li{{color:var(--ink2)}}
.banner,.warn{{background:var(--warnbg);border:1px solid var(--warnline);border-radius:10px;padding:10px 14px;color:var(--ink)}}
.wrap{{overflow-x:auto;margin:8px 0}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:break-word;word-break:normal}}th{{white-space:nowrap}}th{{color:var(--ink2);font-weight:600}}
td{{font-variant-numeric:tabular-nums}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--card);border:1px solid var(--line);padding:12px;border-radius:8px;font:12px/1.55 ui-monospace,monospace}}
details{{margin:8px 0}}summary{{cursor:pointer;color:var(--ink2)}}.chart{{margin:10px 0}}code{{font-size:13px}}
</style><main class="viz-root"><small>生成于 {esc(result['generated_at_utc'])} · 全部指标由 chip_analysis 程序计算</small><h1>芯片测试数据分析报告</h1>
<p class="banner"><b>数据标记：{esc(label)}。</b>字段结构是示例，不代表任何公司的真实数据结构。良率、重测与异常规则均为下方列出的假设，未经业务确认。数据只在本机处理，模型调用只发往 127.0.0.1。</p>
{''.join(parts)}</main></html>'''
    (out_dir / "report.html").write_text(doc, encoding="utf-8")
    (out_dir / "report.md").write_text(markdown(result, explanation), encoding="utf-8")
    return out_dir / "report.html"


def markdown(result, explanation=None):
    lines = [f"# 芯片测试数据分析（{result['data_label']}）", "", f"生成于 {result['generated_at_utc']}。数据为{result['data_label']}，口径假设见 analysis.json 的 assumptions。", "",
             "## 良率（按运行与批次）", "", "| 运行 | 批次 | 芯片 | PASS | FAIL | INCOMPLETE | 良率(全部) | 良率(仅完整) | 首测良率(全部) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    lines += [f"| {r['run_id']} | {r['lot_id']} | {r['chips']} | {r['pass']} | {r['fail']} | {r['incomplete']} | {pct(r['yield_all'])} | {pct(r['yield_complete_only'])} | {pct(r['first_pass_yield_all'])} |" for r in result["yield_by_lot"]]
    lines += ["", "## 测试记录通过率（不是良率）", "", "| 运行 | 批次 | PASS 行 | FAIL 行 | 记录通过率 |", "|---|---|---:|---:|---:|"]
    lines += [f"| {r['run_id']} | {r['lot_id']} | {r['pass_rows']} | {r['fail_rows']} | {pct(r['record_pass_rate'])} |" for r in result["record_pass_rate_by_lot"]]
    lines += ["", f"## 失败最多的 {len(result['top_items'])} 个项目（最终 FAIL 芯片数）", ""] + [f"{r['rank']}. {r['test_item']}：{r['final_fail_chips']} 颗（含重测 FAIL 行 {r['fail_rows_incl_retests']}）" for r in result["top_items"]]
    lines += ["", "## 异常集中（启发式 A9）", ""] + [f"- {r['run_id']} {r.get('lot_id')} {r.get('wafer_id', '')} {r['test_item']}：{r['fail_chips']}/{r['valid_chips']} 失败，为其余合计的 {r['ratio_vs_rest']} 倍" for r in result["concentration_wafer"]]
    lines += ["", "## 数据质量", ""] + [f"- {k}：{v}" for k, v in result["quality_counts"].items()]
    if "run_diff" in result:
        lines += ["", f"## 运行对比 {result['run_diff']['base_run']} → {result['run_diff']['new_run']}", "", json.dumps(result["run_diff"]["counts"], ensure_ascii=False)]
    if explanation and "parsed" in explanation:
        lines += ["", "## 模型辅助解释（本地 Qwen，未经验证）", "", explanation["parsed"]["summary"]]
    lines += ["", "相关不等于因果：本报告不推断芯片失效根因。"]
    return "\n".join(lines) + "\n"
