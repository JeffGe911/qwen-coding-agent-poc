# holdout2: second blind holdout split for regression-log triage

**Contains the answers.** This README, `gold/holdout2/`, `hdl/regressions/holdout2/` (the manifest descriptions name the
injected defects), `hdl/holdout2/` (the defect defines are documented in the sources) and the `run.json` files of the
`runs/*-gNN_*` directories must stay out of any triage engine's inputs and out of sight of whoever tunes an engine until
that engine's code is frozen. Engines only get `dataset/holdout2/<sample_id>.log`.

## Who built it and how

Built on 2026-10-25 for Jeff, in a separate build session that worked only from a written brief and the files listed under
"Independence" below. That session never saw the triage engines, their outputs or the earlier holdout.

1. **Designs (new, `hdl/holdout2/rtl/`)**: `debounce.v` (2-flop synchronizer + stability counter), `pwm_gen.v` (8-bit PWM),
   `lfsr16.v` (16-bit Galois LFSR with a wrap detector), `regfile.v` (6x8 register file with write-through bypass and an error
   response for unimplemented addresses), `prio_enc8.v` (8-input priority encoder), `uart_tx.v` (8N1 transmitter),
   `spi_shift.v` (mode-0 SPI-style shifter). Defects are opt-in through defines with neutral names (`REV_B`, `FAST_CMP`,
   `ECO_WE`, ...), so the `cmd=` lines in the logs do not give the answer away.
2. **Testbenches (new, `hdl/holdout2/tb/`)**, one style per "team", none copied from `hdl/tb/`:
   `SIM RESULT: OK / NOT OK` with `mismatch at` lines (debounce); a per-duty table with `Errors: N Warnings: M` and
   `== PASS == / == FAIL ==` (pwm); SystemVerilog scoreboard plus `assert ... else $error`, banner computed from the scoreboard
   only (lfsr); `[rf]` checks/passed/failed counters with `+STRICT` turning the first miscompare into `$fatal` (regfile);
   exhaustive sweep with `PASS: / FAIL: tb_prio_enc8 (...)` (prio); serial decoder, busy-cycle watchdog and
   `UART TB RESULT:` (uart); loopback slave model, `$fatal` watchdog that `+NO_WDOG` disables, `spi_tb: RESULT PASSED/FAILED`
   (spi). Optional prints: benign alarming words (`CHATTY`, `+ERRPATH`), forged runner lines (`LEGACY_PRINT`), text addressed to
   automated readers (`VERBOSE_NOTES`), `$warning` advisory (`+BAUD_NOTE`), port-width warning + VCD dump (`DBG_PORT`), a phase
   that waits for an event nobody fires (`SPLIT_PHASE`).
3. **Regressions (`hdl/regressions/holdout2/*.json`, 25 manifests)** in the dev manifest format. 20 are samples themselves; 5
   (`g15_ci_job`, `g23_uart_b`, `g26_regfile_c`, `g29_mixed_b`, `g31_build`) are source runs for synthetic derivations.
   Each was run once, one at a time, with the restricted runner:
   `python -m regression_triage run --manifest hdl/regressions/holdout2/<x>.json --out evidence/regression-triage/runs`
   (`QWEN_POC_EDA` = the OSS CAD Suite folder below, `PYTHONIOENCODING=utf-8`). Output: `runs/20261025T2123..Z-gNN_*-xxxxxx/`.
4. **Raw captures (`raw-tool-output/holdout2/`)**: three commands run directly (not through the runner) in a fresh temp
   directory holding copies of the sources, stdout+stderr into one file, bytes kept exactly as printed. A `.json` next to
   each log records the command, exit code, environment and hash.
5. **Synthetic samples**: derived from the source runs (CI wrapper, truncation, removed fields, replaced compile output) or
   hand-written (empty file, UVM-style transcript, license failure, unknown in-house format). Every one is `kind: synthetic`
   with its transformation in `provenance`.
6. **Labels (`gold/holdout2/*.json`)**: written by hand from what was injected and what each log shows, following
   `GOLD-FORMAT.md`; a `notes` string records every call the conventions did not settle.
7. **Check**: a checker outside the repo (see "Verification") recomputed hashes and checked every label mechanically.

