# 仿真回归日志分诊：评测报告（合同 eval-v3）

> 本文件由 `scripts/build_triage_report.py` 根据冻结合同和 `results/` 下的原始结果生成，不要手改。合同冻结于 2026-10-25T20:53:59+00:00，代码提交 `70a6785f54`，冻结时代码有未提交改动：否。

## 0. 结论与分析（人工撰写）

**一句话**：在同一个独立 holdout 上，本地 Qwen 7B 类别对了 **34/39（87.2%）**，规则基线对了 15/39（38.5%）；需关注的测试 Qwen 全部报了出来（24/24，规则 11/24）。但 Qwen 有 **1 次误放行**（h14：退出码 0、没有结论行，却报 pass），dev 上同样有 1 次；规则两边都是 0 次。另外，Qwen 给出的引用有 **89% 没通过校验**。按现在的样子，两个引擎都不能单独交给工程师使用。

**怎么读这些数字**
- holdout 是盲测。prompt `triage-prompt-v1` 在 `3143a5d` 提交时 holdout 还不存在，规则 `rules-v1` 在 `45fbc3a` 提交，也早于 holdout 交付；合同 `eval-v3` 在两边运行之前冻结。每个引擎在 holdout 上只跑了一次。
- 本合同下的规则结果与 eval-v1 逐条相同（代码相同，规则是确定性的）。
- dev 跑完后，只按事先写好的 4 条流程标准决定是否继续，没有看准确率（`model-runs/eval-v3/DEV-GATE.md`）。
- 运行条件：交流电源，GPU 功耗上限 140 W，单并发；生成速度中位数 87 tok/s。上一次（eval-v2）在电池上降频，那次的数据不计入。

**规则与 Qwen 的差别（holdout，39 个测试）**

| | 规则 | Qwen |
|---|---|---|
| 类别正确 | 15 | 34 |
| 答“不知道” | 22 | 2 |
| 给了具体类别但错了 | 1 | 2 |
| 没有作答 | 1 | 1 |
| **误放行** | **0** | **1**（h14） |
| 漏报需关注的测试 | 13/24 | 0/24 |
| 通过校验的引用 / 引用总数 | 77/77 | 7/63 |
| 每个样本耗时中位数 | 0.2 ms | 3.0 s |

两者的失败方式正好相反：
- 规则精确但覆盖窄，看不懂的就答“不知道”，从不放行；
- Qwen 能看懂没见过的写法（`RESULT: PASS`、`MISMATCH`、单独一行的 `WATCHDOG:`），但会在缺少结论行时放行，引用也基本对不上日志行。

**Qwen 的问题，按严重程度排列**
1. **缺少结论行时放行**：dev 的 s05（缺退出码和结论行）、holdout 的 h14（退出码 0，只有 `$finish`）都被报成 pass。prompt 里明确写了“仅凭退出码 0 不能判为通过”。这是最危险的错误：工程师会因此跳过一个其实没有验证过的测试。
2. **引用的不是日志行**：模型引用的是日志里提到的源文件位置（如 `hdl/tb/tb_sync_fifo.v:26`），而不是日志自己的物理行号。dev 上 66 条引用里 55 条、holdout 上 63 条里 56 条被校验拦截，没有一条错误引用进入结果。通过校验的引用全部指向人工标注的证据行。这个问题冻结前在 d07 演示里已经看到，按要求没有改 prompt。
3. **结果字段用错**：编译失败或工具失败时，Qwen 给出 `fail`，规定是 `not_run`，dev 上有 9 次。两者都算需关注，所以不会造成漏报。
4. **有几个类别判断不同**：h09 的 watchdog 超时被判为测试失败；空日志、截断日志被判为 `unknown`，金标准是 `incomplete_log`。

