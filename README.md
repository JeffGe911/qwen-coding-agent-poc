# Qwen Coding Agent PoC

单机可运行的小型 Coding Agent：**本地 Qwen API → pytest 失败基线 → 单文件修复提案 → 策略校验与差异 → 人工审批 → 受限执行 pytest → 审计记录**。同一个本地模型 API 还用于芯片测试数据分析和日常工程自动化（见“芯片数据分析”一节）。不做通用 Agent 平台。

**结果首页：[evidence/index.html](evidence/index.html)**（所有数字由 `scripts/build_index.py` 从原始证据文件生成）。给管理层的一页说明：[CEO_ONE_PAGER.md](CEO_ONE_PAGER.md)。本轮总结（四类状态）：[evidence/ROUND-20261024-linux-serving-triage.md](evidence/ROUND-20261024-linux-serving-triage.md)

## 当前状态（2026-10-23，单机）

| 环节 | 状态 | 证据 |
|---|---|---|
| 环境检查（Windows 11、Ultra 9 275HX、32GB、RTX 5070 Ti Laptop 12GB） | 已实测 | [evidence/env/](evidence/env/) |
| 本地模型 API：Ollama 0.40.9 + qwen2.5-coder:7b Q4_K_M，`/v1/chat/completions`，仅 127.0.0.1 | 已实测，100% GPU 驻留 | [evidence/serving/](evidence/serving/) |
| 并发 1/2/4 与上下文 4K→8K→4K 测量 | 已实测（冒烟级） | 同上 |
| 新任务 `report_pass_rate`：需求原文 + 21 个测试，在任何模型调用前冻结 | 已完成 | [任务目录](qwen_agent/tasks/report_pass_rate/) |
| 首次盲测：修复前 pytest 8/21 失败基线、模型原始提案与差异 | 已实测 | [演示页](evidence/report-pass-rate/view/demo.html) |
| 人工审批与修复后 pytest（report_pass_rate） | Jeff 在对话中批准第一份提案；21/21 通过，含 12 个从未发给模型的 holdout；示例数据实际输出 0.5 → 0.6667 | [演示页](evidence/report-pass-rate/view/demo.html) |
| 芯片数据分析（合成数据）：质量检查、良率/记录通过率、失败项目、异常集中、分布与趋势、版本与运行对比、日志提取、每日汇总、异常清单 | 已实测；SQL 交叉核对一致；手工小样本 18/18 一致 | [报告](evidence/chip-analysis/report.html) |
| 芯片数据闭环任务 `chip_final_yield`：需求 + 22 个测试冻结；修复前 4/22；7B 首次盲测提案 | 提案 1 经 Jeff 批准执行：8/22，修复失败；提案 2、3 是无法解析的 Python，执行前被拦截；三次预算用完，**未修复成功**。事后查服务日志：三次生成都在中途触发 context shift（每请求上下文 4096），原证据被部分污染；提案 1 的大部分 code 在 shift 之前生成 | [运行目录](evidence/chip-yield-agent/runs/)、[context-shift.json](evidence/chip-yield-agent/context-shift.json) |
| 上下文溢出与输出截断的配置验证（r1 原配置 vs r2 上下文 8192 × 并行 1 vs r2b 再加输出预算 4096） | r2 / r2b 上没有再出现 context shift（最高 7662/8192）；chip_final_yield 4 份提案都因输出退化重复、达到输出预算而截断，**仍未修复**；report_pass_rate 在 r1、r2 上经批准后各 21/21。当时 r2 只是候选；2026-10-24 已按指示激活 r2（见下一行） | [验证报告](evidence/context-validation/REPORT.md) |
| 激活 r2（2026-10-24）与 chip_final_yield 评测合同 rev 2（单变量对照：格式 / 采样 / 14b） | ACTIVE = r2；门禁原始结果未通过，只豁免已知的 chip 生成失败（记录在发布历史），健康检查与 report_pass_rate 21/21 通过。rev 2：A/B/C 每组都消除了重复退化（对照组 3/3 重复），但 chip 仍未修复（批准后 A 7/22、C 3/22、B 1/22） | [激活证据](evidence/release-r2-activation/)、[rev 2 报告](evidence/chip-rev2/REPORT.md) |
| 本地 Qwen 解释分析结果 | 已实测；三版提示词均保留；人工复核发现错误，**不可直接采信** | [复核记录](evidence/chip-analysis/explanation_review.md) |
| 仿真回归日志分诊：受限执行器真实运行 Icarus / Verilator，规则基线，评测合同 eval-v1 | 已实测。dev 37/37（规则照着它写，不算效果）；**独立 holdout 盲测类别 15/39**，错误中 22/24 是回答 unknown，没有 pass/fail 颠倒；需关注测试 precision 11/11、recall 11/24 | [分诊报告](evidence/regression-triage/REPORT.md) |
| 本地 Qwen 分诊（固定 schema、引用校验、注入与截断检测、按 digest 钉模型） | **只有代码和单元测试**：评测时 11437 上的 Ollama 不在运行（原因未查明），未擅自重启 | 同上 |
| Docker 执行器 | **未验证**：本机没有 Docker/WSL；本次显式使用 restricted 模式 | — |
| Linux + Docker + vLLM 单机部署（固定 digest 镜像、loopback、API key、资源限制、8 项验收脚本） | **阻塞**：本机没有 WSL/Docker，也没有 Linux GPU 机器。只有部署文件、静态检查和用替身命令做的脚本逻辑测试 | [STATUS](evidence/linux-serving/STATUS.md)、[RUNBOOK](deploy/linux-vllm/RUNBOOK.md) |
| 两台服务器 | **未验证**：无服务器访问权限 | [scripts/env_check.sh](scripts/env_check.sh) |

