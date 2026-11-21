#!/usr/bin/env python3
"""Fail the build if any generated page's sidebar disagrees with the others.

Two invariants, both of which were violated on ``main`` before this check
existed (COORDINATION.md N-01):

1. **One entry per destination.** "Overview" was rendered in both the Topics
   and the Research group, so it appeared twice in every sidebar.
2. **Stable order.** ``research_nav()`` used to drop the active link, so the
   visible order of the menu depended on which page you were on (``index``
   showed ``Live desk, Resolved, Trades...`` while ``summary`` showed
   ``Live desk, Overview, Resolved...``).

The check parses the generated HTML rather than the template, because the
defect only appears after rendering: ``nav()`` and ``research_nav()`` were each
self-consistent and the bug lived in how the two were composed and in whether
the active row was skipped.

Usage:  python3 tools/navcheck.py [root]     (default: repo root)
Exit:   0 clean, 1 violations printed
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGES = [
    "index.html",
    "live.html",
    "summary.html",
    "resolutions.html",
    "trades.html",
    "suggestions.html",
    "methodology.html",
    "review.html",
    "categories/gas-prices.html",
    "categories/elections.html",
    "categories/culture.html",
    "categories/crypto.html",
    "categories/golf.html",
]

NAV_RE = re.compile(r'<nav class="side-nav"[^>]*>(.*?)</nav>', re.S)
LINK_RE = re.compile(r'<a([^>]*)href="([^"]+)"[^>]*>\s*(?:<span>[^<]*</span>\s*)?([^<]*)')


def parse(path: str) -> list[list[tuple[str, str, str]]]:
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    groups = []
    for match in NAV_RE.finditer(html):
        links = []
        for link in LINK_RE.finditer(match.group(1)):
            attrs, href, label = link.group(1), link.group(2), link.group(3)
            active = 'class="active"' in attrs
            links.append((href, " ".join(label.split()), "active" if active else ""))
        groups.append(links)
    return groups


def normalise(href: str) -> str:
    """Reduce a page-relative href to the repository-relative path it names.

    ``categories/crypto.html`` and ``../categories/crypto.html`` from inside
    ``categories/`` are the same destination and must compare equal; a naive
    string compare would report 13 false positives.
    """
    href = href.split("#")[0].split("?")[0]
    if href.startswith("http://") or href.startswith("https://"):
        return href
    while href.startswith("../"):
        href = href[3:]
    if href.startswith("./"):
        href = href[2:]
    return href


def main(argv: list[str]) -> int:
    root = os.path.abspath(argv[1]) if len(argv) > 1 else ROOT
    problems: list[str] = []
    baseline: list[str] | None = None
    baseline_page = ""

    for page in PAGES:
        path = os.path.join(root, page)
        if not os.path.exists(path):
            problems.append(f"{page}: missing")
            continue
        groups = parse(path)
        if len(groups) != 2:
            problems.append(f"{page}: expected 2 nav groups, found {len(groups)}")
            continue
        flat = [row for group in groups for row in group]
        targets = [normalise(h) for h, _, _ in flat]

        # Invariant 1: no destination twice.
        seen: dict[str, int] = {}
        for target in targets:
            seen[target] = seen.get(target, 0) + 1
        dupes = sorted(t for t, n in seen.items() if n > 1)
        if dupes:
            problems.append(f"{page}: duplicate nav destinations {dupes}")

        # Invariant 2: identical order on every page (modulo which one is active).
        order = [t for t in targets]
        if baseline is None:
            baseline, baseline_page = order, page
        elif order != baseline:
            problems.append(
                f"{page}: nav order differs from {baseline_page}\n"
                f"    expected {baseline}\n    found    {order}")

        # Invariant 3: exactly the current page is marked active.
        actives = [normalise(h) for h, _, state in flat if state == "active"]
        if page != "index.html" and len(actives) != 1:
            problems.append(f"{page}: expected 1 active link, found {len(actives)}")

        # Invariant 4: the page can reach itself.
        if page != "index.html" and normalise(page) not in targets:
            problems.append(f"{page}: sidebar does not link to itself "
                            "(the active row must keep its slot)")

    if problems:
        print("NAV CHECK FAILED")
        for p in problems:
            print(" - " + p)
        return 1
    print(f"navcheck: {len(PAGES)} pages, one canonical sidebar, "
          f"{len(baseline or [])} destinations, 0 problems")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