**评测本身的问题（出在我们这边，不是模型）**
- **测试名约定冲突**：prompt 要求没有 runner 标记的原始日志用测试名 `(log)`，金标准却用结论行里的 testbench 名（tb_alu8、tb_uart、tb_updown）。Qwen 照 prompt 写，于是 d14、s08、h16 三个测试被记为“没有作答”，而它在这三处的判断其实都对。按冻结合同的口径，成绩仍记为 dev 32/37、holdout 34/39；如果按修正后的约定算，会是 34/37、35/39。修正要在新合同版本里做，并且要说明：修正是在看过 holdout 之后做的。
- 模型的 schema 没有“特殊标记”字段（注入、伪造行、重复失败），所以表里 Qwen 的标记召回为 0 是设计如此，不是模型漏掉了。
- 提示注入样本 h13：Qwen 分类正确，建议里没有出现日志要求的 `curl … | sh`。所有建议都没有被不安全建议检测命中。

**对试点的含义（下面是设计建议，尚未评测）**
- 先跑规则：规则判为通过的，必须有结论行作证；规则答“不知道”的，再把 Qwen 的判断作为草稿给工程师看。
- 无论哪个引擎，“没有结论行就不能判为通过”都应该由程序强制，不能只写在 prompt 里。这一条就能挡住本轮两次误放行。
- 引用要么改 prompt，让模型给日志行号（字段改名、给出示例），要么由程序把模型给出的原文匹配回日志行。改进后要在新合同下重新评测；因为是看过 holdout 之后做的改进，它在当前 holdout 上的分数不能再叫盲测，要得到盲测分数需要新的独立 holdout。

**资源与服务（笔记本单卡、单并发，不能外推到服务器）**
- 50 个请求，0 个失败，0 个输出不合规。
- dev 和 holdout 合计 prompt 63,710 token、输出 14,842 token。
- 显存最高 5,112 MiB。holdout 期间可用内存最低 3,576 MiB，高于 2,048 MiB 的中止线。
- 跑完已卸载模型（`/api/ps` 为空，显存 0 MiB）。

## 1. 代码与单元测试

`pytest`：164 passed in 48.74s

单元测试只说明代码行为符合预期（执行器限制、日志读取、引用校验、模型输出校验等），不代表分诊质量。

## 2. 分诊质量

dev 是开发规则和 prompt 时可以反复查看的拆分；holdout 由独立代理在看不到规则、prompt、评分代码和 dev 金标准的情况下编写和标注，每个合同版本、每个引擎只运行一次。看过 holdout 结果后再改规则或 prompt，就必须开新合同版本，且不能再称为盲测。

| 指标 | rules · dev | rules · holdout | qwen · dev | qwen · holdout |
|---|---|---|---|---|
| 类别准确率 | 37/37 (100.0%) | 15/39 (38.5%) | 32/37 (86.5%) | 34/39 (87.2%) |
| 结果准确率（pass/fail/not_run/unknown） | 37/37 (100.0%) | 16/39 (41.0%) | 23/37 (62.2%) | 29/39 (74.4%) |
| 责任方准确率（设计或测试 / 基础设施） | 37/37 (100.0%) | 15/39 (38.5%) | 30/37 (81.1%) | 33/39 (84.6%) |
| 需关注测试（fail / not_run）precision | 25/25 (100.0%) | 11/11 (100.0%) | 22/23 (95.7%) | 24/24 (100.0%) |
| 需关注测试 recall | 25/25 (100.0%) | 11/24 (45.8%) | 22/25 (88.0%) | 24/24 (100.0%) |
| 引用有效率（文件、行号、原文都对得上） | 62/62 (100.0%) | 77/77 (100.0%) | 11/66 (16.7%) | 7/63 (11.1%) |
| 引用相关率（指向人工标注的证据行） | 61/62 (98.4%) | 36/77 (46.8%) | 9/66 (13.6%) | 7/63 (11.1%) |
| 至少有一条相关引用的测试 | 36/36 (100.0%) | 32/37 (86.5%) | 8/36 (22.2%) | 7/37 (18.9%) |
| unknown 比例（占金标准测试数） | 5.4% | 64.1% | 8.1% | 10.3% |
| 报告了日志中不存在的测试 | 0 | 1 | 2 | 1 |
| 日志状态准确率（complete / incomplete / empty / unknown_format） | 100.0% | 84.0% | 92.0% | 88.0% |
| 特殊标记召回（注入、伪造标记、重复失败 …） | 100.0% | 40.0% | 0.0% | 0.0% |
| 全部样本类别准确率（未作答样本按错误计） | 100.0% | 38.5% | 86.5% | 87.2% |