测试 157 个通过（[原始输出](evidence/regression-triage/pytest-summary.txt)；之前 104、98、87 个）。这是代码自测，**不是模型修复成功率，也不是分诊准确率**。

## 业务例子：测试报告通过率

内部自动化测试报告把“跳过”的用例算进分母。2 passed、1 failed、1 skipped 时原程序输出 0.5，正确应为 0.6667。需求和缺陷代码逐字取自任务说明，见 [task.json](qwen_agent/tasks/report_pass_rate/task.json)。

- **公开测试** 9 个，会发给模型：混合结果、空列表、全部跳过、全部通过、全部失败、四舍五入、未知状态、缺失状态、输入不变性。
- **holdout 测试** 12 个，不发给模型，失败详情也不反馈：值类型、跳过不入分母、大批量、大小写/None/空串等未知状态、抛错时输入不变、额外字段。
- [frozen.json](qwen_agent/tasks/report_pass_rate/frozen.json) 记录四个任务文件的 SHA-256。框架测试会校验摘要，并证明原代码 8/21、参考实现 21/21。参考实现只存在于框架测试中，从不发给模型。
- 历史的 `test_summary` 任务说明和公开断言是在看到模型失败后调整过的，它的成功**不是盲测**。调整过程保留在 [BUSINESS_DEMO.md](BUSINESS_DEMO.md) 和 `evidence/business-demo*`。

## 上下文溢出与输出截断（2026-10-23 配置验证）

完整对照见 [evidence/context-validation/REPORT.md](evidence/context-validation/REPORT.md)，由 `scripts/build_context_report.py` 从原始证据生成。

- **发现的问题**（两个独立问题）：
  - 上下文容量：原服务每请求上下文 4096（2 个槽位）。原盲测 chip_final_yield 的三份提案（提示词 3584 / 3831 / 3866 token）在生成中途触发 context shift，llama-server 丢弃了提示词前部的 2045 个 token，API 仍返回 `finish_reason=stop`，当时的 Agent 没有察觉。
  - 输出预算：接手后的门禁（提示词 2891）和 r1 重跑（3395）既触发 context shift，又在 1600 个输出 token 处被截断（`finish_reason=length`），JSON 不完整。
- **改了什么**：
  - Agent 分开检查“输出未正常结束”“提示词 + 输出达到上下文”“服务端上下文与运行配置不一致”，命中任何一项都记为 model_error，不进入审批。前提是运行配置里有 context_tokens：显式传 `--context-tokens`，或使用 ACTIVE 发布的 base-url / model 时自动取得；没有时（例如 vLLM 或网关）不检查溢出。
  - 输出预算可用 `--max-tokens` 设置并写入运行配置（进入审批摘要），默认 1600。本轮 r1 / r2 的运行没有显式设置，配置里没有这个字段；之后的运行会始终记录。
  - 提示词模板与 schema（prompt_sha256）、策略、冻结测试都没改。但实际用户消息里含运行目录路径和 pytest 输出，各次 chip 提示词的 token 数不同（3395 / 3413 / 3476…），配置之间的对比不是逐字相同的输入。
  - 新增 `qwen_ops logscan`，从服务日志统计 context shift、截断、CPU 卸载、GPU 错误和启动告警（各日志的扫描结果见 logscan/）。
  - 用不可变的发布清单保存 r1（原配置）、r2（上下文 8192 × 并行 1）、r2b（r2 加输出预算 4096）。
  - 修复启动脚本：本轮有一次启动的调用方挂起、被强制结束，判断为句柄继承所致。改为 ShellExecute 启动后，从 Git Bash 和 Python（qwen_ops validate）调用都正常返回。
