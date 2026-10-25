# vLLM 单机部署操作手册（Linux / WSL2）

**状态（2026-10-24）**：部署文件、权重下载脚本和验收脚本已写好，通过了静态检查和 `bash -n`，但**还没有在任何 Linux GPU 环境上运行过**。本机没有 WSL/Docker，也没有可用的服务器。下面的步骤在第一次真实运行后才算验证。

## 1. 范围与边界

- 一台机器、一张 NVIDIA GPU、一个 vLLM 容器，按 OpenAI 兼容接口在 `127.0.0.1:18000` 提供服务。
- 与本项目在 Windows 上运行的 Ollama（`127.0.0.1:11437`，ACTIVE 发布 r2）**分时使用 GPU，不同时运行**。临时停止 Ollama 之前必须先征得负责人同意。
- 运行时只访问这一个本地服务。没有云 API，也没有回退。

## 2. 环境要求（来自官方文档，2026-10-24 核对）

| 项目 | 要求 | 来源 |
|---|---|---|
| 操作系统 | 仅 Linux；Windows 需要 WSL | docs.vllm.ai `getting_started/installation/gpu` |
| GPU | 计算能力 ≥ 7.5。B200/GB200 这类 Blackwell 卡至少需要 CUDA 12.8；RTX 50 系列（计算能力 12.0）**文档未提及，必须实测** | 同上 |
| 镜像 | `vllm/vllm-openai:v0.32.0@sha256:befccf0e…`（2026-10-18 发布，amd64 约 9.2 GB） | Docker Hub、GitHub releases |
| 运行参数 | `--gpus` / NVIDIA runtime，`--ipc=host` 或 `--shm-size` | `deployment/docker` |
| 权重格式 | 使用 safetensors。Ollama 的 GGUF 不能直接用：GGUF 在 vLLM 中“highly experimental”，已移到外部插件 | `features/quantization/gguf` |
| API key | `--api-key`/`VLLM_API_KEY` 只保护 `/v1`、`/v2`、`/inference`。`/health`、`/metrics` 等不在保护范围内 | `serving/online_serving/openai_compatible_server` |

文档没写的事项一律实测，不靠推断：超长输入的处理方式、`--gpu-memory-utilization` 的计算基准、RTX 50 系列能否运行。

## 3. 权重（下载阶段需要联网，运行阶段离线）

| 用途 | 仓库 | revision | 格式 | 大小 |
|---|---|---|---|---|
| 第一步小模型 | Qwen/Qwen2.5-Coder-1.5B-Instruct | `2e1fd397ee46e1388853d2af2c993145b0f1098a` | BF16 safetensors | 3.1 GB |
| 第二步 | Qwen/Qwen2.5-Coder-7B-Instruct-AWQ | `8e8ed243bbe6f9a5aff549a0924562fc719b2b8a` | AWQ 4-bit（GEMM，group_size 128） | 5.6 GB |

两者都和 Ollama 上的 `qwen2.5-coder:7b`（GGUF Q4_K_M）格式不同。比较结果时必须写明模型和格式差异，不能直接当作同一个模型。

```bash
bash deploy/linux-vllm/download_model.sh Qwen/Qwen2.5-Coder-1.5B-Instruct 2e1fd397ee46e1388853d2af2c993145b0f1098a /srv/models/Qwen2.5-Coder-1.5B-Instruct evidence/linux-serving/model-1.5b
```

脚本只接受 40 位 commit sha。它会把文件列表、大小和 safetensors 的 sha256 写进证据目录。

## 4. 网络要求

- **准备阶段**（联网）：apt 安装 Docker Engine 与 NVIDIA Container Toolkit，`docker pull` 固定 digest 的镜像，`hf download` 下载固定 revision 的权重。
- **运行阶段**（不联网）：容器设置了 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`VLLM_NO_USAGE_STATS=1`，并且 `pull_policy: never`。端口只发布到 127.0.0.1。

## 5. WSL2 资源上限（只在征得同意后执行）

1. 先查看 `%UserProfile%\.wslconfig`。2026-10-24 检查时这个文件不存在；如果已有，就合并配置，不要覆盖。
2. 按 `deploy/linux-vllm/wslconfig.example` 设置 `memory=8GB`、`swap=4GB`，然后执行 `wsl --shutdown`。
3. 在 WSL 中执行 `free -g`、`nproc` 验证上限已生效，并把输出存入证据。
4. 等负责人关闭其他应用、Windows 端空闲内存足够后，再启动小模型。资源不够就报告，**不要**结束其他程序，也不要调大上限反复重试。

