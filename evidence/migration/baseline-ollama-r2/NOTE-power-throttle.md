# eval-v2 dev 基线中止：笔记本在电池供电、静音电源方案下运行（2026-10-25）

**结论**：eval-v2 的 dev 拆分跑了 4 个样本后停止。这 4 个样本的结果都对（6/6 个测试），但测得的耗时只反映电池加降频的状态，不能作为迁移前的服务基线。holdout 没有运行，仍然是盲测。

## 经过

| 时间（UTC） | 事件 | 证据 |
|---|---|---|
| 05:16 | 预检：可用内存 9093 MiB，提交余量 11860 MiB，GPU 空闲，通过 | 00-preflight.json |
| 05:17 | 启动 r2（上下文 8192、并行 1），24 s 后 API 就绪 | 01-start.txt、ollama-launch-*.json |
| 05:18 | `release verify` 与清单一致（二进制、版本、模型 digest、参数） | 02-release-verify.txt |
| 05:18 | 分层健康检查 healthy：100% 在 GPU，上下文 8192 | 03-health.txt |
| 05:18 | 冻结 eval-v2，开始 dev | contract/eval-v2.json |
| 05:19–05:23 | d01–d04 都返回 ok。生成速度只有 7.4 tok/s，平时是 50–90 tok/s | server-log/、results/eval-v2-qwen/dev/ |
| 05:23 | 查明原因，只结束本轮自己的评测进程树，然后卸载模型 | model-runs/eval-v2/dev/session.json、model-runs/eval-v2/unload.json |

## 原因

运行期间（约 05:22Z）`nvidia-smi` 与系统状态的读数如下，从本次会话的控制台抄录：

- **未接交流电源**（`BatteryStatus.PowerOnline = False`，电量 96%），电源方案为 **Silent**；
- GPU 处于 **P5**，强制功耗上限 **33 W**，`sw_power_cap` 降频生效；显存时钟 **810 MHz**；SM 时钟 1890/3090 MHz；利用率 98%。

服务日志里的速度（用 `grep "eval time"` 和 `grep "prompt eval time"` 可以在每份日志中复核）：

| 日志 | prompt（>500 token）平均 | 生成（>200 token）平均 |
|---|---|---|
| 2026-10-23 19:28 启动（r1） | 2643 tok/s | 约 82 tok/s |
| 2026-10-24 05:42 启动（r2 激活与 chip rev 2） | 1795 tok/s | 约 51 tok/s |
| **2026-10-25 05:17 启动（本次）** | **785 tok/s** | **7.4 tok/s（134 ms/token）** |

之前那些请求同样用了 `response_format` json_schema，所以速度下降不是结构化输出造成的。

## 为什么不能继续

- 时限会被触发：`max_tokens` 是 1200，按 7.4 tok/s 要约 165 s，再加上 prompt 处理，已经接近 180 s 的请求超时。超时会被记为模型的“请求失败”，但真正的原因是供电状态。
- 耗时、tokens/s 这类服务指标只代表电池降频状态，拿去和迁移后的服务器比较没有意义。
- 长时间在电池上满载运行 GPU。

## 后续

- 改电源设置是 Jeff 的决定，本轮没有修改任何系统设置。
- 接上电源、切换到平衡或高性能方案后，先复查 P 状态、功耗上限和时钟，再用**新的合同版本**重跑 dev 和 holdout。eval-v2 的 dev 已经有结果，按规则不能在同一版本下重跑。
- 这 4 个样本的原始响应和评分保留在 `results/eval-v2-qwen/dev/`，不删除，也不计入正式基线。
