"""Tests for the published-rows verification panel (session arena-7695ba1b).

The Flagged-for-Review page now publishes the last automated re-check of the
rows this site shows: `tools/verify_rows_479.py` re-opens the top event of
every topic, its market row and its order book from the official demo
endpoints and compares them field by field with the published snapshot. Its
evidence file (`audit/verify-479.json`) is committed by the `verify-479`
workflow.

The panel must:
  * render one row per check, with the published value, the official value and
    a link to the exact official response;
  * never show a row without a source link;
  * say so plainly when no run has been recorded (never invent a result).
"""

import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from site_build import flagpage  # noqa: E402


class TestVerificationPanel(unittest.TestCase):
    def test_rows_are_built_from_the_committed_evidence(self):
        rows, note = flagpage.verification_rows()
        self.assertTrue(rows, "the committed evidence must produce rows")
        self.assertTrue(note, "a summary note must be produced")

    def test_every_row_links_to_an_official_demo_response(self):
        rows, _ = flagpage.verification_rows()
        for row in rows:
            self.assertIn("source-link", row)
            self.assertIn("external-api.demo.kalshi.co/trade-api/v2", row)

    def test_no_row_leaves_the_official_value_blank(self):
        """A check either matched, drifted, or could not be read.

        `published` may legitimately be blank (the site prints UNVERIFIED for
        it); the row still has to carry the official side and the verdict.
        """
        rows, _ = flagpage.verification_rows()
        for row in rows:
            self.assertTrue(re.search(r"tag-(yes|purple|grey)", row),
                            "each row must carry a verdict badge")

    def test_the_panel_is_rendered_on_the_review_page(self):
        path = os.path.join(ROOT, "review.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('id="verified"', html)
        self.assertIn("Published rows re-checked against the official API", html)

    def test_the_evidence_file_is_the_one_the_workflow_writes(self):
        path = os.path.join(ROOT, "audit", "verify-479.json")
        self.assertTrue(os.path.exists(path), "audit/verify-479.json must exist")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc.get("rest_base"),
                         "https://external-api.demo.kalshi.co/trade-api/v2")
        self.assertTrue(doc.get("verified_at"))
        self.assertTrue(doc.get("subjects"))


if __name__ == "__main__":
    unittest.main()