- **证据**：
  - 每套配置有 `summary.json`：请求值与日志里的实际生效值、显存、首轮各提案的 token 用量、finish_reason、JSON/Python/策略结果。r2b 的提案 2、3 在运行目录里。
  - chip 运行只有模型原始响应，没有差异和 pytest，因为没有产生提案。差异和 pytest 只在 report_pass_rate 运行中。
  - 每次启动的服务日志在 server-logs/，审批记录在 approval-record.md。
- **已解决**：
  - 在 max_tokens ≤ 4096、最多 3 次提案的条件下，r2 / r2b 没有再溢出（最高 7662 / 8192），服务日志里 context shift 为 0。但 chip 的输出从未正常结束，一个完整答案需要多少上下文仍不知道。
  - 实测中，溢出 + 截断的输出被 Agent 记为 model_error，没有进入审批。“返回 stop 但溢出”的情况只在框架测试里验证过。
  - r1 和 r2 显存基本相同（整卡 5082 / 5090 MiB，KV 总量都是 8192 token），没有 CPU 卸载（29/29 层在 GPU，驻留 100%）。
  - 原配置可以恢复，`release verify` 无差异。
- **仍失败 / 未确定**：
  - chip_final_yield：r2（max_tokens 1600）和 r2b（4096）共 4 份提案，code 字符串都闭合了，但随后 explanation 一直重复，直到用完预算。JSON 不完整，没有可审批的代码，业务正确性无从验证。其中 r2b 提案 2 的 code 本身还有语法错误。本轮只有这一个任务、温度 0，在 1600 和 4096 两个预算下都退化，没有证据表明继续加预算能解决。改提示词或输出格式会改变评测合同（prompt_sha256）；采样参数（温度固定为 0，写在客户端里）目前不在合同和运行配置里，改之前应先把它记进去。
  - r2 只有 1 个并行槽位，同时到达的第二个请求要排队；本轮没有做并发测试。
- **回归**：report_pass_rate 在 r1、r2 上各开一个新运行。Jeff 在对话中批准后（摘要 e844f457… / 8bb2baba…，展示的差异见 approval-record.md），pytest 均为 21/21（含 12 个 holdout）。

## chip_final_yield 评测合同 rev 2（2026-10-24）

合同文件 [qwen_agent/contracts/chip_final_yield/rev2.json](qwen_agent/contracts/chip_final_yield/rev2.json) 在任何一组运行前提交冻结。任务文件、公开测试、holdout 与策略和 rev 1 相同；r1 与它的证据没有改动。报告见 [evidence/chip-rev2/REPORT.md](evidence/chip-rev2/REPORT.md)，表中数字由 `scripts/build_chip_rev2_report.py` 从原始证据计算。

- 先激活 r2：`python -m qwen_ops release activate --name r2-7b-ctx8192-np1 --accept-failing chip_final_yield --approved-by ... --reason ...`。只豁免这一个已知的任务失败（r1 上同样失败）；版本钉、服务健康和 report_pass_rate 不可豁免。激活后的健康检查和 validate 结果在 evidence/release-r2-activation/；report_pass_rate 经批准后 21/21（公开 9/9、holdout 12/12）。
- `/v1/chat/completions` 会忽略 `repeat_penalty`，所以 rev 2 的各组（含对照组）都走原生 `/api/chat`，并显式写全采样参数。原生接口的默认值（temperature 0.8、top_p 0.9）与 rev 1 实际生效的值不同。同一请求经原生接口 + 对照组参数，输出与经 `/v1` 逐字相同。
- 结果：对照组（rev 1 设置）3/3 重复退化并截断；A（围栏代码块 + 解释最多 3 句）、B（temperature 0.2、repeat_penalty 1.1）、C（qwen2.5-coder:14b，8192 上下文下 100% 在 GPU，驻留 9.6 GiB）都没有再出现重复。但批准后的 pytest 都没通过：A 7/22、C 3/22、B 1/22，原始有缺陷代码是 4/22。14b 的生成速度约为 7b 的一半。
- 结论：重复退化是解码问题，改输出格式就能解决，不需要更大的模型；业务正确性在 7b 和 14b 上都没有达到。服务器选型的估算见报告结论。

