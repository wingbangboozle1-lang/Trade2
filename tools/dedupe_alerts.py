#!/usr/bin/env python3
"""One-off + rerunnable cleanup of already-published alert rows (R-D-01).

Two operations on ``data/alerts.json`` and the ``alerts`` / ``high_roi_alerts``
arrays inside ``data/live.json``:

1. **Dedupe** by (ticker, reference-window ts, direction) keeping the row with
   the largest ``abs_delta`` — the same fold ``collector.alerts.dedupe_alerts``
   applies to fresh runs. Rows written before the id change carried a per-run
   timestamp in their id, so the old ids are normalised to the structural key
   before folding.
2. **Backfill labels** (``spread`` / ``thin_book`` / ``basis``) on rows that
   predate the depth-aware rule, using the ``yes_bid`` / ``yes_ask`` already
   recorded on each row. Nothing is invented: if the quotes are absent the
   labels are left as "legacy midpoint" and the row is marked thin.

Usage: ``python3 tools/dedupe_alerts.py`` (idempotent). The site is rebuilt
afterwards by ``python3 -m site_build.build``.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERTS_VERSION = 3
MAX_SPREAD = 0.20


def structural_key(row: dict) -> str:
    window = int(row.get("previous_ts") or row.get("ts") or 0)
    return f"{row.get('ticker','')}:{window}:{row.get('direction','')}"


def fold(rows: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for row in rows:
        key = structural_key(row)
        row["id"] = key  # normalise legacy per-run ids
        cur = best.get(key)
        if cur is None:
            best[key] = row
            continue
        new_d = row.get("abs_delta") or 0
        cur_d = cur.get("abs_delta") or 0
        if new_d > cur_d or (new_d == cur_d and (row.get("ts") or 0) > (cur.get("ts") or 0)):
            best[key] = row
    # Second fold: the same numeric move re-measured on a later bar within 24h
    # is the same sustained condition (see collector/alerts.dedupe_alerts).
    day = 86400.0
    distinct: list[dict] = []
    for row in sorted(best.values(), key=lambda r: r.get("ts") or 0, reverse=True):
        sig = (row.get("ticker"), row.get("direction"),
               round(row.get("previous") or 0, 4),
               round(row.get("current") or 0, 4))
        ts = row.get("ts") or 0
        if any((k.get("ticker"), k.get("direction"),
                round(k.get("previous") or 0, 4),
                round(k.get("current") or 0, 4)) == sig
               and abs((k.get("ts") or 0) - ts) <= day for k in distinct):
            continue
        distinct.append(row)
    return distinct


def backfill(row: dict) -> dict:
    yb, ya = row.get("yes_bid"), row.get("yes_ask")
    if yb is not None and ya is not None:
        spread = round(ya - yb, 4)
        row["spread"] = spread
        if "basis" not in row:
            row["basis"] = "mid"  # legacy rows were midpoint-measured
        row["thin_book"] = bool(row.get("thin_book")) or spread > MAX_SPREAD
    else:
        if "basis" not in row:
            row["basis"] = "legacy midpoint"
        row["thin_book"] = True
    return row


def process(rows: list[dict]) -> list[dict]:
    return fold([backfill(r) for r in rows])


def main() -> int:
    alerts_path = os.path.join(ROOT, "data", "alerts.json")
    live_path = os.path.join(ROOT, "data", "live.json")

    store = json.load(open(alerts_path))
    before = len(store.get("alerts", []))
    store["alerts"] = process(store.get("alerts", []))
    store["version"] = ALERTS_VERSION
    json.dump(store, open(alerts_path, "w"), indent=1)

    live = json.load(open(live_path))
    for key in ("alerts", "high_roi_alerts"):
        if isinstance(live.get(key), list):
            live[key] = process(live[key])
    json.dump(live, open(live_path, "w"), indent=1, default=str)

    print(json.dumps({
        "alerts_before": before,
        "alerts_after": len(store["alerts"]),
        "live_alerts": len(live.get("alerts", [])),
        "high_roi_alerts": len(live.get("high_roi_alerts", [])),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
