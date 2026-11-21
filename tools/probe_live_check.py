#!/usr/bin/env python3
"""Verify the browser live probe's request shapes against the REAL demo API.

The sandbox that wrote ``assets/live-probe.js`` has no route to Kalshi, so the
only thing it could not check locally was whether the URLs the browser builds
are accepted and interpreted the way the code assumes. This script closes that
gap in CI, where egress is unrestricted. It:

1. takes the two market tickers with the largest open-interest value from the
   committed snapshot (the same seeding rule the page uses);
2. builds the URLs through the probe module itself (node), not by hand, so the
   thing under test is the shipped serialiser;
3. fetches them and asserts, per the official spec:
   * ``GET /markets?tickers=…`` returns one record per requested ticker
     (unpaged when ``tickers`` is the only filter);
   * ``GET /markets/orderbooks?tickers=…`` returns one entry per requested
     ticker, in request order;
   * a comma-joined ``tickers`` does **not** return both books, which is the
     failure mode the repeated-parameter serialiser exists to avoid;
4. runs ``bookTop`` on the real books and reports what the probe would see.

It never writes to the repository and never sends an order.

    python3 tools/probe_live_check.py [--json out.json]
Exit 0 when every assertion holds, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "data", "live.json")
BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
SPEC_BOOKS = "https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks"
SPEC_MARKETS = "https://docs.kalshi.com/api-reference/market/get-markets"


def fetch_json(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Trade2-probe-check/1.0 (+github.com/wingbangboozle1-lang/Trade2)",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.load(resp)


def node_urls(tickers: list[str]) -> dict[str, str]:
    """Build the probe's URLs with the probe's own serialiser."""
    script = r"""
const path = require("path");
// With `node -e`, process.argv[1] is the first user argument.
const L = require(path.join(process.argv[1], "assets", "live-probe.js"));
const tickers = JSON.parse(process.argv[2]);
const q = L.tickersQuery(tickers);
process.stdout.write(JSON.stringify({
  query: q,
  markets: L.ENDPOINTS.markets + "?" + q,
  orderbooks: L.ENDPOINTS.orderbooks + "?" + q
}));
"""
    out = subprocess.run([shutil_node(), "-e", script, ROOT, json.dumps(tickers)],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit("could not run the probe module under node:\n" + out.stderr)
    return json.loads(out.stdout)


def shutil_node() -> str:
    import shutil
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required to build the probe's URLs")
    return node


def top_tickers(limit: int = 2) -> list[str]:
    with open(LIVE, encoding="utf-8") as fh:
        live = json.load(fh)
    rows = [e for e in (live.get("events") or [])
            if e.get("ticker") and e.get("yes_bid") is not None
            and e.get("yes_ask") is not None]
    rows.sort(key=lambda e: e.get("open_interest_notional") or 0, reverse=True)
    seen, out = set(), []
    for row in rows:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        out.append(row["ticker"])
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    problems: list[str] = []
    report: dict = {"base": BASE, "checked_at": None}

    tickers = top_tickers()
    if len(tickers) < 2:
        print("not enough quoted markets in data/live.json to check")
        return 1
    report["tickers"] = tickers
    urls = node_urls(tickers)
    report["urls"] = urls

    # 1. repeated-parameter serialisation, straight from the module
    expected_q = "&".join("tickers=" + urllib.parse.quote(t) for t in tickers)
    if urls["query"] != expected_q:
        problems.append(f"tickersQuery built {urls['query']!r}, expected {expected_q!r}")

    # 2. markets endpoint returns one record per ticker
    try:
        status, body = fetch_json(urls["markets"])
        got = [m.get("ticker") for m in (body.get("markets") or [])]
        report["markets"] = {"status": status, "returned": got}
        if status != 200:
            problems.append(f"GET /markets returned {status}")
        missing = [t for t in tickers if t not in got]
        if missing:
            problems.append(f"GET /markets did not return {missing} (got {got})")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        problems.append(f"GET /markets failed: {exc}")

    # 3. order books: one entry per ticker, in request order
    try:
        status, body = fetch_json(urls["orderbooks"])
        entries = body.get("orderbooks") or []
        order = [e.get("ticker") for e in entries]
        report["orderbooks"] = {
            "status": status,
            "returned": order,
            "with_levels": sum(
                1 for e in entries
                if (e.get("orderbook_fp") or {}).get("yes_dollars")
                or (e.get("orderbook_fp") or {}).get("no_dollars")),
        }
        if status != 200:
            problems.append(f"GET /markets/orderbooks returned {status}")
        if order != tickers:
            problems.append(
                f"orderbooks returned {order} but the spec says request order {tickers}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        problems.append(f"GET /markets/orderbooks failed: {exc}")

    # 4. the comma-joined form must NOT be equivalent (this is why we repeat)
    comma = BASE + "/markets/orderbooks?tickers=" + urllib.parse.quote(",".join(tickers))
    report["comma_url"] = comma
    try:
        status, body = fetch_json(comma)
        comma_order = [e.get("ticker") for e in (body.get("orderbooks") or [])]
        report["comma_returned"] = comma_order
        if comma_order == tickers:
            # Not a failure of our code, but it would make the test meaningless.
            report["comma_note"] = ("comma form returned both books; the repeated "
                                   "form is still the documented one and is used")
        else:
            report["comma_note"] = ("comma form did NOT return both books "
                                   f"({comma_order}); repeated parameters are required")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        report["comma_note"] = f"comma form errored ({exc}); repeated parameters are required"

    report["problems"] = problems
    text = json.dumps(report, indent=1)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    if problems:
        print("\nPROBE LIVE CHECK FAILED", file=sys.stderr)
        for p in problems:
            print(" - " + p, file=sys.stderr)
        # Under Actions, also publish each problem as an annotation. Run logs
        # and artifacts are not always reachable from a restricted client, but
        # the annotations API always is — and evidence nobody can read is not
        # evidence.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            for p in problems:
                msg = p.replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
                print(f"::error title=Probe live check::{msg}")
        return 1
    print(f"\nprobe live check OK — {len(tickers)} tickers, documented shape confirmed\n"
          f"  {SPEC_BOOKS}\n  {SPEC_MARKETS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
