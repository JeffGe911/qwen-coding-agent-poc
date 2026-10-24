# 上下文溢出与输出截断：配置验证报告

由 `python scripts/build_context_report.py` 从原始证据生成：本目录（各配置 summary.json、运行目录、server-logs/、logscan/、审批记录），以及 evidence/chip-yield-agent/（原盲测）和 evidence/serving/logs/（原服务日志）。

- 模型：qwen2.5-coder:7b，量化 Q4_K_M，digest dae161e27b0e90dd…（各发布清单相同）
- 评测合同：本轮所有运行的 prompt_sha256 与策略相同（prompt_sha256 afa3f06258ad6404…，策略修订 2），同一任务的冻结文件摘要相同。prompt_sha256 只覆盖系统提示词和输出 schema；用户消息里包含运行目录的绝对路径和 pytest 输出，所以各次 chip 提示词的 token 数不同，配置之间的对比不是逐字相同的输入。
- 发布：ACTIVE = r1-7b-ctx4096；历史事件 [('snapshot', 'r1-7b-ctx4096'), ('adopt', 'r1-7b-ctx4096'), ('snapshot', 'r2-7b-ctx8192-np1'), ('snapshot', 'r2b-7b-ctx8192-np1-out4096')]（没有 activate 事件，即没有切换过）。

## 0. 本轮开始时的服务状态与恢复

- 11437 上运行的是隐藏 CUDA 的探索实例：pid 10128，启动于 20261023T210900Z，额外环境 {'CUDA_VISIBLE_DEVICES': '-1'}；服务日志选中的后端 [('Vulkan', 'NVIDIA GeForce RTX 5070 Ti Laptop GPU')]；`/api/ps` = {"models": []}（未加载模型）；nvidia-smi 已用 ['0'] MiB。没有在它上面跑过推理。
- 处理：用 stop_ollama.ps1 停止，按 r1 设置重新启动（见 01-restore-gpu/）。第一次启动的调用方因句柄继承挂起、被强制结束，修复启动脚本后再次启动，正常返回。
- 旧的 11435 实例：00-state-before-restore/processes.txt（查询 11434–11437 端口，与同目录 nvidia-smi.txt 同时采集）中只有 11437 在监听；2026-10-24T04:38:20Z 的只读检查结果为“nothing listening on 11435；pid 28256 not running”。退出原因未查明。

- 注意：§4 中“r1 门禁”是在隐藏 CUDA 实验之前（2026-10-23T21:08:15.048+00:00，原实例 pid 60424，CUDA）跑的。

## 1. 服务可用

| 配置 | 请求的设置 | 实际生效（llama-server 日志 / `/api/ps`） | 后端 | GPU 驻留 | 固定答案 | 健康检查时显存 MiB | 运行期间峰值显存 MiB | 启动告警 | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| r1-7b-ctx4096 | 上下文 4096 × 并行 2，max_tokens 1600 | -c 8192 -np 2，n_ctx_seq 4096，n_seq_max 2，context_length 4096，层 29/29 | CUDA | 100% | 2/2 正确 | 5082（未重启，模型已驻留） | 5102 | 3 行 GPU 发现告警 | 正常 |
| r2-7b-ctx8192-np1 | 上下文 8192 × 并行 1，max_tokens 1600 | -c 8192 -np 1，n_ctx_seq 8192，n_seq_max 1，context_length 8192，层 29/29 | CUDA | 100% | 2/2 正确 | 5090 | 5110 | 无 | 正常 |
| r2b-7b-ctx8192-np1-out4096 | 上下文 8192 × 并行 1，max_tokens 4096 | -c 8192 -np 1，n_ctx_seq 8192，n_seq_max 1，context_length 8192，层 29/29 | CUDA | 100% | 2/2 正确 | 5110（未重启，模型已驻留） | 5110 | 无 | 正常 |
| r1-restore | 上下文 4096 × 并行 2，max_tokens 1600 | -c 8192 -np 2，n_ctx_seq 4096，n_seq_max 2，context_length 4096，层 29/29 | CUDA | 100% | 2/2 正确 | 5082 | — | 无 | 正常 |

