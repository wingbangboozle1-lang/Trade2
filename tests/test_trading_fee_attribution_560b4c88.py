"""Docs-sim ledger fee attribution — session `arena-560b4c88` (Board `arena-560b4c88`, M1).

Why these tests exist
---------------------
`docs/data/strategy_lab.json` has carried an unresolved cross-check item since
2026-11-20:

    {"book": "docs-sim book", "metric": "fees (entry+exit)",
     "published": 51.52, "recomputed": 65.24}

Re-derived against the book on `main`: `stats.all.fees` was the sum of the CLOSE-ROW
fees only, because `trading/engine.py::close_position` booked
`proceeds - cost - exit_fee` and never subtracted the position's entry fee — although
`open_position` had already taken that fee out of `cash`. The root book
(`collector/engine.py`) does subtract it, so the same site published "Net P&L" and
"Fees" for two books on two different bases.

Official basis for "both legs" (fetched 2026-11-21, https://kalshi.com/docs/kalshi-fee-schedule.pdf):
    "Trading fees are only charged for orders that are immediately matched with orders
     sitting on the orderbook."   -> an entry that crosses and an exit that crossing
                                     are two charged executions
    "There is no settlement fee." -> a settled position pays nothing more
and https://docs.kalshi.com/getting_started/market_settlement:
    "**Yes outcome**: Yes contract holders receive $1 per contract
     **No outcome**: No contract holders receive $1 per contract"

Run: python3 -m unittest tests.test_trading_fee_attribution_560b4c88 -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.engine import (  # noqa: E402
    EXIT_TARGET,
    START_CASH,
    Engine,
    fee_taker,
    stats,
)


def _book(bid: float) -> dict:
    return {"best_yes_bid": bid, "best_no_bid": round(1.0 - bid + 0.01, 4),
            "yes_depth_usd": 500, "no_depth_usd": 500}


class TestBothLegsAreCharged(unittest.TestCase):
    """net = proceeds - cost - exit fee - entry fee, on both exit paths."""

    def test_book_exit_nets_the_entry_leg_too(self):
        eng = Engine()
        pos = eng.open_position("T-EXIT", "yes", 0.40, "roi_edge", "unit", "crypto",
                                1.0, "test")
        self.assertIsNotNone(pos)
        entry_fee = pos["entry_fee"]
        cash_after_open = eng.cash
        self.assertAlmostEqual(cash_after_open,
                               START_CASH - pos["contracts"] * 0.40 - entry_fee, places=2)

        exit_price = 0.40 + EXIT_TARGET
        closed = eng.close_position("T-EXIT", exit_price, "target")
        self.assertIsNotNone(closed)
        exit_fee = closed["exit_fee"]
        expected = round(closed["contracts"] * exit_price
                         - closed["contracts"] * 0.40 - exit_fee - entry_fee, 2)
        self.assertEqual(closed["pnl"], expected)
        self.assertLess(closed["pnl"], round(closed["contracts"] * EXIT_TARGET
                                             - exit_fee, 2),
                        "entry leg must make the booked net smaller, not equal")
        self.assertEqual(closed["total_fees"], round(entry_fee + exit_fee, 2))

    def test_cash_identity_holds_when_everything_is_closed(self):
        """The accounting identity the old code broke: with no position open,
        cash - start cash == realised pnl, which is only true if both legs' fees
        are inside the realised number."""
        eng = Engine()
        for i, px in enumerate((0.20, 0.50, 0.75)):
            pos = eng.open_position(f"T-{i}", "yes", px, "roi_edge", "unit", "crypto",
                                    1.0, "test")
            self.assertIsNotNone(pos, f"position {i} should open")
        for i, px in enumerate((0.20, 0.50, 0.75)):
            eng.close_position(f"T-{i}", round(px + 0.05, 2), "target")
        self.assertEqual(eng.positions, {})
        self.assertAlmostEqual(eng.cash - START_CASH, eng.realized_pnl, places=2,
                               msg="fees charged to cash must appear in realised pnl")

    def test_settlement_win_pays_no_exit_fee_but_keeps_the_entry_fee(self):
        eng = Engine()
        pos = eng.open_position("T-WIN", "yes", 0.40, "roi_edge", "unit", "crypto",
                                1.0, "test")
        entry_fee = pos["entry_fee"]
        closed = eng.close_position("T-WIN", 0.0, "settled", settlement="yes")
        self.assertEqual(closed["exit_fee"], 0.0)  # "There is no settlement fee."
        self.assertEqual(closed["pnl"], round(closed["contracts"] * 1.0
                                              - closed["contracts"] * 0.40 - entry_fee, 2))
        self.assertEqual(closed["total_fees"], round(entry_fee, 2))

    def test_settlement_loss_is_cost_plus_entry_fee(self):
        eng = Engine()
        pos = eng.open_position("T-LOSE", "no", 0.30, "roi_edge", "unit", "crypto",
                                1.0, "test")
        entry_fee = pos["entry_fee"]
        closed = eng.close_position("T-LOSE", 0.0, "settled", settlement="yes")
        self.assertEqual(closed["pnl"], round(-(closed["contracts"] * 0.30) - entry_fee, 2))


class TestLogRowsCarryTheSplit(unittest.TestCase):
    def test_close_row_records_entry_fee_and_open_row_does_not(self):
        eng = Engine()
        pos = eng.open_position("T-LOG", "yes", 0.50, "roi_edge", "unit", "crypto",
                                1.0, "test")
        opens = [t for t in eng.trades if t["action"] == "open"]
        self.assertEqual(opens[-1]["entry_fee"], None,
                         "an open row's own fee IS the entry leg; entry_fee is the "
                         "round-trip field and belongs on close rows only")
        eng.close_position("T-LOG", 0.55, "target")
        closes = [t for t in eng.trades if t["action"] == "close"]
        self.assertEqual(closes[-1]["entry_fee"], pos["entry_fee"])
        self.assertGreater(closes[-1]["fee"], 0, "the close row carries its own leg fee")

    def test_total_fees_equals_the_sum_of_the_two_leg_rows(self):
        eng = Engine()
        eng.open_position("T-SUM", "yes", 0.40, "roi_edge", "unit", "crypto", 1.0, "t")
        eng.close_position("T-SUM", 0.45, "target")
        open_fee = [t for t in eng.trades if t["action"] == "open"][-1]["fee"]
        close = [t for t in eng.trades if t["action"] == "close"][-1]
        self.assertEqual(close["total_fees"], round(open_fee + close["fee"], 2))


class TestStatsAggregateBothLegs(unittest.TestCase):
    def test_stats_fees_match_the_published_trade_rows(self):
        eng = Engine()
        eng.open_position("T-A", "yes", 0.40, "roi_edge", "high-roi-fade", "crypto", 1.0, "t")
        eng.close_position("T-A", 0.45, "target")
        eng.open_position("T-B", "yes", 0.60, "swing_momentum", "swing-up", "crypto", 1.0, "t")
        eng.close_position("T-B", 0.65, "target")
        s = stats(eng.trades)
        rows = eng.trades
        want = round(sum(float(t["fee"] or 0.0) for t in rows), 2)
        self.assertEqual(s["all"]["fees"], want,
                         "both legs of every closed round trip, from the same rows")
        self.assertEqual(s["all"]["trades"], 2)
        self.assertEqual(set(s["by_strategy"]), {"roi_edge", "swing_momentum"})
        per_group = round(sum(g["fees"] for g in s["by_strategy"].values()), 2)
        self.assertAlmostEqual(per_group, s["all"]["fees"], places=2)

    def test_legacy_close_row_gets_its_entry_leg_paired_and_counted(self):
        """A ledger written before the rule has no entry_fee on its close rows.
        The fee is recovered from the matching open row and the group says so."""
        legacy = [
            {"action": "open", "ticker": "T-OLD", "fee": 9.00, "pnl": 0.0,
             "strategy": "roi_edge", "trade_type": "roi_edge|high-roi-fade|yes"},
            {"action": "close", "ticker": "T-OLD", "fee": 11.00, "pnl": 14.00,
             "strategy": "roi_edge", "trade_type": "roi_edge|high-roi-fade|yes"},
        ]
        s = stats(legacy)
        self.assertEqual(s["all"]["fees"], 20.00, "9.00 entry + 11.00 exit")
        self.assertEqual(s["all"]["fees_rows_without_recorded_entry_fee"], 1)
        self.assertEqual(s["all"]["net_pnl"], 14.00,
                         "a historical pnl is never restated")
        self.assertEqual(s["fee_convention"]["close_rows_with_no_recorded_entry_fee_paired_from_the_log"], 1)

    def test_unpairable_legacy_row_is_zero_not_guessed(self):
        orphan = [{"action": "close", "ticker": "T-GONE", "fee": 3.00, "pnl": 5.00,
                   "strategy": "value", "trade_type": "value|None|yes"}]
        s = stats(orphan)
        self.assertEqual(s["all"]["fees"], 3.00, "no recorded and no pairable entry leg")
        self.assertEqual(s["all"]["fees_rows_without_recorded_entry_fee"], 1)

    def test_convention_is_published_with_the_numbers(self):
        conv = stats([{"action": "close", "ticker": "T", "fee": 1.0, "entry_fee": 1.0,
                       "pnl": 2.0, "strategy": "s", "trade_type": "s|x|yes"}]
                     )["fee_convention"]
        self.assertEqual(conv["both_legs_since"], "2026-11-21")
        self.assertEqual(conv["source"], "https://kalshi.com/docs/kalshi-fee-schedule.pdf")
        self.assertIn("settlement pays no fee", conv["rule"])

    def test_fee_multiplier_of_the_series_changes_both_legs(self):
        """A fee-free series (multiplier 0, e.g. KXBTCY in the PDF's non-standard
        table) must show zero on BOTH legs, so a 0-fee entry cannot pair with a
        charged exit by accident."""
        self.assertEqual(fee_taker(100, 0.50, 0.0), 0.0)
        self.assertEqual(fee_taker(100, 0.50, 1.0), 1.75)


class TestPayloadCarriesTheBasis(unittest.TestCase):
    def test_source_is_the_official_fee_schedule(self):
        """Guard against the rule citing some other authority than the PDF that
        states it, and against the payload losing the basis string."""
        import trading.engine as engine_mod
        self.assertEqual(engine_mod.FEE_SCHEDULE_URL,
                         "https://kalshi.com/docs/kalshi-fee-schedule.pdf")
        text = (Path(ROOT) / "trading" / "engine.py").read_text()
        self.assertIn("There is no settlement fee.", text)
        self.assertIn("immediately matched", text)
        self.assertIn('\"fee_legs\": "entry leg + exit leg; settlement pays no fee"', text)
        self.assertIn('\"net_pnl_basis\":', text)


class TestPerSeriesMultiplierSymmetry(unittest.TestCase):
    """The entry leg was priced with the series' own multiplier and the exit leg with
    the default. Official basis: the schedule's Non-Standard Fees table sets
    per-series multipliers, and 'M = the multiplier for each contract (default is 1
    unless otherwise indicated)' — https://kalshi.com/docs/kalshi-fee-schedule.pdf.
    The root book already keeps `fee_multiplier` on the position and uses it on exit
    (`collector/engine.py`); this pins that the docs-sim book does the same."""

    def test_fee_free_series_exits_fee_free(self):
        eng = Engine()
        pos = eng.open_position("T-FREE", "yes", 0.50, "value", "quiet-value", "crypto",
                                0.0, "series with taker multiplier 0")
        self.assertEqual(pos["entry_fee"], 0.0)
        self.assertEqual(pos["fee_multiplier"], 0.0)
        closed = eng.close_position("T-FREE", 0.55, "target")
        self.assertEqual(closed["exit_fee"], 0.0,
                         "a fee-free entry must not be followed by a charged exit")
        self.assertEqual(closed["pnl"], round(closed["contracts"] * 0.05, 2))

    def test_charged_series_charges_both_legs(self):
        eng = Engine()
        pos = eng.open_position("T-M1", "yes", 0.50, "value", "quiet-value", "crypto",
                                1.0, "standard multiplier")
        self.assertEqual(pos["entry_fee"], 7.00)  # ceil(0.07*400*0.5*0.5)
        closed = eng.close_position("T-M1", 0.55, "target")
        # 0.07*400*0.55*0.45 = 6.930, already a whole cent, so the round-up changes
        # nothing here — the point of the assertion is that the exit leg used M = 1
        # and not the free series' 0.
        self.assertEqual(closed["exit_fee"], 6.93)
        self.assertEqual(closed["total_fees"], 13.93)

    def test_legacy_position_defaults_to_the_documented_multiplier(self):
        """State written before the field existed must not silently become free."""
        eng = Engine()
        pos = eng.open_position("T-OLD", "yes", 0.50, "value", "quiet-value", "crypto",
                                1.0, "t")
        del eng.positions["T-OLD"]["fee_multiplier"]
        closed = eng.close_position("T-OLD", 0.55, "target")
        self.assertEqual(closed["exit_fee"], 6.93)
        self.assertEqual(closed["entry_fee"], pos["entry_fee"])


if __name__ == "__main__":
    unittest.main()
