"""Unit tests for qwen_ops against a fake in-process server (fixtures, not live model results)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import pytest

from qwen_agent import workflow
from qwen_ops import capacity, ollama_log, release
from qwen_ops.health import check, pct
from qwen_ops.monitor import LogWatch

MODEL = "fixture-model"


class FakeOllama:
    """Answers like Ollama's OpenAI-compatible API; `mode` injects one fault at a time."""

    def __init__(self):
        self.mode = "ok"
        self.vram_fraction = 1.0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, obj, status=200):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if fake.mode == "api_hang":
                    time.sleep(2)
                if self.path == "/v1/models":
                    return self.reply({"data": [{"id": MODEL}]})
                if self.path == "/api/ps":
                    return self.reply({"models": [{"name": MODEL, "size": 1000, "size_vram": int(1000 * fake.vram_fraction), "context_length": 4096}]})
                self.reply({"error": "not found"}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if fake.mode == "model_hang":
                    time.sleep(2)
                prompt = body["messages"][-1]["content"]
                if fake.mode == "wrong":
                    text = "42"
                elif "17 * 23" in prompt:
                    text = "391"
                elif "12 * 12" in prompt:
                    text = '{"answer": 144}'
                else:
                    text = "1 2 3"
                usage = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for piece in (text[:1], text[1:]):
                        self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}).encode() + b"\n\n")
                        self.wfile.flush()
                        time.sleep(0.05)
                    self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode() + b"\n\n")
                    self.wfile.write(b"data: " + json.dumps({"choices": [], "usage": usage}).encode() + b"\n\n")
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                self.reply({"choices": [{"finish_reason": "stop", "message": {"content": text}}], "usage": usage})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    server = FakeOllama()
    yield server
    server.close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_health_reports_each_layer_separately(fake, tmp_path):
    assert check(fake.base_url, MODEL, disk_path=tmp_path)["status"] == "healthy"
    fake.mode = "wrong"
    r = check(fake.base_url, MODEL)
    assert r["status"] == "model_wrong_or_slow" and r["checks"]["api"]["ok"]
    fake.mode = "model_hang"
    r = check(fake.base_url, MODEL, model_timeout=0.5)
    assert r["status"] == "model_wrong_or_slow" and "error" in r["checks"]["model"]["golden"][0]
    fake.mode = "api_hang"
    r = check(fake.base_url, MODEL, api_timeout=0.5)
    assert r["status"] == "api_unresponsive" and r["checks"]["port"]["ok"]
    fake.mode = "ok"
    fake.vram_fraction = 0.6
    r = check(fake.base_url, MODEL)
    assert r["status"] == "degraded_cpu_offload" and r["checks"]["residency"]["gpu_fraction"] == 0.6
    assert check(f"http://127.0.0.1:{free_port()}/v1", MODEL)["status"] == "down"
    # A recorded PID that no longer exists is "down" even if something answers on the port.
    assert check(fake.base_url, MODEL, pid=2**31 - 2)["status"] == "down"


class FakeService:
    base_url = "http://127.0.0.1:1/v1"

    def __init__(self):
        self.restarts = 0

    def restart(self):
        self.restarts += 1
        return {"stop": {"exit_code": 0, "seconds": 0.1}, "start": {"exit_code": 0, "seconds": 0.2}}

    def pid(self):
        return None

    def describe(self):
        return {"kind": "fake"}


@pytest.fixture
def releases(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "RELEASES", tmp_path)
    monkeypatch.setattr(release, "apply", lambda manifest, evidence_dir=None: (FakeService(), {"restarted": False}))
    monkeypatch.setattr(release, "verify_pins", lambda manifest, service: [])
    for name, model in (("r1", "good"), ("r2", "bad"), ("r3", "good2")):
        (tmp_path / f"{name}.json").write_text(json.dumps({"name": name, "model": {"name": model}, "server": {"kind": "ollama-windows"}}), encoding="utf-8")
    return tmp_path


