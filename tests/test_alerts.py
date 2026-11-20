"""R-D-01 symptom regressions — the published swing chat must not accumulate
duplicate rows.

Background (COORDINATION.md board A/E, AUDIT_ADDENDUM.md): the 2026-11-20
snapshot carried 29 alert rows over only 3 tickers, the same sustained move
re-appearing on every collector run, some of them midpoint phantoms on wide
books. The merged fix has three layers:

1. quote-mid rule + ``alert_record_valid`` purge — ``tests/test_alerts_basis.py``;
2. view-layer fold — ``test/alerts-view.test.mjs``;
3. store-layer fold — ``collector.alerts.fold_alerts`` (rule tests in
   ``tests/test_alert_quality_dc732aa6.py``).

This module is the end-to-end symptom check across layers 1+3: feed several
runs of the *observed* pattern through purge+fold and assert the published
buffer contains distinct moves only. Offline: rows are constructed directly.
"""

from __future__ import annotations

import unittest

from collector.alerts import (ESCALATION_STEP, alert_record_valid, fold_alerts)


def row(**kw) -> dict:
    """A stored alert row shaped like collector output (all required fields)."""
    base = {
        "id": "T-1:1000", "key": "T-1:down:900",
        "ts": 1000.0, "iso": "2026-11-20T19:00:00Z",
        "first_seen_ts": 1000.0, "last_seen_ts": 1000.0,
        "ticker": "T-1", "direction": "down", "previous": 0.80,
        "current": 0.40, "abs_delta": 0.40, "delta": -0.40,
        "previous_ts": 900.0, "reference_basis": "candle_quote_mid",
        "spread": 0.02, "yes_bid": 0.39, "yes_ask": 0.41,
    }
    base.update(kw)
    return base


class TestRepeatSymptom(unittest.TestCase):
    def test_same_move_reobserved_each_run_stays_one_row(self):
        # The exact audit pattern: identical rows arriving with fresh run ids.
        store: list = []
        for i, ts in enumerate([1000.0, 1300.0, 1600.0, 1900.0]):
            out = fold_alerts([row(ts=ts, id=f"T-1:{int(ts)}",
                                   first_seen_ts=ts, last_seen_ts=ts)],
                              store)
            store = out["alerts"]
        self.assertEqual(len(store), 1)
        self.assertEqual(store[0]["abs_delta"], 0.40)
        self.assertGreaterEqual(store[0].get("repeat_count"), 3)

    def test_largest_move_wins_inside_one_reference_window(self):
        bigger = row(ts=1300.0, current=0.35, abs_delta=0.45, delta=-0.45)
        out = fold_alerts([bigger], [row()])
        self.assertEqual(len(out["alerts"]), 1)
        self.assertEqual(out["alerts"][0]["abs_delta"], 0.45)
        # The first-seen time is preserved when the row is updated.
        self.assertEqual(out["alerts"][0]["first_seen_ts"], 1000.0)

    def test_small_growth_on_a_later_bar_folds_into_the_row(self):
        later_bar = row(key="T-1:down:1200", ts=1300.0,
                        previous_ts=1200.0, current=0.42, abs_delta=0.38,
                        delta=-0.38)
        out = fold_alerts([later_bar], [row()])
        self.assertEqual(len(out["alerts"]), 1)

    def test_grown_move_opens_an_escalation_row(self):
        grown = row(key="T-1:down:1200", ts=1300.0, previous_ts=1200.0,
                    current=0.30, abs_delta=round(0.40 + ESCALATION_STEP, 4),
                    delta=-0.50)
        out = fold_alerts([grown], [row()])
        self.assertEqual(len(out["alerts"]), 2)
        escalated = [a for a in out["alerts"] if a.get("escalated_from")]
        self.assertEqual(len(escalated), 1)

    def test_opposite_directions_are_distinct_moves(self):
        up = row(key="T-1:up:900", direction="up", previous=0.40,
                 current=0.55, abs_delta=0.15, delta=0.15)
        out = fold_alerts([up], [row()])
        self.assertEqual(len(out["alerts"]), 2)


class TestPhantomPurgeSymptom(unittest.TestCase):
    def test_legacy_midpoint_phantom_is_purged_before_the_fold(self):
        # The audit's Hunter Biden row: 0.811 -> 0.4065 measured on a
        # $0.002/$0.811 book, with no reference_basis (legacy rule set).
        phantom = row(key="P-1:down:900", ticker="P-1", id="P-1:2000",
                      previous=0.811, current=0.4065, abs_delta=0.4045,
                      delta=-0.4045, previous_ts=None, reference_basis=None,
                      spread=0.809, yes_bid=0.002, yes_ask=0.811, ts=2000.0)
        merged = [phantom, row()]
        kept = [a for a in merged if alert_record_valid(a)]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["ticker"], "T-1")

    def test_wide_spread_record_fails_the_quote_rule(self):
        wide = row(spread=0.809, yes_bid=0.002, yes_ask=0.811)
        self.assertFalse(alert_record_valid(wide))

    def test_tight_record_passes(self):
        self.assertTrue(alert_record_valid(row()))


if __name__ == "__main__":
    unittest.main()
