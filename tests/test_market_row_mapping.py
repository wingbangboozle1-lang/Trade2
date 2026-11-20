"""`docs/` market-row mapping: published values come from real response fields.

Two rules, both from the project's own verification contract — "if a value can't
be confirmed from an official source, leave it blank and flag it; never infer or
fill in values":

1. The expiration column must read the key the API actually returns. The demo
   API's market object carries `expected_expiration_time` (ISO string) and has
   no `expected_expiration_ts` — checked 2026-11-20 against six live
   `GET /markets/{ticker}` responses (KXBTCY-27JAN0100-B127500,
   KXPGATOUR-THRC26-TMOO, KXPRESNOMD-28-RW, KXAAAGASM-26NOV30-4.70,
   KXCRITICSFOREIGN-27-LAB, KXXRP15M-26NOV200900-00), and against the response
   schema at https://docs.kalshi.com/api-reference/market/get-markets.md.
   Reading the wrong name silently blanks a whole column (40/40 rows did).
2. A dollar figure must never be manufactured. `market_notional` used to plug a
   $0.50 price in when the response had none, and the same function feeds the
   published `notional_usd` column (F-E1-05 / request R-E1-02,
   VERIFICATION-e1a76b9d.md). It now returns None; only the *ranking* key
   substitutes 0.0, which is a convention and is never shown as a value.

Run: python3 -m unittest -v tests.test_market_row_mapping
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.runner import market_notional, market_rank, market_row

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


class TestExpirationField(unittest.TestCase):
    def test_api_field_name_is_copied_verbatim(self):
        row = market_row(market(), SRC)
        self.assertEqual(row["expected_expiration"], "2026-11-22T00:00:00Z")

    def test_absent_field_stays_absent(self):
        row = market_row(market(expected_expiration_time=None), SRC)
        self.assertIsNone(row["expected_expiration"])

    def test_legacy_wrong_key_is_not_read(self):
        # An `expected_expiration_ts` key does not exist on the market object;
        # reading it is what blanked every row. A response that happened to carry
        # it must still not populate the column.
        row = market_row(market(expected_expiration_time=None,
                                 expected_expiration_ts=1796000000), SRC)
        self.assertIsNone(row["expected_expiration"])


class TestNoInventedDollars(unittest.TestCase):
    def test_price_present_uses_the_official_fields(self):
        # 24h volume 10.00 x last 0.41 = 4.10, recomputed from the same two
        # fields the row publishes next to it.
        row = market_row(market(), SRC)
        self.assertEqual(row["notional_usd"], 4.1)

    def test_no_price_leaves_the_column_blank_instead_of_filling_050(self):
        m = market(last_price_dollars=None, yes_bid_dollars=None,
                   yes_ask_dollars=None, volume_24h_fp=None)
        self.assertIsNone(market_notional(m))
        row = market_row(m, SRC)
        self.assertIsNone(row["notional_usd"])
        self.assertTrue(any("notional-unverified" in f for f in row["flags"]), row["flags"])
        self.assertFalse(row["verified"])
        # And explicitly: the old bug would have published 1000 x 0.50 = $500.
        self.assertNotEqual(row["notional_usd"], 500.0)

    def test_mid_is_used_when_only_a_book_exists(self):
        m = market(last_price_dollars=None, volume_24h_fp=None)   # bid .40 ask .42
        self.assertEqual(round(market_notional(m), 4), round(1000.0 * 0.41, 4))

    def test_ranking_still_orders_unpriced_markets_last(self):
        priced = market(volume_24h_fp=None)
        unpriced = market(volume_24h_fp=None, last_price_dollars=None,
                          yes_bid_dollars=None, yes_ask_dollars=None)
        self.assertGreater(market_rank(priced)[1], market_rank(unpriced)[1])
        self.assertEqual(market_rank(unpriced)[1], 0.0)

    def test_missing_volume_is_flagged_and_blank(self):
        row = market_row(market(volume_fp=None), SRC)
        self.assertIsNone(row["notional_usd"])
        self.assertTrue(any("volume-unverified" in f for f in row["flags"]))


class TestRowSourceLinking(unittest.TestCase):
    def test_every_row_links_its_own_api_response(self):
        row = market_row(market(), SRC)
        self.assertTrue(row["source_url"].startswith("https://external-api.demo.kalshi.co/"))
        self.assertEqual(row["docs_url"], "https://docs.kalshi.com/api-reference/market/get-markets")

    def test_status_is_normalised_and_series_is_recovered_from_the_ticker(self):
        # Both are documented live quirks: `status=open` responses report
        # "active", and the market object has no series_ticker field at all.
        row = market_row(market(series_ticker=None), SRC)
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["series_ticker"], "KXTEST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
