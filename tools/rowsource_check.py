#!/usr/bin/env python3
"""Row-level source-link audit for every published table (T20, arena-4f92a11c).

Report-only. Reads the published JSON tables, checks every row, and writes:
  * audit/rowsource-4f92a11c.csv   one line per row (for manual review)
  * audit/rowsource-4f92a11c.json  summary counts and the issue list

Checks, per row:
  source     the row has a primary source URL (a `source_url`-style field)
  host       the source host is an official Kalshi host, classified as
             DEMO (external-api.demo.kalshi.co, demo-api.kalshi.co) or
             PRODUCTION (external-api.kalshi.com, api.elections.kalshi.com)
  docs       the row links an official Kalshi documentation page (where the table has one)
  values     value fields that are blank (None or "") are counted as UNVERIFIED

Nothing is inferred or filled in. A blank value stays blank and is listed.
Settlement sources named inside a market record (for example foxsports.com) are
reported separately as third-party settlement references, not as official sources.

Usage:  python3 tools/rowsource_check.py [--root .] [--out audit]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

DEMO_HOSTS = {"external-api.demo.kalshi.co", "demo-api.kalshi.co", "external-api-ws.demo.kalshi.co"}
PRODUCTION_HOSTS = {"external-api.kalshi.com", "api.elections.kalshi.com", "external-api-ws.kalshi.com"}
# Official Kalshi web/documentation/asset hosts (documentation and contract-terms links).
OFFICIAL_DOC_HOSTS = {"docs.kalshi.com", "kalshi.com", "www.kalshi.com", "assets.kalshi.com"}


def host_of(url) -> str:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return ""
    return (urlparse(url).hostname or "").lower()


def classify_source(url) -> str:
    """Return DEMO, PRODUCTION, OFFICIAL_DOC, THIRD_PARTY, or MISSING."""
    h = host_of(url)
    if not h:
        return "MISSING"
    if h in DEMO_HOSTS:
        return "DEMO"
    if h in PRODUCTION_HOSTS:
        return "PRODUCTION"
    if h in OFFICIAL_DOC_HOSTS:
        return "OFFICIAL_DOC"
    return "THIRD_PARTY"


def is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


@dataclass
class TableSpec:
    table_id: str
    file: str
    rows_path: tuple          # keys to walk to the row list (dict keys; "[]" means iterate a dict's values)
    id_key: str               # row identifier field
    source_key: str           # primary source URL field
    docs_key: str | None = None   # optional official documentation link field
    value_keys: tuple = ()    # fields that must be non-blank to be verified
    # derived field -> official field it is computed from (used to explain a blank derived value)
    derived_of: dict = field(default_factory=dict)


@dataclass
class RowResult:
    table: str
    row_id: str
    source_class: str
    source_url: str
    docs_present: str
    blank_values: str
    status: str
    notes: list = field(default_factory=list)


def _walk(doc, path):
    """Yield row dicts found at `path` inside `doc`. A path element of '*' iterates dict values."""
    nodes = [doc]
    for key in path:
        nxt = []
        for n in nodes:
            if key == "*":
                if isinstance(n, dict):
                    nxt.extend(n.values())
            elif isinstance(n, dict) and key in n:
                nxt.append(n[key])
        nodes = nxt
    for n in nodes:
        if isinstance(n, list):
            for r in n:
                if isinstance(r, dict):
                    yield r


def table_specs() -> list[TableSpec]:
    return [
        TableSpec("kd.markets", "kalshi-dashboard/data/latest.json", ("markets",), "ticker",
                  "source_url", None,
                  ("last_cents", "last_price_dollars", "yes_bid_dollars", "yes_ask_dollars", "open_interest", "volume_24h"),
                  {"last_cents": "last_price_dollars"}),
        TableSpec("kd.topic_events", "kalshi-dashboard/data/latest.json", ("topics", "*", "events"), "event_ticker",
                  "source_url"),
        TableSpec("kd.resolved_pending", "kalshi-dashboard/data/resolved.json", ("pending",), "ticker",
                  "source_url"),
        TableSpec("kd.resolved", "kalshi-dashboard/data/resolved.json", ("resolved",), "ticker",
                  "source_url", None, ("result",)),
        TableSpec("kd.alerts", "kalshi-dashboard/data/alerts.json", ("alerts",), "ticker", "source_url"),
        TableSpec("kd.trade_positions", "kalshi-dashboard/data/trades.json", ("positions",), "ticker", "source_url"),
        TableSpec("docs.markets", "docs/data/markets.json", ("rows",), "ticker", "source_url", "docs_url",
                  ("yes_bid", "yes_ask", "last_price", "title", "expected_expiration")),
        TableSpec("docs.resolutions", "docs/data/resolutions.json", ("rows",), "ticker", "source_url", "docs_url",
                  ("result", "settlement_value")),
        TableSpec("docs.alerts", "docs/data/alerts.json", ("alerts",), "ticker", "source_url", "docs_url"),
        TableSpec("docs.portfolio_trades", "docs/data/portfolio.json", ("trades",), "ticker", "source_url"),
    ]


def audit_table(spec: TableSpec, doc) -> tuple[list[RowResult], dict]:
    rows = list(_walk(doc, spec.rows_path))
    results: list[RowResult] = []
    counts = {"rows": len(rows), "source_present": 0, "demo": 0, "production": 0, "official_doc": 0,
              "third_party_or_other": 0, "missing_source": 0, "docs_present": 0, "docs_expected": 0,
              "rows_with_blank_values": 0, "blank_value_cells": 0, "ok_demo": 0}
    for r in rows:
        row_id = str(r.get(spec.id_key) or "")
        url = r.get(spec.source_key)
        cls = classify_source(url)
        notes = []
        if cls == "MISSING":
            counts["missing_source"] += 1
            notes.append("no primary source URL")
        else:
            counts["source_present"] += 1
        if cls == "DEMO":
            counts["demo"] += 1
        elif cls == "PRODUCTION":
            counts["production"] += 1
            notes.append("production host (task requires demo)")
        elif cls == "THIRD_PARTY":
            counts["third_party_or_other"] += 1
            notes.append("primary source is not an official Kalshi host")
        if cls in ("OFFICIAL_DOC",):
            counts["official_doc"] += 1

        docs_cell = ""
        if spec.docs_key:
            counts["docs_expected"] += 1
            d = r.get(spec.docs_key)
            if host_of(d) == "docs.kalshi.com" or classify_source(d) == "OFFICIAL_DOC":
                counts["docs_present"] += 1
                docs_cell = d
            else:
                notes.append("no official docs link")

        blanks = [k for k in spec.value_keys if is_blank(r.get(k))]
        if blanks:
            counts["rows_with_blank_values"] += 1
            counts["blank_value_cells"] += len(blanks)
            notes.append("UNVERIFIED blank: " + ", ".join(blanks))
            for k in blanks:
                off = spec.derived_of.get(k)
                if off and not is_blank(r.get(off)):
                    counts["derived_blank_official_present"] = counts.get("derived_blank_official_present", 0) + 1
                    notes.append(f"{k} blank but official {off}={r.get(off)} is present")

        if cls == "MISSING":
            status = "MISSING_SOURCE"
        elif cls in ("THIRD_PARTY",):
            status = "NON_OFFICIAL_SOURCE"
        elif cls == "PRODUCTION":
            status = "OFFICIAL_PRODUCTION_HOST"
        elif cls == "DEMO" and not (spec.docs_key and not docs_cell):
            status = "OK_DEMO"
            counts["ok_demo"] += 1
        else:
            status = "PARTIAL"
        if blanks and status == "OK_DEMO":
            status = "OK_DEMO_WITH_UNVERIFIED_VALUES"

        results.append(RowResult(spec.table_id, row_id, cls, url or "", docs_cell,
                                 ";".join(blanks), status, notes))
    return results, counts


def third_party_settlement_refs(doc) -> dict:
    """Count settlement-source hosts named inside market records (informational)."""
    hosts: dict[str, int] = {}
    for r in _walk(doc, ("markets",)):
        for s in r.get("settlement_sources") or []:
            h = host_of((s or {}).get("url"))
            if h:
                hosts[h] = hosts.get(h, 0) + 1
    return dict(sorted(hosts.items(), key=lambda kv: -kv[1]))


def run(root: str, out_dir: str) -> dict:
    summary = {"tables": {}, "settlement_source_hosts": {}, "issues": []}
    all_rows: list[RowResult] = []
    loaded: dict[str, object] = {}
    for spec in table_specs():
        path = os.path.join(root, spec.file)
        if spec.file not in loaded:
            with open(path, encoding="utf-8") as fh:
                loaded[spec.file] = json.load(fh)
        results, counts = audit_table(spec, loaded[spec.file])
        summary["tables"][spec.table_id] = {"file": spec.file, **counts}
        all_rows.extend(results)
        for rr in results:
            if rr.status not in ("OK_DEMO",):
                summary["issues"].append({"table": rr.table, "row": rr.row_id, "status": rr.status,
                                          "notes": "; ".join(rr.notes)})
    if "kalshi-dashboard/data/latest.json" in loaded:
        summary["settlement_source_hosts"] = third_party_settlement_refs(loaded["kalshi-dashboard/data/latest.json"])

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "rowsource-4f92a11c.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["table", "row_id", "source_class", "source_url", "docs_url", "blank_values", "status", "notes"])
        for rr in all_rows:
            w.writerow([rr.table, rr.row_id, rr.source_class, rr.source_url, rr.docs_present,
                        rr.blank_values, rr.status, "; ".join(rr.notes)])
    with open(os.path.join(out_dir, "rowsource-4f92a11c.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="audit")
    args = ap.parse_args()
    s = run(args.root, os.path.join(args.root, args.out))
    for name, c in s["tables"].items():
        print(f"{name:24s} rows={c['rows']:4d} demo={c['demo']:4d} prod={c['production']:4d} "
              f"missing={c['missing_source']:3d} docs={c['docs_present']}/{c['docs_expected']} "
              f"blank_rows={c['rows_with_blank_values']}")
    print(f"issues listed: {len(s['issues'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
