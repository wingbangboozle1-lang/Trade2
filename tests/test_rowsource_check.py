"""Unit tests for tools/rowsource_check.py (T20, arena-4f92a11c). Offline; stdlib only."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import rowsource_check as rc  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def test_demo_host(self):
        self.assertEqual(rc.classify_source("https://external-api.demo.kalshi.co/trade-api/v2/markets/X"), "DEMO")

    def test_production_host(self):
        self.assertEqual(rc.classify_source("https://external-api.kalshi.com/trade-api/v2/markets/X"), "PRODUCTION")

    def test_docs_host(self):
        self.assertEqual(rc.classify_source("https://docs.kalshi.com/api-reference/market/get-markets"), "OFFICIAL_DOC")

    def test_third_party(self):
        self.assertEqual(rc.classify_source("https://www.foxsports.com"), "THIRD_PARTY")

    def test_missing_and_non_http(self):
        self.assertEqual(rc.classify_source(None), "MISSING")
        self.assertEqual(rc.classify_source(""), "MISSING")
        self.assertEqual(rc.classify_source("ftp://external-api.demo.kalshi.co/x"), "MISSING")

    def test_blank(self):
        self.assertTrue(rc.is_blank(None))
        self.assertTrue(rc.is_blank("   "))
        self.assertFalse(rc.is_blank(0))
        self.assertFalse(rc.is_blank("0.0000"))


class AuditTableTests(unittest.TestCase):
    def _spec(self, **kw):
        base = dict(table_id="t", file="x", rows_path=("rows",), id_key="ticker", source_key="source_url",
                    docs_key=None, value_keys=())
        base.update(kw)
        return rc.TableSpec(**base)

    def test_demo_row_ok(self):
        doc = {"rows": [{"ticker": "A", "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/markets/A"}]}
        res, c = rc.audit_table(self._spec(), doc)
        self.assertEqual(res[0].status, "OK_DEMO")
        self.assertEqual((c["rows"], c["demo"], c["ok_demo"]), (1, 1, 1))

    def test_production_row_flagged(self):
        doc = {"rows": [{"ticker": "A", "source_url": "https://external-api.kalshi.com/trade-api/v2/markets/A"}]}
        res, c = rc.audit_table(self._spec(), doc)
        self.assertEqual(res[0].status, "OFFICIAL_PRODUCTION_HOST")
        self.assertEqual(c["production"], 1)
        self.assertIn("production host", res[0].notes[0])

    def test_missing_source_row(self):
        doc = {"rows": [{"ticker": "A"}]}
        res, c = rc.audit_table(self._spec(), doc)
        self.assertEqual(res[0].status, "MISSING_SOURCE")
        self.assertEqual(c["missing_source"], 1)

    def test_blank_value_is_unverified_not_filled(self):
        doc = {"rows": [{"ticker": "A", "source_url": "https://external-api.demo.kalshi.co/x", "yes_bid": None}]}
        res, c = rc.audit_table(self._spec(value_keys=("yes_bid",)), doc)
        self.assertEqual(res[0].blank_values, "yes_bid")
        self.assertEqual(res[0].status, "OK_DEMO_WITH_UNVERIFIED_VALUES")
        self.assertEqual(c["rows_with_blank_values"], 1)

    def test_derived_blank_with_official_value_is_explained(self):
        doc = {"rows": [{"ticker": "A", "source_url": "https://external-api.kalshi.com/x",
                         "last_cents": None, "last_price_dollars": "0.0030"}]}
        spec = self._spec(value_keys=("last_cents",), derived_of={"last_cents": "last_price_dollars"})
        res, c = rc.audit_table(spec, doc)
        self.assertEqual(c["derived_blank_official_present"], 1)
        self.assertTrue(any("0.0030" in n for n in res[0].notes))

    def test_docs_link_required_when_configured(self):
        doc = {"rows": [{"ticker": "A", "source_url": "https://external-api.demo.kalshi.co/x", "docs_url": ""}]}
        res, c = rc.audit_table(self._spec(docs_key="docs_url"), doc)
        self.assertEqual(c["docs_present"], 0)
        self.assertEqual(c["docs_expected"], 1)
        self.assertEqual(res[0].status, "PARTIAL")

    def test_non_official_primary_source(self):
        doc = {"rows": [{"ticker": "A", "source_url": "https://www.example.com/x"}]}
        res, c = rc.audit_table(self._spec(), doc)
        self.assertEqual(res[0].status, "NON_OFFICIAL_SOURCE")
        self.assertEqual(c["third_party_or_other"], 1)

    def test_walk_nested_topics(self):
        doc = {"topics": {"gas": {"events": [{"event_ticker": "E1", "source_url": "u"}]},
                          "golf": {"events": []}}}
        rows = list(rc._walk(doc, ("topics", "*", "events")))
        self.assertEqual([r["event_ticker"] for r in rows], ["E1"])


class RepoSmokeTests(unittest.TestCase):
    """Runs the audit on the committed tables; checks structure, not values (values change every run)."""

    def test_full_run_writes_outputs(self):
        import tempfile
        import json
        with tempfile.TemporaryDirectory() as tmp:
            s = rc.run(ROOT, tmp)
            self.assertTrue(os.path.exists(os.path.join(tmp, "rowsource-4f92a11c.csv")))
            with open(os.path.join(tmp, "rowsource-4f92a11c.json"), encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertEqual(saved["tables"].keys(), s["tables"].keys())
            for name, c in s["tables"].items():
                self.assertEqual(c["rows"], c["source_present"] + c["missing_source"], name)
                self.assertEqual(c["rows"], c["demo"] + c["production"] + c["official_doc"]
                                 + c["third_party_or_other"] + c["missing_source"], name)


if __name__ == "__main__":
    unittest.main()
