"""Unit tests for the order-book model shortlist.

Run: python3 -m unittest discover -s tests -v

The fixtures below are synthetic books shaped like real Kalshi demo books:
a quoted side with resting size, and the degenerate 0.00/1.00 book that the
demo feed produces for markets with no real liquidity. The properties under
test are the ones the site publishes:

  * a price move that the book did not confirm is rejected (the demo feed
    prints alternating trades on a market whose book never moves);
  * a book move of at least $0.10 is priced from the book only;
  * every gate is applied before a row is published;
  * the taker fee is subtracted exactly, using Kalshi's published formula.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.kalshi_api import kalshi_fee
from collector.shortlist import (MAX_SPREAD, MIN_EDGE, SWING_THRESHOLD,
                                  book_of, build, evaluate)


def event(ticker="TEST-1", topic="crypto", bid=0.40, ask=0.42,
          yes_depth=5000.0, no_depth=4000.0, title="Test contract"):
    """One snapshot row shaped like the collector's output."""
    return {
        "ticker": ticker,
        "event_ticker": "TEST",
        "series_ticker": "TEST",
        "topic": topic,
        "title": title,
        "mid": round((bid + ask) / 2, 4),
        "yes_bid": bid,
        "yes_ask": ask,
        "market_url": f"https://kalshi.com/markets/TEST/{ticker}",
        "observation": {"last_price": ask},
        "liquidity": {
            "yes_bids": [{"price": bid, "contracts": yes_depth}],
            "no_bids": [{"price": round(1 - ask, 4), "contracts": no_depth}],
            "best_yes_bid": bid,
            "best_yes_ask": ask,
            "best_no_bid": round(1 - ask, 4),
            "spread": round(ask - bid, 4),
            "yes_bid_contracts": yes_depth,
            "no_bid_contracts": no_depth,
        },
    }


def history_for(points):
    """Build the history file the module expects."""
    trail = {t: [p["mid"] for p in seq] for t, seq in points.items()}
    return {"points": {t: seq[-1] for t, seq in points.items()}, "trail": trail}


class TestBookParsing(unittest.TestCase):
    def test_book_of_uses_the_liquidity_block(self):
        bid, ask, mid = book_of(event(bid=0.40, ask=0.42))
        self.assertAlmostEqual(bid, 0.40)
        self.assertAlmostEqual(ask, 0.42)
        self.assertAlmostEqual(mid, 0.41)

    def test_book_of_falls_back_to_the_market_quotes(self):
        row = event()
        row["liquidity"] = {}
        bid, ask, mid = book_of(row)
        self.assertAlmostEqual(bid, 0.40)
        self.assertAlmostEqual(ask, 0.42)
        self.assertAlmostEqual(mid, 0.41)

    def test_book_of_returns_no_mid_for_a_one_sided_book(self):
        row = event()
        row["liquidity"] = {"best_yes_bid": 0.40, "best_yes_ask": None}
        row["yes_bid"] = 0.40
        row["yes_ask"] = None
        bid, ask, mid = book_of(row)
        self.assertIsNone(mid)


