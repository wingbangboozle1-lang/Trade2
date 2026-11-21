"""R-E1-01 — the published row keeps the status word the API actually used.

The `GET /markets` **filter** vocabulary (`unopened | open | paused | closed |
settled`) is not the vocabulary of the **`status` field on a market object**
(`initialized | inactive | active | closed | determined | disputed | amended |
finalized`) — see https://docs.kalshi.com/api-reference/market/get-markets.

That is verifiable in the demo API's own answers, and it was re-verified on
2026-11-21 at 06:5xZ:

    GET /markets?status=open&limit=1        ->  "status": "active"
    GET /markets/KXPGATOUR-THRC26-MTHO      ->  "status": "active"
    GET /markets/KXAAAGASCDAK-26NOV20-LD    ->  "status": "finalized", "result": "yes"

`collector/runner.py` maps the response's `"active"` to the filter word `"open"`
so every reader of `docs/data/markets.json` keeps working. Mapping is a
translation, and a translated value is not something a reviewer can find at the
URL the row links to — so the row now carries **both**: `status` (the mapped
word, unchanged behaviour) and `api_status` (verbatim). Anything other than the
one documented equivalence is passed through untouched: a `determined` market is
never quietly renamed.

Run: python3 -m unittest -v tests.test_status_verbatim_d6a0282d
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.runner import market_row

SRC = "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXTEST-1"


def market(**over):
    m = {
        "ticker": "KXTEST-1", "event_ticker": "KXTEST", "title": "Test market",
        "status": "active", "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4200",
        "last_price_dollars": "0.4100", "volume_fp": "1000.00",
        "volume_24h_fp": "10.00", "open_interest_fp": "500.00",
        "expected_expiration_time": "2026-11-22T00:00:00Z",
    }
    m.update(over)
    return m


class StatusIsPublishedVerbatim(unittest.TestCase):
    def test_active_is_still_mapped_for_existing_readers(self):
        row = market_row(market(), SRC)
        self.assertEqual(row["status"], "open",
                         "the mapped word stays: readers filter on it")

    def test_the_response_word_is_kept_alongside_it(self):
        row = market_row(market(), SRC)
        self.assertEqual(row["api_status"], "active")

    def test_no_other_status_is_translated(self):
        """Only the one documented equivalence is applied. Everything else is
        copied, so a settled or disputed market cannot be relabelled."""
        for value in ("finalized", "determined", "closed", "paused",
                      "initialized", "inactive", "disputed", "amended",
                      "settled", "open"):
            with self.subTest(status=value):
                row = market_row(market(status=value), SRC)
                self.assertEqual(row["api_status"], value)
                self.assertEqual(row["status"], "open" if value == "active" else value)

    def test_missing_status_stays_missing(self):
        """Absent is not 'open'. Nothing is filled in when the API is silent."""
        row = market_row(market(status=None), SRC)
        self.assertIsNone(row["api_status"])
        self.assertIsNone(row["status"])

    def test_the_docs_browser_path_carries_the_same_field(self):
        """``docs/assets/app.js`` builds live rows in the browser from the raw
        response; if it stopped copying the verbatim value the two row shapes
        would disagree, which is the failure mode this whole file is about."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "docs", "assets", "app.js")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("api_status: raw.status", src)
        self.assertIn("https://docs.kalshi.com/api-reference/market/get-markets", src)

    def test_the_derived_dollar_column_says_it_is_derived(self):
        """F-12 claims the derived volume figure is labelled as derived. The
        docs table header is one of the pages that has to honour that."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "docs", "assets", "app.js")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("$ volume (derived)", src)
        self.assertIn("The API publishes no traded-dollar figure", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
