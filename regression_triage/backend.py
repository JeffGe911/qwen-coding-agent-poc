"""Backend profiles: the only place where serving stacks differ.

The business flow (prompt, schema, citation validation, scoring, report) is the same for every backend. A profile
(deploy/backends/*.json) records where the model is and how it is called: endpoint, served model name, weights
identity, auth, timeout, context, output budget, and every sampling field that goes into the request, together with
the values the server is known to apply on its own. Endpoints stay loopback-only (qwen_agent.client.validate_url).
There is no fallback: if the profile's server does not answer, the call is recorded as request_failed.
"""
import hashlib
import json
import os
from pathlib import Path
import urllib.request

from qwen_agent.client import validate_url

KINDS = ("ollama", "vllm")
REQUIRED = ("name", "kind", "base_url", "model", "weights", "auth", "timeout_s", "context_tokens", "max_tokens", "margin_tokens",
            "chars_per_token_estimate", "request_sampling", "effective_sampling", "concurrency")
# Sampling fields a backend honours in /v1/chat/completions. Ollama's /v1 ignores repeat_penalty and top_k; sending them
# would only make the record look as if they were applied.
HONOURED = {"ollama": {"temperature", "top_p", "seed"}, "vllm": {"temperature", "top_p", "top_k", "repetition_penalty", "seed"}}


def load(path):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = [f"missing {k}" for k in REQUIRED if k not in profile]
    if not problems:
        if profile["kind"] not in KINDS:
            problems.append(f"unknown kind {profile['kind']!r}")
        else:
            ignored = set(profile["request_sampling"]) - HONOURED[profile["kind"]]
            if ignored:
                problems.append(f"{profile['kind']} does not honour {sorted(ignored)} in /v1; record them under effective_sampling instead")
        if "temperature" not in profile["request_sampling"]:
            problems.append("request_sampling must set temperature explicitly")
        if profile["auth"].get("type") not in ("none", "bearer_env"):
            problems.append("auth.type must be none or bearer_env")
        if profile["concurrency"] != 1:
            problems.append("the evaluation runs one request at a time; concurrency must be 1")
        try:
            validate_url(profile["base_url"])
        except ValueError as exc:
            problems.append(str(exc))
    if problems:
        raise ValueError(f"{path}: " + "; ".join(problems))
    return profile


def sha256(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def api_key(profile):
    """The bearer key for this profile, or None. A profile that needs a key never silently goes out without one."""
    if profile["auth"]["type"] == "none":
        return None
    key = os.environ.get(profile["auth"]["env"])
    if not key:
        raise ValueError(f"profile {profile['name']} needs ${profile['auth']['env']} (bearer key); it is not set")
    return key


def _get(profile, url, timeout=10):
    headers = {}
    key = api_key(profile)
    if key:
        headers["Authorization"] = "Bearer " + key
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read(262144))


def server_context(profile):
    """(context the server reports for this model, where it came from). (None, reason) when it is not reported."""
    origin = profile["base_url"][: -len("/v1")]
    try:
        if profile["kind"] == "ollama":
            models = _get(profile, origin + "/api/ps").get("models", [])
            return next((m.get("context_length") for m in models if m.get("name") == profile["model"]), None), "ollama /api/ps context_length"
        entry = next((m for m in _get(profile, profile["base_url"] + "/models").get("data", []) if m.get("id") == profile["model"]), None)
        if entry is None:
            return None, f"/v1/models does not list {profile['model']}"
        return entry.get("max_model_len"), "vllm /v1/models max_model_len" if "max_model_len" in entry else "/v1/models has no max_model_len"
    except (OSError, ValueError) as exc:
        return None, f"not reachable: {type(exc).__name__}"


def identity(profile):
    """What the running server says about the weights, to compare with profile['weights'] before an evaluation."""
    origin = profile["base_url"][: -len("/v1")]
    if profile["kind"] == "ollama":
        for m in _get(profile, origin + "/api/tags").get("models", []):
            if m["name"] == profile["model"]:
                return {"digest": m["digest"], "quantization": m["details"].get("quantization_level"), "format": m["details"].get("format")}
        raise LookupError(f"{profile['model']} is not listed by {origin}")
    entry = next((m for m in _get(profile, profile["base_url"] + "/models").get("data", []) if m.get("id") == profile["model"]), None)
    if entry is None:
        raise LookupError(f"{profile['model']} is not served by {profile['base_url']}")
    return {"served_id": entry["id"], "root": entry.get("root"), "max_model_len": entry.get("max_model_len")}


def identity_problems(profile, served):
    """Empty list when the running server matches the weights the profile names."""
    w = profile["weights"]
    if profile["kind"] == "ollama":
        return [] if served.get("digest") == w["digest"] else [f"server digest {served.get('digest', '')[:12]} != profile {w['digest'][:12]}"]
    # vLLM reports neither a digest nor a revision; the snapshot hashes are checked on the host (download_model.sh evidence).
    problems = [] if served.get("served_id") == profile["model"] else [f"server serves {served.get('served_id')} not {profile['model']}"]
    if served.get("max_model_len") not in (None, profile["context_tokens"]):
        problems.append(f"server max_model_len {served['max_model_len']} != profile {profile['context_tokens']}")
    return problems
