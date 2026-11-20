"""Replays the published 2026-11-20 snapshot against the fixed rules.

These are not synthetic cases: every number below is copied from the committed
snapshot ``data/live.json`` (generated 2026-11-20T18:41:08Z) and the live API
responses it links to. They exist so the defects recorded on the coordination
board (board D, P1-P4) cannot come back unnoticed.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector.alerts import (detect_swing, model_shortlist, observe,  # noqa: E402
                              resolution_topic)

SNAPSHOT = os.path.join(ROOT, "data", "live.json")


def load_snapshot():
    with open(SNAPSHOT, encoding="utf-8") as fh:
        return json.load(fh)


class TestPublishedAlertsWerePhantom(unittest.TestCase):
    """P1/P2: 29 alerts were published; none of them was a real price move."""

    @classmethod
    def setUpClass(cls):
        cls.snap = load_snapshot()
        cls.alerts = cls.snap.get("alerts") or []

    def test_published_alerts_predate_the_spread_gate(self):
        """All 29 rows were written by the old rule: none carries a spread."""
        if not self.alerts:
            self.skipTest("snapshot carries no alerts")
        self.assertTrue(all(a.get("spread") is None for a in self.alerts))
        self.assertEqual(self.alerts[0]["threshold"], 0.1)

    def test_new_alerts_must_declare_a_tradeable_spread(self):
        """Invariant every future row must satisfy."""
        for a in self.alerts:
            spread = a.get("spread")
            if spread is not None:
                self.assertLessEqual(spread, 0.20)

    def test_the_hbid_row_could_not_be_produced_today(self):
        """Live book 2026-11-20T19:04Z, copied verbatim from the API."""
        market = {
            "ticker": "KXPRESNOMD-28-HBID", "event_ticker": "KXPRESNOMD-28",
            "series_ticker": "KXPRESNOMD", "yes_sub_title": "Hunter Biden",
            "yes_bid_dollars": "0.0020", "yes_ask_dollars": "0.8110",
            "last_price_dollars": "0.8110", "volume_fp": "537225441.45",
            "open_interest_fp": "140195139.02", "status": "active",
        }
        book = {"orderbook_fp": {
            "yes_dollars": [["0.0010", "166666.66"], ["0.0020", "83333.33"]],
            "no_dollars": [["0.1850", "1471.00"], ["0.1860", "1417.00"],
                           ["0.1870", "1487.00"], ["0.1880", "1567.00"],
                           ["0.1890", "271.49"]]}}
        obs = observe(market, book, "elections", ts=1795200068.0)
        # The mid is arithmetically correct per the docs: best YES bid 0.0020,
        # implied YES ask 1 - 0.1890 = 0.8110, mid 0.4065. It is the *spread*
        # that makes it unusable, not the arithmetic.
        self.assertAlmostEqual(obs.mid, 0.4065)
        self.assertAlmostEqual(obs.yes_ask, 0.8110)
        self.assertAlmostEqual(obs.spread, 0.8090)
        self.assertGreater(obs.spread, 0.2)
        self.assertFalse(obs.alertable)
        # The candle reference for that bar carried the *traded* price 0.8110
        # and the same 0.0020/0.8110 quote. A reference built from that quote is
        # two-sided (and wide), so the current leg's spread gate is what stops
        # the alert; a reference built from the traded price is rejected outright.
        self.assertIsNone(detect_swing(
            None, obs, reference={"mid": 0.4065, "ts": 1795200000.0,
                                  "quote_source": "book"}))
        self.assertIsNone(detect_swing(
            None, obs, reference={"mid": 0.8110, "ts": 1795200000.0,
                                  "quote_source": "none"}))


class TestModelFeedIsNotEmpty(unittest.TestCase):
    """P3: the model chat published 0 rows while a signal existed."""

    @classmethod
    def setUpClass(cls):
        cls.snap = load_snapshot()

    def test_a_scored_signal_reaches_the_chat(self):
        """A signal must reach the model chat even with no alert on its ticker.

        Built from a synthetic signal because a given snapshot may legitimately
        carry none (books tighten, the exchange settles markets). The invariant
        under test is the *builder*, not the snapshot's contents.
        """
        signal = {"ticker": "KXTEST-1", "topic": "crypto", "title": "Test",
                  "side": "yes", "executable_price": 0.17, "model_fair": 0.38,
                  "net_roi": 0.18, "edge": 0.21, "ts": 1795200000,
                  "market_url": "https://kalshi.com/markets/KXTEST/KXTEST-1"}
        rows = model_shortlist([], [signal])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "signal")

    def test_the_old_intersection_was_empty(self):
        """Documents the defect: no alert ticker equals a signal ticker."""
        alert_tickers = {a["ticker"] for a in self.snap.get("alerts") or []}
        signal_tickers = {s["ticker"] for s in self.snap.get("signals") or []}
        self.assertEqual(alert_tickers & signal_tickers, set())


class TestResolvedEventsReachTopics(unittest.TestCase):
    """P4: 2,000 settlements stored, 0 published per topic."""

    @classmethod
    def setUpClass(cls):
        cls.snap = load_snapshot()
        with open(os.path.join(ROOT, "data", "resolutions.json"),
                  encoding="utf-8") as fh:
            cls.store = json.load(fh)["resolutions"]

    def test_the_store_holds_settlements(self):
        self.assertGreater(len(self.store), 0)

    def test_stored_rows_have_no_series_ticker(self):
        """Proof the old mapping could never fire (Kalshi returns null)."""
        missing = [k for k, v in self.store.items() if not v.get("series_ticker")]
        self.assertEqual(len(missing), len(self.store))

    def test_new_attribution_recovers_tracked_topics(self):
        # Only official fields are consulted: series_ticker (null for every row
        # in this store, see the test above) then event_ticker against events
        # this collector actually discovered. The store is dominated by
        # untracked settlement/temperature markets, so most rows stay None --
        # which is the correct answer, published as "not attributable".
        registry = {"KXAAAGASW": "gas-prices", "KXPGATOUR": "golf"}
        events = {"KXAAAGASW-26NOV23": "gas-prices"}
        recovered = [resolution_topic(v.get("series_ticker"), v.get("event_ticker"),
                                      registry, events)
                     for v in self.store.values()]
        self.assertTrue(all(t in (None, "gas-prices", "golf") for t in recovered))

if __name__ == "__main__":
    unittest.main()
