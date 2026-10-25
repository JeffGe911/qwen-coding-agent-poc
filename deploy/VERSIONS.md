# 版本清单（迁移前 / 迁移后）

每一行都标出版本是**实测得到的**（从运行中的系统读出），还是**目标值**（写在部署文件里，尚未在目标环境运行过）。

## 迁移前：Windows 笔记本 + Ollama（实测，2026-10-25）

| 组件 | 版本 / 标识 | 来源 |
|---|---|---|
| 操作系统 | Windows 11 Home 中文版，build 26200 | evidence/linux-serving/environment-check.txt |
| GPU / 驱动 | RTX 5070 Ti Laptop，计算能力 12.0，12227 MiB；驱动 591.91 | `nvidia-smi` |
| Ollama | 0.40.9 便携版，`ollama.exe` sha256 `0957bdaa7b52e163cdc7feb1275653f27c6b32e8ba309e957bdbb83493e97a4b` | deploy/releases/r2-7b-ctx8192-np1.json，`release verify` |
| 发布 | `r2-7b-ctx8192-np1`（ACTIVE）：上下文 8192，并行 1，队列 512 | deploy/releases/ |
| 模型 | `qwen2.5-coder:7b`，GGUF Q4_K_M，7.6B，digest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364` | `/api/tags`，后端配置 deploy/backends/ollama-r2.json |
| Python | 3.13.4；依赖见 requirements-lock.txt（只用于测试，业务代码只依赖标准库） | `python -V` |
| 仿真工具 | OSS CAD Suite 2026-10-24：Icarus Verilog 14.0 (devel) s20260301-664-g9cfecc9c9-dirty；Verilator 5.053 devel rev v5.052-567-g0041d207c | 每次运行的 run.json |

## 迁移后：Linux + Docker + vLLM（目标值，**未运行**）

| 组件 | 版本 / 标识 | 来源 |
|---|---|---|
| 镜像 | `vllm/vllm-openai:v0.32.0@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34`（amd64 约 9.2 GB） | deploy/linux-vllm/compose.yaml，Docker Hub |
| 迁移对比用的模型 | Qwen/Qwen2.5-Coder-7B-Instruct-AWQ @ `8e8ed243bbe6f9a5aff549a0924562fc719b2b8a`，safetensors，AWQ 4-bit GEMM，group_size 128，5.6 GB | deploy/backends/vllm-qwen7b-awq.json |
| 冒烟用的小模型 | Qwen/Qwen2.5-Coder-1.5B-Instruct @ `2e1fd397ee46e1388853d2af2c993145b0f1098a`，BF16，3.1 GB | deploy/linux-vllm/env.example |
| 服务参数 | `--max-model-len 8192`（迁移对比）、`--max-num-seqs 4`、`--gpu-memory-utilization 0.70`、`--enforce-eager`、`--generation-config vllm` | compose.yaml、env.7b-awq.example |
| Docker Engine、NVIDIA Container Toolkit、驱动、内核 | **安装时记录**，目前未知 | 首次运行 acceptance.sh 的证据 |

## 两边不同的地方（比较结果时必须写明）

- **权重不同**：基础模型相同，但量化方法和文件格式都不同（GGUF Q4_K_M 对比 AWQ 4-bit safetensors），所以输出不会逐字相同。
- **结构化输出的实现不同**：Ollama 用 llama.cpp 的 grammar，vLLM 用 xgrammar 或 guidance（`auto`）。
- **采样**：两边实际都是贪心解码，且不加重复惩罚。Ollama 只在请求里发 `temperature 0`，其他取服务端默认值（从服务日志核对过）。vLLM 在请求里显式发 temperature、top_p、repetition_penalty，并以 `--generation-config vllm` 启动，否则模型自带的 repetition_penalty 1.1 会悄悄生效。
- **分词器**：都是 Qwen2.5 的词表，但 GGUF 内嵌的分词器和 Hugging Face 的分词器可能有细微差别，所以 token 数只能近似比较。
