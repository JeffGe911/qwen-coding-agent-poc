"""Service control behind one interface so the release tooling (and later a watchdog) work on both hosts.

OllamaWindows : this laptop; wraps scripts/start_ollama.ps1 and scripts/stop_ollama.ps1
ComposeService: Linux + Docker Compose (vLLM); restart = docker compose restart <service>  (NOT executed here)
"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def runtime_dir():
    """Portable Ollama + models. Same rule as the PowerShell scripts: $QWEN_POC_RUNTIME, else ../../work/runtime."""
    return Path(os.environ.get("QWEN_POC_RUNTIME") or ROOT.parents[1] / "work" / "runtime")


def run(cmd, timeout=300):
    started = time.monotonic()
    try:
        # Windows PowerShell writes redirected output in the OEM code page (cp936 here), not UTF-8.
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="oem" if os.name == "nt" else "utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        return {"cmd": " ".join(cmd), "exit_code": None, "seconds": round(time.monotonic() - started, 2), "timeout": True,
                "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "", "stderr": f"timed out after {timeout}s"}
    return {"cmd": " ".join(cmd), "exit_code": p.returncode, "seconds": round(time.monotonic() - started, 2),
            "stdout": p.stdout.strip()[-4000:], "stderr": p.stderr.strip()[-4000:]}


class OllamaWindows:
    kind = "ollama-windows"

    def __init__(self, port=11437, context=4096, parallel=2, max_queue=512, evidence_dir=None, extra_env=None):
        self.port, self.context, self.parallel, self.max_queue = port, context, parallel, max_queue
        self.extra_env = dict(extra_env or {})
        self.evidence_dir = Path(evidence_dir) if evidence_dir else ROOT / "evidence" / "serving"
        self.base_url = f"http://127.0.0.1:{port}/v1"

    def _ps(self, script, *args):
        return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / script), *map(str, args),
                    "-Runtime", str(runtime_dir())])

    def start(self):
        args = ["-Port", self.port, "-Context", self.context, "-NumParallel", self.parallel, "-MaxQueue", self.max_queue, "-Evidence", self.evidence_dir]
        if self.extra_env:
            args += ["-ExtraEnv", ";".join(f"{k}={v}" for k, v in self.extra_env.items())]
        r = self._ps("start_ollama.ps1", *args)
        r["record"] = next((line.split("=", 1)[1] for line in r["stdout"].splitlines() if line.startswith("RECORD=")), None)
        return r

    def stop(self):
        return self._ps("stop_ollama.ps1", "-Port", self.port)

    def restart(self):
        return {"stop": self.stop(), "start": self.start()}

    def launch_record(self):
        """Newest launch record for this port (None if there is none)."""
        for path in sorted(self.evidence_dir.glob(f"ollama-launch-{self.port}-*.json"), reverse=True):
            try:
                return json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
        return None

    def pid(self):
        return (self.launch_record() or {}).get("pid")

    def describe(self):
        return {"kind": self.kind, "port": self.port, "context": self.context, "parallel": self.parallel, "max_queue": self.max_queue,
                **({"extra_env": self.extra_env} if self.extra_env else {})}


class ComposeService:
    """Linux/Docker. Prepared for the GPU servers; not exercised on this Windows host."""
    kind = "docker-compose"

    def __init__(self, compose_file, env_file, service="inference", base_url="http://127.0.0.1:11436/v1"):
        self.compose = ["docker", "compose", "--env-file", str(env_file), "-f", str(compose_file)]
        self.service, self.base_url = service, base_url

    def start(self):
        return run(self.compose + ["up", "-d"])

    def stop(self):
        return run(self.compose + ["stop", self.service])

    def restart(self):
        # Restart policies only act on exited containers; a hung-but-running container needs this explicit restart.
        return {"restart": run(self.compose + ["restart", self.service], timeout=600)}

    def pid(self):
        return None

    def describe(self):
        return {"kind": self.kind, "service": self.service}
