"""Exercise a real local gateway, auth denial, route denial, restart and outage."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qwen_agent.gateway import create_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--output", type=Path, default=Path("evidence/local-ops.json"))
    args = parser.parse_args()
    token = secrets.token_hex(32)
    checks = []
    def request(port, path, auth=True, body=None):
        headers = {"Authorization": "Bearer " + token} if auth else {}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(urllib.request.Request(f"http://127.0.0.1:{port}" + path, headers=headers, data=body), timeout=180) as response:
                return response.status, response.read(262144).decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()
    def run_server(upstream, port=0):
        server = create_server(upstream, token, port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread
    def stop(server, thread):
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    def check(name, port, path, expected, **kwargs):
        status, body = request(port, path, **kwargs)
        checks.append({"check": name, "expected_status": expected, "actual_status": status, "passed": status == expected, "response": body[:2000]})
    server, thread = run_server(args.upstream)
    port = server.server_port
    try:
        check("missing_auth", port, "/v1/models", 401, auth=False)
        check("valid_auth", port, "/v1/models", 200)
        check("health", port, "/health", 200)
        check("model_management_disabled", port, "/api/pull", 404)
        check("alternate_inference_route_disabled", port, "/invocations", 404)
        body = json.dumps({"model": "qwen2.5-coder:1.5b", "messages": [{"role": "user", "content": "Reply with READY"}], "max_tokens": 8, "stream": False, "temperature": 0}).encode()
        check("real_authenticated_inference", port, "/v1/chat/completions", 200, body=body)
        check("metrics", port, "/metrics", 200)
    finally:
        stop(server, thread)
    # Restart on the same port; no token or code is written to evidence.
    server, thread = run_server(args.upstream, port)
    try:
        check("gateway_restart_recovery", port, "/health", 200)
    finally:
        stop(server, thread)
    # Reserve then release a loopback port with no service, to simulate an outage.
    reserved, idle = run_server(args.upstream)
    unavailable_port = reserved.server_port
    stop(reserved, idle)
    server, thread = run_server(f"http://127.0.0.1:{unavailable_port}/v1")
    try:
        check("upstream_outage_fails_closed", server.server_port, "/health", 503)
    finally:
        stop(server, thread)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"backend": "real local Ollama", "checks": checks, "all_passed": all(c["passed"] for c in checks), "note": "Gateway restart/outage checks; does not test Docker restart or GPU fault recovery."}, indent=2), encoding="utf-8")
    print(args.output)
    return 0 if all(c["passed"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
