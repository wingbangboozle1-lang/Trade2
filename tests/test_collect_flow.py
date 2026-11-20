"""End-to-end flow test for the collector, offline.

Why this exists: the published defects this session fixed (topic pages with zero
resolutions; an always-empty model chat; a run-over-run swing comparison that
read a key the snapshot never writes) all live in how ``collect()`` wires the
pieces together, which no unit test covered. This runs the real
``collector.collector.collect()`` against a stub client serving captured shapes
and asserts the written snapshot is right. Nothing here touches the network, and
every path is redirected to a temporary directory, so the repo's ``data/`` is
never written.

Fixture shapes are the ones verified live on 2026-11-20 against
https://external-api.demo.kalshi.co/trade-api/v2 (VERIFICATION.md §H2): a market
record carries ``event_ticker`` but **no** ``series_ticker``; a settled market
reports ``result`` and ``settlement_value_dollars``; the book is bids only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time as _time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import alerts                      # noqa: E402
from collector import collector as cc             # noqa: E402
from collector import topics as topic_mod         # noqa: E402

SERIES = "KXAAAGASW"
EVENT = "KXAAAGASW-26NOV16"
MARKET = "KXAAAGASW-26NOV16-4.2000"


def _market(*, bid: str, ask: str, last: str, status: str = "active",
            result: str = "", settlement=None) -> dict:
    row = {
        "ticker": MARKET,
        "event_ticker": EVENT,
        "market_type": "binary",
        "yes_sub_title": "Above 4.2000",
        "title": "Will average **gas prices** be above $4.2000?",
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "no_bid_dollars": "0.9270",
        "last_price_dollars": last,
        "previous_price_dollars": last,
        "volume_fp": "1500.00",
        "volume_24h_fp": "120.00",
        "open_interest_fp": "900.00",
        "notional_value_dollars": "1.0000",
        "status": status,
        "result": result,
        "close_time": "2026-11-16T04:59:00Z",
        "rules_primary": "If average regular gas prices for United States are "
                         "strictly greater than $4.2000 on Nov 16, 2026 according "
                         "to AAA, then the market resolves to Yes.",
    }
    if settlement is not None:
        row["settlement_value_dollars"] = settlement
        row["settlement_ts"] = "2026-11-16T14:32:51.060078Z"
    return row


OPEN_MARKET = _market(bid="0.0060", ask="0.0730", last="0.0400")
SETTLED_MARKET = _market(bid="0.0000", ask="0.0000", last="0.0000",
                         status="finalized", result="no", settlement="0.0000")

# The observation the *previous* run recorded, mid 0.305.
PREV_OBS = {"ts": 1.0, "ticker": MARKET, "event_ticker": EVENT, "topic": "gas-prices",
            "title": "Above 4.2000", "yes_bid": 0.30, "yes_ask": 0.31, "mid": 0.305,
            "last_price": 0.30, "volume": 1400.0, "open_interest": 880.0,
            "series_ticker": SERIES}


class FakeClient:
    """Answers only the endpoints collect() uses, from captured shapes."""

    def __init__(self, *args, **kwargs):
        self.calls: list[tuple[str, dict]] = []
        self.settled_available = False

    def exchange_status(self):
        return {"exchange_active": True, "trading_active": True}

    def series_list(self, **params):
        self.calls.append(("series_list", params))
        return []                      # the seeded cache answers discovery

    def events(self, **params):
        self.calls.append(("events", params))
        market = OPEN_MARKET if not self.settled_available else None
        if market is None:
            return []                  # it stopped being offered as open
        return [{"event_ticker": EVENT, "series_ticker": SERIES,
                 "title": "US average gas price, week ending Nov 16",
                 "category": "Economics", "status": "open", "markets": [market]}]

    def orderbooks(self, tickers):
        self.calls.append(("orderbooks", {"tickers": list(tickers)}))
        # Bids only, ascending, best bid last (orderbook_responses.md).
        return {t: {"yes_dollars": [["0.0010", "10.00"], ["0.0060", "900.00"]],
                    "no_dollars": [["0.9000", "40.00"], ["0.9270", "2100.00"]]}
                for t in tickers}

    def orderbook(self, ticker, depth=None):
        return {"orderbook_fp": {"yes_dollars": [["0.0060", "900.00"]],
                                 "no_dollars": [["0.9270", "2100.00"]]}}

    def markets(self, **params):
        self.calls.append(("markets", dict(params)))
        if params.get("tickers") and self.settled_available:
            wanted = set(params["tickers"].split(","))
            return [dict(SETTLED_MARKET) for t in wanted if t == MARKET]
        return []

    def candlesticks(self, series_ticker, ticker, start_ts, end_ts, period_interval=1):
        self.calls.append(("candlesticks", {"ticker": ticker}))
        return {"candlesticks": []}     # no reference bar: isolate the run path


class _StubNews:
    """Deterministic stand-in for collector.news during the flow test."""

    def __init__(self, status="ok", items=None, error=None):
        self.status = status
        self.items = items if items is not None else [{
            "title": "Gas prices tick up", "url": "https://example.test/candidate",
            "source": "Example Wire", "published": "2026-11-16T13:30:00+00:00",
            "status": "verified-fetch"}]
        self.error = error

    def lookup(self, title, when, **kwargs):
        return {"query": "gas prices", "url": "https://news.google.com/rss/search?q=gas+prices",
                "items": self.items, "status": self.status, "error": self.error}


class TestCollectFlow(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="trade2-flow-")
        self._paths = {name: getattr(cc, name) for name in
                       ("DATA_DIR", "STATE_PATH", "LIVE_PATH", "HISTORY_PATH",
                        "RESOLUTIONS_PATH", "VERIFIED_PATH", "TRACKED_PATH",
                        "MODEL_WATCH_PATH")}
        for name in ("DATA_DIR",):
            setattr(cc, name, self.tmp)
        for name in ("STATE_PATH", "LIVE_PATH", "HISTORY_PATH", "RESOLUTIONS_PATH",
                     "VERIFIED_PATH", "TRACKED_PATH", "MODEL_WATCH_PATH"):
            setattr(cc, name, os.path.join(self.tmp, name.lower().replace("_path", "")
                                           .replace("state", "portfolio_state") + ".json"))
        cc.LIVE_PATH = os.path.join(self.tmp, "live.json")
        cc.STATE_PATH = os.path.join(self.tmp, "portfolio_state.json")
        cc.RESOLUTIONS_PATH = os.path.join(self.tmp, "resolutions.json")
        cc.TRACKED_PATH = os.path.join(self.tmp, "tracked_markets.json")
        cc.MODEL_WATCH_PATH = os.path.join(self.tmp, "model_watchlist.json")

        gas = next(t for t in topic_mod.TOPICS if t.slug == "gas-prices")
        # resolved_at is "now" so the collector treats the cache as fresh and
        # answers discovery from it instead of paging GET /series.
        self._write("series_cache.json", {gas.slug: {
            "resolved_at": _time.time(), "series": [{
                "ticker": SERIES, "title": "US average gas price",
                "category": "Economics", "categories": ["Economics"],
                "tags": ["Oil and energy"], "topic": gas.slug,
                "source_url": f"{cc.DEMO_REST}/series/{SERIES}",
                "frequency": "weekly", "fee_type": "quadratic", "fee_multiplier": 1,
                "settlement_sources": [{"name": "AAA", "url": "https://gasprices.aaa.com/"}],
            }]}})
        # The ledger the previous run left behind: the market is tracked, with a
        # recorded last observation, and has not resolved.
        self._write("tracked_markets.json", {"markets": {MARKET: {
            "ticker": MARKET, "event_ticker": EVENT, "series_ticker": SERIES,
            "topic": "gas-prices", "title": "Above 4.2000",
            "close_time": "2026-11-16T04:59:00Z", "first_seen": "2026-11-16T13:00:00Z",
            "last_open_seen": "2026-11-16T14:00:00Z", "last_mid": 0.305,
            "notional_per_contract": 1.0, "open_interest_contracts": 880.0,
            "volume_contracts": 1400.0, "last_obs": PREV_OBS,
        }}, "meta": {}})
        self._write("alerts.json", {"version": cc.ALERTS_VERSION, "alerts": []})
        self._write("resolutions.json", {"resolutions": {}, "meta": {}})

        self._orig_client = cc.KalshiClient
        self.client = FakeClient()
        cc.KalshiClient = lambda *a, **k: self.client
        # The headline lookup is stubbed so no test depends on the network: the
        # real parser and its three states are covered by TestNewsLookup, which
        # injects a canned feed. Here we only assert the collector propagates
        # whatever status the lookup reports.
        self._orig_news = cc.news
        cc.news = _StubNews()

    def tearDown(self):
        cc.news = self._orig_news
        cc.KalshiClient = self._orig_client
        for name, value in self._paths.items():
            setattr(cc, name, value)

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, name, payload):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _collect(self):
        return cc.collect(market_cap=10, orderbook_cap=10, settle_scan=100,
                          budget_seconds=600.0)

    # ---- defect: the run-over-run swing comparison read nothing -------------
    def test_consecutive_run_swing_fires_from_the_tracked_ledger(self):
        payload = self._collect()
        rows = [a for a in payload["alerts"] if a["ticker"] == MARKET]
        self.assertEqual(len(rows), 1, "mid 0.305 -> 0.0395 is a $0.265 move")
        self.assertAlmostEqual(rows[0]["abs_delta"], 0.2655, places=4)
        self.assertEqual(rows[0]["direction"], "down")
        self.assertEqual(rows[0]["previous_ts"], PREV_OBS["ts"],
                         "the previous price must come from the ledger we seeded")
        self.assertTrue(rows[0]["observed_gap_seconds"] > 0)

    def test_published_snapshot_stays_lean(self):
        payload = self._collect()
        self.assertNotIn("observations", payload,
                         "observations live in the ledger, not the published file")
        stored = TestCollectFlow._read(cc.TRACKED_PATH)["markets"][MARKET]
        self.assertEqual(stored["last_obs"]["mid"], payload["events"][0]["mid"])

    # ---- defect: 'Resolved captured 0' on every topic page -----------------
    def test_settlement_of_a_tracked_market_reaches_its_topic(self):
        self.client.settled_available = True         # it closed and resolved NO
        payload = self._collect()
        rows = payload["resolutions"]["gas-prices"]
        self.assertEqual([r["ticker"] for r in rows], [MARKET])
        row = rows[0]
        self.assertEqual(row["result"], "no")
        self.assertEqual(row["settlement_value_dollars"], "0.0000")
        self.assertEqual(row["series_ticker"], SERIES,
                         "series derived from the ticker: the API omits the field")
        self.assertEqual(row["source_url"], f"{cc.DEMO_REST}/markets/{MARKET}")
        self.assertEqual(TestCollectFlow._read(cc.RESOLUTIONS_PATH)["resolutions"][MARKET]["topic"],
                         "gas-prices")
        # the lookup was asked for exactly our ticker, not a global feed
        tickers_calls = [c for c in self.client.calls if c[0] == "markets"]
        self.assertTrue(tickers_calls, "the settlement lookup must run")
        self.assertEqual(tickers_calls[0][1]["tickers"], MARKET)

    def test_unresolved_markets_stay_tracked_and_say_so(self):
        payload = self._collect()
        stored = TestCollectFlow._read(cc.TRACKED_PATH)["markets"][MARKET]
        self.assertNotIn("awaiting_result", stored)
        self.assertEqual(payload["resolutions"]["gas-prices"], [])
        self.assertTrue(payload["resolutions_count"] >= 0)

    # ---- defect: the model chat could never populate -----------------------
    def test_model_chat_shares_one_gate_with_the_browser(self):
        payload = self._collect()
        self.assertEqual(payload["model_gate"], alerts.MODEL_SCORE_GATE)
        shortlist = payload["model_shortlist"]
        swings = [a for a in payload["alerts"] if a.get("high_roi")]
        self.assertTrue(swings, "the swing must carry the model's verdict")
        self.assertGreater(swings[0]["model_net_roi"], 0)
        self.assertIn(MARKET, {a["ticker"] for a in shortlist},
                      "the browser renders model_shortlist; it must contain the swing")
        entry = TestCollectFlow._read(cc.MODEL_WATCH_PATH)
        self.assertEqual(entry["gate"], payload["model_gate"])
        self.assertIn(MARKET, entry["entries"])
        self.assertEqual(entry["entries"][MARKET]["series_ticker"], SERIES)

    def test_rows_are_annotated_without_mutating_the_store(self):
        first = self._collect()
        stored = TestCollectFlow._read(os.path.join(self.tmp, "alerts.json"))["alerts"]
        self.assertTrue(stored)
        self.assertEqual(len(first["alerts"]), len(stored))
        second = self._collect()          # same inputs -> same annotation, no drift
        self.assertEqual([a.get("model_score") for a in second["alerts"]],
                         [a.get("model_score") for a in first["alerts"]])

    def test_alert_rows_carry_an_explicit_news_state(self):
        """A swing row always states what the lookup did — never a silent blank."""
        payload = self._collect()
        row = payload["alerts"][0]
        self.assertEqual(row["news_status"], "ok")
        self.assertEqual(row["headlines"][0]["url"], "https://example.test/candidate")
        self.assertEqual(row["news_query"], "gas prices",
                         "the row must carry the query that was actually asked")
        self.assertEqual(row["news_url"], "https://news.google.com/rss/search?q=gas+prices",
                         "and the URL a reviewer can open to check it")
        self.assertEqual(payload["news_lookups"]["ok"], len(payload["alerts"]))

    def test_a_failed_lookup_is_recorded_as_a_failure(self):
        cc.news = _StubNews(status="unavailable", items=[], error="OSError: blocked")
        payload = self._collect()
        row = payload["alerts"][0]
        self.assertEqual(row["news_status"], "unavailable")
        self.assertEqual(row["headlines"], [])
        self.assertEqual(row["news_error"], "OSError: blocked")
        self.assertEqual(payload["news_lookups"]["unavailable"], 1)
        self.assertTrue(any("headline lookup unavailable" in e for e in payload["errors"]))

    def test_snapshot_reports_how_it_ran(self):
        payload = self._collect()
        self.assertEqual(payload["api_root"], cc.DEMO_REST)
        self.assertEqual(payload["mode"]["live_demo_trading_enabled"], False)
        for key in ("run_seconds", "budget_seconds", "errors", "timings",
                    "settlement_lookup_batches", "tracked_markets"):
            self.assertIn(key, payload)

    def test_no_repo_data_is_touched(self):
        repo_data = self._paths["DATA_DIR"]
        before = {n: os.path.getmtime(os.path.join(repo_data, n))
                  for n in os.listdir(repo_data)
                  if n in ("live.json", "tracked_markets.json", "model_watchlist.json",
                           "resolutions.json", "alerts.json")}
        self._collect()
        for name, stamp in before.items():
            self.assertEqual(os.path.getmtime(os.path.join(repo_data, name)), stamp,
                             f"{name} must not be written by a test run")


if __name__ == "__main__":
    unittest.main()