## 6. 启动、停止、检查

```bash
cp deploy/linux-vllm/env.example deploy/linux-vllm/.env && chmod 600 deploy/linux-vllm/.env   # 填 key 和 MODEL_DIR；.env 已被 git 忽略
docker compose --env-file deploy/linux-vllm/.env -f deploy/linux-vllm/compose.yaml config --quiet   # 不要去掉 --quiet：会打印出 key
docker compose --env-file deploy/linux-vllm/.env -f deploy/linux-vllm/compose.yaml up -d
curl -s http://127.0.0.1:18000/health; curl -s http://127.0.0.1:18000/metrics | head
python3 -m qwen_ops health --service compose --base-url http://127.0.0.1:18000/v1 --model qwen-local   # 需先 export LOCAL_MODEL_API_KEY
docker compose --env-file deploy/linux-vllm/.env -f deploy/linux-vllm/compose.yaml stop
```

“进程在运行”、“API 能访问”和“模型能正确回答”是三项独立的检查：`qwen_ops health` 分别报告进程/端口、`/v1/models` 和固定答案。

资源限制写在 compose 里：容器内存 6 GB（低于 WSL 的 8 GB 上限）、不额外使用 swap、最多 512 个进程、共享内存 1 GB、`no-new-privileges`、日志按 10 MB × 3 轮转。

## 7. 验收（8 项，一条命令）

```bash
sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/acceptance.sh
```

脚本先做资源预检：WSL 可用内存 ≥ 5000 MB，且 GPU 已用显存 ≤ 1500 MiB（也就是 Ollama 没有加载模型）。任一不满足就停下报告。之后依次检查：

1. 启动、加载与真实推理请求；
2. `/health`、`/metrics`、`/version`、`/v1/models` 在有 key 和无 key 时的返回码；
3. 模型名和 `max_model_len` 与 `.env` 一致；
4. 加载前后的显存，以及日志中的 KV cache 信息；
5. 并发 1/2/4 下的 TTFT、耗时和失败数，以及 `vllm:num_requests_waiting`；
6. 短输入、长输入、超过 `max_model_len` 的输入、超出预算的 `max_tokens`，以及 `finish_reason=length`；
7. stop → 检测到 down → start 恢复；对容器主进程发 SIGKILL 模拟崩溃，验证 restart 策略会拉起容器；
8. 把 `MAX_MODEL_LEN` 减半、`MAX_NUM_SEQS` 设为 2，验证变更生效，再回滚到已知可用的 `.env` 并验证恢复。

证据写到 `evidence/linux-serving/<host>-<utc>/`：包括 `commands.log`、每一步的原始输出、`endpoints.tsv` 和 `summary.tsv`。key 会从所有输出中过滤掉，脚本结束时还会扫描整个目录确认没有残留。

## 8. 排障

| 现象 | 先看 | 处理 |
|---|---|---|
| 容器一直不健康 | `docker compose logs vllm` | 计算能力或 CUDA 不兼容（RTX 50 系列没有写进文档）时，换与驱动匹配的镜像版本；内核不支持就记为“阻塞”，不要退回 CPU 模式 |
| 启动时 CUDA OOM / “No available memory for the cache blocks” | `nvidia-smi` 中的其他占用 | 确认 Ollama 没有加载模型；先降 `MAX_MODEL_LEN`、`MAX_NUM_SEQS`，再降 `GPU_MEMORY_UTILIZATION`；仍放不下就换更小的模型 |
| 请求返回 400，提示上下文过长 | 请求的 prompt 加 `max_tokens` | 这是 vLLM 显式拒绝，和 Ollama 静默截断不同；缩短输入或调大 `MAX_MODEL_LEN` |
| `/metrics` 能被访问 | 端口绑定 | 只绑定在 127.0.0.1；对外提供服务时，要在前面加带 token 的 allowlist 网关（`deploy/nginx.conf.template`） |
| 容器被 OOM kill | `docker inspect -f '{{.State.OOMKilled}}'` | 降低并发或上下文，或提高 `MEM_LIMIT`（不能超过 WSL 上限） |
| 生成速度只有平时的几分之一，GPU 利用率却接近 100% | `nvidia-smi --query-gpu=pstate,clocks.mem,enforced.power.limit,clocks_event_reasons.sw_power_cap --format=csv`，以及服务日志里的 `eval time` | **实际遇到过（2026-10-25，Windows 基线）**：笔记本用电池供电、电源方案为“静音”，GPU 在 P5、功耗上限 33 W、显存时钟 810 MHz，生成从 50–90 tok/s 降到 7.4 tok/s，已接近请求超时。接上电源、换电源方案后再测。降频状态下测到的耗时不能当基线 |
| 迁移后输出质量变了，或出现重复 | 启动参数里是否有 `--generation-config vllm`，请求里是否带了 `repetition_penalty` | vLLM 默认会套用模型自带的 generation_config.json（Qwen2.5-Coder-7B 的 repetition_penalty 是 1.1）。两边对齐见 deploy/VERSIONS.md |
| 评测拒绝运行：`backend ... does not match the contract` | `curl -H "Authorization: Bearer $KEY" 127.0.0.1:18000/v1/models` | 服务名或 `max_model_len` 与后端配置不一致，常见原因是 `.env` 还停留在 1.5B 的设置（4096）。不要改合同，应修正 `.env` |
| 评测拒绝运行：`... changed since the contract was frozen` | `git status` | 被哈希的代码有改动。要么恢复改动，要么冻结一个新的合同版本 |
| 请求返回 401 | `.env` 中的 `VLLM_API_KEY` 和环境变量 `LOCAL_MODEL_API_KEY` | migrate.sh 会从 `.env` 导出 key；手动运行时要自己 export，不要写进命令历史 |

