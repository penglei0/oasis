#!/usr/bin/env python3
"""Minimal server-local visitor counter for the static benchmark report."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = "127.0.0.1"
PORT = 9992
COUNT_FILE = Path(os.environ.get("VISITOR_COUNT_FILE", "/var/lib/http-benchmark/visitor_count.json"))
LOCK = threading.Lock()


def read_count() -> int:
    try:
        return int(json.loads(COUNT_FILE.read_text(encoding="utf-8")).get("count", 0))
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def write_count(count: int) -> None:
    COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = COUNT_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"count": count}) + "\n", encoding="utf-8")
    temporary.replace(COUNT_FILE)


class VisitorHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # pylint: disable=invalid-name
        query = parse_qs(urlparse(self.path).query)
        with LOCK:
            count = read_count()
            if query.get("increment") == ["1"]:
                count += 1
                write_count(count)
        body = json.dumps({"count": count}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), VisitorHandler).serve_forever()
