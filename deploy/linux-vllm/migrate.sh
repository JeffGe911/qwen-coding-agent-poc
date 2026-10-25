#!/usr/bin/env bash
# Migration run: the same triage business flow against vLLM, compared with the Ollama baseline. Linux or WSL2 only.
# STATUS: written and syntax-checked (bash -n); NOT yet run on a Linux GPU host.
#
#   sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/migrate.sh dev       # acceptance, freeze <AFTER>, dev; stop for review
#   sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/migrate.sh holdout   # holdout once, then compare and report
#   sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/migrate.sh all       # dev, a mechanical pipeline gate, holdout, compare
#
# BEFORE (default eval-v3) is the frozen Ollama baseline contract; AFTER (default eval-v4) is frozen here for the
# vLLM profile deploy/backends/vllm-qwen7b-awq.json, so both freeze the same dataset, gold and code hashes. The gate
# between dev and holdout checks only that the pipeline works (no request failures, not every output invalid); it
# never looks at accuracy. Resources are sampled every 5 s; the eval is stopped if host memory runs low.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$(uname -s)" = Linux ] || { echo "Linux/WSL2 only" >&2; exit 2; }
[ "${QWEN_VLLM_CONFIRM:-}" = yes ] || { echo "this runs acceptance (stop/kill/recreate of qwen-vllm-poc) and model evaluations; re-run with QWEN_VLLM_CONFIRM=yes" >&2; exit 2; }
STEP=${1:?dev | holdout | all}
BEFORE=${BEFORE:-eval-v3}
AFTER=${AFTER:-eval-v4}
PROFILE=deploy/backends/vllm-qwen7b-awq.json
ENV_FILE=${ENV_FILE:-deploy/linux-vllm/.env}
PY=${PY:-python3}
MIN_RUN_FREE_MB=${MIN_RUN_FREE_MB:-1024}
EV=evidence/regression-triage
val() { sed -n "s/^$1=//p" "$ENV_FILE" | tr -d '\r' | tail -n 1; }
[ -r "$ENV_FILE" ] || { echo "$ENV_FILE missing (copy deploy/linux-vllm/env.7b-awq.example)" >&2; exit 2; }
[ "$(val MAX_MODEL_LEN)" = 8192 ] || { echo "MAX_MODEL_LEN in $ENV_FILE must be 8192 to match the baseline (ollama-r2)" >&2; exit 2; }
LOCAL_MODEL_API_KEY=$(val VLLM_API_KEY); export LOCAL_MODEL_API_KEY   # never printed; the profile reads it as a bearer key
[ -f "$EV/contract/$BEFORE.json" ] || { echo "baseline contract $BEFORE not found; run the Ollama baseline first" >&2; exit 2; }

sample() {  # sample DIR EVAL_PID: CSV every 5 s; stops the eval (only that pid) if available memory drops below the floor
  local dir=$1 pid=$2 cid
  cid=$(docker compose --env-file "$ENV_FILE" -f deploy/linux-vllm/compose.yaml ps -q vllm)
  echo "utc,mem_available_mb,gpu_used_mb,gpu_util_pct,container_mem" > "$dir/resources.csv"
  while kill -0 "$pid" 2>/dev/null; do
    local avail gpu
    avail=$(free -m | awk '/^Mem:/ {print $7}')
    gpu=$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits | head -1 | tr -d ' ')
    echo "$(date -u +%FT%TZ),$avail,$gpu,$(docker stats --no-stream --format '{{.MemUsage}}' "$cid" | tr ',' ';')" >> "$dir/resources.csv"
    if [ "$avail" -lt "$MIN_RUN_FREE_MB" ]; then echo "available memory $avail MB < $MIN_RUN_FREE_MB: stopping eval $pid" | tee "$dir/ABORTED"; kill "$pid"; fi
    sleep 5
  done
  awk -F, 'NR > 1 {if (min == "" || $2 < min) min = $2; if ($3 > max) max = $3} END {printf "{\"min_available_mb\": %d, \"max_vram_used_mb\": %d, \"samples\": %d}\n", min, max, NR - 1}' \
    "$dir/resources.csv" > "$dir/resources-summary.json"
}

run_split() {  # run_split SPLIT: rules and qwen under AFTER, with resource sampling around the qwen run
  local split=$1 dir=$EV/model-runs/$AFTER/$1
  mkdir -p "$dir"
  "$PY" -m regression_triage eval --contract "$EV/contract/$AFTER.json" --split "$split" --engine rules > "$dir/rules-stdout.txt"
  "$PY" -m regression_triage eval --contract "$EV/contract/$AFTER.json" --split "$split" --engine qwen > "$dir/eval-stdout.txt" 2>&1 &
  local pid=$!
  sample "$dir" "$pid" &
  local spid=$!
  local rc=0; wait "$pid" || rc=$?
  wait "$spid" || true
  echo "$split: eval exit $rc; $(cat "$dir/resources-summary.json")"
  [ ! -e "$dir/ABORTED" ] && [ "$rc" -eq 0 ]
}

gate() {  # the pipeline works: no request failures and at least one schema-valid answer (accuracy is not looked at)
  "$PY" - "$EV/results/$AFTER-qwen/dev/metrics.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
ok = m["request_failed"] == 0 and m["invalid_output"] < m["requests"]
print(f"gate: requests {m['requests']}, request_failed {m['request_failed']}, invalid_output {m['invalid_output']} -> {'pass' if ok else 'STOP'}")
sys.exit(0 if ok else 1)
PY
}

if [ "$STEP" = dev ] || [ "$STEP" = all ]; then
  bash deploy/linux-vllm/acceptance.sh                                  # 8 checks; ends on the known-good .env
  docker compose --env-file "$ENV_FILE" -f deploy/linux-vllm/compose.yaml up -d
  until curl -sf -m 5 http://127.0.0.1:"$(val HOST_PORT)"/health > /dev/null; do sleep 5; done
  "$PY" scripts/freeze_triage_contract.py "$AFTER" --engines rules,qwen --backend "$PROFILE" \
    --note "After migration: same code, prompt, dataset and gold as $BEFORE; backend vllm-qwen7b-awq (AWQ safetensors, not the GGUF of $BEFORE)."
  run_split dev
fi
if [ "$STEP" = all ]; then gate; fi
if [ "$STEP" = holdout ] || [ "$STEP" = all ]; then
  run_split holdout
  "$PY" scripts/compare_migration.py --before "$BEFORE" --after "$AFTER"
  "$PY" scripts/build_triage_report.py --contract "$EV/contract/$AFTER.json"
fi
grep -R -q -F "$LOCAL_MODEL_API_KEY" "$EV/model-runs/$AFTER" evidence/linux-serving 2>/dev/null && { echo "API key found in evidence; remove it before committing" >&2; exit 1; }
echo "done: $STEP"
