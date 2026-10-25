"""Static checks of the single-host vLLM deployment files. They do not start anything; the files are unverified on Linux."""
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "linux-vllm"
COMPOSE = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")


def test_image_and_weights_are_pinned():
    assert re.search(r"vllm/vllm-openai:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", COMPOSE)
    env = (DEPLOY / "env.example").read_text(encoding="utf-8")
    assert re.search(r"@ [0-9a-f]{40}", env) and "pull_policy: never" in COMPOSE
    script = (DEPLOY / "download_model.sh").read_text(encoding="utf-8")
    assert "[0-9a-f]{40}" in script and "--revision" in script


def test_listening_scope_key_and_offline_runtime():
    ports = re.findall(r'-\s*"([^"]+):8000"', COMPOSE)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports)
    assert "VLLM_API_KEY: ${VLLM_API_KEY:?" in COMPOSE and not re.search(r"VLLM_API_KEY:\s*[0-9a-f]{16,}", COMPOSE)
    assert 'HF_HUB_OFFLINE: "1"' in COMPOSE and 'VLLM_NO_USAGE_STATS: "1"' in COMPOSE
    assert "- --generation-config=vllm" in COMPOSE  # otherwise the model's repetition_penalty 1.1 is applied silently
    assert "--enable-log-requests" not in COMPOSE.replace("do not add --enable-log-requests", "")
    assert "REPLACE_WITH" in (DEPLOY / "env.example").read_text(encoding="utf-8")


def test_resource_limits_health_check_and_log_rotation():
    for needle in ("mem_limit:", "memswap_limit:", "pids_limit:", "shm_size:", "healthcheck:", "/health", "max-size", "no-new-privileges", "count: 1"):
        assert needle in COMPOSE, needle
    wsl = (DEPLOY / "wslconfig.example").read_text(encoding="utf-8")
    assert "memory=8GB" in wsl and "swap=4GB" in wsl


def test_acceptance_script_never_traces_and_redacts_the_key():
    text = (DEPLOY / "acceptance.sh").read_text(encoding="utf-8")
    assert "set -x" not in text and "redact" in text and 'grep -R -q -F "$KEY"' in text
    assert "QWEN_VLLM_CONFIRM" in text and "MAX_GPU_USED_MB" in text and "MIN_FREE_MB" in text
    assert "config --quiet" in text and re.search(r"config(?! --quiet)\s*$", text, re.M) is None


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not available")
@pytest.mark.parametrize("script", ["acceptance.sh", "download_model.sh"])
def test_scripts_parse(script):
    assert subprocess.run(["bash", "-n", str(DEPLOY / script)], capture_output=True).returncode == 0


# ---------- refusal paths of acceptance.sh, driven with stub commands ----------
# These only exercise the script's own decisions (when to stop, what reaches the evidence folder) with fake
# uname/free/nvidia-smi/docker on PATH. They are code tests, not a deployment check: nothing here talks to vLLM.

KEY = "0123456789abcdef" * 4


def bash_works():
    exe = shutil.which("bash")
    return bool(exe) and subprocess.run([exe, "-c", "set -o pipefail; echo ok"], capture_output=True, text=True).stdout.strip() == "ok"


