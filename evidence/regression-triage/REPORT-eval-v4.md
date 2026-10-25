# 仿真回归日志分诊：评测报告（合同 eval-v4）

> 本文件由 `scripts/build_triage_report.py` 根据冻结合同和 `results/` 下的原始结果生成，不要手改。合同冻结于 2026-10-25T21:34:11+00:00，代码提交 `d67d17a6bb`，冻结时代码有未提交改动：否。

## 0. 结论与分析（人工撰写）

**一句话**：在新的独立盲测集 holdout2（32 份日志，45 个测试）上，组合引擎（规则优先，规则判断不了时采用经过守卫的 Qwen）类别对了 **33/45**，Qwen v2 单独用对了 31/45，规则单独用对了 16/45。误放行：组合 **0** 次，Qwen 2 次，规则 0 次。代价是组合的漏报为 5/27，比 Qwen 单独用（3/27）多。原因在组合逻辑的两个缺口，以及一次输出被截断，见下文。

**哪些数字是盲测**
- **holdout2 是盲测**：它由另一个会话按书面任务说明编写和标注，交接时只给出数量。被测代码（prompt v2、hybrid-v1、scoring-v2、rules-v1）在交接之前已提交（`9a8476d`），合同 eval-v4 在任何运行之前冻结。每个引擎在 holdout2 上只跑了一次。
- **holdout（h\*）不是盲测**：prompt v2 和组合逻辑都是在看过 eval-v3 的 holdout 结果之后写的。它在这里的数字只作参考。
- **dev** 用来开发：`dev-iterations/prompt-v2-try1/` 保留了冻结前的那次尝试。

**holdout2（盲测）**

| | 规则 | Qwen v2 | 组合 |
|---|---|---|---|
| 类别正确 | 16/45 | 31/45 | **33/45** |
| **误放行** | 0 | **2** | **0** |
| 漏报需关注的测试 | 14/27 | 3/27 | 5/27 |
| 误报 | 0 | 0 | 0 |
| 给了具体类别但错了 | 4 | 7 | 6 |
| 答“不知道” / 没有作答 | 23 / 2 | 1 / 6 | 4 / 2 |
| 通过校验的引用 | 82/83 | 93/97 | 87/87 |
| 请求失败 / 输出不合规 | — | 0 / 1 | — |

**holdout（已看过，非盲测）**：组合 37/39，误放行 0，漏报 0/24；Qwen v2 35/39，误放行 1；规则 15/39。

**改动各自起了多大作用**
1. **prompt v2 只改了引用格式**：Qwen 通过校验的引用从 v1 的 7/63（eval-v3 holdout）升到 62/71（holdout）和 93/97（holdout2）。这是 v1 到 v2 唯一的改动，所以提升可以归到它头上。
2. **守卫（没有结论行不能判通过）**：holdout2 上挡下了 Qwen 的 1 次误放行（g18：没有结论行），holdout 上挡下了 1 次（h14）。Qwen 的另一次误放行（g23：日志被截断却报 pass），被规则自己的明确判断挡住了。**误伤 1 个真 pass**：g10 的 lint 通过时只打印统计信息，没有“pass”字样，守卫降了它的级。这个测试由规则判对了，组合结果没有受影响。lint 类测试需要另外的通过依据。
3. **规则优先**：holdout2 上 32 份日志里有 18 份需要模型（holdout 是 16/25）。也就是说，大约四成日志规则自己就够了，不必调用模型。

**组合引擎还错在哪里（holdout2，12 个测试）**
- **输出预算不够**（g13_nightly，6 个测试）：一份 6 个测试的夜间回归，Qwen 的回答写到 1200 token 被截断，被判为输出不合规。组合只能退回规则，其中 4 个测试规则答“不知道”。测试越多的日志，需要的输出预算越大，应该按测试数给预算，或者按测试拆开请求。
- **组合逻辑缺口一**（g15_ci_job，2 个测试）：在 CI 包装的日志里，规则一个测试都没识别出来，组合于是丢掉了 Qwen 判对的 2 个测试。规则一个测试都没报时，应该采用模型列出、并且确实出现在日志里的测试。
- **组合逻辑缺口二**（g26、g29，3 个测试）：规则判为“日志不完整”（结果是 unknown），但组合只在类别为 unknown 时才问模型，所以保留了规则的错误判断。“日志不完整”也是一种判断不了，同样应该交给模型。
- **watchdog 超时被判成测试失败**（g07、g22，以及 holdout 的 h09）：这是 Qwen 反复出现的错误，规则又不认识这些 testbench 的写法。g10 的 lint 失败也被判成了测试失败。

上面两处缺口是在盲测里暴露的。修好以后在 holdout2 上重新算，**就不能再叫盲测了**。如果只修这两处，事后估算组合能到 38/45（多对 5 个），这个数字只能当作“下一版要验证的假设”，要拿到盲测成绩需要第三个独立测试集。

**资源与服务**（笔记本单卡、单并发，不能外推到服务器）
- 一共 82 个模型请求（dev 25、holdout 25、holdout2 32），**0 个失败**，1 个输出不合规（g13，输出被截断）。
- 每个样本耗时的中位数约 4.5 s，生成速度中位数 89 tok/s；holdout2 合计 prompt 40,768 token、输出 9,314 token。
- 模型驻留时，即使 100% 在 GPU 上，主机可用内存也会少约 4 GB。holdout2 第一次启动时，模型还没卸载，预检因此拒绝运行。卸载后复查一次，通过了才启动（`model-runs/eval-v4/NOTE-holdout2-start.md`）。
- 全部跑完后已卸载模型（`/api/ps` 为空，显存 0 MiB）。

**结论**
- 规则加守卫后的 Qwen，在没见过的数据上做到了零误放行，类别准确率也是三者里最高的。这是目前最适合拿去试点的形态，但还不能直接交给工程师：
  - 输出预算问题和两处组合缺口要先修，并在新的独立测试集上重新验证；
  - 组合采用的模型判断都标注了“需复核”，复核时间必须计入试点的对比。

## 1. 代码与单元测试

`pytest`：168 passed in 39.07s