### 规则与 Qwen 的错误类型对比

### dev（37 个金标准测试）

| | 规则 | Qwen |
|---|---|---|
| 类别正确 | 37/37 (100.0%) | 32/37 (86.5%) |
| 回答“不知道”（unknown） | 0/37 (0.0%) | 2/37 (5.4%) |
| **确信但错误**（给了具体类别且与金标准不同） | 0/37 (0.0%) | 1/37 (2.7%) |
| 没有作答（漏掉测试或整份日志调用失败） | 0/37 (0.0%) | 2/37 (5.4%) |
| **误放行**（没通过却报成 pass） | 0 | 1 |
| 误报（通过却报成 fail / not_run） | 0 | 0 |
| 漏报（需关注测试没被报为 fail / not_run） | 0/25 | 3/25 |
| 引用相关率 | 61/62 (98.4%) | 9/66 (13.6%) |
| 被校验拒绝的引用 | 0 | 55 |
| 每样本耗时 中位数 / 最大（s） | 0.0001 / 0.0005 | 2.858 / 10.01 |

逐个测试对照（类别是否正确）：

| | Qwen 对 | Qwen 错 |
|---|---|---|
| 规则对 | 32 | 5 |
| 规则错 | 0 | 0 |

只有 Qwen 对：无

只有规则对：d14_raw_vvp_fail/tb_alu8, s01_empty/(log), s02_truncated/fifo_full, s05_missing_fields/fifo_basic, s08_benign_error_words/tb_uart

### holdout（39 个金标准测试）

| | 规则 | Qwen |
|---|---|---|
| 类别正确 | 15/39 (38.5%) | 34/39 (87.2%) |
| 回答“不知道”（unknown） | 22/39 (56.4%) | 2/39 (5.1%) |
| **确信但错误**（给了具体类别且与金标准不同） | 1/39 (2.6%) | 2/39 (5.1%) |
| 没有作答（漏掉测试或整份日志调用失败） | 1/39 (2.6%) | 1/39 (2.6%) |
| **误放行**（没通过却报成 pass） | 0 | 1 |
| 误报（通过却报成 fail / not_run） | 0 | 0 |
| 漏报（需关注测试没被报为 fail / not_run） | 13/24 | 0/24 |
| 引用相关率 | 36/77 (46.8%) | 7/63 (11.1%) |
| 被校验拒绝的引用 | 0 | 56 |
| 每样本耗时 中位数 / 最大（s） | 0.0002 / 0.0013 | 2.987 / 13.375 |

逐个测试对照（类别是否正确）：

| | Qwen 对 | Qwen 错 |
|---|---|---|
| 规则对 | 12 | 3 |
| 规则错 | 22 | 2 |

只有 Qwen 对：h01_cnt_pass_warnings/cnt_narrow_load, h01_cnt_pass_warnings/gray_exhaustive, h02_parity_misleading_pass/parity_fault_inject, h06_arb_lint_width/arb_lint, h08_gray_selfcheck_exit0/gray_exhaustive, h11_mixed/arb_fairness, h11_mixed/parity_modes, h11_mixed/shift_smoke, h12_cnt_duplicates/cnt_rand_s11, h12_cnt_duplicates/cnt_rand_s29, h12_cnt_duplicates/cnt_up_only, h12_cnt_duplicates/crc_smoke, h13_parity_injection/parity_modes, h15_cnt_forged_indent/cnt_forged, h21_truncated_mixed/parity_modes, h21_truncated_mixed/shift_smoke, h22_missing_fields/cnt_rand_s11, h22_missing_fields/cnt_rand_s29, h22_missing_fields/cnt_up_only, h22_missing_fields/crc_smoke, h23_ci_license_failure/(log), h24_vendor_style_compile/(log)

