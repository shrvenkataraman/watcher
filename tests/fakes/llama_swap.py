"""Fake llama-swap server: records requests, scripted /running and /v1/chat/completions."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLlamaSwap:
    def __init__(self, running_script=None, completion_status=200, refuse=False):
        # running_script: list of lists of {"model","state"} served to successive GET /running calls;
        # the last entry repeats forever.
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/running":
                    idx = min(outer.running_idx, len(outer.running_script) - 1)
                    outer.running_idx += 1
                    self._send(200, {"running": outer.running_script[idx]})
                else:
                    self._send(404, {"error": "no route"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                outer.requests.append((self.path, raw))
                if self.path.startswith("/api/models/unload/"):
                    outer.unloads.append(self.path.rsplit("/", 1)[-1])
                    self._send(200, {"ok": True})
                elif self.path == "/v1/chat/completions":
                    if outer.completion_status != 200:
                        self._send(outer.completion_status, {"error": "boom"})
                    else:
                        self._send(200, {"choices": [{"message": {"content": "ok"}}]})
                else:
                    self._send(404, {"error": "no route"})

        self.refuse = refuse
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.requests = []
        self.unloads = []
        self.running_idx = 0
        self.running_script = running_script or [[]]
        self.completion_status = completion_status
        if not refuse:
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        if not self.refuse:
            self.server.shutdown()
            self.server.server_close()
