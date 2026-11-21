"""Tests for the local server's same-origin order-book proxy.

`server/app.py` gained `GET /api/orderbooks` in session `arena-f3cb9b9f` so the
live pulse can still measure real books when a browser cannot reach the demo API
directly. The proxy must pass Kalshi's response through unchanged — the page
parses one shape either way — and it must never synthesise a book for a ticker
Kalshi did not return.

The network is stubbed with a payload captured from the live demo API during
this session (GET /markets/orderbooks?tickers=KXPRESNOMD-28-RW, 2026-11-21
06:44Z), so the test is offline and deterministic while still asserting on real
field shapes.

Official source for the endpoint:
https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
"""

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector import kalshi_api  # noqa: E402
from server import app as server_app  # noqa: E402

# Captured from the live endpoint; not fabricated.
CAPTURED = {
    "orderbooks": [{
        "ticker": "KXPRESNOMD-28-RW",
        "orderbook_fp": {
            "no_dollars": [["0.9600", "20833.30"], ["0.9610", "423.25"]],
            "yes_dollars": [["0.0370", "18018.00"], ["0.0380", "13869.69"]],
        },
    }]
}


class _StubClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def orderbooks(self, tickers):
        _StubClient.calls += 1
        return {e["ticker"]: e["orderbook_fp"] for e in CAPTURED["orderbooks"]
                if e["ticker"] in tickers}


class TestOrderbookProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._real = server_app.KalshiClient
        server_app.KalshiClient = _StubClient
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_app.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        server_app.KalshiClient = cls._real

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, json.loads(r.read())

    def test_returns_the_documented_shape(self):
        status, body = self._get("/api/orderbooks?tickers=KXPRESNOMD-28-RW")
        self.assertEqual(status, 200)
        self.assertIn("orderbooks", body)
        entry = body["orderbooks"][0]
        self.assertEqual(entry["ticker"], "KXPRESNOMD-28-RW")
        self.assertIn("yes_dollars", entry["orderbook_fp"])
        self.assertIn("no_dollars", entry["orderbook_fp"])

    def test_quote_derived_through_the_documented_rules(self):
        """best bid = LAST level; implied YES ask = 1 - best NO bid."""
        _, body = self._get("/api/orderbooks?tickers=KXPRESNOMD-28-RW")
        fp = body["orderbooks"][0]["orderbook_fp"]
        best_yes = float(fp["yes_dollars"][-1][0])
        best_no = float(fp["no_dollars"][-1][0])
        self.assertEqual(best_yes, 0.0380)
        self.assertAlmostEqual(1 - best_no, 0.0390, places=4)
        self.assertAlmostEqual((best_yes + 1 - best_no) / 2, 0.0385, places=4)

    def test_an_unknown_ticker_is_omitted_never_invented(self):
        _, body = self._get("/api/orderbooks?tickers=KXPRESNOMD-28-RW,NOT-A-MARKET")
        self.assertEqual([e["ticker"] for e in body["orderbooks"]],
                         ["KXPRESNOMD-28-RW"])

    def test_missing_tickers_is_a_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/orderbooks")
        self.assertEqual(ctx.exception.code, 400)

    def test_at_most_100_tickers_are_forwarded(self):
        many = ",".join(f"T{i}" for i in range(150))
        status, _ = self._get(f"/api/orderbooks?tickers={many}")
        self.assertEqual(status, 200)  # stub accepts any subset

    def test_unreachable_api_is_a_gateway_error_not_a_fake_book(self):
        class Boom:
            def __init__(self, *a, **k):
                pass

            def orderbooks(self, tickers):
                raise kalshi_api.KalshiHTTPError(
                    0, "TLS/SSL connection has been closed", "demo")
        real = server_app.KalshiClient
        server_app.KalshiClient = Boom
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get("/api/orderbooks?tickers=KXPRESNOMD-28-RW")
            self.assertEqual(ctx.exception.code, 502)
        finally:
            server_app.KalshiClient = real


if __name__ == "__main__":
    unittest.main()
