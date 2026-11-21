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
import tempfile
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
    reconcile,
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


class TestStateRoundTrip(unittest.TestCase):
    """The account has to survive the run. `main()` reads back the file `main()`
    writes, and that file keeps cash / fees_paid / realised under `account`.
    Reading only top-level keys reset them every run: the 2026-11-21T06:24:59Z book
    published cash $10,000.00 against $8,688.09 implied by its own 18 rows,
    fees_paid $0.00 against $194.87 charged, realized_pnl $0.00 next to
    stats.all.net_pnl $413.89 in the same file, and `equity` = cash + marks, i.e.
    overstated by exactly $1,311.91."""

    def _payload(self, eng):
        """The shape trading.engine.main() writes."""
        return {
            "generated_at": "2026-11-21T08:00:00+00:00",
            "mode": "simulated-paper",
            "account": {"starting_cash": START_CASH, "cash": eng.cash,
                        "equity": eng.equity(), "realized_pnl": eng.realized_pnl,
                        "fees_paid": eng.fees_paid, "open_positions": len(eng.positions),
                        "daily_loss_cap": 150.0, "blocked_today": eng.blocked_today,
                        "day_key": eng.day_key, "day_realized": eng.day_realized,
                        "day_start_equity": eng.day_start_equity},
            "positions": list(eng.positions.values()),
            "trades": eng.trades[-300:],
            "stats": stats(eng.trades),
            "equity_curve": eng.equity_curve,
        }

    def test_money_fields_are_restored_from_the_account_block(self):
        eng = Engine()
        eng.open_position("T-1", "yes", 0.40, "value", "quiet-value", "crypto", 1.0, "t")
        closed = eng.close_position("T-1", 0.46, "target")
        self.assertIsNotNone(closed)
        reloaded = Engine(self._payload(eng))
        self.assertEqual(reloaded.cash, eng.cash)
        self.assertEqual(reloaded.fees_paid, eng.fees_paid)
        self.assertEqual(reloaded.realized_pnl, eng.realized_pnl)
        self.assertEqual(reloaded.day_realized, eng.day_realized)
        self.assertGreater(reloaded.fees_paid, 0.0, "fees actually paid must not reset")
        self.assertAlmostEqual(reloaded.cash - START_CASH, reloaded.realized_pnl, places=2)

    def test_top_level_state_still_wins(self):
        """An engine-state dict written by a test or a tool keeps working."""
        state = {"cash": 1234.56, "fees_paid": 9.0, "realized_pnl": -3.0,
                 "account": {"cash": 1.0, "fees_paid": 2.0, "realized_pnl": 3.0}}
        eng = Engine(state)
        self.assertEqual(eng.cash, 1234.56)
        self.assertEqual(eng.fees_paid, 9.0)
        self.assertEqual(eng.realized_pnl, -3.0)

    def test_a_stale_day_key_resets_the_daily_cap(self):
        payload = self._payload(Engine())
        payload["account"]["day_key"] = "2000-01-01"
        payload["account"]["day_realized"] = -500.0
        payload["account"]["blocked_today"] = True
        eng = Engine(payload)
        self.assertEqual(eng.day_realized, 0.0)
        self.assertFalse(eng.blocked_today, "yesterday's block must not last forever")

    def test_todays_day_key_keeps_the_block(self):
        eng = Engine()
        payload = self._payload(eng)
        payload["account"]["day_key"] = eng.day_key
        payload["account"]["day_realized"] = -500.0
        payload["account"]["blocked_today"] = True
        reloaded = Engine(payload)
        self.assertTrue(reloaded.blocked_today)
        self.assertIsNone(reloaded.open_position("T-BLOCKED", "yes", 0.40, "value",
                                                 "x", "crypto", 1.0, "t"),
                          "the published risk limit has to bind")