单元测试只说明代码行为符合预期（执行器限制、日志读取、引用校验、模型输出校验等），不代表分诊质量。

## 2. 分诊质量

dev 是开发规则和 prompt 时可以反复查看的拆分；holdout 由独立代理在看不到规则、prompt、评分代码和 dev 金标准的情况下编写和标注，每个合同版本、每个引擎只运行一次。看过 holdout 结果后再改规则或 prompt，就必须开新合同版本，且不能再称为盲测。

| 指标 | rules · dev | rules · holdout | rules · holdout2 | qwen · dev | qwen · holdout | qwen · holdout2 | hybrid · dev | hybrid · holdout | hybrid · holdout2 |
|---|---|---|---|---|---|---|---|---|---|
| 类别准确率 | 37/37 (100.0%) | 15/39 (38.5%) | 16/45 (35.6%) | 34/37 (91.9%) | 35/39 (89.7%) | 31/45 (68.9%) | 37/37 (100.0%) | 37/39 (94.9%) | 33/45 (73.3%) |
| 结果准确率（pass/fail/not_run/unknown） | 37/37 (100.0%) | 16/39 (41.0%) | 18/45 (40.0%) | 26/37 (70.3%) | 30/39 (76.9%) | 30/45 (66.7%) | 37/37 (100.0%) | 37/39 (94.9%) | 36/45 (80.0%) |
| 责任方准确率（设计或测试 / 基础设施） | 37/37 (100.0%) | 15/39 (38.5%) | 17/45 (37.8%) | 32/37 (86.5%) | 34/39 (87.2%) | 32/45 (71.1%) | 37/37 (100.0%) | 38/39 (97.4%) | 36/45 (80.0%) |
| 需关注测试（fail / not_run）precision | 25/25 (100.0%) | 11/11 (100.0%) | 13/13 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) | 25/25 (100.0%) | 24/24 (100.0%) | 22/22 (100.0%) |
| 需关注测试 recall | 25/25 (100.0%) | 11/24 (45.8%) | 13/27 (48.1%) | 24/25 (96.0%) | 24/24 (100.0%) | 24/27 (88.9%) | 25/25 (100.0%) | 24/24 (100.0%) | 22/27 (81.5%) |
| 引用有效率（文件、行号、原文都对得上） | 62/62 (100.0%) | 77/77 (100.0%) | 82/83 (98.8%) | 93/95 (97.9%) | 62/71 (87.3%) | 93/97 (95.9%) | 62/62 (100.0%) | 60/60 (100.0%) | 87/87 (100.0%) |
| 引用相关率（指向人工标注的证据行） | 61/62 (98.4%) | 36/77 (46.8%) | 40/83 (48.2%) | 67/95 (70.5%) | 53/71 (74.6%) | 66/97 (68.0%) | 61/62 (98.4%) | 54/60 (90.0%) | 60/87 (69.0%) |
| 至少有一条相关引用的测试 | 36/36 (100.0%) | 32/37 (86.5%) | 37/44 (84.1%) | 36/36 (100.0%) | 37/37 (100.0%) | 36/38 (94.7%) | 36/36 (100.0%) | 36/37 (97.3%) | 38/44 (86.4%) |
| unknown 比例（占金标准测试数） | 5.4% | 64.1% | 57.8% | 8.1% | 10.3% | 5.1% | 5.4% | 5.1% | 15.6% |
| 报告了日志中不存在的测试 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| 日志状态准确率（complete / incomplete / empty / unknown_format） | 100.0% | 84.0% | 87.5% | 92.0% | 92.0% | 90.3% | 100.0% | 92.0% | 93.8% |
| 特殊标记召回（注入、伪造标记、重复失败 …） | 100.0% | 40.0% | 62.5% | 0.0% | 0.0% | 0.0% | 100.0% | 40.0% | 62.5% |
| 全部样本类别准确率（未作答样本按错误计） | 100.0% | 38.5% | 35.6% | 91.9% | 89.7% | 68.9% | 100.0% | 94.9% | 73.3% |

### 各引擎的错误类型对比

### dev（37 个金标准测试）

| | 规则 | Qwen | 组合（规则 + 守卫后的 Qwen） |
|---|---|---|---|
| 类别正确 | 37/37 (100.0%) | 34/37 (91.9%) | 37/37 (100.0%) |
| 回答“不知道”（unknown） | 0/37 (0.0%) | 2/37 (5.4%) | 0/37 (0.0%) |
| **确信但错误**（给了具体类别且与金标准不同） | 0/37 (0.0%) | 1/37 (2.7%) | 0/37 (0.0%) |
| 没有作答（漏掉测试或整份日志调用失败） | 0/37 (0.0%) | 0/37 (0.0%) | 0/37 (0.0%) |
| **误放行**（没通过却报成 pass） | 0 | 1 | 0 |
| 误报（通过却报成 fail / not_run） | 0 | 0 | 0 |
| 漏报（需关注测试没被报为 fail / not_run） | 0/25 | 1/25 | 0/25 |
| 引用相关率（占给出的全部引用） | 61/62 (98.4%) | 67/95 (70.5%) | 61/62 (98.4%) |
| 被校验拒绝的引用 | 0 | 2 | 0 |
| 每样本耗时 中位数 / 最大（s） | 0.0001 / 0.0003 | 2.712 / 8.965 | 0.0003 / 0.001 |

逐个测试对照，规则 vs Qwen（类别是否正确）：

| | Qwen 对 | Qwen 错 |
|---|---|---|
| 规则对 | 34 | 3 |
| 规则错 | 0 | 0 |

只有Qwen对：无

只有规则对：s01_empty/(log), s02_truncated/fifo_full, s05_missing_fields/fifo_basic

逐个测试对照，规则 vs 组合（规则 + 守卫后的 Qwen）（类别是否正确）：

| | 组合（规则 + 守卫后的 Qwen） 对 | 组合（规则 + 守卫后的 Qwen） 错 |
|---|---|---|
| 规则对 | 37 | 0 |
| 规则错 | 0 | 0 |

只有组合（规则 + 守卫后的 Qwen）对：无

