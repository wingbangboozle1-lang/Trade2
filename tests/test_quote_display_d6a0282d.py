"""K2 — a quote the API returned is never published as UNVERIFIED.

Regression coverage for the defect this session found on the published site
(2026-11-21): the landing page printed ``UNVERIFIED`` for the YES bid and YES
ask of ``KXAAAGASM-26NOV30-4.70`` while the very endpoint that row links to,
``GET /markets/KXAAAGASM-26NOV30-4.70``, returned

    yes_bid_dollars "0.0000"   yes_ask_dollars "1.0000"   last_price_dollars "0.0200"

Those are Kalshi's empty-book values: the market is quoting the whole range
because nothing is resting behind it. ``alerts.observe`` nulls that pair on
purpose, so a phantom $0.50 mid cannot fire a swing alert — a rule this test
also pins, because the fix must not weaken it. What was wrong is that the null
leaked into the *display* row, so the site claimed it could not verify a number
it had in hand.

Run: python3 -m unittest tests.test_quote_display_d6a0282d -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import alerts as A
from site_build.format import bid_ask_cells, cents, last_price_of

SOURCE_ORDERBOOK = "https://docs.kalshi.com/getting_started/orderbook_responses"


def market(ticker="KXAAAGASM-26NOV30-4.70", bid="0.0000", ask="1.0000",
           last="0.0200", **extra):
    """A market object shaped like the demo API's response for that ticker."""
    row = {
        "ticker": ticker,
        "event_ticker": "KXAAAGASM-26NOV30",
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "yes_bid_size_fp": "0.00",
        "yes_ask_size_fp": "0.00",
        "last_price_dollars": last,
        "previous_price_dollars": "0.0200",
        "volume_fp": "58071.52",
        "open_interest_fp": "58062.52",
        "notional_value_dollars": "1.0000",
        "status": "active",
        "result": "",
        "close_time": "2026-11-30T04:59:00Z",
    }
    row.update(extra)
    return row


def observe(market_row, orderbook=None):
    return A.observe(market_row, orderbook or {}, "gas-prices", ts=1795242480.0,
                     series={"ticker": "KXAAAGASM", "fee_multiplier": 1,
                             "fee_type": "quadratic"})


class EmptyBookQuoteIsStillPublished(unittest.TestCase):
    def test_alert_basis_stays_nulled_for_an_empty_book(self):
        """The guard that prevents phantom $0.50 mids must not be weakened."""
        obs = observe(market())
        self.assertIsNone(obs.yes_bid)
        self.assertIsNone(obs.yes_ask)
        self.assertIsNone(obs.mid, "an empty book must not produce a midpoint")
        self.assertEqual(obs.book_state, "empty")

    def test_display_fields_keep_the_official_quote(self):
        obs = observe(market())
        self.assertEqual(obs.quote_bid, 0.0)
        self.assertEqual(obs.quote_ask, 1.0)
        self.assertEqual(obs.last_price, 0.02)

    def test_rank_events_carries_the_row_fields_the_site_reads(self):
        row = A.rank_events([observe(market())])[0]
        self.assertEqual(row["yes_bid"], None)
        self.assertEqual(row["quote_bid"], 0.0)
        self.assertEqual(row["quote_ask"], 1.0)
        self.assertEqual(row["book_state"], "empty")
        self.assertEqual(row["last_price"], 0.02)
        # Ranking is unchanged by the display fields: still open-interest value.
        self.assertEqual(row["open_interest_notional"], 58062.52)

    def test_table_cells_show_the_quote_with_the_caveat(self):
        row = A.rank_events([observe(market())])[0]
        bid, ask = bid_ask_cells(row)
        self.assertIn("$0.0000", bid)
        self.assertIn("$1.0000", ask)
        self.assertIn("empty book · nothing resting", bid)
        self.assertIn(SOURCE_ORDERBOOK, bid)
        self.assertNotIn("UNVERIFIED", bid)
        self.assertNotIn("UNVERIFIED", ask)

    def test_last_price_column_uses_the_markets_own_field(self):
        row = A.rank_events([observe(market())])[0]
        self.assertEqual(last_price_of(row), 0.02)
        self.assertEqual(cents(last_price_of(row)), "$0.0200")

    def test_last_price_falls_back_to_the_observation_block(self):
        """Rows written before the field was published at the top level still
        render the real number instead of a blank."""
        legacy = {"ticker": "T"}
        self.assertIsNone(last_price_of(legacy))
        self.assertEqual(last_price_of({"observation": {"last_price": 0.42}}), 0.42)


class RealQuotesAreNotTaggedAsEmpty(unittest.TestCase):
    def test_two_sided_book_keeps_the_alert_basis_and_adds_no_badge(self):
        obs = observe(market(bid="0.0380", ask="0.0390", last="0.0385"))
        self.assertEqual(obs.yes_bid, 0.038)
        self.assertEqual(obs.yes_ask, 0.039)
        self.assertEqual(obs.book_state, "two-sided")
        row = A.rank_events([obs])[0]
        bid, ask = bid_ask_cells(row)
        self.assertIn("$0.0380", bid)
        self.assertNotIn("empty book", bid + ask)

    def test_missing_quote_is_still_unverified(self):
        """A market that quotes nothing gets the blank-plus-badge treatment:
        the fix publishes values the API returned, it never invents one."""
        obs = observe(market(bid=None, ask=None, last=None))
        self.assertEqual(obs.book_state, "none")
        self.assertIsNone(obs.quote_bid)
        row = A.rank_events([obs])[0]
        bid, ask = bid_ask_cells(row)
        self.assertIn("UNVERIFIED", bid)
        self.assertIn("UNVERIFIED", ask)
        self.assertIsNone(last_price_of(row))
        self.assertIn("UNVERIFIED", cents(last_price_of(row)))

    def test_one_sided_book_is_labelled_not_flattened(self):
        obs = observe(market(bid="0.0300", ask=None, last="0.0300"))
        self.assertEqual(obs.book_state, "one-sided")
        self.assertEqual(obs.quote_bid, 0.03)
        self.assertIsNone(obs.quote_ask)


class RowWrittenBeforeTheFieldsExisted(unittest.TestCase):
    def test_absent_quote_fields_render_as_they_used_to(self):
        """The published snapshot predates ``quote_bid``: it must keep showing
        UNVERIFIED rather than borrow the neighbouring row's numbers."""
        legacy = {"ticker": "X", "yes_bid": None, "yes_ask": None}
        bid, ask = bid_ask_cells(legacy)
        self.assertIn("UNVERIFIED", bid)
        self.assertIn("UNVERIFIED", ask)


if __name__ == "__main__":
    unittest.main(verbosity=2)