r1-7b-ctx4096 的启动告警（第 11 行）：`time=2026-10-23T14:28:07.664-07:00 level=WARN source=runner.go:584 msg="llama-server GPU discovery watchdog timed out" OLLAMA_LIBRARY_PATH="[C:\\Users\\Jeff1\\Documents\\Codex\\2026-10-23\\qwen-coding`；之后模型仍以 CUDA 加载 29/29 层。

CPU 卸载：无（按各配置日志的 offloaded 层数、cpu_offload 计数和 `/api/ps` 驻留比例）。r1 与 r2 的 KV 总量相同（4096 × 2 = 8192 × 1 = 8192 token），显存基本不变。r2 只有 1 个并行槽位，同时到达的第二个请求要排队；本轮没有做并发测试，表 2 中单请求耗时的差异不能只归因于上下文。

## 2. 生成可用（每个提案单独判断）

| 配置 | 任务 | 提案 | 提示词 + 输出 = 合计 / 上下文 | 输出预算 | finish_reason | 服务日志 context shift / truncated | 生成耗时 s | 生成速度 tok/s | 判断 |
|---|---|---|---|---|---|---|---|---|---|
| r1-7b-ctx4096 | report_pass_rate | 1 | 1860 + 340 = 2200 / 4096 | 1600（默认，未写入运行配置） | stop | 0 / 否 | 4.173 | 92.32 | 上下文未溢出；输出正常结束（stop）；JSON 合法；Python 可解析；策略通过 |
| r1-7b-ctx4096 | chip_final_yield | 1 | 3395 + 1600 = 4995 / 4096 | 1600（默认，未写入运行配置） | length | 1 / 是 | 18.422 | 91.15 | 上下文溢出；输出被截断（达到 max_tokens）；JSON 不完整 |
| r2-7b-ctx8192-np1 | report_pass_rate | 1 | 1872 + 302 = 2174 / 8192 | 1600（默认，未写入运行配置） | stop | 0 / 否 | 3.585 | 97.34 | 上下文未溢出；输出正常结束（stop）；JSON 合法；Python 可解析；策略通过 |
| r2-7b-ctx8192-np1 | chip_final_yield | 1 | 3413 + 1600 = 5013 / 8192 | 1600（默认，未写入运行配置） | length | 0 / 否 | 18.386 | 91.18 | 上下文未溢出；输出被截断（达到 max_tokens）；JSON 不完整 |
| r2b-7b-ctx8192-np1-out4096 | chip_final_yield | 1 | 3476 + 4096 = 7572 / 8192 | 4096 | length | 0 / 否 | 46.879 | 88.17 | 上下文未溢出；输出被截断（达到 max_tokens）；JSON 不完整 |
| r2b-7b-ctx8192-np1-out4096 | chip_final_yield | 2 | 3521 + 4096 = 7617 / 8192 | 4096 | length | 0 / 否 | 46.471 | 88.84 | 上下文未溢出；输出被截断（达到 max_tokens）；JSON 不完整 |
| r2b-7b-ctx8192-np1-out4096 | chip_final_yield | 3 | 3566 + 4096 = 7662 / 8192 | 4096 | length | 0 / 否 | 46.958 | 87.71 | 上下文未溢出；输出被截断（达到 max_tokens）；JSON 不完整 |

r2b 的提案 2、3 是同一运行在 3 次提案预算内用 `python -m qwen_agent retry` 重新请求的结果，反馈里带上一次的截断错误，所以提示词每次多约 45 token。

被截断的输出（JSON 不完整，不作为提案提取、不人工补写；下面对其中 code 字符串的解码和语法检查只用于描述失败）：

- r1-7b-ctx4096 提案 1：code 字符串已闭合，解码后 1792 字符，可解析；之后 explanation 805 词，不同 8 词片段占比 0.252，最常见片段“It did not handle the case when the”不重叠出现 40 次
- r2-7b-ctx8192-np1 提案 1：code 字符串已闭合，解码后 1735 字符，可解析；之后 explanation 822 词，不同 8 词片段占比 0.254，最常见片段“It did not handle the case where the”不重叠出现 37 次
- r2b-7b-ctx8192-np1-out4096 提案 1：code 字符串已闭合，解码后 1511 字符，可解析；之后 explanation 2612 词，不同 8 词片段占比 0.083，最常见片段“It did not handle the case where the”不重叠出现 155 次
- r2b-7b-ctx8192-np1-out4096 提案 2：code 字符串已闭合，解码后 1834 字符，语法错误：closing parenthesis ']' does not match opening parenthesis '('（code 第 45 行）；之后 explanation 2806 词，不同 8 词片段占比 0.053，最常见片段“when trying to access a non-existent key in”不重叠出现 100 次
- r2b-7b-ctx8192-np1-out4096 提案 3：code 字符串已闭合，解码后 1745 字符，可解析；之后 explanation 2470 词，不同 8 词片段占比 0.137，最常见片段“retest retest retest retest retest retest retest retest”不重叠出现 43 次