只有规则对：无

### holdout（39 个金标准测试）

| | 规则 | Qwen | 组合（规则 + 守卫后的 Qwen） |
|---|---|---|---|
| 类别正确 | 15/39 (38.5%) | 35/39 (89.7%) | 37/39 (94.9%) |
| 回答“不知道”（unknown） | 23/39 (59.0%) | 2/39 (5.1%) | 0/39 (0.0%) |
| **确信但错误**（给了具体类别且与金标准不同） | 1/39 (2.6%) | 2/39 (5.1%) | 2/39 (5.1%) |
| 没有作答（漏掉测试或整份日志调用失败） | 0/39 (0.0%) | 0/39 (0.0%) | 0/39 (0.0%) |
| **误放行**（没通过却报成 pass） | 0 | 1 | 0 |
| 误报（通过却报成 fail / not_run） | 0 | 0 | 0 |
| 漏报（需关注测试没被报为 fail / not_run） | 13/24 | 0/24 | 0/24 |
| 引用相关率（占给出的全部引用） | 36/77 (46.8%) | 53/71 (74.6%) | 54/60 (90.0%) |
| 被校验拒绝的引用 | 0 | 9 | 0 |
| 每样本耗时 中位数 / 最大（s） | 0.0001 / 0.0008 | 4.627 / 14.478 | 0.0003 / 0.0012 |

逐个测试对照，规则 vs Qwen（类别是否正确）：

| | Qwen 对 | Qwen 错 |
|---|---|---|
| 规则对 | 12 | 3 |
| 规则错 | 23 | 1 |

只有Qwen对：h01_cnt_pass_warnings/cnt_narrow_load, h01_cnt_pass_warnings/gray_exhaustive, h02_parity_misleading_pass/parity_fault_inject, h06_arb_lint_width/arb_lint, h08_gray_selfcheck_exit0/gray_exhaustive, h11_mixed/arb_fairness, h11_mixed/parity_modes, h11_mixed/shift_smoke, h12_cnt_duplicates/cnt_rand_s11, h12_cnt_duplicates/cnt_rand_s29, h12_cnt_duplicates/cnt_up_only, h12_cnt_duplicates/crc_smoke, h13_parity_injection/parity_modes, h15_cnt_forged_indent/cnt_forged, h16_raw_vvp_pass_warn/tb_updown, h21_truncated_mixed/parity_modes, h21_truncated_mixed/shift_smoke, h22_missing_fields/cnt_rand_s11, h22_missing_fields/cnt_rand_s29, h22_missing_fields/cnt_up_only, h22_missing_fields/crc_smoke, h23_ci_license_failure/(log), h24_vendor_style_compile/(log)

只有规则对：h14_shift_no_verdict/shift_smoke, h20_whitespace_only/(log), h21_truncated_mixed/crc_stop

逐个测试对照，规则 vs 组合（规则 + 守卫后的 Qwen）（类别是否正确）：

| | 组合（规则 + 守卫后的 Qwen） 对 | 组合（规则 + 守卫后的 Qwen） 错 |
|---|---|---|
| 规则对 | 15 | 0 |
| 规则错 | 22 | 2 |

只有组合（规则 + 守卫后的 Qwen）对：h01_cnt_pass_warnings/cnt_narrow_load, h01_cnt_pass_warnings/gray_exhaustive, h02_parity_misleading_pass/parity_fault_inject, h06_arb_lint_width/arb_lint, h08_gray_selfcheck_exit0/gray_exhaustive, h11_mixed/arb_fairness, h11_mixed/parity_modes, h11_mixed/shift_smoke, h12_cnt_duplicates/cnt_rand_s11, h12_cnt_duplicates/cnt_rand_s29, h12_cnt_duplicates/cnt_up_only, h12_cnt_duplicates/crc_smoke, h13_parity_injection/parity_modes, h15_cnt_forged_indent/cnt_forged, h16_raw_vvp_pass_warn/tb_updown, h21_truncated_mixed/parity_modes, h21_truncated_mixed/shift_smoke, h22_missing_fields/cnt_rand_s11, h22_missing_fields/cnt_rand_s29, h22_missing_fields/cnt_up_only, h23_ci_license_failure/(log), h24_vendor_style_compile/(log)

只有规则对：无

### holdout2（45 个金标准测试）

| | 规则 | Qwen | 组合（规则 + 守卫后的 Qwen） |
|---|---|---|---|
| 类别正确 | 16/45 (35.6%) | 31/45 (68.9%) | 33/45 (73.3%) |
| 回答“不知道”（unknown） | 23/45 (51.1%) | 1/45 (2.2%) | 4/45 (8.9%) |
| **确信但错误**（给了具体类别且与金标准不同） | 4/45 (8.9%) | 7/45 (15.6%) | 6/45 (13.3%) |
| 没有作答（漏掉测试或整份日志调用失败） | 2/45 (4.4%) | 6/45 (13.3%) | 2/45 (4.4%) |
| **误放行**（没通过却报成 pass） | 0 | 2 | 0 |
| 误报（通过却报成 fail / not_run） | 0 | 0 | 0 |
| 漏报（需关注测试没被报为 fail / not_run） | 14/27 | 3/27 | 5/27 |
| 引用相关率（占给出的全部引用） | 40/83 (48.2%) | 66/97 (68.0%) | 60/87 (69.0%) |
| 被校验拒绝的引用 | 0 | 4 | 0 |
| 每样本耗时 中位数 / 最大（s） | 0.0001 / 0.0005 | 4.471 / 23.514 | 0.0003 / 0.0009 |

逐个测试对照，规则 vs Qwen（类别是否正确）：

| | Qwen 对 | Qwen 错 |
|---|---|---|
| 规则对 | 9 | 7 |
| 规则错 | 22 | 7 |

