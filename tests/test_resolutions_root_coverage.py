"""Root pipeline resolution coverage (claim T-BB-1, closes R-3DCF-1).

Defect on main @ 8d15b95: the exchange-wide settled scan is newest-first, so
data/resolutions.json held only gas-prices and crypto rows (gas 268, crypto 60; elections,
culture and golf = 0). Fixed by a rotating per-series settled scan (documented
``series_ticker`` and ``min_settled_ts`` filters) and a balanced store trim.

Sources (official):
  https://docs.kalshi.com/api-reference/market/get-markets
  https://docs.kalshi.com/getting_started/market_settlement

Run: python3 -m unittest tests.test_resolutions_root_coverage -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import collector as C
from collector.kalshi_api import KalshiHTTPError


class FakeClient:
    def __init__(self, fail_on=None):
        self.calls: list[dict] = []
        self.fail_on = set(fail_on or [])

    def markets(self, status=None, series_ticker=None, min_settled_ts=None, limit=None,
                max_pages=None, **_):
        self.calls.append({"status": status, "series_ticker": series_ticker,
                           "min_settled_ts": min_settled_ts, "limit": limit,
                           "max_pages": max_pages})
        if series_ticker in self.fail_on:
            raise KalshiHTTPError(500, "boom", "/markets")
        return [{"ticker": f"{series_ticker}-26NOV20-A", "result": "yes",
                 "event_ticker": f"{series_ticker}-26NOV20", "settlement_ts": "2026-11-20T10:00:00Z"}]


def _registry(counts: dict[str, int]) -> dict[str, dict]:
    reg: dict[str, dict] = {}
    for topic, n in counts.items():
        for i in range(n):
            ticker = f"{topic[:3].upper()}SER{i:03d}"
            reg[ticker] = {"ticker": ticker, "topic": topic}
    return reg


class TestSeriesScan(unittest.TestCase):
    def test_uses_documented_filters_and_single_page(self):
        client = FakeClient()
        now = 1_800_000_000.0
        reg = _registry({"golf": 3, "elections": 3})
        out = C.scan_settled_by_series(client, reg, now, [], deadline=now + 60)
        self.assertTrue(client.calls)
        for call in client.calls:
            self.assertEqual(call["status"], "settled")
            self.assertEqual(call["max_pages"], 1)
            self.assertEqual(call["limit"], C.RESOLUTION_PAGE_LIMIT)
            self.assertEqual(call["min_settled_ts"], int(now - C.RESOLUTION_LOOKBACK_S))
        topics = {slug for _, slug in out}
        self.assertEqual(topics, {"golf", "elections"})

    def test_request_count_is_bounded_per_run(self):
        client = FakeClient()
        reg = _registry({"golf": 200, "elections": 200, "culture": 200,
                         "crypto": 200, "gas-prices": 200})
        C.scan_settled_by_series(client, reg, 1_800_000_000.0, [], deadline=1e18)
        self.assertLessEqual(len(client.calls),
                             C.RESOLUTION_SERIES_PER_RUN // 5 * 5)

    def test_rotation_visits_every_series_over_its_windows(self):
        reg = _registry({"golf": 50, "culture": 40})
        seen: set[str] = set()
        per_cap = C.RESOLUTION_SERIES_PER_RUN // 2
        windows = -(-50 // per_cap)  # ceil for the larger topic
        base = 1_800_000_000.0
        for w in range(windows + 1):
            client = FakeClient()
            C.scan_settled_by_series(client, reg, base + w * C.RESOLUTION_WINDOW_S, [],
                                     deadline=1e18)
            seen |= {c["series_ticker"] for c in client.calls}
        golf = {t for t, r in reg.items() if r["topic"] == "golf"}
        culture = {t for t, r in reg.items() if r["topic"] == "culture"}
        self.assertTrue(golf <= seen)
        self.assertTrue(culture <= seen)

    def test_http_failure_is_recorded_and_scan_continues(self):
        reg = _registry({"golf": 2})
        bad = sorted(t for t, r in reg.items() if r["topic"] == "golf")[0]
        errors: list[str] = []
        client = FakeClient(fail_on=[bad])
        out = C.scan_settled_by_series(client, reg, 1_800_000_000.0, errors, deadline=1e18)
        self.assertEqual(len(errors), 1)
        self.assertIn(bad, errors[0])
        self.assertEqual(len(out), 1)

    def test_deadline_stops_the_scan_and_says_so(self):
        reg = _registry({"golf": 10})
        errors: list[str] = []
        client = FakeClient()
        C.scan_settled_by_series(client, reg, 1_800_000_000.0, errors, deadline=0.0)
        self.assertEqual(client.calls, [])
        self.assertTrue(errors and "partial" in errors[0])


class TestBalancedTrim(unittest.TestCase):
    def _store(self, topic: str, n: int, day0: int = 1) -> dict:
        return {f"{topic}-{i}": {"ticker": f"{topic}-{i}", "topic": topic,
                                 "settlement_ts": f"2026-11-{day0:02d}T{i:05d}Z"}
                for i in range(n)}

    def test_single_topic_keeps_newest_limit(self):
        recs = self._store("gas-prices", C.MAX_RESOLUTIONS + 25)
        kept = C.balanced_trim(recs, C.MAX_RESOLUTIONS)
        self.assertEqual(len(kept), C.MAX_RESOLUTIONS)
        self.assertIn(f"gas-prices-{C.MAX_RESOLUTIONS + 24}", kept)
        self.assertNotIn("gas-prices-0", kept)

    def test_large_topic_cannot_evict_small_topics(self):
        recs = {}
        recs.update(self._store("gas-prices", 1950, day0=20))  # 2040 total: forces a trim
        recs.update(self._store("golf", 60, day0=5))
        recs.update(self._store("elections", 30, day0=5))
        kept = C.balanced_trim(recs, 2000)
        topics = [r["topic"] for r in kept.values()]
        self.assertEqual(topics.count("golf"), 60)
        self.assertEqual(topics.count("elections"), 30)
        self.assertEqual(len(kept), 2000)
        self.assertEqual(topics.count("gas-prices"), 1910)

    def test_never_exceeds_limit_and_keeps_newest_within_topic(self):
        recs = {}
        recs.update(self._store("gas-prices", 300, day0=20))
        recs.update(self._store("crypto", 300, day0=20))
        recs.update(self._store("golf", 7, day0=3))
        kept = C.balanced_trim(recs, 400)
        self.assertLessEqual(len(kept), 400)
        for topic in ("gas-prices", "crypto"):
            subset = sorted((r["settlement_ts"] for r in kept.values() if r["topic"] == topic),
                            reverse=True)
            if subset:
                self.assertEqual(subset[0], max(r["settlement_ts"] for r in recs.values()
                                                if r["topic"] == topic))

    def test_migrate_applies_balanced_trim_to_store(self):
        store = {"resolutions": {}}
        store["resolutions"].update(self._store("gas-prices", C.MAX_RESOLUTIONS, day0=25))
        store["resolutions"].update({
            "KXPGATOUR-26NOV20-X": {"ticker": "KXPGATOUR-26NOV20-X", "topic": "golf",
                                     "event_ticker": "KXPGATOUR-26NOV20",
                                     "settlement_ts": "2026-11-01T00:00:00Z"}})
        reg = {"KXPGATOUR": {"topic": "golf"}, "AAAGASD": {"topic": "gas-prices"}}
        C.migrate_resolutions(store, reg)
        self.assertLessEqual(len(store["resolutions"]), C.MAX_RESOLUTIONS)
        self.assertIn("KXPGATOUR-26NOV20-X", store["resolutions"])


if __name__ == "__main__":
    unittest.main()
