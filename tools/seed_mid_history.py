"""Seed ``data/mid_history.json`` from real collector snapshots in git history.

The model shortlist compares the current order book with the book as it was
in the previous snapshot, so it needs a history of book mids. On a fresh
install that history is empty and the shortlist stays blank for a run or two
until the scheduled collector has written a couple of snapshots.

This tool fills the history in one step from snapshots that the collector
already produced and that are already committed to the repository, so every
number in it came from the official Kalshi demo API through
``collector/collector.py``. It reads ``data/live.json`` from past commits of
the current branch; it never calls the API itself.

    python3 tools/seed_mid_history.py --revisions 4

Each snapshot contributes one point per market and one entry to the trail.
The most recent snapshot becomes ``points`` (the current book) and the rest
become the trail.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector.shortlist import HISTORY_PATH, TRAIL_LEN, book_of  # noqa: E402


def snapshot_at(revision: str) -> dict | None:
    proc = subprocess.run(
        ["git", "show", f"{revision}:data/live.json"],
        capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revisions", type=int, default=4,
                    help="how many past data/live.json revisions to read")
    ap.add_argument("--out", default=HISTORY_PATH)
    args = ap.parse_args()

    revisions = [f"HEAD~{i}" for i in range(args.revisions)]
    snaps = []
    for rev in revisions:
        snap = snapshot_at(rev)
        if snap:
            snaps.append((rev, snap))
    # Oldest first so the trail is chronological.
    snaps.reverse()
    if not snaps:
        print("no snapshots found in git history", file=sys.stderr)
        return 1

    points: dict[str, dict] = {}
    trail: dict[str, list[float]] = {}
    for rev, snap in snaps:
        for event in snap.get("events") or []:
            ticker = event.get("ticker")
            if not ticker:
                continue
            bid, ask, mid = book_of(event)
            if mid is None:
                continue
            points[ticker] = {"ts": snap.get("generated_at_ts"),
                               "bid": bid, "ask": ask, "mid": mid}
            trail.setdefault(ticker, []).append(mid)
    trail = {t: v[-TRAIL_LEN:] for t, v in trail.items()}

    payload = {
        "generated_at": snaps[-1][1].get("generated_at"),
        "generated_at_ts": snaps[-1][1].get("generated_at_ts"),
        "source": ("git history of data/live.json, written by collector/collector.py "
                   "from the official Kalshi demo API"),
        "snapshots": [{"revision": rev, "generated_at": snap.get("generated_at")}
                      for rev, snap in snaps],
        "points": points,
        "trail": trail,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print(json.dumps({"snapshots": len(snaps), "markets": len(points),
                      "out": args.out}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