def gate_passing(*good):
    return lambda base_url, model, pid=None: {"passed": model in good, "checks": {"model": model}}


def test_failed_gate_rolls_back_to_previous_release(releases):
    gate_fn = gate_passing("good", "good2")
    assert release.activate("r1", gate_fn=gate_fn)["active"] == "r1"
    out = release.activate("r2", gate_fn=gate_fn)
    assert out["active"] == "r1" and out["rollback"]["gate"]["passed"]
    assert release.active_name() == "r1"
    events = [e["event"] for e in release.read_history()]
    assert events == ["activate", "activate", "auto_rollback", "activate"]


def test_manual_rollback_returns_to_last_good_release(releases):
    gate_fn = gate_passing("good", "good2")
    release.activate("r1", gate_fn=gate_fn)
    release.activate("r3", gate_fn=gate_fn)
    assert release.previous_release() == "r1"
    out = release.rollback(gate_fn=gate_fn)
    assert out["active"] == "r1" and release.active_name() == "r1"
    assert [e["event"] for e in release.read_history()][-2:] == ["activate", "rollback_end"]


def test_release_manifests_are_immutable(releases, monkeypatch):
    class Svc:
        base_url = "http://127.0.0.1:1/v1"

        def launch_record(self):
            return {"command": '"C:\\x\\ollama.exe" serve', "server_version": "0"}

        def describe(self):
            return {"port": 1, "context": 1, "parallel": 1, "max_queue": 1}
    monkeypatch.setattr(release, "sha256_file", lambda p: "0" * 64)
    monkeypatch.setattr(release, "model_info", lambda base_url, model: {"name": model, "digest": "d"})
    with pytest.raises(ValueError, match="immutable"):
        release.snapshot("r1", Svc(), "good")
    assert release.snapshot("r9", Svc(), "good")["server"]["context"] == 1


ERR_LOG = """time=1 level=INFO msg="starting llama-server" cmd="llama-server.exe -c 8192 -np 2 --context-shift --keep 4"
load_tensors: offloaded 29/29 layers to GPU
slot   operator(): id  1 | task 7 | new prompt, n_ctx_slot = 4096, n_keep = 4, task.n_tokens = 3584
slot   operator(): id  1 | task 7 | slot context shift, n_keep = 4, n_left = 4091, n_discard = 2045
slot      release: id  1 | task 7 | stop processing: n_tokens = 2300, truncated = 1
load_tensors: offloaded 20/29 layers to GPU
ggml_cuda: CUDA error: out of memory
"""
OUT_LOG = """[GIN] 2026/10/23 - 12:28:56 | 200 |    4.64s |       127.0.0.1 | POST     "/v1/chat/completions"
[GIN] 2026/10/23 - 12:28:57 | 503 |  266.31ms |       127.0.0.1 | POST     "/v1/chat/completions"
[GIN] 2026/10/23 - 12:28:58 | 200 |     1m2.5s |       127.0.0.1 | POST     "/v1/chat/completions"
[GIN] 2026/10/23 - 12:28:59 | 200 |   13.99µs |       127.0.0.1 | GET      "/api/ps"
"""


def test_log_scan_finds_silent_context_shift_offload_and_errors(tmp_path):
    err, out = tmp_path / "ollama-1-x.err.log", tmp_path / "ollama-1-x.out.log"
    err.write_text(ERR_LOG, encoding="utf-8")
    out.write_text(OUT_LOG, encoding="utf-8")
    res = ollama_log.scan({"stderr_log": str(err)})
    assert res["stderr"]["counts"] == {"context_shift": 1, "truncated": 1, "gpu_error": 1, "runner_exit": 0, "queue_full": 0, "gpu_warning": 0, "cpu_offload": 1}
    chat = res["access"]["by_route"]["/v1/chat/completions"]
    assert chat["requests"] == 3 and chat["errors_5xx"] == 1 and chat["max_s"] == 62.5
    assert res["access"]["by_route"]["/api/ps"]["max_s"] == pytest.approx(13.99e-6)
    assert ollama_log.scan({"stderr_log": str(err)}, err_start=5)["stderr"]["counts"]["context_shift"] == 0


