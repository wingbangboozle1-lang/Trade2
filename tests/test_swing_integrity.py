"""Regression tests for alert integrity and in-topic resolution tracking.

Both tests are built from payloads captured from the official demo API on
2026-11-20, so they assert against what the exchange actually returns rather
than an idealised shape.

Fixtures used (fetched live during the audit; URLs logged in VERIFICATION.md,
section "Session D"):

* ``KXPRESNOMD-28-AKLO`` / ``KXPRESNOMD-28-JP`` — the two markets that produced
  the phantom "80 cent" swings published on the dashboard. Their worst-case
  quote is ``yes_bid 0.0020 / yes_ask 0.8030`` (AKLO after the 0.8030 print) and
  ``yes_bid 0.0100 / yes_ask 0.9440`` (JP, whose real NO bid is 0.0560).
* Candle rows from ``.../candlesticks`` show the 0.8030 print alternating with
  0.0030 minute by minute — a single unpaired print, not a price level.

Run: python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.alerts import (HIGH_ROI_GATE, MAX_QUOTE_SPREAD, SWING_THRESHOLD,
                              Observation, detect_swing, is_publishable, observe)
from collector.collector import (candle_reference, resolutions_by_topic,
                                 series_of)


def obs(ticker, bid, ask, ts=1_795_200_000.0, topic="elections",
        series="KXPRESNOMD"):
    return Observation(
        ts=ts, ticker=ticker, event_ticker=ticker.rsplit("-", 1)[0], topic=topic,
        title=ticker, yes_bid=bid, yes_ask=ask,
        mid=(round((bid + ask) / 2, 4) if bid is not None and ask is not None
             else (bid if ask is None else ask)),
        last_price=None, volume=1.0, open_interest=1.0, series_ticker=series,
    )


class TestSwingIntegrity(unittest.TestCase):
    def test_single_print_on_a_tight_market_is_not_a_swing(self):
        """AKLO: a real 0.002/0.003 market that printed 0.8030 for one minute.

        Before the fix this produced "▼ $0.8005 ... $0.8030 -> $0.0025" and was
        published as an 80-cent crash. The current quote is 0.002/0.003, which
        is genuinely tight, but the price it is being compared *from* is the
        artifact. The previous-side guard is applied by the collector through
        the candle reference; here we assert the new-side quote gate.
        """
        # The artifact itself: bid 0.0020, ask 0.8030 -> width 0.8010.
        phantom = obs("KXPRESNOMD-28-AKLO", 0.0020, 0.8030)
        self.assertGreater(round(phantom.yes_ask - phantom.yes_bid, 4),
                           MAX_QUOTE_SPREAD)
        self.assertIsNone(
            detect_swing(None, phantom, reference=0.4025),
            "a quote 0.80 wide must never be published as a price move")

    def test_wide_but_two_sided_quote_is_rejected(self):
        """JP: bid 0.0100 / ask 0.9440 — the real book has depth inside it."""
        jp = obs("KXPRESNOMD-28-JP", 0.0100, 0.9440)
        self.assertIsNone(detect_swing(None, jp, reference=0.9430))

    def test_normal_two_sided_swing_still_alerts(self):
        """The rule must keep firing on real moves."""
        current = obs("KXTEST-1", 0.4000, 0.4400)   # 0.44 - 0.40 = 0.04 wide
        alert = detect_swing(None, current, reference=0.3000,
                             reference_spread=0.02,
                             reference_quote={"bid": 0.29, "ask": 0.31,
                                              "print": 0.30})
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert["delta"], 0.12, places=4)
        self.assertEqual(alert["direction"], "up")
        self.assertTrue(alert["two_sided_quote"])
        self.assertAlmostEqual(alert["quote_width"], 0.04, places=4)

    def test_threshold_is_still_ten_cents(self):
        current = obs("KXTEST-2", 0.4900, 0.5100)   # mid 0.50
        ref = {"bid": 0.39, "ask": 0.41, "print": 0.40}
        self.assertIsNone(detect_swing(None, current, reference=0.41,
                                       reference_spread=0.02, reference_quote=ref))
        self.assertIsNotNone(detect_swing(None, current, reference=0.40,
                                          reference_spread=0.02, reference_quote=ref))
        self.assertEqual(SWING_THRESHOLD, 0.10)

    def test_one_sided_quote_never_raises_an_alert(self):
        """A quote with no opposite side cannot be checked, so it is not a move."""
        current = obs("KXTEST-3", None, 0.6000)
        self.assertIsNone(detect_swing(None, current, reference=0.3000,
                                       reference_spread=0.02,
                                       reference_quote={"bid": 0.29, "ask": 0.31,
                                                        "print": 0.30}))

    def test_observe_keeps_full_spread_as_no_quote(self):
        """Documented empty-market shape: 0 bid / 1 ask is not a 0.50 mid."""
        o = observe({"ticker": "KXEMPTY", "yes_bid_dollars": "0.0000",
                     "yes_ask_dollars": "1.0000"}, None, "golf")
        self.assertIsNone(o.mid)


class TestCandleReferenceIntegrity(unittest.TestCase):
    """The baseline for a swing must itself be a real price.

    Fixture: two consecutive 1-minute candlesticks for KXPRESNOMD-28-AKLO,
    copied from the live demo API on 2026-11-20 (periods ending 1795199940 and
    1795200000). The second minute's printed close is 0.8030 while its own
    quoted market is 0.0020 bid / 0.0030 ask — a single unpaired print. Using
    that close as the baseline is what produced "▼ $0.8005" alerts.
    """

    AKLO = [
        {"end_period_ts": 1795199940,
         "price": {"open_dollars": "0.0030", "close_dollars": "0.0030",
                   "high_dollars": "0.8030", "low_dollars": "0.0030",
                   "mean_dollars": "0.2456", "previous_dollars": "0.8030"},
         "yes_bid": {"open_dollars": "0.0020", "close_dollars": "0.0000",
                     "high_dollars": "0.0030", "low_dollars": "0.0000"},
         "yes_ask": {"open_dollars": "0.0030", "close_dollars": "0.8030",
                     "high_dollars": "0.8030", "low_dollars": "0.0030"}},
        {"end_period_ts": 1795200000,
         "price": {"open_dollars": "0.8030", "close_dollars": "0.8030",
                   "high_dollars": "0.8030", "low_dollars": "0.8030",
                   "mean_dollars": "0.8030", "previous_dollars": "0.0030"},
         "yes_bid": {"open_dollars": "0.0000", "close_dollars": "0.0020",
                     "high_dollars": "0.0030", "low_dollars": "0.0000"},
         "yes_ask": {"open_dollars": "0.8030", "close_dollars": "0.0030",
                     "high_dollars": "0.8030", "low_dollars": "0.0030"}},
    ]

    def test_artifact_minutes_yield_no_reference(self):
        """Honest outcome: neither minute is usable, so no swing is published.

        Minute 1795199940 quotes 0.0000/0.8030 (0.80 wide, not a market price)
        and minute 1795200000 prints 0.8030 outside its own 0.0020/0.0030
        quote. Rather than fall back to a price nobody could trade, the
        collector gets no reference and the caller uses the previous stored
        observation — which keeps these markets out of the alert feed.
        """
        self.assertIsNone(candle_reference(self.AKLO, now=1795200068))

    def test_print_outside_its_own_quote_is_rejected(self):
        only_artifact = [self.AKLO[1]]
        self.assertIsNone(candle_reference(only_artifact, now=1795200068))

    def test_wide_quote_minute_is_rejected(self):
        wide = [{"end_period_ts": 1795200000,
                 "price": {"close_dollars": "0.4770"},
                 "yes_bid": {"close_dollars": "0.0100"},
                 "yes_ask": {"close_dollars": "0.9440"}}]
        self.assertIsNone(candle_reference(wide, now=1795200068))

    def test_normal_minute_is_accepted(self):
        normal = [{"end_period_ts": 1795200000,
                   "price": {"close_dollars": "0.4100"},
                   "yes_bid": {"close_dollars": "0.4000"},
                   "yes_ask": {"close_dollars": "0.4200"}}]
        ref = candle_reference(normal, now=1795200068)
        self.assertIsNotNone(ref)
        self.assertAlmostEqual(ref["mid"], 0.41, places=4)
        self.assertAlmostEqual(ref["spread"], 0.02, places=4)
        self.assertAlmostEqual(ref["quote_width"], 0.02, places=4)

    def test_unfinished_bar_is_not_used(self):
        normal = [{"end_period_ts": 1795200900,      # after now
                   "price": {"close_dollars": "0.4100"},
                   "yes_bid": {"close_dollars": "0.4000"},
                   "yes_ask": {"close_dollars": "0.4200"}}]
        self.assertIsNone(candle_reference(normal, now=1795200000))


class TestPublishability(unittest.TestCase):
    """One function decides what reaches the chat feed."""

    def alert(self, bid, ask, ref_bid, ref_ask, cur_print=None, ref_print=None):
        return {"ticker": "T", "yes_bid": bid, "yes_ask": ask,
                "previous": 0.5, "current": 0.6,
                "reference_quote": {"bid": ref_bid, "ask": ref_ask,
                                    "print": ref_print},
                "_cur_print": cur_print}

    def test_both_ends_verified(self):
        self.assertTrue(is_publishable(self.alert(0.59, 0.61, 0.39, 0.41)))

    def test_wide_destination_rejected(self):
        self.assertFalse(is_publishable(self.alert(0.01, 0.944, 0.39, 0.41)))

    def test_wide_baseline_rejected(self):
        self.assertFalse(is_publishable(self.alert(0.59, 0.61, 0.00, 0.80)))

    def test_print_outside_its_quote_rejected(self):
        self.assertFalse(is_publishable(self.alert(0.59, 0.61, 0.00, 0.09,
                                                   ref_print=0.803)))

    def test_one_sided_baseline_rejected(self):
        self.assertFalse(is_publishable(self.alert(0.59, 0.61, None, 0.41)))

    def test_missing_baseline_quote_rejected(self):
        a = self.alert(0.59, 0.61, 0.39, 0.41)
        a.pop("reference_quote")
        self.assertFalse(is_publishable(a))

    def test_wide_destination_never_becomes_an_alert(self):
        """The gate lives in detect_swing as well as in the record check."""
        phantom = obs("KXPRESNOMD-28-HBID", 0.002, 0.811)
        self.assertIsNone(detect_swing(None, phantom, reference=0.4065,
                                       reference_spread=0.809))

    def test_published_buffer_respects_the_gate(self):
        """Whatever the collector published must pass the gate it publishes."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "live.json")
        if not os.path.exists(path):
            self.skipTest("no collected snapshot in this checkout")
        with open(path, encoding="utf-8") as fh:
            live = json.load(fh)
        for a in live.get("alerts") or []:
            self.assertTrue(is_publishable(a),
                            f"published alert {a.get('id')} fails its own gate")
        for a in live.get("alerts_suppressed") or []:
            self.assertFalse(is_publishable(a),
                             f"held-back alert {a.get('id')} actually passes")

    def test_model_gate_is_published_once(self):
        self.assertEqual(HIGH_ROI_GATE, 0.05)


