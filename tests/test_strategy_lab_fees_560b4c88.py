"""Strategy-lab fixes — session `arena-560b4c88` (Board `arena-560b4c88`, M2/M3).

Covers two things this session changed in `tools/strategy_lab.py`:

1. **R-79CC-5, open on the coordination board since 2026-11-20**: the lab's local
   `money()` printed a loss as `$-155.00`. `site_build/format.money()` was fixed the
   same day (sign outside the currency symbol) but the lab kept its own copy, so
   `docs/strategies.html` and `STRATEGY_ANALYSIS.md` were the only pages on the site
   rendering negative amounts that way.
2. **The unresolved `crosscheck_issues` row.** `docs/data/strategy_lab.json` reported
   `{"metric": "fees (entry+exit)", "published": 51.52, "recomputed": 65.24}` forever,
   because the lab compared its own entry+exit total with a book that publishes the
   exit leg only. The engine side is fixed in `trading/engine.py` (see
   `tests/test_trading_fee_attribution_560b4c88.py`); here the lab learns to say
   *which* of the two it is looking at, so a definitional gap is never printed as an
   arithmetic error and a real arithmetic error is never smoothed into "a different
   definition".

Also pinned: the freshness of the analysis relative to the book it reads (a
pre-rendered page that does not say how old its source is, is a page that lies).

Run: python3 -m unittest tests.test_strategy_lab_fees_560b4c88 -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import strategy_lab as sl  # noqa: E402


def _book(published_fees, published_net=None, exit_only=51.52, both=65.24):
    """A book whose single closed round trip costs 13.72 in and 51.52 out."""
    return {
        "name": "t", "engine": "t/engine.json",
        "published_stats": {"all": {"trades": 1, "net_pnl": 548.48 if published_net is None
                                    else published_net,
                                    "fees": published_fees, "wins": 1}},
        "round_trips": [{"status": "closed", "net": 548.48, "entry_fee": both - exit_only,
                         "exit_fee": exit_only, "result": "win"}],
    }


class TestMoneySign(unittest.TestCase):
    def test_loss_is_signed_outside_the_symbol(self):
        self.assertEqual(sl.money(-155.0), "-$155.00")
        self.assertEqual(sl.money(155.0), "$155.00")
        self.assertEqual(sl.money(-0.001), "-$0.00")
        self.assertEqual(sl.money(None), "—")

    def test_matches_the_site_formatter(self):
        """Two formatters on one site must not print the same amount two ways."""
        sys.path.insert(0, str(ROOT))
        from site_build.format import money as site_money
        for v in (-155.0, -0.01, 0.0, 12.5, 1234.567):
            self.assertEqual(site_money(v), sl.money(v), f"diverged at {v}")

    def test_rendered_outputs_never_contain_dollar_minus(self):
        md = sl.render_markdown(self._report())
        html = sl.render_html(self._report())
        for name, text in (("markdown", md), ("html", html)):
            self.assertNotIn("$-", text, f"{name} still prints a sign inside the symbol")

    def _report(self):
        return {
            "generated_at": "2026-11-21T08:00:00Z",
            "books": [{"name": "t", "engine": "t.json", "round_trips": [
                {"status": "closed", "result": "loss", "net": -155.0, "entry_fee": 13.72,
                 "exit_fee": 51.52, "entry_px": 0.4, "exit_px": 0.2, "contracts": 500,
                 "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/markets/T"}]},
            ],
            "round_trips": [],
            "by_strategy": sl.aggregate([], lambda rt: "x"),
            "by_trade_type": sl.aggregate([], lambda rt: "x"),
            "by_topic": sl.aggregate([], lambda rt: "x"),
            "by_book": sl.aggregate([], lambda rt: "x"),
            "crosscheck_issues": [],
            "candle_series": [],
            "backtest": {},
            "parameters": {},
            "book_freshness": [{"book": "t", "book_generated_at": "2026-11-21T07:00:00Z",
                                "hours_before_this_analysis": 1.0}],
            "max_book_age_hours": 1.0,
        }


class TestCrosscheckNaming(unittest.TestCase):
    def test_exit_only_published_fee_is_a_definition_gap_not_an_error(self):
        book = _book(51.52)
        issues = sl.crosscheck_docs_book(book)
        self.assertEqual(len(issues), 1, issues)
        row = issues[0]
        self.assertEqual(row["metric"], "fees (entry+exit)")
        self.assertEqual(row["kind"], "definition")
        self.assertEqual(row["published"], 51.52)
        self.assertEqual(row["recomputed"], 65.24)
        self.assertEqual(row["also_matches"], 51.52)
        self.assertIn("exit leg only", book["fee_basis"])
        self.assertEqual(book["fee_understated_by"], 13.72)

    def test_both_legs_published_fee_is_clean(self):
        self.assertEqual(sl.crosscheck_docs_book(_book(65.24)), [])

    def test_a_fee_that_matches_neither_definition_is_an_arithmetic_issue(self):
        issues = sl.crosscheck_docs_book(_book(99.99))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["kind"], "arithmetic")
        self.assertIn("neither entry+exit", issues[0]["definition"])

    def test_net_pnl_mismatch_is_arithmetic(self):
        issues = sl.crosscheck_docs_book(_book(65.24, published_net=1.0))
        self.assertEqual([i["metric"] for i in issues], ["net_pnl/realized"])
        self.assertEqual(issues[0]["kind"], "arithmetic")

    def test_missing_published_metric_is_skipped_not_zeroed(self):
        book = _book(None)
        book["published_stats"] = {"all": {"trades": 1, "wins": 1}}
        self.assertEqual(sl.crosscheck_docs_book(book), [],
                         "an absent published figure is left absent, never compared to 0")


class TestFreshness(unittest.TestCase):
    def test_hours_between(self):
        self.assertEqual(sl._hours_between("2026-11-21T07:00:00Z", "2026-11-21T08:00:00Z"), 1.0)
        self.assertEqual(sl._hours_between("2026-11-21T08:00:00Z", "2026-11-21T07:00:00Z"), -1.0)
        self.assertIsNone(sl._hours_between(None, "2026-11-21T08:00:00Z"))
        self.assertIsNone(sl._hours_between("not a date", "2026-11-21T08:00:00Z"))

    def test_age_cell_never_invents_a_time(self):
        self.assertIn(sl.UNVERIFIED, sl._age_cell(None))
        self.assertIn(sl.UNVERIFIED, sl._age_cell({"book_generated_at": None}))
        cell = sl._age_cell({"book_generated_at": "2026-11-21T07:00:00Z",
                             "hours_before_this_analysis": 0.5})
        self.assertIn("2026-11-21T07:00:00Z", cell)
        self.assertIn("0.5 h before this analysis", cell)

    def test_loaders_read_the_books_own_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "docs" / "data").mkdir(parents=True)
            (out / "docs" / "data" / "portfolio.json").write_text(json.dumps(
                {"generated_at": "2026-11-21T07:15:00Z", "trades": [], "stats": {}}))
            book = sl.load_docs_book(out)
            self.assertEqual(book["source_generated_at"], "2026-11-21T07:15:00Z")
            missing = sl.load_docs_book(Path(tmp) / "nothing")
            self.assertIsNone(missing["source_generated_at"],
                              "no file must not become a timestamp")

    def test_real_repo_report_reports_its_books_age(self):
        rep = sl.build_report(ROOT)
        self.assertEqual(len(rep["book_freshness"]), 3)
        ages = [f["hours_before_this_analysis"] for f in rep["book_freshness"]]
        self.assertTrue(any(a is not None for a in ages), ages)
        self.assertIsNotNone(rep["max_book_age_hours"])
        md = sl.render_markdown(rep)
        self.assertIn("When that book was written", md)
        self.assertIn("only as", md.replace("\n", " "))


class TestOfficialHostsOnly(unittest.TestCase):
    def test_the_lab_quotes_the_fee_schedule_it_cites(self):
        self.assertEqual(sl.FEE_SCHEDULE_URL, "https://kalshi.com/docs/kalshi-fee-schedule.pdf")
        self.assertIn("kalshi-fee-schedule.pdf", sl.FEE_FORMULA_DOC)


if __name__ == "__main__":
    unittest.main()