def acceptance(tmp_path, free_mb=8000, gpu_used=300, confirm="yes", key=KEY, leak_key=False):
    bin_dir, evid = tmp_path / "bin", tmp_path / "evidence"
    bin_dir.mkdir(parents=True)
    calls = (tmp_path / "calls.log").as_posix()
    stubs = {
        "uname": "echo Linux",
        "hostname": "echo stubhost",
        "free": f'echo "     total used free shared buff/cache available"; echo "Mem: 31000 20000 1000 100 10000 {free_mb}"',
        "nvidia-smi": f'case "$*" in *query-gpu*) echo {gpu_used};; *) echo "nvidia-smi stub";; esac',
        # a tool that echoes the key (e.g. `compose config` without --quiet) must still not leak it into evidence
        "docker": f'echo "docker $*" >> "{calls}"' + (f'; echo "environment: VLLM_API_KEY={key}"' if leak_key else ""),
        "curl": f'echo "curl $*" >> "{calls}"; exit 7',
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
    env_file = tmp_path / "test.env"
    env_file.write_text(f"VLLM_API_KEY={key}\nVLLM_IMAGE=vllm/vllm-openai:v0.32.0@sha256:{'0' * 64}\nHOST_PORT=18999\n", encoding="utf-8", newline="\n")
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "ENV_FILE": env_file.as_posix(), "EVID_ROOT": evid.as_posix(),
           "QWEN_VLLM_CONFIRM": confirm}
    p = subprocess.run([shutil.which("bash"), str(DEPLOY / "acceptance.sh")], env=env, capture_output=True, text=True, timeout=60)
    docker_calls = Path(calls).read_text(encoding="utf-8") if Path(calls).exists() else ""
    files = {f.name: f.read_text(encoding="utf-8") for f in evid.rglob("*") if f.is_file()} if evid.exists() else {}
    return p, docker_calls, files


needs_bash = pytest.mark.skipif(not bash_works(), reason="no working bash")


@needs_bash
def test_acceptance_needs_explicit_confirmation_and_a_hex_key(tmp_path):
    p, calls, _ = acceptance(tmp_path, confirm="")
    assert p.returncode == 2 and "QWEN_VLLM_CONFIRM=yes" in p.stderr and calls == ""
    p, calls, _ = acceptance(tmp_path / "k", key="REPLACE_WITH_64_HEX_CHARS")
    assert p.returncode == 2 and "must be hex" in p.stderr and calls == ""


@needs_bash
@pytest.mark.parametrize("free_mb,gpu_used,failed", [(3000, 300, "available RAM"), (8000, 9000, "GPU memory already used")])
def test_acceptance_stops_before_starting_when_resources_are_short(tmp_path, free_mb, gpu_used, failed):
    p, calls, files = acceptance(tmp_path, free_mb=free_mb, gpu_used=gpu_used)
    assert p.returncode == 1 and "not starting vLLM" in p.stderr
    assert "config --quiet" in calls and " up " not in calls and " kill " not in calls  # report and stop, never start or free anything
    assert any(line.startswith("FAIL") and failed in line for line in files["summary.tsv"].splitlines())


@needs_bash
def test_acceptance_redacts_the_key_from_every_evidence_file(tmp_path):
    _, _, files = acceptance(tmp_path, free_mb=3000, leak_key=True)
    assert files and not any(KEY in text for text in files.values())
    assert any("[REDACTED]" in text for text in files.values())


def test_migration_script_is_gated_and_uses_the_recorded_profile():
    text = (DEPLOY / "migrate.sh").read_text(encoding="utf-8")
    assert "QWEN_VLLM_CONFIRM" in text and "set -x" not in text and "deploy/backends/vllm-qwen7b-awq.json" in text
    assert "MAX_MODEL_LEN in $ENV_FILE must be 8192" in text  # same context as the Ollama baseline
    assert 'grep -R -q -F "$LOCAL_MODEL_API_KEY"' in text and "echo $LOCAL_MODEL_API_KEY" not in text
    assert 'kill "$pid"' in text and "accuracy is not looked at" in text  # stops only its own eval; the gate never tunes on results
    profile = (DEPLOY.parent / "backends" / "vllm-qwen7b-awq.json").read_text(encoding="utf-8")
    assert "NEVER RUN" in profile and "8e8ed243bbe6f9a5aff549a0924562fc719b2b8a" in profile
    env = (DEPLOY / "env.7b-awq.example").read_text(encoding="utf-8")
    assert "MAX_MODEL_LEN=8192" in env and "Qwen2.5-Coder-7B-Instruct-AWQ" in env and "REPLACE_WITH" in env


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not available")
def test_migration_script_parses():
    assert subprocess.run(["bash", "-n", str(DEPLOY / "migrate.sh")], capture_output=True).returncode == 0
