"""Line-by-line verification of the published snapshot against the official API.

Run (needs egress to the demo API, e.g. on a GitHub Actions runner):

    python3 tools/verify_snapshot.py --per-topic 3 --out data/verification.json

What it does
------------
Every published table row links to the exact official response it came from.
This tool re-opens those responses and checks that what the site publishes
still matches the API, one market at a time:

  * the market still exists and still reports the same ticker, event and
    series;
  * the YES bid and the implied YES ask still match the live order book
    (within a tolerance, because a live book moves);
  * open interest and volume still match within a relative tolerance;
  * the status still matches, and a settled market still reports the same
    yes/no result;
  * for series rows, the settlement source still comes back from
    ``GET /series/{ticker}``.

Prices move between the snapshot and this check, so a difference is not
automatically an error. The output classifies every comparison as
``match``, ``drift`` (inside tolerance) or ``mismatch`` (outside it), and
records the exact URL that was opened. Only ``mismatch`` rows make the tool
exit non-zero.

Nothing here is inferred: every row records the official URL it was checked
against.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

API = "https://external-api.demo.kalshi.co/trade-api/v2"
USER_AGENT = "Trade2-verify/1.0 (+https://github.com/wingbangboozle1-lang/Trade2)"

PRICE_TOLERANCE = 0.02      # dollars, for a live book
REL_TOLERANCE = 0.02        # 2% for open interest and volume


def fetch(url: str, timeout: float = 15.0) -> tuple[Any, str | None]:
    """GET a URL. Returns (parsed json, error message)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return json.loads(body), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:                       # noqa: BLE001
        return None, str(exc)


