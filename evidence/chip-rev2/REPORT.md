# chip_final_yield 评测合同 rev 2：单变量对照

合同 `chip_final_yield/rev2`（qwen_agent/contracts/chip_final_yield/rev2.json，sha256 41b658cc2888a1e6…），在任何一组运行前提交冻结。任务文件、公开测试、holdout、策略与 rev 1 相同；服务为 r2（每请求上下文 8192，1 个槽位）；每组一个运行，最多 3 次提案，规则同 rev 1。表中数字由 `python scripts/build_chip_rev2_report.py` 从原始证据计算。

- 通道等价性：同一份 rev 1 请求，经原生接口 + 对照组参数与经 /v1 重发的输出逐字相同（True）；与一天前的原记录从第 1260 字符起不同（提示词缓存状态不同），温度 0 也不是严格可复现。
- 重复判定（运行前冻结）：repetition = some 8-word phrase occurs >= 5 times, non-overlapping, in the full output text (words = [A-Za-z_'][A-Za-z_'-]*, JSON-escaped newlines read as spaces)，阈值 5 次。

| 组 | 提案 | finish_reason | 提示词 + 输出 | context shift | 重复（最多片段次数） | 格式 | Python | 策略 | Agent 判定 | 公开测试 | holdout | 实际生效 temp / repeat_penalty |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rev 1 基线（对照组，rev 2 通道重跑） | 1 | length | 3314 + 1600 | 0 | 是（41） | ✗ Unterminated string starting at: line 3  | — | — | model_error（未进入审批） | 未执行 | 未执行 | 0.0 / 1.0 |
|  | 2 | length | 3359 + 1600 | 0 | 是（26） | ✗ Unterminated string starting at: line 3  | — | — | model_error（未进入审批） | 未执行 | 未执行 | 0.0 / 1.0 |
|  | 3 | length | 3404 + 1600 | 0 | 是（37） | ✗ Unterminated string starting at: line 3  | — | — | model_error（未进入审批） | 未执行 | 未执行 | 0.0 / 1.0 |
| A 输出格式 | 1 | stop | 3323 + 505 | 0 | 否（2） | ✓（解释 6 句，超过 3 句） | ✓ | ✓ | 批准 → pytest 未通过 | 3/11 | 4/11 | 0.0 / 1.0 |
|  | 2 | stop | 3514 + 492 | 0 | 否（2） | ✓（解释 3 句） | ✓ | ✓ | no_change（与当前代码相同，运行停止） | 未执行 | 未执行 | 0.0 / 1.0 |
| B 采样 | 1 | stop | 3296 + 753 | 0 | 否（2） | ✓ | ✓ | ✗（Forbidden syntax: Lambda） | 策略拦截（自动重新提案） | 未执行 | 未执行 | 0.2 / 1.1 |
|  | 2 | stop | 3319 + 899 | 0 | 否（2） | ✓ | ✗（unexpected character after line continuation character (line 40)） | ✗（Invalid Python: unexpected character aft） | 策略拦截（自动重新提案） | 未执行 | 未执行 | 0.2 / 1.1 |
|  | 3 | stop | 3354 + 700 | 0 | 否（1） | ✓ | ✓ | ✓ | 批准 → pytest 未通过 | 1/11 | 0/11 | 0.2 / 1.1 |
| C 模型 14b | 1 | stop | 3314 + 990 | 0 | 否（1） | ✓ | ✓ | ✓ | 批准 → pytest 未通过 | 2/11 | 1/11 | 0.0 / 1.0 |
|  | 2 | stop | 3889 + 754 | 0 | 否（1） | ✓ | ✓ | ✓ | no_change（与当前代码相同，运行停止） | 未执行 | 未执行 | 0.0 / 1.0 |

各组只改一个变量（相对 rev 1）：rev 1 基线（对照组，rev 2 通道重跑） = none (rev-1 format, sampling and model through the revision-2 transport)；A 输出格式 = output format only: json_v1 -> fenced_v1；B 采样 = sampling only: temperature 0 -> 0.2, repeat_penalty 1.0 -> 1.1, seed 42 (needed for a reproducible non-greedy run)；C 模型 14b = model only: qwen2.5-coder:7b -> qwen2.5-coder:14b。
“未执行”：该提案没有进入审批（输出截断、格式/策略未通过或与当前代码相同）。holdout 结果只用于评测，从不反馈给模型。原始有缺陷代码的成绩是 4/22（公开 2/11、holdout 2/11）。

## 各组汇总（由上表计算）

