"""Alert-feed quality rules added by session `arena-dc732aa6` (request R-D-01).

Why these tests exist: the published snapshot of 2026-11-20T18:41Z carried 29
buffered alerts that described only 8 distinct moves, and the largest of them
(Amy Klobuchar -0.8005) was measured as an order-book midpoint against a
reference that was a *trade* close. Both are measured here so they cannot
silently come back.

Official field shapes used by the fixtures:
  * candlesticks  https://docs.kalshi.com/api-reference/market/get-market-candlesticks
  * order book    https://docs.kalshi.com/getting_started/orderbook_responses
  * market record https://docs.kalshi.com/api-reference/market/get-markets
"""

import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.alerts import (ESCALATION_STEP, MODEL_MIN_NET_ROI, SWING_THRESHOLD,
                              Observation, book_record_divergence, clears_model_gate,
                              detect_swing, fold_alerts, high_roi_alerts,
                              swing_rejection)
from collector.collector import bar_reference
from collector import news as news_mod


def obs(mid, ts=1000.0, bid=None, ask=None, yes_size=100.0, no_size=100.0,
        ref_bid=None, ref_ask=None, ref_trade=None, ref_ts=900.0, ticker="T"):
    if bid is None and ask is None and mid is not None:
        bid = ask = mid
    return Observation(ts=ts, ticker=ticker, event_ticker="E-1", topic="elections",
                       title="Sample market", yes_bid=bid, yes_ask=ask, mid=mid,
                       last_price=None, volume=10.0, open_interest=10.0,
                       yes_bid_size=yes_size, no_bid=ask if ask is not None else None,
                       no_bid_size=no_size,
                       ref_ts=ref_ts, ref_yes_bid=ref_bid, ref_yes_ask=ref_ask,
                       ref_trade_close=ref_trade, series_ticker="S")


class TestPriceBasis(unittest.TestCase):
    """The reference must be the same kind of price as the observation."""

    def test_two_sided_candle_quote_becomes_the_reference(self):
        # The collector attaches the candle's own yes_bid / yes_ask closes; the
        # test must equal the reference the site publishes.
        cur = obs(0.43, bid=0.42, ask=0.44, ref_bid=0.30, ref_ask=0.32)
        alert = detect_swing(None, cur)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["basis"], "candle_quote_mid")
        self.assertEqual(alert["reference_basis"], "candle_quote_mid")
        self.assertEqual(alert["previous"], 0.31)   # mid of 0.30 / 0.32
        self.assertAlmostEqual(alert["delta"], 0.12)
        self.assertEqual(alert["price_pair"], "quote mid to quote mid")

    def test_last_trade_reference_is_never_an_alert_but_is_reported(self):
        # The published phantom: mid 0.4065 of a 0.002 / 0.811 book measured
        # against a 0.811 last trade. Refused by the quote rule...
        cur = obs(0.4065, bid=0.002, ask=0.811, ref_trade=0.811, ref_ts=1795200000.0)
        self.assertIsNone(detect_swing(None, cur))
        # ...but recorded as a labelled suppression, so the reviewer still sees
        # the 40-cent midpoint move that the alert rule refused.
        gone = swing_rejection(None, cur, reference=0.811, reference_ts=1795200000.0)
        self.assertIsNotNone(gone)
        self.assertAlmostEqual(gone["abs_delta"], 0.4045, places=4)
        self.assertIn("spread", gone["reason"])
        self.assertEqual(gone["ticker"], "T")

    def test_previous_snapshot_is_the_last_resort(self):
        alert = detect_swing(obs(0.30, ts=900.0), obs(0.42, ts=1000.0))
        self.assertEqual(alert["basis"], "previous_snapshot_mid")
        self.assertEqual(alert["previous"], 0.30)

    def test_reference_needs_its_own_spread(self):
        prev, cur = obs(0.40, ts=1010.0, ref_ts=None), obs(0.44, ts=1020.0, ref_ts=None)
        self.assertIsNone(detect_swing(prev, cur))
        # No spread -> refused, and the refusal is explained.
        self.assertIsNone(detect_swing(prev, cur, reference=0.30, reference_ts=900.0))
        rej = swing_rejection(prev, cur, reference=0.30, reference_ts=900.0)
        self.assertIn("reference quote is missing", rej["reason"])
        # Tight reference spread -> the 14c move alerts.
        alert = detect_swing(prev, cur, reference=0.30, reference_ts=900.0,
                             reference_spread=0.02)
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert["abs_delta"], 0.14)

    def test_no_price_at_all_never_fires(self):
        self.assertIsNone(detect_swing(None, obs(None, bid=None, ask=None,
                                                 ref_bid=0.30, ref_ask=0.32)))


