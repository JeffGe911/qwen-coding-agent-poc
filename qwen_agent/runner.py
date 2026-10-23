import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "qwen-agent-sandbox:0.1"


def execute(workspace, sandbox, timeout=20):
    workspace = Path(workspace).resolve()
    container = "qwen-poc-" + uuid.uuid4().hex
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC"}}
    env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    if sandbox == "docker":
        if not shutil.which("docker"):
            raise RuntimeError("Docker is required. Install/start Docker or explicitly choose --sandbox restricted for the documented trusted demo only")
        command = ["docker", "run", "--rm", "--name", container, "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534", "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=32", "--tmpfs=/tmp:rw,noexec,nosuid,size=32m", "--mount", f"type=bind,source={workspace},target=/job,readonly", IMAGE, "python", "-I", "-B", "-m", "qwen_agent.worker", "/job"]
    elif sandbox == "restricted":
        # Isolated interpreter, clean env, no shell; this is not an OS security boundary.
        bootstrap = "import sys;sys.path.insert(0,sys.argv[1]);from qwen_agent.worker import main;sys.argv=sys.argv[1:];main()"
        command = [sys.executable, "-I", "-B", "-c", bootstrap, str(ROOT), str(workspace)]
    else:
        raise ValueError("Unknown sandbox")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="qwen-worker-") as cwd:
        # File-backed output avoids an unbounded parent-memory capture.
        with tempfile.TemporaryFile() as out:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, shell=False)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                if sandbox == "docker":
                    subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=10, check=False)
                return {"exit_code": -1, "timeout": True, "tests": 0, "passed": 0, "output": "pytest execution exceeded time limit", "elapsed_seconds": round(time.monotonic() - started, 3)}
            out.seek(0)
            raw = out.read(65537).decode("utf-8", errors="replace")
    if len(raw) > 65536:
        raise RuntimeError("Worker output exceeded limit")
    if process.returncode != 0:
        raise RuntimeError(f"Worker failed ({process.returncode}): {raw[-3000:]}")
    result = json.loads(raw.strip().splitlines()[-1])
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result

