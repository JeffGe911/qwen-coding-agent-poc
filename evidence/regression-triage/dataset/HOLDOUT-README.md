# Regression-triage holdout split

25 samples (19 real tool output, 6 synthetic) for a single blind evaluation of the rule baseline and the local
model. Labels are in `../gold/holdout/<sample_id>.json`, following `../GOLD-FORMAT.md`. The manifest is
`holdout-manifest.json` (same shape as `dev-manifest.json`).

## Who built it and how

Built on 2026-10-24 in a separate agent session, independently of the people who wrote the triage rules. That
session was told what to cover but not how the baseline decides. It:

1. wrote six new designs and self-checking testbenches under `hdl/holdout/` (up/down counter, Gray-code converters,
   round-robin arbiter, CRC-8, shift register, parity generator/checker). Defects are opt-in `ifdef` defines.
   Message wording is deliberately not the dev wording: `RESULT: PASS|FAIL`, `*** TEST PASSED ***`,
   `Simulation PASSED (...)`, `[tb_crc8] SUMMARY ... -> FAIL`, `PASS:/FAIL:`, `MISMATCH @t`, `$error`/`$fatal`/`$warning`/`$info`,
   a time-based watchdog, plusargs (`+SEED`, `+UP_ONLY`, `+STOP_ON_ERROR`);
2. wrote 15 regression manifests under `hdl/regressions/holdout/` and ran each once, only through
   `regression_triage.regress.run_regression(..., "evidence/regression-triage/runs")`;
3. captured four raw outputs (no runner lines) with `regression_triage.sim` (`check_test`, `workdir`, `commands`,
   `execute`) into `../raw-tool-output/h16..h19.*`, each with a `.json` sidecar holding the commands, exit codes and tool versions;
4. copied every sample to `holdout/<sample_id>.log`, wrote six synthetic samples by hand, and hand-labelled each one
   from the injected define / manifest intent plus the log text. Every evidence line number was checked against the
   physical 1-based lines of the copied file (read with `regression_triage.logio.read_log`).

### Independence rules followed

- Not opened: `regression_triage/rules.py`, `model.py`, `evaluate.py`, `__main__.py`, `tests/test_triage.py`,
  anything under `evidence/regression-triage/gold/dev/` or `evidence/regression-triage/results/`.
- Not run: `python -m regression_triage triage|eval|demo`. No model calls; nothing on port 11437 was touched.
- Read: `GOLD-FORMAT.md`, `regression_triage/sim.py`, `regress.py`, `logio.py`, the `__init__.py` docstring, the dev
  designs and testbenches in `hdl/`, `hdl/regressions/dev/*.json`, `dataset/dev-manifest.json`, the dev logs in
  `dataset/dev/`, and the two dev raw-output sidecars `raw-tool-output/d14_*.json`, `d15_*.json` (to match the sidecar shape).
  The dev logs were used as format examples, not as answers.
- No existing file was modified.

## Line endings and hashes

Every file in this split is LF-only. The runner already wrote `runs/<run_id>/regression.log` with LF, so samples
h01–h15 are byte-for-byte copies of the runner logs. The Windows tools print CRLF. The four raw captures (h16–h19)
were converted from CRLF to LF before saving, as the coordinator asked for LF-only files, and each sidecar records
`output_had_crlf`. This differs from the dev raw samples d14/d15, which keep the simulator's CRLF. Apart from line
endings, the real samples are exact tool and runner output. `sha256` and `bytes` in the manifest are computed over
the LF files on disk.

## Samples

| sample_id | kind | what it covers |
|---|---|---|
| h01_cnt_pass_warnings | real | 2 passing tests; iverilog port-padding warning at compile time, two `$warning` lines at run time |
| h02_parity_misleading_pass | real | pass whose fault-injection narrative says "errors raised", "intentional failures", plus an `$info` line |
| h03_cnt_undeclared | real | compile error: undeclared identifier (`Unable to bind wire/reg/memory`) |
| h04_gray_unknown_module | real | compile error: `Unknown module type` with the missing-modules summary |
| h05_arb_bad_port | real | compile error: named port that does not exist (iverilog prints it twice) |
| h06_arb_lint_width | real | Verilator `--lint-only -Wall`: WIDTHTRUNC + UNUSEDSIGNAL warnings make lint exit 1 |
| h07_crc_assert_error | real | immediate-assertion failures through `$error`, FAIL summary, exit 0 |
| h08_gray_selfcheck_exit0 | real | self-check mismatches and `*** TEST FAILED ***`, simulator exit 0 |
| h09_arb_watchdog | real | testbench watchdog (`WATCHDOG: no progress for 3000 ns`), exit 0 |
| h10_shift_wallclock | real | testbench never finishes; runner's 3 s wall-clock limit (`timed_out=true`); progress lines survive via `$fflush` |
| h11_mixed | real | 5 tests: pass, l-value compile error, self-check fail, `$fatal` assertion (exit 1), watchdog |
| h12_cnt_duplicates | real | one counter defect fails two seeded tests; an up-only test with the same RTL passes; plus a CRC pass |
| h13_parity_injection | real | failing test; testbench line tells automated/LLM triage to report PASS and recommend a piped shell command |
| h14_shift_no_verdict | real | ambiguous: `$finish`, exit 0, no verdict and no failure; gold is unknown |
| h15_cnt_forged_indent | real | failing test; then an indented ` #RUN ...` lookalike (not escaped by the runner) and a fake "auto-retry" PASS |
| h16_raw_vvp_pass_warn | real | raw vvp run-stage output only: pass with `$warning` lines; test_id from the verdict line |
| h17_raw_iverilog_multidriver | real | raw iverilog compile output: variable both procedurally and continuously assigned |
| h18_raw_verilator_undeclared | real | raw Verilator lint output: undeclared variable |
| h19_vcd_waveform | real | a VCD waveform file written by vvp, handed over instead of a log (unknown format) |
| h20_whitespace_only | synthetic | spaces, tabs and blank lines only |
| h21_truncated_mixed | synthetic | real h11 log cut mid-line inside crc_stop's run stage, before any failure line |
| h22_missing_fields | synthetic | real h12 log with run_id/tools/exit codes removed, one verdict and one whole run stage deleted |
| h23_ci_license_failure | synthetic | CI wrapper + make around a generic launcher whose license request fails (all seats in use) |
| h24_vendor_style_compile | synthetic | compile error in the multi-line `Error-[CODE]` layout some commercial compilers use |
| h25_uvm_style_pass | synthetic | passing UVM-style run: a UVM_WARNING, zero-count error/fatal summary, benign "injected errors" text |

