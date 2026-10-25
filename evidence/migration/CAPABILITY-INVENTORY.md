# 部署迁移能力盘点（2026-10-25）

范围：把现有的 Coding Agent 和仿真日志分诊应用，从 Windows 上的 Ollama 迁到 Linux 上的 Docker + vLLM。盘点依据是代码、各分支的报告和原始证据。**配置文件写好了，不等于部署完成。** 下面的“实测”都是在一台 Windows 笔记本（RTX 5070 Ti Laptop 12 GB，单用户）上完成的，没有任何一项是在 Linux、多用户或生产环境里做的。

## 一、已实测

| 能力 | 做了什么 | 如何验证 | 证据 | 限制 |
|---|---|---|---|---|
| 本地模型服务的启动、停止和发布记录 | 便携 Ollama 只监听 127.0.0.1。端口被占用时拒绝启动。每次启动都写一份启动记录。发布清单记录二进制 sha256、版本、模型 digest 和参数 | 2026-10-25 发现 11437 已停止。之后重新启动 r2，`release verify` 没有报告任何问题 | evidence/migration/baseline-ollama-r2/01-start.txt、02-release-verify.txt | Windows 便携版，单机 |
| 分层健康检查 | 依次检查进程、端口、API、固定答案、GPU 驻留和磁盘，退出码指出第一个失败的层 | 2026-10-25 结果 healthy：100% 在 GPU，上下文 8192 | 03-health.txt | 没有常驻监控和告警 |
| 一次配置变更，再恢复原配置 | r1（4096 × 2）→ r2（8192 × 1）→ r2b，再恢复到 r1 并重新验证 | 恢复后验证通过；对比报告由原始证据生成 | evidence/context-validation/（r1-restore、01-restore-gpu、REPORT.md） | 在 Ollama 上完成，不是 vLLM |
| 停止后恢复 | 服务停了，原因没查明。重新启动、核对清单、做健康检查，三步都通过 | 同第一行 | baseline-ollama-r2/ | 停止不是刻意做的演练；崩溃恢复（kill 主进程）在 vLLM 上还没做 |
| 从服务日志诊断问题 | 发现两类问题：context shift 造成的静默截断，以及电池供电时 GPU 功耗受限导致生成慢 10 倍 | 服务日志的计时行加上 `nvidia-smi` 的降频原因 | evidence/context-validation/、baseline-ollama-r2/NOTE-power-throttle.md | 靠手动诊断 |
| 资源监控和预设阈值 | 加载模型前检查可用内存、提交余量和空闲显存；运行时每 2 秒采样一次，低于阈值时只结束自己的进程 | 05:16Z 预检通过后才启动；05:19–05:23 在 dev 运行中采样 124 次，没有触发中止。03:54Z 曾因提交余量不足（约 2.4–3.7 GB，低于 4 GB）不加载模型，这次只在对话里报告过，没有保存文件 | baseline-ollama-r2/00-preflight.json、model-runs/eval-v2/dev/session.json、resources.csv | 只支持 Windows 和 Ollama；Linux 上的采样写在 migrate.sh 里，尚未运行 |
| 并发与上下文测量 | 并发 1/2/4，上下文 4K→8K→4K 时的显存驻留变化 | 冒烟级，每档 8 个请求 | evidence/serving/ | 笔记本上的数字，不能推到服务器 |
| 访问限制 | 客户端只接受 loopback，不走代理，不跟随重定向，响应上限 256 KiB；本地网关提供 Bearer 鉴权和 4 个端点的白名单；没有云端回退 | 单元测试，加上网关的实测记录 | qwen_agent/client.py、evidence/local-ops.json | 单用户 |
| 业务：Coding Agent | 单文件修复提案，经人工审批后在受限执行器中跑 pytest | report_pass_rate：21/21（含 12 个 holdout）；chip_final_yield：**没有修好** | evidence/report-pass-rate/、evidence/chip-rev2/REPORT.md | 只是小任务 |
| 业务：日志分诊（规则） | 用真实的 Icarus/Verilator 运行生成日志，规则基线按冻结合同评测 | dev 37/37；独立 holdout 15/39，没有误放行 | evidence/regression-triage/REPORT-eval-v1.md | 覆盖率低：结论写法因项目而异 |
| 业务：日志分诊（本地 Qwen，迁移前基线） | Ollama r2，后端配置 ollama-r2，单并发，合同 eval-v3（与 eval-v1 数据相同，prompt 未改） | holdout 盲测类别 34/39；漏报 0/24；误放行 1；引用 7/63 通过校验；50 个请求 0 失败；中位数 3.0 s/样本 | evidence/regression-triage/REPORT-eval-v3.md、results/eval-v3-qwen/、model-runs/eval-v3/ | 缺少结论行时放行；引用对不上日志行；笔记本数据不能外推 |
| 业务：日志分诊（组合引擎） | 规则优先；规则判断不了时，采用经过守卫的 Qwen（没有结论行不能判通过，退出码矛盾也不能）；prompt v2 修正引用格式；合同 eval-v4 | 新的独立盲测集 holdout2：类别 33/45，误放行 0，漏报 5/27；Qwen v2 单独用 31/45，误放行 2 | evidence/regression-triage/REPORT-eval-v4.md | 输出预算按测试数给；规则一个测试都没识别时、或判为“日志不完整”时，都要交给模型（这两处未修，修完需要新的独立测试集）；lint 通过没有结论字样，守卫会误伤 |
| 评测纪律 | 合同冻结数据、金标准和代码的哈希；holdout 由独立代理编写和标注；证据按字节存储；有请求体的黄金哈希 | `eval` 遇到哈希不符、合同未覆盖的引擎、重复运行时都会拒绝（有测试） | contract/、tests/ | — |

