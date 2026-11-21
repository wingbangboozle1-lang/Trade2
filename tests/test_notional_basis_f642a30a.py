"""R-3DCF-5 (session arena-f642a30a): the derived ``notional_usd`` figure must be
re-checkable — the row stores the exact price used and the official field(s) it
was read from (``notional_basis_price`` / ``notional_basis``).

Official fields verified against the live demo API market object
(https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker},
https://docs.kalshi.com/api-reference/market/get-markets): ``last_price_dollars``,
``yes_bid_dollars``, ``yes_ask_dollars``, ``volume_fp``, ``volume_24h_fp``.
"""

import unittest

from collector.runner import market_notional, market_notional_basis, market_row


def market(**over):
    m = {
        "ticker": "KXTEST-26NOV21-ABOVE",
        "event_ticker": "KXTEST-26NOV21",
        "title": "Synthetic test market",
        "status": "active",
        "last_price_dollars": "0.4100",
        "yes_bid_dollars": "0.4000",
        "yes_ask_dollars": "0.4200",
        "volume_fp": "5000.00",
        "volume_24h_fp": "500.00",
        "open_interest_fp": "800.00",
    }
    m.update(over)
    return m


class TestNotionalBasis(unittest.TestCase):
    def test_basis_is_last_price_when_returned(self):
        price, basis = market_notional_basis(market())
        self.assertEqual(price, 0.41)
        self.assertEqual(basis, "last_price_dollars")

    def test_basis_is_midpoint_when_only_bid_ask(self):
        price, basis = market_notional_basis(
            market(last_price_dollars=None, yes_bid_dollars="0.3000", yes_ask_dollars="0.3400"))
        self.assertEqual(price, 0.32)
        self.assertEqual(basis, "mid(yes_bid_dollars,yes_ask_dollars)")

    def test_no_price_means_no_basis_and_no_figure(self):
        price, basis = market_notional_basis(
            market(last_price_dollars=None, yes_bid_dollars=None, yes_ask_dollars=None))
        self.assertIsNone(price)
        self.assertIsNone(basis)
        self.assertIsNone(market_notional(market(
            last_price_dollars=None, yes_bid_dollars=None, yes_ask_dollars=None)))

    def test_row_publishes_basis_and_figure_is_recomputable(self):
        row = market_row(market(), "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXTEST-26NOV21-ABOVE")
        self.assertEqual(row["notional_basis_price"], 0.41)
        self.assertEqual(row["notional_basis"], "last_price_dollars")
        # volume basis is volume_24h_fp when > 0, else volume_fp (documented in market_notional)
        self.assertEqual(row["notional_usd"], round(500.00 * row["notional_basis_price"], 2))
        # the raw official inputs sit in the same row, so the product can be re-derived
        self.assertEqual(row["volume_24h_fp"], 500.00)
        self.assertEqual(row["last_price"], 0.41)

    def test_row_midpoint_fallback_is_labelled(self):
        row = market_row(market(last_price_dollars=None), "https://example.invalid/x")
        self.assertEqual(row["notional_basis"], "mid(yes_bid_dollars,yes_ask_dollars)")
        self.assertAlmostEqual(row["notional_basis_price"], (0.40 + 0.42) / 2)
        self.assertEqual(row["notional_usd"], round(500.00 * (0.40 + 0.42) / 2, 2))

    def test_row_with_no_price_keeps_basis_blank(self):
        row = market_row(market(last_price_dollars=None, yes_bid_dollars=None, yes_ask_dollars=None),
                         "https://example.invalid/x")
        self.assertIsNone(row["notional_basis_price"])
        self.assertIsNone(row["notional_basis"])
        self.assertIsNone(row["notional_usd"])


if __name__ == "__main__":
    unittest.main()
