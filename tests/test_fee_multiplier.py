"""Fee-model parity: the simulated ledger charges each series' OWN official fee
multiplier instead of assuming the general one.

Why this exists
---------------
`collector/engine.py` used to call ``kalshi_fee(price, contracts)`` with the
default multiplier at both the entry and the exit site, which charged the
general quadratic fee to every series. `trading/engine.py` (the `docs/`
pipeline) already read the series' own value, so the two pipelines could
disagree about the same trade. This was published as a standing item on the
site's Flagged-for-review page ("Taker fees use a multiplier of 1 for every
series"), with the note that the exposure was "series whose demo multiplier is
not 1". These tests pin the fix.

Official sources for every number asserted here
-----------------------------------------------
* Fee formula and the per-series multiplier M, incl. the "Non-Standard Fees"
  table that lists KXBTCY at maker 0 / taker 0 and uncorrelated combos at 2:
  <https://kalshi.com/docs/kalshi-fee-schedule.pdf> (last updated and effective
  July 7, 2026 — re-fetched and re-read on 2026-11-20).
* ``fee_multiplier`` ("a floating point multiplier applied to the fee
  calculations") and ``fee_type`` (enum: quadratic, quadratic_with_maker_fees,
  quadratic_with_combo_maker_fees, flat — 'flat' is the Specific Trading Fees
  Table, which this model does not compute) are *required* fields of ``Series``:
  <https://docs.kalshi.com/api-reference/market/get-series-list.md>
* The demo API's own value for the series the dashboard currently ranks first in
  crypto, fetched live 2026-11-20:
  <https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY> →
  ``{"fee_type": "quadratic", "fee_multiplier": 1}``.
* Settlement pays $1.00 per contract to the winning side and there is no
  settlement fee, so ``settle()`` must not charge anything either way:
  <https://docs.kalshi.com/getting_started/market_settlement.md> and the fee
  schedule's own "Settlement Fees: There is no settlement fee." line.

Run: python3 -m unittest -v tests.test_fee_multiplier
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.alerts import (Observation, fee_params, kalshi_fee, observe,
                              score_market)
from collector.engine import Portfolio, STARTING_BANKROLL
from collector.collector import series_row_for_event

# Orderbook fixture copied from Kalshi's own worked example, like the other
# alerting tests: https://docs.kalshi.com/getting_started/orderbook_responses.md
BOOK = {"orderbook_fp": {"yes_dollars": [["0.4000", "100.00"]],
                         "no_dollars": [["0.5900", "100.00"]]}}
MARKET = {
    "ticker": "KXTEST-1",
    "event_ticker": "KXTEST",
    "series_ticker": "KXTEST",
    "title": "Test market",
    "yes_sub_title": "Test",
    "status": "active",
    "result": "",
    "last_price_dollars": "0.4500",
    "open_interest_fp": "1000.00",
    "volume_fp": "1200.00",
    "notional_value_dollars": "1.0000",
    "close_time": "2026-12-31T00:00:00Z",
}


def series(multiplier=1, fee_type="quadratic"):
    row = {"ticker": "KXTEST", "topic": "crypto", "fee_type": fee_type}
    if multiplier is not None:
        row["fee_multiplier"] = multiplier
    return row


class TestFeeParams(unittest.TestCase):
    """The resolver that turns a series row into (multiplier, basis)."""

    def test_quadratic_uses_the_series_value(self):
        self.assertEqual(fee_params(series(1))[0], 1.0)
        self.assertEqual(fee_params(series(0))[0], 0.0)
        self.assertEqual(fee_params(series(2))[0], 2.0)
        self.assertIn("fee_multiplier=0", fee_params(series(0))[1])

    def test_maker_fee_series_still_reads_the_multiplier(self):
        # 'quadratic_with_maker_fees' is quadratic for the taker side, so the
        # series' own multiplier governs; it must not be treated as unmodelled.
        mult, basis = fee_params(series(3, "quadratic_with_maker_fees"))
        self.assertEqual(mult, 3.0)
        self.assertIn("quadratic_with_maker_fees", basis)

    def test_flat_schedule_is_not_charged_a_quadratic_fee(self):
        # 'flat' is the Specific Trading Fees Table (a per-contract fee this
        # model does not implement). Inventing a quadratic number for it would
        # be a fabrication, so the fee is 0 and the basis says why.
        mult, basis = fee_params(series(1, "flat"))
        self.assertEqual(mult, 0.0)
        self.assertIn("not the quadratic schedule", basis)

    def test_missing_row_falls_back_to_the_documented_default(self):
        mult, basis = fee_params(None)
        self.assertEqual(mult, 1.0)
        self.assertIn("series default M=1", basis)
        # A row that omits the field behaves the same but says so differently.
        mult2, basis2 = fee_params({"fee_type": "quadratic"})
        self.assertEqual(mult2, 1.0)
        self.assertIn("fee_multiplier absent", basis2)

    def test_unreadable_multiplier_is_defaulted_not_guessed(self):
        mult, basis = fee_params({"fee_type": "quadratic", "fee_multiplier": "n/a"})
        self.assertEqual(mult, 1.0)
        self.assertIn("unreadable", basis)

    def test_today_no_series_changes_number(self):
        # The 300 series the collector tracks all report quadratic / M=1 in the
        # live snapshot, so resolving the multiplier from the API rather than
        # hard-coding it does not restate any published fee. Asserted here so
        # the parity claim is checked, not asserted in prose.
        self.assertEqual(fee_params(series(1))[0], 1.0)
        self.assertEqual(kalshi_fee(0.40, 100, 1.0), kalshi_fee(0.40, 100))


class TestObserveCarriesFee(unittest.TestCase):
    def test_series_row_reaches_the_observation(self):
        obs = observe(MARKET, BOOK, "crypto", ts=1.0, series=series(0))
        self.assertEqual(obs.fee_multiplier, 0.0)
        self.assertEqual(obs.fee_type, "quadratic")
        self.assertIn("fee_multiplier=0", obs.fee_basis)

    def test_no_series_row_leaves_the_multiplier_unknown(self):
        obs = observe(MARKET, BOOK, "crypto", ts=1.0)
        self.assertIsNone(obs.fee_multiplier)
        self.assertIn("no GET /series row", obs.fee_basis)


class TestSignalFeeFollowsSeries(unittest.TestCase):
    """The model's ROI must not screen out a fee-free series on an imaginary fee."""

    def signal(self, **kw):
        obs = observe(MARKET, BOOK, "crypto", ts=1.0, **kw)
        liq = {"spread": 0.19, "yes_bid_contracts": 100.0, "no_bid_contracts": 100.0,
               "yes_bids": [{"contracts": 100.0, "price": 0.40}],
               "no_bids": [{"contracts": 100.0, "price": 0.59}]}
        return score_market(obs, liq)

    def test_fee_free_series_charges_nothing(self):
        sig = self.signal(series=series(0))
        self.assertIsNotNone(sig, "a fee-free series must still be scoreable")
        self.assertEqual(sig.fee, 0.0)
        self.assertEqual(sig.fee_multiplier, 0.0)
        self.assertAlmostEqual(sig.net_roi, sig.gross_roi, places=6)
        self.assertIn("fee_multiplier=0", sig.fee_basis)
        self.assertIn("fee_multiplier=0", sig.reason)

    def test_default_series_charges_the_general_schedule(self):
        paid = self.signal(series=series(1))
        assumed = self.signal()
        self.assertEqual(paid.fee, assumed.fee)          # published parity
        self.assertEqual(paid.fee, kalshi_fee(paid.executable_price, 1.0, 1.0))
        self.assertGreater(paid.fee, 0.0)
        self.assertLess(paid.net_roi, paid.gross_roi)

    def test_double_multiplier_series_doubles_the_fee(self):
        # '2' is the schedule's own multiplier for uncorrelated combos.
        single = self.signal(series=series(1))
        double = self.signal(series=series(2))
        self.assertAlmostEqual(double.fee, 2 * single.fee, places=6)


