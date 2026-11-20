#!/usr/bin/env python3
"""Tests for tools/strategy_lab.py (task T32, session arena-5bec0ea3).

Run: python3 -m unittest tests.test_strategy_lab -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import strategy_lab as sl  # noqa: E402


class TestFee(unittest.TestCase):
    def test_official_example_100_at_half(self):
        # Kalshi fee schedule example: 100 contracts at $0.50 -> $1.75
        # (https://kalshi.com/docs/kalshi-fee-schedule.pdf)
        self.assertEqual(sl.taker_fee(Decimal(100), Decimal("0.50")), Decimal("1.75"))

    def test_docs_book_entry_fee_400_at_half(self):
        # docs/data/portfolio.json row: 400 contracts at 0.50 -> fee 7.00
        self.assertEqual(sl.taker_fee(Decimal(400), Decimal("0.50")), Decimal("7.00"))

    def test_rounds_up_to_cent(self):
        # 0.07 * 100 * 0.81 * 0.19 = 1.0773 -> 1.08 (round UP, not nearest)
        self.assertEqual(sl.taker_fee(Decimal(100), Decimal("0.81")), Decimal("1.08"))


class TestNormTs(unittest.TestCase):
    def test_epoch_float_to_iso(self):
        # 1795150800 == 2026-11-20T05:00:00Z (checked against the recorded
        # candle rows in docs/data/candles.json); +39180 s = 10:53:00
        self.assertEqual(sl.norm_ts(1795189980.82), "2026-11-20T15:53:00Z")

    def test_string_passthrough(self):
        self.assertEqual(sl.norm_ts("2026-11-20T14:58:49+00:00"), "2026-11-20T14:58:49+00:00")

    def test_none(self):
        self.assertIsNone(sl.norm_ts(None))


class TestBacktest(unittest.TestCase):
    def _pts(self, closes):
        return [{"t": 1700000000 + 3600 * i, "close": c} for i, c in enumerate(closes)]

    def test_momentum_enters_after_swing(self):
        # +0.12 bar -> buy YES at 0.62, exit at last close 0.70
        pts = self._pts([0.50, 0.62, 0.70])
        trades = sl.run_backtest(pts, "momentum")
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual(t["side"], "yes")
        self.assertEqual(t["entry_px"], 0.62)
        self.assertEqual(t["exit_px"], 0.70)
        # gross = 100 * (0.70 - 0.62) = 8.00
        self.assertAlmostEqual(t["gross"], 8.00, places=6)
        fees = sl.taker_fee(Decimal(100), Decimal("0.62")) + sl.taker_fee(Decimal(100), Decimal("0.70"))
        self.assertAlmostEqual(t["net"], 8.00 - float(fees), places=6)

    def test_mean_reversion_fades_swing(self):
        pts = self._pts([0.50, 0.62, 0.70])
        trades = sl.run_backtest(pts, "mean-reversion")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["side"], "no")

    def test_no_zero_hold_trades(self):
        # swing on the final bar must not produce a trade
        pts = self._pts([0.50, 0.50, 0.62])
        self.assertEqual(sl.run_backtest(pts, "momentum"), [])

    def test_breakout_needs_eleven_priors(self):
        closes = [0.5] * 13
        closes[11] = 0.65
        closes[12] = 0.70
        pts = self._pts(closes)
        trades = sl.run_backtest(pts, "breakout")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["side"], "yes")
        # shorter record -> no trades
        self.assertEqual(sl.run_backtest(pts[:12], "breakout"), [])

    def test_null_closes_are_ignored(self):
        pts = self._pts([0.50, 0.62, 0.70])
        pts[1]["close"] = None
        self.assertEqual(sl.run_backtest(pts, "momentum"), [])


class TestAggregate(unittest.TestCase):
    def test_win_rate_and_net(self):
        rts = [
            {"status": "closed", "result": "win", "net": 10.0, "gross": 12.0,
             "entry_fee": 1.0, "exit_fee": 1.0, "entry_px": 0.5, "contracts": 100,
             "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/markets/X",
             "strategy": "a", "trade_type": "a|s|yes", "topic": "crypto"},
            {"status": "closed", "result": "loss", "net": -5.0, "gross": -4.0,
             "entry_fee": 0.5, "exit_fee": 0.5, "entry_px": 0.5, "contracts": 100,
             "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/markets/X",
             "strategy": "a", "trade_type": "a|s|yes", "topic": "crypto"},
            {"status": "open", "result": "open", "net": None, "gross": None,
             "entry_fee": 1.0, "exit_fee": None, "entry_px": 0.5, "contracts": 100,
             "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/markets/X",
             "strategy": "a", "trade_type": "a|s|yes", "topic": "crypto"},
        ]
        g = sl.aggregate(rts, lambda rt: rt["strategy"])[0]
        self.assertEqual(g["trades"], 3)
        self.assertEqual(g["closed"], 2)
        self.assertEqual(g["open"], 1)
        self.assertAlmostEqual(g["win_rate"], 0.5)
        self.assertAlmostEqual(g["net"], 5.0)
        self.assertAlmostEqual(g["fees"], 3.0)
        self.assertAlmostEqual(g["roi_on_cost"], 5.0 / 100.0)

    def test_blank_key_labelled(self):
        g = sl.aggregate([{"status": "closed", "result": "flat", "net": 0.0,
                           "entry_fee": 0, "exit_fee": 0, "entry_px": 0.5,
                           "contracts": 10, "source_url": ""}],
                         lambda rt: rt.get("missing"))
        self.assertEqual(g[0]["key"], "(blank)")
        self.assertEqual(g[0]["sources"], [])


class TestCrosscheck(unittest.TestCase):
    def _book(self, published):
        return {
            "name": "t", "published_stats": published,
            "round_trips": [
                {"status": "closed", "net": 548.48, "entry_fee": 13.72,
                 "exit_fee": 51.52, "result": "win"},
            ],
        }

    def test_mismatch_flagged(self):
        issues = sl.crosscheck_docs_book(self._book({"all": {
            "trades": 1, "net_pnl": 548.48, "fees": 51.52, "wins": 1}}))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["metric"], "fees (entry+exit)")

    def test_consistent_no_issues(self):
        issues = sl.crosscheck_docs_book(self._book({"all": {
            "trades": 1, "net_pnl": 548.48, "fees": 65.24, "wins": 1}}))
        self.assertEqual(issues, [])

    def test_root_overall_shape(self):
        issues = sl.crosscheck_docs_book(self._book({"overall": {
            "trades": 1, "realized": 548.48, "fees": 65.24, "wins": 1}}))
        self.assertEqual(issues, [])


class TestRealData(unittest.TestCase):
    """Run the lab on the repo's real published data and check the
    verification invariants on its outputs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        for sub in ("docs/data", "data", "kalshi-dashboard/data"):
            (out / sub).mkdir(parents=True, exist_ok=True)
        for f in ("docs/data/portfolio.json", "docs/data/candles.json",
                  "data/live.json", "data/portfolio_state.json",
                  "kalshi-dashboard/data/trades.json"):
            src = ROOT / f
            if src.exists():
                (out / f).write_text(src.read_text())
        # redirect outputs into the temp dir
        cls.md = sl.build_report(out)
        (out / "STRATEGY_ANALYSIS.md").write_text(sl.render_markdown(cls.md))
        (out / "docs/strategies.html").write_text(sl.render_html(cls.md))
        cls.out = out

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_round_trips_found(self):
        self.assertGreaterEqual(len(self.md["round_trips"]), 1)

    def test_every_markdown_row_has_source_or_unverified(self):
        md = (self.out / "STRATEGY_ANALYSIS.md").read_text()
        for line in md.splitlines():
            if line.startswith("|") and "---" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                # header rows carry column names, not values
                if cells and cells[0] in ("Book", "Strategy", "Trade type", "Topic",
                                          "Rule", "Entry ts (UTC)", "Trade type observed",
                                          "Metric"):
                    continue
                joined = " ".join(cells)
                self.assertTrue(
                    "source](" in joined or sl.UNVERIFIED in joined
                    or joined.startswith("#") or "`" in joined,
                    f"row without source link or unverified marker: {line[:120]}")

    def test_every_html_ledger_row_has_source_or_unverified(self):
        html = (self.out / "docs/strategies.html").read_text()
        rows = html.split("<tr>")[1:]
        checked = 0
        for r in rows:
            if "<th>" in r.split("</tr>")[0]:
                continue  # header row
            body = r.split("</tr>")[0]
            self.assertTrue(
                'href="https://external-api.demo.kalshi.co/' in body
                or 'href="https://kalshi.com/docs/' in body
                or 'href="https://docs.kalshi.com/' in body
                or sl.UNVERIFIED in body
                or "<code>" in body,
                f"html row without official source link or unverified marker: {body[:120]}")
            checked += 1
        self.assertGreater(checked, 0)

    def test_json_round_trips_have_source_or_blank(self):
        for rt in self.md["round_trips"]:
            self.assertIsInstance(rt.get("source_url"), str)

    def test_links_are_official_hosts_only(self):
        html = (self.out / "docs/strategies.html").read_text()
        import re
        for href in re.findall(r'href="(https?://[^"]+)"', html):
            self.assertTrue(href.startswith(sl.OFFICIAL_HOSTS) or href.startswith("../"),
                            f"non-official href: {href}")


if __name__ == "__main__":
    unittest.main()
