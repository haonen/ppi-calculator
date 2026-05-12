from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
    }

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


def main() -> None:
    host = os.getenv("PPI_FRONTEND_HOST", "0.0.0.0")
    port = int(os.getenv("PPI_FRONTEND_PORT", "5173"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"PPI extension listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