class TestExecutability(unittest.TestCase):
    def test_one_sided_book_is_refused_with_a_reason(self):
        cur = obs(0.44, bid=None, ask=0.44, ref_bid=0.30, ref_ask=0.32)
        self.assertIsNone(detect_swing(None, cur))
        rej = swing_rejection(None, cur)
        self.assertIn("one-sided book", rej["reason"])

    def test_wide_spread_is_refused_with_a_reason(self):
        cur = obs(0.46, bid=0.40, ask=0.52, ref_bid=0.30, ref_ask=0.34)
        self.assertIsNone(detect_swing(None, cur))
        rej = swing_rejection(None, cur)
        self.assertAlmostEqual(rej["abs_delta"], 0.14)
        self.assertIn("not tighter than", rej["reason"])

    def test_no_size_at_the_top_is_indicative(self):
        cur = obs(0.44, bid=0.42, ask=0.44, no_size=0.0, ref_bid=0.30, ref_ask=0.32)
        alert = detect_swing(None, cur)
        self.assertEqual(alert["quality"], "indicative")
        self.assertIn("no size", alert["quality_reason"])
        self.assertEqual(alert["size_name"],
                         "contracts offered at the implied YES ask")

    def test_tight_two_sided_book_is_executable(self):
        cur = obs(0.43, bid=0.42, ask=0.44, ref_bid=0.30, ref_ask=0.32)
        alert = detect_swing(None, cur)
        self.assertEqual(alert["quality"], "executable")
        self.assertEqual(alert["executable"]["side"], "buy YES at the ask")
        self.assertAlmostEqual(alert["executable"]["delta"], 0.12)

    def test_midpoint_only_move_flagged_as_not_executable(self):
        # Mid moves 11c but the ask only moves 8c: the "swing" is bid-side drift.
        cur = obs(0.45, bid=0.44, ask=0.46, ref_bid=0.30, ref_ask=0.38)
        alert = detect_swing(None, cur)
        self.assertAlmostEqual(alert["abs_delta"], 0.11)
        self.assertFalse(alert["executable"]["clears_threshold"])
        self.assertEqual(alert["quality"], "indicative")
        self.assertIn("the executable side moved only", alert["quality_reason"])


