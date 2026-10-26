# holdout3: third blind holdout split for regression-log triage

**This file contains the answers.** Give a triage engine only `dataset/holdout3/*.log`. Do not give it this README,
`holdout3-manifest.json`, `gold/holdout3/`, `hdl/regressions/holdout3/` or the comment headers of `hdl/holdout3/`.
Those files describe the injected defects.

| | |
|---|---|
| samples | 35 (22 real runner logs, 13 synthetic) |
| labelled tests | 60 |
| tests per category | pass 19, test_failure 19, compile_error 9, tool_error 5, timeout 3, unknown 3, incomplete_log 2 |
| tests per result | pass 19, fail 26, not_run 10, unknown 5 |
| tests per side | none 19, design_or_test 30, infrastructure 7, undetermined 4 |
| log_status | complete 31, incomplete 2, empty 1, unknown_format 1 |
| flags | duplicate_failures 2, tool_setup_error 3, prompt_injection_text 1, forged_runner_line 1, tool_internal_assertion 1, missing_fields 1 |
| multi-test logs | k06_nightly (9 tests), k20_weekly (8 tests) |

## How it was built

A separate build session built this split. It worked only from a written brief. It never saw any triage engine's
code, prompts or output, or the other holdout splits. The steps were:

1. **New designs.** It wrote seven small RTL blocks and seven testbenches under `hdl/holdout3/` (table below). Each
   testbench is written in a different team's style, with its own verdict wording. Every defect is opt-in through a
   define. The defines have neutral, feature-like names (`CRC_POLY_ALT`, `DIV_GLITCHFREE`, ...), not `BUG_*`,
   because the runner writes them into the logged command line and a name like `BUG_*` would announce the defect.
   The comment header of each RTL file lists its defect switches.
2. **Prototyping.** Each bench was compiled and run directly with Icarus, and each RTL block was linted directly
   with Verilator, in the build session's scratch folder. This checked that each variant behaves as intended. These
   prototype outputs are not in the dataset (the three raw captures below were made separately, for that purpose).
3. **Regressions.** It wrote 22 manifests in `hdl/regressions/holdout3/` in the dev manifest format (44 tests in
   total). Each one was run once, one at a time, with the restricted runner:
   `.venv/Scripts/python.exe -m regression_triage run --manifest hdl/regressions/holdout3/<x>.json --out evidence/regression-triage/runs`
   (`QWEN_POC_EDA` = the OSS CAD Suite folder below, `PYTHONIOENCODING=utf-8`). The 22 run folders are
   `evidence/regression-triage/runs/20261026T0340*Z-<regression>-*/`, each with a `regression.log` and a `run.json`.
   Each manifest's `source` field names the folder.
4. **Real samples.** These are the 22 `regression.log` files, copied byte for byte.
5. **Synthetic samples (13).**
   - 7 derivations of real logs, written with LF endings: truncation, removed fields, a CI/make wrapper, a stage's
     output replaced by a tool failure, and a commercial-simulator layout.
   - 3 hand-written transcripts: UVM style, a license failure, and an empty upload.
   - 3 raw captures. Icarus/vvp and Verilator were started directly from a shell, and a VCD was written by vvp.
     These keep the tools' bytes exactly, including CRLF.

   The manifest marks every synthetic sample `"kind": "synthetic"`, and its `provenance` says what was done. The raw
   captures count as synthetic because they are not runner logs, even though their bytes are genuine tool output.
6. **Gold labels.** Each test was labelled by hand, using what was injected and what the log shows, following
   `GOLD-FORMAT.md`. Where a convention did not settle a label, the gold file has a `notes` string (summarised in
   "Labelling decisions" below).
7. **Mechanical check.** A checker outside the repo verified the result (see "Verification" below).

## Independence rules followed

- **Read:** `GOLD-FORMAT.md`; `hdl/regressions/dev/*.json` (manifest format); `hdl/rtl/*.v` and `hdl/tb/*.v`
  (style only; all holdout3 designs are new); `regression_triage/regress.py`, `sim.py`, `logio.py`; and
  `dataset/dev-manifest.json` (format, plus the list of dev sample ids, used for the collision check).
