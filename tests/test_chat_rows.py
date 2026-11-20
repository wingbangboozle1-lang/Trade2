"""Static chat-row builders for the two scrolling chats.

Regression for two defects found on main @ 58be24d:

1. the landing page pre-rendered every re-fired swing row byte-identically
   (three copies of one AKLO move), while the live desk grouped them — the
   static builder must group them the same way (coordination R-D-01);
2. the model shortlist chat was populated by intersecting swing alerts with
   high-ROI signals, a set that is near-always empty by construction, so the
   brief's second scrolling chat never showed anything.

Run: python3 -m unittest tests.test_chat_rows -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_build.build import (MODEL_NET_ROI_GATE, build_alert_rows,
                              build_model_rows, dedupe_alerts)


def alert(ticker="KXPRESNOMD-28-AKLO", previous=0.803, current=0.0025,
          direction="down", iso="2026-11-20T18:41:08Z", ts=1795200068.0):
    delta = round(current - previous, 4)
    return {
        "id": f"{ticker}:{int(ts)}", "ts": ts, "iso": iso, "ticker": ticker,
        "event_ticker": ticker, "series_ticker": "KXPRESNOMD",
        "topic": "elections", "title": "Amy Klobuchar",
        "previous": previous, "current": current, "delta": delta,
        "abs_delta": abs(delta), "direction": direction,
        "yes_bid": 0.002, "yes_ask": 0.003,
        "market_url": f"https://kalshi.com/markets/KXPRESNOMD/{ticker}",
    }


def signal(ticker="KXBTC15M-26NOV201345-45", net_roi=0.4871, score=0.4871,
           side="yes", price=0.07, edge=0.0441, topic="crypto"):
    return {
        "ticker": ticker, "event_ticker": ticker, "topic": topic,
        "title": "Bitcoin up or down", "side": side,
        "executable_price": price, "model_fair": round(price + edge, 4),
        "edge": edge, "gross_roi": 0.63, "fee": 0.01, "net_roi": net_roi,
        "spread": 0.01, "liquidity": 500.0, "score": score,
        "reason": "test", "ts": 1795200000.0,
        "market_url": f"https://kalshi.com/markets/KX/{ticker}",
    }


class TestDedupeAlerts(unittest.TestCase):
    def test_identical_re_fires_collapse_to_one_row(self):
        rows = dedupe_alerts([alert(ts=1), alert(ts=2), alert(ts=3)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["repeat_count"], 3)

    def test_first_appearance_order_is_kept(self):
        rows = dedupe_alerts([
            alert(ticker="A", ts=1), alert(ticker="B", ts=2),
            alert(ticker="A", ts=3),
        ])
        self.assertEqual([r["ticker"] for r in rows], ["A", "B"])
        self.assertEqual(rows[0]["repeat_count"], 2)

    def test_newest_iso_wins_for_the_group(self):
        rows = dedupe_alerts([
            alert(iso="2026-11-20T16:51:26Z", ts=1),
            alert(iso="2026-11-20T18:41:08Z", ts=3),
        ])
        self.assertEqual(rows[0]["iso"], "2026-11-20T18:41:08Z")

    def test_different_price_steps_stay_separate(self):
        rows = dedupe_alerts([alert(previous=0.803, current=0.0025),
                              alert(previous=0.943, current=0.4765)])
        self.assertEqual(len(rows), 2)

    def test_empty_and_garbage_input(self):
        self.assertEqual(dedupe_alerts([]), [])
        self.assertEqual(dedupe_alerts(None), [])
        self.assertEqual(dedupe_alerts(["not-a-dict"]), [])


class TestAlertRows(unittest.TestCase):
    def test_static_rows_are_grouped(self):
        rows = build_alert_rows([alert(ts=1), alert(ts=2), alert(ts=3)])
        self.assertEqual(len(rows), 1)
        self.assertIn("repeated ×3", rows[0])

    def test_empty_feed_renders_honest_empty_state(self):
        rows = build_alert_rows([])
        self.assertEqual(len(rows), 1)
        self.assertIn("empty-state", rows[0])

    def test_limit_applies_after_grouping(self):
        raw = [alert(ticker=f"T{i}", ts=i) for i in range(5)]
        raw += [alert(ticker="T0", ts=99)]      # one duplicate of T0
        rows = build_alert_rows(raw, limit=3)
        self.assertEqual(len(rows), 3)


class TestModelRows(unittest.TestCase):
    def test_gate_constant_matches_desk_js(self):
        # assets/desk.js filters on net_roi >= 0.05 — keep them in step.
        self.assertEqual(MODEL_NET_ROI_GATE, 0.05)

    def test_signal_without_matching_alert_still_reaches_the_chat(self):
        # The structural-emptyness regression: a healthy signal on a market
        # with no swing must still appear in the shortlist.
        rows = build_model_rows({"alerts": [], "signals": [signal()]})
        self.assertEqual(len(rows), 1)
        self.assertIn("★ 48.7%", rows[0])
        self.assertIn("buy YES @ $0.0700", rows[0])
        self.assertIn("edge $0.0441", rows[0])

    def test_matching_alert_is_annotated_with_net_roi(self):
        live = {"alerts": [alert(ticker="SIG-TICK")],
                "signals": [signal(ticker="SIG-TICK")]}
        rows = build_model_rows(live)
        self.assertEqual(len(rows), 1)          # one row, not two
        self.assertIn("net ROI 48.7%", rows[0])

    def test_signals_below_the_gate_are_excluded(self):
        live = {"alerts": [], "signals": [signal(net_roi=0.049, score=0.049)]}
        rows = build_model_rows(live)
        self.assertEqual(len(rows), 1)          # only the empty-state row
        self.assertIn("empty-state", rows[0])

    def test_signals_are_ordered_by_score(self):
        live = {"alerts": [], "signals": [
            signal(ticker="LOW", net_roi=0.10, score=0.10),
            signal(ticker="HIGH", net_roi=0.90, score=0.90),
        ]}
        rows = build_model_rows(live)
        self.assertEqual(len(rows), 2)
        self.assertIn("HIGH", rows[0])

    def test_gated_alert_rows_come_before_signal_only_rows(self):
        live = {"alerts": [alert(ticker="SWINGY")],
                "signals": [signal(ticker="SWINGY"),
                            signal(ticker="QUIET", score=0.2)]}
        rows = build_model_rows(live)
        self.assertEqual(len(rows), 2)
        self.assertIn("SWINGY", rows[0])
        self.assertIn("QUIET", rows[1])

    def test_no_signals_renders_empty_state_not_an_error(self):
        rows = build_model_rows({"alerts": [], "signals": []})
        self.assertEqual(len(rows), 1)
        self.assertIn("empty-state", rows[0])

    def test_limit_caps_the_combined_feed(self):
        live = {"alerts": [alert(ticker=f"T{i}", ts=i) for i in range(10)],
                "signals": [signal(ticker=f"T{i}") for i in range(10)]}
        rows = build_model_rows(live, limit=4)
        self.assertEqual(len(rows), 4)


if __name__ == "__main__":
    unittest.main()