class TestReconciliationAndEndToEnd(unittest.TestCase):
    """`reconcile()` publishes the ledger-implied numbers beside the account ones,
    and an end-to-end two-run sequence proves the bankroll no longer resets."""

    def _write_inputs(self, data_dir: Path, bid: float, alerts):
        import json as _json
        (data_dir / "markets.json").write_text(_json.dumps({"rows": [
            {"ticker": "T-E2E", "status": "open", "topic": "crypto", "fee_multiplier": 1.0,
             "event_ticker": "T-E2E-EV"}]}))
        (data_dir / "orderbooks.json").write_text(_json.dumps({"books": {
            "T-E2E": {"best_yes_bid": bid, "best_no_bid": round(bid - 0.01, 4),
                      "yes_depth_usd": 1000, "no_depth_usd": 1000}}}))
        (data_dir / "alerts.json").write_text(_json.dumps({"alerts": alerts}))
        (data_dir / "resolutions.json").write_text(_json.dumps({"rows": []}))

    def test_reconcile_is_zero_for_a_consistent_book(self):
        eng = Engine()
        eng.open_position("T-R", "yes", 0.40, "value", "quiet-value", "crypto", 1.0, "t")
        eng.close_position("T-R", 0.46, "target")
        rec = reconcile(eng)
        self.assertEqual(rec["cash_delta"], 0.0)
        self.assertEqual(rec["fees_delta"], 0.0)
        self.assertEqual(rec["realized_delta"], 0.0)
        self.assertFalse(rec["log_may_be_truncated"])
        self.assertGreater(rec["fees_implied_by_trade_log"], 0.0)

    def test_two_runs_keep_the_account_and_the_lab_can_recompute_it(self):
        import json as _json
        import trading.engine as engine_mod
        tmp = Path(tempfile.mkdtemp())
        saved = engine_mod.DATA
        try:
            engine_mod.DATA = str(tmp)
            self._write_inputs(tmp, 0.50, [{"ticker": "T-E2E", "delta": -0.20,
                                            "window": "60m"}])
            self.assertEqual(engine_mod.main([]), 0)
            first = _json.loads((tmp / "portfolio.json").read_text())
            self.assertEqual(first["account"]["open_positions"], 1)
            self.assertLess(first["account"]["cash"], START_CASH,
                            "run 1 spent something; the published cash must show it")
            self.assertEqual(first["ledger_reconciliation"]["cash_delta"], 0.0)

            # run 2: no new alerts, mark moves +0.06 -> the position takes profit
            self._write_inputs(tmp, 0.57, [])
            self.assertEqual(engine_mod.main([]), 0)
            second = _json.loads((tmp / "portfolio.json").read_text())
            rec = second["ledger_reconciliation"]
            self.assertEqual(rec["cash_delta"], 0.0)
            self.assertEqual(rec["fees_delta"], 0.0)
            self.assertEqual(rec["realized_delta"], 0.0)
            # The exit happened (one closed round trip) and the book then took the
            # next opportunity its own rules allow, so `open_positions` is 1 again —
            # what this test pins is that the money fields carried across the run
            # instead of resetting, and that they stay consistent with the ledger.
            self.assertEqual(second["stats"]["all"]["trades"], 1)
            self.assertGreater(second["account"]["fees_paid"], 0.0,
                               "both legs were charged and both were kept")
            self.assertLess(second["account"]["cash"], START_CASH,
                            "an account holding a position has spent money")
            held = second["positions"][0] if second["positions"] else {}
            held_cost = round(float(held.get("contracts") or 0)
                              * float(held.get("avg_price") or 0)
                              + float(held.get("entry_fee") or 0), 2)
            self.assertAlmostEqual(second["account"]["cash"] - START_CASH,
                                   second["account"]["realized_pnl"] - held_cost, places=2,
                                   msg="cash = start + realised - what is still held")
            # Two different, both-correct fee scopes, pinned so they can never be
            # confused again: the account total is every leg charged so far (open
            # positions included), while `stats.fees` is the two legs of each CLOSED
            # round trip — which is what the strategy-lab cross-check compares.
            self.assertEqual(second["account"]["fees_paid"], rec["fees_implied_by_trade_log"])
            closed_rows = [r for r in second["trades"] if r["action"] == "close"]
            self.assertEqual(second["stats"]["all"]["fees"],
                             round(sum(float(r["fee"] or 0) + float(r["entry_fee"] or 0)
                                       for r in closed_rows), 2))
        finally:
            engine_mod.DATA = saved


if __name__ == "__main__":
    unittest.main()
