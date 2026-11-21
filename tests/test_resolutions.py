"""Resolution-topic classification and store migration.

Regression for the defect found on main @ 58be24d: every record in
data/resolutions.json carried ``series_ticker: null`` (Kalshi market objects
have no such field — the same live finding session c0205283 logged), the
topic lookup keyed on it, and every per-topic YES/NO list on the root site
rendered empty while the stat card claimed 2 000 resolutions.

Fixture tickers are real Kalshi demo tickers observed in the committed
resolutions store on 2026-11-20 (sources: the records' own source_url fields,
https://external-api.demo.kalshi.co/trade-api/v2/markets/<ticker>).

Run: python3 -m unittest tests.test_resolutions -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.collector import (MAX_RESOLUTIONS, migrate_resolutions,
                                 resolution_topic)

REGISTRY = {
    "AAAGASD": {"topic": "gas-prices"},
    "AAAGAS": {"topic": "gas-prices"},
    "GAS-MONTH": {"topic": "gas-prices"},
    "KXPRESNOMD": {"topic": "elections"},
    "KXPRESNOMR": {"topic": "elections"},
    "KXBTCY": {"topic": "crypto"},
    "KXPGATOUR": {"topic": "golf"},
}


class TestResolutionTopic(unittest.TestCase):
    def test_event_with_kx_prefixed_series(self):
        # Real record: KXAAAGASD-26NOV20-3.7600 settled "no", series AAAGASD.
        self.assertEqual(
            resolution_topic("KXAAAGASD-26NOV20-3.7600", REGISTRY), "gas-prices")

    def test_event_ticker_without_market_suffix(self):
        self.assertEqual(
            resolution_topic("KXAAAGASD-26NOV20", REGISTRY), "gas-prices")

    def test_series_already_kx_prefixed(self):
        self.assertEqual(
            resolution_topic("KXPRESNOMD-28-RW", REGISTRY), "elections")
        self.assertEqual(
            resolution_topic("KXBTCY-27JAN0100-B127500", REGISTRY), "crypto")
        self.assertEqual(
            resolution_topic("KXPGATOUR-MAST27-HENG", REGISTRY), "golf")

    def test_series_without_kx_prefix(self):
        self.assertEqual(
            resolution_topic("AAAGASD-26NOV20", REGISTRY), "gas-prices")

    def test_dashed_series_is_matched_whole(self):
        # KX + GAS-MONTH: the KX-stripped head must be the whole dashed
        # series name, never its first fragment.
        self.assertEqual(
            resolution_topic("KXGAS-MONTH-26NOV20", REGISTRY), "gas-prices")

    def test_sibling_series_never_swallowed(self):
        # AAAGAS is in the registry; AAAGASMAX is not. Delimiter-anchored
        # heads must not let the shorter series claim the longer one's events.
        self.assertIsNone(resolution_topic("KXAAAGASMAX-27", REGISTRY))

    def test_out_of_scope_markets_return_none(self):
        # Real out-of-scope tickers from the committed store (soccer,
        # quicksettle) — these must not occupy the five topics' lists.
        self.assertIsNone(resolution_topic("KXESOCCERGAME-26NOV20-X", REGISTRY))
        self.assertIsNone(resolution_topic("KXQUICKSETTLE-1", REGISTRY))

    def test_empty_inputs_are_none(self):
        self.assertIsNone(resolution_topic(None, REGISTRY))
        self.assertIsNone(resolution_topic("", REGISTRY))
        self.assertIsNone(resolution_topic("KXAAAGASD-1", {}))

    def test_memo_caches_repeated_tickers(self):
        memo = {}
        first = resolution_topic("KXAAAGASD-26NOV20-3.7600", REGISTRY, memo)
        self.assertEqual(first, "gas-prices")
        self.assertIn("KXAAAGASD-26NOV20-3.7600", memo)
        # Corrupting the registry must not change a memoised answer.
        self.assertEqual(
            resolution_topic("KXAAAGASD-26NOV20-3.7600", {}, memo), "gas-prices")


class TestMigrateResolutions(unittest.TestCase):
    def _store(self):
        return {"resolutions": {
            "KXAAAGASD-26NOV20-3.7600": {
                "ticker": "KXAAAGASD-26NOV20-3.7600",
                "event_ticker": "KXAAAGASD-26NOV20",
                "series_ticker": None,          # exactly what the API returns
                "result": "no",
                "settlement_ts": "2026-11-20T13:14:49Z",
            },
            "KXPRESNOMD-28-RW-YES": {
                "ticker": "KXPRESNOMD-28-RW-YES",
                "event_ticker": "KXPRESNOMD-28",
                "series_ticker": None,
                "result": "yes",
                "settlement_ts": "2026-11-19T08:00:00Z",
            },
            "KXESOCCERGAME-26NOV20-1": {
                "ticker": "KXESOCCERGAME-26NOV20-1",
                "event_ticker": "KXESOCCERGAME-26NOV20",
                "series_ticker": None,
                "result": "yes",
                "settlement_ts": "2026-11-20T18:00:00Z",  # newest, but out of scope
            },
        }}

    def test_keeps_in_scope_drops_out_of_scope_and_tags_topic(self):
        store = self._store()
        kept = migrate_resolutions(store, REGISTRY)
        self.assertEqual(kept, 2)
        res = store["resolutions"]
        self.assertNotIn("KXESOCCERGAME-26NOV20-1", res)
        self.assertEqual(res["KXAAAGASD-26NOV20-3.7600"]["topic"], "gas-prices")
        self.assertEqual(res["KXPRESNOMD-28-RW-YES"]["topic"], "elections")

    def test_empty_registry_never_wipes_the_store(self):
        # A failed discovery run must not classify everything as out of scope
        # and erase the YES/NO history.
        store = self._store()
        kept = migrate_resolutions(store, {})
        self.assertEqual(kept, 3)
        self.assertEqual(len(store["resolutions"]), 3)

    def test_store_is_bounded_to_max_resolutions(self):
        store = {"resolutions": {}}
        for i in range(MAX_RESOLUTIONS + 25):
            store["resolutions"][f"KXAAAGASD-26NOV20-{i}"] = {
                "ticker": f"KXAAAGASD-26NOV20-{i}",
                "event_ticker": "KXAAAGASD-26NOV20",
                "result": "no",
                "settlement_ts": f"2026-11-20T{i:05d}Z",
            }
        kept = migrate_resolutions(store, REGISTRY)
        self.assertEqual(kept, MAX_RESOLUTIONS)
        # Newest settlement timestamps survive.
        newest = max(store["resolutions"],
                     key=lambda t: store["resolutions"][t]["settlement_ts"])
        self.assertEqual(newest, f"KXAAAGASD-26NOV20-{MAX_RESOLUTIONS + 24}")

    def test_non_dict_records_are_dropped(self):
        store = {"resolutions": {"bad": "not-a-record", "good": {
            "ticker": "good", "event_ticker": "KXAAAGASD-1", "result": "yes"}}}
        migrate_resolutions(store, REGISTRY)
        self.assertEqual(list(store["resolutions"]), ["good"])


if __name__ == "__main__":
    unittest.main()