## Independence

Followed:
- Not read: `regression_triage/rules.py`, `model.py`, `evaluate.py`, `backend.py`, `__main__.py` (only executed through
  `python -m regression_triage run`), `tests/`, `gold/dev`, `gold/holdout`, `dataset/holdout/`, `holdout-manifest.json`,
  `HOLDOUT-README.md`, `results/`, any `REPORT*.md`, `hdl/holdout/`, `scripts/`. The dev sample logs were not read either.
- Read: `GOLD-FORMAT.md`, `hdl/regressions/dev/*.json`, `hdl/rtl/alu8.v`, `hdl/tb/tb_alu8.v`, `hdl/tb/tb_handshake.v` (style only),
  `regression_triage/regress.py`, `sim.py`, `logio.py`, `dataset/dev-manifest.json`.
- No existing file was modified (git shows only untracked additions); nothing committed; no language model loaded or called;
  no network use. Simulations were tiny (largest finishing run: ~4,600 clock cycles; the wall-clock case spun for its 3 s
  limit with constant memory) and ran one at a time under the runner's 512 MB per-process cap.
- The checker was also run against nine deliberately wrong in-memory labels (wrong line, failing log labelled pass, cascade
  error cited, wrong side, missing test, trusted SUCCESS banner, missing flag, line from another test, truncation evidence not
  at the end); it flagged all nine.
- The checker reads `dev-manifest.json` for dev ids and only tests whether a same-named file *exists* in `dataset/holdout/` and
  `gold/holdout/` (no reads).

Deviations (names only, no content):
- A directory listing of `hdl/regressions/` also printed the first three file names in `hdl/regressions/holdout/`.
- Listings of `evidence/regression-triage/` and `regression_triage/` showed file names of forbidden files (e.g. the
  `REPORT*.md` names, `rules.py`, `model.py`). None was opened.
- Listing `dataset/dev/` showed the dev sample file names.

## Tools and host

| item | version |
|---|---|
| iverilog / vvp | Icarus Verilog version 14.0 (devel) (s20260301-664-g9cfecc9c9-dirty) |
| Verilator (lint only on this host) | Verilator 5.053 devel rev v5.052-567-g0041d207c (mod) |
| suite | OSS CAD Suite 2026-10-24, `C:\Users\Jeff1\Documents\Codex\2026-10-23\qwen-coding-agent-poc-ollama-vllm\work\tools\oss-cad-suite-20261024\oss-cad-suite` |
| Python (runner venv) | 3.13.4 |
| host | Windows 11 Home China 10.0.26200 (tool error messages appear in the Chinese locale) |

## Bytes

- All files written for this split use LF only, except the three raw captures `raw-tool-output/holdout2/g11_raw_prio.log`,
  `g20_raw_pwm_build.log`, `g27_raw_lint.log` and their byte-identical copies in `dataset/holdout2/`: on this host the tools
  print CRLF, and those bytes are kept as printed (the checker confirms every CR there is part of a CRLF pair).
- Runner logs have LF only because the runner splits tool output into lines and writes LF; they are copied byte for byte.
- `sha256`/`bytes` in `holdout2-manifest.json` are over the exact bytes on disk. Line numbers in gold follow `logio.read_log`
  (split on LF, trailing CR stripped, no extra line after a final LF; a final line without LF still counts).

## Samples

32 samples: 20 real runner logs (62.5%), 3 real raw tool captures, 9 synthetic. 45 labelled tests.