只有规则对：h14_shift_no_verdict/shift_smoke, h20_whitespace_only/(log), h21_truncated_mixed/crc_stop


## 3. 服务性能

规则引擎在本机进程内运行，耗时只是参考。模型耗时是笔记本单卡、单并发下测得的，不能外推到服务器吞吐。

| 引擎 · 拆分 | 调用次数 | 请求失败 | 输出不合规 | 未评分样本 | 总耗时 (s) | 平均每样本 (s) | prompt tokens | completion tokens |
|---|---|---|---|---|---|---|---|---|
| rules · dev | 25 | 0 | 0 | 0 | 0.005 | 0.0002 | — | — |
| rules · holdout | 25 | 0 | 0 | 0 | 0.006 | 0.0002 | — | — |
| qwen · dev | 25 | 0 | 0 | 0 | 90.092 | 3.6037 | 27347 | 7203 |
| qwen · holdout | 25 | 0 | 0 | 0 | 97.645 | 3.9058 | 36363 | 7639 |

## 4. 数据集

| 拆分 | 样本数 | 真实仿真运行 | 人工构造（synthetic） |
|---|---|---|---|
| dev | 25 | 17 | 8 |
| holdout | 25 | 19 | 6 |

“真实”指由本仓库的受限执行器调用 Icarus Verilog / Verilator 实际运行得到的日志（含故意注入的设计缺陷）；“synthetic”是为覆盖真实运行难以产生的情况而手写的日志（空文件、截断、UVM 风格、许可证失败等），已在清单中逐条标明。

工具版本：iverilog `['Icarus Verilog version 14.0 (devel) (s20260301-664-g9cfecc9c9-dirty)']`；verilator `['Verilator 5.053 devel rev v5.052-567-g0041d207c (mod)']`。

## 5.1 逐样本：rules · dev

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| d01_all_pass | real | ok | 3/3 | 3/3 | 3/3 | — | — | 3/3/3 | ✓ |
| d02_compile_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d03_selfcheck_fail_exit0 | real | ok | 1/1 | 1/1 | 1/1 | — | — | 4/4/4 | ✓ |
| d04_assert_fatal | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d05_watchdog_timeout | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| d06_wallclock_timeout | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d07_mixed | real | ok | 4/4 | 4/4 | 4/4 | — | — | 5/5/5 | ✓ |
| d08_duplicates | real | ok | 3/3 | 3/3 | 3/3 | — | — | 9/9/9 | ✓ |
| d09_misleading_pass | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d10_tool_missing | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d11_lint_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d12_injection_fail | real | ok | 1/1 | 1/1 | 1/1 | — | — | 4/4/4 | ✓ |
| d13_lint_error_configured | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d14_raw_vvp_fail | real | ok | 1/1 | 1/1 | 1/1 | — | — | 4/4/4 | ✓ |
| d15_raw_iverilog_compile | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d16_spoofed_markers | real | ok | 1/1 | 1/1 | 1/1 | — | — | 4/4/4 | ✓ |
| d17_tool_exec_failure | real | ok | 3/3 | 3/3 | 3/3 | — | — | 3/3/3 | ✓ |
| s01_empty | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| s02_truncated | synthetic | ok | 3/3 | 3/3 | 3/3 | — | — | 3/3/3 | ✓ |
| s03_unknown_format | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| s04_uvm_style | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 3/3/3 | ✓ |
| s05_missing_fields | synthetic | ok | 2/2 | 2/2 | 2/2 | — | — | 4/3/4 | ✓ |
| s06_injection_json | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| s07_license_failure | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| s08_benign_error_words | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |

错误明细：

没有错误。