本轮只有这一个任务、温度 0：在 1600 和 4096 两个预算下都退化成重复，没有证据表明继续加预算能解决。

## 3. 业务正确（人工批准后的 pytest）

| 配置 | 任务 | 最终状态 | 审批人 | pytest | 审批摘要 |
|---|---|---|---|---|---|
| r1-7b-ctx4096 | report_pass_rate | succeeded | Jeff (approved in chat) | 21/21 | e844f45762c2aa52 |
| r1-7b-ctx4096 | chip_final_yield | model_error | — | 未执行（没有可审批的提案） | — |
| r2-7b-ctx8192-np1 | report_pass_rate | succeeded | Jeff (approved in chat) | 21/21 | 8bb2babaa5df77dd |
| r2-7b-ctx8192-np1 | chip_final_yield | model_error | — | 未执行（没有可审批的提案） | — |
| r2b-7b-ctx8192-np1-out4096 | chip_final_yield | model_error | — | 未执行（没有可审批的提案） | — |

批准在对话中给出，展示的差异、摘要和提问原文见 [approval-record.md](approval-record.md)，decide 命令随后代为执行（[approval-console.txt](approval-console.txt)）。report_pass_rate 的 21 个测试中有 12 个 holdout（任务说明；holdout 失败详情从不发给模型）。

## 4. 历史失败的重新解读

| 原盲测提案 | 提示词 + 输出 | finish_reason | context shift 前生成 | 丢弃 | shift 后生成 |
|---|---|---|---|---|---|
| 1（failed） | 3584 + 762 = 4346 | stop | 511 | 2045 | 250 |
| 2（policy_blocked） | 3831 + 624 = 4455 | stop | 264 | 2045 | 359 |
| 3（policy_blocked） | 3866 + 672 = 4538 | stop | 229 | 2045 | 442 |

- 提案 1：输出 2918 字符，code 字段结束于第 2106 字符；按字符比例估计 shift 发生在第 1957 字符附近。
- 提案 2：输出 2338 字符，code 字段结束于第 2029 字符；按字符比例估计 shift 发生在第 989 字符附近；语法错误（code 第 53 行：assignment to yield expression not possible）位于第 1633 字符，在估计的 shift 位置之后。
- 提案 3：输出 2414 字符，code 字段结束于第 2052 字符；按字符比例估计 shift 发生在第 823 字符附近；语法错误（code 第 34 行：unterminated f-string literal (detected at line 34)）位于第 1013 字符，在估计的 shift 位置之后。
- 三份提案都没有达到输出预算，都在生成中途触发 context shift（丢弃提示词第 5 个 token 起的 2045 个 token）。按上面的估计，提案 1 的 code 字段大部分在 shift 之前生成，所以它 8/22 的结果主要不能用 context shift 解释。结论：原证据被 context shift 部分污染，不足以单独支持“7B 能力不够”，也不能反过来说失败只是配置问题（估计基于字符比例，本机没有分词器）。
- r1 门禁（2026-10-23T21:08:15.048+00:00）：report_pass_rate 生成检查通过（上下文、JSON、策略；门禁不执行代码，没有跑 pytest）；chip_final_yield 提示词 2891 + 输出 1600，context_ok=False，json_ok=False（服务日志 evidence/serving/logs/ollama-11437-20261023T192809Z.err.log 中有对应的 context shift）。

## 5. 恢复原配置

候选验证结束后按 r1 的设置重启：`python -m qwen_ops release verify --name r1-7b-ctx4096` 的差异为 []；实际生效 {"llama_server_ctx_total": "8192", "llama_server_parallel": "2", "n_ctx_seq": "4096", "n_seq_max": "2", "offloaded_layers": "29/29"}。ACTIVE = r1-7b-ctx4096。

