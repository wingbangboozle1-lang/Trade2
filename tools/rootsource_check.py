#!/usr/bin/env python3
"""Row-level source-link audit for the RENDERED site (session arena-7695ba1b).

`tools/rowsource_check.py` audits the intermediate JSON tables of the `docs/`
and `kalshi-dashboard/` pipelines. The root pipeline — the one published at
https://wingbangboozle1-lang.github.io/Trade2/ — builds its per-row source
link at RENDER time from the market ticker, so the JSON rows carry no
`source_url` field and that tool could not see them.

This tool audits the artefact that is actually served: the generated HTML.
For every table row that mentions a Kalshi market ticker it requires

  1. at least one link to an official **demo** API host
     (external-api.demo.kalshi.co / demo-api.kalshi.co), and
  2. no link to a **production** Kalshi API host
     (external-api.kalshi.com / api.elections.kalshi.com) — the brief asks
     for the demo environment only.

Rows with no market ticker (section headers, aggregate/summary rows) are
counted and skipped. Nothing is inferred: a row without a source link is
reported, never filled in.

Usage:
    python3 tools/rootsource_check.py [--root .] [--out audit]
Exit code 1 when any data row is missing a demo source link or points at a
production host.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from urllib.parse import urlparse

DEMO_HOSTS = {"external-api.demo.kalshi.co", "demo-api.kalshi.co",
              "external-api-ws.demo.kalshi.co"}
PRODUCTION_HOSTS = {"external-api.kalshi.com", "api.elections.kalshi.com",
                    "external-api-ws.kalshi.com"}

TICKER_RE = re.compile(r"KX[A-Z0-9]{2,}(?:-[A-Za-z0-9.]+)*")
ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S)
HREF_RE = re.compile(r'href="([^"]+)"')

# The published site trees: (label, relative directory). Root pages first.
PAGE_TREES = [
    ("root", ""),
    ("docs", "docs"),
    ("kalshi-dashboard", "kalshi-dashboard"),
]


def host_of(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    return (urlparse(url).hostname or "").lower()


def iter_pages(root: str, tree: str):
    base = os.path.join(root, tree) if tree else root
    if not os.path.isdir(base):
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in {".git", "node_modules", "audit", "data", "assets",
                                          "verification", "pages", "_site"})
        for name in sorted(filenames):
            if name.endswith(".html"):
                yield os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")


def audit_file(root: str, rel: str) -> tuple[list[dict], dict]:
    path = os.path.join(root, rel)
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    rows = []
    counts = {"data_rows": 0, "non_data_rows": 0, "with_demo_source": 0,
              "missing_demo_source": 0, "production_links": 0}
    for row_html in ROW_RE.findall(html):
        tickers = sorted(set(TICKER_RE.findall(row_html)))
        hrefs = HREF_RE.findall(row_html)
        if not tickers:
            counts["non_data_rows"] += 1
            continue
        counts["data_rows"] += 1
        demo = [h for h in hrefs if host_of(h) in DEMO_HOSTS]
        prod = [h for h in hrefs if host_of(h) in PRODUCTION_HOSTS]
        if prod:
            counts["production_links"] += 1
        if demo:
            counts["with_demo_source"] += 1
            status = "OK_DEMO"
        else:
            counts["missing_demo_source"] += 1
            status = "MISSING_DEMO_SOURCE"
        rows.append({
            "page": rel,
            "tickers": ";".join(tickers[:4]),
            "status": status,
            "demo_links": ";".join(demo[:2]),
            "production_links": ";".join(prod[:2]),
        })
    return rows, counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="audit")
    args = ap.parse_args()

    all_rows: list[dict] = []
    summary = {"pages": {}, "totals": {}}
    totals = {"pages": 0, "data_rows": 0, "with_demo_source": 0,
              "missing_demo_source": 0, "production_links": 0}

    for label, tree in PAGE_TREES:
        for rel in iter_pages(args.root, tree):
            rows, counts = audit_file(args.root, rel)
            if not rows and counts["non_data_rows"] == 0:
                continue
            summary["pages"][rel] = counts
            all_rows.extend(rows)
            totals["pages"] += 1
            for k in ("data_rows", "with_demo_source", "missing_demo_source", "production_links"):
                totals[k] += counts[k]

    summary["totals"] = totals

    out_dir = os.path.join(args.root, args.out)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "rootsource-7695ba1b.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page", "tickers", "status",
                                           "demo_links", "production_links"])
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    with open(os.path.join(out_dir, "rootsource-7695ba1b.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"pages checked      : {totals['pages']}")
    print(f"market rows        : {totals['data_rows']}")
    print(f"  with demo source : {totals['with_demo_source']}")
    print(f"  MISSING source   : {totals['missing_demo_source']}")
    print(f"  production links : {totals['production_links']}")
    bad = [r for r in all_rows if r["status"] != "OK_DEMO" or r["production_links"]]
    for r in bad[:20]:
        print(f"  ! {r['page']} :: {r['tickers']} :: {r['status']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
