"""Static checks of the single-host vLLM deployment files. They do not start anything; the files are unverified on Linux."""
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
