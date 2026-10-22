"""A tiny fake Ollama server so the app can be tested without models or a GPU."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

REPLY = (
    "Here is a quick example:\n\n```python\ndef add(a, b):\n    return a + b\n```\n\n"
    "Call it with `add(1, 2)`.\n\n- fast\n- simple\n"
)


class Handler(BaseHTTPRequestHandler):
    delay = 0.01
    last_chat: dict = {}   # body of the most recent /api/chat request

    def log_message(self, *args):  # silence
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [
                {"name": "qwen2.5-coder:1.5b", "model": "qwen2.5-coder:1.5b", "size": 986000000},
                {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 4700000000},
            ]})
        elif self.path == "/api/ps":
            self._json({"models": [
                {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b",
                 "size": 4700000000, "size_vram": 2820000000},
            ]})
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Ollama is running")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path != "/api/chat":
            self._json({"error": "not found"}, 404)
            return
        Handler.last_chat = body
        if not body.get("stream", True):
            self._json({"model": body["model"], "done": True,
                        "message": {"role": "assistant", "content": "Test title"}})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        words = REPLY.split(" ")
        try:
            for i, w in enumerate(words):
                piece = w + ("" if i == len(words) - 1 else " ")
                line = {"model": body["model"], "message": {"role": "assistant", "content": piece},
                        "done": False}
                self.wfile.write((json.dumps(line) + "\n").encode())
                self.wfile.flush()
                time.sleep(self.delay)
            self.wfile.write((json.dumps({"model": body["model"], "done": True,
                                          "message": {"role": "assistant", "content": ""}}) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


def start(port: int = 0, delay: float = 0.01) -> tuple[HTTPServer, int]:
    Handler.delay = delay
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
