"""Regression tests for the swing-alert rules (COORDINATION.md R-D-01).

Three behaviours are pinned here, each of which previously produced bad rows in
the published chat:

1. The same sustained move re-observed on later runs must fold into ONE alert
   (same market + reference window + direction), largest move winning.
2. A wide-spread book must not produce a midpoint "swing": the basis falls back
   to the last traded price, so a $0.002/$0.811 book that "mids" at $0.4065
   cannot alert against a $0.811 reference when nothing traded.
3. A real move on a thin book (last price changes) still alerts, labelled
   ``basis='last_price'`` / ``thin_book=True``.

All tests are offline: Observations are constructed directly.
"""

from __future__ import annotations

import unittest

from collector import alerts


def obs(**kw) -> alerts.Observation:
    base = dict(
        ts=1000.0, ticker="T-1", event_ticker="E-1", topic="test", title="T",
        yes_bid=None, yes_ask=None, mid=None, last_price=None,
        volume=10.0, open_interest=5.0, series_ticker="T",
    )
    base.update(kw)
    return alerts.Observation(**base)


class TestPriceBasis(unittest.TestCase):
    def test_tight_book_uses_mid(self):
        o = obs(yes_bid=0.40, yes_ask=0.42, mid=0.41, spread=0.02)
        self.assertEqual(alerts.price_basis(o), (0.41, "mid"))

    def test_wide_book_falls_back_to_last_price(self):
        o = obs(yes_bid=0.002, yes_ask=0.811, mid=0.4065, spread=0.809,
                last_price=0.811)
        self.assertEqual(alerts.price_basis(o), (0.811, "last_price"))

    def test_no_price_when_wide_and_no_last(self):
        o = obs(yes_bid=0.002, yes_ask=0.811, mid=0.4065, spread=0.809)
        self.assertEqual(alerts.price_basis(o), (None, "none"))


class TestDetectSwing(unittest.TestCase):
    def test_wide_book_mid_move_does_not_alert(self):
        # Reference 0.811 (candle close). The book mids at 0.4065 but nothing
        # traded there; last price is unchanged at 0.811 -> no alert.
        current = obs(yes_bid=0.002, yes_ask=0.811, mid=0.4065, spread=0.809,
                      last_price=0.811)
        self.assertIsNone(alerts.detect_swing(
            None, current, reference=0.811, reference_ts=900.0))

    def test_real_move_on_thin_book_alerts_with_labels(self):
        current = obs(yes_bid=0.002, yes_ask=0.811, mid=0.4065, spread=0.809,
                      last_price=0.40)
        alert = alerts.detect_swing(None, current, reference=0.811,
                                    reference_ts=900.0)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["basis"], "last_price")
        self.assertTrue(alert["thin_book"])
        self.assertAlmostEqual(alert["delta"], -0.411)

    def test_tight_book_mid_move_alerts(self):
        current = obs(yes_bid=0.40, yes_ask=0.42, mid=0.41, spread=0.02)
        alert = alerts.detect_swing(None, current, reference=0.25,
                                    reference_ts=900.0)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["basis"], "mid")
        self.assertFalse(alert["thin_book"])

    def test_small_move_is_silent(self):
        current = obs(yes_bid=0.40, yes_ask=0.42, mid=0.41, spread=0.02)
        self.assertIsNone(alerts.detect_swing(
            None, current, reference=0.35, reference_ts=900.0))

    def test_alert_id_is_stable_across_reruns_of_same_window(self):
        current = obs(ts=1000.0, yes_bid=0.40, yes_ask=0.42, mid=0.41,
                      spread=0.02)
        later = obs(ts=1300.0, yes_bid=0.38, yes_ask=0.40, mid=0.39,
                    spread=0.02)
        a1 = alerts.detect_swing(None, current, reference=0.25,
                                 reference_ts=900.0)
        a2 = alerts.detect_swing(None, later, reference=0.25,
                                 reference_ts=900.0)
        self.assertEqual(a1["id"], a2["id"])  # same window + direction
        self.assertNotIn(":1000", a1["id"])   # no per-run timestamp in the key


class TestDedupeAlerts(unittest.TestCase):
    def test_repeated_rows_fold_to_one_keeping_largest_move(self):
        row = {"id": "T-1:900:down", "ts": 1000.0, "abs_delta": 0.40,
               "direction": "down"}
        bigger = {"id": "T-1:900:down", "ts": 1300.0, "abs_delta": 0.45,
                  "direction": "down"}
        other = {"id": "T-2:900:up", "ts": 1100.0, "abs_delta": 0.20,
                 "direction": "up"}
        out = alerts.dedupe_alerts([row, other, dict(row, ts=1100.0), bigger])
        self.assertEqual(len(out), 2)
        by_id = {r["id"]: r for r in out}
        self.assertEqual(by_id["T-1:900:down"]["abs_delta"], 0.45)
        self.assertEqual(by_id["T-1:900:down"]["ts"], 1300.0)

    def test_tie_keeps_newest(self):
        a = {"id": "T-1:900:up", "ts": 1000.0, "abs_delta": 0.30}
        b = {"id": "T-1:900:up", "ts": 1200.0, "abs_delta": 0.30}
        out = alerts.dedupe_alerts([a, b])
        self.assertEqual(out[0]["ts"], 1200.0)

    def test_same_move_across_windows_folds_to_newest(self):
        a = {"id": "T-1:900:down", "ts": 1000.0, "abs_delta": 0.40,
             "direction": "down", "ticker": "T-1",
             "previous": 0.80, "current": 0.40}
        b = {"id": "T-1:1200:down", "ts": 1300.0, "abs_delta": 0.40,
             "direction": "down", "ticker": "T-1",
             "previous": 0.80, "current": 0.40}
        out = alerts.dedupe_alerts([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ts"], 1300.0)

    def test_same_move_outside_a_day_keeps_both(self):
        a = {"id": "T-1:900:down", "ts": 1000.0, "abs_delta": 0.40,
             "direction": "down", "ticker": "T-1",
             "previous": 0.80, "current": 0.40}
        b = {"id": "T-1:90000:down", "ts": 100000.0, "abs_delta": 0.40,
             "direction": "down", "ticker": "T-1",
             "previous": 0.80, "current": 0.40}
        out = alerts.dedupe_alerts([a, b])
        self.assertEqual(len(out), 2)

    def test_rows_without_id_are_dropped(self):
        out = alerts.dedupe_alerts([{"ts": 1.0}, {"id": "", "ts": 2.0}])
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