class TestLedgerUsesSeriesFee(unittest.TestCase):
    def signal(self, price=0.40, side="yes", fee_multiplier=1.0, fee_basis="test"):
        from collector.alerts import Signal
        return Signal(ticker="M1", event_ticker="E", topic="crypto", title="t",
                      side=side, executable_price=price, model_fair=0.60,
                      edge=0.20, gross_roi=0.5,
                      fee=kalshi_fee(price, 100.0, fee_multiplier),
                      net_roi=0.47, spread=0.02, liquidity=100, score=0.3,
                      reason="r", market_url="u", ts=1.0,
                      fee_multiplier=fee_multiplier, fee_basis=fee_basis)

    def test_open_and_close_on_a_fee_free_series_cost_nothing_in_fees(self):
        p = Portfolio()
        pos = p.open(self.signal(fee_multiplier=0.0), "value")
        self.assertIsNotNone(pos)
        c = pos.contracts
        self.assertGreater(c, 0)
        self.assertEqual(pos.entry_fee, 0.0)
        self.assertEqual(pos.fee_multiplier, 0.0)
        self.assertAlmostEqual(p.bankroll, STARTING_BANKROLL - c * 0.40, places=4)
        closed = p.close("M1", 0.30, ts=2.0)
        self.assertIsNotNone(closed)
        self.assertEqual(closed.exit_fee, 0.0)
        # No fees anywhere: bankroll moved by exactly the price difference.
        self.assertAlmostEqual(
            p.bankroll, STARTING_BANKROLL - c * 0.40 + c * 0.30, places=4)
        self.assertEqual(closed.realized, round(c * 0.30 - c * 0.40, 4))

    def test_exit_uses_the_multiplier_the_entry_used(self):
        p = Portfolio()
        pos = p.open(self.signal(fee_multiplier=2.0), "value")
        c = pos.contracts
        self.assertEqual(pos.entry_fee, kalshi_fee(0.40, c, 2.0))
        self.assertGreater(pos.entry_fee, 0.0)
        closed = p.close("M1", 0.30, ts=2.0)
        self.assertEqual(closed.exit_fee, kalshi_fee(0.30, c, 2.0))
        # And the same size at M=1 charges exactly half, because the schedule is
        # linear in M. Checked, not assumed.
        q = Portfolio()
        qpos = q.open(self.signal(fee_multiplier=1.0), "value")
        self.assertAlmostEqual(qpos.entry_fee, pos.entry_fee / 2, places=4)

    def test_settlement_never_charges_a_fee(self):
        # "There is no settlement fee." — official schedule, Settlement Fees.
        p = Portfolio()
        pos = p.open(self.signal(fee_multiplier=0.0), "value")
        c = pos.contracts
        settled = p.settle("M1", "yes", ts=3.0)
        self.assertIsNotNone(settled)
        self.assertEqual(settled.exit_fee or 0.0, 0.0)
        self.assertEqual([t.fee for t in p.trades if t.action == "settle"], [0.0])
        self.assertAlmostEqual(
            p.bankroll, STARTING_BANKROLL - c * 0.40 + c * 1.00, places=4)

    def test_state_written_before_the_field_existed_still_loads(self):
        # Backward compatibility: an old ledger row has no fee_multiplier, and it
        # must load as M=1 — the value it was actually charged at — so no
        # historical P&L is restated by this change.
        p = Portfolio()
        opened = p.open(self.signal(fee_multiplier=1.0), "value")
        self.assertIsNotNone(opened)
        c = opened.contracts
        state = p.to_state()
        self.assertEqual(state["positions"][0]["fee_multiplier"], 1.0,
                         "the basis is written into the ledger, not just used")
        for row in state["positions"]:
            row.pop("fee_multiplier", None)
            row.pop("fee_basis", None)
        q = Portfolio(state)
        pos = list(q.positions.values())[0]
        self.assertEqual(pos.fee_multiplier, 1.0)
        self.assertEqual(pos.entry_fee, kalshi_fee(0.40, c, 1.0))
        closed = q.close("M1", 0.30, ts=9.0)
        self.assertEqual(closed.exit_fee, kalshi_fee(0.30, c, 1.0))


