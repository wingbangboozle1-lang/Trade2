"""Optional local live server — for a trader who wants faster-than-cron updates.

    python3 live/server.py            # serves the site on http://0.0.0.0:8080
    python3 live/server.py --port 9000

What it does (local use only; the GitHub Pages site never depends on it):
  * serves docs/ as static files (same files Pages publishes)
  * GET /api/snapshot  -> live snapshot fetched straight from the Kalshi demo REST
    API (top tracked markets + their order books), cached for a few seconds
  * GET /api/stream    -> Server-Sent Events pushing that snapshot every 5s, which
    the front-end auto-detects; on GitHub Pages this endpoint does not exist, the
    page falls back to polling the published JSON (docs/data/*.json) every 20s.

This is the concrete "make it more live" suggestion implemented: same UI, two
data speeds, zero extra infrastructure on the published site.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, ROOT)

from collector.kalshi import DEMO_BASE, KalshiClient  # noqa: E402

CACHE_TTL = 4.0
_lock = threading.Lock()
_cache: Dict[str, Any] = {"t": 0.0, "payload": None}


def build_snapshot() -> Dict[str, Any]:
    """Fetch a compact live snapshot: tracked open markets + their books."""
    with _lock:
        if _cache["payload"] and time.time() - _cache["t"] < CACHE_TTL:
            return _cache["payload"]
    client = KalshiClient(min_interval=0.3, max_retries=2, timeout=8)
    # reuse the published topic list so local mode and Pages mode agree
    topics_path = os.path.join(DOCS, "data", "series.json")
    series: Dict[str, str] = {}
    if os.path.exists(topics_path):
        try:
            with open(topics_path, encoding="utf-8") as fh:
                for row in json.load(fh).get("rows", []):
                    series[row["ticker"]] = row["topic"]
        except Exception:
            series = {}
    markets = client.markets(status="open", limit=200, max_pages=1)
    rows = []
    for m in markets:
        st = str(m.get("series_ticker") or "")
        topic = series.get(st) or series.get(st.split("-")[0])
        if topic:
            rows.append(m)
        if len(rows) >= 40:
            break
    books = {}
    for m in rows[:10]:
        try:
            books[m["ticker"]] = client.orderbook(m["ticker"], depth=15)
        except Exception:
            books[m["ticker"]] = {}
    payload = {"fetched_at": int(time.time()), "source": DEMO_BASE, "markets": rows, "books": books}
    with _lock:
        _cache.update(t=time.time(), payload=payload)
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/snapshot":
            try:
                payload = json.dumps(build_snapshot()).encode()
                self._send(200, payload, "application/json")
            except Exception as exc:
                self._send(502, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                for _ in range(120):  # ~10 min per connection, client reconnects
                    data = json.dumps(build_snapshot())
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(5)
            except (BrokenPipeError, ConnectionResetError):
                return
            return
        # static file serving from docs/
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = os.path.normpath(os.path.join(DOCS, rel))
        if not target.startswith(DOCS) or not os.path.isfile(target):
            self._send(404, b"not found", "text/plain")
            return
        ctype = "text/html; charset=utf-8"
        if target.endswith(".css"):
            ctype = "text/css"
        elif target.endswith(".js"):
            ctype = "application/javascript"
        elif target.endswith(".json"):
            ctype = "application/json"
        elif target.endswith(".png") or target.endswith(".jpg"):
            ctype = "image/jpeg"
        with open(target, "rb") as fh:
            self._send(200, fh.read(), ctype)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    print(f"serving docs/ on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    print("live endpoints: /api/snapshot  /api/stream")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
