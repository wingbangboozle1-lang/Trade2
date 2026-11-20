#!/usr/bin/env python3
"""Fresh line-by-line verification of the published root site against the
official Kalshi demo API (task F-479-2, session arena-479bbd2f).

This sandbox cannot reach Kalshi hosts (egress is limited), so this tool runs
on a GitHub Actions runner (workflow `.github/workflows/verify-479.yml`,
workflow_dispatch only). It re-fetches the exact rows the published site shows
from the official demo endpoints and compares field by field:

  1. Per topic (gas-prices, elections, culture, crypto, golf): the top active
     event by published `open_interest_notional` — the brief's "highest dollar
     amount live events" ranking. Recomputed as
     `round(open_interest_fp * notional_value_dollars, 2)` exactly like
     `collector.alerts.rank_events` documents in-code, from the FRESH payload.
  2. The market row itself (`GET /markets?ticker=...`): title (yes_sub_title
     fallback, stripped), YES bid/ask (order-book best bids with the market
     record's own *_dollars quotes as fallback — the exact derivation in
     `collector.alerts.observe`), volume_fp, open_interest_fp, notional value,
     status, close time, result — compared field by field.
  3. The order book (`GET /markets/{ticker}/orderbook?depth=25`): best YES bid,
     best NO bid, implied YES ask, and total bid-side depth in contracts,
     recomputed with the derivation documented at
     https://docs.kalshi.com/getting_started/orderbook_responses.md and used by
     `collector.alerts.analyse_liquidity`.

Verdicts are honest: EXACT (equal to the fresh payload), DRIFT (the live
market moved since the snapshot — both values shown, never silently equalised),
or UNVERIFIED (nothing was guessed; reason recorded). Every comparison row
carries the official endpoint URL that produced it.

Output: audit/verify-479.json (machine evidence incl. raw response heads) and
audit/verify-479.md (human-readable table). Exit code 0 unless the tool itself
crashed — drift is a fact about the market, not a broken site.

Usage: python3 tools/verify_rows_479.py [--root .] [--timeout 20] [--per-topic N]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

REST_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
DOC_MARKETS = "https://docs.kalshi.com/api-reference/market/get-markets"
DOC_ORDERBOOK = "https://docs.kalshi.com/getting_started/orderbook_responses.md"
TOPICS = ["gas-prices", "elections", "culture", "crypto", "golf"]
LEVELS = 25  # same depth the collector requests (collector/runner.py)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "Trade2-verify-479/1.0")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return {"status": r.status, "headers": dict(r.headers),
                "body": json.loads(r.read().decode("utf-8"))}


def dollars(v) -> float | None:
    """Parse a dollars field (e.g. yes_bid_dollars "0.0350") the way
    collector.alerts.dollars does; None when absent/unparseable."""
    if v is None:
        return None
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return None


def count(v) -> float | None:
    """Parse a contracts field (e.g. volume_fp "3064.00")."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def best_bid(levels) -> float | None:
    """Order-book price levels arrive lowest-first; best bid is the last one."""
    if not levels:
        return None
    price = dollars(levels[-1][0]) if isinstance(levels[-1], (list, tuple)) and len(levels[-1]) >= 2 else None
    return price


def side_depth(levels) -> tuple[float | None, float | None]:
    """Total bid-side depth in contracts (and dollars) for one side."""
    contracts = 0.0
    dollars_sum = 0.0
    seen = False
    for row in levels or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = dollars(row[0])
        size = count(row[1])
        if price is None or size is None:
            continue
        seen = True
        contracts += size
        dollars_sum += price * size
    if not seen:
        return None, None
    return round(contracts, 2), round(dollars_sum, 2)


def compare(field: str, published, fresh, source_url: str,
            note: str = "") -> dict:
    if published is None or fresh is None:
        verdict = "UNVERIFIED"
        note = note or ("published value blank" if published is None
                        else "fresh value absent")
    elif isinstance(published, (int, float)) and isinstance(fresh, (int, float)):
        verdict = "EXACT" if abs(published - fresh) < 5e-7 else "DRIFT"
    else:
        verdict = "EXACT" if str(published) == str(fresh) else "DRIFT"
    return {"field": field, "published": published, "fresh": fresh,
            "verdict": verdict, "source_url": source_url, "note": note}