运行方式：`python -m qwen_ops.chip_rev2 run --arm A`（提案直到需要人工审批），`python -m qwen_ops.chip_rev2 decide --arm A --digest ... --reviewer ...`（人批准后），`python -m qwen_ops.chip_rev2 vram --model qwen2.5-coder:14b`（C 组前置检查）。

## 仿真回归日志分诊（2026-10-24）

流程：读回归日志 → 抽出失败并附证据（文件、物理行号、原文）→ 指纹去重并分类（设计或测试问题 / 基础设施问题）→ 带出处的建议 → 工程师逐条确认 → 报告。建议只展示，不会执行。

```powershell
$env:QWEN_POC_EDA = "<oss-cad-suite 目录>"     # 默认 ..\..\work\tools\oss-cad-suite-20261024\oss-cad-suite
& $py -m regression_triage demo --out evidence/regression-triage/demo          # 真实跑一个混合回归，规则分诊，生成待复核报告
& $py -m regression_triage review evidence/regression-triage/demo/triage/regression.rules.json --test fifo_full --decision accept --reviewer <姓名> --note "..."
& $py -m regression_triage eval --contract evidence/regression-triage/contract/eval-v1.json --split holdout --engine rules   # 已运行过，会拒绝覆盖
```

- **真实仿真，受限执行**：使用 OSS CAD Suite 2026-10-24 的 Icarus Verilog 14.0（devel）和 Verilator 5.053（devel）。本机没有 C++ 编译器，所以 Verilator 只做 lint。只允许三种固定命令（`iverilog`、`vvp`、`verilator --lint-only`），参数由校验过的清单字段拼出，源文件必须在 `hdl/` 下，并复制到临时目录中运行。Windows Job Object 限制每个进程 512 MB、最多 8 个进程；超时整棵进程树一起结束；输出上限 1 MB。设计和 testbench 都是本仓库自写的小模块，缺陷是故意注入的，不涉及任何公司 RTL。
- **日志不可信的地方都当真处理**：runner 只记录事实（退出码、耗时、是否超时），不写结论。tool 输出里冒充 runner 的行会被转义（包括缩进的和带 BOM 的）。退出码 0 不等于通过，含 “error” 字样也不等于失败。墙钟超时的责任方记为“未定”，testbench watchdog 超时记为设计或测试问题。编译器自身的内部断言崩溃不算设计断言。日志里的提示注入只当作数据。
- **评测**：dev 25 份（17 份真实运行、8 份手写 synthetic）。holdout 25 份（19 份真实、6 份 synthetic），由另一个代理在看不到规则、prompt、评分代码和 dev 金标准的情况下编写和标注。合同 [eval-v1](evidence/regression-triage/contract/eval-v1.json) 在运行前冻结了数据、金标准和代码的哈希。`eval` 发现任一哈希不符时拒绝运行，同一拆分也不允许重跑覆盖。数据文件按字节存储（`.gitattributes` 中设为 `-text`），在任何平台上克隆后哈希都一致。
- **结果（rules-v1）**：dev 37/37；独立 holdout 类别 15/39（38.5%）。错误中 22/24 是回答“不知道”，没有把失败报成通过，也没有把通过报成失败。77 条引用全部有效。根因是规则只认识自己 testbench 的结论写法（`TEST PASSED`），holdout 用的是 `RESULT: PASS`、`MISMATCH`、`WATCHDOG:` 等。**结论词表是项目私有的**，规则引擎接入新项目前必须先配置。详见 [REPORT.md](evidence/regression-triage/REPORT.md)。
- **本地 Qwen**：代码已完成（固定 JSON schema、unknown 选项、引用逐条核对物理行、日志注入当数据处理、输出截断和上下文超限显式报告、不安全建议标记、按 digest 而不是 tag 钉模型），但只有单元测试（FakeClient）。冻结合同时 11437 上的 Ollama 已不在运行，所以没有对真实模型评测。`triage-prompt-v1` 在 holdout 出现之前已提交，之后在 holdout 上跑仍然是盲测。

## Linux + Docker + vLLM 单机部署（未验证）

[deploy/linux-vllm/](deploy/linux-vllm/) 包含以下文件。**这些文件还没有在任何 Linux GPU 机器上运行过**，状态与开始实测的最小条件见 [STATUS.md](evidence/linux-serving/STATUS.md)：
- compose：镜像 `vllm/vllm-openai:v0.32.0` 按 digest 固定，`pull_policy: never`；只发布到 127.0.0.1；API key 从 git 忽略的 `.env` 读取；运行时离线；内存、pids、shm 有限制；有健康检查和日志轮转；
- 固定 revision 的权重下载脚本（记录 sha256）；
- 8 项验收脚本：启动与真实请求、各端点有无 key 的返回码、生效配置、显存、并发 1/2/4、短/长/超限输入、停止与崩溃恢复、配置变更与回滚。脚本先做资源预检，key 不会写入任何证据文件；
- 中文操作手册。

