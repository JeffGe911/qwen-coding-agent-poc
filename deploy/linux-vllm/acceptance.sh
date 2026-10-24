#!/usr/bin/env bash
# Acceptance checks for the single-host vLLM deployment (deploy/linux-vllm/compose.yaml). Linux or WSL2 only.
# STATUS: written and syntax-checked (bash -n); NOT yet run on a Linux GPU host.
#
#   sudo QWEN_VLLM_CONFIRM=yes bash deploy/linux-vllm/acceptance.sh
#
# Steps (each output saved raw, API key filtered, under evidence/linux-serving/<host>-<utc>/):
#   0 preflight: free RAM, GPU already in use (Ollama loaded?), image digest present, .env readable
#   1 start, model load, a real chat completion           5 concurrency 1/2/4 with TTFT, queueing (num_requests_waiting)
#   2 /health, /metrics, /version, /v1/models with and    6 short, long and over-budget inputs (prompt beyond max-model-len,
#     without the key: which paths answer                   max_tokens beyond what fits)
#   3 served name, max_model_len, limits = .env           7 stop -> detected -> start; crash (SIGKILL main pid) -> restart policy
#   4 GPU memory before/after, KV-cache lines in the log  8 config change (MAX_MODEL_LEN/MAX_NUM_SEQS) and rollback to .env
# Touches only the compose project qwen-vllm-poc. Never prints the API key; never run with bash -x.
set -euo pipefail
cd "$(dirname "$0")/../.."
[ "$(uname -s)" = Linux ] || { echo "Linux/WSL2 only" >&2; exit 2; }
[ "${QWEN_VLLM_CONFIRM:-}" = yes ] || { echo "this stops, kills and recreates the qwen-vllm-poc container; re-run with QWEN_VLLM_CONFIRM=yes" >&2; exit 2; }

ENV_FILE=${ENV_FILE:-deploy/linux-vllm/.env}
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/linux-vllm/compose.yaml)
MIN_FREE_MB=${MIN_FREE_MB:-5000}
MAX_GPU_USED_MB=${MAX_GPU_USED_MB:-1500}
PY=${PY:-python3}
[ -r "$ENV_FILE" ] || { echo "$ENV_FILE missing (copy env.example)" >&2; exit 2; }
val() { sed -n "s/^$1=//p" "${2:-$ENV_FILE}" | tr -d '\r' | tail -n 1; }
KEY=$(val VLLM_API_KEY)
[[ $KEY =~ ^[0-9a-f]{32,128}$ ]] || { echo "VLLM_API_KEY must be hex" >&2; exit 2; }
export LOCAL_MODEL_API_KEY=$KEY            # qwen_ops sends it as a Bearer token
PORT=$(val HOST_PORT); PORT=${PORT:-18000}
MODEL=$(val SERVED_MODEL_NAME); MODEL=${MODEL:-qwen-local}
LEN=$(val MAX_MODEL_LEN); LEN=${LEN:-4096}
BASE=http://127.0.0.1:$PORT
EVID=evidence/linux-serving/$(hostname -s 2>/dev/null || hostname)-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$EVID"
TMP=$(mktemp -d); chmod 700 "$TMP"; trap 'rm -rf "$TMP"' EXIT
(umask 077; printf 'Authorization: Bearer %s\n' "$KEY" > "$TMP/auth")
N=0; FAILS=0
redact() { sed -u "s/$KEY/[REDACTED]/g"; }
rec() {  # rec NAME CMD... : raw output -> NN-NAME.out; never aborts
  N=$((N + 1)); local name; name=$(printf '%02d-%s' "$N" "$1"); shift
  { printf '%s %s:' "$(date -u +%FT%TZ)" "$name"; printf ' %q' "$@"; echo; } | redact >> "$EVID/commands.log"
  local t0=$SECONDS rc=0
  "$@" > >(redact > "$EVID/$name.out") 2>&1 || rc=$?
  sleep 0.2
  printf '%s\trc=%s\t%ss\n' "$name" "$rc" "$((SECONDS - t0))" | tee -a "$EVID/commands.log"
  return 0
}
check() {  # check LABEL CONDITION...
  if "${@:2}"; then printf 'PASS\t%s\n' "$1" | tee -a "$EVID/summary.tsv"; else printf 'FAIL\t%s\n' "$1" | tee -a "$EVID/summary.tsv"; FAILS=$((FAILS + 1)); fi
}
api() { curl -sS -m "${2:-60}" -H @"$TMP/auth" -H 'Content-Type: application/json' "${@:3}" "$BASE$1"; }
chat() { api /v1/chat/completions "${2:-300}" -d "{\"model\":\"$MODEL\",\"temperature\":0,\"max_tokens\":${3:-64},\"messages\":[{\"role\":\"user\",\"content\":$1}]}"; }
wait_healthy() {
  local t0=$SECONDS
  until curl -sf -m 5 "$BASE/health" >/dev/null; do
    [ $((SECONDS - t0)) -lt "${1:-900}" ] || return 1
    sleep 5
  done
  echo "healthy after $((SECONDS - t0)) s"
}
gpu_used() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d ' '; }
container() { "${COMPOSE[@]}" ps -q vllm; }