只有Qwen对：g01_smoke/debounce_basic, g01_smoke/lfsr_seq, g01_smoke/pwm_duty, g02_debounce/debounce_glitch, g08_pwm_regfile/pwm_duty_chatty, g08_pwm_regfile/regfile_err_resp, g11_raw_prio/tb_prio_enc8, g14_debounce_notes/debounce_glitch, g15_ci_job/debounce_glitch, g15_ci_job/spi_loopback, g16_pwm/pwm_duty, g17_regfile_pair/regfile_b2b, g17_regfile_pair/regfile_rw, g17_regfile_pair/uart_tx_bytes, g21_prio_dbg/prio_enc_dbg, g24_regfile_byp/regfile_rw, g25_uvm_lfsr/lfsr_rand_test, g26_regfile_c/regfile_rw, g28_uart_warn/uart_tx_bytes, g29_mixed_b/prio_enc_exh, g29_mixed_b/pwm_duty, g31_build/uart_tx_bytes

只有规则对：g05_shard/(log), g12_tools/spi_loopback, g13_nightly/lfsr_taps_v2, g13_nightly/regfile_lint, g18_prio_phase/prio_enc_split, g23_uart_b/uart_tx_bytes, g27_raw_lint/(log)

逐个测试对照，规则 vs 组合（规则 + 守卫后的 Qwen）（类别是否正确）：

| | 组合（规则 + 守卫后的 Qwen） 对 | 组合（规则 + 守卫后的 Qwen） 错 |
|---|---|---|
| 规则对 | 16 | 0 |
| 规则错 | 17 | 12 |

只有组合（规则 + 守卫后的 Qwen）对：g01_smoke/debounce_basic, g01_smoke/lfsr_seq, g01_smoke/pwm_duty, g02_debounce/debounce_glitch, g08_pwm_regfile/pwm_duty_chatty, g08_pwm_regfile/regfile_err_resp, g11_raw_prio/tb_prio_enc8, g14_debounce_notes/debounce_glitch, g16_pwm/pwm_duty, g17_regfile_pair/regfile_b2b, g17_regfile_pair/regfile_rw, g17_regfile_pair/uart_tx_bytes, g21_prio_dbg/prio_enc_dbg, g24_regfile_byp/regfile_rw, g25_uvm_lfsr/lfsr_rand_test, g28_uart_warn/uart_tx_bytes, g31_build/uart_tx_bytes

只有规则对：无


## 3. 服务性能

规则引擎在本机进程内运行，耗时只是参考。模型耗时是笔记本单卡、单并发下测得的，不能外推到服务器吞吐。

| 引擎 · 拆分 | 调用次数 | 请求失败 | 输出不合规 | 未评分样本 | 总耗时 (s) | 平均每样本 (s) | prompt tokens | completion tokens |
|---|---|---|---|---|---|---|---|---|
| rules · dev | 25 | 0 | 0 | 0 | 0.003 | 0.0001 | — | — |
| rules · holdout | 25 | 0 | 0 | 0 | 0.004 | 0.0002 | — | — |
| rules · holdout2 | 32 | 0 | 0 | 0 | 0.004 | 0.0001 | — | — |
| qwen · dev | 25 | 0 | 0 | 0 | 86.824 | 3.4730 | 29197 | 7419 |
| qwen · holdout | 25 | 0 | 0 | 0 | 137.798 | 5.5119 | 38213 | 6792 |
| qwen · holdout2 | 32 | 0 | 1 | 1 | 187.882 | 5.8713 | 40768 | 9314 |
| hybrid · dev | 25 | 0 | 0 | 0 | 0.008 | 0.0003 | 0 | 0 |
| hybrid · holdout | 25 | 0 | 0 | 0 | 0.009 | 0.0004 | 0 | 0 |
| hybrid · holdout2 | 32 | 0 | 0 | 0 | 0.011 | 0.0003 | 0 | 0 |

## 4. 数据集

| 拆分 | 样本数 | 真实仿真运行 | 人工构造（synthetic） |
|---|---|---|---|
| dev | 25 | 17 | 8 |
| holdout | 25 | 19 | 6 |
| holdout2 | 32 | 23 | 9 |

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
- `h16_raw_vvp_pass_warn` / `tb_updown`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
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

## 5.3 逐样本：rules · holdout2

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| g01_smoke | real | ok | 0/3 | 0/3 | 0/3 | — | — | 9/3/9 | ✓ |
| g02_debounce | real | ok | 0/1 | 0/1 | 0/1 | debounce_glitch | — | 3/1/3 | ✓ |
| g03_prio_enc | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g04_regfile | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g05_shard | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| g06_lfsr | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g07_uart | real | ok | 0/1 | 0/1 | 0/1 | uart_tx_bytes | — | 3/1/3 | ✓ |
| g08_pwm_regfile | real | ok | 0/2 | 0/2 | 0/2 | — | — | 6/2/6 | ✓ |
| g09_spi | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g10_lint | real | ok | 1/2 | 1/2 | 1/2 | — | — | 3/2/3 | ✓ |
| g11_raw_prio | real | ok | 0/1 | 0/1 | 0/1 | tb_prio_enc8 | — | 0/0/0 | ✗ unknown_format |
| g12_tools | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g13_nightly | real | ok | 2/6 | 2/6 | 2/6 | pwm_duty, uart_tx_bytes | — | 14/6/14 | ✓ |
| g14_debounce_notes | real | ok | 0/1 | 0/1 | 0/1 | debounce_glitch | — | 3/1/3 | ✓ |
| g15_ci_job | synthetic | ok | 0/2 | 0/2 | 0/2 | debounce_glitch | — | 0/0/0 | ✗ unknown_format |
| g16_pwm | real | ok | 0/1 | 0/1 | 0/1 | pwm_duty | — | 3/1/3 | ✓ |
| g17_regfile_pair | real | ok | 0/3 | 0/3 | 0/3 | regfile_b2b, regfile_rw | — | 9/3/9 | ✓ |
| g18_prio_phase | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/2/3 | ✓ |
| g19_uart_tb | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g20_raw_pwm_build | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g21_prio_dbg | real | ok | 0/1 | 0/1 | 0/1 | — | — | 3/1/3 | ✓ |
| g22_spi_wdog | real | ok | 0/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g23_uart_b | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g24_regfile_byp | real | ok | 0/1 | 0/1 | 0/1 | regfile_rw | — | 3/1/3 | ✓ |
| g25_uvm_lfsr | synthetic | ok | 0/1 | 0/1 | 0/1 | lfsr_rand_test | — | 0/0/0 | ✗ unknown_format |
| g26_regfile_c | synthetic | ok | 0/1 | 0/1 | 0/1 | regfile_rw | — | 1/1/1 | ✓ |
| g27_raw_lint | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g28_uart_warn | real | ok | 0/1 | 0/1 | 0/1 | — | — | 3/1/3 | ✓ |
| g29_mixed_b | synthetic | ok | 0/2 | 0/2 | 0/2 | pwm_duty | — | 2/0/2 | ✗ incomplete |
| g30_sim_farm | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g31_build | synthetic | ok | 0/1 | 1/1 | 0/1 | — | — | 1/1/2 | ✓ |
| g32_job_summary | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |

错误明细：

- `g01_smoke` / `debounce_basic`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g01_smoke` / `pwm_duty`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g01_smoke` / `lfsr_seq`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g02_debounce` / `debounce_glitch`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g07_uart` / `uart_tx_bytes`：金标准 timeout/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g08_pwm_regfile` / `pwm_duty_chatty`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g08_pwm_regfile` / `regfile_err_resp`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g10_lint` / `pwm_lint`：金标准 compile_error/fail/design_or_test，预测 unknown/not_run/undetermined（category、result、side）
- `g11_raw_prio` / `tb_prio_enc8`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
- `g12_tools`：没有给出标记 tool_setup_error
- `g13_nightly` / `uart_tx_bytes`：金标准 timeout/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g13_nightly` / `lfsr_seq`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g13_nightly` / `pwm_duty`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g13_nightly` / `spi_loopback`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g14_debounce_notes` / `debounce_glitch`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g14_debounce_notes`：没有给出标记 prompt_injection_text
- `g15_ci_job` / `spi_loopback`：金标准 pass/pass/none，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `g15_ci_job` / `debounce_glitch`：金标准 test_failure/fail/design_or_test，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `g15_ci_job` / `(log)`：报告了日志中不存在的测试
- `g16_pwm` / `pwm_duty`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g17_regfile_pair` / `regfile_rw`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g17_regfile_pair` / `uart_tx_bytes`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g17_regfile_pair` / `regfile_b2b`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g21_prio_dbg` / `prio_enc_dbg`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g22_spi_wdog` / `spi_loopback`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g24_regfile_byp` / `regfile_rw`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g25_uvm_lfsr` / `lfsr_rand_test`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side；没有指向证据行的引用）
- `g26_regfile_c` / `regfile_rw`：金标准 test_failure/fail/design_or_test，预测 incomplete_log/unknown/infrastructure（category、result、side）
- `g28_uart_warn` / `uart_tx_bytes`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g29_mixed_b` / `prio_enc_exh`：金标准 pass/pass/none，预测 incomplete_log/unknown/infrastructure（category、result、side；没有指向证据行的引用）
- `g29_mixed_b` / `pwm_duty`：金标准 test_failure/fail/design_or_test，预测 incomplete_log/unknown/infrastructure（category、result、side；没有指向证据行的引用）
- `g30_sim_farm`：没有给出标记 tool_setup_error
- `g31_build` / `uart_tx_bytes`：金标准 tool_error/not_run/infrastructure，预测 unknown/not_run/undetermined（category、side）
- `g32_job_summary` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/undetermined（没有指向证据行的引用）

## 5.3 逐样本：qwen · dev

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| d01_all_pass | real | ok | 3/3 | 3/3 | 3/3 | — | — | 3/3/3 | ✓ |
| d02_compile_error | real | ok | 1/1 | 0/1 | 1/1 | — | — | 19/1/19 | ✓ |
| d03_selfcheck_fail_exit0 | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| d04_assert_fatal | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d05_watchdog_timeout | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| d06_wallclock_timeout | real | ok | 1/1 | 1/1 | 0/1 | — | — | 1/1/1 | ✓ |
| d07_mixed | real | ok | 4/4 | 3/4 | 4/4 | — | — | 5/4/5 | ✓ |
| d08_duplicates | real | ok | 3/3 | 3/3 | 3/3 | — | — | 5/5/5 | ✓ |
| d09_misleading_pass | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| d10_tool_missing | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| d11_lint_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| d12_injection_fail | real | ok | 1/1 | 1/1 | 1/1 | — | — | 9/9/9 | ✓ |
| d13_lint_error_configured | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| d14_raw_vvp_fail | real | ok | 1/1 | 1/1 | 1/1 | — | — | 9/9/9 | ✓ |
| d15_raw_iverilog_compile | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| d16_spoofed_markers | real | ok | 1/1 | 1/1 | 1/1 | — | — | 10/9/10 | ✓ |
| d17_tool_exec_failure | real | ok | 3/3 | 0/3 | 3/3 | — | — | 3/3/3 | ✓ |
| s01_empty | synthetic | ok | 0/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✓ |
| s02_truncated | synthetic | ok | 2/3 | 1/3 | 2/3 | fifo_full | — | 4/3/4 | ✗ complete |
| s03_unknown_format | synthetic | ok | 1/1 | 1/1 | 0/1 | — | — | 1/1/1 | ✓ |
| s04_uvm_style | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| s05_missing_fields | synthetic | ok | 1/2 | 1/2 | 1/2 | — | — | 3/2/3 | ✗ complete |
| s06_injection_json | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| s07_license_failure | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 2/2/2 | ✓ |
| s08_benign_error_words | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |

错误明细：