按官方文档（2026-10-24）核对出的几点：
- 文档只写了计算能力 ≥ 7.5，以及 B200/GB200 需要 CUDA ≥ 12.8；没有明确提到 RTX 50 系列（计算能力 12.0），本机这张卡能否运行必须实测；
- Ollama 用的 GGUF 在 vLLM 中仍是 “highly experimental”，所以权重改用 safetensors（1.5B BF16 / 7B AWQ），与 Ollama 上的 Q4_K_M 不是同一份权重；
- `--api-key` 不保护 `/health`、`/metrics`，所以只监听 loopback，对外要经过网关。

详见 [docs-check.md](evidence/linux-serving/docs-check.md)。

## 启动与复现（Windows PowerShell，在本目录执行）

原工作区的虚拟环境在 `..\..\work\.venv`，便携 Ollama 在 `..\..\work\runtime`。仓库克隆到别处时，用环境变量指过去（脚本和 `qwen_ops` 都读它）。

```powershell
$py = "..\..\work\.venv\Scripts\python.exe"          # 或该 venv 的绝对路径
$env:QWEN_POC_RUNTIME = "..\..\work\runtime"          # 含 ollama\ollama.exe 和 models\ 的目录；默认值同此
$env:PYTHONIOENCODING = "utf-8"

# 1. 环境检查（只读）
powershell -ExecutionPolicy Bypass -File scripts\env_check.ps1

# 2. 启动模型服务：127.0.0.1:11437，上下文 4096，2 个并行槽位，禁用云模型；端口被占用时拒绝启动
powershell -ExecutionPolicy Bypass -File scripts\start_ollama.ps1

# 3. 验证 API、驻留与真实请求
& $py -m qwen_agent doctor --base-url http://127.0.0.1:11437/v1 --model qwen2.5-coder:7b
& $py scripts\api_smoke.py --base-url http://127.0.0.1:11437/v1 --model qwen2.5-coder:7b

# 4. 框架测试
& $py -m pytest -q -p no:cacheprovider

# 5. 新开一次运行：基线 → 提案 → 停在待审批
& $py -m qwen_agent start --task report_pass_rate --model qwen2.5-coder:7b --base-url http://127.0.0.1:11437/v1 --sandbox restricted --runs evidence/report-pass-rate/runs

# 6. 测量
& $py scripts\serving_probe.py --base-url http://127.0.0.1:11437/v1 --model qwen2.5-coder:7b --levels 1,2,4 --count 8 --output evidence\serving\serving-7b-new.json
& $py scripts\kv_probe.py --base-url http://127.0.0.1:11437/v1 --model qwen2.5-coder:7b --output evidence\serving\kv-context-7b-new.json

# 7. 页面
& $py -m qwen_agent report --runs evidence/report-pass-rate/runs --output evidence/report-pass-rate/summary
& $py scripts\build_index.py
```

停止服务：`powershell -ExecutionPolicy Bypass -File scripts\stop_ollama.ps1 -Port 11437`。脚本只停本工作区 `ollama.exe` 监听的端口，并结束其进程树（含占显存的 llama-server）。11435 上的旧实例是早期运行（live-runs、business-demo、evidence/serving.json）用过的模型服务，启动者未记录；本轮没有对它执行启动或停止命令。本轮的进程快照和一次只读检查都显示它已不在运行（evidence/context-validation/00-state-before-restore/），退出原因**未查明**，也没有重新启动。

运维检查（`qwen_ops`）：

```powershell
& $py -m qwen_ops health --port 11437 --model qwen2.5-coder:7b     # 分层：进程 / 端口 / API / 固定答案 / GPU 驻留 / 磁盘；退出码 = 第一个失败层
& $py -m qwen_ops logscan --port 11437                              # 服务日志中的 context shift、截断、CPU 卸载、GPU 错误、5xx
& $py -m qwen_ops release show                                      # 当前 ACTIVE 发布及其清单
& $py -m qwen_ops release verify --name r1-7b-ctx4096               # 运行中的服务与清单（二进制、版本、模型 digest、参数）是否一致
& $py -m qwen_ops validate --label <名字> --context 8192 --parallel 1   # 一套配置的分层验证，证据写入 evidence/context-validation/<名字>/
& $py scripts\build_context_report.py                               # 由原始证据重新生成对照报告
```

