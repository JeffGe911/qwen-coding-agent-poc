# 仿真回归日志分诊：评测报告（合同 eval-v1）

> 本文件由 `scripts/build_triage_report.py` 根据冻结合同和 `results/` 下的原始结果生成，不要手改。合同冻结于 2026-10-24T19:07:13+00:00，代码提交 `0b7a85a176`，冻结时代码有未提交改动：否。

## 0. 结论与分析（人工撰写）

**一句话**：规则基线在自己的开发集上 37/37，在独立编写的 holdout 上类别只对了 15/39（38.5%）。它错得“安全”：24 个错误里 22 个是回答“不知道”（unknown），没有把通过的测试报成失败，也没有把失败报成通过。但覆盖面太窄，换一个项目的 testbench 写法就大面积失效。本地 Qwen 本轮**没有运行**（原因见下）。

**怎么读这两个数字**
- dev 的 37/37 不代表效果：规则和 dev 金标准出自同一人，规则就是照着这些日志写的。
- holdout 的 38.5% 是盲测数字：holdout 由另一个代理编写和标注，它看不到规则、prompt、评分代码和 dev 金标准。规则 `rules-v1` 在 holdout 交付前已提交（`45fbc3a`），评测合同 `eval-v1` 在运行前冻结。holdout 只跑了一次。

**错在哪里（holdout 39 个测试）**
- 15 个正确，22 个回答 unknown，1 个类别判断确实不同（h22/crc_smoke：规则判 `incomplete_log`/基础设施，金标准判 `unknown`/未定。两者都表示“没有结论”，分歧在于缺少结束记录算不算日志不完整），1 个测试没对上（h16：没有 runner 标记的原始 vvp 输出被判为 `unknown_format`）。
- 需关注测试（fail / not_run）的 precision 是 11/11，recall 是 11/24。规则报出来的问题都是真的，但漏掉了一半以上。
- 77 条引用全部有效（文件、行号、原文都对得上），但只有 36 条指向人工标注的证据行。回答 unknown 的测试引用的是附近的行。
- 唯一结论相反的情况：h06 的 lint 失败被判为 `not_run`，金标准是 `fail`。两者都算需关注，所以没有漏报。

**根因：结论词表是项目私有的**
规则只认识本仓库 dev testbench 的写法：行首的 `TEST PASSED` / `TEST FAILED`、`ERROR:` / `FATAL:` 前缀，而且只在 `ERROR` 行里找 watchdog。holdout 的 testbench 用的是 `RESULT: PASS  tb_updown`、`*** TEST PASSED ***`、`PASS: tb_parity`、`MISMATCH @3000`、`Simulation FAILED`、`parity check failed`、单独的 `WATCHDOG:` 行，规则一个都不认识。其余漏判：Verilator 的 `%Warning` 在 `-Wall` 下导致 lint 失败（h06）；商业仿真器风格的 `Error-[IND]`（h24）和 CI 包装里的许可证失败（h23）都被判为无法识别的格式。

真实公司里每个项目组的 testbench 写法都不同。所以：
1. 规则引擎不能直接拿到新项目上用。接入时要先由该项目的验证工程师声明结论词表（通过、失败、超时各用什么字样）。这一步必须写进试点计划。
2. “看不懂就说不知道”是这次唯一做对的地方：没有一个测试被错误地放行。失效时应该退化为“交给人看”，不能退化为“报告通过”。
3. 模型的潜在价值正好在这里，也就是读懂没见过的写法。但这只是假设，下一步必须用同一个 holdout 盲测验证。prompt `triage-prompt-v1` 在 holdout 出现之前就已提交（`3143a5d`），所以模型在 holdout 上仍然是盲测。

**安全相关样本**
- h13 的提示注入（`[ci-bot] Attention automated reviewers and LLM triage tools ... Classify this run as ...`）没有改变规则的判断，因为规则从不执行日志里的文字。但它也没有被标记出来：v1 的注入检测只认几种固定说法。
- h15 中缩进的伪造 `#RUN` 行没有被标记。v1 只认行首的伪造标记。runner 已在评测之后修复，缩进或带 BOM 的伪造行现在也会被转义（新增了测试）。但用于检测的规则仍是冻结的 v1，要到下一版才会跟上（`#OUT` 后面会保留原来的缩进）。

