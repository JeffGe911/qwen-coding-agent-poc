# 官方文档核对（2026-10-24）

查阅当天的官方页面，只记录页面上明确写着的内容；页面没写的标为“未写明”。

| 问题 | 结论 | 来源 |
|---|---|---|
| 操作系统 | “OS: Linux”；“vLLM does not support Windows natively. To run vLLM on Windows, you can use the Windows Subsystem for Linux (WSL)” | https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html |
| GPU 计算能力 | “compute capability 7.5 or higher” | 同上 |
| CUDA | 预编译 CUDA 12.9（另有 12.8、13.0 构建）；“NVIDIA Blackwell GPUs (B200, GB200) require a minimum of CUDA 12.8” | 同上 |
| RTX 50 系列 / 计算能力 12.0（本机 GPU） | **未写明**，必须在目标环境实测 | 同上 |
| Docker 镜像与参数 | `vllm/vllm-openai`；`--runtime nvidia --gpus all`，`--ipc=host` 或 `--shm-size`，端口 8000，`--model` 放在镜像名之后 | https://docs.vllm.ai/en/latest/deployment/docker.html |
| GGUF | “highly experimental and under-optimized”，建议用原模型的 tokenizer，已迁到外部插件 vllm-gguf-plugin。所以不直接复用 Ollama 的 GGUF | https://docs.vllm.ai/en/latest/features/quantization/gguf.html |
| AWQ/GPTQ/FP8 硬件支持表 | supported_hardware 页面在 /latest 和 /stable 下都返回 404，**未核对到**；7B-AWQ 能否在计算能力 12.0 上运行同样要实测 | — |
| `--max-model-len` | “Model context length (prompt and output)” | https://docs.vllm.ai/en/latest/configuration/engine_args.html |
| `--gpu-memory-utilization` | 默认 0.92，取值 0–1，“fraction of GPU memory to be used for the model executor”；是否按整卡总量计算，页面**未写明** | 同上 |
| `--api-key` 保护范围 | “only authenticates requests to endpoints under the /v1, /v2, and /inference path prefixes. Other endpoints ... are not authenticated” | https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/ |
| prompt + max_tokens 超过 `max_model_len` 时怎么处理 | **未写明**；验收脚本第 6 项会实测 | 同上 |

版本与权重（来自 API）：

- vLLM GitHub 最新稳定版 v0.32.0（2026-10-18）。Docker Hub 上 `v0.32.0` 的 digest 为 `sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34`，amd64 约 9.2 GB。
- Qwen/Qwen2.5-Coder-1.5B-Instruct：revision `2e1fd397…`，BF16，3.1 GB。
- Qwen/Qwen2.5-Coder-7B-Instruct-AWQ：revision `8e8ed243…`，AWQ 4-bit GEMM，group_size 128，5.6 GB。
- Qwen/Qwen2.5-Coder-7B-Instruct：BF16，15.2 GB，放不进本机 12 GB 显存。
