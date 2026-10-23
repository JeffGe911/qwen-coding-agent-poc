#!/usr/bin/env bash
# Read-only Linux GPU server inventory for the planned servers.
# NOT YET EXECUTED on any Linux host; written on Windows without server access.
# Changes nothing: no installs, no service restarts, no driver changes.
# Usage: bash scripts/env_check.sh [output_dir]
set -u
out_dir="${1:-evidence/env}"
mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
file="$out_dir/linux-$(hostname)-$stamp.txt"

section() { printf '\n=== %s ===\n' "$1"; }
tool() { if command -v "$1" >/dev/null 2>&1; then echo "path: $(command -v "$1")"; "$@" 2>&1; else echo "$1 : NOT FOUND in PATH"; fi; }

{
  echo "collected_at_utc: $stamp"
  echo "host: $(hostname)"
  section "OS";        cat /etc/os-release 2>/dev/null | grep -E '^(PRETTY_NAME|VERSION_ID)='; uname -srm
  section "CPU";       lscpu 2>/dev/null | grep -E 'Model name|^CPU\(s\)|Socket|NUMA node\(s\)'
  section "Memory";    free -h
  section "Disks";     df -h -x tmpfs -x devtmpfs -x overlay 2>/dev/null
  section "GPU (CUDA Version in nvidia-smi = driver capability, NOT installed toolkit)"
  tool nvidia-smi
  section "GPU query"; tool nvidia-smi --query-gpu=index,name,memory.total,memory.used,driver_version,compute_cap --format=csv
  section "GPU topology (relevant for tensor parallel across GPUs)"; tool nvidia-smi topo -m
  section "CUDA Toolkit"; tool nvcc --version
  section "Python";    tool python3 --version
  python3 - <<'PY' 2>&1
import importlib.util as u
for name in ("pytest", "vllm", "torch"):
    print(f"{name} installed: {bool(u.find_spec(name))}")
PY
  section "Docker";    tool docker --version; docker info --format 'server={{.ServerVersion}} runtimes={{json .Runtimes}} default={{.DefaultRuntime}}' 2>&1
  section "Docker Compose"; docker compose version 2>&1
  section "NVIDIA Container Toolkit"; tool nvidia-ctk --version
  section "Existing inference services (inspect only; do not stop)"
  ps -eo pid,user,etime,cmd 2>/dev/null | grep -Ei 'ollama|vllm|llama|tgi|text-generation|sglang|triton' | grep -v grep
  docker ps --format '{{.ID}} {{.Image}} {{.Ports}} {{.Names}}' 2>&1
  section "Listening ports of interest"
  ss -ltnp 2>/dev/null | grep -E ':(8000|8080|11434|11436|11437)\b' || echo "none of 8000/8080/11434/11436/11437 listening (or ss unavailable)"
  section "Model directories"
  for d in "$HOME/.ollama/models" "$HOME/.cache/huggingface" /srv/models /data/models; do
    [ -d "$d" ] && du -sh "$d" 2>/dev/null || echo "$d : missing"
  done
} > "$file" 2>&1

echo "$file"
