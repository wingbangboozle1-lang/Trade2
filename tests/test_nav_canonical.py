"""The sidebar must be one canonical menu on every page (defect N-01).

Before this test, ``site_build/build.py`` rendered "Overview" in both the
Topics and Research groups and dropped the active link from Research, so:

* every page showed Overview twice, and
* the menu order changed depending on which page you were on.

Both are invisible to a template-only test (each function was individually
consistent); they only appear in the rendered HTML. So these tests read the
files that ship.
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = [
    "index.html", "live.html", "summary.html", "resolutions.html",
    "trades.html", "suggestions.html", "methodology.html", "review.html",
    "categories/gas-prices.html", "categories/elections.html",
    "categories/culture.html", "categories/crypto.html", "categories/golf.html",
]
NAV_RE = re.compile(r'<nav class="side-nav"[^>]*>(.*?)</nav>', re.S)
LINK_RE = re.compile(r'<a([^>]*)href="([^"]+)"')


def links(page: str):
    with open(os.path.join(ROOT, page), encoding="utf-8") as fh:
        html = fh.read()
    groups = []
    for m in NAV_RE.finditer(html):
        groups.append([(a.group(2), 'class="active"' in a.group(1))
                       for a in LINK_RE.finditer(m.group(1))])
    return groups


def norm(href: str) -> str:
    href = href.split("#")[0]
    while href.startswith("../"):
        href = href[3:]
    return href


class TestSidebarIsCanonical(unittest.TestCase):
    def test_every_page_has_two_nav_groups(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.assertEqual(len(links(page)), 2,
                                 f"{page}: expected Topics + Research navs")

    def test_no_destination_appears_twice(self):
        for page in PAGES:
            with self.subTest(page=page):
                flat = [norm(h) for g in links(page) for h, _ in g]
                dupes = {h for h in flat if flat.count(h) > 1}
                self.assertEqual(dupes, set(), f"{page}: duplicate {sorted(dupes)}")

    def test_order_is_identical_on_every_page(self):
        first = [norm(h) for g in links(PAGES[0]) for h, _ in g]
        for page in PAGES[1:]:
            with self.subTest(page=page):
                self.assertEqual([norm(h) for g in links(page) for h, _ in g], first,
                                 f"{page}: sidebar order differs from {PAGES[0]}")

    def test_active_page_keeps_its_slot_and_is_marked(self):
        for page in PAGES:
            if page == "index.html":
                continue
            with self.subTest(page=page):
                flat = [(norm(h), a) for g in links(page) for h, a in g]
                actives = [h for h, a in flat if a]
                self.assertEqual(actives, [page],
                                 f"{page}: exactly its own row must be active")
                self.assertIn(page, [h for h, _ in flat])

    def test_every_page_links_every_topic(self):
        topics = ["categories/gas-prices.html", "categories/elections.html",
                  "categories/culture.html", "categories/crypto.html",
                  "categories/golf.html"]
        for page in PAGES:
            with self.subTest(page=page):
                flat = {norm(h) for g in links(page) for h, _ in g}
                self.assertTrue(set(topics) <= flat, f"{page}: missing a topic link")

    def test_template_lists_overview_once(self):
        """Guards the root cause, so a future edit cannot reintroduce it in the
        template without failing a test even if the pages are not rebuilt."""
        with open(os.path.join(ROOT, "site_build", "build.py"), encoding="utf-8") as fh:
            src = fh.read()
        topics_block = src.split("NAV_TOPICS =", 1)[1].split("NAV_RESEARCH", 1)[0]
        research_block = src.split("NAV_RESEARCH =", 1)[1].split("def _render_nav", 1)[0]
        self.assertIn("index.html", topics_block)
        self.assertNotIn("index.html", research_block,
                         "Overview belongs to the Topics group only")

    def test_navcheck_tool_passes(self):
        import subprocess
        import sys
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "navcheck.py")],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
