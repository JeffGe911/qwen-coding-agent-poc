from collections import Counter
from datetime import datetime
import html
import json
from pathlib import Path

from .workflow import read_json, write_json

# Every run status maps to exactly one reporting category. Interrupted runs
# (executing/generating/baseline left behind by a killed process) count as infra errors.
CATEGORIES = [
    ("task_success", "任务成功", {"succeeded"}),
    ("repair_failed", "修复失败", {"failed"}),
    ("pending_approval", "待审批", {"awaiting_approval"}),
    ("policy_blocked", "策略拦截", {"policy_blocked"}),
    ("model_api_error", "模型/API 错误", {"model_error"}),
    ("infra_error", "基础设施错误", {"infra_error", "executing", "generating", "baseline"}),
    ("human_rejected", "人工拒绝", {"rejected"}),
]


def category(status):
    return next((key for key, _, statuses in CATEGORIES if status in statuses), "infra_error")


def summarize(states):
    counts = Counter(s["status"] for s in states)
    by_category = Counter(category(s["status"]) for s in states)
    evaluated = by_category["task_success"] + by_category["repair_failed"]
    succeeded = by_category["task_success"]
    first = sum(s["status"] == "succeeded" and len(s["attempts"]) == 1 for s in states)
    total = len(states)
    return {"started_runs": total, "completed_evaluations": evaluated, "succeeded": succeeded, "first_attempt_successes": first,
            "success_rate_completed": succeeded / evaluated if evaluated else None,
            "success_rate_started": succeeded / total if total else None,
            "first_attempt_rate_completed": first / evaluated if evaluated else None,
            "first_attempt_rate_started": first / total if total else None,
            "categories": {key: {"label": label, "count": by_category[key]} for key, label, _ in CATEGORIES},
            "denominators": {
                "success_rate_started": "全部启动运行 = 所有类别之和（含待审批、拦截、错误、拒绝）",
                "success_rate_completed": "已完成执行评测 = 任务成功 + 修复失败（只含经人工批准并真正跑完 pytest 的运行）",
            },
            "statuses": dict(sorted(counts.items())),
            "note": "One run is one task trial (up to 3 proposals). Framework/unit test pass rates are NOT model repair rates. Small samples only demonstrate the workflow."}


def wall_seconds(run):
    path = run / "events.jsonl"
    if not path.exists():
        return None
    times = [datetime.fromisoformat(json.loads(line)["at"]) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return round((times[-1] - times[0]).total_seconds(), 3) if len(times) > 1 else 0.0


def generate(runs, output):
    runs, output = Path(runs), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted(runs.glob("*/state.json"))
    states = [read_json(p) for p in paths]
    summary = summarize(states)
    for path, state in zip(paths, states):
        state["wall_seconds_first_to_last_event"] = wall_seconds(path.parent)
    write_json(output / "summary.json", {**summary, "runs": states})
    escape = lambda x: html.escape(str(x), quote=True)
    rows = []
    for s in states:
        attempts = s["attempts"]
        result = next((a["result"] for a in reversed(attempts) if "result" in a), {})
        task = s.get("task", {})
        contract = s["config"].get("contract", {})
        cells = [s["run_id"], task.get("id", "-"), "首次盲测" if task.get("blind") else "调整后/未标注", s["config"]["model"],
                 s["config"]["sandbox"], f"{s['status']} → {dict((k, l) for k, l, _ in CATEGORIES)[category(s['status'])]}",
                 " / ".join(a.get("status", "?") for a in attempts) or "-", s.get("stop_reason", "-"),
                 f"{result.get('passed', '-')}/{result.get('tests', '-')}", contract.get("policy_revision", "1(未记录)"),
                 s.get("wall_seconds_first_to_last_event", "-")]
        rows.append("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in cells) + "</tr>")
    percent = lambda v: "N/A" if v is None else f"{v:.0%}"
    cards = "".join(f'<div class="card">{escape(c["label"])}<strong>{c["count"]}</strong></div>' for c in summary["categories"].values())
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Qwen Agent 运行统计</title><style>body{{font:15px system-ui;background:#101922;color:#e6edf3;max-width:1240px;margin:32px auto;padding:0 16px}}h1{{font-size:28px}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:#1b2b39;padding:16px 20px;border-radius:12px;min-width:120px}}strong{{display:block;font-size:30px;color:#78ddc0}}.wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{text-align:left;border-bottom:1px solid #304452;padding:10px 6px;overflow-wrap:anywhere}}p,li{{line-height:1.7;color:#b6c5d0}}</style>
<h1>Qwen Coding Agent 运行统计</h1><p>本地推理 → 代码提案 → 人工审批 → pytest → 可审计结果。统计对象是本目录中的真实运行，不含框架单元测试。</p>
<div class="cards">{cards}</div>
<ul><li>全部启动运行成功率：<b>{percent(summary['success_rate_started'])}</b> = {summary['succeeded']} / {summary['started_runs']}（分母：{escape(summary['denominators']['success_rate_started'])}）</li>
<li>已完成执行评测成功率：<b>{percent(summary['success_rate_completed'])}</b> = {summary['succeeded']} / {summary['completed_evaluations']}（分母：{escape(summary['denominators']['success_rate_completed'])}）</li>
<li>首次提案即成功：{summary['first_attempt_successes']} 个运行</li></ul>
<div class="wrap"><table><thead><tr><th>运行</th><th>任务</th><th>盲测?</th><th>模型</th><th>执行器</th><th>状态 → 类别</th><th>各提案状态</th><th>终止原因</th><th>最终 pytest 通过/总数</th><th>策略版本</th><th>首末事件间隔(s)</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>restricted 模式是受限 Python 演示，不是操作系统沙箱；Docker 模式提供无网络、只读根目录、非 root、资源限额。待审批运行的模型代码尚未执行，其正确性未验证。小样本只证明流程可运行，不代表模型整体修复能力。</p></html>'''
    (output / "report.html").write_text(document, encoding="utf-8")
    return summary
