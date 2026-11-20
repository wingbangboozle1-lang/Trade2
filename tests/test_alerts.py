"""Regression tests for store-level alert dedupe (COORDINATION.md R-D-01).

The quote-mid swing rule is covered by ``tests/test_alerts_basis.py`` and the
view-layer fold by ``test/alerts-view.test.mjs``. This module pins the third
layer: the *store* fold in ``collector.alerts.dedupe_alerts`` — the collector
re-observes the same sustained swing every run, and the published buffer must
not accumulate one row per run (the observed symptom was 29 rows over 3
tickers). Offline: rows are constructed directly.
"""

from __future__ import annotations

import unittest

from collector import alerts


def row(**kw) -> dict:
    base = {"id": "T-1:1000", "ts": 1000.0, "iso": "2026-11-20T19:00:00Z",
            "ticker": "T-1", "direction": "down", "previous": 0.80,
            "current": 0.40, "abs_delta": 0.40, "delta": -0.40,
            "previous_ts": 900.0, "reference_basis": "candle_quote_mid",
            "spread": 0.02, "yes_bid": 0.39, "yes_ask": 0.41}
    base.update(kw)
    return base


class TestWindowKey(unittest.TestCase):
    def test_key_is_market_window_direction_not_run_timestamp(self):
        a = row(id="T-1:1000")   # legacy per-run id
        b = row(id="T-1:1300")   # same move, later run
        self.assertEqual(alerts.alert_window_key(a), alerts.alert_window_key(b))
        self.assertEqual(alerts.alert_window_key(a), "T-1:900:down")

    def test_different_directions_are_distinct(self):
        self.assertNotEqual(alerts.alert_window_key(row(direction="up")),
                            alerts.alert_window_key(row(direction="down")))


class TestDedupeAlerts(unittest.TestCase):
    def test_repeated_rows_fold_to_one_keeping_largest_move(self):
        bigger = row(ts=1300.0, abs_delta=0.45, current=0.35, delta=-0.45,
                     id="T-1:1300")
        other = row(ticker="T-2", id="T-2:1000", ts=1100.0, abs_delta=0.20,
                    direction="up", previous=0.30, current=0.50, delta=0.20)
        out = alerts.dedupe_alerts([row(), other, row(ts=1100.0), bigger])
        self.assertEqual(len(out), 2)
        by_key = {alerts.alert_window_key(r): r for r in out}
        kept = by_key["T-1:900:down"]
        self.assertEqual(kept["abs_delta"], 0.45)
        self.assertEqual(kept["ts"], 1300.0)

    def test_same_move_across_windows_folds_to_newest(self):
        later = row(id="T-1:1300", ts=1300.0, previous_ts=1200.0)
        out = alerts.dedupe_alerts([row(), later])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ts"], 1300.0)

    def test_same_move_outside_a_day_keeps_both(self):
        old = row(ts=1000.0)
        much_later = row(ts=100000.0, previous_ts=99000.0, id="T-1:99100")
        out = alerts.dedupe_alerts([old, much_later])
        self.assertEqual(len(out), 2)

    def test_tie_keeps_newest(self):
        out = alerts.dedupe_alerts([row(ts=1000.0), row(ts=1200.0, id="T-1:1200")])
        self.assertEqual(out[0]["ts"], 1200.0)

    def test_rows_without_identity_are_dropped(self):
        out = alerts.dedupe_alerts([{"ts": 1.0}, {"id": "", "ts": 2.0}])
        self.assertEqual(out, [])

    def test_output_is_newest_first(self):
        rows = [row(ts=1000.0), row(ticker="T-2", ts=2000.0, id="T-2:1"),
                row(ticker="T-3", ts=1500.0, id="T-3:1")]
        out = alerts.dedupe_alerts(rows)
        self.assertEqual([r["ts"] for r in out], [2000.0, 1500.0, 1000.0])

    def test_stored_fold_composes_with_quote_rule_purge(self):
        # A phantom legacy row (no reference_basis) is purged by
        # alert_record_valid; the fold then collapses the valid repeats.
        phantom = row(reference_basis=None, id="T-9:1", ticker="T-9",
                      previous_ts=900.0)
        good_a = row()
        good_b = row(ts=1100.0)
        merged = [good_a, good_b, phantom]
        kept = alerts.dedupe_alerts(
            [a for a in merged if alerts.alert_record_valid(a)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(alerts.alert_window_key(kept[0]), "T-1:900:down")


if __name__ == "__main__":
    unittest.main()
