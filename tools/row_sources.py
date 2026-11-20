"""Fail if any table data row on the published site lacks an official source.

The brief requires: "Every table row must have a source link to an official
site. If a value can't be confirmed from an official source, leave it blank and
flag it as unverified."

This script is the mechanical check for that. A "data row" is a <tr> inside a
<tbody> that contains at least one non-empty cell and is not an empty-state
placeholder. Every such row must contain a link whose host is a Kalshi host
(external-api.demo.kalshi.co, demo-api.kalshi.co, docs.kalshi.com, kalshi.com,
assets.kalshi.com) or a publisher Kalshi itself names as a settlement source in
the series record (checked separately in flagpage; here the Kalshi link is what
is required, because the row must be traceable to the API response).

Usage: python3 tools/row_sources.py [--root .] [--quiet]
Exit code 0 = every row carries a source; 1 = at least one row does not.
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys

OFFICIAL_HOSTS = (
    "external-api.demo.kalshi.co",
    "demo-api.kalshi.co",
    "docs.kalshi.com",
    "external-api.kalshi.com",
    "kalshi.com",
    "assets.kalshi.com",
)

PAGES = ["index.html", "live.html", "summary.html", "review.html",
         "methodology.html"] + sorted(glob.glob("categories/*.html"))


def rows_without_source(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        page = fh.read()
    missing = []
    for body in re.findall(r"(?s)<tbody[^>]*>(.*?)</tbody>", page):
        for row in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", body):
            if 'class="empty-state"' in row:
                continue
            cells = re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)
            if not cells:
                continue
            text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", row)).strip()
            if not text:
                continue
            hrefs = re.findall(r'href="([^"]+)"', row)
            if not any(any(h in u for h in OFFICIAL_HOSTS) for u in hrefs):
                missing.append(text[:100])
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    os.chdir(args.root)

    total_rows = 0
    problems: list[tuple[str, str]] = []
    for path in PAGES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        for block in re.findall(r"(?s)<tbody[^>]*>(.*?)</tbody>", body):
            total_rows += len([r for r in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", block)
                               if 'class="empty-state"' not in r])
        for text in rows_without_source(path):
            problems.append((path, text))

    if not args.quiet:
        print(f"pages={len([p for p in PAGES if os.path.exists(p)])} rows={total_rows} "
              f"rows_without_official_source={len(problems)}")
    for path, text in problems[:40]:
        print(f"  {path}: {text}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