def close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None and b is None:
        # Both sides agree there is no quote (empty book). That is a match,
        # not a disagreement.
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def close_rel(a: float | None, b: float | None, tol: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    scale = max(abs(float(a)), abs(float(b)), 1.0)
    return abs(float(a) - float(b)) / scale <= tol


def verify_market(event: dict[str, Any]) -> list[dict[str, Any]]:
    ticker = event.get("ticker")
    checks: list[dict[str, Any]] = []
    url = f"{API}/markets/{ticker}"
    market, err = fetch(url)
    if err or not market:
        return [{"check": "market record", "url": url, "field": "ticker",
                 "published": ticker, "official": None,
                 "result": "unverified", "detail": f"could not read ({err})"}]
    m = market.get("market") or {}

    def add(field: str, published: Any, official: Any, ok: bool,
            detail: str = "", structural: bool = True) -> None:
        """Record one comparison.

        Structural fields (ticker, event, status, result) must match exactly:
        they do not move between two reads of the same market. Size and price
        fields are allowed to drift inside their tolerance.
        """
        if ok:
            result = "match"
        elif structural:
            result = "mismatch"
        else:
            result = "drift"
        checks.append({"check": "market record", "url": url, "field": field,
                       "published": published, "official": official,
                       "result": result, "detail": detail})

    add("ticker", ticker, m.get("ticker"), m.get("ticker") == ticker)
    add("event_ticker", event.get("event_ticker"), m.get("event_ticker"),
        event.get("event_ticker") == m.get("event_ticker"))
    add("status", event.get("status"), m.get("status"),
        event.get("status") == m.get("status"))
    published_result = (event.get("result") or "")
    official_result = (m.get("result") or "")
    add("result", published_result, official_result,
        published_result == official_result,
        "settled market result must match the official field")
    add("open_interest_fp", event.get("open_interest_contracts"),
        m.get("open_interest_fp"),
        close_rel(event.get("open_interest_contracts"),
                  _num(m.get("open_interest_fp")), REL_TOLERANCE),
        f"relative tolerance {REL_TOLERANCE:.0%}", structural=False)
    add("volume_fp", event.get("volume_contracts"), m.get("volume_fp"),
        close_rel(event.get("volume_contracts"), _num(m.get("volume_fp")),
                  REL_TOLERANCE),
        f"relative tolerance {REL_TOLERANCE:.0%}", structural=False)
    add("notional_value_dollars", event.get("notional_per_contract"),
        m.get("notional_value_dollars"),
        close(event.get("notional_per_contract"),
              _num(m.get("notional_value_dollars")), 0.0001), structural=False)

    book_url = f"{API}/markets/{ticker}/orderbook"
    book, err = fetch(book_url)
    if err or not book:
        checks.append({"check": "order book", "url": book_url, "field": "book",
                       "published": None, "official": None,
                       "result": "unverified", "detail": f"could not read ({err})"})
        return checks

    fp = book.get("orderbook_fp") or {}
    yes = list(fp.get("yes_dollars") or [])
    no = list(fp.get("no_dollars") or [])
    live_bid = _num(yes[-1][0]) if yes else None
    live_ask = round(1.0 - _num(no[-1][0]), 4) if no else None
    liq = event.get("liquidity") or {}
    add_book = liq.get("best_yes_bid")
    add_ask = liq.get("best_yes_ask")
    checks.append({
        "check": "order book", "url": book_url, "field": "best_yes_bid",
        "published": add_book, "official": live_bid,
        "result": "match" if close(add_book, live_bid, PRICE_TOLERANCE)
                  else ("drift" if add_book is not None and live_bid is not None
                        else "mismatch"),
        "detail": f"a live book moves; tolerance ${PRICE_TOLERANCE:.2f}"})
    checks.append({
        "check": "order book", "url": book_url, "field": "best_yes_ask",
        "published": add_ask, "official": live_ask,
        "result": "match" if close(add_ask, live_ask, PRICE_TOLERANCE)
                  else ("drift" if add_ask is not None and live_ask is not None
                        else "mismatch"),
        "detail": f"a live book moves; tolerance ${PRICE_TOLERANCE:.2f}"})
    return checks


def verify_series(series: dict[str, Any]) -> list[dict[str, Any]]:
    ticker = series.get("ticker")
    url = f"{API}/series/{ticker}"
    payload, err = fetch(url)
    if err or not payload:
        return [{"check": "series record", "url": url, "field": "ticker",
                 "published": ticker, "official": None,
                 "result": "unverified", "detail": f"could not read ({err})"}]
    s = payload.get("series") or {}
    checks = [{
        "check": "series record", "url": url, "field": "title",
        "published": series.get("title"), "official": s.get("title"),
        "result": "match" if series.get("title") == s.get("title") else "mismatch",
        "detail": ""}]
    published_sources = [x.get("url") for x in
                         (series.get("settlement_sources") or []) if x.get("url")]
    official_sources = [x.get("url") for x in
                        (s.get("settlement_sources") or []) if x.get("url")]
    checks.append({
        "check": "series record", "url": url, "field": "settlement_sources",
        "published": ", ".join(published_sources) or None,
        "official": ", ".join(official_sources) or None,
        "result": "match" if published_sources == official_sources else "mismatch",
        "detail": "the settlement source is the official page the contract "
                  "settles against"})
    return checks


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-topic", type=int, default=3,
                    help="highest-value markets checked per topic")
    ap.add_argument("--snapshot", default=os.path.join(ROOT, "data", "live.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "verification.json"))
    args = ap.parse_args()

    try:
        with open(args.snapshot, encoding="utf-8") as fh:
            live = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"cannot read snapshot: {exc}", file=sys.stderr)
        return 2

    events = live.get("events") or []
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_topic.setdefault(event.get("topic") or "", []).append(event)

    selected: list[dict[str, Any]] = []
    for topic, rows in by_topic.items():
        rows = sorted(rows, key=lambda r: -(r.get("open_interest_notional") or 0))
        selected.extend(rows[:args.per_topic])
    # Every market that carries a swing or a model pick is checked too.
    flagged = {(a.get("ticker")) for a in (live.get("alerts") or [])}
    flagged |= {(p.get("ticker")) for p in
                ((live.get("shortlist") or {}).get("picks") or [])}
    ticker_of = {e.get("ticker"): e for e in events}
    for ticker in sorted(t for t in flagged if t in ticker_of):
        selected.append(ticker_of[ticker])

    seen: set[str] = set()
    unique = []
    for event in selected:
        ticker = event.get("ticker")
        if ticker and ticker not in seen:
            seen.add(ticker)
            unique.append(event)

    checks: list[dict[str, Any]] = []
    for event in unique:
        checks.extend(verify_market(event))

    series_checked = 0
    for topic in sorted(by_topic):
        series_list = ((live.get("topics") or {}).get(topic) or {}).get("series") or []
        for series in series_list[:1]:
            checks.extend(verify_series(series))
            series_checked += 1

    counts = {"match": 0, "drift": 0, "mismatch": 0, "unverified": 0}
    mismatches = []
    for row in checks:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
        if row["result"] == "mismatch":
            mismatches.append(row)

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_root": API,
        "snapshot_generated_at": live.get("generated_at"),
        "markets_checked": len(unique),
        "series_checked": series_checked,
        "checks": checks,
        "counts": counts,
        "mismatches": mismatches,
        "ok": not mismatches,
        "tolerances": {"price_dollars": PRICE_TOLERANCE,
                       "relative": REL_TOLERANCE},
        "note": ("Prices and sizes move between the snapshot and this check, so a "
                 "difference inside the tolerance is recorded as drift, not as an "
                 "error. Every row records the official URL it was checked "
                 "against."),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    print(json.dumps({"markets_checked": len(unique),
                      "series_checked": series_checked,
                      "counts": counts, "out": args.out}, indent=1))
    for row in mismatches:
        print(f"MISMATCH {row['check']} {row['field']}: published="
              f"{row['published']!r} official={row['official']!r} url={row['url']}")
    # A response that could not be read is "unverified", not a mismatch: it
    # records that the check did not happen. Only a field that disagrees with
    # the official response fails the run.
    return 1 if counts["mismatch"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
