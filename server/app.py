"""Local dashboard server.

Serves the static site from ``docs/`` and exposes a small JSON/SSE API:

  GET /api/live        latest collector snapshot (data/live.json)
  GET /api/stream      Server-Sent Events: pushes the snapshot whenever the
                       collector rewrites it
  GET /api/markets     live market list pulled straight from the Kalshi demo API
                       (so the grapher can poll order books without the browser
                       needing to guess endpoints)
  GET /api/candle      candlesticks for one market, proxied from Kalshi

The Kalshi proxy exists because this container cannot reach Kalshi directly; in
production the browser talks to Kalshi itself (verified CORS) and falls back to
these routes only when that fails.

Bind host comes from HOST (default 0.0.0.0) so the preview proxy can reach it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Allow `python3 server/app.py` without installing anything.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from collector.collector import LIVE_PATH, load_json  # noqa: E402
from collector.kalshi_api import (DEMO_REST, KalshiClient,  # noqa: E402
                                  KalshiHTTPError)
DOCS = ROOT  # GitHub Pages publishes the repo root, so the pages live here


class Handler(SimpleHTTPRequestHandler):
    server_version = "Trade2Dashboard/1.0"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOCS, **kwargs)

    # -- helpers ----------------------------------------------------------
    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")

    # -- routing ----------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/api/live":
            payload = load_json(LIVE_PATH, {"error": "collector has not run yet"})
            return self._json(payload)

        if route == "/api/health":
            return self._json({"ok": True, "ts": time.time(), "docs": DOCS,
                               "live_exists": os.path.exists(LIVE_PATH)})

        if route == "/api/stream":
            return self._stream()

        if route == "/api/markets":
            return self._markets(query)

        if route == "/api/candle":
            return self._candle(query)

        if route == "/api/orderbooks":
            return self._orderbooks(query)

        return super().do_GET()

    # -- SSE --------------------------------------------------------------
    def _stream(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        last_mtime = None
        deadline = time.time() + 300          # cap each connection at 5 minutes
        try:
            while time.time() < deadline:
                try:
                    mtime = os.path.getmtime(LIVE_PATH)
                except OSError:
                    mtime = None
                if mtime and mtime != last_mtime:
                    last_mtime = mtime
                    payload = load_json(LIVE_PATH, {})
                    chunk = f"event: snapshot\ndata: {json.dumps(payload, default=str)}\n\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                else:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                time.sleep(3)
        except (BrokenPipeError, ConnectionResetError):
            return

    # -- Kalshi proxy -----------------------------------------------------
    def _markets(self, query):
        try:
            limit = int((query.get("limit") or ["40"])[0])
        except ValueError:
            limit = 40
        client = KalshiClient(DEMO_REST)
        tickers = (query.get("tickers") or [""])[0]
        try:
            if tickers:
                rows = []
                for ticker in tickers.split(",")[:25]:
                    ticker = ticker.strip()
                    if not ticker:
                        continue
                    book = client.orderbook(ticker, depth=10)
                    rows.append({"ticker": ticker,
                                 "orderbook": book.get("orderbook_fp", {})})
                return self._json({"as_of": time.time(), "books": rows,
                                   "api_root": DEMO_REST})
            markets = client.markets(status="open", limit=min(limit, 200))
            return self._json({"as_of": time.time(), "api_root": DEMO_REST,
                               "markets": markets})
        except KalshiHTTPError as exc:
            return self._json({"error": str(exc), "api_root": DEMO_REST},
                              HTTPStatus.BAD_GATEWAY)

    def _candle(self, query):
        series = (query.get("series") or [""])[0]
        ticker = (query.get("ticker") or [""])[0]
        interval = int((query.get("interval") or ["1"])[0])
        end = int(query.get("end", [str(int(time.time()))])[0])
        start = int(query.get("start", [str(end - 3600)])[0])
        if not series or not ticker:
            return self._json({"error": "series and ticker are required"},
                              HTTPStatus.BAD_REQUEST)
        client = KalshiClient(DEMO_REST)
        try:
            data = client.candlesticks(series, ticker, start, end, interval)
            return self._json(data)
        except KalshiHTTPError as exc:
            return self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)

    def _orderbooks(self, query):
        """Same-origin proxy for GET /markets/orderbooks (the live pulse).

        The browser talks to Kalshi directly when it can — CORS was verified for
        the Pages origin (docs/data/capabilities.json). When it cannot (a
        locked-down network, or a preview origin the exchange has not seen), the
        pulse falls back to this route, so the panel measures the real books
        instead of going dark. The response is passed through unchanged so the
        page parses one shape either way.
        """
        # `tickers` is a string[] query parameter, so the browser sends one
        # occurrence per ticker. Accept every occurrence AND a comma-joined
        # list, so the proxy works with either shape and always forwards the
        # full set to the exchange (which requires the repeated form).
        tickers = []
        for raw in (query.get("tickers") or []):
            for part in raw.split(","):
                part = part.strip()
                if part:
                    tickers.append(part)
        tickers = tickers[:100]
        if not tickers:
            return self._json({"error": "tickers is required"}, HTTPStatus.BAD_REQUEST)
        client = KalshiClient(DEMO_REST)
        try:
            books = client.orderbooks(tickers)
        except KalshiHTTPError as exc:
            return self._json({"error": str(exc), "api_root": DEMO_REST},
                              HTTPStatus.BAD_GATEWAY)
        return self._json({
            "orderbooks": [{"ticker": t, "orderbook_fp": b}
                           for t, b in books.items()],
            "as_of": time.time(),
            "api_root": DEMO_REST,
            "source": "local proxy (same data as GET /markets/orderbooks)",
        })

    # quieter logs
    def log_message(self, fmt, *args):
        if "/api/stream" in str(args[0] if args else ""):
            return
        super().log_message(fmt, *args)


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer already mixes in ThreadingMixIn."""
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = ap.parse_args()
    httpd = Server((args.host, args.port), Handler)
    print(f"serving {DOCS} on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