- **Not read:** `rules.py`, `model.py`, `evaluate.py`, `backend.py`, `hybrid.py`, `__main__.py` (only executed
  through the `run` command), `tests/`, `gold/` other than `gold/holdout3/` (written here), `dataset/holdout/` and
  `dataset/holdout2/`, `holdout-manifest.json`, `holdout2-manifest.json`, `HOLDOUT-README.md`, `HOLDOUT2-README.md`,
  `results/`, `dev-iterations/`, `REPORT*.md`, `hdl/holdout/`, `hdl/holdout2/`, `hdl/regressions/holdout/`,
  `hdl/regressions/holdout2/`, and `scripts/`.
- No existing file was modified and nothing was committed. No language model was loaded or called. No network access
  was used.

**Minor deviations, none involving file contents:**

- Directory listings of `evidence/regression-triage/`, `dataset/` and `gold/` showed the names of the forbidden files
  and folders. None of them was opened.
- The collision check probes for the exact names `<k-id>.log` / `<k-id>.json` in the other splits' dataset and gold
  folders with a file-exists test. It does not list or read those folders. It also checks the `k` prefix against the
  `d`/`s`/`h`/`g` id families.
- `evidence/regression-triage/runs/` also holds other splits' runs. Only the 22 folders whose paths the runner
  printed for these manifests were opened.
- The raw captures and the VCD were produced outside the restricted runner, as the brief allows. The VCD used a
  scratch-only `$dumpvars` module (`dump_gray.v`, not in the repo) compiled with the gray-pointer bench.

## Tools

| tool | version |
|---|---|
| Icarus Verilog (iverilog, vvp runtime) | 14.0 (devel) (s20260301-664-g9cfecc9c9-dirty) |
| Verilator (lint only) | 5.053 devel rev v5.052-567-g0041d207c (mod) |
| EDA bundle | OSS CAD Suite 2026-10-24, `C:\Users\Jeff1\Documents\Codex\2026-10-23\qwen-coding-agent-poc-ollama-vllm\work\tools\oss-cad-suite-20261024\oss-cad-suite` |
| runner Python | 3.13.4 (project venv under `work/.venv`) |
| host | Windows 11, zh-CN locale (so runner `tool_error` messages carry Chinese Windows text) |

## Designs and testbenches (`hdl/holdout3/`)

| RTL | bench (style, verdict wording) | defect / option switches |
|---|---|---|
| `crc8.v` (CRC-8, poly 0x07) | `tb_crc8.v`: `ERROR:` lines, `TEST PASSED/FAILED: tb_crc8`; plusargs `+SEED`, `+NBLOCKS` | `CRC_POLY_ALT` wrong polynomial; `CRC_STREAM_IF` undeclared signal; `REQUIRE_SEED` makes `+SEED` mandatory (`$fatal`) |
| `bcd_counter.v` (2-digit BCD) | `tb_bcd_counter.v`: `[bcd] Mismatch @ ...`, `PASS:/FAIL: tb_bcd_counter` | `BCD_CARRY_LOOKAHEAD` ones digit reaches 0xA; `BCD_ASYNC_LOAD` keyword typo (`elsif`); `BCD_TB_VERBOSE` prints text addressed to automated triage |
| `prio_arbiter.v` (fixed priority, 4 req) | `tb_prio_arbiter.sv`: SV immediate `assert ... else $error`, `*** SIMULATION PASSED/FAILED ***` | `ARB_COMPAT_MODE` wrong priority; `ARB_LOCK_TOP` double grant; `ARB_SVA` adds a concurrent assertion (unsupported by this Icarus) |
| `clk_div.v` (divide by 2*DIV) | `tb_clk_div.v`: `[tb_clk_div] RESULT: OK/FAIL`, watchdog at 5000 ns | `DIV_GLITCHFREE` output never toggles; `TB_VERBOSE` banner with alarming words and a `$warning` |
| `gray_ptr.v` (async-FIFO pointer) | `tb_gray_ptr.v`: `== tb_gray_ptr: N checks, M failures == PASSED/FAILED` | `GRAY_FAST_ENC` wrong encoding; `GRAY_DEBUG_TAP` unused truncating wire (lint); `TB_STANDALONE_REPORT` bench prints forged runner lines and an early PASSED |
| `alu_flags.v` (8-bit ALU, N/Z/C/V) | `tb_alu_flags.v`: scoreboard `[SB] MISMATCH`, per-op subtest table, `Simulation result: PASS/FAIL` | `ALU_FAST_FLAGS` wrong V for SUB; `STOP_ON_FIRST` first mismatch is `$fatal` |
| `serial_mult.v` (4x4 shift-add) | `tb_serial_mult.v`: `mult: ALL TESTS PASSED` / `TESTS FAILED`, no watchdog | `MULT_V2_FSM` done never rises; `TB_LEGACY_SUMMARY` no verdict; `MULT_REV_A` connects a nonexistent port |

