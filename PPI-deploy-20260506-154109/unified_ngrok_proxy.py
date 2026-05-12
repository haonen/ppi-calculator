from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HOST = os.getenv("PPI_PUBLIC_PROXY_HOST", "0.0.0.0")
PORT = int(os.getenv("PPI_PUBLIC_PROXY_PORT", "9000"))
BACKEND_ORIGIN = os.getenv("PPI_PUBLIC_PROXY_BACKEND", "http://127.0.0.1:8000")
FRONTEND_DIR = Path(__file__).parent / "base-extension"


def copy_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    blocked = {
        "connection",
        "content-encoding",
        "content-length",
        "transfer-encoding",
    }
    return [(key, value) for key, value in headers if key.lower() not in blocked]


class Handler(BaseHTTPRequestHandler):
    write_body = True

    def end_common_headers(self, length: int | None = None) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-PPI-Trigger-Token")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_common_headers(0)

    def proxy_backend(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        request = Request(
            f"{BACKEND_ORIGIN}{self.path}",
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            with urlopen(request, timeout=300) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in copy_headers(response.headers.items()):
                    self.send_header(key, value)
                self.end_common_headers(len(payload))
                if self.write_body:
                    self.wfile.write(payload)
        except HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            for key, value in copy_headers(exc.headers.items()):
                self.send_header(key, value)
            self.end_common_headers(len(payload))
            if self.write_body:
                self.wfile.write(payload)
        except URLError as exc:
            payload = f'{{"ok": false, "error": "Backend unavailable: {exc.reason}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_common_headers(len(payload))
            if self.write_body:
                self.wfile.write(payload)

    def serve_frontend(self) -> None:
        route = self.path.split("?", 1)[0]
        if route in {"", "/"}:
            route = "/ppi-feishu-entry.html"
        file_path = (FRONTEND_DIR / route.lstrip("/")).resolve()
        if FRONTEND_DIR.resolve() not in file_path.parents and file_path != FRONTEND_DIR.resolve():
            self.send_error(403)
            return
        if not file_path.is_file():
            self.send_error(404)
            return
        payload = file_path.read_bytes()
        content_type = "text/html; charset=utf-8" if file_path.suffix == ".html" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_common_headers(len(payload))
        if self.write_body:
            self.wfile.write(payload)

    def do_GET(self) -> None:
        route = self.path.split("?", 1)[0]
        if route in {"/health", "/version"} or route.startswith("/jobs/"):
            self.proxy_backend()
            return
        self.serve_frontend()

    def do_HEAD(self) -> None:
        self.write_body = False
        try:
            self.do_GET()
        finally:
            self.write_body = True

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] == "/run-ppi":
            self.proxy_backend()
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[public-proxy] {self.address_string()} - {format % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"PPI public proxy listening on http://{HOST}:{PORT}")
    print(f"Forwarding backend calls to {BACKEND_ORIGIN}")
    server.serve_forever()


if __name__ == "__main__":
    main()
