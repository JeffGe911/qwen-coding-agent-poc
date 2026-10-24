#!/usr/bin/env bash
# Download one model snapshot at a pinned revision and record what was downloaded (file list, sizes, sha256).
# Network is needed only here (Hugging Face); the running server is offline (HF_HUB_OFFLINE=1).
# STATUS: written, not yet run.  Usage: bash deploy/linux-vllm/download_model.sh <repo> <revision> <target_dir> <evidence_dir>
set -euo pipefail
repo=${1:?repo, e.g. Qwen/Qwen2.5-Coder-1.5B-Instruct}
rev=${2:?pinned commit sha}
target=${3:?target directory}
evid=${4:?evidence directory}
[[ $rev =~ ^[0-9a-f]{40}$ ]] || { echo "revision must be a 40-char commit sha, not a branch name" >&2; exit 2; }
command -v hf >/dev/null || { echo "install the Hugging Face CLI first: pip install -U huggingface_hub" >&2; exit 2; }
mkdir -p "$target" "$evid"
df -h "$target" | tee "$evid/disk-before.txt"
hf download "$repo" --revision "$rev" --local-dir "$target" 2>&1 | tee "$evid/download.log"
( cd "$target" && find . -type f ! -path './.cache/*' -printf '%s %p\n' | sort -k2 ) > "$evid/files.txt"
( cd "$target" && find . -type f ! -path './.cache/*' -name '*.safetensors' -print0 | xargs -0 sha256sum ) > "$evid/safetensors.sha256"
printf '{"repo": "%s", "revision": "%s", "target": "%s", "bytes": %s}\n' "$repo" "$rev" "$target" "$(awk '{s+=$1} END {print s}' "$evid/files.txt")" > "$evid/model.json"
cat "$evid/model.json"
