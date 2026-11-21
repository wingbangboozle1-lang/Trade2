"""Regression tests for the batch order-book request shape (session arena-7695ba1b).

Two defects were found during the final integration pass and are pinned here.

1. `GET /markets/orderbooks` takes `tickers` as a **string[]** query parameter
   ("Required array length: 1 - 100 elements",
   https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks).
   The exchange reads ONE value per occurrence of the parameter, so a
   comma-joined value is read as one ticker whose name contains the commas
   and comes back with an EMPTY book. Verified live on the demo exchange
   2026-11-21 ~07:20Z:

     ?tickers=KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70
       -> one entry, ticker "KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70",
          orderbook_fp {"yes_dollars": [], "no_dollars": []}
     ?tickers=KXPRESNOMD-28-RW&tickers=KXAAAGASM-26NOV30-4.70
       -> two entries, each with its real book.

   The browser pulse shipped the comma form and therefore measured nothing.
   The Python client already used the repeated form
   (`urllib.parse.urlencode(..., doseq=True)` in collector/kalshi_api.py), so
   the published ladders were correct and only the live pulse was affected.

2. `server/app.py`'s proxy read only the FIRST `tickers` value
   (`query.get("tickers")[0]`), so a repeated-parameter request reached the
   proxy with only one ticker. It must accept every occurrence and a
   comma-joined list alike.

These tests are offline: the exchange call is stubbed, and the stub records
exactly which tickers were forwarded.
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

from server import app as server_app  # noqa: E402


class _RecordingClient:
    """Stub exchange client that records the tickers it was asked for."""

    last = []

    def __init__(self, *args, **kwargs):
        pass

    def orderbooks(self, tickers):
        _RecordingClient.last = list(tickers)
        return {t: {"yes_dollars": [["0.0380", "10.00"]],
                    "no_dollars": [["0.9610", "5.00"]]} for t in tickers}


class TestBatchOrderbookShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._real = server_app.KalshiClient
        server_app.KalshiClient = _RecordingClient
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

    def test_repeated_tickers_parameters_are_all_forwarded(self):
        """The documented shape: one `tickers=` occurrence per market."""
        _RecordingClient.last = []
        status, body = self._get(
            "/api/orderbooks?tickers=KXPRESNOMD-28-RW&tickers=KXAAAGASM-26NOV30-4.70")
        self.assertEqual(status, 200)
        self.assertEqual(_RecordingClient.last,
                         ["KXPRESNOMD-28-RW", "KXAAAGASM-26NOV30-4.70"])
        self.assertEqual([e["ticker"] for e in body["orderbooks"]],
                         ["KXPRESNOMD-28-RW", "KXAAAGASM-26NOV30-4.70"])

    def test_a_comma_joined_list_is_still_accepted_by_the_proxy(self):
        """The proxy is lenient on input; the exchange call is not."""
        _RecordingClient.last = []
        self._get("/api/orderbooks?tickers=KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70")
        self.assertEqual(_RecordingClient.last,
                         ["KXPRESNOMD-28-RW", "KXAAAGASM-26NOV30-4.70"])

    def test_a_mixed_form_keeps_every_ticker(self):
        _RecordingClient.last = []
        self._get("/api/orderbooks?tickers=A,B&tickers=C")
        self.assertEqual(_RecordingClient.last, ["A", "B", "C"])

    def test_the_proxy_never_sends_more_than_the_documented_100(self):
        _RecordingClient.last = []
        many = "&".join(f"tickers=T{i}" for i in range(150))
        self._get(f"/api/orderbooks?{many}")
        self.assertEqual(len(_RecordingClient.last), 100)


class TestPythonClientUsesRepeatedParams(unittest.TestCase):
    """The Python client must keep using the repeated form."""

    def test_client_encodes_tickers_as_repeated_query_parameters(self):
        from collector import kalshi_api
        seen = {}

        class _Fake(kalshi_api.KalshiClient):
            def __init__(self, *a, **k):
                pass

            def _request(self, method, path, params=None, **kwargs):
                seen["method"] = method
                seen["path"] = path
                seen["params"] = params
                return {"orderbooks": []}

        client = _Fake()
        client.orderbooks(["A", "B"])
        self.assertEqual(seen["path"], "/markets/orderbooks")
        self.assertEqual(seen["params"], {"tickers": ["A", "B"]})

        # urlencode(..., doseq=True) is what turns the list into repeated
        # `tickers=` occurrences. Assert the encoded form, not just the input.
        import urllib.parse
        encoded = urllib.parse.urlencode(seen["params"], doseq=True)
        self.assertEqual(encoded, "tickers=A&tickers=B")
        self.assertNotIn(",", encoded)


class TestDeskUsesTheDocumentedShape(unittest.TestCase):
    """The browser call site must not re-introduce the comma-joined form.

    A source-level assertion is used on purpose: the defect was a one-line
    URL construction in a browser IIFE that no unit test could reach, and the
    cheapest reliable guard is to require that the call site goes through the
    tested helper.
    """

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "assets", "desk.js"), encoding="utf-8") as fh:
            cls.source = fh.read()

    def test_desk_builds_the_orderbook_url_through_the_tested_helper(self):
        self.assertIn("LiveFeed.batchOrderbookUrl(", self.source)

    def test_desk_never_joins_tickers_with_a_comma(self):
        # The pre-fix line was:
        #   var list = pulse.tickers.map(encodeURIComponent).join(",");
        self.assertNotIn('pulse.tickers.map(encodeURIComponent).join(",")', self.source)
        self.assertNotIn('?tickers=" + list', self.source)

    def test_the_helper_is_exported_by_the_pure_module(self):
        with open(os.path.join(ROOT, "assets", "live-feed.js"), encoding="utf-8") as fh:
            module = fh.read()
        self.assertIn("function batchOrderbookUrl(", module)
        self.assertIn("batchOrderbookUrl: batchOrderbookUrl,", module)


if __name__ == "__main__":
    unittest.main()