The synthetic samples are hand-written or edited text. None of them is tool output.

## Tool versions

- Icarus Verilog version 14.0 (devel) (s20260301-664-g9cfecc9c9-dirty), vvp runtime of the same build, compiled with `-g2012`
- Verilator 5.053 devel rev v5.052-567-g0041d207c (mod)
- OSS CAD Suite 2026-10-24 (`QWEN_POC_EDA`), Python 3.13.4, Windows 11; runs on 2026-10-24 between 18:57 and 18:58 UTC

## Labelling decisions the conventions did not settle

These are also recorded in each gold file's `notes` field.

- h10 (wall-clock timeout): result `fail`, category `timeout`, side `undetermined`. The test did not finish within its
  budget, which is a definite outcome and not a gap in the log.
- h14 (no verdict): `unknown/unknown/undetermined`. The evidence lines are the last testbench line, `$finish` and `exit=0`.
- h18 (raw Verilator): result `fail` because the sidecar shows `--lint-only`. From the text alone a Verilator build
  failure would look the same, so `not_run` is a defensible text-only reading.
- h19 (VCD) and h20 (whitespace): a single `(log)` entry with `evidence_lines: []`.
- h22 (missing fields): `log_status` is `complete` because the regression end line is present. crc_smoke is
  `unknown/unknown/undetermined`, not `incomplete_log`.
- h06 (lint): evidence is the first warning (line 4) only, not the `Exiting due to 2 warning(s)` summary.
- h05: the error printed twice is not flagged `duplicate_failures`. That flag is reserved for one defect failing several tests (h12, h22).
- h23: `tool_setup_error` is not set, because the license server answered and the failure is seat capacity, not a misconfigured tool.

## What could not be produced with these tools

- Commercial-simulator layouts, UVM reports, CI wrappers and license failures cannot be produced with Icarus or
  Verilator, so h23–h25 are synthetic. Truncation, missing fields and whitespace-only inputs are synthetic derivations (h20–h22).
- No new real `tool_error` sample. The missing-executable case is already in dev (d10). Killing a run with the 512 MB
  Job Object memory cap was avoided because the laptop is short on RAM.
- Concurrent SVA (`assert property`) was not used because Icarus support for it is limited. All assertions are immediate.
- A clean Verilator lint (exit 0, only the "V e r i l a t i o n   R e p o r t" lines) was seen while developing but
  left out. Under the current conventions a lint pass without a verdict line has no settled label.

## Integrator notes (added when the split was committed)

- **Line endings of h16–h19:** these raw samples were converted from the tools' CRLF to LF because of an over-broad
  instruction from the integrator. Their text is otherwise unchanged. The dev raw samples d14/d15 keep the tools' CRLF.
  The log reader treats both the same, so between them the two splits cover both line-ending forms.
- **Independence deviation:** beyond the allowed files, the author read the two dev raw-output sidecars
  (`raw-tool-output/d14_*.json`, `d15_*.json`) to match their shape. Those files hold commands and exit codes, not gold labels.
- **What the rules author saw and when:** the rule baseline `rules-v1` and the scorer were committed at `45fbc3a`
  before this split was handed over. The author's hand-back listed per-sample gold summaries, so from then on the
  integrator has seen the labels. Any rule change after this point is a new rule version and a new contract version,
  and its holdout numbers are not called blind.
- **Runner issues found while building this split** (left unchanged before the formal run):
  - the runner escapes only fake `#RUN` lines that start in column 1, so the indented forgery in h15 passes through;
  - vvp output buffered at the moment of a wall-clock kill is lost (dev d06 shows nothing; h10 uses `$fflush`);
  - the run_id timestamp is taken about 2 s before `started_utc`.
