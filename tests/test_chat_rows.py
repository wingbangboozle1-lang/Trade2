"""The two scrolling chats on the generated landing page.

Regression coverage for the defect found on main @ 58be24d and fixed jointly
by session arena-79cc0bd5 (server-side grouping + signal rows in
``build_overview``) and this session (the live desk's ``signalRow`` in
``assets/desk.js``):

1. byte-identical re-fired swing rows used to render three times on the
   landing page while the live desk grouped them — both must group now;
2. the model shortlist was populated by intersecting swing alerts with
   high-ROI signals, a set that is near-always empty by construction, so the
   brief's second scrolling chat never showed anything — a healthy signal
   with no matching swing must still reach the chat.

These tests go through the public generator API (``build_overview``), so they
keep holding if the row builders are reorganised internally.

Run: python3 -m unittest tests.test_chat_rows -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_build.build import build_overview


def alert(ticker="KXPRESNOMD-28-AKLO", previous=0.803, current=0.0025,
          direction="down", iso="2026-11-20T18:41:08Z", ts=1795200068.0,
          title="Amy Klobuchar"):
    delta = round(current - previous, 4)
    return {
        "id": f"{ticker}:{int(ts)}", "ts": ts, "iso": iso, "ticker": ticker,
        "event_ticker": ticker, "series_ticker": "KXPRESNOMD",
        "topic": "elections", "title": title,
        "previous": previous, "current": current, "delta": delta,
        "abs_delta": abs(delta), "direction": direction,
        "yes_bid": 0.002, "yes_ask": 0.003,
        "market_url": f"https://kalshi.com/markets/KXPRESNOMD/{ticker}",
    }


def signal(ticker="KXBTC15M-26NOV201345-45", net_roi=0.4871, score=0.4871,
           side="yes", price=0.07, edge=0.0441, topic="crypto",
           title="Bitcoin up or down"):
    return {
        "ticker": ticker, "event_ticker": ticker, "topic": topic,
        "title": title, "side": side,
        "executable_price": price, "model_fair": round(price + edge, 4),
        "edge": edge, "gross_roi": 0.63, "fee": 0.01, "net_roi": net_roi,
        "spread": 0.01, "liquidity": 500.0, "score": score,
        "reason": "test", "ts": 1795200000.0,
        "market_url": f"https://kalshi.com/markets/KX/{ticker}",
    }


def page(alerts=(), signals=()):
    return build_overview({
        "generated_at": "2026-11-20T19:09:37Z",
        "generated_at_ts": 1795200997,
        "observation_count": 750,
        "resolutions_count": 339,
        "alerts": list(alerts),
        "signals": list(signals),
        "events": [],
        "topics": {},
        "portfolio": {"open_positions": 1, "equity": 9861.56,
                      "starting_bankroll": 10000.0},
        "exchange": {"trading_active": True},
    })


class TestTwoChats(unittest.TestCase):
    def test_landing_ships_both_required_chats(self):
        html = page()
        self.assertIn("Swing chat — all events", html)
        self.assertIn("Model shortlist", html)
        self.assertIn('class="desk-grid two-chats"', html)


class TestSwingChatGrouping(unittest.TestCase):
    def test_identical_re_fires_render_once_with_a_repeat_marker(self):
        html = page(alerts=[alert(ts=1), alert(ts=2), alert(ts=3)])
        self.assertEqual(html.count("Amy Klobuchar"), 1)
        self.assertIn("3", html)          # the ×N marker
        self.assertNotIn("16:51:26", html)  # collapsed rows are not rendered

    def test_distinct_price_steps_stay_separate_rows(self):
        html = page(alerts=[
            alert(ticker="A", title="A", previous=0.803, current=0.0025),
            alert(ticker="B", title="B", previous=0.943, current=0.4765),
        ])
        self.assertIn(">A<", html)
        self.assertIn(">B<", html)

    def test_empty_feed_renders_honest_empty_state(self):
        html = page(alerts=[])
        self.assertIn("No ≥ $0.10 swing observed", html)


class TestModelShortlist(unittest.TestCase):
    def test_signal_without_a_matching_swing_reaches_the_chat(self):
        # The structural-emptyness regression: signals and swings are almost
        # never present on the same market, so the shortlist must also show
        # the model's current picks on their own, each labelled with its
        # actual net ROI (design shared by build_overview and desk.js).
        html = page(alerts=[], signals=[signal()])
        block = html.split("Model shortlist", 1)[1].split("</article>", 1)[0]
        self.assertIn("★ 48.7%", block)
        self.assertIn("YES at $0.0700", block)
        self.assertNotIn("honest answer", block)

    def test_gated_swing_is_annotated_with_net_roi(self):
        html = page(alerts=[alert(ticker="SIG-TICK", title="Sig Market")],
                    signals=[signal(ticker="SIG-TICK")])
        block = html.split("Model shortlist", 1)[1].split("</article>", 1)[0]
        self.assertIn("Sig Market", block)
        self.assertIn("48.7%", block)

    def test_signal_picks_are_shown_with_their_honest_roi(self):
        # Picks are the model's current best signals (score-sorted); the
        # row prints the real net ROI rather than claiming a threshold.
        html = page(alerts=[], signals=[signal(net_roi=0.049, score=0.049)])
        block = html.split("Model shortlist", 1)[1].split("</article>", 1)[0]
        self.assertIn("★ 4.9%", block)
        self.assertNotIn("honest answer", block)

    def test_gated_swing_rows_suppress_the_signal_fallback(self):
        # Parity with desk.js: when a gated swing row exists it is the
        # shortlist; signal-only picks appear only when it does not.
        html = page(alerts=[alert(ticker="SIG-TICK", title="Sig Market")],
                    signals=[signal(ticker="SIG-TICK"),
                             signal(ticker="OTHER", title="Other Pick")])
        block = html.split("Model shortlist", 1)[1].split("</article>", 1)[0]
        self.assertIn("Sig Market", block)
        self.assertNotIn("Other Pick", block)

    def test_nothing_at_all_renders_the_empty_state(self):
        html = page(alerts=[], signals=[])
        block = html.split("Model shortlist", 1)[1].split("</article>", 1)[0]
        self.assertIn("honest answer", block)


if __name__ == "__main__":
    unittest.main()
