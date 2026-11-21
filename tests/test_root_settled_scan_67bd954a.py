"""Regression tests for the ROOT collector's resolution coverage (session arena-67bd954a, R1).

Request R-3DCF-1 (session arena-3dcf3f13): the published root snapshot data/resolutions.json
had only gas-prices (268) and crypto (60) rows and no elections, culture or golf, even
though the live demo API returns settled yes outcomes in those topics. Causes, all in
collector/collector.py before this change:

1. The settled scan was ``GET /markets?status=settled&limit=400`` with no time filter.
   It read the first three pages of whatever the exchange returned, which never reached
   the other topics.
2. The store was cut to the newest 2000 rows globally, so the busiest topics (crypto,
   gas-prices, which settle many times a day) evicted the others.
3. Open simulated positions were graded only if they appeared in that same unfiltered
   scan, so a position whose market settled earlier was never graded.

The fixes under test: ``scan_settled`` (documented ``min_settled_ts`` window, documented
``mve_filter=exclude``, cursor paging, truncation flag), ``lookup_held_settled`` (documented
``tickers`` filter, yes/no results only), and ``migrate_resolutions`` (per-topic floor inside the unchanged global bound).

Every test uses an offline fake client. The fake records the exact query parameters, so
the assertions check what would be sent to https://external-api.demo.kalshi.co/trade-api/v2
(the parameter names are quoted from https://docs.kalshi.com/api-reference/market/get-markets).
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import collector as root  # noqa: E402
from collector.kalshi_api import KalshiHTTPError  # noqa: E402

NOW = 1795243800.0  # 2026-11-21T06:50:00Z (fixed clock for the tests)


class FakeRequestClient:
    """Stands in for KalshiClient._request. Settled-scan calls are answered with
    ``pages`` in order (the last page repeats). ``tickers=`` lookups are answered from
    ``lookup_table``; a lookup containing a ticker in ``raise_on`` raises."""

    def __init__(self, pages: list[dict[str, Any]] | None = None, raise_on: set[str] | None = None):
        self.pages = pages or [{"markets": [], "cursor": ""}]
        self.raise_on = raise_on or set()
        self.lookup_table: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._scan_calls = 0

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, **kw: Any) -> Any:
        params = dict(params or {})
        self.calls.append((method, path, params))
        if "tickers" in params:
            chunk = params["tickers"].split(",")
            if self.raise_on & set(chunk):
                raise KalshiHTTPError(500, "simulated", "/markets")
            return {"markets": [self.lookup_table[t] for t in chunk if t in self.lookup_table],
                    "cursor": ""}
        idx = min(self._scan_calls, len(self.pages) - 1)
        self._scan_calls += 1
        return self.pages[idx]


def market(ticker: str, result: str = "yes", event: str | None = None, settled: str = "2026-11-21T06:00:00Z") -> dict[str, Any]:
    return {"ticker": ticker, "event_ticker": event or ticker.rsplit("-", 1)[0],
            "result": result, "settlement_ts": settled, "status": "settled",
            "settlement_value_dollars": "1.0000" if result == "yes" else "0.0000"}


class ScanSettledParameters(unittest.TestCase):
    def test_sends_documented_window_and_filters(self) -> None:
        client = FakeRequestClient()
        root.scan_settled(client, NOW)
        method, path, params = client.calls[0]
        self.assertEqual((method, path), ("GET", "/markets"))
        self.assertEqual(params["status"], "settled")
        self.assertEqual(params["min_settled_ts"], int(NOW - root.SETTLED_LOOKBACK_S))
        self.assertEqual(params["mve_filter"], "exclude")
        self.assertEqual(params["limit"], 1000)           # documented maximum
        self.assertIsNone(params["cursor"])                # first page has no cursor

    def test_window_is_two_hours_and_not_zero(self) -> None:
        # Runs happen every 5 minutes; the window must overlap consecutive runs.
        self.assertEqual(root.SETTLED_LOOKBACK_S, 7200)
        self.assertGreater(root.SETTLED_LOOKBACK_S, 5 * 60)


class ScanSettledPaging(unittest.TestCase):
    def test_follows_cursor_and_dedupes_tickers(self) -> None:
        pages = [
            {"markets": [market("KXA-1"), market("KXB-1")], "cursor": "c1"},
            {"markets": [market("KXB-1"), market("KXC-1")], "cursor": ""},
        ]
        client = FakeRequestClient(pages)
        rows, info = root.scan_settled(client, NOW)
        self.assertEqual([r["ticker"] for r in rows], ["KXA-1", "KXB-1", "KXC-1"])
        self.assertEqual(info["pages"], 2)
        self.assertFalse(info["truncated"])
        self.assertEqual(client.calls[1][2]["cursor"], "c1")

    def test_cap_stops_early_and_is_flagged_as_truncated(self) -> None:
        # A cursor that never ends: the cap must stop the read and say so.
        pages = [{"markets": [market(f"KXX-{i}")], "cursor": "more"} for i in range(5)]
        client = FakeRequestClient(pages)
        rows, info = root.scan_settled(client, NOW, cap=2000)
        self.assertEqual(info["pages"], 2)
        self.assertTrue(info["truncated"])
        self.assertEqual(info["cap"], 2000)
        self.assertEqual(len(rows), 2)

    def test_exact_end_on_last_allowed_page_is_not_truncated(self) -> None:
        client = FakeRequestClient([{"markets": [market("KXA-1")], "cursor": ""}])
        _, info = root.scan_settled(client, NOW, cap=1000)
        self.assertEqual(info["pages"], 1)
        self.assertFalse(info["truncated"])

    def test_default_cap_is_three_pages(self) -> None:
        self.assertEqual(root.SETTLED_DEFAULT_CAP // root.SETTLED_PAGE_SIZE, 3)


class WatchlistRules(unittest.TestCase):
    def test_seen_and_held_tickers_are_added_with_topic(self) -> None:
        watch: dict = {}
        size = root.update_watchlist(watch, {"KXA-1": "golf"}, {"KXHELD-1"}, NOW)
        self.assertEqual(size, 2)
        self.assertEqual(watch["KXA-1"]["topic"], "golf")
        self.assertIsNone(watch["KXHELD-1"]["topic"])

    def test_entries_not_seen_for_ttl_are_dropped(self) -> None:
        watch = {"KXOLD-1": {"topic": "golf", "last_seen": NOW - root.WATCH_TTL_S - 1, "last_checked": 0},
                 "KXNEW-1": {"topic": "golf", "last_seen": NOW - 60, "last_checked": 0}}
        root.update_watchlist(watch, {}, set(), NOW)
        self.assertEqual(sorted(watch), ["KXNEW-1"])

    def test_pick_checks_least_recently_checked_first(self) -> None:
        watch = {"KXA": {"last_checked": 500}, "KXB": {"last_checked": 100},
                 "KXC": {"last_checked": 0}}
        self.assertEqual(root.pick_watchlist(watch, 2), ["KXC", "KXB"])

    def test_pick_respects_the_per_run_bound(self) -> None:
        watch = {f"KXT-{i}": {"last_checked": i} for i in range(5000)}
        self.assertEqual(len(root.pick_watchlist(watch, root.WATCH_BATCH * root.WATCH_MAX_CALLS)),
                         root.WATCH_BATCH * root.WATCH_MAX_CALLS)


class HeldPositionLookup(unittest.TestCase):
    def test_uses_tickers_filter_in_batches(self) -> None:
        client = FakeRequestClient()
        tickers = [f"KXT-{i}" for i in range(120)]
        root.lookup_settled_tickers(client, tickers, batch=50)
        lookups = [c for c in client.calls if "tickers" in c[2]]
        self.assertEqual(len(lookups), 3)                    # 50 + 50 + 20
        self.assertEqual(lookups[0][2]["tickers"].split(","), tickers[:50])

    def test_returns_only_yes_or_no_results(self) -> None:
        client = FakeRequestClient()
        client.lookup_table = {
            "KXOPEN-1": {"ticker": "KXOPEN-1", "result": ""},            # still open: never graded
            "KXDONE-1": market("KXDONE-1", "no"),
            "KXDONE-2": market("KXDONE-2", "yes"),
        }
        rows, errors = root.lookup_settled_tickers(client, ["KXOPEN-1", "KXDONE-1", "KXDONE-2"])
        self.assertEqual(sorted(r["ticker"] for r in rows), ["KXDONE-1", "KXDONE-2"])
        self.assertEqual(errors, [])

    def test_failed_lookup_is_reported_not_silent(self) -> None:
        client = FakeRequestClient(raise_on={"KXBAD-1"})
        rows, errors = root.lookup_settled_tickers(client, ["KXBAD-1"])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("ticker lookup failed", errors[0])


class PerTopicFloor(unittest.TestCase):
    REGISTRY = {
        "KXBTCD": {"ticker": "KXBTCD", "topic": "crypto"},
        "KXDOGE": {"ticker": "KXDOGE", "topic": "crypto"},
        "KXAAAGASCDAK": {"ticker": "KXAAAGASCDAK", "topic": "gas-prices"},
        "KXCAGOVPRIMARY1ST": {"ticker": "KXCAGOVPRIMARY1ST", "topic": "elections"},
        "KXBIGBROTHER": {"ticker": "KXBIGBROTHER", "topic": "culture"},
        "KXDPWORLDTOUR": {"ticker": "KXDPWORLDTOUR", "topic": "golf"},
    }

    def _row(self, ticker: str, event: str, ts: int) -> dict[str, Any]:
        return {"ticker": ticker, "event_ticker": event, "topic": None, "result": "no",
                "settlement_ts": f"2026-11-21T{ts // 3600 % 24:02d}:{ts // 60 % 60:02d}:{ts % 60:02d}Z"}

    def test_busy_topic_cannot_evict_quiet_topics(self) -> None:
        store: dict[str, Any] = {"resolutions": {}, "meta": {}}
        # 2,500 very recent crypto rows (more than the old global 2,000 cap) ...
        for i in range(2500):
            t = f"KXBTCD-{i}"
            store["resolutions"][t] = self._row(t, f"KXBTCD-26NOV{i:04d}", 40000 + i)
        # ... and a handful of older rows in the other four topics.
        store["resolutions"]["KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC"] = self._row(
            "KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC", "KXCAGOVPRIMARY1ST-26JUN02-1ST", 100)
        store["resolutions"]["KXBIGBROTHER-26DEC31-RIC"] = self._row(
            "KXBIGBROTHER-26DEC31-RIC", "KXBIGBROTHER-26DEC31", 200)
        store["resolutions"]["KXDPWORLDTOUR-DPWTC26-THAT"] = self._row(
            "KXDPWORLDTOUR-DPWTC26-THAT", "KXDPWORLDTOUR-DPWTC26", 300)
        store["resolutions"]["KXAAAGASCDAK-26NOV20-LD"] = self._row(
            "KXAAAGASCDAK-26NOV20-LD", "KXAAAGASCDAK-26NOV20", 400)

        kept = root.migrate_resolutions(store, self.REGISTRY)
        rows = list(store["resolutions"].values())
        topics = {r["topic"] for r in rows}
        self.assertEqual(topics, {"crypto", "elections", "culture", "golf", "gas-prices"})
        # Every quiet topic keeps all of its rows (one each), even though they are older.
        for topic in ("elections", "culture", "golf", "gas-prices"):
            self.assertEqual(sum(1 for r in rows if r["topic"] == topic), 1, topic)
        # The bound is unchanged: the store still holds exactly MAX_RESOLUTIONS rows.
        self.assertEqual(kept, root.MAX_RESOLUTIONS)
        self.assertEqual(len(rows), root.MAX_RESOLUTIONS)
        # The busy topic keeps its newest rows, not an arbitrary subset.
        crypto_ids = sorted(int(r["ticker"].split("-")[1]) for r in rows if r["topic"] == "crypto")
        self.assertEqual(crypto_ids[-1], 2499)
        self.assertGreaterEqual(len(crypto_ids), root.RESOLUTION_TOPIC_FLOOR)

    def test_out_of_scope_rows_are_still_dropped(self) -> None:
        store: dict[str, Any] = {"resolutions": {
            "KXSOCCER-1": {"ticker": "KXSOCCER-1", "event_ticker": "KXSOCCER-26NOV20",
                           "topic": None, "result": "yes", "settlement_ts": "2026-11-21T01:00:00Z"},
        }}
        root.migrate_resolutions(store, self.REGISTRY)
        self.assertEqual(store["resolutions"], {})

    def test_empty_registry_keeps_store_unchanged(self) -> None:
        # Discovery failure must not wipe the store (existing contract).
        store: dict[str, Any] = {"resolutions": {"KXBTCD-1": self._row("KXBTCD-1", "KXBTCD-1", 1)}}
        root.migrate_resolutions(store, {})
        self.assertEqual(len(store["resolutions"]), 1)


class ClientRequestBuilder(unittest.TestCase):
    """Runs the real KalshiClient._request (URL building included) and stubs only the
    network call, urllib.request.urlopen."""

    def test_query_string_carries_documented_names(self) -> None:
        import io
        import json as _json
        from unittest import mock

        from collector import kalshi_api

        sent: list[str] = []

        class _Resp(io.BytesIO):
            headers: dict[str, str] = {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None, context=None):
            sent.append(req.full_url)
            return _Resp(_json.dumps({"markets": [], "cursor": ""}).encode("utf-8"))

        client = kalshi_api.KalshiClient(kalshi_api.DEMO_REST)
        with mock.patch.object(kalshi_api.urllib.request, "urlopen", fake_urlopen):
            root.scan_settled(client, NOW)
        self.assertEqual(len(sent), 1)
        url = sent[0]
        self.assertTrue(url.startswith(kalshi_api.DEMO_REST + "/markets?"), url)
        self.assertIn("status=settled", url)
        self.assertIn("mve_filter=exclude", url)
        self.assertIn("limit=1000", url)
        self.assertIn(f"min_settled_ts={int(NOW - root.SETTLED_LOOKBACK_S)}", url)
        self.assertNotIn("cursor=", url)


class CollectEndToEndOffline(unittest.TestCase):
    """Runs collector.collector.collect() from start to finish with no network: the
    client answers only the settled scan and the ``tickers`` lookup, discovery is given
    fixture series, and every file write is captured in memory (nothing under data/ changes)."""

    SERIES = {
        "elections": "KXCAGOVPRIMARY1ST",
        "golf": "KXDPWORLDTOUR",
        "gas-prices": "KXAAAGASCDAK",
        "crypto": "KXBTCD",
        "culture": "KXBIGBROTHER",
    }

    def test_quiet_topics_reach_the_store_and_held_position_is_graded(self) -> None:
        from unittest import mock

        from collector import topics as topic_mod
        from collector.kalshi_api import KalshiHTTPError

        series_by_topic = {t.slug: [{"ticker": self.SERIES[t.slug], "topic": t.slug,
                                     "title": t.slug, "source_url": "x"}]
                           for t in topic_mod.TOPICS}

        def mk(ticker: str, event: str, result: str) -> dict:
            return {"ticker": ticker, "event_ticker": event, "result": result,
                    "settlement_ts": "2026-11-21T06:00:00Z", "status": "settled",
                    "settlement_value_dollars": "1.0000" if result == "yes" else "0.0000",
                    "title": ticker}

        settled = [
            mk("KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC", "KXCAGOVPRIMARY1ST-26JUN02-1ST", "yes"),
            mk("KXBIGBROTHER-26DEC31-RIC", "KXBIGBROTHER-26DEC31", "yes"),
            mk("KXDPWORLDTOUR-DPWTC26-THAT", "KXDPWORLDTOUR-DPWTC26", "yes"),
            mk("KXSOCCERX-1", "KXSOCCERX-26NOV20", "yes"),          # out of scope
        ]
        # 2,600 crypto settlements, newer than the quiet topics (the old failure mode).
        settled += [mk(f"KXBTCD-26NOV{i:04d}-{i}", f"KXBTCD-26NOV{i:04d}", "no") for i in range(2600)]
        held_result = {"KXHELD-1": mk("KXHELD-1", "KXDPWORLDTOUR-HELD", "yes"),      # in-scope golf
                       # watched elections market that the exchange window does NOT return
                       "KXCAGOVPRIMARY1ST-26JUN02-2ND-WATCH": mk(
                           "KXCAGOVPRIMARY1ST-26JUN02-2ND-WATCH", "KXCAGOVPRIMARY1ST-26JUN02-2ND", "no")}

        class FakeClient:
            budget = None

            def __init__(self) -> None:
                self.params: list[dict] = []

            def _request(self, method, path, params=None, **kw):
                params = dict(params or {})
                self.params.append(params)
                if "tickers" in params:
                    return {"markets": [held_result[t] for t in params["tickers"].split(",")
                                        if t in held_result], "cursor": ""}
                start = int(params.get("cursor") or 0)
                nxt = str(start + 1000) if start + 1000 < len(settled) else ""
                return {"markets": settled[start:start + 1000], "cursor": nxt}

            def __getattr__(self, name):
                def offline(*a, **k):
                    raise KalshiHTTPError(0, "offline (unit test)", name)
                return offline

        fake = FakeClient()
        captured: dict[str, object] = {}
        watched = {"KXCAGOVPRIMARY1ST-26JUN02-2ND-WATCH": {"topic": "elections", "last_seen": NOW - 60,
                                                          "last_checked": 0}}
        held_state = {"bankroll": 10000.0, "starting_bankroll": 10000.0, "trades": [],
                      "equity_curve": [], "started_at": 1795189000.0,
                      "positions": [{
                          "position_id": "pos-test-held-1", "ticker": "KXHELD-1",
                          "event_ticker": "KXHELD", "topic": "golf", "title": "held",
                          "strategy": "value", "side": "yes", "contracts": 10.0,
                          "entry_price": 0.40, "entry_ts": 1795189980.0, "entry_fee": 0.1,
                          "status": "open", "bankroll_at_entry": 10000.0}]}

        def load(path, default):
            if str(path).endswith("portfolio_state.json"):
                return held_state
            if str(path).endswith("resolutions.json"):
                return {"resolutions": {}, "meta": {}, "watch": dict(watched)}
            return default

        with mock.patch.object(root, "KalshiClient", lambda *a, **k: fake), \
                mock.patch.object(root, "load_json", load), \
                mock.patch.object(root, "save_json", lambda p, payload: captured.__setitem__(p, payload)), \
                mock.patch.object(topic_mod, "cached_series",
                                  lambda client, topic, cache, max_age_seconds=0: series_by_topic[topic.slug]):
            payload = root.collect(market_cap=5, orderbook_cap=0, settle_scan=10000, budget_seconds=60)

        store = captured[root.RESOLUTIONS_PATH]["resolutions"]
        by_topic = {}
        for rec in store.values():
            by_topic[rec["topic"]] = by_topic.get(rec["topic"], 0) + 1
        self.assertEqual(by_topic.get("elections"), 2)   # window row + watched row (quiet topic kept)
        self.assertTrue("KXCAGOVPRIMARY1ST-26JUN02-2ND-WATCH" in store)   # found only by ticker
        self.assertEqual(by_topic.get("culture"), 1)
        self.assertEqual(by_topic.get("golf"), 2)        # DPWTC26-THAT and the held KXDPWORLDTOUR-HELD market
        self.assertEqual(by_topic.get("gas-prices"), None)
        self.assertFalse("KXSOCCERX-1" in store)          # out of scope: never stored
        self.assertLessEqual(len(store), root.MAX_RESOLUTIONS)
        self.assertTrue("KXHELD-1" in store)              # held position's settlement recorded
        graded = [c["ticker"] for c in payload["settled_this_run"]]
        self.assertTrue("KXHELD-1" in graded)             # and the simulated position is graded
        scan = captured[root.RESOLUTIONS_PATH]["meta"]["settled_scan"]
        self.assertEqual(scan["watch_resolved"], 2)       # KXHELD-1 and the watched elections market
        self.assertFalse("KXCAGOVPRIMARY1ST-26JUN02-2ND-WATCH" in captured[root.RESOLUTIONS_PATH]["watch"])
        self.assertEqual(scan["pages"], 3)                 # 2,604 markets / 1,000 per page (cap = 3 pages)
        self.assertFalse(scan["truncated"])
        self.assertEqual(scan["watch_checked"], 2)         # the held position and the watched market
        # The request that went out carried the documented window and filters.
        first = fake.params[0]
        self.assertEqual(first["status"], "settled")
        self.assertEqual(first["mve_filter"], "exclude")


if __name__ == "__main__":
    unittest.main()
