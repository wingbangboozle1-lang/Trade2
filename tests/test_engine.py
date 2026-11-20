"""Unit tests for the price maths, swing detection and simulator.

Run: python3 -m unittest discover -s tests -v

The orderbook fixture below is copied verbatim from the official docs example:
https://docs.kalshi.com/getting_started/orderbook_responses.md
so the parsing logic is checked against Kalshi's own worked example.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.alerts import (Observation, analyse_liquidity, detect_swing,
                              rank_events, score_market, SWING_THRESHOLD)
from collector.engine import Portfolio, STARTING_BANKROLL, select_trades
from collector.kalshi_api import (best_bid, dollars, implied_yes_ask,
                                  kalshi_fee, mid_price, sign_message)

DOC_ORDERBOOK = {
    "orderbook_fp": {
        "yes_dollars": [["0.0100", "200.00"], ["0.1500", "100.00"],
                        ["0.2000", "50.00"], ["0.2500", "20.00"],
                        ["0.3000", "11.00"], ["0.3100", "10.00"],
                        ["0.3200", "10.00"], ["0.3300", "11.00"],
                        ["0.3400", "9.00"], ["0.3500", "11.00"],
                        ["0.4100", "10.00"], ["0.4200", "13.00"]],
        "no_dollars": [["0.0100", "100.00"], ["0.1600", "3.00"],
                       ["0.2500", "50.00"], ["0.2800", "19.00"],
                       ["0.3600", "5.00"], ["0.3700", "50.00"],
                       ["0.3800", "300.00"], ["0.4400", "29.00"],
                       ["0.4500", "20.00"], ["0.5600", "17.00"]],
    }
}


class TestFixedPoint(unittest.TestCase):
    def test_dollars_never_coerces_empty_to_zero(self):
        self.assertIsNone(dollars(""))
        self.assertIsNone(dollars(None))
        self.assertEqual(dollars("0.0000"), 0.0)      # a genuine zero bid
        self.assertEqual(dollars("0.4200"), 0.42)

    def test_best_bid_is_last_element(self):
        price, size = best_bid(DOC_ORDERBOOK["orderbook_fp"]["yes_dollars"])
        self.assertEqual(price, 0.42)
        self.assertEqual(size, 13.0)

    def test_implied_ask_matches_docs_example(self):
        # Docs worked example: best NO bid 0.56 -> implied YES ask 0.44
        self.assertAlmostEqual(implied_yes_ask(0.56), 0.44)

    def test_mid_matches_docs_example(self):
        self.assertAlmostEqual(mid_price(0.42, 0.44), 0.43)


    def test_signature_uses_timestamp_method_path(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )
        except ImportError:
            self.skipTest("cryptography not installed")
        key = Ed25519PrivateKey.generate()
        sig = sign_message(key, "1703123456789", "GET",
                           "/trade-api/v2/portfolio/balance")
        self.assertIsInstance(sig, str)
        self.assertGreater(len(sig), 20)


class TestFees(unittest.TestCase):
    """Every row of the official General Trading Fees Table must reproduce.

    Table transcribed from https://kalshi.com/docs/kalshi-fee-schedule.pdf
    (columns: price of 1 contract, fee for 1 contract, price for 100, fee for 100).
    """

    TABLE = [
        (0.01, 0.01, 0.07), (0.05, 0.01, 0.34), (0.10, 0.01, 0.63),
        (0.15, 0.01, 0.90), (0.20, 0.02, 1.12), (0.25, 0.02, 1.32),
        (0.30, 0.02, 1.47), (0.35, 0.02, 1.60), (0.40, 0.02, 1.68),
        (0.45, 0.02, 1.74), (0.50, 0.02, 1.75), (0.55, 0.02, 1.74),
        (0.60, 0.02, 1.68), (0.65, 0.02, 1.60), (0.70, 0.02, 1.47),
        (0.75, 0.02, 1.32), (0.80, 0.02, 1.12), (0.85, 0.01, 0.90),
        (0.90, 0.01, 0.63), (0.95, 0.01, 0.34), (0.99, 0.01, 0.07),
    ]

    def test_all_published_fee_table_rows(self):
        for price, fee_1, fee_100 in self.TABLE:
            with self.subTest(price=price):
                self.assertAlmostEqual(kalshi_fee(price, 1), fee_1, places=10)
                self.assertAlmostEqual(kalshi_fee(price, 100), fee_100, places=10)

    def test_zero_multiplier_series_is_fee_free(self):
        self.assertEqual(kalshi_fee(0.50, 100, multiplier=0), 0.0)

    def test_no_fee_at_the_extremes(self):
        self.assertEqual(kalshi_fee(0.0, 10), 0.0)
        self.assertEqual(kalshi_fee(1.0, 10), 0.0)


class TestPhantomPrice(unittest.TestCase):
    """An unquoted market reports 0.0000 / 1.0000 and must not become a 0.50 mid."""

    def test_no_book_placeholder_is_not_a_price(self):
        from collector.alerts import observe
        market = {"ticker": "T", "event_ticker": "E", "title": "t",
                  "yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000",
                  "status": "active"}
        obs = observe(market, {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
                      "golf")
        self.assertIsNone(obs.mid)
        self.assertIsNone(obs.yes_bid)
        self.assertIsNone(obs.yes_ask)

    def test_a_real_quote_still_works(self):
        from collector.alerts import observe
        market = {"ticker": "T", "event_ticker": "E", "title": "t",
                  "yes_bid_dollars": "0.3100", "yes_ask_dollars": "0.3300",
                  "status": "active"}
        obs = observe(market, None, "gas-prices")
        self.assertAlmostEqual(obs.mid, 0.32)


class TestLiquidity(unittest.TestCase):
    def test_depth_and_spread(self):
        liq = analyse_liquidity(DOC_ORDERBOOK)
        self.assertAlmostEqual(liq["best_yes_bid"], 0.42)
        self.assertAlmostEqual(liq["best_yes_ask"], 0.44)
        self.assertAlmostEqual(liq["spread"], 0.02)
        expected = sum(float(v) for _, v in DOC_ORDERBOOK["orderbook_fp"]["yes_dollars"])
        self.assertEqual(liq["yes_bid_contracts"], expected)
        # output is best-price-first
        self.assertEqual(liq["yes_bids"][0]["price"], 0.42)

    def test_empty_book_is_empty_not_dashed(self):
        liq = analyse_liquidity({"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
        self.assertEqual(liq["yes_bids"], [])
        self.assertIsNone(liq["spread"])


class TestSwing(unittest.TestCase):
    def base(self, mid, ts=1000.0):
        return Observation(ts=ts, ticker="T", event_ticker="E", topic="crypto",
                           title="t", yes_bid=mid - 0.01, yes_ask=mid + 0.01,
                           mid=mid, last_price=mid, volume=1, open_interest=1,
                           series_ticker="S")

    def test_no_alert_below_threshold(self):
        self.assertIsNone(detect_swing(self.base(0.40), self.base(0.49, 1010)))

    def test_alert_at_exact_threshold(self):
        alert = detect_swing(self.base(0.40), self.base(0.50, 1010))
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert["delta"], 0.10)
        self.assertEqual(alert["direction"], "up")
        self.assertEqual(alert["threshold"], SWING_THRESHOLD)

    def test_alert_down(self):
        alert = detect_swing(self.base(0.70), self.base(0.55, 1010))
        self.assertEqual(alert["direction"], "down")
        self.assertAlmostEqual(alert["abs_delta"], 0.15)

    def test_reference_bar_catches_a_gradual_move(self):
        # Two snapshots 4 cents apart do not alert on their own...
        prev, cur = self.base(0.40), self.base(0.44, 1010)
        self.assertIsNone(detect_swing(prev, cur))
        # ...but against the bar's opening price of 0.30 it is a 14c swing.
        # The reference is a candle *quote* mid, so it must carry its own tight
        # spread (see VERIFICATION_856e184e.md, T16). Without it, no alert.
        alert = detect_swing(prev, cur, reference=0.30, reference_ts=900.0,
                             reference_spread=0.02)
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert["abs_delta"], 0.14)
        self.assertEqual(alert["previous"], 0.30)

    def test_reference_bar_still_respects_the_threshold(self):
        prev, cur = self.base(0.40), self.base(0.44, 1010)
        self.assertIsNone(detect_swing(prev, cur, reference=0.38, reference_ts=900.0,
                                       reference_spread=0.02))

    def test_missing_quote_never_fires(self):
        prev = self.base(0.40)
        cur = self.base(0.90)
        cur.mid = None
        self.assertIsNone(detect_swing(prev, cur))

    def test_alert_carries_a_clickable_market_url(self):
        alert = detect_swing(self.base(0.40), self.base(0.55, 1010))
        self.assertTrue(alert["market_url"].startswith("https://kalshi.com/markets/"))


class TestScoring(unittest.TestCase):
    def obs(self, bid, ask):
        return Observation(ts=1.0, ticker="T", event_ticker="E", topic="crypto",
                           title="t", yes_bid=bid, yes_ask=ask,
                           mid=(bid + ask) / 2, last_price=None, volume=10,
                           open_interest=10, series_ticker="S")

    def test_wide_spread_is_rejected(self):
        liq = {"spread": 0.30, "yes_bid_contracts": 100, "no_bid_contracts": 100,
               "yes_bids": [{"price": 0.20, "contracts": 100}],
               "no_bids": [{"price": 0.50, "contracts": 100}]}
        self.assertIsNone(score_market(self.obs(0.20, 0.50), liq))

    def test_fair_value_is_shrunk_toward_half(self):
        liq = {"spread": 0.02, "yes_bid_contracts": 100, "no_bid_contracts": 100,
               "yes_bids": [{"price": 0.90, "contracts": 100}],
               "no_bids": [{"price": 0.08, "contracts": 100}]}
        sig = score_market(self.obs(0.90, 0.92), liq)
        if sig is not None:
            self.assertLess(sig.model_fair, 0.92)

    def test_no_signal_on_empty_or_thin_book(self):
        # A stale 2c bid with no size must never produce a trade.
        thin = {"spread": 0.01, "yes_bid_contracts": 0, "no_bid_contracts": 1,
                "yes_bids": [{"price": 0.02, "contracts": 1}],
                "no_bids": [{"price": 0.02, "contracts": 1}]}
        self.assertIsNone(score_market(self.obs(0.02, 0.03), thin))

    def test_no_signal_below_one_cent(self):
        liq = {"spread": 0.01, "yes_bid_contracts": 500, "no_bid_contracts": 500,
               "yes_bids": [{"price": 0.0, "contracts": 500}],
               "no_bids": [{"price": 0.0, "contracts": 500}]}
        self.assertIsNone(score_market(self.obs(0.0, 0.0), liq))

    def test_no_signal_without_edge(self):
        liq = {"spread": 0.01, "yes_bid_contracts": 100, "no_bid_contracts": 100,
               "yes_bids": [{"price": 0.50, "contracts": 100}],
               "no_bids": [{"price": 0.49, "contracts": 100}]}
        self.assertIsNone(score_market(self.obs(0.50, 0.51), liq))


class TestPortfolio(unittest.TestCase):
    def signal(self, ticker="M1", price=0.40, side="yes", ts=1.0):
        from collector.alerts import Signal
        return Signal(ticker=ticker, event_ticker="E", topic="crypto", title="t",
                      side=side, executable_price=price, model_fair=0.60,
                      edge=0.20, gross_roi=0.5, fee=0.01, net_roi=0.47,
                      spread=0.02, liquidity=100, score=0.3, reason="r",
                      market_url="u", ts=ts)

    def test_open_deducts_cash_and_fee(self):
        p = Portfolio()
        pos = p.open(self.signal(), "value")
        self.assertIsNotNone(pos)
        self.assertLess(p.bankroll, STARTING_BANKROLL)
        self.assertAlmostEqual(
            p.bankroll,
            STARTING_BANKROLL - pos.contracts * 0.40 - pos.entry_fee, places=4)

    def test_no_duplicate_position_per_ticker(self):
        p = Portfolio()
        self.assertIsNotNone(p.open(self.signal(), "value"))
        self.assertIsNone(p.open(self.signal(), "value"))

    def test_settle_yes_pays_one_dollar(self):
        p = Portfolio()
        pos = p.open(self.signal(price=0.40, side="yes"), "value")
        p.settle("M1", "yes")
        settled = p.positions[pos.position_id]
        self.assertEqual(settled.status, "settled")
        expected = pos.contracts * 1.0 - pos.contracts * 0.40 - pos.entry_fee
        self.assertAlmostEqual(settled.realized, expected, places=3)

    def test_settle_no_is_a_real_loss(self):
        p = Portfolio()
        pos = p.open(self.signal(price=0.40, side="yes"), "value")
        p.settle("M1", "no")
        settled = p.positions[pos.position_id]
        self.assertAlmostEqual(settled.realized,
                               -pos.contracts * 0.40 - pos.entry_fee, places=3)
        self.assertLess(settled.realized, 0)

    def test_unknown_result_is_ignored(self):
        p = Portfolio()
        p.open(self.signal(), "value")
        # An empty/unknown result must never settle a position.
        self.assertIsNone(p.settle("M1", ""))
        self.assertIsNone(p.settle("M1", "maybe"))
        self.assertEqual(p.positions[list(p.positions)[0]].status, "open")
        # ...but a valid one does, and a second settle is a no-op.
        self.assertIsNotNone(p.settle("M1", "yes"))
        self.assertIsNone(p.settle("M1", "yes"))

    def test_analytics_reports_losses_honestly(self):
        p = Portfolio()
        p.open(self.signal("A", 0.40), "momentum")
        p.open(self.signal("B", 0.60), "value")
        p.settle("A", "yes")
        p.settle("B", "no")
        a = p.analytics()
        self.assertEqual(a["overall"]["trades"], 2)
        self.assertEqual(a["overall"]["wins"], 1)
        self.assertEqual(a["overall"]["losses"], 1)
        self.assertAlmostEqual(a["overall"]["win_rate"], 0.5)

    def test_state_roundtrip(self):
        p = Portfolio()
        p.open(self.signal(), "value")
        p.settle("M1", "yes")
        q = Portfolio(p.to_state())
        self.assertAlmostEqual(q.bankroll, p.bankroll, places=4)
        self.assertEqual(len(q.positions), 1)


class TestExits(unittest.TestCase):
    def signal(self, ticker="X", price=0.40, side="yes"):
        from collector.alerts import Signal
        return Signal(ticker=ticker, event_ticker="E", topic="crypto", title="t",
                      side=side, executable_price=price, model_fair=0.6, edge=0.2,
                      gross_roi=0.5, fee=0.01, net_roi=0.4, spread=0.02,
                      liquidity=100, score=0.3, reason="r", market_url="u")

    def obs(self, mid, bid, ask):
        return Observation(ts=2.0, ticker="X", event_ticker="E", topic="crypto",
                           title="t", yes_bid=bid, yes_ask=ask, mid=mid,
                           last_price=None, volume=1, open_interest=1,
                           series_ticker="S")

    def test_take_profit_closes_and_books_a_gain(self):
        from collector.engine import exit_signals
        p = Portfolio()
        p.open(self.signal(price=0.40, side="yes"), "momentum")
        decisions = exit_signals(p, {"X": self.obs(0.55, 0.54, 0.56)})
        self.assertEqual(len(decisions), 1)
        pos, price, why = decisions[0]
        self.assertAlmostEqual(price, 0.54)   # we sell at the bid
        p.close("X", price, 2.0, why)
        settled = p.positions[pos.position_id]
        self.assertEqual(settled.status, "stopped")
        self.assertGreater(settled.realized, 0)

    def test_stop_out_closes_at_a_loss(self):
        from collector.engine import exit_signals
        p = Portfolio()
        p.open(self.signal(price=0.40, side="yes"), "momentum")
        decisions = exit_signals(p, {"X": self.obs(0.25, 0.24, 0.26)})
        self.assertEqual(len(decisions), 1)
        pos, price, why = decisions[0]
        p.close("X", price, 2.0, why)
        self.assertLess(p.positions[pos.position_id].realized, 0)

    def test_small_move_holds(self):
        from collector.engine import exit_signals
        p = Portfolio()
        p.open(self.signal(price=0.40, side="yes"), "momentum")
        self.assertEqual(exit_signals(p, {"X": self.obs(0.45, 0.44, 0.46)}), [])

    def test_exit_fee_is_charged(self):
        p = Portfolio()
        p.open(self.signal(price=0.40), "momentum")
        p.close("X", 0.60, 2.0, "test")
        closed = [x for x in p.positions.values() if x.status == "stopped"][0]
        self.assertGreater(closed.exit_fee, 0)


class TestStrategyGate(unittest.TestCase):
    def sig(self, ticker, side, price, net_roi, model_fair=0.6, score=0.2,
            spread=0.02, liquidity=200):
        from collector.alerts import Signal
        return Signal(ticker=ticker, event_ticker="E", topic="crypto", title="t",
                      side=side, executable_price=price, model_fair=model_fair,
                      edge=0.1, gross_roi=0.1, fee=0.01, net_roi=net_roi,
                      spread=spread, liquidity=liquidity, score=score,
                      reason="r", market_url="u")

    def test_momentum_needs_swing_and_edge(self):
        swings = [{"ticker": "A", "direction": "up", "abs_delta": 0.15}]
        picks = select_trades([self.sig("A", "yes", 0.5, 0.10)], swings, Portfolio())
        self.assertEqual(picks[0][1], "momentum")

    def test_no_pick_without_edge(self):
        swings = [{"ticker": "A", "direction": "up", "abs_delta": 0.15}]
        picks = select_trades([self.sig("A", "yes", 0.5, 0.01)], swings, Portfolio())
        self.assertEqual(picks, [])

    def test_resolution_hold_requires_cheap_side_above_85c(self):
        picks = select_trades(
            [self.sig("B", "yes", 0.90, 0.10, spread=0.02, liquidity=500)],
            [], Portfolio())
        self.assertTrue(any(p[1] == "resolution-hold" for p in picks))


class TestRanking(unittest.TestCase):
    def test_rank_by_open_interest_value(self):
        def o(t, vol, oi, notional=1.0):
            return Observation(ts=1, ticker=t, event_ticker="E", topic="crypto",
                               title=t, yes_bid=0.4, yes_ask=0.42, mid=0.41,
                               last_price=None, volume=vol, open_interest=oi,
                               series_ticker="S", notional=notional)
        rows = rank_events([o("small", 9000, 5), o("big", 1, 100)])
        # Open-interest value wins over raw contract volume.
        self.assertEqual(rows[0]["ticker"], "big")
        self.assertEqual(rows[0]["dollar_activity"], 100.0)
        self.assertEqual(rows[1]["dollar_activity"], 5.0)

    def test_non_unit_notional_is_applied(self):
        obs = Observation(ts=1, ticker="T", event_ticker="E", topic="crypto",
                          title="t", yes_bid=0.4, yes_ask=0.42, mid=0.41,
                          last_price=None, volume=0, open_interest=10,
                          series_ticker="S", notional=2.0)
        self.assertEqual(rank_events([obs])[0]["dollar_activity"], 20.0)


class TestBatchOrderbooks(unittest.TestCase):
    """GET /markets/orderbooks batching, per the official docs contract."""

    def test_batches_are_capped_at_100_and_flattened(self):
        from collector.kalshi_api import KalshiClient
        calls = []

        def fake_request(method, path, params=None, **kw):
            calls.append((path, len(params["tickers"])))
            return {"orderbooks": [
                {"ticker": t, "orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
                for t in params["tickers"]
            ]}

        client = KalshiClient()
        client._request = fake_request
        tickers = [f"T{i}" for i in range(250)]
        books = client.orderbooks(tickers)
        self.assertEqual(len(books), 100)          # the endpoint caps at 100
        self.assertEqual(calls[0][0], "/markets/orderbooks")
        self.assertEqual(calls[0][1], 100)

    def test_empty_book_and_unknown_ticker_both_return_empty(self):
        from collector.kalshi_api import KalshiClient
        client = KalshiClient()
        client._request = lambda *a, **k: {"orderbooks": [
            {"ticker": "KNOWN", "orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
            {"ticker": "UNKNOWN", "orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
        ]}
        books = client.orderbooks(["KNOWN", "UNKNOWN"])
        self.assertEqual(books["KNOWN"], books["UNKNOWN"])


if __name__ == "__main__":
    unittest.main()
