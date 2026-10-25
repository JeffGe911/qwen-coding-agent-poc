"""Show one log next to what the rules and the model made of it: numbered input lines (cited ones marked), each
engine's category / result / side, the lines it cited and its suggestion, plus the gold label when one is given.
Suggestions are displayed only; nothing is executed.
Usage: python scripts/side_by_side.py --root <dir> --log <file in root> --rules <x.rules.json> [--qwen <x.qwen.json>]
                                      [--gold <gold.json>] --out <file.md>
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from regression_triage import logio  # noqa: E402
from regression_triage.report import LABEL, SIDE  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def cell(t):
    if t is None:
        return "（没有报告这个测试）"
    lines = ", ".join(str(e["line"]) for e in t.get("evidence", [])) or "无"
    extra = []
    if t.get("rejected_citations"):
        extra.append(f"另有 {len(t['rejected_citations'])} 条引用与日志不符，已拦截")
    if t.get("unmatched"):
        extra.append("日志里没有这个测试名")
    if t.get("source"):
        extra.append("来源：" + ("规则" if t["source"] == "rules" else "模型（规则无法判断，需复核）"))
    if t.get("guard"):
        extra.append(t["guard"])
    return f"{LABEL.get(t['category'], t['category'])} / {t['result']} / {SIDE.get(t['side'], t['side'])}<br>引用行：{lines}" + (f"<br>{'；'.join(extra)}" if extra else "")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--rules", required=True)
    p.add_argument("--qwen")
    p.add_argument("--hybrid")
    p.add_argument("--gold")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    log = logio.read_log(args.log, Path(args.root))
    docs = {"规则": load(args.rules), "Qwen": load(args.qwen), **({"组合": load(args.hybrid)} if args.hybrid else {})}
    gold = load(args.gold)
    engines = {k: (d["triage"] if d else None) for k, d in docs.items()}
    cited = {e["line"] for t in (engines.values()) if t for x in t["tests"] for e in x.get("evidence", [])}
    md = [f"# 同一份日志，规则与 Qwen 各自的判断：`{log.name}`\n",
          "> 建议只展示，不会执行任何命令，也不会修改 RTL 或测试。", ""]
    call = (docs["Qwen"] or {}).get("model_call")
    if call:
        u = call.get("usage") or {}
        md += ["## 模型调用", "",
               f"- 状态 **{call['status']}**，耗时 {call.get('seconds')} s，prompt {u.get('prompt_tokens')} token，输出 {u.get('completion_tokens')} token，"
               f"finish_reason {call.get('finish_reason')}；后端 `{call.get('backend')}`；请求 {call.get('request_chars')} 字符，"
               f"输入被截断：{'是' if call.get('input_truncated') else '否'}；服务端上下文 {call.get('server_context')}（{call.get('server_context_source')}）",
               *([f"- 校验发现：{'；'.join(call['problems'])}"] if call.get("problems") else []), ""]
    elif args.qwen is None:
        md += ["## 模型调用", "", "- 未运行。", ""]
    md += [f"## 输入：日志原文（共 {len(log.lines)} 行，▶ 表示被至少一个引擎引用）", "", "```"]
    show = range(1, len(log.lines) + 1) if len(log.lines) <= 120 else sorted({n for c in cited for n in (c - 1, c, c + 1) if 1 <= n <= len(log.lines)})
    md += [f"{'▶' if n in cited else ' '} {n:4d} | {log.line(n)}" for n in show] + ["```", ""]
    tests = list(dict.fromkeys([*(gold["tests"] if gold else {}), *(x["test_id"] for t in engines.values() if t for x in t["tests"])]))
    md += ["## 每个测试的判断", "", "| 测试 | 人工标注（金标准） | " + " | ".join(docs) + " |", "|---|---|" + "---|" * len(docs)]
    for tid in tests:
        g = gold["tests"].get(tid) if gold else None
        gcell = f"{LABEL.get(g['category'], g['category'])} / {g['result']} / {SIDE.get(g['side'], g['side'])}<br>证据行：{', '.join(map(str, g['evidence_lines'])) or '无'}" if g else "—"
        row = [cell(next((x for x in t["tests"] if x["test_id"] == tid), None)) if t else "未运行" for t in engines.values()]
        md.append(f"| `{tid}` | {gcell} | " + " | ".join(row) + " |")
    md += ["", "## 建议（只展示）", ""]
    for name, t in engines.items():
        if not t:
            continue
        md.append(f"**{name}**")
        md += [f"- `{x['test_id']}`：{x['suggestion']}" for x in t["tests"] if x["category"] != "pass"] or ["- 没有需要处理的测试"]
        md.append("")
    Path(args.out).write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    print(args.out)


if __name__ == "__main__":
    main()
