"""Regression tests: swing alerts must compare like with like, and must not fire
on quote-width artifacts.

Fixture values are copied from the official demo API responses fetched on
2026-11-20 (sources in VERIFICATION_856e184e.md):

  GET /markets/KXPRESNOMD-28-HBID            last_price 0.8110, yes_bid 0.0020, yes_ask 0.8110
  GET /markets/KXPRESNOMD-28-HBID/orderbook  best YES bid 0.0020, best NO bid 0.1890 -> YES ask 0.8110
  GET /series/KXPRESNOMD/markets/KXPRESNOMD-28-HBID/candlesticks (period 60)
      candle.price.close_dollars 0.8110 (LAST TRADE), candle.yes_bid.close 0.0020, candle.yes_ask.close 0.8110

Run: python3 -m unittest tests.test_alerts_basis -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import alerts
from collector.alerts import (ALERT_MAX_SPREAD, Observation, alert_record_valid,
                              detect_swing, quoted_spread, swing_quotes_ok)
from collector.collector import bar_reference

TS_NOW = 1795200068.0
TS_PREV = 1795200000.0


def obs(ts, bid, ask, last=None, ticker="KXPRESNOMD-28-HBID"):
    mid = None if bid is None or ask is None else round((bid + ask) / 2, 4)
    return Observation(ts=ts, ticker=ticker, event_ticker="KXPRESNOMD-28",
                       topic="elections", title="Hunter Biden",
                       yes_bid=bid, yes_ask=ask, mid=mid, last_price=last,
                       volume=None, open_interest=None,
                       series_ticker="KXPRESNOMD")


class FakeClient:
    def __init__(self, candles):
        self._candles = candles

    def candlesticks(self, series, ticker, start, end, period_interval=1):
        return {"ticker": ticker, "candlesticks": self._candles}


def candle(end_ts, last_close, bid_close, ask_close):
    return {
        "end_period_ts": end_ts,
        "price": {"close_dollars": last_close},
        "yes_bid": {"open_dollars": bid_close, "low_dollars": bid_close,
                    "high_dollars": bid_close, "close_dollars": bid_close},
        "yes_ask": {"open_dollars": ask_close, "low_dollars": ask_close,
                    "high_dollars": ask_close, "close_dollars": ask_close},
        "volume_fp": "1.00",
        "open_interest_fp": "1.00",
    }


class PhantomAlertRegression(unittest.TestCase):
    """The observed bug: a 0.811 'previous' vs a 0.4065 'current' mid."""

    def test_wide_book_midpoint_is_not_a_swing(self):
        # Current book: bid 0.002, ask 0.811 -> mid 0.4065 (the value the old code alerted on).
        current = obs(TS_NOW, 0.002, 0.811)
        previous = obs(TS_PREV, 0.002, 0.811)
        # Old reference was the last-trade close 0.811; new reference is a quote mid
        # with the same wide spread, so the alert must be suppressed.
        self.assertIsNone(detect_swing(previous, current, reference=0.4065,
                                       reference_ts=TS_PREV, reference_spread=0.809))

    def test_wide_current_spread_suppresses_alert_even_with_previous_snapshot(self):
        previous = obs(TS_PREV, 0.40, 0.42)   # tight, mid 0.41
        current = obs(TS_NOW, 0.002, 0.811)   # wide, mid 0.4065 -> |delta| < 0.10 anyway
        self.assertIsNone(detect_swing(previous, current))
        previous_far = obs(TS_PREV, 0.90, 0.92)   # tight, mid 0.91
        self.assertIsNone(detect_swing(previous_far, current),
                          "a wide current quote must never produce an alert")

    def test_one_sided_quote_never_alerts(self):
        previous = obs(TS_PREV, 0.50, 0.52)
        current = obs(TS_NOW, None, 0.90)
        self.assertIsNone(detect_swing(previous, current))


class TrueSwingStillDetected(unittest.TestCase):
    def test_tight_quote_move_of_ten_cents_alerts_from_candle_mid(self):
        # Candle quote mid 0.41 (bid .40 / ask .42); current tight quote mid 0.52 (bid .51 / ask .53).
        current = obs(TS_NOW, 0.51, 0.53)
        alert = detect_swing(None, current, reference=0.41, reference_ts=TS_PREV,
                             reference_spread=0.02)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["reference_basis"], "candle_quote_mid")
        self.assertAlmostEqual(alert["delta"], 0.11, places=4)
        self.assertEqual(alert["direction"], "up")
        self.assertAlmostEqual(alert["spread"], 0.02, places=4)

    def test_previous_snapshot_fallback_uses_quote_mids_on_both_sides(self):
        previous = obs(TS_PREV, 0.40, 0.42)   # mid 0.41
        current = obs(TS_NOW, 0.49, 0.51)     # mid 0.50 -> +0.09, below threshold
        self.assertIsNone(detect_swing(previous, current))
        current2 = obs(TS_NOW, 0.50, 0.52)    # mid 0.51 -> +0.10
        alert = detect_swing(previous, current2)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["reference_basis"], "previous_snapshot_mid")

    def test_reference_with_wide_spread_is_rejected(self):
        current = obs(TS_NOW, 0.51, 0.53)
        self.assertIsNone(detect_swing(None, current, reference=0.41,
                                       reference_ts=TS_PREV, reference_spread=0.50))
        self.assertIsNone(detect_swing(None, current, reference=0.41,
                                       reference_ts=TS_PREV, reference_spread=None))


class QuoteRule(unittest.TestCase):
    def test_spread_boundary_is_strict(self):
        self.assertTrue(swing_quotes_ok(0.40, 0.40 + ALERT_MAX_SPREAD - 0.0001))
        self.assertFalse(swing_quotes_ok(0.40, 0.40 + ALERT_MAX_SPREAD))
        self.assertFalse(swing_quotes_ok(None, 0.50))
        self.assertFalse(swing_quotes_ok(0.50, None))
        self.assertEqual(quoted_spread(0.002, 0.811), 0.809)

    def test_stored_phantom_record_is_purged(self):
        phantom = {"id": "KXPRESNOMD-28-HBID:1795200068", "previous": 0.811,
                   "current": 0.4065, "delta": -0.4045,
                   "yes_bid": 0.002, "yes_ask": 0.811}
        self.assertFalse(alert_record_valid(phantom))

    def test_stored_tight_record_is_kept(self):
        good = {"yes_bid": 0.51, "yes_ask": 0.53}
        self.assertTrue(alert_record_valid(good))


class CandleReferenceBasis(unittest.TestCase):
    """bar_reference must return a quote mid, never the last-trade close."""

    MARKET = {"ticker": "KXPRESNOMD-28-HBID", "series_ticker": "KXPRESNOMD"}

    def test_reference_uses_quote_closes_not_last_trade(self):
        # Official values: last trade 0.8110, quotes 0.0020 / 0.8110.
        c = candle(TS_PREV, last_close="0.8110", bid_close="0.0020", ask_close="0.8110")
        ref = bar_reference(FakeClient([c]), self.MARKET, deadline=float("inf"))
        self.assertIsNotNone(ref)
        self.assertEqual(ref["mid"], 0.4065)
        self.assertEqual(ref["spread"], 0.809)
        self.assertEqual(ref["ts"], TS_PREV)

    def test_no_quotes_in_candle_gives_no_reference(self):
        c = {"end_period_ts": TS_PREV, "price": {"close_dollars": "0.5000"},
             "yes_bid": {}, "yes_ask": {}}
        self.assertIsNone(bar_reference(FakeClient([c]), self.MARKET,
                                        deadline=float("inf")))

    def test_end_to_end_hbid_observed_case_produces_no_alert(self):
        # Reproduce the published alert: reference from the candle, current from the book.
        c = candle(TS_PREV, last_close="0.8110", bid_close="0.0020", ask_close="0.8110")
        ref = bar_reference(FakeClient([c]), self.MARKET, deadline=float("inf"))
        current = obs(TS_NOW, 0.0020, 0.8110)
        self.assertIsNone(detect_swing(None, current, reference=ref["mid"],
                                       reference_ts=ref["ts"],
                                       reference_spread=ref["spread"]))


if __name__ == "__main__":
    unittest.main()