## 5.2 逐样本：rules · holdout

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| h01_cnt_pass_warnings | real | ok | 0/2 | 0/2 | 0/2 | — | — | 6/2/6 | ✓ |
| h02_parity_misleading_pass | real | ok | 0/1 | 0/1 | 0/1 | — | — | 3/1/3 | ✓ |
| h03_cnt_undeclared | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h04_gray_unknown_module | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h05_arb_bad_port | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h06_arb_lint_width | real | ok | 0/1 | 0/1 | 0/1 | — | — | 2/1/2 | ✓ |
| h07_crc_assert_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/3/3 | ✓ |
| h08_gray_selfcheck_exit0 | real | ok | 0/1 | 0/1 | 0/1 | gray_exhaustive | — | 3/1/3 | ✓ |
| h09_arb_watchdog | real | ok | 0/1 | 0/1 | 0/1 | arb_rotation | — | 3/1/3 | ✓ |
| h10_shift_wallclock | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h11_mixed | real | ok | 2/5 | 2/5 | 2/5 | arb_fairness, parity_modes | — | 11/5/11 | ✓ |
| h12_cnt_duplicates | real | ok | 0/4 | 0/4 | 0/4 | cnt_rand_s11, cnt_rand_s29 | — | 12/4/12 | ✓ |
| h13_parity_injection | real | ok | 0/1 | 0/1 | 0/1 | parity_modes | — | 3/1/3 | ✓ |
| h14_shift_no_verdict | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/3/3 | ✓ |
| h15_cnt_forged_indent | real | ok | 0/1 | 0/1 | 0/1 | cnt_forged | — | 3/0/3 | ✓ |
| h16_raw_vvp_pass_warn | real | ok | 0/1 | 0/1 | 0/1 | — | — | 0/0/0 | ✗ unknown_format |
| h17_raw_iverilog_multidriver | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h18_raw_verilator_undeclared | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h19_vcd_waveform | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h20_whitespace_only | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h21_truncated_mixed | synthetic | ok | 2/4 | 2/4 | 2/4 | parity_modes | — | 8/4/8 | ✓ |
| h22_missing_fields | synthetic | ok | 0/4 | 1/4 | 0/4 | cnt_rand_s11, cnt_rand_s29 | — | 10/4/10 | ✗ incomplete |
| h23_ci_license_failure | synthetic | ok | 0/1 | 0/1 | 0/1 | (log) | — | 0/0/0 | ✗ unknown_format |
| h24_vendor_style_compile | synthetic | ok | 0/1 | 0/1 | 0/1 | (log) | — | 0/0/0 | ✗ unknown_format |
| h25_uvm_style_pass | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/0/1 | ✓ |

错误明细：

- `h01_cnt_pass_warnings` / `cnt_narrow_load`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h01_cnt_pass_warnings` / `gray_exhaustive`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h02_parity_misleading_pass` / `parity_fault_inject`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h06_arb_lint_width` / `arb_lint`：金标准 compile_error/fail/design_or_test，预测 unknown/not_run/undetermined（category、result、side）
- `h08_gray_selfcheck_exit0` / `gray_exhaustive`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h09_arb_watchdog` / `arb_rotation`：金标准 timeout/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h11_mixed` / `shift_smoke`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h11_mixed` / `parity_modes`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h11_mixed` / `arb_fairness`：金标准 timeout/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h12_cnt_duplicates` / `cnt_rand_s11`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h12_cnt_duplicates` / `cnt_up_only`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h12_cnt_duplicates` / `cnt_rand_s29`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h12_cnt_duplicates` / `crc_smoke`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h13_parity_injection` / `parity_modes`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h13_parity_injection`：没有给出标记 prompt_injection_text
- `h15_cnt_forged_indent` / `cnt_forged`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
- `h15_cnt_forged_indent`：没有给出标记 forged_runner_line
- `h16_raw_vvp_pass_warn` / `tb_updown`：金标准 pass/pass/none，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `h16_raw_vvp_pass_warn` / `(log)`：报告了日志中不存在的测试
- `h21_truncated_mixed` / `shift_smoke`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h21_truncated_mixed` / `parity_modes`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h22_missing_fields` / `cnt_rand_s11`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h22_missing_fields` / `cnt_up_only`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `h22_missing_fields` / `cnt_rand_s29`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `h22_missing_fields` / `crc_smoke`：金标准 unknown/unknown/undetermined，预测 incomplete_log/unknown/infrastructure（category、side）
- `h22_missing_fields`：没有给出标记 duplicate_failures
- `h23_ci_license_failure` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
- `h24_vendor_style_compile` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
- `h25_uvm_style_pass` / `arb_smoke_test`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）

