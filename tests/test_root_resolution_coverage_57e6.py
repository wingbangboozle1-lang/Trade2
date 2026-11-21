"""Regression tests for root-pipeline resolution coverage (session arena-57e6bd3d, E57-T1).

Defect (COORDINATION.md, R-3DCF-1): the root collector's settled scan reads the newest
settled markets exchange-wide. Crypto 15-minute markets fill that window, so the published
data/resolutions.json held 328 rows with zero elections, culture or golf outcomes.

Fix under test (collector/collector.py): every market the collector watches is tracked
until it settles, and once its close time has passed it is re-read with
GET /markets/{ticker}. Official sources:
  * https://docs.kalshi.com/api-reference/market/get-market  ({"market": {...}} response)
  * https://docs.kalshi.com/getting_started/market_settlement (YES / NO settlement)
  * live check: https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDPWORLDTOUR-DPWTC26-THAT
    returns result "yes", status "finalized", settlement_ts set.

All tests are offline. They use a fake client and fake observations.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector import collector as root  # noqa: E402


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> float:
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc).timestamp()


def iso_utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeClient:
    """Answers GET /markets/{ticker} from a dict. Records every request path."""

    def __init__(self, markets: dict[str, dict[str, Any]] | None = None,
                 fail: set[str] | None = None) -> None:
        self.markets = markets or {}
        self.fail = fail or set()
        self.paths: list[str] = []

    def _request(self, method: str, path: str, params: Any = None, **_: Any) -> Any:
        self.paths.append(f"{method} {path}")
        ticker = path.rsplit("/", 1)[-1]
        if ticker in self.fail:
            raise RuntimeError("simulated transport failure")
        market = self.markets.get(ticker)
        return {"market": market} if market is not None else {}


def obs(ticker: str, topic: str, close_time: str, event: str = "") -> SimpleNamespace:
    return SimpleNamespace(ticker=ticker, event_ticker=event or ticker.rsplit("-", 1)[0],
                           topic=topic, title=f"title {ticker}", close_time=close_time,
                           series_ticker="")


def settled(ticker: str, result: str, event: str = "", at: str = "2026-11-15T14:56:17Z") -> dict:
    result = result.lower()  # the API returns lowercase; the fixture accepts either case
    return {"ticker": ticker, "event_ticker": event or ticker.rsplit("-", 1)[0],
            "result": result, "status": "finalized", "settlement_ts": at,
            "settlement_value_dollars": "1.0000" if result == "yes" else "0.0000",
            "yes_sub_title": "Tyrrell Hatton", "title": "DP World Tour Championship"}


class EpochParsingTests(unittest.TestCase):
    def test_documented_timestamp_shape(self) -> None:
        self.assertEqual(root._epoch("2026-11-15T14:52:33Z"), utc(2026, 11, 15, 14, 52) + 33)

    def test_fractional_seconds_are_accepted(self) -> None:
        self.assertEqual(root._epoch("2026-11-21T07:04:27.959753Z"),
                         utc(2026, 11, 21, 7, 4) + 27)

    def test_missing_or_bad_values_are_none(self) -> None:
        for bad in (None, "", "not-a-time", "2026-11-15"):
            self.assertIsNone(root._epoch(bad), bad)


class RecordShapeTests(unittest.TestCase):
    def test_record_uses_market_fields_and_official_source(self) -> None:
        now = utc(2026, 11, 21, 7, 0)
        rec = root.resolution_record(settled("KXDPWORLDTOUR-DPWTC26-THAT", "YES"),
                                     "KXDPWORLDTOUR-DPWTC26-THAT", "golf", now)
        self.assertEqual(rec["result"], "yes")
        self.assertEqual(rec["topic"], "golf")
        self.assertEqual(rec["settlement_value_dollars"], "1.0000")
        self.assertEqual(rec["settlement_ts"], "2026-11-15T14:56:17Z")
        self.assertEqual(rec["status"], "finalized")
        self.assertEqual(rec["source_url"], f"{root.DEMO_REST}/markets/KXDPWORLDTOUR-DPWTC26-THAT")
        self.assertEqual(rec["verified_at"], "2026-11-21T07:00:00Z")


class FetchMarketTests(unittest.TestCase):
    def test_requests_the_documented_ticker_path(self) -> None:
        client = FakeClient({"KXDPWORLDTOUR-DPWTC26-THAT": settled("KXDPWORLDTOUR-DPWTC26-THAT", "yes")})
        market = root.fetch_market(client, "KXDPWORLDTOUR-DPWTC26-THAT")
        self.assertEqual(client.paths, ["GET /markets/KXDPWORLDTOUR-DPWTC26-THAT"])
        self.assertEqual(market["result"], "yes")

    def test_ticker_is_percent_encoded(self) -> None:
        client = FakeClient()
        root.fetch_market(client, "A/B C")
        self.assertEqual(client.paths, ["GET /markets/A%2FB%20C"])

    def test_body_without_market_object_returns_none(self) -> None:
        self.assertIsNone(root.fetch_market(FakeClient(), "MISSING"))


class TrackingTests(unittest.TestCase):
    def test_each_observed_market_is_registered_once(self) -> None:
        pending: dict[str, dict] = {}
        now = utc(2026, 11, 21, 7, 0)
        watch = [obs("KXDPWORLDTOUR-DPWTC26-THAT", "golf", "2026-11-29T00:00:00Z")]
        root.track_pending(pending, watch, now)
        root.track_pending(pending, watch, now + 300)
        self.assertEqual(list(pending), ["KXDPWORLDTOUR-DPWTC26-THAT"])
        row = pending["KXDPWORLDTOUR-DPWTC26-THAT"]
        self.assertEqual(row["topic"], "golf")
        self.assertEqual(row["first_seen"], "2026-11-21T07:00:00Z")
        self.assertIsNone(row["last_checked"])

    def test_missing_close_time_is_filled_when_it_appears(self) -> None:
        pending: dict[str, dict] = {}
        root.track_pending(pending, [obs("X-1", "culture", "")], 0.0)
        self.assertIsNone(pending["X-1"]["close_time"])
        root.track_pending(pending, [obs("X-1", "culture", "2026-11-20T00:00:00Z")], 0.0)
        self.assertEqual(pending["X-1"]["close_time"], "2026-11-20T00:00:00Z")

    def test_cap_keeps_the_markets_closing_soonest(self) -> None:
        pending: dict[str, dict] = {}
        watch = [obs(f"M-{i}", "gas-prices", iso_utc(utc(2026, 11, 22) + i * 3600))
                 for i in range(5)]
        with mock.patch.object(root, "RESOLUTION_PENDING_MAX", 3):
            root.track_pending(pending, watch, 0.0)
        self.assertEqual(sorted(pending), ["M-0", "M-1", "M-2"])


class ResolvePendingTests(unittest.TestCase):
    NOW = utc(2026, 11, 21, 7, 0)

    def test_only_markets_past_close_are_read(self) -> None:
        pending: dict[str, dict] = {}
        track = [obs("DUE-1", "golf", "2026-11-20T00:00:00Z"),
                 obs("LATER-1", "golf", "2026-11-30T00:00:00Z")]
        root.track_pending(pending, track, self.NOW)
        client = FakeClient({"DUE-1": settled("DUE-1", "yes")})
        resolved, dropped, lookups = root.resolve_pending(client, pending, self.NOW)
        self.assertEqual(client.paths, ["GET /markets/DUE-1"])
        self.assertEqual(lookups, 1)
        self.assertEqual([t for t, _ in resolved], ["DUE-1"])
        self.assertEqual(dropped, [])
        self.assertEqual(list(pending), ["LATER-1"])

    def test_resolved_market_gets_topic_from_the_watch_list(self) -> None:
        pending: dict[str, dict] = {}
        root.track_pending(pending, [obs("KXDPWORLDTOUR-DPWTC26-THAT", "golf",
                                         "2026-11-15T14:52:33Z")], self.NOW)
        client = FakeClient({"KXDPWORLDTOUR-DPWTC26-THAT":
                             settled("KXDPWORLDTOUR-DPWTC26-THAT", "YES")})
        resolved, _, _ = root.resolve_pending(client, pending, self.NOW)
        ticker, rec = resolved[0]
        self.assertEqual(ticker, "KXDPWORLDTOUR-DPWTC26-THAT")
        self.assertEqual(rec["topic"], "golf")
        self.assertEqual(rec["result"], "yes")
        self.assertNotIn(ticker, pending)

    def test_open_market_stays_pending_and_is_marked_checked(self) -> None:
        pending: dict[str, dict] = {}
        root.track_pending(pending, [obs("OPEN-1", "elections", "2026-11-20T00:00:00Z")], self.NOW)
        client = FakeClient({"OPEN-1": {"ticker": "OPEN-1", "status": "active", "result": ""}})
        resolved, dropped, _ = root.resolve_pending(client, pending, self.NOW)
        self.assertEqual(resolved, [])
        self.assertEqual(dropped, [])
        self.assertIn("OPEN-1", pending)
        self.assertEqual(pending["OPEN-1"]["last_checked"], "2026-11-21T07:00:00Z")
        self.assertEqual(pending["OPEN-1"]["lookups"], 1)

    def test_lookups_are_bounded_and_rotate_least_recent_first(self) -> None:
        pending: dict[str, dict] = {}
        watch = [obs(f"DUE-{i}", "culture", "2026-11-20T00:00:00Z") for i in range(5)]
        root.track_pending(pending, watch, self.NOW)
        client = FakeClient()  # every market stays open
        seen_per_run = []
        for run in range(3):
            before = len(client.paths)
            root.resolve_pending(client, pending, self.NOW + run * 300, limit=2)
            seen_per_run.append({p.rsplit("/", 1)[-1] for p in client.paths[before:]})
        self.assertTrue(all(len(s) == 2 for s in seen_per_run), seen_per_run)
        self.assertEqual(seen_per_run[0] & seen_per_run[1], set())
        self.assertEqual(set().union(*seen_per_run), {f"DUE-{i}" for i in range(5)})

    def test_market_is_dropped_after_the_give_up_horizon(self) -> None:
        pending: dict[str, dict] = {}
        close = self.NOW - root.RESOLUTION_GIVE_UP_S - 3600
        root.track_pending(pending, [obs("STUCK-1", "golf", iso_utc(close))], self.NOW)
        client = FakeClient({"STUCK-1": {"ticker": "STUCK-1", "status": "active", "result": ""}})
        resolved, dropped, _ = root.resolve_pending(client, pending, self.NOW)
        self.assertEqual(resolved, [])
        self.assertEqual(dropped, ["STUCK-1"])
        self.assertNotIn("STUCK-1", pending)

    def test_failed_lookup_keeps_the_market_and_reports_it(self) -> None:
        pending: dict[str, dict] = {}
        root.track_pending(pending, [obs("FLAKY-1", "golf", "2026-11-20T00:00:00Z")], self.NOW)
        errors: list[str] = []
        client = FakeClient(fail={"FLAKY-1"})
        resolved, dropped, lookups = root.resolve_pending(client, pending, self.NOW, errors=errors)
        self.assertEqual((resolved, dropped, lookups), ([], [], 1))
        self.assertIn("FLAKY-1", pending)
        self.assertTrue(any("FLAKY-1" in e for e in errors), errors)

    def test_expired_run_budget_makes_no_requests(self) -> None:
        pending: dict[str, dict] = {}
        root.track_pending(pending, [obs("LATE-1", "golf", "2026-11-20T00:00:00Z")], self.NOW)
        errors: list[str] = []
        client = FakeClient({"LATE-1": settled("LATE-1", "no")})
        resolved, _, lookups = root.resolve_pending(client, pending, self.NOW,
                                                    deadline=self.NOW - 1, errors=errors)
        self.assertEqual((resolved, lookups), ([], 0))
        self.assertEqual(client.paths, [])
        self.assertIn("LATE-1", pending)
        self.assertTrue(any("budget" in e for e in errors), errors)


class _FakePosition:
    def __init__(self, ticker: str, price: float) -> None:
        self.ticker = ticker
        self.exit_price = price

    def as_dict(self) -> dict:
        return {"ticker": self.ticker, "exit_price": self.exit_price}


class _FakePortfolio:
    """Settles only ticker names it holds, like Portfolio.settle (open positions only)."""

    def __init__(self, held: set[str]) -> None:
        self.held = set(held)
        self.calls: list[tuple[str, str]] = []

    def settle(self, ticker: str, result: str) -> _FakePosition | None:
        self.calls.append((ticker, result))
        if ticker in self.held:
            self.held.discard(ticker)
            return _FakePosition(ticker, 1.0 if result == "yes" else 0.0)
        return None


class ApplyResolutionsTests(unittest.TestCase):
    NOW = utc(2026, 11, 21, 7, 0)

    def test_resolved_rows_are_stored_and_held_positions_graded(self) -> None:
        store: dict[str, Any] = {"resolutions": {}}
        history: dict[str, Any] = {"series": {}}
        settled_updates: list[dict] = []
        portfolio = _FakePortfolio(held={"KXDPWORLDTOUR-DPWTC26-THAT"})
        rec = root.resolution_record(settled("KXDPWORLDTOUR-DPWTC26-THAT", "yes"),
                                     "KXDPWORLDTOUR-DPWTC26-THAT", "golf", self.NOW)
        root.apply_pending_resolutions(store, [("KXDPWORLDTOUR-DPWTC26-THAT", rec)],
                                       portfolio, history, settled_updates, self.NOW)
        self.assertIn("KXDPWORLDTOUR-DPWTC26-THAT", store["resolutions"])
        self.assertEqual(len(settled_updates), 1)
        self.assertEqual(history["series"]["KXDPWORLDTOUR-DPWTC26-THAT"][0]["result"], "yes")

    def test_market_already_graded_by_the_scan_is_not_graded_twice(self) -> None:
        store: dict[str, Any] = {"resolutions": {}}
        history: dict[str, Any] = {"series": {}}
        settled_updates: list[dict] = []
        portfolio = _FakePortfolio(held=set())  # the scan already closed it
        rec = root.resolution_record(settled("GOLF-1", "no"), "GOLF-1", "golf", self.NOW)
        root.apply_pending_resolutions(store, [("GOLF-1", rec)], portfolio, history,
                                       settled_updates, self.NOW)
        self.assertEqual(settled_updates, [])
        self.assertNotIn("GOLF-1", history["series"])
        self.assertEqual(store["resolutions"]["GOLF-1"]["result"], "no")


class _SmokeClient:
    """Offline stand-in for KalshiClient used by the collect() smoke test.

    Discovery returns nothing, so the only market that can settle is the pending one
    seeded in the store. GET /markets/{ticker} answers from SETTLED.
    """

    SETTLED: dict[str, dict[str, Any]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.budget = None

    def exchange_status(self) -> dict[str, Any]:
        return {"trading_active": True}

    def series_list(self, *args: Any, **kwargs: Any) -> list:
        return []

    def events(self, *args: Any, **kwargs: Any) -> list:
        return []

    def markets(self, *args: Any, **kwargs: Any) -> list:
        return []  # the exchange-wide settled scan sees nothing this run

    def orderbooks(self, tickers: Any) -> dict:
        return {}

    def candlesticks(self, *args: Any, **kwargs: Any) -> dict:
        return {"candlesticks": []}

    def _request(self, method: str, path: str, params: Any = None, **_: Any) -> Any:
        import urllib.parse
        ticker = urllib.parse.unquote(path.rsplit("/", 1)[-1])
        market = self.SETTLED.get(ticker)
        return {"market": market} if market else {}


class CollectSmokeTests(unittest.TestCase):
    """Runs the real collect() offline, with every data path redirected to a temp dir."""

    def test_pending_market_is_settled_stored_and_graded(self) -> None:
        import json
        import tempfile

        ticker = "KXDPWORLDTOUR-DPWTC26-THAT"
        close = "2026-11-15T14:52:33Z"  # already past: the live demo market closed here
        with tempfile.TemporaryDirectory() as tmp:
            paths = {
                "DATA_DIR": tmp,
                "STATE_PATH": os.path.join(tmp, "portfolio_state.json"),
                "LIVE_PATH": os.path.join(tmp, "live.json"),
                "HISTORY_PATH": os.path.join(tmp, "history.json"),
                "RESOLUTIONS_PATH": os.path.join(tmp, "resolutions.json"),
                "VERIFIED_PATH": os.path.join(tmp, "verified_results.json"),
            }
            seeded = {"resolutions": {}, "meta": {}, "pending": {ticker: {
                "ticker": ticker, "event_ticker": "KXDPWORLDTOUR-DPWTC26", "series_ticker": None,
                "topic": "golf", "title": "DP World Tour Championship: Tyrrell Hatton wins",
                "close_time": close, "first_seen": "2026-11-10T00:00:00Z",
                "last_checked": None, "lookups": 0}}}
            with open(paths["RESOLUTIONS_PATH"], "w", encoding="utf-8") as fh:
                json.dump(seeded, fh)
            _SmokeClient.SETTLED = {ticker: settled(ticker, "yes", at="2026-11-15T14:56:17Z")}

            patches = [mock.patch.object(root, name, value) for name, value in paths.items()]
            patches.append(mock.patch.object(root, "KalshiClient", _SmokeClient))
            for p in patches:
                p.start()
            try:
                payload = root.collect(budget_seconds=60.0)
            finally:
                for p in reversed(patches):
                    p.stop()

            with open(paths["RESOLUTIONS_PATH"], encoding="utf-8") as fh:
                store = json.load(fh)
            with open(paths["LIVE_PATH"], encoding="utf-8") as fh:
                live = json.load(fh)

        self.assertIn(ticker, store["resolutions"])
        rec = store["resolutions"][ticker]
        self.assertEqual((rec["topic"], rec["result"]), ("golf", "yes"))
        self.assertNotIn(ticker, store.get("pending", {}))
        self.assertEqual(payload["resolution_tracking"]["resolved_this_run"], 1)
        self.assertEqual(payload["resolution_tracking"]["pending"], 0)
        self.assertEqual(live["resolution_tracking"]["lookups_this_run"], 1)
        self.assertEqual([r["ticker"] for r in live["resolutions"]["golf"]], [ticker])
        self.assertEqual(live["resolutions_count"], 1)


if __name__ == "__main__":
    unittest.main()
