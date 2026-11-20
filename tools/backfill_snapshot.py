"""Re-derive snapshot groupings that a code change introduced.

Why this exists: ``data/live.json`` is written by the collector on GitHub
Actions. When the *grouping* rules in ``collector/collector.py`` are fixed, the
already-collected snapshot still holds the old, wrong grouping until the next
scheduled run. This tool applies the current code to the data already in the
repository, so the published site is correct immediately instead of one cycle
late.

It never invents a value. It only re-runs the collector's own functions over
records that are already in the repository:

* ``events_by_topic`` — computed from ``events``, which is the collector's
  ranked table; the order inside each topic is preserved exactly.
* ``resolutions`` — recomputed from ``data/resolutions.json`` (official
  ``result`` / ``settlement_value_dollars`` / ``settlement_ts`` fields read from
  ``GET /markets?status=settled``) plus ``data/series_cache.json`` for the
  series-to-topic map.
* ``observations`` — copied from each event's stored observation, so the next
  collector run has a real previous sample to compare against.

Every row keeps the source URL it already carried.

Usage:  python3 tools/backfill_snapshot.py [--check]
        --check  report what would change, write nothing (exit 1 if stale)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector.alerts import alert_record_valid, is_publishable
from collector.collector import (DATA_DIR, LIVE_PATH, MAX_SUPPRESSED,
                                 RESOLUTIONS_PATH, TOP_PER_TOPIC, load_json,
                                 resolutions_by_topic, save_json)

SERIES_CACHE = os.path.join(ROOT, "data", "series_cache.json")
TOPIC_ORDER = ["gas-prices", "elections", "culture", "crypto", "golf"]


def rebuild(live: dict[str, Any], res_map: dict[str, dict[str, Any]],
            series_cache: dict[str, Any]) -> dict[str, Any]:
    out = dict(live)

    # 1. per-topic event ranking (same rule as collector.collect)
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for row in out.get("events") or []:
        bucket = by_topic.setdefault(row.get("topic") or "unknown", [])
        if len(bucket) < TOP_PER_TOPIC:
            bucket.append(row)
    ordered = {slug: by_topic[slug] for slug in TOPIC_ORDER if slug in by_topic}
    ordered.update({k: v for k, v in by_topic.items() if k not in ordered})
    out["events_by_topic"] = ordered
    out["top_per_topic"] = TOP_PER_TOPIC

    # 2. resolution attribution
    series_to_topic: dict[str, str] = {}
    for slug, cached in (series_cache or {}).items():
        for row in (cached or {}).get("series") or []:
            if row.get("ticker"):
                series_to_topic.setdefault(row["ticker"], slug)
    for row in out.get("events") or []:
        if row.get("series_ticker") and row.get("topic"):
            series_to_topic.setdefault(row["series_ticker"], row["topic"])
    out["resolutions"] = resolutions_by_topic(res_map, series_to_topic)
    attributed = sum(len(v or []) for v in out["resolutions"].values())
    out["resolutions_count"] = len(res_map)
    out["resolutions_attributed"] = attributed
    out["resolutions_unattributed"] = max(0, len(res_map) - attributed)

    # 3. alert integrity: apply the current gate to the stored buffer and keep
    #    the held-back rows visible for review instead of deleting them.
    def keep(a):
        # Same two rules the collector applies (quote basis + two-sidedness).
        return alert_record_valid(a) and is_publishable(a)

    # Candidates come from both the published snapshot and the alert store, so a
    # second run does not forget rows the first run already held back. The store
    # is the collector's own buffer (data/alerts.json) and may predate this rule.
    store_alerts = (load_json(os.path.join(DATA_DIR, "alerts.json"), {})
                    .get("alerts") or [])
    candidates: list[dict] = []
    seen_ids: set[str] = set()
    for a in (out.get("alerts") or []) + (out.get("alerts_suppressed") or []) \
            + store_alerts:
        key = a.get("id") or f"{a.get('ticker')}:{a.get('ts')}"
        if key not in seen_ids:
            seen_ids.add(key)
            candidates.append(a)
    out["alerts"] = [a for a in candidates if keep(a)]
    held = [a for a in candidates if not keep(a)]

    # Rows written before the gate existed carry no baseline quote, so they
    # cannot be re-checked. They are logged as unverifiable rather than either
    # republished or quietly dropped -- the reviewer can open the API link.
    for a in held:
        if a.get("reference_quote") is None:
            a["integrity_note"] = ("recorded before the integrity gate; no "
                                   "baseline quote was stored, so the move "
                                   "cannot be re-checked")
    out["alerts_suppressed"] = held[:MAX_SUPPRESSED]
    out["alerts_publishable"] = len(out["alerts"])
    out["alerts_suppressed_count"] = len(held)

    # 4. observations, verbatim from what the collector already stored per event
    if "observations" not in out:
        rows = [e["observation"] for e in out.get("events") or []
                if isinstance(e.get("observation"), dict)]
        if rows:
            out["observations"] = rows
    return out


def main() -> int:
    check = "--check" in sys.argv
    live = load_json(LIVE_PATH, {})
    if not live:
        print("no snapshot at", LIVE_PATH)
        return 1
    res_map = (load_json(RESOLUTIONS_PATH, {}) or {}).get("resolutions") or {}
    series_cache = load_json(SERIES_CACHE, {}) or {}

    rebuilt = rebuild(live, res_map, series_cache)

    attributed = sum(len(v or []) for v in (rebuilt["resolutions"] or {}).values())
    summary = {
        "alerts_publishable": rebuilt.get("alerts_publishable"),
        "alerts_suppressed": rebuilt.get("alerts_suppressed_count"),
        "events_by_topic": {k: len(v) for k, v in rebuilt["events_by_topic"].items()},
        "resolutions_attributed": attributed,
        "resolutions_unattributed": max(0, len(res_map) - attributed),
        "observations": len(rebuilt.get("observations") or []),
    }
    changed = {k: rebuilt[k] != live.get(k) for k in
               ("events_by_topic", "top_per_topic", "resolutions",
                "resolutions_count", "resolutions_attributed",
                "resolutions_unattributed", "alerts", "alerts_suppressed",
                "alerts_publishable", "alerts_suppressed_count", "observations")}
    print(json.dumps({**summary, "changed": changed}, indent=1))
    if check:
        return 1 if any(changed.values()) else 0
    if any(changed.values()):
        save_json(LIVE_PATH, rebuilt)
        print("wrote", LIVE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
