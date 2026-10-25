# 回归日志分诊：dataset/dev/d07_mixed.log

- 引擎：rules-v1；生成于 2026-10-25T20:53:01+00:00；日志 46 行，sha256 1223e5d400b6ec0f…
- 日志状态：complete；标记：tool_internal_assertion
- 复核状态：待工程师复核：alu_basic, alu_syntax, fifo_full, handshake_stuck
- 建议只供参考，不会自动执行任何命令或修改 RTL/测试。

| 测试 | 结果 | 类别 | 归属 | 证据 | 指纹 | 复核 |
|---|---|---|---|---|---|---|
| alu_basic | pass | 通过 | — | `dataset/dev/d07_mixed.log:7` TEST PASSED: tb_alu8 | — | 待复核 |
| alu_syntax | not_run | 编译失败 | 设计或测试问题 | `dataset/dev/d07_mixed.log:11` hdl/rtl/alu8.v:25: syntax error | compile_error:849a9b12 | 待复核 |
| fifo_full | fail | 测试/断言失败 | 设计或测试问题 | `dataset/dev/d07_mixed.log:35` FATAL: hdl/tb/tb_sync_fifo.v:26: fifo reports full after 3 writes (count=3, DEPTH=4) | test_failure:c65e3fd8 | 待复核 |
| handshake_stuck | fail | 超时 | 设计或测试问题 | `dataset/dev/d07_mixed.log:42` ERROR: [2000000] TIMEOUT watchdog: ack not seen within 2000 ns after req<br>`dataset/dev/d07_mixed.log:43` TEST FAILED: tb_handshake (timeout) | timeout:ee609678 | 待复核 |

## 排查建议

- **alu_syntax**：先修第一条编译错误 dataset/dev/d07_mixed.log:11：“hdl/rtl/alu8.v:25: syntax error”。之后的报错多半是它引起的连锁报错，修完再重新编译。（第 29 行是编译器在报错后自身的内部断言崩溃，不是设计断言；其余 16 条报错多半是第一条引起的连锁报错）
- **fifo_full**：testbench 检查失败，首条证据 dataset/dev/d07_mixed.log:35：“FATAL: hdl/tb/tb_sync_fifo.v:26: fifo reports full after 3 writes (count=3, DEPTH=4)”。对照期望值与实际值，查看相关信号在报告时刻附近的驱动和时序。
- **handshake_stuck**：testbench 的 watchdog 触发 dataset/dev/d07_mixed.log:42：“ERROR: [2000000] TIMEOUT watchdog: ack not seen within 2000 ns after req”。DUT 没有在规定时间内响应，优先检查握手信号、复位和计数器是否推进。