## 9. 业务迁移（Ollama → vLLM）与对比

业务入口和输出契约都不变：同一套 prompt、schema、引用校验和评分，只换后端配置文件（`deploy/backends/*.json`）。配置文件记录接口地址、模型名、权重标识、鉴权、超时、上下文、输出预算、请求里发送的采样参数，以及服务端实际生效的参数。没有回退：服务不响应时，记为 request_failed。

```bash
# 迁移前（Windows，已具备条件时）：冻结基线合同，按 dev → holdout 运行，带资源监控，结束后卸载模型
python scripts/freeze_triage_contract.py eval-v3 --engines rules,qwen --backend deploy/backends/ollama-r2.json --note "..."
python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v3.json --split dev
python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v3.json --split holdout --unload

# 迁移后（Linux）：cp deploy/linux-vllm/env.7b-awq.example deploy/linux-vllm/.env，填好 key，再执行
sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/migrate.sh dev       # 验收 8 项 → 冻结 eval-v4 → dev，停下等复核
sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/migrate.sh holdout   # holdout 跑一次 → 对比报告
# 端到端一条命令（复现用）：验收 → dev → 检查流程是否正常（不看准确率）→ holdout → 对比
sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/migrate.sh all
```

对比报告由 `scripts/compare_migration.py` 生成，写到 `evidence/migration/COMPARISON-eval-v3-vs-eval-v4.md`。内容依次是：
1. 两边的差异：权重、量化、结构化输出实现、采样参数；
2. 请求成功率和结构化输出合规率；
3. 类别正确、误放行、漏报、误报、unknown 和引用相关率；
4. 耗时、token 数和资源占用；
5. 逐个测试的类别是否一致。

两边输出不要求逐字相同，接口调用成功也不等于业务迁移成功。

恢复命令：
- 停止：`docker compose --env-file deploy/linux-vllm/.env -f deploy/linux-vllm/compose.yaml stop`
- 启动：把命令里的 `stop` 换成 `up -d`
- 重启：换成 `restart vllm`
- 回滚配置：改配置前先执行 `cp deploy/linux-vllm/.env deploy/linux-vllm/.env.known-good`，这个文件含 key，已被 git 忽略。回滚时把它复制回 `.env`，再执行 `up -d --force-recreate vllm`。acceptance.sh 第 8 步用临时副本做同样的事，脚本结束时临时副本会被删除。
- Ollama 一侧：`scripts\stop_ollama.ps1 -Port 11437`，然后 `scripts\start_ollama.ps1 -Port 11437 -Context 8192 -NumParallel 1`，最后用 `python -m qwen_ops release verify --name r2-7b-ctx8192-np1` 核对。

## 10. 两台服务器时

这份 compose 只针对单机。到两台服务器时，按 `deploy/compose.vllm.yaml`（网关 + 内部网络）部署推理机。另一台的用途（执行沙箱、评测或第二个推理副本）在盘点之后再决定。`wip/ops-drills-linux` 分支里有一套更完整但从未运行、也没审查完的套件，复用之前要先审查。
