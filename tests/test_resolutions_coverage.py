"""Regression tests for resolution coverage in the docs/ collector (session arena-3dcf3f13, X1).

Symptom found on 2026-11-21 in the published snapshot docs/data/resolutions.json:
300 rows, all topic=crypto, all result=no, newest 3 hours only. Zero rows for
gas-prices, elections, culture or golf, although the live demo API returns settled
`yes` outcomes in golf (KXDPWORLDTOUR-DPWTC26-THAT), culture (KXBIGBROTHER-26DEC31-RIC)
and elections (KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC). Causes, all in
collector/runner.py::collect_resolutions:

1. the same first-N series per topic were scanned every run (no rotation);
2. the global newest-300 cut let the busiest topic fill the file;
3. outcomes were overwritten each run instead of accumulated.

These tests use an offline fake client. They exercise the real selection, merge and
retention code. The client pass-through test exercises KalshiClient.markets() with its
real request builder (only the HTTP method is stubbed).

Source for the query parameters used: https://docs.kalshi.com/api-reference/market/get-markets
(min_settled_ts: "Filter items that settled after this Unix timestamp").
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import runner  # noqa: E402
from collector.kalshi import KalshiClient  # noqa: E402

NOW = 1795243800.0  # 2026-11-21T06:50:00Z


def series_map(per_topic: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for topic, tickers in per_topic.items():
        for t in tickers:
            out[t] = {"ticker": t, "topic": topic}
    return out


class FakeClient:
    """Stands in for KalshiClient.markets(): returns canned settled markets per series."""

    def __init__(self, settled: Dict[str, List[Dict[str, Any]]], budget=None):
        self.settled = settled
        self.budget = budget
        self.calls: List[Dict[str, Any]] = []

    def markets(self, status=None, series_ticker=None, min_settled_ts=None, limit=None, max_pages=None, **kw):
        self.calls.append({"status": status, "series_ticker": series_ticker,
                           "min_settled_ts": min_settled_ts, "limit": limit, "max_pages": max_pages})
        if self.budget is not None:
            self.budget -= 1
        return list(self.settled.get(series_ticker, []))


def market(ticker: str, result: str, ts: str, event: str = "EVT") -> Dict[str, Any]:
    return {"ticker": ticker, "event_ticker": event, "title": ticker, "result": result,
            "settlement_ts": ts, "settlement_value_dollars": "1.0000" if result == "yes" else "0.0000",
            "volume_fp": "10.00"}


class ResolutionCoverageTests(unittest.TestCase):

    def test_every_topic_is_scanned_and_yes_outcomes_survive(self):
        per_topic = {
            "crypto": ["KXDOGE", "KXDOGED"],
            "golf": ["KXDPWORLDTOUR", "KXPGATOUR"],
            "culture": ["KXBIGBROTHER"],
            "elections": ["KXCAGOVPRIMARY1ST"],
            "gas-prices": ["KXAAAGASD"],
        }
        settled = {
            "KXDOGE": [market("KXDOGE-A", "no", "2026-11-21T06:03:37Z")],
            "KXDPWORLDTOUR": [market("KXDPWORLDTOUR-DPWTC26-THAT", "yes", "2026-11-15T14:56:17Z")],
            "KXBIGBROTHER": [market("KXBIGBROTHER-26DEC31-RIC", "yes", "2026-10-02T04:20:30Z")],
            "KXCAGOVPRIMARY1ST": [market("KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC", "yes", "2026-07-11T00:45:14Z")],
            "KXAAAGASD": [market("KXAAAGASD-26NOV20-3.7600", "no", "2026-11-20T13:14:49Z")],
        }
        client = FakeClient(settled)
        meta = {"errors": []}
        rows = runner.collect_resolutions(client, series_map(per_topic), meta, max_series=24, now_ts=NOW)
        topics = {r["topic"] for r in rows}
        self.assertEqual(topics, set(per_topic), "all five topics must appear")
        results = {r["result"] for r in rows}
        self.assertEqual(results, {"yes", "no"}, "yes outcomes must not be dropped")
        self.assertEqual(meta["errors"], [])

    def test_rotation_visits_every_series_within_its_window_cycle(self):
        tickers = [f"KXGOLF{i:02d}" for i in range(12)]
        smap = series_map({"golf": tickers, "crypto": ["KXC"]})
        seen = set()
        for window in range(3):  # 12 golf series; max_series=8 over 2 topics -> per_cap 4 -> 3 windows
            client = FakeClient({})
            runner.collect_resolutions(client, smap, {"errors": []}, max_series=8,
                                       now_ts=window * runner.RESOLUTION_WINDOW_S + 1)
            seen |= {c["series_ticker"] for c in client.calls if c["series_ticker"].startswith("KXGOLF")}
        self.assertEqual(seen, set(tickers), "rotation must cover all tracked golf series in 3 windows")

    def test_scan_uses_documented_settlement_lookback(self):
        smap = series_map({"golf": ["KXPGATOUR"]})
        client = FakeClient({})
        runner.collect_resolutions(client, smap, {"errors": []}, max_series=24, now_ts=NOW)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["status"], "settled")
        self.assertEqual(call["min_settled_ts"], int(NOW - runner.RESOLUTION_LOOKBACK_S))

    def test_prior_rows_accumulate_and_newest_wins_per_topic_cap(self):
        prior = [{"ticker": f"KXDOGE-OLD{i:03d}", "topic": "crypto", "result": "no",
                  "settlement_ts": f"2026-11-20T{i % 24:02d}:00:00Z"} for i in range(100)]
        prior.append({"ticker": "KXPGATOUR-OLD", "topic": "golf", "result": "yes",
                      "settlement_ts": "2026-11-01T00:00:00Z"})
        smap = series_map({"crypto": ["KXDOGE"], "golf": ["KXPGATOUR"]})
        client = FakeClient({"KXDOGE": [market("KXDOGE-NEW", "no", "2026-11-21T06:03:37Z")]})
        rows = runner.collect_resolutions(client, smap, {"errors": []}, max_series=24,
                                          prior_rows=prior, now_ts=NOW)
        crypto = [r for r in rows if r["topic"] == "crypto"]
        golf = [r for r in rows if r["topic"] == "golf"]
        self.assertEqual(len(crypto), runner.RESOLUTION_KEEP_PER_TOPIC)
        self.assertEqual(crypto[0]["ticker"], "KXDOGE-NEW", "newest settlement first")
        self.assertEqual([r["ticker"] for r in golf], ["KXPGATOUR-OLD"], "prior golf outcome kept")

    def test_budget_exhaustion_is_flagged_and_prior_rows_still_kept(self):
        prior = [{"ticker": "KXPGATOUR-OLD", "topic": "golf", "result": "yes",
                  "settlement_ts": "2026-11-01T00:00:00Z"}]
        smap = series_map({"golf": ["KXPGATOUR"], "crypto": ["KXDOGE"]})
        client = FakeClient({}, budget=0)
        meta = {"errors": []}
        rows = runner.collect_resolutions(client, smap, meta, max_series=24, prior_rows=prior, now_ts=NOW)
        self.assertTrue(any("budget exhausted" in e["error"] for e in meta["errors"]))
        self.assertEqual([r["ticker"] for r in rows], ["KXPGATOUR-OLD"])

    def test_rows_without_a_final_yes_or_no_are_skipped(self):
        smap = series_map({"golf": ["KXPGATOUR"]})
        client = FakeClient({"KXPGATOUR": [market("KXPGATOUR-X", "", "2026-11-20T00:00:00Z"),
                                           market("KXPGATOUR-Y", "void", "2026-11-20T00:00:00Z")]})
        rows = runner.collect_resolutions(client, smap, {"errors": []}, max_series=24, now_ts=NOW)
        self.assertEqual(rows, [])


class ClientPassThroughTests(unittest.TestCase):

    def test_markets_sends_min_settled_ts_as_a_query_parameter(self):
        captured: List[Dict[str, Any]] = []

        class Stub(KalshiClient):
            def get(self, path, **params):
                captured.append({"path": path, **params})
                return {"markets": [], "cursor": ""}

        Stub().markets(status="settled", series_ticker="KXPGATOUR", min_settled_ts=1792651800,
                       limit=200, max_pages=2)
        self.assertEqual(captured[0]["path"], "/markets")
        self.assertEqual(captured[0]["min_settled_ts"], 1792651800)
        self.assertIsNone(captured[0]["max_settled_ts"], "unset filters must be left out of the request")


if __name__ == "__main__":
    unittest.main()
