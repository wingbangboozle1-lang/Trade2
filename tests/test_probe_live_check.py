"""The live shape check must be able to fail.

``tools/probe_live_check.py`` needs network access, so it runs in CI. The
assertion layer on top of its report (``tools/probe_shape_assert.py``) is pure
and is tested here with synthetic reports: a comma-joined query, a reordered
order-book response and a partial markets response must each be rejected.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSERT = os.path.join(ROOT, "tools", "probe_shape_assert.py")
CHECK = os.path.join(ROOT, "tools", "probe_live_check.py")


def run(report: dict) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(report, fh)
        path = fh.name
    try:
        return subprocess.run([sys.executable, ASSERT, path],
                              capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)


GOOD = {
    "tickers": ["A", "B"],
    "probe": {"markets": {"returned": ["A", "B"]},
              "orderbooks": {"returned": ["A", "B"]}},
    "forms": {
        "markets:comma": {"status": 200, "n": 2, "returned": ["A", "B"]},
        "markets:repeated": {"status": 400, "n": None},
        "orderbooks-plural:repeated": {"status": 200, "n": 2,
                                       "returned": ["A", "B"]},
        "orderbooks-plural:comma": {"status": 200, "n": 1,
                                    "returned": ["A,B"]},
    },
    "problems": [],
}


class TestShapeAssert(unittest.TestCase):
    def test_good_report_passes(self):
        proc = run(GOOD)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_markets_no_longer_accepting_comma_is_rejected(self):
        """The measured contract: /markets takes ONE comma-joined value."""
        bad = json.loads(json.dumps(GOOD))
        bad["forms"]["markets:comma"] = {"status": 400, "n": None}
        proc = run(bad)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("comma-joined form", proc.stderr)

    def test_books_no_longer_accepting_repeats_is_rejected(self):
        bad = json.loads(json.dumps(GOOD))
        bad["forms"]["orderbooks-plural:repeated"] = {"status": 404, "n": None}
        proc = run(bad)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("repeated parameters", proc.stderr)

    def test_out_of_order_books_are_rejected(self):
        bad = json.loads(json.dumps(GOOD))
        bad["probe"]["orderbooks"]["returned"] = ["B", "A"]
        proc = run(bad)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("request order", proc.stderr)

    def test_partial_markets_response_is_rejected(self):
        bad = json.loads(json.dumps(GOOD))
        bad["probe"]["markets"]["returned"] = ["A"]
        self.assertEqual(run(bad).returncode, 1)

    def test_empty_ticker_list_proves_nothing(self):
        bad = {"tickers": [], "probe": {}, "forms": {}, "problems": []}
        self.assertEqual(run(bad).returncode, 1)

    def test_carried_problems_are_surfaced(self):
        bad = json.loads(json.dumps(GOOD))
        bad["problems"] = ["GET /markets failed: timeout"]
        proc = run(bad)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("timeout", proc.stderr)

    def test_the_probe_uses_a_serialisation_per_endpoint(self):
        """Static guard: comma for /markets, repeated for /markets/orderbooks."""
        with open(os.path.join(ROOT, "assets", "live-probe.js"), encoding="utf-8") as fh:
            probe = fh.read()
        self.assertIn('fetchAll(tickers, ENDPOINTS.markets, "markets", "comma")', probe)
        self.assertIn('fetchAll(tickers, ENDPOINTS.orderbooks, "orderbooks", "repeated")',
                      probe)
        self.assertIn('list.join(",")', probe)


if __name__ == "__main__":
    unittest.main()