# 0 preflight: report and stop instead of freeing resources ourselves
rec preflight-free free -m
rec preflight-gpu nvidia-smi
rec preflight-image docker image inspect --format '{{json .RepoDigests}} {{.Size}}' "$(val VLLM_IMAGE)"
rec preflight-compose "${COMPOSE[@]}" config --quiet
free_mb=$(free -m | awk '/^Mem:/ {print $7}')
used_mb=$(gpu_used)
check "preflight: available RAM ${free_mb} MB >= ${MIN_FREE_MB} MB" test "$free_mb" -ge "$MIN_FREE_MB"
check "preflight: GPU memory already used ${used_mb} MiB <= ${MAX_GPU_USED_MB} MiB (Ollama must be idle or stopped by the operator)" test "$used_mb" -le "$MAX_GPU_USED_MB"
if [ "$FAILS" -gt 0 ]; then echo "preflight failed: not starting vLLM. See $EVID/summary.tsv" >&2; exit 1; fi

# 1 start, load, real request
rec up "${COMPOSE[@]}" up -d
rec wait-healthy wait_healthy 900
rec chat-short chat '"Reply with the single word READY."'
check "1 real chat completion answers" grep -q '"choices"' "$EVID/$(printf '%02d' "$N")-chat-short.out"
rec gpu-after-load nvidia-smi --query-gpu=memory.used,memory.total --format=csv
rec log-load sh -c "${COMPOSE[*]} logs --no-color vllm 2>&1 | grep -E -i 'model weights|KV cache|maximum concurrency|cuda graph|loading' | tail -20"

# 2 endpoints with and without the key (status codes only)
declare -A CODE
for path in /health /metrics /version /v1/models; do
  for mode in noauth auth; do
    hdr=(); [ "$mode" = auth ] && hdr=(-H @"$TMP/auth")
    CODE[$mode$path]=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "${hdr[@]}" "$BASE$path" || true)
    printf '%s\t%s\t%s\n' "$path" "$mode" "${CODE[$mode$path]}" >> "$EVID/endpoints.tsv"
  done
done
check "2 /health answers without the key (${CODE[noauth/health]})" test "${CODE[noauth/health]}" = 200
check "2 /metrics answers (${CODE[noauth/metrics]}); it is not covered by the key, so the port stays on loopback" test "${CODE[noauth/metrics]}" = 200
check "2 /v1/models refuses requests without the key (${CODE[noauth/v1/models]})" test "${CODE[noauth/v1/models]}" = 401
check "2 /v1/models answers with the key (${CODE[auth/v1/models]})" test "${CODE[auth/v1/models]}" = 200

# 3 effective configuration
rec models api /v1/models 10
check "3 served model name is $MODEL" grep -q "\"id\":\"$MODEL\"" "$EVID/$(printf '%02d' "$N")-models.out"
check "3 max_model_len is $LEN" grep -q "\"max_model_len\":$LEN" "$EVID/$(printf '%02d' "$N")-models.out"
rec metrics-config sh -c "curl -s -m 10 $BASE/metrics | grep -E '^vllm:(cache_config_info|num_requests_|kv_cache_usage)' | head -20"

# 4/5 concurrency, TTFT, queueing (qwen_ops capacity streams and records TTFT; residency lookup is Ollama-only and reports an error here)
rec capacity "$PY" -m qwen_ops capacity --service compose --base-url "$BASE/v1" --model "$MODEL" --levels 1,2,4 --count 8 --max-tokens 128 --out "$EVID/capacity.json"
rec metrics-after-load sh -c "curl -s -m 10 $BASE/metrics | grep -E '^vllm:(num_requests_running|num_requests_waiting|kv_cache_usage_perc|num_preemptions_total|request_success_total)' | head -20"
rec gpu-after-burst nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv

