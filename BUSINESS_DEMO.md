# 本地例子：Qwen 修复测试结果汇总器（历史，调整后的非盲测版本）

> 2026-10-23 第二轮新增了 `report_pass_rate` 任务：使用需求原文、21 个在模型调用前冻结的测试，作为首次盲测。见 README 与 `evidence/report-pass-rate/`。本文件记录的是此前调整过任务说明的 `test_summary` 过程，保留不改。

本机实际运行：Windows、Python 3.13.4、RTX 5070 Ti Laptop 12GB、Ollama 0.40.9、Qwen2.5-Coder 7B 量化模型。无需两台服务器。

## 例子解决的问题

内部测试程序收到四条合成记录：登录通过、权限检查通过、导出失败、外部设备测试跳过。原程序使用“通过数 / 全部记录数”，输出 50%。需求规定通过率只计算实际执行的用例，正确为 `2 / (2 + 1)`，保留四位小数后输出 66.67%。还需处理空结果、全部跳过、未知状态和缺失字段。

## 本次真实结果

| 项目 | 修复前 | 修复后 |
|---|---:|---:|
| 示例实际输出 pass_rate | 0.5 | 0.6667 |
| pytest 通过 | 5/11 | 11/11 |
| pytest 失败 | 6 | 0 |

代码来自本地 Qwen 的原始 API 响应；用户在本次聊天中批准摘要 `b0be04b50d9cffd65bf761d84d91a2819bb74a36e0e47e21ceed4bd0398255df` 后才执行。示例前后输出由独立 Python 进程真实计算，不是把期望值填进报告。

[查看演示页](evidence/business-demo-view/demo.html) · [实际输出 JSON](evidence/business-demo-view/example.json) · [模型 GPU 驻留](evidence/business-demo-view/ollama-ps.txt)

## 保留的迭代过程

这是工作流演示，不是盲测。初始 1.5B 草案未修正分母；第一份 7B 草案也未修正分母。随后将“跳过不计入分母、保留四位小数”明确写进任务说明和独立公开断言；另一份 7B 草案改对了分母，但漏了缺失状态的错误类型；将该已明确的需求列为公开失败测试后，最终提案完整处理了这些要求。

此前三份草案均未获批准、未执行，原始响应和任务快照分别保留在 `evidence/business-demo/`、`evidence/business-demo-7b/`、`evidence/business-demo-final/` 中。最终成功运行是 `20261023T184855Z-test_summary-036f2d1b`。不能将它宣传为“第一次就成功”或用它估算模型整体成功率。此前三任务的原始评测统计保持独立。

## 在当前电脑重新跑一次

在项目目录执行，当前工作区已有便携式 Ollama 与虚拟环境。本机 Ollama 应监听 `127.0.0.1:11435`；若服务结束，按 README 的工作区启动命令重启。

```powershell
..\..\work\.venv\Scripts\python.exe -m qwen_agent demo --task test_summary --model qwen2.5-coder:7b --base-url http://127.0.0.1:11435/v1 --sandbox restricted --reviewer Jeff --runs runs-local-demo
```

命令显示模型代码差异；输入 `approve 完整摘要` 才运行测试。新运行的模型输出可能不同，不会复用此次批准或伪造成功结果。

为某次运行生成页面和实际业务输出：

```powershell
..\..\work\.venv\Scripts\python.exe scripts\render_test_summary_demo.py runs-local-demo\RUN_ID --output evidence\my-demo-view
```

渲染器在待审批状态只执行可信旧程序；只有已批准且 pytest 成功的候选代码才会用于计算修复后的样例输出。未通过时不会用正确答案冒充真实结果。

本机采用受限 Python 演示执行器，不是操作系统沙箱；默认 Docker 执行路径仍保留。生成代码使用本机 Python 3.13 的语法能力，其他版本应重新验证。
