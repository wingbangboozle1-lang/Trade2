"""The server-rendered chats and the browser chats must group alerts identically.

``site_build.extras.group_alerts`` (used for the pre-rendered HTML) and
``dedupeAlerts`` in ``assets/alerts-view.js`` (used once the page boots) are two
implementations of one rule. This test runs both on the same fixture and
asserts they agree. It is skipped when Node is not installed.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from site_build import extras

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = [
    {"ticker": "A", "direction": "down", "previous": 0.80, "current": 0.0025,
     "ts": 1.0, "iso": "2026-11-20T18:41:08Z", "yes_bid": 0.0, "yes_ask": 0.0025},
    {"ticker": "A", "direction": "down", "previous": 0.80, "current": 0.0025,
     "ts": 2.0, "iso": "2026-11-20T18:46:08Z", "yes_bid": 0.0, "yes_ask": 0.0025},
    {"ticker": "A", "direction": "down", "previous": 0.80, "current": 0.0025,
     "ts": 3.0, "iso": "2026-11-20T18:51:08Z", "yes_bid": 0.0, "yes_ask": 0.0025},
    # Wide spread: 0.20 >= 0.10, so not executable.
    {"ticker": "B", "direction": "up", "previous": 0.30, "current": 0.45,
     "ts": 4.0, "iso": "2026-11-20T18:52:00Z", "yes_bid": 0.35, "yes_ask": 0.55},
    # Same market, opposite direction: a different alert.
    {"ticker": "A", "direction": "up", "previous": 0.0025, "current": 0.20,
     "ts": 5.0, "iso": "2026-11-20T18:53:00Z", "yes_bid": 0.19, "yes_ask": 0.21},
]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class AlertGroupingParity(unittest.TestCase):
    def _browser(self):
        script = (
            "const V=require(%r);"
            "const out=V.dedupeAlerts(%s);"
            "process.stdout.write(JSON.stringify(out));"
        ) % (str(ROOT / "assets" / "alerts-view.js"), json.dumps(FIXTURE))
        res = subprocess.run(["node", "-e", script], capture_output=True,
                             text=True, check=True)
        return json.loads(res.stdout)

    def test_same_rows_counts_and_flags(self):
        py = extras.group_alerts(FIXTURE)
        js = self._browser()
        self.assertEqual(len(py), len(js))
        for p, j in zip(py, js):
            self.assertEqual(p["ticker"], j["ticker"])
            self.assertEqual(p["direction"], j["direction"])
            self.assertEqual(p["repeat_count"], j["repeat_count"])
            self.assertEqual(bool(p["wide_spread"]), bool(j["wide_spread"]))
            self.assertEqual(p.get("last_iso"), j.get("last_iso"))

    def test_expected_grouping(self):
        py = extras.group_alerts(FIXTURE)
        self.assertEqual([r["repeat_count"] for r in py], [3, 1, 1])
        self.assertEqual([bool(r["wide_spread"]) for r in py],
                         [False, True, False])
        self.assertEqual(py[0]["last_iso"], "2026-11-20T18:51:08Z")

    def test_raw_rows_not_mutated(self):
        before = json.dumps(FIXTURE, sort_keys=True)
        extras.group_alerts(FIXTURE)
        self.assertEqual(before, json.dumps(FIXTURE, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