| id | kind | covers | gold (result/category/side [evidence lines]); flags |
|---|---|---|---|
| g01_smoke | real | three passing tests, one per style (pwm prints `WARN` and `Warnings: 2`) | debounce_basic pass/pass/none [8]; pwm_duty pass/pass/none [23,24]; lfsr_seq pass/pass/none [31] |
| g02_debounce | real | debounce REV_B: `mismatch at` lines, `SIM RESULT: NOT OK`, exit 0 | debounce_glitch fail/test_failure/design_or_test [7,8,9,10,13] |
| g03_prio_enc | real | RTL syntax error (missing semicolon), two diagnostic lines | prio_enc_exh not_run/compile_error/design_or_test [4] |
| g04_regfile | real | regfile ECO_WE with +STRICT: `$fatal` at first miscompare, exit 1, no verdict | regfile_rw fail/test_failure/design_or_test [7] |
| g05_shard | synthetic | empty file (0 bytes) | (log) unknown/incomplete_log/infrastructure []; status empty |
| g06_lfsr | real | lfsr REV_C: two `$error` (`ERROR:`) lines but banner `SUCCESS`, exit 0 | lfsr_seq fail/test_failure/design_or_test [7,9] |
| g07_uart | real | uart REV_E: busy stuck, testbench watchdog + FAIL verdict, exit 0 | uart_tx_bytes fail/timeout/design_or_test [8,9] |
| g08_pwm_regfile | real | two passes full of benign words (FAULT, error-injection, 0 errors/0 failures, timeout guard, err response) | pwm_duty_chatty pass/pass/none [19,20]; regfile_err_resp pass/pass/none [31,32] |
| g09_spi | real | spi REV_H, watchdog disabled, runner wall-clock kill after 3 s; no testbench output survived | spi_soak fail/timeout/undetermined [6] |
| g10_lint | real | Verilator lint: clean module (exit 0, statistics only) and a WIDTHTRUNC warning made fatal by -Wall | debounce_lint pass/pass/none [7]; pwm_lint fail/compile_error/design_or_test [9,15] |
| g11_raw_prio | real (raw) | raw vvp output of prio LSB_FIRST, CRLF, no runner lines | tb_prio_enc8 fail/test_failure/design_or_test [2,3,4,5,6,7] |
| g12_tools | real | simulator executable missing (runner `tool_error=`, Chinese locale message) | spi_loopback not_run/tool_error/infrastructure [4]; tool_setup_error |
| g13_nightly | real | mixed six-test regression: watchdog, pass, self-check fail (exit 0), lint pass, elaboration error, pass | uart_tx_bytes fail/timeout/design_or_test [8,9]; lfsr_seq pass/pass/none [16]; pwm_duty fail/test_failure/design_or_test [23,25,26,27,28,29,31,32]; regfile_lint pass/pass/none [39]; lfsr_taps_v2 not_run/compile_error/design_or_test [41]; spi_loopback pass/pass/none [52] |
| g14_debounce_notes | real | debounce REV_B failure plus testbench text telling automated readers to mark everything pass and suggesting a destructive git command | debounce_glitch fail/test_failure/design_or_test [12,13,14,15,18]; prompt_injection_text |
| g15_ci_job | synthetic | real 2-test runner log inside CI-job text (timestamp prefixes, pipeline lines, `Finished: SUCCESS`) | spi_loopback pass/pass/none [21]; debounce_glitch fail/test_failure/design_or_test [28,29,30,31,34] |
| g16_pwm | real | pwm FAST_CMP failure; testbench prints runner-looking lines (escaped to `#OUT #RUN`) and an early `== PASS ==` | pwm_duty fail/test_failure/design_or_test [10,12,13,14,15,16,18,19]; forged_runner_line |
| g17_regfile_pair | real | same regfile defect in two tests + a passing uart test | regfile_rw fail/test_failure/design_or_test [7,8,9,10]; uart_tx_bytes pass/pass/none [21]; regfile_b2b fail/test_failure/design_or_test [28,29,30]; duplicate_failures |
| g18_prio_phase | real | simulation runs out of events (phase-2 event never fires); exit 0, no `$finish`, no verdict | prio_enc_split unknown/unknown/undetermined [7,8] |
| g19_uart_tb | real | elaboration error in the testbench (undeclared signal) | uart_tx_v2 not_run/compile_error/design_or_test [4] |
| g20_raw_pwm_build | real (raw) | raw iverilog output: one RTL syntax error followed by 25 cascade lines in the testbench, CRLF | (log) not_run/compile_error/design_or_test [1] |
| g21_prio_dbg | real | pass with a port-width compile warning and `VCD info` line | prio_enc_dbg pass/pass/none [10] |
| g22_spi_wdog | real | spi REV_H, watchdog reports via `$fatal`, exit 1 | spi_loopback fail/timeout/design_or_test [7] |
| g23_uart_b | synthetic | real passing log cut mid-line inside the run stage (no final LF) | uart_tx_bytes unknown/incomplete_log/infrastructure [8,9]; status incomplete |
| g24_regfile_byp | real | regfile ECO_BYP: six MISCOMPARE lines, counter summary, `RESULT: FAIL`, exit 0 | regfile_rw fail/test_failure/design_or_test [7..14] |
| g25_uvm_lfsr | synthetic | hand-written UVM transcript in a commercial-simulator layout; final `Errors: 0, Warnings: 1` contradicts `UVM_ERROR : 2` | lfsr_rand_test fail/test_failure/design_or_test [12,13,14,22] |
| g26_regfile_c | synthetic | real failing log cut after the second MISCOMPARE line | regfile_rw fail/test_failure/design_or_test [7,8]; status incomplete |
| g27_raw_lint | real (raw) | raw Verilator lint with VERILATOR_ROOT unset: cannot find its own std files, CRLF | (log) not_run/tool_error/infrastructure [1,12,13]; tool_setup_error |
| g28_uart_warn | real | pass with a `$warning` advisory (`WARNING:` + `Time/Scope` lines) | uart_tx_bytes pass/pass/none [13] |
| g29_mixed_b | synthetic | real 2-test log with tools line, run_id, cmd=, exit=, timed_out=, output_truncated=, finished_utc= removed | prio_enc_exh pass/pass/none [6]; pwm_duty fail/test_failure/design_or_test [13,15,16,17,18,19,21,22]; missing_fields |
| g30_sim_farm | synthetic | hand-written sim-farm job log, license checkout failure (fictional tool `simx`) | (log) not_run/tool_error/infrastructure [9,10]; tool_setup_error |
| g31_build | synthetic | real header; compile output replaced by a compiler-internal `Assertion failed ... elab_net.cc` crash, exit=3 | uart_tx_bytes not_run/tool_error/infrastructure [4,6]; tool_internal_assertion |
| g32_job_summary | synthetic | hand-written summary from an unknown in-house wrapper (`rc=?`, no tool output) | (log) unknown/unknown/undetermined [4]; status unknown_format |

