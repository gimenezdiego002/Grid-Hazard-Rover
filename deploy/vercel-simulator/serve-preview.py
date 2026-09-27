"""Serve only the static build on loopback with its deployment security headers."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
HEADERS = json.loads((ROOT / "vercel-output-config.json").read_text())["routes"][0]["headers"]


class Preview(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".mjs": "text/javascript", ".wasm": "application/wasm"}

    def do_GET(self):
        if urlsplit(self.path).path in {"/simulator", "/simulator/"}:
            self.path = "/index.html"
        super().do_GET()

    def end_headers(self):
        for name, value in HEADERS.items():
            self.send_header(name, value)
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535")
    if not (ROOT / "dist/index.html").is_file():
        parser.error("Build the static simulator first")
    ThreadingHTTPServer(("127.0.0.1", args.port),
                       partial(Preview, directory=str(ROOT / "dist"))).serve_forever()
