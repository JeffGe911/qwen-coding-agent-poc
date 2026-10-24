"""Pinned releases with gated activation and rollback.

deploy/releases/<name>.json : server kind/version/binary hash/settings + model name/digest + agent contract
deploy/releases/ACTIVE      : name of the release currently in service
deploy/releases/history.jsonl: every snapshot / activate / rollback event (append-only)

A release is activated only if its pins match (binary hash, server version, model digest) and the
regression gate passes; otherwise the previous release is restored and gated again.
"""
import hashlib
import json
from pathlib import Path

from qwen_agent.client import DEFAULT_MAX_TOKENS, prompt_sha256
from qwen_agent.policy import POLICY_REVISION

from . import gate as gate_mod
from .health import http_json, now, pid_alive
from .service import OllamaWindows

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "deploy" / "releases"


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def path_of(name):
    return RELEASES / f"{name}.json"


def load(name):
    return json.loads(path_of(name).read_text(encoding="utf-8"))


def active_name():
    p = RELEASES / "ACTIVE"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def history(event, **data):
    RELEASES.mkdir(parents=True, exist_ok=True)
    record = {"at_utc": now(), "event": event, **data}
    with (RELEASES / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_history():
    p = RELEASES / "history.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def model_info(base_url, model):
    origin = base_url[: -len("/v1")]
    for m in http_json(origin + "/api/tags", timeout=10).get("models", []):
        if m["name"] == model:
            return {"name": model, "digest": m["digest"], "quantization": m["details"].get("quantization_level"),
                    "parameter_size": m["details"].get("parameter_size"), "format": m["details"].get("format")}
    raise ValueError(f"model {model} not present on the server")


def snapshot(name, service, model, note="", overrides=None, max_tokens=None):
    """Record the running server + the given model as a pinned release (no restart).

    overrides: server settings that differ from the running server (a candidate config);
    the binary and version pins still come from the running server.
    """
    launch = service.launch_record()
    if not launch:
        raise ValueError("no launch record; start the server with scripts/start_ollama.ps1 first")
    exe = Path(launch["command"].split('"')[1])
    server = {**service.describe(), **(overrides or {}), "version": launch["server_version"], "exe": str(exe), "exe_sha256": sha256_file(exe)}
    manifest = {
        "name": name, "created_at_utc": now(), "note": note, "server": server,
        "model": model_info(service.base_url, model),
        "agent": {"base_url": service.base_url, "model": model, "prompt_sha256": prompt_sha256(), "policy_revision": POLICY_REVISION,
                  "policy_sha256": sha256_file(ROOT / "qwen_agent" / "policy.py"), "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
                  "context_tokens": server["context"]},
    }
    RELEASES.mkdir(parents=True, exist_ok=True)
    if path_of(name).exists():
        raise ValueError(f"release {name} already exists; releases are immutable, pick a new name")
    path_of(name).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    history("snapshot", name=name, server={k: server[k] for k in ("port", "context", "parallel", "max_queue")}, model=model)
    return manifest


def service_for(manifest, evidence_dir=None):
    s = manifest["server"]
    if s["kind"] != "ollama-windows":
        raise ValueError("only ollama-windows releases can be activated on this host")
    return OllamaWindows(s["port"], s["context"], s["parallel"], s["max_queue"], evidence_dir, s.get("extra_env"))


def verify_pins(manifest, service):
    """Binary and model must be byte/digest-identical to the manifest; the running server must use its settings."""
    problems = []
    if sha256_file(manifest["server"]["exe"]) != manifest["server"]["exe_sha256"]:
        problems.append("server binary hash differs from manifest")
    launch = service.launch_record()
    if not launch:
        problems.append("no launch record for the server")
    else:
        if launch["server_version"] != manifest["server"]["version"]:
            problems.append(f"server version {launch['server_version']} != {manifest['server']['version']}")
        env = launch.get("environment", {})
        for key, value in wanted_env(service).items():
            if env.get(key) != value:
                problems.append(f"running {key}={env.get(key)} != release {value}")
        extra = sorted(set(env) - set(wanted_env(service)) - BASE_ENV)
        if extra:
            problems.append(f"running server has settings the release does not have: {extra}")
        if launch.get("exe_sha256") != manifest["server"]["exe_sha256"]:
            problems.append("binary of the running server (launch record) differs from manifest")
        if not pid_alive(launch.get("pid")):
            problems.append(f"server pid {launch.get('pid')} from the launch record is not running")
    try:
        if model_info(service.base_url, manifest["model"]["name"])["digest"] != manifest["model"]["digest"]:
            problems.append("model digest differs from manifest")
    except (OSError, ValueError) as exc:
        problems.append(f"model check failed: {exc}")
    return problems


BASE_ENV = {"OLLAMA_HOST", "OLLAMA_MODELS", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE", "OLLAMA_NO_CLOUD"}


def wanted_env(service):
    return {"OLLAMA_CONTEXT_LENGTH": str(service.context), "OLLAMA_NUM_PARALLEL": str(service.parallel),
            "OLLAMA_MAX_QUEUE": str(service.max_queue), **{k: str(v) for k, v in service.extra_env.items()}}


def apply(manifest, evidence_dir=None):
    """Restart the server only if it is not running with exactly the manifest's settings."""
    service = service_for(manifest, evidence_dir)
    launch = service.launch_record()
    env = (launch or {}).get("environment", {})
    running = bool(launch) and pid_alive(launch["pid"])
    extra_now = {k for k in env if k not in ("OLLAMA_HOST", "OLLAMA_MODELS", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_KEEP_ALIVE", "OLLAMA_NO_CLOUD")}
    same = running and all(env.get(k) == v for k, v in wanted_env(service).items()) and extra_now <= set(wanted_env(service))
    if same:
        return service, {"restarted": False}
    return service, {"restarted": True, **service.restart()}


def activate(name, auto_rollback=True, evidence_dir=None, gate_fn=None):
    previous = active_name()
    manifest = load(name)
    service, action = apply(manifest, evidence_dir)
    pins = verify_pins(manifest, service)
    gate_fn = gate_fn or gate_mod.run
    result = gate_fn(service.base_url, manifest["model"]["name"], pid=service.pid()) if not pins else {"passed": False, "checks": {"pins": pins}}
    event = history("activate", name=name, previous=previous, restarted=action["restarted"], pin_problems=pins, gate_passed=result["passed"],
                    gate_checks=result["checks"])
    outcome = {"name": name, "previous": previous, "action": action, "pins": pins, "gate": result, "event": event}
    if result["passed"]:
        (RELEASES / "ACTIVE").write_text(name + "\n", encoding="utf-8")
        outcome["active"] = name
    elif auto_rollback and previous and previous != name:
        history("auto_rollback", failed=name, to=previous)
        outcome["rollback"] = activate(previous, auto_rollback=False, evidence_dir=evidence_dir, gate_fn=gate_fn)
        outcome["active"] = active_name()
    else:
        outcome["active"] = previous
    return outcome


def adopt(name, service, model, note=""):
    """Take over a service that is already running: record it as a release and mark it ACTIVE without a gate.

    This is the starting point when inheriting a deployment; run `qwen_ops gate` next to see where it stands.
    """
    if active_name():
        raise ValueError(f"release {active_name()} is already ACTIVE; use activate for changes")
    launch = service.launch_record()
    if not launch:
        raise ValueError("no launch record for the running server")
    env = launch.get("environment", {})
    # Settings come from what the server was actually started with, not from CLI defaults.
    # Launch records written before OLLAMA_MAX_QUEUE was recorded ran with Ollama's default of 512.
    running = OllamaWindows(service.port, int(env["OLLAMA_CONTEXT_LENGTH"]), int(env["OLLAMA_NUM_PARALLEL"]), int(env.get("OLLAMA_MAX_QUEUE", 512)),
                            service.evidence_dir)
    manifest = snapshot(name, running, model, note)
    (RELEASES / "ACTIVE").write_text(name + "\n", encoding="utf-8")
    history("adopt", name=name, gated=False, note="pre-existing running service recorded as-is")
    return manifest


def previous_release(current=None):
    """The release that was in service before `current` (gated activations and the adopted starting point)."""
    current = current or active_name()
    actives = [e["name"] for e in read_history() if (e["event"] == "activate" and e.get("gate_passed")) or e["event"] == "adopt"]
    for name in reversed(actives):
        if name != current:
            return name
    return None


def rollback(evidence_dir=None, gate_fn=None):
    current = active_name()
    target = previous_release(current)
    if not target:
        raise ValueError("no earlier release in history to roll back to")
    history("rollback_begin", current=current, to=target)
    outcome = activate(target, auto_rollback=False, evidence_dir=evidence_dir, gate_fn=gate_fn)
    history("rollback_end", current=current, to=target, active=outcome["active"], gate_passed=outcome["gate"]["passed"])
    return outcome