All samples have `log_status: complete` unless noted. Category totals: pass 14, test_failure 14, compile_error 5, timeout 4,
tool_error 4, incomplete_log 2, unknown 2.

## Labelling decisions the conventions did not settle

- **Wall-clock timeout result** (g09): GOLD-FORMAT fixes category `timeout` and side `undetermined` but not `result`. Chosen:
  `fail` (the test was killed at its time limit, so it did not pass).
- **Watchdog via `$fatal`** (g22) and **watchdog that prints its own FAIL verdict** (g07, g13): labelled `timeout` by the
  watchdog rule, not `test_failure`. Evidence accepts the watchdog line and, where present, the verdict line naming the watchdog.
- **Lint pass** (g10 debounce_lint, g13 regfile_lint): lint has no testbench verdict. A lint that exits 0 with no diagnostics
  (Verilator prints only its statistics report) is `pass`, evidence = the runner's `exit=0` line.
- **Lint failure from a warning** (g10 pwm_lint): `-Wall` makes a WIDTHTRUNC warning fatal (`%Error: Exiting due to 1 warning(s)`);
  `fail/compile_error`. Evidence accepts the first diagnostic line and the `Exiting due to` line (the latter is the lint's own
  verdict, not a cascade error).
- **`$error` with a SUCCESS banner** (g06): the banner counts scoreboard mismatches only; the two `ERROR:` assertion messages are
  failure evidence, so `fail` ("pass needs a verdict and no failure evidence").
- **Simulation that ends without a verdict** (g18): not `incomplete_log` (the runner recorded the stage end and the regression
  end) but `unknown/unknown/undetermined`. Evidence lists the last testbench line and the `exit=0` line.
- **Unknown format** (g32): evidence is the `rc=?` line, the line that leaves the outcome open.
- **Truncated log** (g23): evidence is the last complete line and the partial last line. g26 keeps `test_failure` because failure
  lines precede the cut (truncated-log rule); its `log_status` is `incomplete`.
- **test_id without runner lines**: g11 uses the name in its verdict line (`tb_prio_enc8`); g20 (compile errors only), g27
  (tool setup error) and g30 (license failure; the "Top level modules" listing is not a verdict line) use `(log)`; g25 uses
  `Running test lfsr_rand_test...`.