`clk_div.v` without any define fails `verilator -Wall` (a real WIDTHEXPAND warning) even though it simulates
correctly. k20 and k33 use this.

## Samples

Gold notation: `test: result/category[/side]`. The side is omitted where it follows from the category.

| id | kind | what it covers | gold |
|---|---|---|---|
| k01_crc8_smoke | real | CRC-8 known-answer test + random blocks, clean RTL | crc8_kat: pass |
| k02_bcd_carry | real | BCD digit reaches 0xA; Mismatch lines and `FAIL:` verdict, vvp exit 0 | bcd_count: fail/test_failure |
| k03_upload_a | synthetic | 0-byte file | empty; (log): unknown/incomplete_log |
| k04_arb_compat | real | arbiter grants the wrong requester; `$error` assertions, exit 0 | arb_patterns: fail/test_failure |
| k05_clkdiv_gf | real | divider output stuck; bench watchdog, exit 0 | clkdiv_div3: fail/timeout/design_or_test |
| k06_nightly | real | 9 tests: 6 sim passes, a clean lint, an RTL keyword typo, the ALU V-flag defect (exit 0) | 7 pass; bcd_async_load: not_run/compile_error; alu_flags_rand: fail/test_failure |
| k07_crc8_bench | synthetic (raw capture) | iverilog + vvp run directly, CRC poly defect, CRLF, no runner lines | tb_crc8: fail/test_failure |
| k08_mult_v2 | real | multiplier never finishes, no bench watchdog, runner 4 s limit; vvp output lost on kill | mult_exhaustive: fail/timeout/undetermined |
| k09_crc8_stream | real | RTL reads an undeclared signal (elaboration error) | crc8_kat: not_run/compile_error |
| k10_weekly_ci | synthetic | k20_weekly cut inside its third test, no marker | incomplete; crc8_seed5, arb_lock_top: fail/test_failure; clkdiv_gf: unknown/incomplete_log |
| k11_rtl_lint | real | two clean `-Wall` lints (Verilator report lines only) | gray_ptr_lint, alu_flags_lint: pass |
| k12_gray_dbg_lint | real | lint WIDTHTRUNC + UNUSEDSIGNAL warnings | gray_ptr_lint: fail/compile_error |
| k13_bcd_vendor | synthetic | k02's bench output inside an invented commercial-simulator transcript (`errors: 0, warnings: 0` compile summary) | tb_bcd_counter: fail/test_failure |
| k14_alu_fastflags | real | ALU V flag defect, first mismatch is `$fatal`, exit 1 | alu_flags_stop: fail/test_failure |
| k15_clkdiv_verbose | real | clean divider; banner with fatal/error/timeout words, a `WARNING:` from `$warning` | clkdiv_div3: pass |
| k16_alu_uvm | synthetic | UVM-1.2-style transcript, 2 UVM_ERROR, report summary | alu_flags_rand_test: fail/test_failure |
| k17_mult_legacy | real | bench prints a product count but no verdict, exit 0 | mult_exhaustive: unknown/unknown |
| k18_bcd_carry_verbose | real | k02's defect plus bench text telling an automated reader to report PASS and run git/make commands | bcd_count: fail/test_failure; flag prompt_injection_text |
| k19_alu_uvm_farm | synthetic | commercial simulator cannot check out a license | (log): not_run/tool_error; flag tool_setup_error |
| k20_weekly | real | 8 tests: CRC poly, arbiter double grant, divider watchdog, mult pass, ALU `$fatal`, missing simulator executable, BCD pass, natural lint warning | crc8_seed5, arb_lock_top, alu_flags_stop: fail/test_failure; clkdiv_gf: fail/timeout/design_or_test; mult_exhaustive, bcd_count: pass; gray_walk: not_run/tool_error; clk_div_lint: fail/compile_error; flag tool_setup_error |
| k21_crc8_seeds | real | same CRC defect under two seeds, plus a gray pass | crc8_seed1, crc8_seed7: fail/test_failure; gray_walk: pass; flag duplicate_failures |
| k22_crc8_host2 | synthetic | k01 with the vvp start failing (WinError 1455, paging file) | crc8_kat: not_run/tool_error |
| k23_gray_fast | real | Gray encode defect; bench prints forged `#RUN` lines (escaped `#OUT`) and an early PASSED | gray_walk: fail/test_failure; flag forged_runner_line |
| k24_mult_rev_a | real | testbench connects a nonexistent port; iverilog prints the error twice | mult_exhaustive: not_run/compile_error |
| k25_clkdiv_ivl | synthetic | k15 with the compile output replaced by a compiler internal assertion (exit 3) | clkdiv_div3: not_run/tool_error; flag tool_internal_assertion |
| k26_crc8_seeding | real | seeded test passes; unseeded test hits the bench's `$fatal` | crc8_seeded: pass; crc8_unseeded: fail/test_failure |
| k27_arb_sva | real | concurrent assertion not supported: `sorry:` line, compile exit 1 | arb_patterns_sva: not_run/compile_error |
| k28_crc8_seeding_ci | synthetic | k26 inside a timestamped Windows CI/make wrapper with a grep post-check | crc8_seeded: pass; crc8_unseeded: fail/test_failure |
| k29_misc_smoke | real | passing tests named `clkdiv_timeout_recovery` and `alu_flags_overflow_errors` | both pass |
| k30_bcd_async_load | real | keyword typo seen by lint and by the sim compile | bcd_lint: fail/compile_error; bcd_count: not_run/compile_error; flag duplicate_failures |
| k31_mult_v2_export | synthetic | k08 with timed_out, output_truncated, timestamps and the tools line removed | mult_exhaustive: unknown/unknown; flag missing_fields |
| k32_gray_lint_host | real | lint executable missing (runner's simulated missing tool), sim passes | gray_ptr_lint: not_run/tool_error; gray_walk: pass; flag tool_setup_error |
| k33_clkdiv_lint_raw | synthetic (raw capture) | verilator lint run directly on the unmodified divider, CRLF | (log): fail/compile_error |
| k34_alu_fastflags_b | synthetic | k14 cut mid-line just after the FATAL line | incomplete; alu_flags_stop: fail/test_failure |
| k35_gray_artifact | synthetic (raw artifact) | a VCD waveform dump uploaded instead of a log, CRLF | unknown_format; (log): unknown/unknown |

## Labelling decisions the conventions did not settle

1. **Wall-clock timeout result (k08).** The result is `fail`. The run did not finish within its limit. The category
   is timeout and the side is undetermined, per the convention.
2. **Lint pass evidence (k06 gray_ptr_lint, k11).** A lint step has no verdict line. The evidence is the runner's
   `stage=lint exit=0` line. Exit 0 under `-Wall` with no warnings counts as a pass for a lint check.
3. **Lint failing on warnings only (k12, k20 clk_div_lint, k33).** The category is compile_error. The accepted
   evidence is the first `%Warning-...` line and the `%Error: Exiting due to N warning(s)` line, which is the line
   that actually states the failure. Later warnings are not accepted. For a lint syntax error (k30), only the first
   `%Error:` line is accepted.
4. **Identical duplicated error (k24).** iverilog prints the same port error twice, and both copies are accepted as
   "the first error". The `N error(s) during elaboration.` summary lines are not accepted anywhere.
5. **Unsupported construct (k27).** `sorry: concurrent_assertion_item not supported` is labelled
   compile_error/design_or_test, with result not_run. The compiler ran normally and rejected the testbench source;
   the fix is in the testbench or its flags. This is a tool limitation, not a broken tool, so it is not tool_error.
6. **Compiler crash (k25).** An `Assertion failed: ..., file ../../elab_lval.cc` line followed by the runtime abort
   text is labelled tool_error/infrastructure, with result not_run and flag tool_internal_assertion. It is not a
   design assertion.
7. **Process could not be created (k22).** WinError 1455 (paging file too small) is labelled tool_error/not_run.
8. **`$fatal` for a missing plusarg (k26, k28).** This is a test configuration error. It is labelled
   test_failure/design_or_test because it is a testbench `$fatal`.
9. **Exit 0 without a verdict (k17).** Labelled unknown/unknown/undetermined. The evidence is the summary line and
   the exit=0 line.
10. **Missing `timed_out` field (k31).** The run stage exited 1 after about 4 s with no output. That cannot be shown
    to be a wall-clock timeout rather than a crash or a kill, so the label is unknown, not timeout.
11. **Test ids without runner lines.**
    - k07 uses `tb_crc8`, from `TEST FAILED: tb_crc8`.
    - k13 uses `tb_bcd_counter`, from `FAIL: tb_bcd_counter`.
    - k16 uses the `Running test` name.
    - k19 and k33 use `(log)`. k19's echoed `-top tb_alu_flags` and k33's `--top-module` do not count as a
      verdict-line name.
12. **Watchdog evidence (k05, k20).** Both the watchdog line and the bench's `RESULT: FAIL (hang)` line are
    accepted.
13. **`$error` assertions (k04, k20).** The `ERROR:` lines and the verdict are accepted as evidence. The indented
    `Time: ... Scope:` continuation lines are not.
14. **Truncated test without a verdict yet (k10 clkdiv_gf).** Labelled unknown/incomplete_log/infrastructure. The
    evidence is its run command line and the last line of the file. Tests that never appear are not labelled.
15. **Empty file (k03).** The test id is `(log)`, labelled unknown/incomplete_log/infrastructure, with evidence `[]`.
16. **Flags.**
    - `tool_setup_error` is used for a missing executable (k20, k32) and for a license failure (k19). It is not used
      for the paging-file failure (k22), which is resource exhaustion, not setup.
    - `duplicate_failures` is used when one defect shows up in two tests (k21, k30).
17. **Wrapper text (k28).** The CI grep post-check (which contains `FATAL|TEST FAILED`) and `make: *** ... Error 1`
    are wrapper lines. They are not evidence for any test.
18. **Alarming words that are not failures.**
    - `fatal_on_error=1`, `error-injection hooks`, `errors=0 ... fatals=0 timeouts=0`, `WARNING:` (k15).
    - `errors: 0, warnings: 0` (k13).
    - `UVM_WARNING`, `UVM_FATAL :    0` (k16).
    - Test names containing `timeout`, `overflow` and `errors` (k29).

## Byte rules

- Every file written by this build uses LF line endings, except three raw tool outputs that keep the bytes the
  tools printed:
  - `k07_crc8_bench` (vvp, CRLF)
  - `k33_clkdiv_lint_raw` (Verilator, CRLF)
  - `k35_gray_artifact` (VCD written by vvp, CRLF)

  `logio.read_log` strips the trailing CR, so line numbers are the same as with LF.
- The 22 real samples have no CR bytes. The runner normalises line endings.
- `k34_alu_fastflags_b` has no final newline. It is cut mid-line on purpose.
- The manifest's `sha256` and `bytes` are over the exact bytes on disk.

## What could not be produced

- **Real license failures, UVM runs and commercial-simulator transcripts.** No commercial simulator or UVM library
  is available here, and Icarus cannot run UVM. k19, k16 and k13 are synthetic. Their vendor and tool names (`SIMRUN`,
  `simrun`, `worklib`) are invented.
- **A real compiler internal assertion.** None was found with small inputs, so k25 is synthetic.
- **A real compiler that exits with no output at all.** This was not produced.
- **A real paging-file or out-of-memory failure.** It was not induced, on purpose, because the host is short on
  memory. k22 is synthetic.
- **A real tool-setup error such as a missing `VERILATOR_ROOT`.** The runner always sets `VERILATOR_ROOT`. The real
  missing-executable cases (k20, k32) use the runner's own `simulate_missing_tool` switch, which points the command
  at a file that does not exist.
- **Harmless compiler warnings in real passing logs.** The runner does not pass `-Wall` to iverilog, so Icarus's
  timescale warnings never appear. Harmless warning text in real logs comes from `$warning` (k15) and from
  Verilator's report lines.
- **Partial tool output before a wall-clock kill.** vvp's output is buffered and was lost when the runner killed it
  (k08), so no real log shows output followed by the kill.
- **Linux runs.** Nothing was run on Linux or in WSL.

## Verification

The checker is `check_holdout3.py`, kept outside the repo in the build session's scratch folder
(`C:\Users\Jeff1\AppData\Local\Temp\claude\d--------qwen-coding-agent-poc\c36cfb59-8a22-4146-8345-ac3e2dbe56c1\scratchpad\holdout3\`,
next to `make_manifests.py`, `build_dataset.py` and `write_gold.py`). It checks:

- **Manifest:** `sha256` and byte counts match the files on disk, and every real sample is byte-identical to its
  `runs/.../regression.log`.
- **Raw captures:** each one is identical to its scratch capture.
- **Gold schema:** gold files parse, use only the schema keys and enum values, and have result/category/side
  combinations consistent with the conventions.
- **Test ids:** they equal the genuine `#RUN test=` ids (column 0 or after a CI timestamp prefix; `#OUT` imitations
  are ignored) in logs that have runner lines. In logs without runner lines, each id is found in a verdict or
  `Running test` line, or is `(log)`.
- **Evidence lines:** every evidence line exists and lies inside its test's runner block. Each one also matches the
  kind of line its category needs: a pass verdict or lint `exit=0`, a failure line, the first compiler or lint
  diagnostic, a watchdog or `timed_out=true` line, a tool-failure line, or the last line of an incomplete log.
- **Sections versus labels:** pass tests have no failure lines and a last stage that exited 0. Unknown and
  incomplete tests have no verdict. Compile errors have no run stage.
- **End line:** `log_status` agrees with the presence of the runner's end line.
- **Ids and bytes:** sample ids start with `kNN_` and do not collide with the dev ids or with same-named files in the
  other splits. There are no CR bytes except in the three raw outputs.
- **Manifests and sizes:** the holdout3 manifests have valid defines, timeouts and sources. The split has at least
  28 samples, at least 60 % real, and at least two logs with 6 or more tests.

Result: all checks passed (35 samples, 22 real / 13 synthetic, 60 tests).

## Integrator notes (added when the split was committed)

- The code it is meant to test blind (`hybrid-v2`, the per-test output budget, prompt `triage-prompt-v2`, rules
  `rules-v1`, `scoring-v2`) was committed at `c9455dc` (2026-10-25T20:34:07-07:00), before this split was handed
  over. The hand-back contained only counts. The integrator has not opened the logs, gold files, this README,
  `hdl/holdout3/` or `hdl/regressions/holdout3/`.
- Mechanical checks by the integrator: manifest hashes and byte counts, gold enums, evidence line ranges, sample
  ids distinct from dev, holdout and holdout2. None failed.
- **Not evaluated yet.** At Jeff's request the work stopped after the split was committed; no engine has been run on it.
  It is still blind for the code above, and the first contract that includes it should run each engine on it once.