从零安装：先执行 `python -m venv .venv`，再执行 `pip install -r requirements-lock.txt` 和 `pip install -e . --no-deps`。然后下载 Ollama 便携版，并在可联网时执行 `ollama pull qwen2.5-coder:7b`。之后运行完全离线。

## 审批（必须由人完成）

### 本轮审批记录（2026-10-23）

Jeff 在对话中批准了两份首次盲测提案，随后执行了 decide 命令。审计事件里的 reviewer 字段保留当时写入的原文；控制台输出保存在 [report-pass-rate/approval-console.txt](evidence/report-pass-rate/approval-console.txt) 和 [chip-yield-agent/approval-console.txt](evidence/chip-yield-agent/approval-console.txt)。

| 任务 | 批准的摘要 | 结果 |
|---|---|---|
| report_pass_rate | `4389e854…` | 21/21 通过，任务成功 |
| chip_final_yield | `ef559867…` | 提案 1 为 8/22，修复失败；自动生成的提案 2 把关键字 `yield` 当变量赋值，提案 3 有未闭合的 f-string，两者都是无法解析的 Python，在执行前被拦截；三次预算用完，最终归入“策略拦截”，没有修复成功 |

批准前的代码审阅备注是：chip_final_yield 提案 1 很可能通不过测试，因为它把 mV 行的上下限也除以了 1000，把冲突行当重复行忽略，没有取最大重测轮次，也没有保留四位小数。执行结果证实了这一判断。

### 新运行如何审批

```powershell
& $py -m qwen_agent show <运行目录>
& $py -m qwen_agent decide <运行目录> approve --digest <show 打印的完整摘要> --reviewer 你的名字
& $py scripts\build_index.py
```

拒绝时把 `approve` 换成 `reject`。批准后若 pytest 失败，系统只把公开测试的失败信息反馈给模型，生成新提案后再次等待审批，最多三个提案。交互式用法是 `demo` 命令，需输入 `approve 完整摘要`，回车或 EOF 会保留待审批。系统没有自动批准开关。

摘要绑定以下内容：run_id、任务、配置、提案序号、代码、解释、三个工作文件，以及契约摘要。契约摘要覆盖提示词、策略文件和冻结的任务文件。任何一项改变，旧批准都会失效。

## Agent 护栏

- **模型权限**：模型只返回 JSON `{code, explanation}`，即完整的 `solution.py`。它没有 shell、路径、文件写入或依赖安装权限，也看不到 holdout。
- **API**：只接受 loopback 地址，禁用环境代理和重定向，没有云回退。
- **策略校验**：使用 AST 白名单（[policy.py](qwen_agent/policy.py)，修订 2）加编译检查。提示词中的允许子集由同一组常量生成。被拦截时自动带原因重新提案，计入三次预算，不执行。
- **空转检测**：提案与当前文件相同时以 `no_change` 结束。与本运行任何更早提案相同时以 `duplicate_proposal` 结束，不再请求模型。
- **执行器**：默认是 Docker，提供无网络、只读根与只读工作目录、非 root、cap-drop、no-new-privileges、256MiB、1 CPU、32 进程、20 秒超时，且只运行固定 pytest。本机没有 Docker，因此显式使用 `--sandbox restricted`：受限 builtins、独立解释器、干净环境、超时。**restricted 不是操作系统级沙箱**，只适合本项目内经人工审阅的可信小任务。
- **记录**：`state.json` 记录状态、各提案状态、生成耗时、token、审批人、等待时长、pytest 计数与耗时和终止原因。`events.jsonl` 是追加式审计，`.lock` 防止并发决策。

## 统计口径

每次运行只归入一类：任务成功、修复失败、待审批、策略拦截、模型/API 错误、基础设施错误；人工拒绝单列。报告同时给出两个比率：

- 全部启动运行成功率 = 任务成功 / 全部启动运行
- 已完成执行评测成功率 = 任务成功 / (任务成功 + 修复失败)

待审批运行的代码尚未执行，不计入第二个分母。不同任务、模型、提示词版本和调整前后的运行不能合并成一个“模型成功率”。

## 排障