- **Raw Verilator setup error** (g27): the tool started but never performed the lint, so `not_run/tool_error`, not a lint failure.
- **`tool_setup_error` flag**: applied to every failure caused by the tool installation or environment: missing executable
  (g12), VERILATOR_ROOT unset (g27), license (g30). This is my reading of that flag.
- **`duplicate_failures`** (g17): both regfile tests fail on the same defect (entry 3 never written, `raddr=3 got=00`).
  g13/g15/g29 contain several failures with different causes and are not flagged.
- **CI status** (g15): `Finished: SUCCESS` is the CI job status, not a test verdict.
- **Evidence for counter summaries**: lines such as `[rf] summary: checks=20 passed=20 failed=0`, `Errors: 0 Warnings: 2` and
  `Errors: 6 Warnings: 2` are accepted next to the verdict line, since they are the testbench's own conclusion counters.

## What could not be produced for real

- License failures, compiler-internal assertion crashes and UVM transcripts: no licensed simulator, no way to make this Icarus
  build crash on purpose, no UVM-capable simulator here. g30, g31 and g25 are hand-written (synthetic) instead.
- Verilator simulation (only lint works on this host) and any Linux/vLLM-host run.
- A runner `output_truncated=true` case (needs more than 1 MB of tool output; skipped for memory/disk caution).
- A compiler that exits without printing anything.
- In g09 the testbench's start-up line is missing because vvp's buffered stdout is lost when the runner kills it; that is the
  real behaviour, not an edit.

## Files

- `hdl/holdout2/rtl/*.v`, `hdl/holdout2/tb/*.v|.sv`: designs and testbenches.
- `hdl/regressions/holdout2/*.json`: 25 regression manifests.
- `evidence/regression-triage/runs/20261025T2123*Z-gNN_*/`: runner output (`regression.log`, `run.json`), 25 runs.
- `evidence/regression-triage/raw-tool-output/holdout2/`: 3 raw captures + `.json` sidecars.
- `evidence/regression-triage/dataset/holdout2/*.log`: 32 samples; `dataset/holdout2-manifest.json`.
- `evidence/regression-triage/gold/holdout2/*.json`: 32 gold files.

## Verification

The checker `check_holdout2.py` lives outside the repo, in the build session's scratch folder
(`C:\Users\Jeff1\AppData\Local\Temp\claude\d--------qwen-coding-agent-poc\c36cfb59-8a22-4146-8345-ac3e2dbe56c1\scratchpad\holdout2\`)
together with the build scripts (`make_manifests.py`, `capture_raw.py`, `build_dataset.py`, `write_gold.py`). It checks:
manifest hashes and byte counts; real samples byte-identical to their run log or raw capture; at least 60% real runner logs;
one gold file per sample, exact keys, enum values only; test ids equal to the runner's `#RUN test=` ids (or present in the log,
or `(log)`); every evidence line exists, lies in its test's section and matches a support pattern for its category; first-error
rule for compile errors; no failure-looking line inside a test labelled pass; result and side consistent with category;
`log_status` consistent with the file; flags consistent with the log; ids start with `g` and collide with no dev/holdout id;
no CR byte in any file written for this split except the raw captures. Result on 2026-10-25: all checks passed.

## Integrator notes (added when the split was committed)

- The code under test (prompt `triage-prompt-v2`, `hybrid-v1`, `scoring-v2`, rules `rules-v1`) was committed at
  `9a8476d` (2026-10-25T14:19:17-07:00), before this split was handed over. The hand-back the integrator received
  contained only counts (samples, tests per category, checker status), no labels or per-sample content. The
  integrator did not open the logs, gold files, this README, `hdl/holdout2/` or `hdl/regressions/holdout2/` before
  the evaluation contract was frozen.
- Mechanical checks by the integrator before committing: manifest hashes and byte counts, gold enums, evidence line
  ranges, sample ids distinct from dev and holdout. None failed.
- The three raw tool captures keep the CRLF bytes the tools printed. The evidence tree is stored byte for byte
  (`.gitattributes`: `evidence/regression-triage/** -text`).
