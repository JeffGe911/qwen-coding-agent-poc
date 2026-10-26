# Local LLM for chip-verification workflows (PoC)

A small, single-machine proof of concept: a local Qwen2.5-Coder 7B, served on a laptop GPU, used for two chip-verification
chores. Every number below is computed from raw evidence in this repo, and failures are reported as failures.

1. **Regression-log triage**: read a simulation regression log, classify every test (pass, compile error, test failure,
   timeout, tool problem, incomplete log, unknown), cite the exact log lines, and suggest a next step. Suggestions are
   shown only; nothing is executed.
2. **Coding agent**: propose a one-file fix for a failing Python task. A person approves the proposal, and only then is it
   run against frozen tests in a restricted executor.

中文详细说明（含每一轮的过程、审批记录与排障）：[DETAILS.zh-CN.md](DETAILS.zh-CN.md)

## Results (measured)

**Log triage on an independently built blind set** (holdout2: 32 logs from real Icarus Verilog / Verilator runs plus
labelled synthetic cases, 45 tests). Built and labelled by a separate session that never saw the engines; the code was
frozen before it was handed over, and each engine ran on it once.

| Engine | Correct category | **False passes** | Missed failures | Valid citations |
|---|---|---|---|---|
| Rules only | 16 / 45 | 0 | 14 / 27 | 82 / 83 |
| Qwen 7B only | 31 / 45 | **2** | 3 / 27 | 93 / 97 |
| **Rules first, guarded Qwen where rules are unsure** | **33 / 45** | **0** | 5 / 27 | 87 / 87 |

- The rules never pass a failing test, but they only understand the verdict wording they were written for. On another
  team's testbenches they mostly answer "unknown".
- The model covers unfamiliar wording, but on logs with no verdict line it twice reported "pass". The guard enforces the
  rule in code instead of in the prompt: a pass must cite a verdict line, and the runner must have recorded a clean end
  of the run.
- **Coding agent:** a report-pass-rate bug was fixed after human approval, passing 21/21 tests, 12 of which were never
  shown to the model. A chip final-yield task was **not** fixed by 7B or 14B in any configuration tried: the best was
  7/22, against 4/22 for the original code.
- **Serving issues found from server logs:**
  - a 4K context silently truncated prompts (llama.cpp context shift) while the API still returned `stop`;
  - a 10× generation slowdown was the laptop running on battery under a 33 W GPU power cap.

## How results are kept honest

- **Frozen evaluation contracts.** Each contract freezes the SHA-256 of every log, every gold label and every code file
  on the request path, plus the model digest and all sampling settings. The evaluator refuses to run when anything
  differs, and refuses to re-run a split.
- **Blind holdouts.** Holdout splits are written and labelled by an independent session that cannot see the engines or
  the dev labels. A split tuned against stops being called blind. A third blind split, holdout3 (35 logs, 60 tests), is
  committed and has not been evaluated yet.
- **Checked citations.** A citation counts only if the file, the physical line number and the quoted text all match the
  log.
- **Hostile logs are covered.** The test logs include prompt injection, forged runner lines, exit code 0 with failures,
  harmless "error" words, empty and truncated files, and compiler crashes.
- **Explicit backends.** Endpoint, auth, timeout, context, output budget and every sampling field live in one profile per
  backend ([deploy/backends/](deploy/backends/)). The API is loopback-only, with no cloud fallback.

## Status

| Area | State |
|---|---|
| Local serving on Windows (Ollama, Qwen2.5-Coder 7B Q4_K_M, RTX 5070 Ti Laptop 12 GB) | Measured: release manifests, layered health checks, a config change with restore |
| Regression triage: rules, Qwen, hybrid; 4 dataset splits | Measured (reports: [eval-v4](evidence/regression-triage/REPORT-eval-v4.md), [eval-v3](evidence/regression-triage/REPORT-eval-v3.md)) |
| Hybrid v2 + per-test output budget (fixes found on holdout2) | Code and unit tests only; blind run on holdout3 pending |
| Linux + Docker + vLLM migration | **Not run.** Deployment kit, 8-check acceptance script and migration script are written and statically tested ([deploy/linux-vllm/](deploy/linux-vllm/)); WSL2 is installed on the laptop, nothing deployed |

Laptop numbers are single-user and single-GPU, and are not extrapolated to servers.

## Try it

```bash
python -m pip install -r requirements-lock.txt    # test dependencies; the code itself uses only the standard library
python -m pytest -q                               # unit and integration tests (simulator tests skip if it is absent)

# Rule-based triage of a bundled log: no model and no simulator needed
python -m regression_triage triage dataset/dev/d07_mixed.log --root evidence/regression-triage --out out --engine rules

# Rules + local model + hybrid, side by side (needs Ollama serving qwen2.5-coder:7b on 127.0.0.1:11437)
python -m regression_triage triage dataset/dev/d07_mixed.log --root evidence/regression-triage --out out --engine both

# End to end: run a mixed regression with Icarus Verilog, triage it, write a report pending review
# (needs OSS CAD Suite; point QWEN_POC_EDA at it)
python -m regression_triage demo --out out/demo
```

## Layout

| Path | What |
|---|---|
| `regression_triage/` | restricted simulator runner, rules, model client, guards and hybrid, scorer, report |
| `qwen_agent/`, `qwen_ops/` | coding agent with human approval; service operations (health, releases, log scan) |
| `hdl/` | small self-written RTL and testbenches with injected defects (no company data) |
| `evidence/` | raw run records, contracts, model responses, per-sample scores and generated reports |
| `deploy/` | backend profiles, release manifests, Linux/vLLM kit (not yet run) |
| [CEO_ONE_PAGER.md](CEO_ONE_PAGER.md) | one-page summary for a decision maker: results, limits, pilot plan, what to know before buying servers |