def verify_row(market: dict, book: dict | None, published_row: dict,
               mkt_url: str, ob_url: str) -> list[dict]:
    """Field-by-field comparison of one published event row vs fresh payloads.

    Quote derivation mirrors collector.alerts.observe() exactly: book best
    bids first, the market record's own *_dollars quotes as fallback.
    """
    ob = (book or {}).get("orderbook_fp") or {}
    yes_levels = ob.get("yes_dollars") or []
    no_levels = ob.get("no_dollars") or []
    yb = best_bid(yes_levels)
    nb = best_bid(no_levels)

    yes_bid = yb if yb is not None else dollars(market.get("yes_bid_dollars"))
    yes_ask = (round(1.0 - nb, 4) if nb is not None
               else dollars(market.get("yes_ask_dollars")))

    title = str(market.get("yes_sub_title") or market.get("title") or "").strip()
    oi = count(market.get("open_interest_fp"))
    vol = count(market.get("volume_fp"))
    notional = dollars(market.get("notional_value_dollars"))

    rows = [
        compare("title (yes_sub_title fallback, stripped)",
                published_row.get("title"), title, mkt_url),
        compare("yes_bid ($) [book best bid, else yes_bid_dollars]",
                published_row.get("yes_bid"), yes_bid, mkt_url),
        compare("yes_ask ($) [1 - best no bid, else yes_ask_dollars]",
                published_row.get("yes_ask"), yes_ask, mkt_url),
        compare("open_interest (open_interest_fp)",
                published_row.get("open_interest_contracts"), oi, mkt_url),
        compare("volume (volume_fp)", published_row.get("volume_contracts"),
                vol, mkt_url),
        compare("notional_value_dollars", published_row.get("notional_per_contract"),
                notional, mkt_url),
        # The published dollar-at-stake ranking value, recomputed from FRESH
        # fields with the exact formula documented in rank_events:
        compare("open_interest_notional = oi x notional",
                published_row.get("open_interest_notional"),
                round((oi or 0.0) * (notional if notional is not None else 1.0), 2),
                mkt_url, "collector/alerts.py rank_events; " + DOC_MARKETS),
        compare("status (raw API value)", published_row.get("status"),
                market.get("status"), mkt_url),
        compare("close_time", published_row.get("close_time"),
                market.get("close_time"), mkt_url),
        compare("result", published_row.get("result"),
                market.get("result"), mkt_url),
    ]

    yc, _ = side_depth(yes_levels)
    nc, _ = side_depth(no_levels)
    pub_liq = published_row.get("liquidity") or {}
    rows += [
        compare("book best_yes_bid ($)", pub_liq.get("best_yes_bid"), yb, ob_url),
        compare("book best_no_bid ($)", pub_liq.get("best_no_bid"), nb, ob_url),
        compare("book implied_yes_ask ($) = 1 - best_no_bid",
                pub_liq.get("best_yes_ask"),
                round(1.0 - nb, 4) if nb is not None else None, ob_url,
                "derivation per " + DOC_ORDERBOOK),
        compare("book YES bid-side depth (contracts)",
                pub_liq.get("yes_bid_contracts"), yc, ob_url),
        compare("book NO bid-side depth (contracts)",
                pub_liq.get("no_bid_contracts"), nc, ob_url),
    ]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--per-topic", type=int, default=1,
                    help="top-N events per topic to verify")
    args = ap.parse_args()

    snap_path = f"{args.root}/data/live.json"
    with open(snap_path) as f:
        snap = json.load(f)

    events = [e for e in snap.get("events", []) if e.get("status") == "active"
              and e.get("ticker")]
    out: dict = {
        "tool": "tools/verify_rows_479.py",
        "session": "arena-479bbd2f",
        "task": "F-479-2",
        "rest_base": REST_BASE,
        "snapshot_path": snap_path,
        "snapshot_generated_at": snap.get("generated_at"),
        "verified_at": now(),
        "subjects": [],
        "notes": [],
    }

    for topic in TOPICS:
        pool = [e for e in events if e.get("topic") == topic]
        pool.sort(key=lambda e: (e.get("open_interest_notional") or 0.0), reverse=True)
        if not pool:
            out["notes"].append(
                f"{topic}: no active event in snapshot — UNVERIFIED (nothing guessed)")
            continue
        for pub in pool[: args.per_topic]:
            ticker = pub["ticker"]
            subject: dict = {"topic": topic,
                             "event_ticker": pub.get("event_ticker"),
                             "market_ticker": ticker, "title": pub.get("title"),
                             "published_open_interest_notional":
                                 pub.get("open_interest_notional"),
                             "checks": [], "raw": {}}

            mkt_url = f"{REST_BASE}/markets?ticker={urllib.parse.quote(ticker)}"
            market: dict | None = None
            try:
                resp = http_get_json(mkt_url, args.timeout)
                subject["raw"]["market"] = {
                    "url": mkt_url, "status": resp["status"],
                    "body_head": json.dumps(resp["body"])[:600]}
                markets = resp["body"].get("markets") or []
                if markets:
                    market = markets[0]
            except Exception as exc:  # evidence, never a crash
                subject["raw"]["market"] = {"url": mkt_url, "error": repr(exc)}

            ob_url = (f"{REST_BASE}/markets/{urllib.parse.quote(ticker)}"
                      f"/orderbook?depth={LEVELS}")
            book: dict | None = None
            try:
                resp = http_get_json(ob_url, args.timeout)
                subject["raw"]["orderbook"] = {
                    "url": ob_url, "status": resp["status"],
                    "body_head": json.dumps(resp["body"])[:600]}
                book = resp["body"]
            except Exception as exc:
                subject["raw"]["orderbook"] = {"url": ob_url, "error": repr(exc)}

            if market is None:
                subject["checks"].append({
                    "field": "market fetch", "published": "row exists on site",
                    "fresh": None, "verdict": "UNVERIFIED", "source_url": mkt_url,
                    "note": "fresh market fetch failed or returned no market"})
            else:
                subject["checks"].extend(
                    verify_row(market, book, pub, mkt_url, ob_url))
            out["subjects"].append(subject)

    counts: dict[str, int] = {}
    for s in out["subjects"]:
        for c in s["checks"]:
            counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    out["summary"] = counts

    import os
    os.makedirs(f"{args.root}/audit", exist_ok=True)
    with open(f"{args.root}/audit/verify-479.json", "w") as f:
        json.dump(out, f, indent=1)

    # Human-readable report — every row carries its official endpoint link.
    lines = [
        "# Fresh verification vs the official demo API — session `arena-479bbd2f` (F-479-2)",
        "",
        f"- Verified at: `{out['verified_at']}` (GitHub Actions runner)",
        f"- Published snapshot: `{snap_path}` generated at `{out['snapshot_generated_at']}`",
        f"- REST base: `{REST_BASE}` (documented at"
        " https://docs.kalshi.com/getting_started/demo_env)",
        f"- Verdict counts: {json.dumps(counts)}",
        "- DRIFT means the live market moved between the snapshot and this"
        " re-fetch; both values are shown, nothing was equalised or inferred.",
        "",
        "| Topic | Market | Field | Published | Fresh | Verdict | Source (official API) |",
        "| - | - | - | - | - | - | - |",
    ]
    for s in out["subjects"]:
        for c in s["checks"]:
            lines.append(
                f"| {s['topic']} | `{s['market_ticker']}` | {c['field']} | "
                f"{c['published']} | {c['fresh']} | **{c['verdict']}** |"
                f" [{c['source_url'].replace(REST_BASE, 'REST_BASE')}]({c['source_url']}) |")
    for n in out["notes"]:
        lines.append(f"\n> NOTE: {n}")
    with open(f"{args.root}/audit/verify-479.md", "w") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"summary": counts, "subjects": len(out["subjects"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