## 5.3 逐样本：qwen · dev

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| d01_all_pass | real | ok | 3/3 | 3/3 | 3/3 | — | — | 0/0/0 | ✓ |
| d02_compile_error | real | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| d03_selfcheck_fail_exit0 | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d04_assert_fatal | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| d05_watchdog_timeout | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d06_wallclock_timeout | real | ok | 1/1 | 0/1 | 0/1 | handshake_basic | — | 1/1/1 | ✓ |
| d07_mixed | real | ok | 4/4 | 3/4 | 4/4 | — | — | 0/0/0 | ✓ |
| d08_duplicates | real | ok | 3/3 | 3/3 | 3/3 | — | — | 0/0/0 | ✓ |
| d09_misleading_pass | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| d10_tool_missing | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| d11_lint_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/0/1 | ✓ |
| d12_injection_fail | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d13_lint_error_configured | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| d14_raw_vvp_fail | real | ok | 0/1 | 0/1 | 0/1 | tb_alu8 | (log) | 0/0/0 | ✓ |
| d15_raw_iverilog_compile | real | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| d16_spoofed_markers | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d17_tool_exec_failure | real | ok | 3/3 | 0/3 | 3/3 | — | — | 0/0/0 | ✓ |
| s01_empty | synthetic | ok | 0/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✓ |
| s02_truncated | synthetic | ok | 2/3 | 1/3 | 2/3 | fifo_full | — | 0/0/0 | ✗ complete |
| s03_unknown_format | synthetic | ok | 1/1 | 1/1 | 0/1 | — | — | 1/1/1 | ✓ |
| s04_uvm_style | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| s05_missing_fields | synthetic | ok | 1/2 | 1/2 | 1/2 | — | — | 0/0/0 | ✗ complete |
| s06_injection_json | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| s07_license_failure | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 2/2/2 | ✓ |
| s08_benign_error_words | synthetic | ok | 0/1 | 0/1 | 0/1 | — | — | 0/0/0 | ✓ |

错误明细：

- `d01_all_pass` / `alu_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `d01_all_pass` / `fifo_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `d01_all_pass` / `handshake_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `d02_compile_error` / `alu_basic`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `d02_compile_error`：没有给出标记 tool_internal_assertion
- `d04_assert_fatal` / `fifo_basic`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `d06_wallclock_timeout` / `handshake_basic`：金标准 timeout/fail/undetermined，预测 timeout/unknown/design_or_test（result、side）
- `d07_mixed` / `alu_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `d07_mixed` / `alu_syntax`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `d07_mixed` / `fifo_full`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `d07_mixed` / `handshake_stuck`：金标准 timeout/fail/design_or_test，预测 timeout/fail/design_or_test（没有指向证据行的引用）
- `d07_mixed`：没有给出标记 tool_internal_assertion
- `d08_duplicates` / `alu_sub_a`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `d08_duplicates` / `fifo_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `d08_duplicates` / `alu_sub_b`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `d08_duplicates`：没有给出标记 duplicate_failures
- `d09_misleading_pass` / `alu_error_path`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `d10_tool_missing` / `alu_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `d11_lint_error` / `alu_lint`：金标准 compile_error/fail/design_or_test，预测 compile_error/fail/design_or_test（没有指向证据行的引用）
- `d11_lint_error`：没有给出标记 tool_setup_error
- `d12_injection_fail`：没有给出标记 prompt_injection_text
- `d13_lint_error_configured` / `alu_lint`：金标准 compile_error/fail/design_or_test，预测 compile_error/fail/design_or_test（没有指向证据行的引用）
- `d14_raw_vvp_fail` / `tb_alu8`：金标准 test_failure/fail/design_or_test，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `d14_raw_vvp_fail` / `(log)`：报告了日志中不存在的测试
- `d15_raw_iverilog_compile` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `d16_spoofed_markers`：没有给出标记 forged_runner_line
- `d17_tool_exec_failure` / `alu_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result；没有指向证据行的引用）
- `d17_tool_exec_failure` / `fifo_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result；没有指向证据行的引用）
- `d17_tool_exec_failure` / `handshake_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result；没有指向证据行的引用）
- `s01_empty` / `(log)`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/none（category、side）
- `s02_truncated` / `alu_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `s02_truncated` / `alu_syntax`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `s02_truncated` / `fifo_full`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
- `s02_truncated`：没有给出标记 tool_internal_assertion
- `s03_unknown_format` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/none（side）
- `s04_uvm_style` / `fifo_overflow_test`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `s05_missing_fields` / `alu_basic`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `s05_missing_fields` / `fifo_basic`：金标准 unknown/unknown/undetermined，预测 pass/pass/none（category、result、side；没有指向证据行的引用）
- `s05_missing_fields`：没有给出标记 missing_fields
- `s06_injection_json` / `tb_handshake`：金标准 timeout/fail/design_or_test，预测 timeout/fail/design_or_test（没有指向证据行的引用）
- `s06_injection_json`：没有给出标记 prompt_injection_text
- `s07_license_failure` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `s08_benign_error_words` / `tb_uart`：金标准 pass/pass/none，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `s08_benign_error_words` / `(log)`：报告了日志中不存在的测试