- `d02_compile_error` / `alu_basic`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `d02_compile_error`：没有给出标记 tool_internal_assertion
- `d06_wallclock_timeout` / `handshake_basic`：金标准 timeout/fail/undetermined，预测 timeout/fail/design_or_test（side）
- `d07_mixed` / `alu_syntax`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `d07_mixed`：没有给出标记 tool_internal_assertion
- `d08_duplicates`：没有给出标记 duplicate_failures
- `d10_tool_missing` / `alu_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `d11_lint_error`：没有给出标记 tool_setup_error
- `d12_injection_fail`：没有给出标记 prompt_injection_text
- `d15_raw_iverilog_compile` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `d16_spoofed_markers`：没有给出标记 forged_runner_line
- `d17_tool_exec_failure` / `alu_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `d17_tool_exec_failure` / `fifo_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `d17_tool_exec_failure` / `handshake_basic`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `s01_empty` / `(log)`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/none（category、side）
- `s02_truncated` / `alu_syntax`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `s02_truncated` / `fifo_full`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `s02_truncated`：没有给出标记 tool_internal_assertion
- `s03_unknown_format` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/none（side）
- `s05_missing_fields` / `fifo_basic`：金标准 unknown/unknown/undetermined，预测 pass/pass/none（category、result、side）
- `s05_missing_fields`：没有给出标记 missing_fields
- `s06_injection_json`：没有给出标记 prompt_injection_text
- `s07_license_failure` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）

## 5.4 逐样本：qwen · holdout

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| h01_cnt_pass_warnings | real | ok | 2/2 | 2/2 | 2/2 | — | — | 2/2/2 | ✓ |
| h02_parity_misleading_pass | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h03_cnt_undeclared | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| h04_gray_unknown_module | real | ok | 1/1 | 0/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h05_arb_bad_port | real | ok | 1/1 | 0/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h06_arb_lint_width | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| h07_crc_assert_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| h08_gray_selfcheck_exit0 | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| h09_arb_watchdog | real | ok | 0/1 | 1/1 | 1/1 | — | — | 3/2/3 | ✓ |
| h10_shift_wallclock | real | ok | 1/1 | 1/1 | 0/1 | — | — | 1/1/1 | ✓ |
| h11_mixed | real | ok | 5/5 | 4/5 | 5/5 | — | — | 7/7/7 | ✓ |
| h12_cnt_duplicates | real | ok | 4/4 | 4/4 | 4/4 | — | — | 6/6/6 | ✓ |
| h13_parity_injection | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| h14_shift_no_verdict | real | ok | 0/1 | 0/1 | 0/1 | — | — | 1/1/1 | ✓ |
| h15_cnt_forged_indent | real | ok | 1/1 | 1/1 | 1/1 | — | — | 5/5/5 | ✓ |
| h16_raw_vvp_pass_warn | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h17_raw_iverilog_multidriver | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| h18_raw_verilator_undeclared | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/1/3 | ✓ |
| h19_vcd_waveform | real | ok | 1/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✗ complete |
| h20_whitespace_only | synthetic | ok | 0/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✓ |
| h21_truncated_mixed | synthetic | ok | 3/4 | 3/4 | 3/4 | — | — | 5/5/5 | ✗ complete |
| h22_missing_fields | synthetic | ok | 4/4 | 4/4 | 4/4 | — | — | 8/6/8 | ✓ |
| h23_ci_license_failure | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h24_vendor_style_compile | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 3/3/3 | ✓ |
| h25_uvm_style_pass | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |

错误明细：

- `h03_cnt_undeclared` / `cnt_basic`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h04_gray_unknown_module` / `gray_exhaustive`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h05_arb_bad_port` / `arb_rotation`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h09_arb_watchdog` / `arb_rotation`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `h10_shift_wallclock` / `shift_drain`：金标准 timeout/fail/undetermined，预测 timeout/fail/design_or_test（side）
- `h11_mixed` / `shift_lvalue`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h12_cnt_duplicates`：没有给出标记 duplicate_failures
- `h13_parity_injection`：没有给出标记 prompt_injection_text
- `h14_shift_no_verdict` / `shift_smoke`：金标准 unknown/unknown/undetermined，预测 pass/pass/none（category、result、side）
- `h15_cnt_forged_indent`：没有给出标记 forged_runner_line
- `h17_raw_iverilog_multidriver` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h19_vcd_waveform` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/none（side）
- `h20_whitespace_only` / `(log)`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/none（category、side）
- `h21_truncated_mixed` / `shift_lvalue`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h21_truncated_mixed` / `crc_stop`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/undetermined（category、side）
- `h22_missing_fields`：没有给出标记 duplicate_failures, missing_fields
- `h23_ci_license_failure` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `h24_vendor_style_compile` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）

## 5.5 逐样本：qwen · holdout2

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| g01_smoke | real | ok | 3/3 | 3/3 | 3/3 | — | — | 6/3/6 | ✓ |
| g02_debounce | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g03_prio_enc | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| g04_regfile | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g05_shard | synthetic | ok | 0/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✓ |
| g06_lfsr | real | ok | 1/1 | 1/1 | 1/1 | — | — | 4/2/4 | ✓ |
| g07_uart | real | ok | 0/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g08_pwm_regfile | real | ok | 2/2 | 2/2 | 2/2 | — | — | 4/2/4 | ✓ |
| g09_spi | real | ok | 1/1 | 1/1 | 0/1 | — | — | 1/1/1 | ✓ |
| g10_lint | real | ok | 1/2 | 2/2 | 2/2 | — | — | 2/2/2 | ✓ |
| g11_raw_prio | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| g12_tools | real | ok | 0/1 | 0/1 | 0/1 | — | — | 2/1/2 | ✓ |
| g13_nightly | real | invalid_output | — | — | — | — | — | — | — |
| g14_debounce_notes | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| g15_ci_job | synthetic | ok | 2/2 | 2/2 | 2/2 | — | — | 4/3/4 | ✓ |
| g16_pwm | real | ok | 1/1 | 1/1 | 1/1 | — | — | 13/8/13 | ✓ |
| g17_regfile_pair | real | ok | 3/3 | 3/3 | 3/3 | — | — | 7/3/7 | ✓ |
| g18_prio_phase | real | ok | 0/1 | 0/1 | 0/1 | — | — | 2/1/2 | ✓ |
| g19_uart_tb | real | ok | 1/1 | 0/1 | 1/1 | — | — | 2/1/2 | ✓ |
| g20_raw_pwm_build | real | ok | 1/1 | 0/1 | 1/1 | — | — | 4/1/4 | ✓ |
| g21_prio_dbg | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g22_spi_wdog | real | ok | 0/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g23_uart_b | synthetic | ok | 0/1 | 0/1 | 0/1 | — | — | 2/1/2 | ✗ complete |
| g24_regfile_byp | real | ok | 1/1 | 1/1 | 1/1 | — | — | 8/8/8 | ✓ |
| g25_uvm_lfsr | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g26_regfile_c | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✗ complete |
| g27_raw_lint | real | ok | 0/1 | 0/1 | 0/1 | — | — | 2/2/2 | ✓ |
| g28_uart_warn | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g29_mixed_b | synthetic | ok | 2/2 | 2/2 | 2/2 | — | — | 8/8/8 | ✓ |
| g30_sim_farm | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g31_build | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g32_job_summary | synthetic | ok | 1/1 | 1/1 | 0/1 | — | — | 0/0/0 | ✗ incomplete |

错误明细：

- `g03_prio_enc` / `prio_enc_exh`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `g05_shard` / `(log)`：金标准 incomplete_log/unknown/infrastructure，预测 unknown/unknown/none（category、side）
- `g07_uart` / `uart_tx_bytes`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g09_spi` / `spi_soak`：金标准 timeout/fail/undetermined，预测 timeout/fail/design_or_test（side）
- `g10_lint` / `pwm_lint`：金标准 compile_error/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g12_tools` / `spi_loopback`：金标准 tool_error/not_run/infrastructure，预测 compile_error/fail/design_or_test（category、result、side）
- `g12_tools`：没有给出标记 tool_setup_error
- `g13_nightly`：模型调用 invalid_output，['output cut off: finish_reason=length at 1200 tokens (max_tokens 1200)']
- `g14_debounce_notes`：没有给出标记 prompt_injection_text
- `g16_pwm`：没有给出标记 forged_runner_line
- `g17_regfile_pair` / `uart_tx_bytes`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `g17_regfile_pair`：没有给出标记 duplicate_failures
- `g18_prio_phase` / `prio_enc_split`：金标准 unknown/unknown/undetermined，预测 pass/pass/none（category、result、side）
- `g19_uart_tb` / `uart_tx_v2`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `g20_raw_pwm_build` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `g22_spi_wdog` / `spi_loopback`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g23_uart_b` / `uart_tx_bytes`：金标准 incomplete_log/unknown/infrastructure，预测 pass/pass/none（category、result、side）
- `g27_raw_lint` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 compile_error/fail/design_or_test（category、result、side）
- `g27_raw_lint`：没有给出标记 tool_setup_error
- `g29_mixed_b`：没有给出标记 missing_fields
- `g30_sim_farm` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `g30_sim_farm`：没有给出标记 tool_setup_error
- `g31_build` / `uart_tx_bytes`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `g31_build`：没有给出标记 tool_internal_assertion
- `g32_job_summary` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/none（side；没有指向证据行的引用）

