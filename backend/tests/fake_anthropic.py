"""API de Anthropic SIMULADA para pruebas sin red ni cargos (no es la integración real).

Imita lo que usa Video Studio AI de la Messages API:

- ``GET /v1/models/{id}``: verificación de la clave (gratuita en la API real).
- ``POST /v1/messages`` con ``stream: true``: eventos SSE con un texto JSON construido a partir
  del esquema pedido (mismas propuestas que el CLI simulado, ``fake_claude.build``).

Claves: ``sk-ant-test-…`` válida; ``sk-ant-test-revoked…`` → 401; ``sk-ant-test-nocredit…`` →
400 por falta de saldo. Modo (``FAKE_ANTHROPIC_MODE``): ok | rate_limit | overloaded | invalid.
``FAKE_ANTHROPIC_LOG`` guarda un resumen de cada llamada (nunca la clave).

Uso independiente: ``python tests/fake_anthropic.py --port 8790``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_claude import build

USAGE = {"input_tokens": 1200, "output_tokens": 800}


def _log(entry: dict) -> None:
    path = os.environ.get("FAKE_ANTHROPIC_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silencio en las pruebas
        return

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, kind: str, message: str) -> None:
        self._json(status, {"type": "error", "error": {"type": kind, "message": message}})

    def _auth(self) -> bool:
        key = self.headers.get("x-api-key", "")
        if not key.startswith("sk-ant-test-") or key.startswith("sk-ant-test-revoked"):
            self._error(401, "authentication_error", "invalid x-api-key")
            return False
        if key.startswith("sk-ant-test-nocredit"):
            self._error(
                400,
                "invalid_request_error",
                "Your credit balance is too low to access the Anthropic API.",
            )
            return False
        return True

    def do_GET(self) -> None:
        _log({"method": "GET", "path": self.path})
        if not self._auth():
            return
        if self.path.startswith("/v1/models/"):
            model = self.path.rsplit("/", 1)[-1]
            if model != "claude-opus-5-5":
                self._error(404, "not_found_error", f"model: {model}")
                return
            self._json(
                200,
                {
                    "type": "model",
                    "id": model,
                    "display_name": "Claude Opus 5.5",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            )
            return
        self._error(404, "not_found_error", "Not found")

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        blocks = body.get("messages", [{}])[0].get("content", [])
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        schema = body.get("output_config", {}).get("format", {}).get("schema", {})
        _log(
            {
                "method": "POST",
                "path": self.path,
                "model": body.get("model"),
                "effort": body.get("output_config", {}).get("effort"),
                "images": sum(1 for b in blocks if b.get("type") == "image"),
                "chars": len(text),
                "schema": sorted(schema.get("properties", {})),
            }
        )
        if not self._auth():
            return
        mode = os.environ.get("FAKE_ANTHROPIC_MODE", "ok")
        if mode == "rate_limit":
            self._error(429, "rate_limit_error", "Number of request tokens has exceeded")
            return
        if mode == "overloaded":
            self._error(529, "overloaded_error", "Overloaded")
            return
        payload = "{no es json" if mode == "invalid" else json.dumps(build(schema, text))
        model = body.get("model")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()

        def event(name: str, data: dict) -> None:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_fake",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": USAGE["input_tokens"], "output_tokens": 1},
                },
            },
        )
        event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
        for i in range(0, len(payload), 400):
            event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": payload[i : i + 400]},
                },
            )
        event("content_block_stop", {"type": "content_block_stop", "index": 0})
        event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": USAGE["output_tokens"]},
            },
        )
        event("message_stop", {"type": "message_stop"})


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Arranca el servidor en un hilo y devuelve (servidor, URL base)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"API simulada en http://127.0.0.1:{args.port}", flush=True)
    srv.serve_forever()
