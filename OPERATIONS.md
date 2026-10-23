# GPU Serving 与私有化运维

本项目分清两类证据：**本机已实跑的是 Windows/Ollama/GPU/API/Agent/pytest/本地网关**；Linux Docker、vLLM、Prometheus 和多 GPU 是可部署配置与操作说明，**本机没有 Docker/WSL，因此未实测这些路径**。这证明最小工作流可运行，不代表已经上线生产服务。

## 1. GPU、CUDA 与显存

先运行：

```bash
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu --format=csv
nvcc --version
```

`nvidia-smi` 显示驱动和 GPU 是否可用；其 `CUDA Version` 是驱动支持能力，不等于已安装 CUDA Toolkit。`nvcc` 检查编译工具链，预编译 Ollama/vLLM 容器通常使用自带运行库。Linux Docker GPU 还依赖 NVIDIA Container Toolkit，驱动与容器 CUDA/PyTorch 构建必须兼容；不要看到 CUDA 字样就断言环境无问题。

本机记录：RTX 5070 Ti Laptop、12,227MiB、驱动 591.91，`nvidia-smi` 报告 CUDA 13.1；PATH 中没有 nvcc。Ollama 服务检测到 CUDA GPU，`ollama ps` 显示 100% GPU。见 [原始输出](evidence/nvidia-smi.txt)、[工具链检查](evidence/cuda-toolkit.txt)、[驻留模型数据](evidence/serving.json)。桌面显示等进程也占显存，整卡 `memory.used` 不能直接当模型大小。

显存预算至少包括：

```text
显存 ≈ 模型权重 + KV Cache + 激活/执行图/工作缓冲 + 安全余量
权重粗估 ≈ 参数量 × 每参数字节
KV 粗估 ≈ 2(K,V) × 层数 × KV heads × head_dim × token数 × 并发序列数 × 每元素字节
```

FP16/BF16 权重约 2 字节/参数，4-bit 原始权重约 0.5 字节/参数，但量化元数据和未量化张量会增加实际大小。GGUF `Q4_K_M` 与 vLLM 的 AWQ/GPTQ/其他量化不等价，支持情况取决于模型格式、GPU 架构、内核和版本；不能直接把 Ollama 模型文件挂到此 vLLM safetensors 配置里。

本次模型为 1.5437B 参数、GGUF Q4_K_M。其模型配置为 28 层、2 个 KV heads、head_dim=128。若 KV 使用 FP16，4096 tokens、单序列的理论 KV 是 **112MiB**；8192 tokens 是 224MiB。这是估算，不等于进程总显存。

实测同一模型上下文 4096 → 8192 → 4096，`/api/ps.size_vram` 为：

| 上下文 | 驻留字节数 | 说明 |
|---:|---:|---|
| 4096 | 1,169,382,440 | 基线 |
| 8192 | 1,367,059,988 | 比基线高约 188.5MiB |
| 4096 | 1,169,382,440 | 已恢复 |

驻留增量还可能包含执行图和缓冲区变化，不能把 188.5MiB 全归因于 KV。原始数据见 [上下文实验](evidence/kv-context.json)。增大上下文或并发会增加容量压力；权重量化也不会自动量化 KV Cache。

## 2. 并发与 Ollama/vLLM 选择

本次 Ollama 服务使用 `OLLAMA_NUM_PARALLEL=1` 的默认设置。客户端同时发两个请求，不表示服务正在并行计算两条序列；可能排队。因此以下只是短请求 smoke benchmark：

| 客户端并发 | 请求数 | 成功 | 完整响应 P50 | 完整响应 P95 | 聚合输出 tokens/s |
|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 4 | 0.146s | 0.158s | 135.4 |
| 2 | 4 | 4 | 0.240s | 0.267s | 157.5 |

短提示、短输出、相似前缀且缓存命中，样本太少，不能得出 vLLM 更快/更慢或服务能支持某个用户规模的结论。需要继续用代表性的长代码提示、不同输出长度、并发 1/2/4/8 做测试，测 TTFT、TPOT、吞吐、P95/P99、排队和错误率。当前客户端是非流式，因此没有 TTFT 指标。[原始请求级数据](evidence/serving.json)。

| 维度 | Ollama | vLLM |
|---|---|---|
| 本 PoC 路径 | 已实跑 | Linux 配置，待部署验证 |
| 适用起点 | 开发机、小规模本地推理、量化模型快速验证 | Linux GPU 服务、并发调度与指标、更多部署调优 |
| 重点关注 | 模型 GPU 驻留、上下文、并行槽位与队列 | batching、KV 容量、max-model-len、max-num-seqs、显存预算 |
| Agent 接口 | `/v1/chat/completions` | 同一客户端与 JSON schema 合同 |
| 鉴权 | 本项目本地网关 / 内部反向代理 | API key 加反向代理；不要只依赖原生 key |