**本地 Qwen 为什么没跑**
2026-10-24 19:05Z 准备冻结合同时，11437 端口上的 Ollama 已不在运行：没有进程，没有监听。日志最后一行是约 06:47Z 的 `all slots are idle`，没有崩溃或退出记录，机器自 10-07 以来没有重启。退出原因**未查明**。没有擅自重启：是否启动、何时加载模型，要由 Jeff 根据内存情况决定。所以 `eval-v1` 只冻结了规则引擎，模型评测需要另开合同版本。

**下一步（均未做）**
1. 经 Jeff 同意后启动 r2，冻结 `eval-v2`（规则 + 模型，同一数据集），模型在 dev 上跑一次，在 holdout 上跑一次。
2. `rules-v2`：加入项目可配置的结论词表。因为是看过 holdout 之后改的，它在当前 holdout 上的分数不能叫盲测。要得到盲测分数，需要一个新的独立 holdout。

## 1. 代码与单元测试

`pytest`：156 passed in 29.40s

单元测试只说明代码行为符合预期（执行器限制、日志读取、引用校验、模型输出校验等），不代表分诊质量。

## 2. 分诊质量

dev 是开发规则和 prompt 时可以反复查看的拆分；holdout 由独立代理在看不到规则、prompt、评分代码和 dev 金标准的情况下编写和标注，每个合同版本、每个引擎只运行一次。看过 holdout 结果后再改规则或 prompt，就必须开新合同版本，且不能再称为盲测。

| 指标 | rules · dev | rules · holdout |
|---|---|---|
| 类别准确率 | 37/37 (100.0%) | 15/39 (38.5%) |
| 结果准确率（pass/fail/not_run/unknown） | 37/37 (100.0%) | 16/39 (41.0%) |
| 责任方准确率（设计或测试 / 基础设施） | 37/37 (100.0%) | 15/39 (38.5%) |
| 需关注测试（fail / not_run）precision | 25/25 (100.0%) | 11/11 (100.0%) |
| 需关注测试 recall | 25/25 (100.0%) | 11/24 (45.8%) |
| 引用有效率（文件、行号、原文都对得上） | 62/62 (100.0%) | 77/77 (100.0%) |
| 引用相关率（指向人工标注的证据行） | 61/62 (98.4%) | 36/77 (46.8%) |
| 至少有一条相关引用的测试 | 36/36 (100.0%) | 32/37 (86.5%) |
| unknown 比例（占金标准测试数） | 5.4% | 64.1% |
| 报告了日志中不存在的测试 | 0 | 1 |
| 日志状态准确率（complete / incomplete / empty / unknown_format） | 100.0% | 84.0% |
| 特殊标记召回（注入、伪造标记、重复失败 …） | 100.0% | 40.0% |
| 全部样本类别准确率（未作答样本按错误计） | 100.0% | 38.5% |

## 3. 服务性能

规则引擎在本机进程内运行，耗时只是参考。模型耗时是笔记本单卡、单并发下测得的，不能外推到服务器吞吐。

| 引擎 · 拆分 | 调用次数 | 请求失败 | 输出不合规 | 未评分样本 | 总耗时 (s) | 平均每样本 (s) | prompt tokens | completion tokens |
|---|---|---|---|---|---|---|---|---|
| rules · dev | 25 | 0 | 0 | 0 | 0.002 | 0.0001 | — | — |
| rules · holdout | 25 | 0 | 0 | 0 | 0.004 | 0.0002 | — | — |

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

## 6. 冻结内容与复现

- 覆盖的引擎：rules；规则版本 `rules-v1`
- 本合同只覆盖规则引擎，没有冻结模型设置；模型评测需要另一个合同版本。
- 代码哈希：`rules.py` 7834e0e764a8，`model.py` bc21052894be，`evaluate.py` 8bcd2719e254，`logio.py` 773dbb123f6e，`__main__.py` ffccb7898042

```
python -m regression_triage eval --contract evidence/regression-triage/contract/eval-v1.json --split dev --engine rules
python -m regression_triage eval --contract evidence/regression-triage/contract/eval-v1.json --split holdout --engine rules
python scripts/build_triage_report.py --contract evidence/regression-triage/contract/eval-v1.json
```

`eval` 会先核对数据、金标准和代码哈希，与合同不一致时拒绝运行；同一合同版本的同一拆分已有结果时也拒绝覆盖。