## 二、只有代码（有单元测试或静态检查，没在目标环境运行过）

| 能力 | 做了什么 | 如何验证 | 证据 | 限制 |
|---|---|---|---|---|
| Docker + vLLM 单机部署 | compose：镜像按 digest 固定、只监听 loopback、API key 来自被忽略的 .env、运行时离线、有资源上限、健康检查、日志轮转、`--generation-config vllm`。另有权重下载脚本（固定 revision，记录 sha256）和中文操作手册 | 静态检查和 `bash -n` | deploy/linux-vllm/、tests/test_linux_vllm.py | **从未运行**；RTX 50 系列能否运行文档未说明 |
| 8 项验收脚本 | 启动和真实请求、鉴权与各端点、生效配置、显存、并发 1/2/4、短/长/超限输入、停止与崩溃恢复、配置变更与回滚 | 用替身命令测了拒绝路径：未确认、key 格式不对、内存不足、GPU 被占用时都会停下，key 不会写进证据 | acceptance.sh | 正常路径没有跑过 |
| 后端切换（配置文件） | 接口、模型、权重标识、鉴权、超时、上下文、输出预算和采样都写在一份配置文件里；业务流程只有一套；没有回退 | Ollama 配置生成的 50 个请求体与 eval-v2 逐字节一致（黄金哈希）；vLLM 的身份和上下文读取用模拟 HTTP 测过 | regression_triage/backend.py、deploy/backends/ | vLLM 一侧没有连过真实服务 |
| 迁移端到端脚本与前后对比 | migrate.sh：验收 → 冻结合同 → dev → 检查流程是否正常 → holdout → 对比；compare_migration.py 生成对比报告 | `bash -n`、静态检查；对比脚本只用规则引擎的结果试跑过 | deploy/linux-vllm/migrate.sh、scripts/compare_migration.py | 从未运行 |
| 早期写的网关方案和运维套件 | compose.vllm.yaml 加 nginx 网关；wip 分支上的演练、watchdog、systemd、linux_acceptance.sh | 没有运行，也没审查完 | deploy/compose.vllm.yaml、分支 wip/ops-drills-linux | 复用前必须先审查 |
| Docker 执行器（Coding Agent） | 无网络、只读、非 root、有资源限额 | 没有验证（本机没有 Docker） | qwen_agent/ | 目前用的是 restricted 模式，它不是操作系统级的沙箱 |

## 三、未实现

- 指标采集和告警：Ollama 没有 `/metrics`；vLLM 的 `/metrics` 只在验收脚本里读一次，没有 Prometheus 采集（wip 分支里有一份配置，没跑过）。
- 长时间稳定性测试和更高并发的压测。
- 多用户访问：`/health` 和 `/metrics` 的访问控制只停留在设计上，靠 loopback 加网关。
- CI 流水线。

## 四、环境受阻

| 项目 | 原因 | 最小条件 |
|---|---|---|
| ~~迁移前的 Qwen 分诊基线~~ | 2026-10-25 接上交流电源后已完成，见“已实测” | — |
| Linux 上实际部署 Docker + vLLM，以及验证和迁移对比（第 3–5 步） | 本机没有 WSL 和 Docker；本轮不安装 WSL，不租云 GPU；没有 Linux GPU 机器 | 三选一：(1) 同意在本机安装 WSL2（8 GB / 4 GB swap，测试期间 Ollama 保持空闲；**结果只能标为 WSL2，不算独立服务器**）；(2) 一台 Linux GPU 机器的 SSH；(3) 批准云 GPU 的预算 |
| 两台服务器 | 没有访问权限 | 硬件到位后按 CEO_ONE_PAGER.md 的清单做盘点 |
