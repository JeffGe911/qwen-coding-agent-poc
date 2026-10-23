# Qwen Coding Agent PoC

单机可运行的小型 Coding Agent：**本地 Qwen API → pytest 失败基线 → 单文件修复提案 → 策略校验与差异 → 人工审批 → 受限执行 pytest → 审计记录**。同一个本地模型 API 还用于芯片测试数据分析和日常工程自动化（见“芯片数据分析”一节）。不做通用 Agent 平台。

**结果首页：[evidence/index.html](evidence/index.html)**（所有数字由 `scripts/build_index.py` 从原始证据文件生成）

## 当前状态（2026-10-23，单机）

| 环节 | 状态 | 证据 |
|---|---|---|
| 环境检查（Windows 11、Ultra 9 275HX、32GB、RTX 5070 Ti Laptop 12GB） | 已实测 | [evidence/env/](evidence/env/) |
| 本地模型 API：Ollama 0.40.9 + qwen2.5-coder:7b Q4_K_M，`/v1/chat/completions`，仅 127.0.0.1 | 已实测，100% GPU 驻留 | [evidence/serving/](evidence/serving/) |
| 并发 1/2/4 与上下文 4K→8K→4K 测量 | 已实测（冒烟级） | 同上 |
| 新任务 `report_pass_rate`：需求原文 + 21 个测试，在任何模型调用前冻结 | 已完成 | [任务目录](qwen_agent/tasks/report_pass_rate/) |
| 首次盲测：修复前 pytest 8/21 失败基线、模型原始提案与差异 | 已实测 | [演示页](evidence/report-pass-rate/view/demo.html) |
| **人工审批与修复后 pytest** | **待审批，未验证** | 见下方“审批” |
| 芯片数据分析（合成数据）：质量检查、良率/记录通过率、失败项目、异常集中、分布与趋势、版本与运行对比、日志提取、每日汇总、异常清单 | 已实测；SQL 交叉核对一致；手工小样本 18/18 一致 | [报告](evidence/chip-analysis/report.html) |
| 芯片数据闭环任务 `chip_final_yield`：需求 + 22 个测试冻结；修复前 4/22；7B 首次盲测提案 | 已生成提案，**待审批，未验证** | [运行目录](evidence/chip-yield-agent/runs/) |
| 本地 Qwen 解释分析结果 | 已实测；三版提示词均保留；人工复核发现错误，**不可直接采信** | [复核记录](evidence/chip-analysis/explanation_review.md) |
| Docker 执行器 | **未验证**：本机没有 Docker/WSL；本次显式使用 restricted 模式 | — |
| Linux + Docker + vLLM、两台服务器 | **未验证**：无服务器访问权限 | [deploy/](deploy/)、[scripts/env_check.sh](scripts/env_check.sh) |

框架测试 87 个通过（[原始输出](evidence/framework-tests-20261023-round2.txt)），那是代码自测，**不是模型修复成功率**。

## 业务例子：测试报告通过率

内部自动化测试报告把“跳过”的用例算进分母。2 passed、1 failed、1 skipped 时原程序输出 0.5，正确应为 0.6667。需求和缺陷代码逐字取自任务说明，见 [task.json](qwen_agent/tasks/report_pass_rate/task.json)。

- **公开测试** 9 个，会发给模型：混合结果、空列表、全部跳过、全部通过、全部失败、四舍五入、未知状态、缺失状态、输入不变性。
- **holdout 测试** 12 个，不发给模型，失败详情也不反馈：值类型、跳过不入分母、大批量、大小写/None/空串等未知状态、抛错时输入不变、额外字段。
- [frozen.json](qwen_agent/tasks/report_pass_rate/frozen.json) 记录四个任务文件的 SHA-256。框架测试会校验摘要，并证明原代码 8/21、参考实现 21/21。参考实现只存在于框架测试中，从不发给模型。
- 历史的 `test_summary` 任务说明和公开断言是在看到模型失败后调整过的，它的成功**不是盲测**。调整过程保留在 [BUSINESS_DEMO.md](BUSINESS_DEMO.md) 和 `evidence/business-demo*`。

## 启动与复现（Windows PowerShell，在本目录执行）

本工作区已有虚拟环境 `..\..\work\.venv` 和便携 Ollama `..\..\work\runtime`。

```powershell
$py = "..\..\work\.venv\Scripts\python.exe"
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

停止服务时，用启动记录 `evidence\serving\ollama-launch-*.json` 中的 pid 执行 `Stop-Process -Id <pid>`。11435 端口上的旧实例由更早的会话启动，本次没有改动它。

从零安装：先执行 `python -m venv .venv`，再执行 `pip install -r requirements-lock.txt` 和 `pip install -e . --no-deps`。然后下载 Ollama 便携版，并在可联网时执行 `ollama pull qwen2.5-coder:7b`。之后运行完全离线。

## 审批（必须由人完成）

本次盲测停在待审批。审批人需要先看差异，再决定：

```powershell
& $py -m qwen_agent show evidence\report-pass-rate\runs\20261023T193344Z-report_pass_rate-af15fe39
& $py -m qwen_agent decide evidence\report-pass-rate\runs\20261023T193344Z-report_pass_rate-af15fe39 approve --digest 4389e85471b596354cc57cbf85cf701a36e5cafd92f35e09ba061e82ca3081d2 --reviewer 你的名字
& $py scripts\render_test_summary_demo.py evidence\report-pass-rate\runs\20261023T193344Z-report_pass_rate-af15fe39 --output evidence\report-pass-rate\view
& $py scripts\build_index.py
```

芯片良率闭环任务的待审批运行：

```powershell
& $py -m qwen_agent show evidence\chip-yield-agent\runs\20261023T200053Z-chip_final_yield-3d2bde61
& $py -m qwen_agent decide evidence\chip-yield-agent\runs\20261023T200053Z-chip_final_yield-3d2bde61 approve --digest ef559867f6c1c1db51405b3ced7eefc8f0044ea91791efc1c440717b62c30046 --reviewer 你的名字
& $py -m qwen_agent report --runs evidence/chip-yield-agent/runs --output evidence/chip-yield-agent/summary
& $py scripts\build_index.py
```

审阅者备注（Claude 阅读代码所得，未执行验证）：这份 chip_final_yield 提案很可能通不过测试。它把 mV 行的上下限也除以了 1000；把同轮次冲突行当作重复行忽略，而不是抛出 ValueError；没有取最大重测轮次；良率没有保留四位小数。批准会在 restricted 模式下运行测试，并把公开测试失败反馈给模型，生成第二个提案；拒绝则直接结束。由你决定。

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
- **与 Coding Agent 闭环**：`chip_final_yield` 要求模型修复一个从 CSV 行计算最终良率的函数。测试覆盖正常数据、缺失值、重复记录、重测、单位不一致、空文件、冲突、边界和输入不变性，公开 11 个、holdout 11 个，在模型调用前冻结。模型只能改 `solution.py`，审批绑定测试快照摘要。当前待审批。
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
