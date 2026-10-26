"""Build an honest report of the saved partial qa-v1 run; does not call a model."""
import json
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    ev = ROOT / "evidence/doc-qa"
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ev / "results/qa-v1/dev").glob("d[0-9][0-9].json"))]
    samples = [json.loads(line) for line in (ev / "sessions/qa-v1/dev/resources.jsonl").read_text(encoding="utf-8").splitlines()]
    session = json.loads((ev / "sessions/qa-v1/dev/session.json").read_text(encoding="utf-8"))
    cleanup = json.loads((ev / "sessions/qa-v1/dev/unload.json").read_text(encoding="utf-8"))
    summary = {"contract": "qa-v1", "dev_expected": 17, "dev_completed": len(rows), "holdout_expected": 40,
               "holdout_completed": 0, "complete": False, "request_failures_in_saved_answers": sum(r["record"]["status"] == "request_failed" for r in rows),
               "invalid_outputs_in_saved_answers": sum(r["record"]["status"] == "invalid_output" for r in rows),
               "minimum_available_mb": min(r["memory"]["available_mb"] for r in samples),
               "minimum_commit_headroom_mb": min(r["memory"]["commit_headroom_mb"] for r in samples), "stop": session["aborted"],
               "models_after_cleanup": cleanup.get("after", {}).get("models"), "cleanup_errors": cleanup["errors"]}
    cli_rows = []
    for r in rows:
        q, rec, score = r["question"], r["record"], r["score"]
        answer = html.escape(rec["shown"]["answer"], quote=False).replace("|", "\\|").replace("\n", " ")
        cli_rows.append(f"| {q['id']} | {q['question']} | {answer} | {score['correct']} | {score['supported']} | {rec['seconds']} |")
    report = f"""# 本地文档问答 RAG 运行记录

## 本轮结果

已在本机真实调用 bge-m3 和 Qwen2.5-Coder 7B，完成 **{len(rows)}/17 道开发题**。
两份原始响应、检索结果、引用和评分保留在 [results/qa-v1/dev](results/qa-v1/dev/)。
第 2 题后，可提交内存余量降到 **{summary['minimum_commit_headroom_mb']} MiB**，触发原有 **2048 MiB** 停止线；
监督进程停止本次评测并卸载模型。最低物理可用内存为 **{summary['minimum_available_mb']} MiB**，因此这次触发的是提交余量，不是物理内存耗尽。
根据使用者选择，本轮不再加载模型。**40 道独立题没有运行，本报告不提供整体准确率或盲测成绩。**

## 两道真实回答

| 题目 | 问题 | 模型回答 | 冻结关键词检查 | 引用分段与标注范围重叠 | 秒 |
|---|---|---|---|---|---|
{chr(10).join(cli_rows)}

d01 命中了预设选项关键词，并引用了另一段真实的相关文档；其标注范围重叠检查仍为 false。
d02 虽引用了真实文档，却给出了错误的选项组合。这说明“引文存在”与“回答正确”是两件事。
不能把两题的关键词检查结果当成整个知识库的质量估计。

## 工作流

固定版本的 lowRISC 编码规范、Icarus 和 Verilator 公开文档被切成 **674 段**。
本地 bge-m3 向量检索与 BM25 通过 RRF 合并排序，取六段交给本地 Qwen 回答。
引用检查校验来源编号和原文是否在给定分段出现，输出文档、章节和行范围；它不验证每句话的语义是否得到支持。
没有有效引用的回答显示为“没找到”，只读问答不会执行回答中的命令。

## 合同和证据

- [qa-v1 冻结合同](contract/qa-v1.json)：原代码、提示词、索引与模型指纹未改。
- [运行前计划](qa-v1-RUN-PLAN.json)：开发集仅按流程条件放行，不按准确率选择是否运行独立题；本轮流程未完成，因此没有放行。
- [启动命令](sessions/qa-v1/dev/command.json)、[预检](sessions/qa-v1/dev/preflight.json)、[资源采样](sessions/qa-v1/dev/resources.jsonl)、[停止记录](sessions/qa-v1/dev/session.json)。
- [卸载记录](sessions/qa-v1/dev/unload.json)：结束后模型列表为空；传输失败和输出错误与“正确拒答”分开看。
- 原有七项 RAG 测试与新增四项入口测试通过；全套回归 **187 passed**，见 [测试记录](../verification/showcase-tests.txt)。这些不计入模型效果。

冻结评分中的 `correct` 是预设关键词的字面匹配；`supported` 是整个引用分段与标注行范围重叠，不是完整的语义正确性审核。
请求失败也可能被原评分器记为“没找到”，所以必须同时检查 `status`。本轮两份已保存回答均为 `ok`。
以后继续时保留本轮部分结果，另开合同版本；不能覆盖后声称这是第一次完整运行。

## 演示

```bash
python scripts/show_doc_qa.py
```

该命令只回放保存的回答，不加载模型。交互用法见 [本地文档问答](../../docs/LOCAL_DOC_QA.md)。
"""
    (ev / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    (ev / "qa-v1-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == "__main__":
    main()