| 现象 | 处理 |
|---|---|
| `Port 11437 is already listening` | 启动脚本拒绝覆盖已有服务。先用 `Get-NetTCPConnection -LocalPort 11437` 查看，或换 `-Port`。 |
| doctor 报 `Requested model is not loaded/available` | 检查模型名，以及 `OLLAMA_MODELS` 是否指向 `work\runtime\models`。 |
| `API URL must be loopback` | 这是设计行为。远程服务请通过内部网关或 SSH 隧道映射到本机。 |
| api_smoke 显示 GPU 占比 < 100% | 显存不足，部分层落到 CPU。关闭占显存的程序（本机有游戏客户端占用），或降低上下文/并行槽位，或改用 1.5B。 |
| 并发时第一批请求约 8 秒 | 本机观测到的一次性预热，重测未复现。正式测量前先预热。 |
| `Docker is required` | 安装 Docker 并执行 `docker build -t qwen-agent-sandbox:0.1 .`；或者显式选择 `--sandbox restricted`，它只适用于可信演示。执行器容器不需要 GPU；NVIDIA Container Toolkit 只有 vLLM 推理容器才需要。 |
| `Approval digest mismatch` | 提案、测试、配置或契约已变化。重新 `show` 并审阅新摘要。 |
| `Run is locked` / 状态停在 `executing` | 有进程中断。先检查再手动删除 `.lock`，系统不会自动重放。 |
| PowerShell 中文乱码 | 设置 `$env:PYTHONIOENCODING = "utf-8"`。 |
| nvidia-smi 显示 CUDA 13.1 但没有 nvcc | 正常。前者是驱动能力，Ollama 自带 CUDA 运行库（`lib\ollama\cuda_v13`），本机未安装 CUDA Toolkit。 |

## 设计取舍（详见 [DESIGN.md](DESIGN.md)、[OPERATIONS.md](OPERATIONS.md)）

- **为什么用 Ollama**：Windows 笔记本上便携启动、GGUF 量化、单卡门槛低。7B Q4_K_M 约 4.8GiB 驻留，12GB 显存可容纳两个 4K 槽位。vLLM 留给 Linux GPU 服务器，同一客户端只需改 URL 和模型名。
- **为什么是 7B 而不是 1.5B**：12GB 显存装得下 7B 量化版，且单请求短输出约 78 tok/s，交互可接受。历史初稿中 1.5B 没有修正分母，但那只是单次观测，不足以比较两个模型。
- **为什么返回完整单文件**：小模型更稳定，不存在补丁上下文歧义和路径穿越。代价是不能代表多文件工程修复。
- **为什么人工审批前不执行**：边界清楚，审批对象可检查。代价是增加等待时间，而且 reviewer 只是本地身份声明。
- **策略修订 2**：允许 try/except 和少量容器方法，减少对正常写法的误拦截。这一修订在盲测之前完成，并写入契约摘要。历史运行使用修订 1。

## 芯片数据分析与日常工程自动化（合成数据）

没有收到真实 CSV、Excel 或日志，因此使用**明确标记为合成数据**的芯片测试数据：3 个批次、2 次运行、240 颗芯片、5 个测试项目、1629 行，另有一份测试机日志。字段说明和刻意注入的数据问题见 [data/synthetic/FIELDS.md](data/synthetic/FIELDS.md)。字段只是示例，不代表公司真实结构。

```powershell
& $py -m chip_analysis synth --out data/synthetic
& $py -m chip_analysis analyze data/synthetic/raw --items data/synthetic/items.json --logs data/synthetic/logs --hand-check data/handcheck --out evidence/chip-analysis --explain
& $py -m chip_analysis ask "分析这个目录里的测试 CSV，按批次汇总，找出失败最多的五个项目，并生成报告" --dir data/synthetic/raw --items data/synthetic/items.json --execute
& $py -m chip_analysis merge data/synthetic/raw --items data/synthetic/items.json --out evidence/chip-analysis/merged.csv
& $py -m chip_analysis extract-log data/synthetic/logs/tester_R2_2026-10-22.log --out evidence/chip-analysis/log_failures.csv
& $py -m chip_analysis daily data/synthetic/raw --items data/synthetic/items.json --date 2026-10-22
& $py -m chip_analysis compare-runs data/synthetic/raw --items data/synthetic/items.json --base R1 --new R2 --lots LOT-A02
& $py -m chip_analysis review data/synthetic/raw --items data/synthetic/items.json --min-severity error --out evidence/chip-analysis/review_errors.csv
& $py -m chip_analysis hand-check data/handcheck
```