class TestFoldAlerts(unittest.TestCase):
    """One row per market + direction + reference bar, with honest repeats."""

    BASE = dict(ts=1_795_200_068.0, iso="2026-11-20T18:41:08Z", ticker="X",
                topic="elections", title="X", quality="executable")

    def row(self, direction, delta, bar, ts=None):
        return {**self.BASE, "direction": direction, "abs_delta": delta,
                "delta": delta if direction == "up" else -delta,
                "bar_start": bar, "key": f"X:{direction}:{bar}",
                "first_seen_ts": ts or (1_795_200_000.0 + bar % 1000),
                "last_seen_ts": ts or (1_795_200_000.0 + bar % 1000),
                "repeat_count": 0}

    def test_same_bar_repeats_fold_into_one_row(self):
        existing = []
        first = fold_alerts([self.row("down", 0.4045, 1_795_200_000)], existing)
        again = fold_alerts([self.row("down", 0.4045, 1_795_200_000,
                                     ts=1_795_200_300.0)], first["alerts"])
        self.assertEqual(len(again["alerts"]), 1)
        self.assertEqual(again["folded"], 1)
        self.assertEqual(again["alerts"][0]["repeat_count"], 1)

    def test_bigger_move_in_same_bar_replaces_and_keeps_history(self):
        first = fold_alerts([self.row("down", 0.4045, 1_795_200_000)], [])
        second = fold_alerts([self.row("down", 0.55, 1_795_200_000)], first["alerts"])
        self.assertEqual(len(second["alerts"]), 1)
        self.assertAlmostEqual(second["alerts"][0]["abs_delta"], 0.55)
        self.assertEqual(second["alerts"][0]["first_seen_ts"],
                         first["alerts"][0]["first_seen_ts"])

    def test_sustained_move_in_a_later_bar_does_not_spam(self):
        first = fold_alerts([self.row("down", 0.4045, 1_795_200_000)], [])
        later = fold_alerts([self.row("down", 0.4045, 1_795_200_300)], first["alerts"])
        self.assertEqual(len(later["alerts"]), 1)
        self.assertEqual(later["folded"], 1)

    def test_escalation_by_a_further_threshold_opens_a_new_row(self):
        first = fold_alerts([self.row("down", 0.4045, 1_795_200_000)], [])
        grown = fold_alerts([self.row("down", 0.4045 + ESCALATION_STEP,
                                     1_795_200_300)], first["alerts"])
        self.assertEqual(len(grown["alerts"]), 2)
        self.assertEqual(grown["escalated"], 1)
        self.assertTrue(grown["alerts"][0]["key"].endswith("1795200300"))

    def test_reversal_is_its_own_row(self):
        first = fold_alerts([self.row("down", 0.40, 1_795_200_000)], [])
        both = fold_alerts([self.row("up", 0.30, 1_795_200_000)], first["alerts"])
        self.assertEqual(len(both["alerts"]), 2)
        self.assertEqual(both["added"], 1)

    def test_buffer_stays_bounded_and_sorted(self):
        rows = [self.row("down", 0.10 + i / 100, 1_795_200_000 + i * 300)
                for i in range(30)]
        out = fold_alerts(rows[:1], [], max_alerts=10)
        for row in rows[1:]:
            out = fold_alerts([row], out["alerts"], max_alerts=10)
        self.assertLessEqual(len(out["alerts"]), 10)
        stamps = [a["ts"] for a in out["alerts"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_legacy_rows_without_keys_are_preserved(self):
        legacy = [{"ticker": "OLD", "direction": "up", "abs_delta": 0.2,
                   "ts": 1.0, "iso": "x"}]
        out = fold_alerts([self.row("down", 0.30, 1_795_200_000)], legacy)
        self.assertEqual(len(out["alerts"]), 2)


class TestModelFeed(unittest.TestCase):
    """The shortlist chat and the generator must agree on one gate."""

    def test_gate_boundary_is_inclusive(self):
        self.assertTrue(clears_model_gate({"net_roi": MODEL_MIN_NET_ROI}))
        self.assertFalse(clears_model_gate({"net_roi": MODEL_MIN_NET_ROI - 0.0001}))
        self.assertFalse(clears_model_gate(None))
        self.assertFalse(clears_model_gate({"net_roi": None}))

    def test_only_liked_and_executable_alerts_pass(self):
        signal = {"ticker": "A", "net_roi": 0.20, "side": "yes",
                  "executable_price": 0.40}
        alerts = [{"ticker": "A", "quality": "executable"},
                  {"ticker": "A", "quality": "indicative"},
                  {"ticker": "B", "quality": "executable"}]
        out = high_roi_alerts(alerts, [signal])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["model_net_roi"], 0.20)
        self.assertEqual(out[0]["model_side"], "yes")

    def test_weak_signal_empties_the_feed_rather_than_padding_it(self):
        out = high_roi_alerts([{"ticker": "A", "quality": "executable"}],
                             [{"ticker": "A", "net_roi": 0.01}])
        self.assertEqual(out, [])


class TestNewsLookup(unittest.TestCase):
    """Headlines are candidates, and an unavailable lookup stays blank."""

    RSS = (b"<?xml version='1.0'?><rss><channel>"
           b"<item><title>Gas prices jump as refiners cut output</title>"
           b"<link>https://example.com/gas-jump</link>"
           b"<pubDate>Mon, 20 Nov 2026 15:00:00 GMT</pubDate>"
           b"<source url='https://example.org'>Example Times</source></item>"
           b"<item><title>Old story from last month</title>"
           b"<link>https://example.com/old</link>"
           b"<pubDate>Tue, 10 Nov 2026 09:00:00 GMT</pubDate></item>"
           b"</channel></rss>")

    class Resp:
        def __init__(self, payload): self.payload = payload
        def read(self): return self.payload
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def test_window_filters_out_far_off_headlines(self):
        import urllib.request
        when = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
        original = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: self.Resp(self.RSS)
        try:
            found = news_mod.headlines_near("gas prices", when, window_hours=6,
                                            max_items=5)
        finally:
            urllib.request.urlopen = original
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source"], "Example Times")
        self.assertEqual(found[0]["status"], "verified-fetch")

    def test_network_failure_returns_empty_not_an_exception(self):
        import urllib.request
        original = urllib.request.urlopen

        def boom(*a, **k):
            raise urllib.error.URLError("egress blocked")
        urllib.request.urlopen = boom
        try:
            found = news_mod.headlines_near("gas prices",
                                           datetime(2026, 11, 20, tzinfo=timezone.utc))
        finally:
            urllib.request.urlopen = original
        self.assertEqual(found, [])


class TestBarReference(unittest.TestCase):
    """bar_reference must read the documented candle fields."""

    class Client:
        def __init__(self, payload): self.payload = payload
        def candlesticks(self, series, ticker, start_ts, end_ts,
                         period_interval=1):
            return self.payload

    def test_prefers_two_sided_quote_over_trade_close(self):
        now = 1_795_200_068
        payload = {"candlesticks": [{
            "end_period_ts": now - 60,
            "yes_bid": {"close_dollars": "0.3000"},
            "yes_ask": {"close_dollars": "0.3200"},
            "price": {"close_dollars": "0.2500"},
        }]}
        import time as _t
        real = _t.time
        _t.time = lambda: float(now)
        try:
            ref = bar_reference(self.Client(payload),
                                {"series_ticker": "S", "ticker": "T"},
                                deadline=real() + 60)
        finally:
            _t.time = real
        self.assertEqual(ref["yes_bid"], 0.30)
        self.assertEqual(ref["yes_ask"], 0.32)
        self.assertEqual(ref["trade_close"], 0.25)
        self.assertEqual(ref["mid"], 0.31)      # quote mid, never 0.25
        self.assertEqual(ref["spread"], 0.02)
        self.assertEqual(ref["period_interval_minutes"], 1)

    def test_missing_history_returns_none(self):
        real = __import__("time").time
        import time as _t
        _t.time = lambda: 1_795_200_068.0
        try:
            ref = bar_reference(self.Client({"candlesticks": []}),
                                {"series_ticker": "S", "ticker": "T"},
                                deadline=float("inf"))
        finally:
            _t.time = real
        self.assertIsNone(ref)


class TestPayloadContract(unittest.TestCase):
    """Keys the site renders, asserted at the source so the UI cannot break."""

    def test_alert_carries_every_field_the_pages_read(self):
        cur = obs(0.43, bid=0.42, ask=0.44, ref_bid=0.30, ref_ask=0.32)
        alert = detect_swing(None, cur)
        for key in ("id", "key", "bar_start", "ts", "iso", "ticker", "title",
                    "previous", "current", "delta", "abs_delta", "direction",
                    "basis", "quality", "quality_reason", "executable",
                    "size_at_top", "market_url", "threshold", "first_seen_ts",
                    "last_seen_ts", "repeat_count"):
            self.assertIn(key, alert, f"alert is missing {key!r}")
        self.assertEqual(alert["threshold"], SWING_THRESHOLD)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestBookAgainstRecord(unittest.TestCase):
    """Two Kalshi endpoints, one market, different prices. Verified live.

    Fixture values were read from the demo API on 2026-11-20T19:16Z:
      https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID
      https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID/orderbook
    """

    MARKET = {"ticker": "KXPRESNOMD-28-HBID", "event_ticker": "KXPRESNOMD-28",
              "yes_sub_title": "Hunter Biden",
              "yes_bid_dollars": "0.0020", "yes_ask_dollars": "0.0030"}
    BOOK = {"orderbook_fp": {
        "yes_dollars": [["0.0010", "166666.66"], ["0.0020", "83333.33"]],
        "no_dollars": [["0.1880", "1567.00"], ["0.1890", "215.44"]],
    }}

    def test_gap_is_measured_and_sourced(self):
        gap = book_record_divergence(self.MARKET, self.BOOK)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["book_mid"], 0.4065)      # (0.0020 + 1-0.1890)/2
        self.assertEqual(gap["record_mid"], 0.0025)    # (0.0020 + 0.0030)/2
        self.assertAlmostEqual(gap["gap"], 0.404)
        self.assertEqual(gap["abs_gap"], 0.404)
        self.assertEqual(gap["source_book"],
                         "https://external-api.demo.kalshi.co/trade-api/v2/markets/"
                         "KXPRESNOMD-28-HBID/orderbook")
        self.assertEqual(gap["source_record"],
                         "https://external-api.demo.kalshi.co/trade-api/v2/markets/"
                         "KXPRESNOMD-28-HBID")

    def test_agreement_is_silent(self):
        book = {"orderbook_fp": {"yes_dollars": [["0.0020", "10.00"]],
                                 "no_dollars": [["0.9970", "10.00"]]}}
        self.assertIsNone(book_record_divergence(self.MARKET, book))

    def test_missing_side_is_not_invented(self):
        self.assertIsNone(book_record_divergence(self.MARKET, None))
        self.assertIsNone(book_record_divergence(
            {"ticker": "T", "yes_bid_dollars": "", "yes_ask_dollars": ""}, self.BOOK))

    def test_threshold_is_the_alert_threshold(self):
        book = {"orderbook_fp": {"yes_dollars": [["0.0600", "10.00"]],
                                 "no_dollars": []}}
        market = {"ticker": "T", "yes_bid_dollars": "0.0000",
                  "yes_ask_dollars": "0.0300"}
        self.assertIsNone(book_record_divergence(market, book, threshold=0.10))
        self.assertIsNotNone(book_record_divergence(market, book, threshold=0.02))

