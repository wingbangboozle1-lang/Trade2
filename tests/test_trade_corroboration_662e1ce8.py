"""Regression tests: R-F3-1 trade-price corroboration of the swing reference.

The swing rule compares two *quote* mids. A quote mid can move on a single
stray, un-arbitraged level with no trade behind it, which is the artefact class
seen on KXPRESNOMD-28-BOBA (a 0.8820 ask close against a 0.0050 trade price).
The candlestick schema also publishes the bar's trade price, so ``_swing()``
cross-checks the reference quote mid against it and refuses a candidate swing
that the trade price does not corroborate.

Official schema fields used here (all from the candlestick endpoint,
https://docs.kalshi.com/api-reference/market/get-market-candlesticks):

    yes_bid.close_dollars / yes_ask.close_dollars  -> the reference quote mid
    price.close_dollars                             -> price.close_dollars
    price.previous_dollars                          -> price.previous_dollars

The guard only runs on the candle basis (it needs a trade price to compare
against); the previous-snapshot fallback carries no candle trade price and is
left untouched.

Run: python3 -m unittest tests.test_trade_corroboration_662e1ce8 -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.alerts import (REFERENCE_TRADE_TOLERANCE, SWING_THRESHOLD,
                              Observation, detect_swing, swing_rejection)

TS_NOW = 1795300068.0
TS_PREV = 1795300000.0


def obs(bid, ask, last=None, ticker="KXTEST-1", **ref) -> Observation:
    mid = None if bid is None or ask is None else round((bid + ask) / 2, 4)
    return Observation(
        ts=TS_NOW, ticker=ticker, event_ticker="KXTEST", topic="culture",
        title="Test market", yes_bid=bid, yes_ask=ask, mid=mid, last_price=last,
        volume=None, open_interest=None, series_ticker="KXTEST", **ref)


class TradeCorroborationGuard(unittest.TestCase):
    def test_stray_tight_reference_is_refused_at_the_source(self):
        # Reference candle: tight quote mid 0.51 (bid .50 / ask .52) but a trade
        # price of 0.30 - the quote is not corroborated by trades.
        current = obs(0.61, 0.63, ref_trade_close=0.30,
                      ref_previous_dollars=0.30)
        self.assertIsNone(detect_swing(
            None, current, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02))
        rej = swing_rejection(
            None, current, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02)
        self.assertIsNotNone(rej)
        self.assertEqual(rej["corroboration"], "uncorroborated")
        self.assertEqual(rej["trade_price"], 0.30)
        self.assertEqual(rej["trade_price_basis"], "price.previous_dollars")
        self.assertAlmostEqual(rej["trade_price_gap"], 0.21, places=4)
        self.assertIn("not corroborated", rej["reason"])

    def test_previous_dollars_is_preferred_over_close(self):
        current = obs(0.61, 0.63, ref_trade_close=0.50,
                      ref_previous_dollars=0.29)
        rej = swing_rejection(
            None, current, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02)
        self.assertIsNotNone(rej)
        self.assertEqual(rej["trade_price"], 0.29)
        self.assertEqual(rej["trade_price_basis"], "price.previous_dollars")

    def test_close_dollars_is_the_fallback_basis(self):
        current = obs(0.61, 0.63, ref_trade_close=0.29)
        rej = swing_rejection(
            None, current, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02)
        self.assertIsNotNone(rej)
        self.assertEqual(rej["trade_price_basis"], "price.close_dollars")

    def test_corroborated_swing_still_alerts(self):
        # Reference trade price agrees with the reference quote mid.
        current = obs(0.51, 0.53, ref_trade_close=0.41,
                      ref_previous_dollars=0.41)
        alert = detect_swing(
            None, current, reference=0.41, reference_ts=TS_PREV,
            reference_spread=0.02)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["direction"], "up")
        self.assertAlmostEqual(alert["delta"], 0.11, places=4)
        self.assertEqual(alert["corroboration"], "corroborated")
        self.assertAlmostEqual(alert["trade_price_gap"], 0.00, places=4)

    def test_previous_snapshot_fallback_is_untouched(self):
        # No candle -> no trade price -> the guard must not fire at all.
        prev = obs(0.40, 0.42, ticker="KXTEST-1")
        prev.ts = TS_PREV
        current = obs(0.50, 0.52)
        alert = detect_swing(prev, current)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["reference_basis"], "previous_snapshot_mid")
        self.assertIsNone(alert["corroboration"])
        self.assertIsNone(alert["trade_price"])

    def test_below_threshold_move_is_not_refused(self):
        # A small move is not a candidate swing, so no refusal is published.
        current = obs(0.52, 0.54, ref_trade_close=0.29,
                      ref_previous_dollars=0.29)
        self.assertIsNone(detect_swing(
            None, current, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02))
        self.assertIsNone(swing_rejection(
            None, current, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02))

    def test_tolerance_boundary(self):
        # A gap of exactly the threshold is refused; just below it is not.
        at = obs(0.61, 0.63, ref_previous_dollars=0.410)
        self.assertIsNotNone(swing_rejection(
            None, at, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02))
        below = obs(0.61, 0.63, ref_previous_dollars=0.411)
        self.assertIsNone(swing_rejection(
            None, below, reference=0.51, reference_ts=TS_PREV,
            reference_spread=0.02))
        self.assertEqual(REFERENCE_TRADE_TOLERANCE, SWING_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