Ollama 的上下文和 GPU 驻留方法见 [官方 FAQ](https://docs.ollama.com/faq)，结构化输出见 [官方说明](https://ollama.com/blog/structured-outputs)。

## 3. Linux + Docker + vLLM

交付 [Compose](deploy/compose.vllm.yaml)、[Nginx 端点白名单](deploy/nginx.conf.template)、[环境变量示例](deploy/env.example) 和 [Prometheus 抓取示例](deploy/prometheus.example.yaml)。需要 Docker Compose 2.30+ 以支持 `gpus` 字段。默认使用较小的 Qwen2.5-Coder-1.5B-Instruct safetensors，不要求大模型。vLLM 标签 0.32.0 来自本次查询的官方 release；部署前仍需在目标 GPU 验证镜像/驱动兼容性并固定 image digest。

在**可联网的准备阶段**：

```bash
# Linux GPU 主机；先安装 Docker 与 NVIDIA Container Toolkit。
nvidia-smi
docker pull vllm/vllm-openai:v0.32.0
docker pull nginx:1.28.0-alpine
docker image inspect vllm/vllm-openai:v0.32.0 --format '{{json .RepoDigests}}'
docker build -t qwen-agent-sandbox:0.1 .
# 用审核过的 Hugging Face commit 下载完整 snapshot，包括 tokenizer/config/safetensors：
# hf download Qwen/Qwen2.5-Coder-1.5B-Instruct --revision REVIEWED_COMMIT --local-dir /srv/models/Qwen2.5-Coder-1.5B-Instruct
cp deploy/env.example deploy/.env
chmod 600 deploy/.env
python -c 'import secrets; print(secrets.token_hex(32))'
# 将生成的随机 hex key 和绝对 MODEL_DIR 写入 deploy/.env；不要提交该文件。
```

核验模型和镜像校验值，将镜像/模型同步到离线环境。**准备阶段不要传入内部代码**。运行期设置 egress 默认拒绝后：

```bash
docker compose --env-file deploy/.env -f deploy/compose.vllm.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.vllm.yaml up -d
docker compose --env-file deploy/.env -f deploy/compose.vllm.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.vllm.yaml logs --tail=100 inference
```

`pull_policy: never` 不在运行期拉镜像；只读挂载本地模型；`HF_HUB_OFFLINE`、`TRANSFORMERS_OFFLINE`、关闭 usage stats；推理与代理位于 `internal: true` 网络。原始推理端口不发布，网关只发布 `127.0.0.1:11436`。只有操作员/内部 SSH 隧道可访问。跨主机服务应在组织内的 TLS/mTLS 入口后部署，配置防火墙、服务身份、密钥轮换和内部证书；当前文件没有假装完成这一步。

在当前 shell 安全设置同一个 `LOCAL_MODEL_API_KEY` 后：

```bash
curl -i http://127.0.0.1:11436/v1/models
# 预期 401
curl -f -H "Authorization: Bearer $LOCAL_MODEL_API_KEY" http://127.0.0.1:11436/health
curl -f -H "Authorization: Bearer $LOCAL_MODEL_API_KEY" http://127.0.0.1:11436/metrics
python -m qwen_agent doctor --base-url http://127.0.0.1:11436/v1 --model qwen-local
python -m qwen_agent demo --task all --reviewer YOUR_NAME --base-url http://127.0.0.1:11436/v1 --model qwen-local
```

健康检查不等于模型回答正确；再执行一次最小推理和任务回归。vLLM 原生 API key 并不覆盖全部端点，不能把整个原生端口直接发布到不可信网络；本配置只放行四个端点，对 health/metrics 同样要求网关 token。参见 [官方安全说明](https://docs.vllm.ai/en/latest/usage/security/)。不要使用 `docker compose config` 的非 quiet 输出到公共日志，它会展开环境变量中的密钥。

## 4. 日志、监控与恢复

| 信号 | 用途 | 操作 |
|---|---|---|
| `/health` | 推理服务是否存活/就绪 | 超时或连续失败时停止接收任务，检查模型加载日志 |
| `/metrics` | 请求、排队、KV、吞吐、延迟 | Prometheus 内部抓取，结合目标版本的实际 metric 名称 |
| `nvidia-smi` | 显存/利用率/驱动异常 | OOM、降速、驱动故障排查；多进程显存总和需区分 |
| Agent `events.jsonl` | 审批、执行、失败原因 | 按 run_id 关联，不自动重放 executing 任务 |
| 容器状态/日志 | 退出、重启、OOM | 容器日志轮转，不记录 prompts 或 Authorization |

vLLM 提供 [原生 Prometheus 指标](https://docs.vllm.ai/en/latest/usage/metrics/)。可观察 TTFT、TPOT、等待/运行请求、KV 使用和 preemption；不同版本名称可能变化，先读取实际 `/metrics`。不要把高维 request_id、原始代码或患者/业务数据放到指标标签。

`restart: unless-stopped` 处理容器退出，**不会因为 healthcheck 变为 unhealthy 自动重启**。无响应/持续 unhealthy 需要监控告警与人工/外部监督器处理。上线前应验证：

1. 进程退出后容器重启、模型重新就绪、smoke 推理恢复。
2. 模型路径错误/权限不足时不接任务，日志给出原因，无云 fallback。
3. OOM 时降低上下文、并发或模型大小；不要循环无限重启，必要时限次回滚上一镜像/模型。
4. API 不可用时 Agent 记录 model_error/infra_error，批准状态不自动重用。
5. 断网后推理仍正常；从服务容器与执行器验证禁止 DNS/出站；检查主机 Docker 转发规则也受网络策略控制。

本机已实际验证：无 token 401、正确 token 200、真实鉴权推理 200、管理/备用端点 404、网关同端口重启后恢复 200、上游不可用时 503。见 [9 项检查](evidence/local-ops.json)。**没有把这些检查称为 Docker/GPU 故障恢复实测。**

## 5. 单卡放不下与多 GPU

先确定 OOM 来自权重还是 KV/并发；依次考虑缩小上下文/并发、合适量化、较小模型。若模型可装入单卡，通常不必增加分布式复杂度。

当一个 dense 模型单卡放不下但一台多 GPU 主机可容纳时，可用 Tensor Parallelism 将张量计算与权重分片，例如：

```bash
vllm serve /srv/models/Qwen2.5-Coder-32B-Instruct \
  --tensor-parallel-size 2 --max-model-len 4096 \
  --gpu-memory-utilization 0.80 --served-model-name qwen-local
```

这条命令只说明双卡启动方式，不承诺任意两张 GPU 的显存足够。32B FP16/BF16 原始权重约 64GB（十进制），还需 KV、缓冲和余量。检查模型 head 数可否按 TP size 分片、每卡实际可用显存、NCCL、NVLink/PCIe 带宽和拓扑 `nvidia-smi topo -m`；通信开销可能使延迟上升。`gpus: all` 只暴露设备，不等于自动启用 TP，Compose 中用 `TP_SIZE` 控制。

Data Parallelism 是多个完整模型副本，主要扩吞吐，不能解决单副本放不下；Pipeline Parallelism 按层分割，适合特定拓扑或跨节点组合；多节点还需统一模型路径、软件版本和受保护的节点通信，Ray/NCCL 管理端口不能公开。参考 [vLLM 官方并行部署说明](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)。本机只有一张 GPU，以上没有伪造多 GPU 测试成绩。

## 演示时的说明顺序

先展示失败基线，再展示模型原始提案和人工审批，最后展示通过/失败/策略拦截三条路径与真实分母。随后打开显存和并发证据，解释为何选小模型与 Ollama；再用 Linux 配置讲清 egress、鉴权、监控、容器重启边界和 TP 扩展。可以据此说明已有 Agent 编排经验如何迁移，以及哪些生产基础设施仍需要在目标环境验证。

## 附：2026-10-23 第二轮单机实测（7B）

`scripts/start_ollama.ps1` 在 127.0.0.1:11437 启动便携 Ollama：上下文 4096、`OLLAMA_NUM_PARALLEL=2`、`OLLAMA_MAX_LOADED_MODELS=1`、`OLLAMA_NO_CLOUD=1`。启动日志确认这些配置生效，计算后端为 Ollama 自带的 cuda_v13 运行库。启动记录在 `evidence/serving/ollama-launch-*.json`。11435 上由更早会话启动的实例未被改动。

| 项目 | 实测 |
|---|---|
| 模型 | qwen2.5-coder:7b，7.6B，GGUF Q4_K_M，文件 4.68GB |
| 驻留 | 两个 4096 槽位共 4.79GiB，100% 在 GPU |
| 8192 上下文 | 驻留增加约 456MiB；理论 FP16 KV 增量 448MiB（28 层 × 4 KV 头 × 128 × 2 × 2 字节 × 4096 × 2 槽） |
| 并发 | 两次测量原样保留，见 `evidence/serving/serving-7b-*.json` 与 `evidence/index.html`；首次双槽并行出现一次约 8 秒的延迟，重测未复现 |

这些是 Windows 笔记本上的冒烟测量，不代表 Linux 服务器容量。
