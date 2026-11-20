"""The row-source gate must actually catch an unsourced row."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from row_sources import rows_without_source  # noqa: E402


class RowSourceCheck(unittest.TestCase):
    def _page(self, html: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html)
        self.addCleanup(os.unlink, path)
        return path

    def test_row_with_official_link_passes(self):
        page = self._page(
            '<table><tbody><tr><td>BTC</td><td>'
            '<a href="https://external-api.demo.kalshi.co/trade-api/v2/markets/X">API</a>'
            '</td></tr></tbody></table>')
        self.assertEqual(rows_without_source(page), [])

    def test_row_with_docs_link_passes(self):
        page = self._page(
            '<table><tbody><tr><td>0.42</td><td>'
            '<a href="https://docs.kalshi.com/api-reference/market/get-markets.md">docs</a>'
            '</td></tr></tbody></table>')
        self.assertEqual(rows_without_source(page), [])

    def test_row_without_any_link_fails(self):
        page = self._page(
            '<table><tbody><tr><td>BTC</td><td>0.42</td></tr></tbody></table>')
        self.assertEqual(len(rows_without_source(page)), 1)

    def test_non_kalshi_link_does_not_count(self):
        """A third-party link is not a substitute for the official record."""
        page = self._page(
            '<table><tbody><tr><td>BTC</td><td>'
            '<a href="https://www.coindesk.com/price/bitcoin">news</a></td></tr>'
            '</tbody></table>')
        self.assertEqual(len(rows_without_source(page)), 1)

    def test_empty_state_is_not_a_data_row(self):
        page = self._page(
            '<table><tbody><tr><td colspan="3" class="empty-state">No rows yet.</td>'
            '</tr></tbody></table>')
        self.assertEqual(rows_without_source(page), [])


if __name__ == "__main__":
    unittest.main()