- rev 1 基线（对照组，rev 2 通道重跑）：3 次提案，重复 3 次，正常结束 0 次，进入审批 0 次，批准后最好的 pytest —；平均生成速度 57.8 token/s；运行最终状态 model_error。
- A 输出格式：2 次提案，重复 0 次，正常结束 2 次，进入审批 1 次，批准后最好的 pytest 7/22；平均生成速度 57.7 token/s；运行最终状态 failed。
- B 采样：3 次提案，重复 0 次，正常结束 3 次，进入审批 1 次，批准后最好的 pytest 1/22；平均生成速度 57.5 token/s；运行最终状态 failed。
- C 模型 14b：2 次提案，重复 0 次，正常结束 2 次，进入审批 1 次，批准后最好的 pytest 3/22；平均生成速度 27.4 token/s；运行最终状态 failed。

生成速度口径：本轮取原生响应的 eval_count / eval_duration。本轮 7b 为 56.7–58.6 token/s，上一轮（evidence/context-validation，同一模型、同一服务配置）的服务日志是 87.71–97.34 token/s。今天的服务日志 eval time 与本轮数值一致，说明是机器状态不同（原因未查明），不是测量口径不同。所以只比较同一天测得的 7b 与 14b。

C 组显存检查（evidence/chip-rev2/C/vram-check/）：{"decision": "fits fully on GPU at 8192 context -> arm C runs", "evidence": {"api_ps_size_bytes": 10290085231, "api_ps_size_vram_bytes": 10290085231, "gpu_fraction": 1.0, "context_length": 8192, "llama_server": "offloaded 49/49 layers; CUDA0 model 8148.38 MiB + KV 1536.00 MiB + compute 129.01 MiB = 9813 MiB projected vs 11026 MiB free (1212 MiB left, no changes needed)", "cuda_host_model_buffer": "417.66 MiB on host for 14b (7b: same kind of host buffer, see 7b log) - token-embedding table placement, all 49 layers on GPU", "nvidia_smi_after_load": "9996 MiB, 1949 MiB, 12227 MiB", "estimate_before_pull_gib": 9.871, "measured_resident_gib": 9.583}}

## 结论（人工撰写，依据上表）

**哪个改动消除了重复退化：三个都消除了，最便宜的是 A（改输出格式）。**

- 对照组（rev 1 的格式、采样和模型，走同一条 rev 2 通道）3 次提案全部重复退化，都在 1600 个输出 token 处截断，复现了 rev 1 的问题。
- 只改一个变量后，A 组（代码放进围栏代码块、解释限 3 句）2/2、B 组（temperature 0.2 + repeat_penalty 1.1）3/3、C 组（换 14b）2/2 都正常结束，没有一次重复。所有组都没有 context shift。
- 因此重复退化不是上下文问题，也不是“只有更大模型才能解决”的问题。它是 7b 在贪心解码下、把长篇解释写进 JSON 字段时出现的解码失败。A 从源头去掉了那个长文本字段，没有额外运行成本。B 也有效，但引入了随机性，3 次里有 2 次代码被策略拦截（lambda、语法错误）。
- 样本很小：每组最多 3 次提案、只有一个任务。温度 0 也不是严格可复现的（等价性检查中，同一请求隔一天的输出从第 1260 个字符起就不同）。所以只能说“在这次实验里，每个单变量改动都避开了重复”，不能给出概率。

**消除重复不等于修好代码。** 批准后的 pytest：A 7/22，C 3/22，B 1/22；原始有缺陷代码本身是 4/22。没有一组接近通过。三份代码的错误都是业务逻辑层面的：mV 上下限换算、空值、冲突行与最大重测轮次、按芯片计数，以及崩溃。14b 在业务正确性上没有比“7b + 改格式”更好。

**对公司服务器选型的含义：**

1. 不要为了解决重复退化去换更大的模型或更大的 GPU。改输出格式（或采样参数）在 7b 上就能解决，成本几乎为零。
2. 这个多规则数据处理任务，7b 和 14b（Q4_K_M）都没能在 3 次提案内做对。本实验既不能说明 14b 够用，也不能说明需要多大的模型。
3. 本机实测的 7b → 14b 代价（同为 8192 上下文 × 1 槽位、同一天同一机器状态）：
   - 驻留显存 4.8 GiB → 9.6 GiB，其中 KV 从 0.44 GiB 变为 1.5 GiB；
   - 生成速度约 58 → 约 27 token/s，下降一半多；
   - 12 GB 显卡只剩约 1.2 GiB 余量，开不了第二个并发槽位，也加不了上下文。
4. 换算到服务器（估算，未实测）：
   - 14b Q4 要同时支持并发或更长上下文，至少需要 16–24 GB 显存；BF16 的 14b 光权重就约 28 GiB，需要 40–48 GB 的卡。
   - 如果下一步要试更强的模型（例如 32B 级 coder，本次未测）：Q4 约 18.5 GiB 权重 + 8k KV 约 2 GiB，24 GB 卡只够单槽位；BF16 约 61 GiB，需要 80 GB 的卡或两卡张量并行。
5. 更务实的顺序：先在 7b / 14b 上用 A 格式，改进任务拆分和反馈，并增加试验次数，确认瓶颈确实在模型能力上，再决定是否采购能跑 32B 的 GPU。
