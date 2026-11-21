"""Tests for the shared chat-row renderer and the Flagged page.

These cover the parts of the ≥ $0.10 alert display that a reader can be misled
by: a row must say what two numbers were subtracted, whether the price could
actually be traded, and what the candidate catalyst links are *not* claiming.
They also pin the two rules that keep the site honest — a blank plus a reason
instead of an invented value, and no untrusted scheme reaching an ``href``.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_build.build import alert_chat_row, model_shortlist  # noqa: E402
from site_build.format import safe_url  # noqa: E402

EXECUTABLE = {
    "ticker": "KXBTC-26NOV20-65000", "event_ticker": "KXBTC-26NOV20",
    "series_ticker": "KXBTC", "topic": "crypto", "title": "Bitcoin above $65k",
    "direction": "up", "abs_delta": 0.124, "previous": 0.44, "current": 0.564,
    "iso": "2026-11-20T19:02:11Z", "yes_bid": 0.44, "yes_ask": 0.45,
    "market_url": "https://demo.kalshi.co/events/KXBTC-26NOV20",
    "reference_basis": "quote mid vs quote mid",
    "quality": "executable", "quality_reason": "",
    "spread": 0.01, "size_at_top": 2400.0, "repeat_count": 3,
    "news": [{"title": "Exchange reports outage", "url": "https://example.com/a"}],
    "news_status": "",
}


class TestAlertChatRow(unittest.TestCase):
    def test_row_states_basis_depth_and_repeat_count(self):
        html = alert_chat_row(EXECUTABLE)
        self.assertIn("quote mid vs quote mid", html)
        self.assertIn("YES spread", html)
        self.assertIn("2,400 contracts at the level", html)
        self.assertIn("×3 repeats", html)
        self.assertIn(">executable<", html)

    def test_indicative_row_is_labelled_not_hidden(self):
        row = dict(EXECUTABLE, quality="indicative",
                   quality_reason="YES spread 0.8090 is not tighter than the "
                                  "$0.10 alert threshold",
                   size_at_top=None)
        html = alert_chat_row(row)
        self.assertIn("indicative · not executable", html)
        self.assertIn("0.10 alert threshold", html)
        self.assertIn("no resting size at the level", html)
        self.assertNotIn(">executable<", html)

    def test_legacy_row_makes_no_claim(self):
        row = {k: v for k, v in EXECUTABLE.items()
               if k not in ("quality", "reference_basis", "spread", "size_at_top",
                            "news", "repeat_count")}
        html = alert_chat_row(row)
        self.assertIn("pre-rule row", html)
        for claim in ("executable", "contracts at the level"):
            self.assertNotIn(claim, html)

    def test_headline_link_is_a_candidate_never_a_cause(self):
        html = alert_chat_row(EXECUTABLE)
        self.assertIn("candidate headline, not confirmed", html)
        self.assertIn('href="https://example.com/a"', html)
        self.assertIn("Exchange reports outage", html)
        self.assertNotIn("caused", html)

    def test_missing_headline_is_a_reason_not_a_blank(self):
        row = dict(EXECUTABLE, news=[],
                   news_status="lookup disabled: no route to news.google.com")
        html = alert_chat_row(row)
        self.assertIn("no verified news link", html)
        self.assertIn("no route to news.google.com", html)

    def test_api_supplied_text_cannot_escape_the_row(self):
        row = dict(EXECUTABLE, title='"><img src=x onerror=alert(1)>',
                   news=[{"title": "y", "url": "javascript:alert(1)"}])
        html = alert_chat_row(row)
        self.assertNotIn("<img", html)
        self.assertNotIn("javascript:", html)
        self.assertIn("&lt;img", html)


class TestSafeUrl(unittest.TestCase):
    def test_only_http_and_https_survive(self):
        self.assertTrue(safe_url("https://x.test/a").startswith("https://x.test/a"))
        self.assertTrue(safe_url("http://x.test").startswith("http://"))
        for bad in ("javascript:alert(1)", "data:text/html,<b>", "JaVaScRiPt:x",
                    " //x.test", "", None, "mailto:a@b.c"):
            self.assertEqual(safe_url(bad), "", msg=repr(bad))

    def test_quotes_are_escaped(self):
        self.assertNotIn('"', safe_url('https://x.test/?a"><b'))


class TestModelShortlist(unittest.TestCase):
    def test_published_shortlist_is_used_verbatim(self):
        live = {"high_roi_alerts": [{"ticker": "A", "model_net_roi": 0.08}],
                "model_gate": {"min_net_roi": 0.05},
                "alerts": [{"ticker": "A"}, {"ticker": "B"}],
                "signals": [{"ticker": "A", "net_roi": 0.08},
                            {"ticker": "B", "net_roi": 0.40}]}
        out = model_shortlist(live)
        self.assertEqual([a["ticker"] for a in out], ["A"])

    def test_legacy_snapshot_uses_the_published_gate_not_a_second_number(self):
        live = {"alerts": [{"ticker": "A"}, {"ticker": "B"}],
                "signals": [{"ticker": "A", "net_roi": 0.04},
                            {"ticker": "B", "net_roi": 0.06}],
                "model_gate": {"min_net_roi": 0.06}}
        out = model_shortlist(live)
        self.assertEqual([a["ticker"] for a in out], ["B"])
        self.assertEqual(out[0]["model_net_roi"], 0.06)

    def test_no_signals_no_rows(self):
        self.assertEqual(model_shortlist({"alerts": [{"ticker": "A"}]}), [])


class TestFlaggedPage(unittest.TestCase):
    def test_refusals_are_published(self):
        from site_build import flagpage
        live = {"generated_at": "2026-11-20T19:30:00Z",
                "suppressed_alerts": [{"ticker": "KXBT-1", "topic": "crypto",
                                       "title": "Bitcoin", "direction": "down",
                                       "abs_delta": 0.4045, "yes_bid": 0.002,
                                       "yes_ask": 0.003,
                                       "reason": "YES spread 0.8090 is not tighter "
                                                 "than the $0.10 alert threshold",
                                       "iso": "2026-11-20T18:41:58Z"}]}
        html = flagpage.render(live)
        self.assertIn('id="refused"', html)
        self.assertIn("KXBT-1", html)
        self.assertIn("not tighter", html)

    def test_book_record_divergence_table(self):
        from site_build import flagpage
        live = {"generated_at": "2026-11-20T19:30:00Z",
                "book_record_gap_count": 1,
                "book_record_gaps": [{"ticker": "KXPRESNOMD-28-HBID",
                                       "event_ticker": "KXPRESNOMD-28",
                                       "topic": "elections", "title": "Hunter Biden",
                                       "book_mid": 0.4065, "record_mid": 0.0025,
                                       "gap": 0.404, "abs_gap": 0.404,
                                       "book_yes_bid": 0.002, "book_yes_ask": 0.811,
                                       "record_yes_bid": 0.002,
                                       "record_yes_ask": 0.003,
                                       "source_book": "https://x.test/orderbook",
                                       "source_record": "https://x.test/markets"}]}
        html = flagpage.render(live)
        self.assertIn('id="book-vs-record"', html)
        self.assertIn("KXPRESNOMD-28-HBID", html)
        self.assertIn("0.4065", html)
        self.assertIn("1 of the tracked markets show such a gap", html)
        self.assertIn('href="https://x.test/orderbook"', html)

    def test_empty_divergence_says_so(self):
        from site_build import flagpage
        html = flagpage.render({"generated_at": "2026-11-20T19:30:00Z"})
        self.assertIn("No tracked market", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