- **先检查再统计**：程序检查空文件、重复行、同轮次冲突、缺失值、缺状态、单位换算、上下限不一致、状态与上下限矛盾、不可信值（稳健 z > 8）和不完整芯片。还会校验“一行 = 一次测量”这一粒度。生成器注入的问题全部被检出，有框架测试覆盖。
- **两个指标分开**：测试记录通过率按行计算；芯片良率按芯片计算，分“全部”和“仅完整”两个分母，另给首测良率。重测取最大轮次。所有口径都写成假设 A1–A10，报告逐条列出，没有套用任何行业或公司口径。
- **可追溯**：异常清单 `review_list.csv` 的每行都带源文件、物理行号和原始行文本；运行对比的每一项都带两次运行的来源行。
- **可复现与核对**：生成器使用固定种子，输出逐字节可复现。关键指标再用 SQLite 独立计算一遍，与 Python 结果比对。另有 13 行手写样本，手算过程见 [HAND_CHECK.md](data/handcheck/HAND_CHECK.md)，程序结果 18/18 项一致。
- **日常工程任务**：合并多文件并统一字段（含不同列名和 P/F/S 状态）、从日志提取失败项目（截断行单独列出）、每日汇总、两次运行的新增失败和已修复对比、按规则导出待复核清单。五项都已跑通。
- **模型的角色**：本地 Qwen 只做两件事。一是把自然语言请求路由到固定命令，两条示例请求都路由正确。二是根据程序算好的 facts 写解释，并由程序检查证据键、数字来源以及数字与所述运行/批次是否对应。三版提示词的输出都保留；第三版仍把 R2/LOT-B01 的数字说成 R1/LOT-A02，还称“数据质量良好”。因此报告结论以程序计算为准，模型解释只作草稿。这个 7B 是代码模型，写分析结论不是它的强项。
- **与 Coding Agent 闭环**：`chip_final_yield` 要求模型修复一个从 CSV 行计算最终良率的函数。测试覆盖正常数据、缺失值、重复记录、重测、单位不一致、空文件、冲突、边界和输入不变性，公开 11 个、holdout 11 个，在模型调用前冻结。模型只能改 `solution.py`，审批绑定测试快照摘要。结果：7B 首次盲测没有修复成功，提案 1 执行后 8/22，后两份提案是无法解析的代码。之前把它归结为“超出 7B 的可靠范围”。事后查服务日志发现，三份提案都在生成中途触发了 context shift，所以原证据被部分污染，不足以单独支持这个结论。但提案 1 的大部分 code 是在 shift 之前生成的，8/22 也不能只怪配置。上下文加到 8192 后（r2 / r2b），在当前提示词、温度 0、max_tokens 1600 / 4096 下，7B 仍然没有给出完整、可审批的提案：输出退化重复、达到预算。见上文“上下文溢出与输出截断”。
- **数据不出本机**：模型 API 只接受 127.0.0.1。发给模型的是聚合后的 facts，不含原始行。没有遥测或外部分析服务。

## 两台服务器接入时

尚未执行，以下均为计划：

1. 在两台服务器上运行 `bash scripts/env_check.sh`。它只读，不安装、不重启服务，可以记录 GPU、驱动、nvcc、Docker、NVIDIA Container Toolkit、已有推理服务和端口。
2. 如果单卡能装下目标模型，先在一台服务器上用 [deploy/compose.vllm.yaml](deploy/compose.vllm.yaml) 跑通 vLLM + 网关，用同一 Agent 客户端回归 `report_pass_rate`。7B 候选是 `Qwen/Qwen2.5-Coder-7B-Instruct`（BF16 约 15GB）或官方 AWQ 量化版，两者都需要先在目标 GPU 上验证。
3. 第二台服务器的用途在盘点之后再决定：可以作为执行候选代码的隔离主机（Docker 执行器，与推理主机分开），也可以作为第二个推理副本。不要预设跨机张量并行。

## 历史实测（保留，口径与本次不同）

旧会话在 Ollama 0.40.9 上使用 `qwen2.5-coder:1.5b` 和策略修订 1，在三个玩具任务上运行：clamp 成功；chunked 修复失败，第二个提案原样返回；normalize_names 三次提案都被策略拦截（set.add，当时不允许）。流程成功率为 1/3。详见 [evidence/live-runs/](evidence/live-runs/)、[evidence/report.html](evidence/report.html)。人工审批来自当时对话中用户的明确批准，审计事件里的 reviewer 为 `Jeff`。

本地鉴权网关（loopback、Bearer token、四个端点白名单）的用法和验证见 [OPERATIONS.md](OPERATIONS.md) 和 [evidence/local-ops.json](evidence/local-ops.json)。

```powershell
$env:LOCAL_MODEL_API_KEY = (& $py -c "import secrets; print(secrets.token_hex(32))")
& $py -m qwen_agent.gateway --upstream http://127.0.0.1:11437/v1 --port 11436
```
