"""R-67-1: KXBIGBROTHER must classify as culture in BOTH pipelines (arena-89ffef51).

Official source, read live on 2026-11-21:
  GET https://external-api.demo.kalshi.co/trade-api/v2/series/KXBIGBROTHER
  -> category "Entertainment", categories ["Entertainment"],
     tags ["Reality TV", "Television"], title "Big Brother",
     fee_type "quadratic", fee_multiplier 1.

Before this fix the docs pipeline labelled the series ``topic=culture``
(``docs/data/series.json``) while the root culture keyword matcher in
``collector/topics.py`` did not match it, so the root collector never tracked
Big Brother markets and never stored their outcomes (flag I-B / request
R-67-1). These tests pin the decision and both classification paths.
"""

from __future__ import annotations

import unittest

from collector.topics import TOPIC_BY_KEY, classify_market, resolve_series

# Verbatim from GET /series/KXBIGBROTHER (2026-11-21); volume_fp is not part
# of that response and resolve_series stores it as None.
OFFICIAL_SERIES = {
    "ticker": "KXBIGBROTHER",
    "title": "Big Brother",
    "category": "Entertainment",
    "categories": ["Entertainment"],
    "tags": ["Reality TV", "Television"],
    "frequency": "one_off",
    "fee_type": "quadratic",
    "fee_multiplier": 1,
    "contract_terms_url": "https://assets.kalshi.com/contract_terms/COMPETITIONREALITYELIM.pdf",
    "settlement_sources": [{"name": "The Source Agencies are",
                            "url": "https://kalshi.com/"}],
}


class FakeClient:
    """series_list() answers from a fixed row set, keyed by queried category."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def series_list(self, category=None, tags=None, max_pages=None):
        self.queries.append(category)
        return [dict(r) for r in self.rows
                if category is None or r.get("category") == category]


class RootMatcherTests(unittest.TestCase):
    """resolve_series() (root pipeline, queries + keyword matchers)."""

    def test_big_brother_resolves_as_culture(self):
        culture = TOPIC_BY_KEY["culture"]
        rows = resolve_series(FakeClient([OFFICIAL_SERIES]), culture)
        by_ticker = {r["ticker"]: r for r in rows}
        self.assertIn("KXBIGBROTHER", by_ticker,
                      "root resolver must include the official Big Brother series")
        self.assertEqual(by_ticker["KXBIGBROTHER"]["topic"], "culture")
        self.assertEqual(by_ticker["KXBIGBROTHER"]["category"], "Entertainment")
        self.assertEqual(by_ticker["KXBIGBROTHER"]["tags"],
                         ["Reality TV", "Television"])

    def test_resolver_queries_the_official_category(self):
        client = FakeClient([OFFICIAL_SERIES])
        resolve_series(client, TOPIC_BY_KEY["culture"])
        # culture queries both the Culture and the Entertainment category.
        self.assertIn("Entertainment", client.queries)

    def test_generic_entertainment_series_still_excluded(self):
        """Entertainment alone is not culture — the deliberate strictness stays."""
        not_culture = {
            "ticker": "KXFICTITIOUS",
            "title": "Cooking Show Final",
            "category": "Entertainment",
            "categories": ["Entertainment"],
            "tags": ["Food"],
        }
        rows = resolve_series(FakeClient([OFFICIAL_SERIES, not_culture]),
                              TOPIC_BY_KEY["culture"])
        tickers = {r["ticker"] for r in rows}
        self.assertIn("KXBIGBROTHER", tickers)
        self.assertNotIn("KXFICTITIOUS", tickers,
                         "the keyword filter must keep excluding ordinary "
                         "Entertainment series (the 963-series problem)")

    def test_non_culture_topics_do_not_claim_big_brother(self):
        for slug in ("gas-prices", "elections", "crypto", "golf"):
            rows = resolve_series(FakeClient([OFFICIAL_SERIES]),
                                  TOPIC_BY_KEY[slug])
            self.assertNotIn("KXBIGBROTHER", {r["ticker"] for r in rows},
                             f"{slug} must not claim KXBIGBROTHER")


class DocsMatcherTests(unittest.TestCase):
    """Topic.matches() (docs pipeline, category rules)."""

    def test_docs_side_matches_official_row(self):
        self.assertTrue(TOPIC_BY_KEY["culture"].matches(OFFICIAL_SERIES),
                        "docs-side category rule must classify the official "
                        "Entertainment row as culture (it already did)")

    def test_docs_side_rejects_sports_row(self):
        self.assertFalse(
            TOPIC_BY_KEY["culture"].matches(
                {"ticker": "KXNBA", "title": "NBA Game",
                 "category": "Sports", "categories": ["Sports"]}))


class BothPipelinesAgreeTests(unittest.TestCase):
    """The point of R-67-1: one series, one topic, both classifiers."""

    def test_root_and_docs_classifiers_agree(self):
        culture = TOPIC_BY_KEY["culture"]
        root_rows = resolve_series(FakeClient([OFFICIAL_SERIES]), culture)
        self.assertTrue(any(r["ticker"] == "KXBIGBROTHER" for r in root_rows))
        self.assertTrue(culture.matches(OFFICIAL_SERIES))

    def test_market_level_classification_inherits_series_topic(self):
        topic = classify_market(
            {"ticker": "KXBIGBROTHER-26DEC31-RIC",
             "series_ticker": "KXBIGBROTHER",
             "title": "Will Rick Devens win Big Brother Season 28?"},
            {"KXBIGBROTHER": "culture"})
        self.assertEqual(topic, "culture")


if __name__ == "__main__":
    unittest.main()