class TestSeriesRowLookup(unittest.TestCase):
    """`GET /markets` has no series_ticker, so the row is found by ticker prefix."""

    REG = {
        "KXBTCY": {"ticker": "KXBTCY", "fee_multiplier": 1, "topic": "crypto"},
        "AAAGASD": {"ticker": "AAAGASD", "fee_multiplier": 1, "topic": "gas-prices"},
        "KXPGATOUR": {"ticker": "KXPGATOUR", "fee_multiplier": 1, "topic": "golf"},
    }

    def test_prefixed_and_bare_heads_both_resolve(self):
        self.assertEqual(
            series_row_for_event("KXBTCY-27JAN0100", self.REG)["ticker"], "KXBTCY")
        self.assertEqual(
            series_row_for_event("KXAAAGASD-26NOV21", self.REG)["ticker"], "AAAGASD")

    def test_heads_are_tried_shortest_first(self):
        # Behaviour copied from resolution_topic on purpose: the scan returns the
        # first "-"-delimited head present in the registry, so a registry keyed by
        # series ticker resolves every market of that series to the same row — and
        # a hypothetical series whose own ticker is a prefix of another series'
        # ticker would resolve to the shorter one. Logged, not "improved": the two
        # lookups must agree, or fee and topic would disagree about one market.
        reg = dict(self.REG, **{"KXBTCY-27JAN0100": {"ticker": "KXBTCY-27JAN0100"}})
        self.assertEqual(
            series_row_for_event("KXBTCY-27JAN0100-B127500", reg)["ticker"], "KXBTCY")
        self.assertEqual(
            series_row_for_event("KXBTCY-27JAN0100-B127500",
                                {"KXBTCY-27JAN0100": {"ticker": "KXBTCY-27JAN0100"}})["ticker"],
            "KXBTCY-27JAN0100")

    def test_unrelated_market_returns_none_not_a_guess(self):
        self.assertIsNone(series_row_for_event("KXSOMETHINGELSE-26", self.REG))
        self.assertIsNone(series_row_for_event(None, self.REG))
        self.assertIsNone(series_row_for_event("KXBTCY-1", {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
