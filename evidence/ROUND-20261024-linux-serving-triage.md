# 本轮总结：Linux 部署与仿真回归日志分诊（2026-10-24）

工作分支 `feat/linux-serving-regression-triage`，从 main `e287c59` 拉出。没有重置、改写历史或强推。ACTIVE 仍是 `r2-7b-ctx8192-np1`，本轮没有修改它。没有启动、停止或重启任何模型服务，也没有占用新端口。没有安装 WSL、Docker 或任何系统组件。

## 已运行且通过

| 项目 | 结果 | 证据 |
|---|---|---|
| 受限执行器真实运行 Icarus Verilog 14.0 / Verilator 5.053（lint） | dev 14 个回归、holdout 15 个回归，覆盖通过、编译错误、自检失败但退出码 0、`$fatal` 断言、watchdog 超时、墙钟超时、工具缺失、lint 错误、提示注入、伪造 runner 行 | `evidence/regression-triage/runs/` |
| 执行器限制 | 1 s 超时后经 Job Object 结束整个进程树；256 MB 内存上限触发 MemoryError；不存在的工具返回 tool_error；源路径、宏、plusarg、顶层名注入均被拒绝 | `tests/test_triage.py` |
| 端到端演示 | `python -m regression_triage demo`：真实运行混合回归 → 规则分诊 → 中文报告，状态为“待工程师复核” | `evidence/regression-triage/demo/` |
| 评测合同 | `eval-v1` 在运行前冻结了数据、金标准和代码的哈希。哈希不符、合同未覆盖的引擎、重复运行都会被拒绝（有测试） | `evidence/regression-triage/contract/eval-v1.json` |
| 规则基线 · dev | 37/37。规则和 dev 金标准出自同一人，**不代表效果** | `evidence/regression-triage/REPORT-eval-v1.md` |
| pytest | 157 个通过，0 个跳过 | `evidence/regression-triage/pytest-summary.txt` |

## 已运行但结果不达标

| 项目 | 结果 | 说明 |
|---|---|---|
| 规则基线 · 独立 holdout（盲测，只跑一次） | 类别 15/39（38.5%）；需关注测试 precision 11/11、recall 11/24；77 条引用全部有效，36 条指向标注证据行 | 错误中 22/24 是 unknown，没有 pass/fail 颠倒。根因：结论写法是项目私有的。没有预设阈值，但这个覆盖率不能用于生产 |
| 提示注入标记（h13） | 没有标记出来 | 注入没有改变任何判断，但 v1 的检测只认几种固定说法 |
| 缩进的伪造 runner 行（h15） | 没有标记出来 | runner 已修复转义（有测试）；冻结的规则 v1 仍然检测不到，要到下一版 |

## 只有代码或单元测试

| 项目 | 内容 |
|---|---|
| 本地 Qwen 分诊 | 固定 JSON schema、unknown 选项、引用逐条核对物理行、注入当数据、输出截断和上下文超限显式报告、不安全建议标记、按 digest 钉模型。只用 FakeClient 测试过，**没有对真实模型运行** |
| Linux + Docker + vLLM 部署文件 | compose（digest、loopback、key、资源限制、健康检查、离线）、权重下载、8 项验收脚本、中文手册。只有静态检查、`bash -n`，以及用替身命令测试的拒绝路径（未确认、key 格式不对、内存不足、GPU 被占用时都停下，key 不进证据） |
| 报告生成器 | `scripts/build_triage_report.py` 从原始结果生成 REPORT.md，已运行 |

## 受阻

| 项目 | 原因 | 继续所需 |
|---|---|---|
| Linux GPU + vLLM 实测 | 本机没有 WSL/Docker，也没有 Linux GPU 机器 | 三选一：同意在本机安装 WSL2（8 GB / 4 GB swap，测试期间让 Ollama 空闲）；提供一台 Linux GPU 机器的 SSH；批准租用云 GPU 的预算 |
| 本地 Qwen 分诊评测 | 19:05Z 冻结合同时，11437 上的 Ollama 已不在运行（没有进程，也没有监听；日志最后一行约 06:47Z，没有退出记录；10-07 以来没有重启过）。原因**未查明**，没有擅自重启 | Jeff 决定何时启动 r2 并加载 7B，之后冻结 `eval-v2` |

## 本轮发现的、别处容易漏掉的问题

1. **换行符让哈希冻结失效**：Windows 上的 Python 写出 CRLF，Git 按 LF 存储，克隆后每个样本的哈希都会对不上，评测会拒绝运行。已改为写 LF，证据目录按字节存储（`-text`），并加了检查测试。
2. **原始工具输出多了一个 CR**：Windows 工具输出 CRLF，写文件时 `\n` 又被展开一次，存成了 `\r\r\n`。d14/d15 已恢复为工具的实际字节。
3. **`--api-key` 不保护 `/health` 和 `/metrics`**（官方文档原文），所以服务只监听 loopback，对外必须经过网关。
4. **同一个 tag 可能对应不同权重**：`qwen2.5-coder:7b` 可以被重新 pull，所以评测按 digest 钉模型，digest 不符时拒绝运行。
5. **iverilog 在干净环境下静默失败**：没有 COMSPEC 时退出码是 4294967295，而且没有任何输出。这批运行保留为基础设施类样本。
6. **墙钟超时会丢掉 vvp 的缓冲输出**：所以墙钟超时的责任方只能记为“未定”。