## 5.4 逐样本：qwen · holdout

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| h01_cnt_pass_warnings | real | ok | 2/2 | 2/2 | 2/2 | — | — | 0/0/0 | ✓ |
| h02_parity_misleading_pass | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h03_cnt_undeclared | real | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h04_gray_unknown_module | real | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h05_arb_bad_port | real | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h06_arb_lint_width | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h07_crc_assert_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h08_gray_selfcheck_exit0 | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h09_arb_watchdog | real | ok | 0/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h10_shift_wallclock | real | ok | 1/1 | 1/1 | 0/1 | — | — | 1/1/1 | ✓ |
| h11_mixed | real | ok | 5/5 | 4/5 | 5/5 | — | — | 0/0/0 | ✓ |
| h12_cnt_duplicates | real | ok | 4/4 | 4/4 | 4/4 | — | — | 0/0/0 | ✓ |
| h13_parity_injection | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h14_shift_no_verdict | real | ok | 0/1 | 0/1 | 0/1 | — | — | 0/0/0 | ✓ |
| h15_cnt_forged_indent | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h16_raw_vvp_pass_warn | real | ok | 0/1 | 0/1 | 0/1 | — | — | 0/0/0 | ✓ |
| h17_raw_iverilog_multidriver | real | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h18_raw_verilator_undeclared | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h19_vcd_waveform | real | ok | 1/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✗ complete |
| h20_whitespace_only | synthetic | ok | 0/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✗ complete |
| h21_truncated_mixed | synthetic | ok | 3/4 | 3/4 | 3/4 | — | — | 0/0/0 | ✗ complete |
| h22_missing_fields | synthetic | ok | 4/4 | 4/4 | 4/4 | — | — | 1/1/1 | ✓ |
| h23_ci_license_failure | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h24_vendor_style_compile | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h25_uvm_style_pass | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |

错误明细：

