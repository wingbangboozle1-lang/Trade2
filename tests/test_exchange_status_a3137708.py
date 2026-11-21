"""Regression tests for the exchange-status summary (session arena-a3137708).

Why these exist: ``run_meta.json`` is the audit trail that says *what the demo
exchange told us*, and it was reading two fields -- ``exchange_status`` and
``exchange_indexes`` -- that are not part of the documented response. Every run
therefore published ``status: null, indexes: 0`` next to a raw response in
``data/live.json`` that said the exchange was active and trading.

Official field list: https://docs.kalshi.com/api-reference/exchange/get-exchange-status
(``exchange_active``, ``trading_active``, ``intra_exchange_transfers_active``,
``exchange_estimated_resume_time``, ``exchange_index_statuses[]``).
"""

from __future__ import annotations

import json
import os
import unittest

from collector.runner import EXCHANGE_STATUS_DOC, summarize_exchange_status

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "data", "live.json")

DOCUMENTED_RESPONSE = {
    "exchange_active": True,
    "trading_active": True,
    "intra_exchange_transfers_active": True,
    "exchange_estimated_resume_time": "2023-11-07T05:31:56Z",
    "exchange_index_statuses": [
        {"exchange_index": 0, "description": "Default", "exchange_active": True,
         "trading_active": True, "intra_exchange_transfers_active": True},
        {"exchange_index": 1, "description": "Demo shard 1", "exchange_active": True,
         "trading_active": True, "intra_exchange_transfers_active": True},
    ],
}


class SummarizeExchangeStatus(unittest.TestCase):
    def test_projects_documented_fields(self) -> None:
        out = summarize_exchange_status(DOCUMENTED_RESPONSE)
        self.assertIs(out["exchange_active"], True)
        self.assertIs(out["trading_active"], True)
        self.assertIs(out["intra_exchange_transfers_active"], True)
        self.assertEqual(out["estimated_resume_time"], "2023-11-07T05:31:56Z")
        self.assertEqual(out["indexes"], 2)
        self.assertEqual(out["index_statuses"][1]["description"], "Demo shard 1")
        # every summary row carries the source a reviewer can click
        self.assertEqual(out["source_url"], EXCHANGE_STATUS_DOC)

    def test_absent_fields_stay_unknown_never_false(self) -> None:
        """Missing != off. Coercing would publish a claim the API did not make."""
        out = summarize_exchange_status({})
        self.assertIsNone(out["trading_active"])
        self.assertIsNone(out["exchange_active"])
        self.assertIsNone(out["intra_exchange_transfers_active"])
        self.assertEqual(out["indexes"], 0)
        self.assertEqual(out["index_statuses"], [])

    def test_error_passthrough_keeps_flags_unknown(self) -> None:
        out = summarize_exchange_status({"error": "HTTP 503"})
        self.assertEqual(out["error"], "HTTP 503")
        self.assertIsNone(out["trading_active"])

    def test_documented_shape_and_captured_response_agree(self) -> None:
        """The live demo capture must summarize the same way the docs sample does."""
        if not os.path.exists(LIVE):
            self.skipTest("data/live.json not present in this checkout")
        raw = json.load(open(LIVE, encoding="utf-8")).get("exchange") or {}
        out = summarize_exchange_status(raw)
        self.assertNotIn("error", out)
        self.assertGreaterEqual(out["indexes"], 1)
        # trading_active must be a real boolean taken from the response, not a
        # leftover of the old always-null path
        self.assertIsInstance(out["trading_active"], bool)
        self.assertIs(out["trading_active"], bool(raw.get("trading_active")))


class NoUndocumentedKeys(unittest.TestCase):
    def test_runner_no_longer_reads_invented_field_names(self) -> None:
        src = open(os.path.join(REPO, "collector", "runner.py"), encoding="utf-8").read()
        for bad in ('get("exchange_status")', 'get("exchange_indexes")'):
            self.assertNotIn(bad, src, f"runner.py still reads undocumented field {bad}")

    def test_site_does_not_assert_not_trading_without_the_field(self) -> None:
        src = open(os.path.join(REPO, "site_build", "build.py"), encoding="utf-8").read()
        self.assertIn('"trading_active" in exchange', src)
        self.assertIn("unknown (trading_active not returned)", src)


if __name__ == "__main__":
    unittest.main()
