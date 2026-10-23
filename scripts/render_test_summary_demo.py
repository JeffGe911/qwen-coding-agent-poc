"""Render one real summarize_results run as a static page plus example.json.

Supports the tuned historical task (test_summary) and the frozen blind task (report_pass_rate).
Model code is executed here ONLY if the run already succeeded after a recorded human approval
whose digest matches; a pending proposal is shown as text, never run.
Usage: python scripts/render_test_summary_demo.py RUN_DIR --output evidence/report-pass-rate/view
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qwen_agent.workflow import TASKS, read_json, write_json

SUPPORTED = {"test_summary", "report_pass_rate"}
SAMPLE = [
    {"name": "login", "status": "passed"},
    {"name": "permissions", "status": "passed"},
    {"name": "export", "status": "failed"},
    {"name": "external_device", "status": "skipped"},
]
LABELS = {"awaiting_approval": "等待人工审批 · 模型代码尚未执行", "succeeded": "修复成功 · pytest 全部通过",
          "failed": "修复未通过", "policy_blocked": "策略拦截", "model_error": "模型/API 错误",
          "infra_error": "基础设施错误", "rejected": "人工拒绝"}


def evaluate(code):
    """Run summarize_results on SAMPLE in a separate isolated interpreter with restricted builtins."""
    bootstrap = '''import json, sys
sys.path.insert(0, sys.argv[1])
from qwen_agent.policy import validate, safe_builtins
payload = json.load(sys.stdin)
scope = {"__builtins__": safe_builtins()}
exec(compile(validate(payload["code"]), "solution.py", "exec"), scope)
print(json.dumps(scope["summarize_results"](payload["sample"])))
'''
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
    result = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap, str(ROOT)], input=json.dumps({"code": code, "sample": SAMPLE}),
                            capture_output=True, text=True, timeout=5, env=env, check=True)
    return json.loads(result.stdout)


def render(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    state = read_json(run / "state.json")
    task_id = state["task"]["id"]
    if task_id not in SUPPORTED:
        raise ValueError("This viewer only supports the bundled summarize_results tasks")
    output.mkdir(parents=True, exist_ok=True)
    original_path = TASKS / task_id / "solution.py"
    recorded = state["config"].get("contract", {}).get("task_files_sha256", {}).get("solution.py")
    if recorded and hashlib.sha256(original_path.read_bytes()).hexdigest() != recorded:
        raise ValueError("Bundled original solution.py differs from the run's recorded snapshot")
    before = evaluate(original_path.read_text(encoding="utf-8"))  # Trusted original code only.
    events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    attempts = state["attempts"]
    last = attempts[-1] if attempts else {}
    result = last.get("result", {})
    after = None
    if state["status"] == "succeeded":
        folder = run / f"attempt-{last['attempt']}"
        proposal = read_json(folder / "proposal.json")
        if not last.get("reviewer") or not any(e["type"] == "approve" and e.get("digest") == last["digest"] for e in events):
            raise ValueError("No matching human approval event")
        code = (folder / "job" / "solution.py").read_text(encoding="utf-8")
        if code != proposal.get("code") or result.get("exit_code") != 0:
            raise ValueError("Approved source/result mismatch")
        after = evaluate(code)
    baseline = state.get("baseline", {})
    counts = lambda r: {k: r.get(k) for k in ("passed", "tests", "failures", "errors")}
    evidence = {"task": task_id, "blind": bool(state["task"].get("blind")), "model": state["config"]["model"], "run_id": state["run_id"],
                "status": state["status"], "stop_reason": state.get("stop_reason"), "sample_input": SAMPLE, "actual_before": before,
                "actual_after": after, "actual_after_note": None if after else "Not computed: no approved, passing proposal yet.",
                "baseline_tests": counts(baseline), "after_tests": counts(result) if result else None,
                "attempts": [{k: a.get(k) for k in ("attempt", "status", "digest", "generation_seconds", "usage", "reviewer", "reviewed_at", "approval_wait_seconds", "error")} for a in attempts],
                "approval_events": [e for e in events if e["type"] in {"approve", "reject"}], "contract": state["config"].get("contract")}
    write_json(output / "example.json", evidence)

    esc = lambda x: html.escape(str(x), quote=True)
    pretty = lambda obj: esc(json.dumps(obj, indent=2, ensure_ascii=False))
    failed_lines = "\n".join(l for l in baseline.get("output", "").splitlines() if l.startswith("FAILED") or " passed" in l or " failed" in l)
    rows = "".join(f"<tr><td>{esc(i['name'])}</td><td>{esc(i['status'])}</td></tr>" for i in SAMPLE)
    attempt_rows, diffs = [], []
    for a in attempts:
        r = a.get("result", {})
        usage = a.get("usage") or {}
        attempt_rows.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in [
            a["attempt"], a["status"], a.get("generation_seconds", "-"), f"{usage.get('prompt_tokens', '-')} / {usage.get('completion_tokens', '-')}",
            (a.get("digest") or "-")[:16] + "…", a.get("reviewer", "未审批"), a.get("approval_wait_seconds", "-"),
            f"{r['passed']}/{r['tests']} ({r.get('elapsed_seconds', '-')}s)" if r else "未执行", a.get("error") or ""]) + "</tr>")
        folder = run / f"attempt-{a['attempt']}"
        if (folder / "diff.txt").exists():
            explanation = read_json(folder / "proposal.json").get("explanation", "") if (folder / "proposal.json").exists() else ""
            diffs.append(f"<details {'open' if a is last else ''}><summary>提案 {a['attempt']} · 模型原始代码差异（{esc(a['status'])}）</summary><pre>{esc((folder / 'diff.txt').read_text(encoding='utf-8'))}</pre><p><small>模型解释原文（可能不准确，以测试为准）：</small></p><pre>{esc(explanation)}</pre></details>")
    approvals = "".join(f"<li>{esc(e['at'])} · {esc(e['type'])} · reviewer={esc(e.get('reviewer'))} · 提案 {esc(e.get('attempt'))} · 摘要 {esc(e.get('digest'))}</li>" for e in evidence["approval_events"]) or "<li>暂无审批事件。</li>"
    pending = ""
    if state["status"] == "awaiting_approval":
        rel = os.path.relpath(run, ROOT)
        pending = f'''<section class="card warn"><h2>下一步：人工审批</h2><p>审阅上面的差异后，在项目目录执行（批准只对这一份代码 + 测试快照 + 配置的摘要有效）：</p><pre>..\\..\\work\\.venv\\Scripts\\python.exe -m qwen_agent decide "{esc(rel)}" approve --digest {esc(last['digest'])} --reviewer 你的名字
..\\..\\work\\.venv\\Scripts\\python.exe scripts\\render_test_summary_demo.py "{esc(rel)}" --output {esc(os.path.relpath(output, ROOT))}</pre><p>拒绝则把 approve 换成 reject。批准后若 pytest 失败，系统会把公开测试的失败信息反馈给模型并生成新提案，新提案需要重新审批。</p></section>'''
    after_tests = f"{result.get('passed')} / {result.get('tests')}" if result else "尚未执行"
    note = ("本任务的需求原文与 21 个测试在任何模型调用之前写好并冻结（frozen.json 记录 SHA-256），这是该任务的首次盲测运行。"
            if state["task"].get("blind") else
            "这是任务说明与公开断言经过调整后的工作流演示，不是盲测成功率；调整过程保留在 evidence/business-demo* 目录。")
    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>本地 Qwen 修复通过率</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#101922;color:#edf3f7;font:15px system-ui;line-height:1.65}}main{{max-width:1120px;margin:auto;padding:32px 16px}}.eyebrow{{color:#80dfc0;letter-spacing:.12em;font-size:12px}}h1{{font-size:30px;line-height:1.3;margin:10px 0}}h2{{font-size:18px;margin-top:0}}p,li{{color:#b8c8d3}}.badge{{display:inline-block;padding:6px 14px;border:1px solid #426858;border-radius:20px;color:#80dfc0}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:20px 0}}.card{{background:#1a2a38;border:1px solid #2d4352;border-radius:14px;padding:20px;margin:16px 0}}.warn{{border-color:#8a6a3a}}.number{{font-size:40px;font-weight:750;color:#80dfc0}}.old{{color:#f4b18a}}.muted{{color:#7f93a1}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#0d151e;padding:14px;border-radius:10px;font:12.5px/1.6 ui-monospace,monospace}}.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{text-align:left;padding:7px;border-bottom:1px solid #334957}}small{{color:#a7bac7}}details{{margin:14px 0}}summary{{cursor:pointer;font-weight:600}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}h1{{font-size:24px}}}}
</style><main><div class="eyebrow">LOCAL QWEN · CODING AGENT · {esc(task_id)}</div><h1>本地 Qwen 修复测试报告通过率</h1><p>原程序把“跳过”的用例算进分母。本地 Qwen 只能返回一个完整的 solution.py；经人工审批后才在受限执行器中运行固定的 pytest。</p><span class="badge">{esc(LABELS.get(state['status'], state['status']))}</span><p><small>模型：{esc(state['config']['model'])} · API：{esc(state['config']['base_url'])}（仅本机） · 执行器：{esc(state['config']['sandbox'])}{'（受限 Python 演示模式，不是操作系统级沙箱）' if state['config']['sandbox'] == 'restricted' else ''}</small></p>
<div class="grid"><section class="card"><h2>修复前 · 程序实际输出</h2><div class="number old">{before['pass_rate']}</div><p>2 ÷ 4：跳过的用例被算进分母</p><small>基线 pytest：{baseline.get('passed')} / {baseline.get('tests')} 通过</small></section><section class="card"><h2>修复后 · 程序实际输出</h2><div class="number{'' if after else ' muted'}">{after['pass_rate'] if after else '未验证'}</div><p>{'2 ÷ (2 + 1)，由已批准代码在独立进程中真实计算' if after else '尚无已批准且通过测试的代码，不计算、不填写期望值'}</p><small>修复后 pytest：{esc(after_tests)}</small></section></div>
<div class="grid"><section class="card"><h2>示例输入（合成数据）</h2><table><tr><th>用例</th><th>status</th></tr>{rows}</table></section><section class="card"><h2>输出 JSON</h2><p><small>修复前（原程序真实输出）</small></p><pre>{pretty(before)}</pre><p><small>修复后</small></p><pre>{pretty(after) if after else '尚未批准并执行模型代码'}</pre></section></div>
<section class="card"><h2>修复前 pytest 真实失败结果</h2><pre>{esc(failed_lines)}</pre><details><summary>完整 pytest 输出</summary><pre>{esc(baseline.get('output', ''))}</pre></details></section>
<section class="card"><h2>提案与审批记录</h2><div class="wrap"><table><tr><th>提案</th><th>状态</th><th>生成耗时 s</th><th>提示/输出 tokens</th><th>审批摘要</th><th>reviewer</th><th>等待审批 s</th><th>pytest</th><th>原因</th></tr>{''.join(attempt_rows)}</table></div>{''.join(diffs)}<h2>审批事件</h2><ul>{approvals}</ul></section>
{pending}
{f'<section class="card"><h2>修复后 pytest 输出</h2><pre>{esc(result.get("output", ""))}</pre></section>' if result else ''}
<p><small>{esc(note)}<br>run_id：{esc(state['run_id'])} · 终止原因：{esc(state.get('stop_reason') or '-')}<br>契约摘要（提示词/策略/任务文件）：{esc(json.dumps(state['config'].get('contract', {}), ensure_ascii=False))}</small></p></main></html>'''
    (output / "demo.html").write_text(doc, encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in ("task", "blind", "status", "actual_before", "actual_after", "baseline_tests", "after_tests")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evidence/report-pass-rate/view"))
    args = parser.parse_args()
    render(args.run, args.output)
