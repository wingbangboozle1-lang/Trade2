"""Board L (session `arena-282a1080`) — the open requests still missing from
main, implemented.

R-F3-1 landed on `main` via PR #60/#72 (`REFERENCE_TRADE_TOLERANCE`
corroboration) while this branch was in flight; this session therefore does NOT
ship its own label-only variant of that guard. What it ships instead:

* L1b — plumbing completion for the merged R-F3-1 guard: `bar_reference()`
  publishes the candle's documented ``price.previous_dollars`` under the key
  ``previous_dollars`` (the merged code reads it but nothing supplied it), and
  the collector attaches it to observations — until now the merged guard could
  only ever fall back to ``price.close_dollars``.
* L2 / R-F3-2 — tick size ``price_ranges[0].step`` on observations, event rows
  and alert rows, with the "≈ N ticks" note beside the $0.10 threshold.
* L3 / R-3DCF-3 — ``mark_reverted``: "reverted within one candle" annotation
  from the next completed candle's trade close.
* L4 / R-3DCF-2 — explicit-zero ask size renders as "no ask size", not a bare 0.
* L5 / R-3DCF-6 — window labels state data granularity (seconds = live quotes,
  candles are 1-minute minimum).

Official field shapes used by the fixtures:
  * candlesticks  https://docs.kalshi.com/api-reference/market/get-market-candlesticks
    (``price.previous_dollars``, ``price.close_dollars``, ``yes_bid``/``yes_ask``)
  * market record https://docs.kalshi.com/api-reference/market/get-market
    (``price_ranges[].step`` — "Price step/tick size for this range in dollars")

Mutation checks: every assertion here fails on the pre-change code — the tick
fields, revert annotation and ask-size wording did not exist, and bar_reference
published no ``previous_dollars`` / ``candles`` keys.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.alerts import (Observation, detect_swing, mark_reverted,
                              observe, rank_events, threshold_in_ticks,
                              SWING_THRESHOLD)
from collector.collector import bar_reference
from site_build.build import alert_chat_row


def obs(mid, ts=1000.0, bid=None, ask=None, yes_size=100.0, no_size=100.0,
        ref_bid=None, ref_ask=None, ref_trade=None, ref_ts=900.0, ticker="T",
        tick_size=None):
    if bid is None and ask is None and mid is not None:
        bid = ask = mid
    return Observation(ts=ts, ticker=ticker, event_ticker="E-1", topic="elections",
                       title="Sample market", yes_bid=bid, yes_ask=ask, mid=mid,
                       last_price=None, volume=10.0, open_interest=10.0,
                       yes_bid_size=yes_size, no_bid=ask if ask is not None else None,
                       no_bid_size=no_size,
                       ref_ts=ref_ts, ref_yes_bid=ref_bid, ref_yes_ask=ref_ask,
                       ref_trade_close=ref_trade,
                       tick_size=tick_size, series_ticker="S")


class TestTickSize(unittest.TestCase):
    """L2 / R-F3-2: the documented tick travels with the row."""

    MARKET = {
        "ticker": "T", "yes_bid_dollars": "0.4200", "yes_ask_dollars": "0.4400",
        "price_ranges": [{"step": "0.0100", "min_price": "0.0100",
                          "max_price": "0.9900"}],
    }

    def test_step_is_read_from_the_documented_field(self):
        o = observe(dict(self.MARKET), None, "elections", ts=1000.0)
        self.assertEqual(o.tick_size, 0.01)

    def test_missing_price_ranges_stays_none(self):
        o = observe({"ticker": "T", "yes_bid_dollars": "0.42",
                     "yes_ask_dollars": "0.44"}, None, "elections", ts=1000.0)
        self.assertIsNone(o.tick_size)

    def test_alert_row_states_the_tick_count(self):
        alert = detect_swing(None, obs(0.43, bid=0.42, ask=0.44,
                                       ref_bid=0.30, ref_ask=0.32,
                                       tick_size=0.01))
        self.assertIsNotNone(alert)
        self.assertEqual(alert["tick_size"], 0.01)
        self.assertEqual(alert["threshold_ticks"], 10.0)

    def test_threshold_in_ticks(self):
        self.assertEqual(threshold_in_ticks(SWING_THRESHOLD, 0.01), 10.0)
        self.assertEqual(threshold_in_ticks(SWING_THRESHOLD, 0.05), 2.0)
        self.assertIsNone(threshold_in_ticks(SWING_THRESHOLD, None))
        self.assertIsNone(threshold_in_ticks(SWING_THRESHOLD, 0.0))

    def test_event_rows_carry_the_tick(self):
        rows = rank_events([obs(0.43, tick_size=0.01)])
        self.assertEqual(rows[0]["tick_size"], 0.01)

    def test_unknown_tick_is_omitted_not_invented(self):
        alert = detect_swing(None, obs(0.43, bid=0.42, ask=0.44,
                                       ref_bid=0.30, ref_ask=0.32))
        self.assertIsNone(alert["tick_size"])
        self.assertIsNone(alert["threshold_ticks"])


class TestReferencePlumbing(unittest.TestCase):
    """L1b: the merged R-F3-1 guard can now actually see previous_dollars.

    The merged corroboration reads ``Observation.ref_previous_dollars``, which
    nothing on main supplied: bar_reference published no ``previous_dollars``
    key and the collector never attached it. These tests pin the completed
    plumbing end to end.
    """

    class Client:
        def __init__(self, payload): self.payload = payload
        def candlesticks(self, series, ticker, start_ts, end_ts,
                         period_interval=1):
            return self.payload

    def test_bar_reference_publishes_previous_dollars(self):
        now = 1_795_200_068          # current 5-minute bar starts at ...1795200000
        bar = now - (now % 300)      # 1795200000 — the reference bar's end
        payload = {"candlesticks": [{
            "end_period_ts": bar,
            "yes_bid": {"close_dollars": "0.3000"},
            "yes_ask": {"close_dollars": "0.3200"},
            "price": {"close_dollars": "0.2500",
                      "previous_dollars": "0.2450"},
        }]}
        import time as _t
        real = _t.time
        _t.time = lambda: float(now)
        try:
            ref = bar_reference(self.Client(payload),
                                {"series_ticker": "S", "ticker": "T"},
                                deadline=real() + 60)
        finally:
            _t.time = real
        self.assertEqual(ref["previous_dollars"], 0.2450)
        self.assertEqual(ref["trade_close"], 0.2500)
        self.assertEqual(ref["mid"], 0.31)          # quote mid, never 0.25

    def test_missing_previous_dollars_is_none_not_zero(self):
        now = 1_795_200_068
        bar = now - (now % 300)
        payload = {"candlesticks": [{
            "end_period_ts": bar,
            "yes_bid": {"close_dollars": "0.3000"},
            "yes_ask": {"close_dollars": "0.3200"},
            "price": {"close_dollars": "0.2500"},
        }]}
        import time as _t
        real = _t.time
        _t.time = lambda: float(now)
        try:
            ref = bar_reference(self.Client(payload),
                                {"series_ticker": "S", "ticker": "T"},
                                deadline=real() + 60)
        finally:
            _t.time = real
        self.assertIsNone(ref["previous_dollars"])

    def test_observe_carries_the_previous_dollars_reference(self):
        o = observe({"ticker": "T", "yes_bid_dollars": "0.42",
                     "yes_ask_dollars": "0.44"},
                    None, "elections", ts=1000.0,
                    reference={"ts": 900.0, "yes_bid": 0.30, "yes_ask": 0.32,
                               "trade_close": 0.25,
                               "previous_dollars": 0.245})
        self.assertEqual(o.ref_previous_dollars, 0.245)
        self.assertEqual(o.ref_trade_close, 0.25)

    def test_bar_reference_publishes_completed_candles_for_the_revert_check(self):
        now = 1_795_200_068
        bar = now - (now % 300)
        payload = {"candlesticks": [
            {"end_period_ts": bar,
             "yes_bid": {"close_dollars": "0.3000"},
             "yes_ask": {"close_dollars": "0.3200"},
             "price": {"close_dollars": "0.2500"}},
            {"end_period_ts": bar + 60,     # still forming — excluded
             "yes_bid": {"close_dollars": "0.3300"},
             "yes_ask": {"close_dollars": "0.3500"},
             "price": {"close_dollars": "0.3400"}},
        ]}
        import time as _t
        real = _t.time
        _t.time = lambda: float(now)
        try:
            ref = bar_reference(self.Client(payload),
                                {"series_ticker": "S", "ticker": "T"},
                                deadline=real() + 60)
        finally:
            _t.time = real
        self.assertEqual(len(ref["candles"]), 1)
        self.assertEqual(ref["candles"][0]["ts"], bar)
        self.assertEqual(ref["candles"][0]["trade_close"], 0.2500)


class TestMarkReverted(unittest.TestCase):
    """L3 / R-3DCF-3: the 3dcf3f13 example (0.17 -> 0.39, next candle 0.17)."""

    def test_revert_within_one_candle_is_annotated(self):
        alerts = [{
            "ticker": "KXPGATOUR-THRC26-MTHO", "previous": 0.17,
            "previous_ts": 900.0, "ts": 960.0,
        }]
        refs = {"KXPGATOUR-THRC26-MTHO": {"candles": [
            {"ts": 900.0, "trade_close": 0.39},
            {"ts": 960.0, "trade_close": 0.17},
        ]}}
        n = mark_reverted(alerts, refs, threshold=SWING_THRESHOLD)
        self.assertEqual(n, 1)
        ann = alerts[0]["reverted_within_candle"]
        self.assertEqual(ann["candle_end_ts"], 960.0)
        self.assertEqual(ann["trade_close"], 0.17)
        self.assertEqual(ann["previous_level"], 0.17)

    def test_move_that_held_is_not_annotated(self):
        alerts = [{"ticker": "T", "previous": 0.39, "previous_ts": 900.0,
                   "ts": 960.0}]
        refs = {"T": {"candles": [{"ts": 960.0, "trade_close": 0.55}]}}
        self.assertEqual(mark_reverted(alerts, refs), 0)
        self.assertNotIn("reverted_within_candle", alerts[0])

    def test_annotation_survives_a_second_run(self):
        alerts = [{"ticker": "T", "previous": 0.39, "previous_ts": 900.0,
                   "ts": 960.0,
                   "reverted_within_candle": {"candle_end_ts": 960.0,
                                              "trade_close": 0.41,
                                              "previous_level": 0.39}}]
        refs = {"T": {"candles": [{"ts": 1200.0, "trade_close": 0.90}]}}
        self.assertEqual(mark_reverted(alerts, refs), 0)
        self.assertEqual(alerts[0]["reverted_within_candle"]["trade_close"],
                         0.41)

    def test_snapshot_basis_alert_uses_the_observation_time(self):
        alerts = [{"ticker": "T", "previous": 0.30, "previous_ts": None,
                   "ts": 1000.0}]
        refs = {"T": {"candles": [{"ts": 1020.0, "trade_close": 0.33}]}}
        self.assertEqual(mark_reverted(alerts, refs), 1)
        self.assertEqual(alerts[0]["reverted_within_candle"]["candle_end_ts"],
                         1020.0)

    def test_no_candle_or_no_close_is_a_silent_skip(self):
        alerts = [{"ticker": "T", "previous": 0.30, "previous_ts": 900.0,
                   "ts": 960.0}]
        self.assertEqual(mark_reverted(alerts, {}), 0)
        self.assertEqual(mark_reverted(alerts, {"T": {"candles": []}}), 0)
        self.assertEqual(mark_reverted(
            alerts, {"T": {"candles": [{"ts": 960.0, "trade_close": None}]}}), 0)
        self.assertNotIn("reverted_within_candle", alerts[0])


class TestAskSizeAndWindowRendering(unittest.TestCase):
    """L4 / R-3DCF-2 and L5 / R-3DCF-6 as they render for a trader."""

    def base_alert(self, **kw):
        row = {
            "ticker": "T", "title": "Sample market", "topic": "elections",
            "direction": "down", "abs_delta": 0.22, "previous": 0.39,
            "current": 0.17, "iso": "2026-11-21T06:12:00Z",
            "reference_basis": "candle_quote_mid", "spread": 0.02,
            "size_at_top": 0.0, "market_url": "https://kalshi.com/markets/T",
            "event_ticker": "E-1", "threshold": 0.10,
        }
        row.update(kw)
        return row

    def test_explicit_zero_size_says_no_ask_size(self):
        html_out = alert_chat_row(self.base_alert())
        self.assertIn("no ask size: 0 contracts resting at the level", html_out)

    def test_known_size_still_states_the_count(self):
        html_out = alert_chat_row(self.base_alert(size_at_top=25.0))
        self.assertIn("25 contracts at the level", html_out)

    def test_missing_size_keeps_the_published_render_contract(self):
        # The pre-existing None wording is pinned by test_site_render_dc732aa6;
        # L4 changes only the explicit zero.
        html_out = alert_chat_row(self.base_alert(size_at_top=None))
        self.assertIn("no resting size at the level", html_out)
        self.assertNotIn("no ask size", html_out)

    def test_ticks_note_renders_with_the_tick_size(self):
        html_out = alert_chat_row(self.base_alert(threshold_ticks=10.0,
                                                  tick_size=0.01))
        self.assertIn("≈ 10 ticks", html_out)
        self.assertIn("$0.0100", html_out)

    def test_no_tick_note_without_tick_data(self):
        html_out = alert_chat_row(self.base_alert(threshold_ticks=None,
                                                  tick_size=None))
        self.assertNotIn("ticks", html_out)

    def test_reverted_badge_renders(self):
        html_out = alert_chat_row(self.base_alert(
            reverted_within_candle={"candle_end_ts": 960.0,
                                    "trade_close": 0.17,
                                    "previous_level": 0.17}))
        self.assertIn("reverted within one candle", html_out)

    def test_window_labels_state_data_granularity(self):
        # L5 / R-3DCF-6: the desk must not imply second-based candles. The
        # pre-change labels were "Last 90 seconds" / "Last 60 minutes" /
        # "Last 12 hours" with no granularity statement.
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "assets", "desk.js"),
                encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Last 90 seconds · live book quotes", src)
        self.assertIn("Last 60 minutes · 1-minute candles + live quotes", src)
        self.assertIn("Last 12 hours · 1-minute candles + live quotes", src)


if __name__ == "__main__":
    unittest.main()