def test_log_watch_reports_only_new_lines_and_follows_restarts(tmp_path):
    err = tmp_path / "ollama-1-a.err.log"
    err.write_text(ERR_LOG, encoding="utf-8")
    current = {"stderr_log": str(err)}
    watch = LogWatch(lambda: current)
    assert watch.delta()["counts"]["context_shift"] == 0  # history before monitoring is ignored
    with err.open("a", encoding="utf-8") as f:
        f.write("slot   operator(): id  0 | task 9 | slot context shift, n_keep = 4\n")
    assert watch.delta()["counts"]["context_shift"] == 1
    new = tmp_path / "ollama-1-b.err.log"
    new.write_text(ERR_LOG, encoding="utf-8")
    current["stderr_log"] = str(new)
    assert watch.delta()["counts"]["context_shift"] == 1  # a restarted server's log is read from its first line


def test_stream_records_ttft_and_usage(fake):
    r = capacity.post_stream(fake.base_url + "/chat/completions", {"model": MODEL, "messages": [{"role": "user", "content": "count"}]}, 10)
    assert r["ok"] and r["text"] == "1 2 3" and r["usage"]["completion_tokens"] == 3 and r["finish_reason"] == "stop"
    assert 0 < r["ttft_s"] < r["seconds"]
    rows = capacity.concurrency(fake.base_url, MODEL, levels=[2], count=4, max_tokens=8)
    assert rows[0]["ok"] == 4 and rows[0]["ttft_p50_s"] is not None


def test_percentile_is_nearest_rank():
    assert pct([], 0.5) is None
    assert pct([3, 1, 2, 4], 0.5) == 2 and pct([3, 1, 2, 4], 0.95) == 4


class UsageModel:
    def __init__(self, prompt_tokens, completion_tokens):
        self.usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}

    def propose(self, *args):
        code = (workflow.TASKS / "clamp" / "solution.py").read_text(encoding="utf-8").replace("return value", "return min(max(value, lower), upper)")
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"code": code, "explanation": "fixture"})}}], "usage": self.usage}


def test_output_that_fills_the_server_context_is_not_offered_for_approval(tmp_path):
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, UsageModel(3584, 512), context_tokens=4096)
    assert state["status"] == "model_error" and "context window of 4096" in state["error"]
    assert state["config"]["context_tokens"] == 4096
    assert not (run / "attempt-1" / "proposal.json").exists()
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, UsageModel(3584, 511), context_tokens=4096)
    assert state["status"] in ("awaiting_approval", "policy_blocked")
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, UsageModel(9000, 900))
    assert "context_tokens" not in state["config"] and state["status"] != "model_error" and state["config"]["max_tokens"] == 1600


class MismatchModel(UsageModel):
    def server_context(self):
        return 4096


def test_proposal_from_a_server_with_another_context_is_rejected(tmp_path):
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, MismatchModel(100, 50), context_tokens=8192)
    assert state["status"] == "model_error" and "Server context mismatch" in state["error"]


def test_output_budget_and_context_overflow_are_reported_separately(tmp_path):
    class Cut(UsageModel):
        def propose(self, *args, **kwargs):
            r = super().propose(*args)
            r["choices"][0]["finish_reason"] = "length"
            self.kwargs = kwargs
            return r
    model = Cut(2891, 1600)
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, model, context_tokens=4096, max_tokens=1600)
    assert "Output incomplete: finish_reason=length after 1600" in state["error"] and "Context overflow" in state["error"]
    assert state["config"]["max_tokens"] == 1600 and model.kwargs == {}  # default budget: not passed explicitly