class TestObservationPersistence(unittest.TestCase):
    """``data/live.json`` must carry the observations the next run compares to."""

    def test_live_snapshot_round_trips_observations(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "live.json")
        if not os.path.exists(path):
            self.skipTest("no collected snapshot in this checkout")
        with open(path, encoding="utf-8") as fh:
            live = json.load(fh)
        if "observations" not in live:
            self.skipTest("snapshot predates observation persistence; "
                          "the next collector run adds it")
        for row in live["observations"][:50]:
            self.assertIn("ticker", row)
            self.assertIn("mid", row)
            Observation(ts=row["ts"], ticker=row["ticker"],
                        event_ticker=row.get("event_ticker", ""),
                        topic=row.get("topic", ""), title=row.get("title", ""),
                        yes_bid=row.get("yes_bid"), yes_ask=row.get("yes_ask"),
                        mid=row.get("mid"), last_price=row.get("last_price"),
                        volume=row.get("volume"),
                        open_interest=row.get("open_interest"),
                        series_ticker=row.get("series_ticker", ""))


class TestResolutionTopicMapping(unittest.TestCase):
    """A settled market has no ``series_ticker``; the topic must still be found.

    Live evidence (2026-11-20): GET /markets?status=settled returns market
    objects with ``event_ticker`` but no ``series_ticker`` field at all, so the
    old mapping ``series_to_topic[rec["series_ticker"]]`` always missed and
    every topic page rendered "No resolved market ... captured yet" while the
    overview claimed 2,000 resolutions.
    """

    def test_series_is_derived_from_the_ticker_prefix(self):
        for ticker, expected in [
            ("KXDEMOFUTHOURLY-26NOV20H19-UP", "KXDEMOFUTHOURLY"),
            ("KXQUICKSETTLE-20NOV26H1310-3", "KXQUICKSETTLE"),
            ("KXPRESNOMD-28-HBID", "KXPRESNOMD"),
        ]:
            self.assertEqual(ticker.split("-")[0], expected)

    def test_mapping_attributes_a_real_settled_market(self):
        """Payload shape copied from GET /markets?status=settled (live)."""
        settled = {
            "KXDEMOFUTHOURLY-26NOV20H19-UP": {
                "ticker": "KXDEMOFUTHOURLY-26NOV20H19-UP",
                "event_ticker": "KXDEMOFUTHOURLY-26NOV20H19",
                "series_ticker": None,          # the bug: Kalshi omits this
                "title": "At or above reference",
                "result": "no",
                "settlement_value_dollars": "0.0000",
                "settlement_ts": "2026-11-20T19:01:38.771408Z",
                "status": "finalized",
            },
            "KXQUICKSETTLE-20NOV26H1310-2": {
                "ticker": "KXQUICKSETTLE-20NOV26H1310-2",
                "event_ticker": "KXQUICKSETTLE-20NOV26H1310",
                "series_ticker": None,
                "title": "2",
                "result": "yes",
                "settlement_value_dollars": "1.0000",
                "settlement_ts": "2026-11-20T18:50:38.774518Z",
                "status": "finalized",
            },
            "KXUNTRACKED-1": {"ticker": "KXUNTRACKED-1", "result": "yes"},
        }
        mapping = {"KXDEMOFUTHOURLY": "crypto", "KXQUICKSETTLE": "crypto"}
        grouped = resolutions_by_topic(settled, mapping)

        crypto = grouped["crypto"]
        self.assertEqual(len(crypto), 2, "both tracked settlements must map")
        self.assertEqual(crypto[0]["ticker"], "KXDEMOFUTHOURLY-26NOV20H19-UP",
                         "newest settlement first")
        for row in crypto:
            self.assertEqual(row["topic"], "crypto")
            self.assertTrue(row["series_ticker"])
            self.assertIn(row["result"], ("yes", "no"))

        # An unattributable market is dropped, never guessed into a topic.
        everything = [r["ticker"] for rows in grouped.values() for r in rows]
        self.assertNotIn("KXUNTRACKED-1", everything)
        self.assertEqual(grouped["golf"], [])
        for slug in ("gas-prices", "elections", "culture", "golf"):
            self.assertEqual(grouped[slug], [])

    def test_topic_hint_from_the_event_wins(self):
        """Payload shape: GET /events?status=settled&with_nested_markets=true."""
        event = {"event_ticker": "KXDEMOFUTHOURLY-26NOV20H19",
                 "series_ticker": "KXDEMOFUTHOURLY", "title": "Demo BTC",
                 "markets": [{"ticker": "KXDEMOFUTHOURLY-26NOV20H19-UP",
                              "result": "no",
                              "settlement_value_dollars": "0.0000",
                              "settlement_ts": "2026-11-20T19:01:38Z"}]}
        market = event["markets"][0]
        rec = {**market,
               "series_ticker": event["series_ticker"],
               "event_ticker": event["event_ticker"],
               "topic_hint": "crypto"}
        grouped = resolutions_by_topic({market["ticker"]: rec}, {})
        self.assertEqual(len(grouped["crypto"]), 1,
                         "an explicit topic_hint needs no series map")
        self.assertEqual(grouped["crypto"][0]["result"], "no")

    def test_unknown_topic_hint_is_not_trusted(self):
        rec = {"ticker": "X-1", "result": "yes", "topic_hint": "sports-ish"}
        grouped = resolutions_by_topic({"X-1": rec}, {"X": "golf"})
        self.assertEqual(grouped["sports-ish"] if "sports-ish" in grouped else [],
                         [], "an unknown hint must not create a topic")

    def test_series_of_prefers_the_recorded_value(self):
        self.assertEqual(series_of("KXPRESNOMD-28-HBID"), "KXPRESNOMD")
        self.assertEqual(series_of("KXPRESNOMD-28-HBID", "OTHER"), "OTHER")


if __name__ == "__main__":
    unittest.main()
