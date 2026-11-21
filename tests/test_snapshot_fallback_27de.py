"""Regression tests for the previous-snapshot swing fallback (session arena-27de8294, N1).

THE DEFECT
----------
``collector/collector.py`` builds the per-ticker previous observation from
``previous_live.get("observations")``. The snapshot payload that the same module
writes never contains an ``"observations"`` key, so ``previous_obs`` was empty on
every run and no market ever received a ``previous`` Observation.

Two documented behaviours therefore could not happen:

1. ``collector/alerts.py::_swing`` falls back to ``"previous_snapshot_mid"`` when
   the official candlestick reference bar is unavailable. In the published
   snapshot of 2026-11-21T07:19Z only 98 of 750 tracked markets had a reference
   bar, so the fallback is the basis for the large majority of the tracked set.
2. ``collector/alerts.py::swing_rejection`` reports a *suppressed* move using the
   previous snapshot for the same markets.

The tests below are offline. They exercise the two helpers this session adds and
then run the real ``collect()`` against a fake client across two successive runs,
proving that a genuine ≥ $0.10 move with no candle reference is caught on the
second run and published with ``reference_basis == "previous_snapshot_mid"``.

Official sources for the numbers and field names used here:
  * GET /markets         https://docs.kalshi.com/api-reference/market/get-markets
    (``yes_bid_dollars`` / ``yes_ask_dollars`` / ``open_interest_fp`` / ``volume_fp``)
  * order books          https://docs.kalshi.com/getting_started/orderbook_responses
    (bids only; best = last level; implied YES ask = 1 - best NO bid)
  * candlesticks         https://docs.kalshi.com/api-reference/market/get-market-candlesticks
    (``period_interval`` is 1, 60 or 1440 minutes; no row -> no reference)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector import collector as root  # noqa: E402


TICKER = "KXTESTMENU-27JAN01-A"
EVENT = "KXTESTMENU-27JAN01"
SERIES = "KXTESTMENU"


def market_row(yes_bid: str, yes_ask: str) -> dict[str, Any]:
    """A market object shaped like GET /markets returns it."""
    return {
        "ticker": TICKER,
        "event_ticker": EVENT,
        "market_type": "binary",
        "title": "Will the test pass?",
        "yes_sub_title": "Yes it will",
        "status": "active",
        "result": "",
        "close_time": "2027-01-01T15:00:00Z",
        "open_time": "2026-11-20T00:00:00Z",
        "yes_bid_dollars": yes_bid,
        "yes_bid_size_fp": "250.00",
        "yes_ask_dollars": yes_ask,
        "yes_ask_size_fp": "250.00",
        "no_bid_dollars": f"{1 - float(yes_ask):.4f}",
        "no_ask_dollars": f"{1 - float(yes_bid):.4f}",
        "last_price_dollars": yes_bid,
        "previous_price_dollars": yes_bid,
        "open_interest_fp": "10000.00",
        "volume_fp": "20000.00",
        "notional_value_dollars": "1.0000",
    }


def book(yes_bid: str, yes_ask: str, size: str = "250.00") -> dict[str, Any]:
    """Order book as the documented endpoint returns it (bids only)."""
    return {
        "yes_dollars": [[yes_bid, size]],
        "no_dollars": [[f"{1 - float(yes_ask):.4f}", size]],
    }


class ObservationStoreTests(unittest.TestCase):
    """N1(a): the snapshot must publish what the next run reads."""

    def test_helper_returns_the_published_rows(self) -> None:
        obs = [{"ticker": "A", "mid": 0.5}, {"ticker": "B", "mid": 0.4}]
        rows = root.observation_store(obs)
        self.assertEqual([r["ticker"] for r in rows], ["A", "B"])
        self.assertEqual(rows, obs)

    def test_rows_without_a_ticker_are_dropped(self) -> None:
        rows = root.observation_store([{"mid": 0.5}, {"ticker": "", "mid": 0.4},
                                       {"ticker": "C", "mid": 0.3}])
        self.assertEqual([r["ticker"] for r in rows], ["C"])

    def test_store_is_a_plain_copy(self) -> None:
        obs = [{"ticker": "A", "mid": 0.5}]
        rows = root.observation_store(obs)
        rows[0]["mid"] = 0.9
        self.assertEqual(obs[0]["mid"], 0.5, "the live observation must not be mutated")

    def test_store_is_json_serialisable(self) -> None:
        rows = root.observation_store([{"ticker": "A", "mid": 0.5, "ts": 1.5}])
        self.assertIn('"A"', json.dumps(rows))

    def test_reading_a_payload_without_observations_is_not_an_error(self) -> None:
        # The published payload before the fix; must degrade to "no previous rows".
        self.assertEqual(root.previous_observations({"events": []}), {})
        self.assertEqual(root.previous_observations({}), {})

    def test_reading_ignores_unnamed_rows(self) -> None:
        prev = root.previous_observations({"observations": [{"mid": 0.5},
                                                             {"ticker": "A", "mid": 0.5}]})
        self.assertEqual(list(prev), ["A"])


class _TwoRunClient:
    """Fake KalshiClient that serves one topic, one market, two different quotes.

    The candlestick endpoint always answers with an EMPTY list, which is what the
    live demo returns for a market with no trade history (and what it returned for
    652 of the 750 tracked markets at 07:19Z). That is the exact condition under
    which the previous-snapshot fallback is supposed to take over.
    """

    quotes: list[tuple[str, str]] = [("0.20", "0.22"), ("0.40", "0.42")]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.budget = None
        self.run = 0

    # -- discovery ------------------------------------------------------
    def exchange_status(self) -> dict[str, Any]:
        return {"trading_active": True}

    def series_list(self, *args: Any, **kwargs: Any) -> list:
        if kwargs.get("tags"):
            return []
        return [{"ticker": SERIES, "title": SERIES, "category": "Economics",
                 "volume_fp": "20000.00", "fee_multiplier": 1.0,
                 "fee_type": "quadratic"}]

    def events(self, *args: Any, **kwargs: Any) -> list:
        if kwargs.get("series_ticker") != SERIES:
            return []
        class _C(_TwoRunClient):
            quotes = self.quotes
        return [{"event_ticker": EVENT, "series_ticker": SERIES,
                 "category": "Economics", "title": "Test event",
                 "markets": [market_row(*self.quotes[min(self.run, 1)])]}]

    def markets(self, *args: Any, **kwargs: Any) -> list:
        return []

    def orderbooks(self, tickers: Any) -> dict:
        return {TICKER: book(*self.quotes[min(self.run, 1)])}

    def candlesticks(self, *args: Any, **kwargs: Any) -> dict:
        return {"candlesticks": []}


def _patched_paths(tmp: str) -> dict[str, Any]:
    return {
        "DATA_DIR": tmp,
        "STATE_PATH": os.path.join(tmp, "portfolio_state.json"),
        "LIVE_PATH": os.path.join(tmp, "live.json"),
        "HISTORY_PATH": os.path.join(tmp, "history.json"),
        "RESOLUTIONS_PATH": os.path.join(tmp, "resolutions.json"),
        "VERIFIED_PATH": os.path.join(tmp, "verified_results.json"),
    }


class CollectEndToEndTests(unittest.TestCase):
    """Runs the real collect() twice offline: the move must alert on run 2."""

    def test_second_run_alerts_on_the_snapshot_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _patched_paths(tmp)
            client = _TwoRunClient()
            patches = [mock.patch.object(root, n, v) for n, v in paths.items()]
            patches.append(mock.patch.object(root, "KalshiClient", lambda *a, **k: client))
            patches.append(mock.patch.object(root.topic_mod, "cached_series",
                                             lambda c, topic, cache: [
                                                 {"ticker": SERIES, "title": SERIES,
                                                  "topic": "gas-prices",
                                                  "volume_fp": "20000.00",
                                                  "fee_multiplier": 1.0,
                                                  "fee_type": "quadratic"}]))
            for p in patches:
                p.start()
            try:
                client.run = 0
                first = root.collect(market_cap=5, orderbook_cap=5, budget_seconds=60.0)
                # The published payload must now carry the store the next run reads.
                self.assertIn("observations", first,
                              "the snapshot must publish the observations it measured")
                stored = {r["ticker"]: r for r in first["observations"]}
                self.assertIn(TICKER, stored)
                self.assertAlmostEqual(stored[TICKER]["mid"], 0.21, places=4)
                self.assertEqual(first["alerts"], [])

                client.run = 1
                second = root.collect(market_cap=5, orderbook_cap=5, budget_seconds=60.0)
            finally:
                for p in reversed(patches):
                    p.stop()

        self.assertEqual(len(second["alerts"]), 1,
                         f"expected one swing on the second run, got {second['alerts']}")
        alert = second["alerts"][0]
        self.assertEqual(alert["ticker"], TICKER)
        self.assertEqual(alert["direction"], "up")
        self.assertAlmostEqual(alert["delta"], 0.20, places=4)  # 0.21 -> 0.41 mid
        self.assertEqual(alert["reference_basis"], "previous_snapshot_mid")
        self.assertEqual(alert["basis"], "previous_snapshot_mid")
        self.assertEqual(alert["bar_start"] % 300, 0,
                         "the alert must be keyed to a 5-minute reference bar")
        self.assertEqual(alert["observed_gap_seconds"], 0.0)
        self.assertTrue(alert["quality"] in ("executable", "indicative"))
        # Every alert stays traceable: the market URL is the exchange's own page
        # and the api_root is published alongside so the row links to the same
        # demo environment the numbers came from.
        self.assertEqual(alert["market_url"],
                         f"https://kalshi.com/markets/{SERIES}/{TICKER}")
        self.assertEqual(second["api_root"],
                         "https://external-api.demo.kalshi.co/trade-api/v2")

    def test_first_run_publishes_placeholders_but_no_false_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _patched_paths(tmp)
            client = _TwoRunClient()
            client.run = 0
            patches = [mock.patch.object(root, n, v) for n, v in paths.items()]
            patches.append(mock.patch.object(root, "KalshiClient", lambda *a, **k: client))
            patches.append(mock.patch.object(root.topic_mod, "cached_series",
                                             lambda c, topic, cache: [
                                                 {"ticker": SERIES, "title": SERIES,
                                                  "topic": "gas-prices",
                                                  "volume_fp": "20000.00",
                                                  "fee_multiplier": 1.0,
                                                  "fee_type": "quadratic"}]))
            for p in patches:
                p.start()
            try:
                payload = root.collect(market_cap=5, orderbook_cap=5, budget_seconds=60.0)
            finally:
                for p in reversed(patches):
                    p.stop()
        self.assertEqual(payload["alerts"], [],
                         "a first run has no earlier measurement, so it cannot alert")
        self.assertEqual(payload["snapshot_fallback"]["previous_rows"], 0)


class DeskCopyTests(unittest.TestCase):
    """N1(b): the empty chat must say what was measured, not "nothing happened"."""

    def test_desk_copy_names_both_bases(self) -> None:
        with open(os.path.join(ROOT, "assets", "desk.js"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertTrue("previous_snapshot_mid" in src,
                        "desk.js must name the previous-snapshot basis its rows can use")
        self.assertTrue("candle_quote_mid" in src,
                        "desk.js must name the candle basis its rows can use")

    def test_empties_report_what_was_measured(self) -> None:
        """The JS and the pre-render must both state the measured counts."""
        import re
        with open(os.path.join(ROOT, "assets", "desk.js"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("emptyAllFeedHtml", src)
        self.assertIn("snapshot_fallback", src)
        # The old copy, in a rendered string (not a comment about the old copy).
        rendered = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        self.assertTrue("move observed yet" not in rendered,
                        "the empty chat must not read as \"nothing happened\"")
        self.assertIn("markets measured this snapshot", rendered)

    def test_prerendered_empty_chat_states_the_counts(self) -> None:
        sys.path.insert(0, ROOT)
        from site_build.build import empty_all_feed
        html_text = empty_all_feed({
            "observation_count": 750,
            "suppressed_alerts": [{"ticker": "A"}, {"ticker": "B"}],
            "snapshot_fallback": {"measured_rows": 750, "candle_reference_rows": 98,
                                  "previous_rows": 0},
        })
        self.assertIn("750 markets measured this snapshot", html_text)
        self.assertIn("98 had an official 1-minute candle reference", html_text)
        self.assertIn("no earlier rows yet", html_text)
        self.assertIn("2 midpoint moves", html_text)
        self.assertIn("candle_quote_mid", html_text)
        self.assertIn("previous_snapshot_mid", html_text)
        self.assertIn("review.html#refused", html_text)


if __name__ == "__main__":
    unittest.main()