class TestGates(unittest.TestCase):
    def test_a_book_that_did_not_move_produces_no_pick(self):
        """The demo feed prints alternating trades on a static book."""
        result = evaluate(event(bid=0.002, ask=0.003), 0.0025, 0.0025, "swing")
        self.assertFalse(result["accepted"])

    def test_a_wide_book_is_rejected(self):
        result = evaluate(event(bid=0.01, ask=1.00), 0.50, 0.50, "swing")
        self.assertFalse(result["accepted"])
        self.assertIn("wider than", result["reason"])

    def test_a_book_without_resting_size_is_rejected(self):
        result = evaluate(event(bid=0.40, ask=0.42, yes_depth=0.0), 0.60, 0.40, "swing")
        self.assertFalse(result["accepted"])
        self.assertIn("contracts resting", result["reason"])

    def test_a_move_smaller_than_the_edge_is_rejected(self):
        # fair = (0.50 + 0.47) / 2 = 0.485, ask 0.46 -> edge 0.025 but the
        # fee eats most of it.
        result = evaluate(event(bid=0.45, ask=0.46), 0.50, 0.47, "swing")
        self.assertFalse(result["accepted"])

    def test_a_real_book_move_is_priced_from_the_book(self):
        # book mid 0.50 -> 0.30, fair 0.40, YES ask 0.31 -> edge 0.09.
        result = evaluate(event(bid=0.29, ask=0.31), 0.50, 0.30, "swing")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["side"], "yes")
        self.assertAlmostEqual(result["model_fair"], 0.40, places=4)
        self.assertAlmostEqual(result["executable_price"], 0.31, places=4)
        self.assertAlmostEqual(result["edge"], 0.09, places=4)
        self.assertAlmostEqual(result["fee"], kalshi_fee(0.31, 1.0), places=6)
        self.assertAlmostEqual(result["net_edge"],
                               round(result["edge"] - result["fee"], 4), places=4)
        self.assertGreater(result["net_roi"], 0)

    def test_the_no_side_is_picked_when_yes_is_expensive(self):
        # book mid 0.30 -> 0.50, fair 0.40. Buying NO at 1 - 0.49 = 0.51
        # leaves 0.49 - 0.40 = 0.09 of edge on the YES axis.
        result = evaluate(event(bid=0.49, ask=0.51), 0.30, 0.50, "swing")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["side"], "no")
        self.assertAlmostEqual(result["edge"], 0.09, places=4)

    def test_the_edge_gate_is_at_least_two_cents(self):
        self.assertEqual(MIN_EDGE, 0.02)
        self.assertEqual(SWING_THRESHOLD, 0.10)
        self.assertEqual(MAX_SPREAD, 0.20)


class TestBuild(unittest.TestCase):
    def test_build_prices_a_book_move_and_rejects_a_print_only_move(self):
        moved = event(ticker="MOVED", bid=0.29, ask=0.31)
        still = event(ticker="STILL", bid=0.002, ask=0.003)
        live = {
            "generated_at": "2026-11-20T19:00:00Z",
            "generated_at_ts": 1_795_200_000.0,
            "events": [moved, still],
            "alerts": [
                {"ticker": "MOVED", "ts": 1_795_200_000.0, "iso": "2026-11-20T19:00:00Z",
                 "topic": "crypto", "title": "Test contract", "delta": -0.20,
                 "direction": "down"},
                {"ticker": "STILL", "ts": 1_795_200_000.0, "iso": "2026-11-20T19:00:00Z",
                 "topic": "elections", "title": "Print only", "delta": -0.80,
                 "direction": "down"},
            ],
        }
        hist = history_for({
            "MOVED": [{"mid": 0.50}, {"mid": 0.50}],
            "STILL": [{"mid": 0.0025}, {"mid": 0.0025}],
        })
        result = build(live, hist)
        picks = result["shortlist"]["picks"]
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["ticker"], "MOVED")
        self.assertEqual(picks[0]["kind"], "swing")

        verdicts = {v["ticker"]: v for v in result["shortlist"]["verdicts"]}
        self.assertEqual(set(verdicts), {"MOVED", "STILL"})
        self.assertEqual(verdicts["MOVED"]["verdict"], "picked")
        self.assertEqual(verdicts["STILL"]["verdict"], "rejected")
        self.assertIn("book has not moved", verdicts["STILL"]["reason"])

    def test_the_history_trail_advances(self):
        live = {"generated_at": "2026-11-20T19:00:00Z", "events": [event()],
                "alerts": []}
        hist = history_for({"TEST-1": [{"mid": 0.41}]})
        result = build(live, hist)
        trail = result["history"]["trail"]["TEST-1"]
        self.assertEqual(trail[-1], 0.41)
        self.assertGreaterEqual(len(trail), 2)

    def test_a_snapshot_without_history_prices_nothing(self):
        live = {"generated_at": "2026-11-20T19:00:00Z", "events": [event()],
                "alerts": []}
        result = build(live, {})
        self.assertEqual(result["shortlist"]["picks_count"], 0)


if __name__ == "__main__":
    unittest.main()