## 5.5 逐样本：hybrid · dev

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

## 5.6 逐样本：hybrid · holdout

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| h01_cnt_pass_warnings | real | ok | 2/2 | 2/2 | 2/2 | — | — | 2/2/2 | ✓ |
| h02_parity_misleading_pass | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h03_cnt_undeclared | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h04_gray_unknown_module | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h05_arb_bad_port | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h06_arb_lint_width | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| h07_crc_assert_error | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/3/3 | ✓ |
| h08_gray_selfcheck_exit0 | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| h09_arb_watchdog | real | ok | 0/1 | 1/1 | 1/1 | — | — | 3/2/3 | ✓ |
| h10_shift_wallclock | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h11_mixed | real | ok | 5/5 | 5/5 | 5/5 | — | — | 7/7/7 | ✓ |
| h12_cnt_duplicates | real | ok | 4/4 | 4/4 | 4/4 | — | — | 6/6/6 | ✓ |
| h13_parity_injection | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| h14_shift_no_verdict | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/3/3 | ✓ |
| h15_cnt_forged_indent | real | ok | 1/1 | 1/1 | 1/1 | — | — | 5/5/5 | ✓ |
| h16_raw_vvp_pass_warn | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h17_raw_iverilog_multidriver | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h18_raw_verilator_undeclared | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h19_vcd_waveform | real | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✗ complete |
| h20_whitespace_only | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| h21_truncated_mixed | synthetic | ok | 4/4 | 4/4 | 4/4 | — | — | 5/5/5 | ✓ |
| h22_missing_fields | synthetic | ok | 3/4 | 4/4 | 3/4 | — | — | 7/5/7 | ✗ incomplete |
| h23_ci_license_failure | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 1/1/1 | ✓ |
| h24_vendor_style_compile | synthetic | ok | 1/1 | 0/1 | 1/1 | — | — | 3/3/3 | ✓ |
| h25_uvm_style_pass | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/0/1 | ✓ |

错误明细：

- `h09_arb_watchdog` / `arb_rotation`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `h13_parity_injection`：没有给出标记 prompt_injection_text
- `h15_cnt_forged_indent`：没有给出标记 forged_runner_line
- `h22_missing_fields` / `crc_smoke`：金标准 unknown/unknown/undetermined，预测 incomplete_log/unknown/infrastructure（category、side）
- `h22_missing_fields`：没有给出标记 duplicate_failures
- `h23_ci_license_failure` / `(log)`：金标准 tool_error/not_run/infrastructure，预测 tool_error/fail/infrastructure（result）
- `h24_vendor_style_compile` / `(log)`：金标准 compile_error/not_run/design_or_test，预测 compile_error/fail/design_or_test（result）
- `h25_uvm_style_pass` / `arb_smoke_test`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）

## 5.7 逐样本：hybrid · holdout2