# 6 short, long, over-budget
long_prompt() { "$PY" -c "import json,sys; n=int(sys.argv[1]); print(json.dumps('Code ZEBRA-4417.\n' + '\n'.join(f'Record {i:04d}: nominal.' for i in range(n)) + '\nWhat was the code? Reply with the code only.'))" "$1"; }
rec long-fits chat "$(long_prompt $((LEN / 12)))" 300 16
rec long-over chat "$(long_prompt $((LEN / 4)))" 300 16
check "6 a prompt beyond max_model_len is rejected with an error, not silently truncated" grep -q -i -E 'maximum context length|max_model_len|too long|error' "$EVID/$(printf '%02d' "$N")-long-over.out"
rec budget-over chat '"Count from 1 to 10."' 60 $((LEN * 2))
rec finish-length chat '"Count from 1 to 200, separated by spaces."' 120 8
check "6 an 8-token budget ends with finish_reason length" grep -q '"finish_reason":"length"' "$EVID/$(printf '%02d' "$N")-finish-length.out"

# 7 stop -> detect -> start; crash -> restart policy
rec stop "${COMPOSE[@]}" stop vllm
rec health-while-stopped "$PY" -m qwen_ops health --service compose --base-url "$BASE/v1" --model "$MODEL" --no-golden
check "7 a stopped server is reported down (exit 1)" grep -q '"status": "down"' "$EVID/$(printf '%02d' "$N")-health-while-stopped.out"
rec start "${COMPOSE[@]}" start vllm
rec wait-healthy-after-start wait_healthy 900
rec health-after-start "$PY" -m qwen_ops health --service compose --base-url "$BASE/v1" --model "$MODEL"
check "7 healthy again after start, golden prompts answered" grep -q '"status": "healthy"' "$EVID/$(printf '%02d' "$N")-health-after-start.out"
restarts_before=$(docker inspect -f '{{.RestartCount}}' "$(container)")
rec crash sh -c "kill -9 \$(docker inspect -f '{{.State.Pid}}' $(container)) && echo 'sent SIGKILL to the container main process'"
rec wait-healthy-after-crash wait_healthy 900
restarts_after=$(docker inspect -f '{{.RestartCount}}' "$(container)")
check "7 restart policy restarted the crashed container (RestartCount $restarts_before -> $restarts_after)" test "$restarts_after" -gt "$restarts_before"
rec chat-after-crash chat '"Reply with the single word READY."'

# 8 config change and rollback to the known-good .env
cp "$ENV_FILE" "$TMP/known-good.env"
sed -e "s/^MAX_MODEL_LEN=.*/MAX_MODEL_LEN=$((LEN / 2))/" -e 's/^MAX_NUM_SEQS=.*/MAX_NUM_SEQS=2/' "$ENV_FILE" > "$TMP/changed.env"
rec change docker compose --env-file "$TMP/changed.env" -f deploy/linux-vllm/compose.yaml up -d --force-recreate vllm
rec wait-healthy-changed wait_healthy 900
rec models-changed api /v1/models 10
check "8 the change took effect (max_model_len $((LEN / 2)))" grep -q "\"max_model_len\":$((LEN / 2))" "$EVID/$(printf '%02d' "$N")-models-changed.out"
rec rollback docker compose --env-file "$TMP/known-good.env" -f deploy/linux-vllm/compose.yaml up -d --force-recreate vllm
rec wait-healthy-rolled-back wait_healthy 900
rec models-rolled-back api /v1/models 10
check "8 rollback restored max_model_len $LEN" grep -q "\"max_model_len\":$LEN" "$EVID/$(printf '%02d' "$N")-models-rolled-back.out"
rec chat-after-rollback chat '"Reply with the single word READY."'

rec logs sh -c "${COMPOSE[*]} logs --no-color --tail 300 vllm"
# the key must not appear anywhere in the evidence
if grep -R -q -F "$KEY" "$EVID"; then echo "FAIL	API key found in evidence; deleting those files" | tee -a "$EVID/summary.tsv"; grep -R -l -F "$KEY" "$EVID" | xargs rm -f; FAILS=$((FAILS + 1)); fi
echo "done: $FAILS failed checks; evidence in $EVID"
exit $((FAILS > 0))
