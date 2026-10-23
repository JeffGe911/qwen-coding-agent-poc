"""Loopback-only authenticated PoC proxy. Use a hardened reverse proxy for LAN use."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
import threading
import urllib.error
import urllib.request

from .client import Client


def create_server(upstream, token, port=11436):
    if len(token) < 24:
        raise ValueError("LOCAL_MODEL_API_KEY must contain at least 24 characters")
    client = Client(upstream, "gateway")
    slots = threading.BoundedSemaphore(2)
    metrics = {"requests": 0, "denied": 0, "upstream_errors": 0}
    metrics_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            # Do not log tokens, prompts, completions, or query strings.
            pass

        def send(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            with metrics_lock:
                metrics["requests"] += 1
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                with metrics_lock:
                    metrics["denied"] += 1
                return self.send(401, b'{"error":"unauthorized"}')
            routes = {("GET", "/v1/models"): "/models", ("POST", "/v1/chat/completions"): "/chat/completions", ("GET", "/health"): "/models"}
            if (self.command, self.path) == ("GET", "/metrics"):
                with metrics_lock:
                    body = "".join(f"qwen_gateway_{key}_total {value}\n" for key, value in metrics.items()).encode()
                return self.send(200, body, "text/plain; version=0.0.4")
            if (self.command, self.path) not in routes:
                return self.send(404, b'{"error":"route disabled"}')
            body = None
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.headers.get("Transfer-Encoding") or not 0 < length <= 65536:
                        return self.send(413, b'{"error":"body limit"}')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict) or body.get("stream") is True:
                        return self.send(400, b'{"error":"non-streaming JSON object required"}')
                except (ValueError, OSError):
                    return self.send(400, b'{"error":"invalid request"}')
            if not slots.acquire(blocking=False):
                return self.send(429, b'{"error":"busy; retry later"}')
            try:
                response = client.request(routes[(self.command, self.path)], body)
                if self.path == "/health":
                    response = {"status": "ready", "available_models": len(response.get("data", []))}
                self.send(200, json.dumps(response).encode())
            except (OSError, ValueError, KeyError):
                with metrics_lock:
                    metrics["upstream_errors"] += 1
                self.send(503, b'{"error":"local model unavailable"}')
            finally:
                slots.release()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--port", type=int, default=11436)
    args = parser.parse_args()
    server = create_server(args.upstream, os.environ.get("LOCAL_MODEL_API_KEY", ""), args.port)
    print(f"Authenticated gateway on 127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