| 样本 | 来源 | 调用 | 类别 | 结果 | 责任方 | 漏报 | 误报 | 引用 有效/相关/总 | 日志状态 |
|---|---|---|---|---|---|---|---|---|---|
| g01_smoke | real | ok | 3/3 | 3/3 | 3/3 | — | — | 6/3/6 | ✓ |
| g02_debounce | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g03_prio_enc | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g04_regfile | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g05_shard | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✓ |
| g06_lfsr | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g07_uart | real | ok | 0/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g08_pwm_regfile | real | ok | 2/2 | 2/2 | 2/2 | — | — | 4/2/4 | ✓ |
| g09_spi | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g10_lint | real | ok | 1/2 | 2/2 | 2/2 | — | — | 2/2/2 | ✓ |
| g11_raw_prio | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| g12_tools | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g13_nightly | real | ok | 2/6 | 2/6 | 2/6 | pwm_duty, uart_tx_bytes | — | 14/6/14 | ✓ |
| g14_debounce_notes | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/1/2 | ✓ |
| g15_ci_job | synthetic | ok | 0/2 | 0/2 | 0/2 | debounce_glitch | — | 0/0/0 | ✓ |
| g16_pwm | real | ok | 1/1 | 1/1 | 1/1 | — | — | 13/8/13 | ✓ |
| g17_regfile_pair | real | ok | 3/3 | 3/3 | 3/3 | — | — | 7/3/7 | ✓ |
| g18_prio_phase | real | ok | 1/1 | 1/1 | 1/1 | — | — | 3/2/3 | ✓ |
| g19_uart_tb | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g20_raw_pwm_build | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g21_prio_dbg | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g22_spi_wdog | real | ok | 0/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g23_uart_b | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g24_regfile_byp | real | ok | 1/1 | 1/1 | 1/1 | — | — | 8/8/8 | ✓ |
| g25_uvm_lfsr | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g26_regfile_c | synthetic | ok | 0/1 | 0/1 | 0/1 | regfile_rw | — | 1/1/1 | ✓ |
| g27_raw_lint | real | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g28_uart_warn | real | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g29_mixed_b | synthetic | ok | 0/2 | 0/2 | 0/2 | pwm_duty | — | 2/0/2 | ✗ incomplete |
| g30_sim_farm | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 1/1/1 | ✓ |
| g31_build | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 2/2/2 | ✓ |
| g32_job_summary | synthetic | ok | 1/1 | 1/1 | 1/1 | — | — | 0/0/0 | ✗ incomplete |

错误明细：

- `g07_uart` / `uart_tx_bytes`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g10_lint` / `pwm_lint`：金标准 compile_error/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g12_tools`：没有给出标记 tool_setup_error
- `g13_nightly` / `uart_tx_bytes`：金标准 timeout/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g13_nightly` / `lfsr_seq`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g13_nightly` / `pwm_duty`：金标准 test_failure/fail/design_or_test，预测 unknown/unknown/undetermined（category、result、side）
- `g13_nightly` / `spi_loopback`：金标准 pass/pass/none，预测 unknown/unknown/undetermined（category、result、side）
- `g14_debounce_notes`：没有给出标记 prompt_injection_text
- `g15_ci_job` / `spi_loopback`：金标准 pass/pass/none，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `g15_ci_job` / `debounce_glitch`：金标准 test_failure/fail/design_or_test，预测 None/None/None（category、result、side；没有指向证据行的引用）
- `g15_ci_job` / `(log)`：报告了日志中不存在的测试
- `g17_regfile_pair` / `uart_tx_bytes`：金标准 pass/pass/none，预测 pass/pass/none（没有指向证据行的引用）
- `g22_spi_wdog` / `spi_loopback`：金标准 timeout/fail/design_or_test，预测 test_failure/fail/design_or_test（category）
- `g26_regfile_c` / `regfile_rw`：金标准 test_failure/fail/design_or_test，预测 incomplete_log/unknown/infrastructure（category、result、side）
- `g29_mixed_b` / `prio_enc_exh`：金标准 pass/pass/none，预测 incomplete_log/unknown/infrastructure（category、result、side；没有指向证据行的引用）
- `g29_mixed_b` / `pwm_duty`：金标准 test_failure/fail/design_or_test，预测 incomplete_log/unknown/infrastructure（category、result、side；没有指向证据行的引用）
- `g30_sim_farm`：没有给出标记 tool_setup_error
- `g32_job_summary` / `(log)`：金标准 unknown/unknown/undetermined，预测 unknown/unknown/undetermined（没有指向证据行的引用）

## 6. 冻结内容与复现

- 覆盖的引擎：rules、qwen、hybrid；规则版本 `rules-v1`
- prompt 版本 `triage-prompt-v2`，prompt+schema sha256 `20002b0f784833ce…`
- 后端 `ollama-r2`（ollama，`deploy/backends/ollama-r2.json`，sha256 `5bca08cac0c7…`）：Ollama 0.40.9, Windows portable build；模型 `qwen2.5-coder:7b`，权重 Ollama library qwen2.5-coder:7b，gguf Q4_K_M，digest `dae161e27b0e90dd…`；上下文 8192，max_tokens 1200，超时 180 s，并发 1，鉴权 none
- 请求中的采样参数 `{"temperature": 0}`；服务端实际生效 `{"temperature": 0, "top_p": 1.0, "top_k": 40, "repeat_penalty": 1.0, "min_p": 0.0, "decoder": "greedy"}`
- 代码哈希：`rules.py` 7834e0e764a8，`model.py` 290ea9c734b8，`evaluate.py` 904e11a54943，`logio.py` 773dbb123f6e，`__main__.py` 50defcbc714d，`backend.py` 1abb5a93772a，`hybrid.py` e006ee146133，`client.py` 2ef7c36704bd，`workflow.py` eefa9f9b1d7a，`policy.py` 98f066638f72

```
python -m regression_triage eval --contract evidence/regression-triage/contract/eval-v4.json --split dev --engine rules
python -m regression_triage eval --contract evidence/regression-triage/contract/eval-v4.json --split holdout --engine rules
python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v4.json --split dev
python scripts/triage_model_session.py --contract evidence/regression-triage/contract/eval-v4.json --split holdout --unload
python scripts/build_triage_report.py --contract evidence/regression-triage/contract/eval-v4.json
```

`eval` 会先核对数据、金标准和代码哈希，与合同不一致时拒绝运行；同一合同版本的同一拆分已有结果时也拒绝覆盖。
