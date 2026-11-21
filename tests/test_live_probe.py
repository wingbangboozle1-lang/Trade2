"""Runs assets/live-probe.js's own test suite from ``python3 -m unittest``.

The browser-side swing detector is JavaScript because it has to run in the
visitor's tab (the demo REST API is CORS-open; see data/_cors.txt). Its logic
is still part of the shipped product, so the Python suite gates it too: this
module shells out to ``node test/live-probe.test.mjs``, which exits non-zero on
any failed assertion.

Skipped, never silently passed, when ``node`` is not on PATH.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "test", "live-probe.test.mjs")
SOURCE = os.path.join(ROOT, "assets", "live-probe.js")


def strip_comments(src: str) -> str:
    """Remove /* ... */ and // ... so a check can look at executable code only.

    Needed because the module's header legitimately *describes* the things it
    must never do ("POST /portfolio/... is never called"); a naive substring
    search over the raw file matches that prose and fails a correct file.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    return src


class TestLiveProbeSuite(unittest.TestCase):
    def test_script_and_source_exist(self):
        self.assertTrue(os.path.exists(SOURCE), "assets/live-probe.js is missing")
        self.assertTrue(os.path.exists(SCRIPT), "test/live-probe.test.mjs is missing")

    def test_node_suite_passes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed; the JS suite runs in CI")
        proc = subprocess.run([node, SCRIPT], cwd=ROOT, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(
            proc.returncode, 0,
            "live-probe JS suite failed:\n" + proc.stdout + proc.stderr)

    def test_module_cannot_place_an_order(self):
        """The browser must have no path to a private or mutating endpoint.

        Checked against executable code only (comments describe the guarantee).
        Any of these appearing means the page could act on an account, which
        this project promises it never does.
        """
        with open(SOURCE, encoding="utf-8") as fh:
            code = strip_comments(fh.read())
        for forbidden in ("/portfolio", "method:", "POST", "PUT", "DELETE",
                          "Authorization", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(
                forbidden, code,
                f"assets/live-probe.js must not reference {forbidden!r} in code")

    def test_module_only_reads_the_public_demo_api(self):
        """Every API base the module builds a request from is the demo host.

        ``kalshi.com`` and ``docs.kalshi.com`` are linked as human-readable
        references (market pages, documentation), never fetched; the check is
        therefore scoped to the constants that are actually concatenated into
        request URLs plus any template that contains ``/trade-api/``.
        """
        with open(SOURCE, encoding="utf-8") as fh:
            code = strip_comments(fh.read())
        api_bases = set(re.findall(r'(https://[a-z0-9.\-]+)/trade-api/', code))
        self.assertEqual(
            api_bases, {"https://external-api.demo.kalshi.co"},
            "API bases must be the demo host only, found: %s" % sorted(api_bases))
        # No production host may appear anywhere in the executable code.
        for production in ("external-api.kalshi.com", "api.elections.kalshi.com",
                           "demo-api.kalshi.co/trade-api", "trading-api.kalshi.com"):
            self.assertNotIn(production, code)

    def test_module_is_served_with_the_site(self):
        """site_build writes the page template; if the script tag were missing
        the desk would silently fall back to snapshot-only alerts."""
        with open(os.path.join(ROOT, "site_build", "build.py"), encoding="utf-8") as fh:
            build = fh.read()
        self.assertIn("live-probe.js", build)

    def test_desk_wires_the_probe(self):
        with open(os.path.join(ROOT, "assets", "desk.js"), encoding="utf-8") as fh:
            desk = fh.read()
        self.assertIn("window.KalshiLive", desk)
        self.assertIn("startLiveProbe", desk)
        # The probe's rows must be labelled, or a reader cannot tell who
        # measured a move.
        self.assertIn('origin === "live"', desk)


if __name__ == "__main__":
    unittest.main()