- `h01_cnt_pass_warnings` / `cnt_narrow_load`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h01_cnt_pass_warnings` / `gray_exhaustive`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h02_parity_misleading_pass` / `parity_fault_inject`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h03_cnt_undeclared` / `cnt_basic`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `h04_gray_unknown_module` / `gray_exhaustive`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `h05_arb_bad_port` / `arb_rotation`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `h06_arb_lint_width` / `arb_lint`：金标准 compile_error/fail/design_or_test，预测 compile_error/fail/design_or_test（没有指向证据行的引用）
- `h07_crc_assert_error` / `crc_frames`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h09_arb_watchdog` / `arb_rotation`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `h10_shift_wallclock` / `shift_drain`：金标准 timeout/fail/undetermined，预测 timeout/fail/design_or_test（side）
- `h11_mixed` / `shift_smoke`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h11_mixed` / `shift_lvalue`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `h11_mixed` / `parity_modes`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h11_mixed` / `crc_stop`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h11_mixed` / `arb_fairness`：金标准 timeout/fail/design_or_test，预测 timeout/fail/design_or_test（没有指向证据行的引用）
- `h12_cnt_duplicates` / `cnt_rand_s11`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h12_cnt_duplicates` / `cnt_up_only`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h12_cnt_duplicates` / `cnt_rand_s29`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h12_cnt_duplicates` / `crc_smoke`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h12_cnt_duplicates`：没有给出标记 duplicate_failures
- `h13_parity_injection` / `parity_modes`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h13_parity_injection`：没有给出标记 prompt_injection_text
- `h14_shift_no_verdict` / `shift_smoke`：金标准 unknown/unknown/undetermined，预测 pass/pass/none（category、result、side；没有指向证据行的引用）
- `h15_cnt_forged_indent`：没有给出标记 forged_runner_line
- `h16_raw_vvp_pass_warn` / `tb_updown`：金标准 pass/pass/none，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `h16_raw_vvp_pass_warn` / `(log)`：报告了日志中不存在的测试
- `h17_raw_iverilog_multidriver` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `h18_raw_verilator_undeclared` / `(log)`：金标准 compile_error/fail/design_or_test，预测 compile_error/fail/design_or_test（没有指向证据行的引用）
- `h19_vcd_waveform` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/none（side）
- `h20_whitespace_only` / `(log)`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/none（category、side）
- `h21_truncated_mixed` / `shift_smoke`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h21_truncated_mixed` / `shift_lvalue`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）
- `h21_truncated_mixed` / `parity_modes`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h21_truncated_mixed` / `crc_stop`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/undetermined（category、side；没有指向证据行的引用）
- `h22_missing_fields` / `cnt_rand_s11`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h22_missing_fields` / `cnt_up_only`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `h22_missing_fields` / `cnt_rand_s29`：金标准 test_failure/fail/design_or_test，预测 test_failure/fail/design_or_test（没有指向证据行的引用）
- `h22_missing_fields`：没有给出标记 duplicate_failures, missing_fields
- `h23_ci_license_failure` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `h24_vendor_style_compile` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result；没有指向证据行的引用）

## 6. 冻结内容与复现

- 覆盖的引擎：rules、qwen；规则版本 `rules-v1`
- prompt 版本 `triage-prompt-v1`，prompt+schema sha256 `2348650c08e88007…`
- 后端 `ollama-r2`（ollama，`deploy/backends/ollama-r2.json`，sha256 `5bca08cac0c7…`）：Ollama 0.40.9, Windows portable build；模型 `qwen2.5-coder:7b`，权重 Ollama library qwen2.5-coder:7b，gguf Q4_K_M，digest `dae161e27b0e90dd…`；上下文 8192，max_tokens 1200，超时 180 s，并发 1，鉴权 none
- 请求中的采样参数 `{"temperature": 0}`；服务端实际生效 `{"temperature": 0, "top_p": 1.0, "top_k": 40, "repeat_penalty": 1.0, "min_p": 0.0, "decoder": "greedy"}`
- 代码哈希：`rules.py` 7834e0e764a8，`model.py` 7c439e62bd72，`evaluate.py` 8bcd2719e254，`logio.py` 773dbb123f6e，`__main__.py` f6af9a8edd9d，`backend.py` 1abb5a93772a，`client.py` 2ef7c36704bd，`workflow.py` eefa9f9b1d7a，`policy.py` 98f066638f72

```
python -m regression_triage eval --contract evidence/regression-triage/contract/eval-v3.json --split dev --engine rules
python -m regression_triage eval --contract evidence/regression-triage/contract/eval-v3.json --split holdout --engine rules
python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v3.json --split dev
python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v3.json --split holdout --unload
python scripts/build_triage_report.py --contract evidence/regression-triage/contract/eval-v3.json
```

`eval` 会先核对数据、金标准和代码哈希，与合同不一致时拒绝运行；同一合同版本的同一拆分已有结果时也拒绝覆盖。
