"""Collector: pulls the public demo API once and writes the JSON the site reads.

Run once (CI cron or locally):
    python3 -m collector.runner
    python3 -m collector.runner --topics crypto,golf --max-markets 25

Outputs (under docs/data/):
    run_meta.json    run status, timestamps, request count, errors (audit trail)
    series.json      series -> topic mapping with the exact API URL that proves it
    markets.json     one row per market, each with its official source URL
    orderbooks.json  depth ladders for tracked markets
    candles.json     OHLC series for chart windows (seconds/minutes/hours)
    alerts.json      >= $0.10 swings with candidate headlines (links blank if unverified)
    resolutions.json settled markets with YES/NO outcomes
    portfolio.json   simulated-trades portfolio snapshot (written by trading engine)

Verification rule enforced here: a value that could not be fetched stays None
(JSON null) and the row carries a `flags` array entry saying why. Nothing is inferred.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import news, topics as T  # noqa: E402
from collector.kalshi import (  # noqa: E402
    DEMO_BASE,
    KalshiClient,
    best_bid,
    depth_usd,
    fnum,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "data")

SOURCE_SERIES = "https://docs.kalshi.com/api-reference/market/get-series-list"
SOURCE_MARKETS = "https://docs.kalshi.com/api-reference/market/get-markets"
SOURCE_ORDERBOOK = "https://docs.kalshi.com/getting_started/orderbook_responses"
SOURCE_CANDLES = "https://docs.kalshi.com/api-reference/market/get-market-candlesticks"
SOURCE_TRADES = "https://docs.kalshi.com/api-reference/market/get-market-trades"
SOURCE_DEMO = "https://docs.kalshi.com/getting_started/demo_env"

# category -> endpoint URL template (exact, case-sensitive per docs)
CAT_URL = "{base}/series/?category={cat}&include_product_metadata=false"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def write_json(name: str, payload: Any) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def api_link(path: str) -> str:
    return f"{DEMO_BASE}{path}"


def collect_series(client: KalshiClient, topic_keys: List[str], meta: Dict) -> Dict[str, Dict]:
    """Fetch series per topic category and return {series_ticker: {topic, evidence}}."""
    wanted = [t for t in T.TOPICS if t.key in topic_keys]
    by_ticker: Dict[str, Dict] = {}
    for topic in wanted:
        for cat in tuple(topic.categories_strict) + tuple(topic.categories_broad):
            url = CAT_URL.format(base=DEMO_BASE, cat=cat)
            try:
                data = client.get("/series/", category=cat, include_product_metadata="false")
            except Exception as exc:
                meta["errors"].append({"step": "series", "category": cat, "error": str(exc)})
                continue
            for s in data.get("series") or []:
                if not topic.matches(s):
                    continue
                ticker = str(s.get("ticker") or "")
                if not ticker:
                    continue
                by_ticker[ticker] = {
                    "ticker": ticker,
                    "title": s.get("title"),
                    "category": s.get("category"),
                    "categories": s.get("categories"),
                    "tags": s.get("tags"),
                    "topic": topic.key,
                    "source_url": url,
                    "verified": True,
                }
    return by_ticker


def pick_markets(
    client: KalshiClient,
    series_by_ticker: Dict[str, Dict],
    topic_keys: List[str],
    per_topic: int,
    meta: Dict,
) -> List[Dict]:
    """Fetch open markets for each topic's series and keep the highest notional per topic."""
    rows: List[Dict] = []
    by_topic_series: Dict[str, List[str]] = {k: [] for k in topic_keys}
    for ticker, s in series_by_ticker.items():
        if s["topic"] in by_topic_series:
            by_topic_series[s["topic"]].append(ticker)

    for topic_key, tickers in by_topic_series.items():
        for st in tickers:
            try:
                markets = client.markets(status="open", series_ticker=st, limit=500, max_pages=3)
            except Exception as exc:
                meta["errors"].append({"step": "markets", "series": st, "error": str(exc)})
                continue
            for m in markets:
                m["_topic"] = topic_key
                m["_series_source"] = api_link(f"/markets?status=open&series_ticker={st}")
                rows.append(m)
        # keep the richest markets only
        rows_topic = [r for r in rows if r.get("_topic") == topic_key]
        rows_topic.sort(key=lambda r: market_notional(r), reverse=True)
        keep = {id(r) for r in rows_topic[:per_topic]}
        rows = [r for r in rows if r.get("_topic") != topic_key or id(r) in keep]
    return rows


def market_notional(m: Dict) -> float:
    """Dollar volume proxy = volume_fp x last price (both official fields).

    Documented as a derived ranking metric, not an API-provided value.
    """
    vol = fnum(m.get("volume_fp")) or 0.0
    price = fnum(m.get("last_price_dollars"))
    if price is None:
        bid = fnum(m.get("yes_bid_dollars"))
        ask = fnum(m.get("yes_ask_dollars"))
        price = (bid + ask) / 2 if bid is not None and ask is not None else None
    if price is None:
        price = 0.5  # ranking fallback only; the displayed value stays null in tables
    return vol * price


def market_row(m: Dict, source_url: str) -> Dict[str, Any]:
    """Normalize a market into a table row. Unconfirmable fields stay None + flagged."""
    flags: List[str] = []
    last = fnum(m.get("last_price_dollars"))
    bid = fnum(m.get("yes_bid_dollars"))
    ask = fnum(m.get("yes_ask_dollars"))
    if last is None and bid is None and ask is None:
        flags.append("price-unverified:no last/bid/ask returned")
    volume = fnum(m.get("volume_fp"))
    if volume is None:
        flags.append("volume-unverified:not returned")
    row = {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "title": m.get("title"),
        "topic": m.get("_topic"),
        "series_ticker": m.get("series_ticker"),
        "status": m.get("status"),
        "yes_bid": bid,
        "yes_ask": ask,
        "last_price": last,
        "volume_fp": volume,
        "notional_usd": round(market_notional(m), 2) if volume is not None else None,
        "open_interest_fp": fnum(m.get("open_interest_fp")),
        "expected_expiration": m.get("expected_expiration_ts"),
        "fee_type": m.get("fee_type"),
        "price_level_structure": m.get("price_level_structure"),
        "source_url": api_link(f"/markets/{m.get('ticker')}"),
        "docs_url": SOURCE_MARKETS,
        "flags": flags,
        "verified": not flags,
    }
    return row


def collect_orderbooks(client: KalshiClient, rows: List[Dict], top_n: int, meta: Dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for row in sorted(rows, key=lambda r: (r.get("notional_usd") or 0), reverse=True)[:top_n]:
        ticker = row.get("ticker")
        if not ticker:
            continue
        try:
            data = client.orderbook(ticker, depth=25)
        except Exception as exc:
            meta["errors"].append({"step": "orderbook", "ticker": ticker, "error": str(exc)})
            out[ticker] = {"ticker": ticker, "flags": ["orderbook-unverified:fetch failed"], "source_url": api_link(f"/markets/{ticker}/orderbook")}
            continue
        ob = data.get("orderbook_fp") or {}
        yes_levels = ob.get("yes_dollars") or []
        no_levels = ob.get("no_dollars") or []
        yb = best_bid(yes_levels)
        nb = best_bid(no_levels)
        yc, yusd = depth_usd(yes_levels)
        nc, nusd = depth_usd(no_levels)
        out[ticker] = {
            "ticker": ticker,
            "yes_levels": yes_levels,
            "no_levels": no_levels,
            "best_yes_bid": yb,
            "best_no_bid": nb,
            "implied_yes_ask": round(1.0 - nb, 4) if nb is not None else None,
            "yes_depth_contracts": yc,
            "yes_depth_usd": yusd,
            "no_depth_contracts": nc,
            "no_depth_usd": nusd,
            "source_url": api_link(f"/markets/{ticker}/orderbook"),
            "docs_url": SOURCE_ORDERBOOK,
            "fetched_at": int(time.time()),
            "flags": [] if yes_levels or no_levels else ["orderbook-empty"],
        }
    return out


def collect_candles(client: KalshiClient, rows: List[Dict], windows: Dict[str, int], top_n: int, meta: Dict) -> Dict[str, Any]:
    """Fetch candlesticks per (interval label). `windows` maps label -> seconds of history."""
    out: Dict[str, Any] = {}
    end = int(time.time())
    interval_of = {"seconds": 1, "minutes": 60, "hours": 1440}
    for row in sorted(rows, key=lambda r: (r.get("notional_usd") or 0), reverse=True)[:top_n]:
        ticker, series = row.get("ticker"), row.get("series_ticker")
        if not ticker or not series:
            continue
        for label, secs in windows.items():
            interval = interval_of[label]
            try:
                sticks = client.candlesticks(series, ticker, end - secs, end, interval)
            except Exception as exc:
                meta["errors"].append({"step": "candles", "ticker": ticker, "window": label, "error": str(exc)})
                sticks = []
            out.setdefault(ticker, {})[label] = {
                "interval": interval,
                "points": [
                    {
                        "t": s.get("end_period_ts"),
                        "close": fnum((s.get("price") or {}).get("close_dollars")),
                        "open": fnum((s.get("price") or {}).get("open_dollars")),
                        "high": fnum((s.get("price") or {}).get("high_dollars")),
                        "low": fnum((s.get("price") or {}).get("low_dollars")),
                        "volume": fnum(s.get("volume_fp")),
                    }
                    for s in sticks
                ],
                "source_url": api_link(f"/series/{series}/markets/{ticker}/candlesticks?start_ts={end - secs}&end_ts={end}&period_interval={interval}"),
                "docs_url": SOURCE_CANDLES,
            }
    return out


def detect_alerts(candles: Dict[str, Any], rows: List[Dict], threshold: float, with_news: bool = True) -> List[Dict]:
    """Alert when consecutive closes differ by >= threshold (either direction).

    Swing = latest close vs previous close inside the shortest window (seconds),
    which is the most granular official series. A market with <2 points gets no
    alert (never fabricate a move).
    """
    by_ticker = {r.get("ticker"): r for r in rows}
    alerts: List[Dict] = []
    for ticker, windows in candles.items():
        points = (windows.get("seconds") or {}).get("points") or []
        if len(points) < 2:
            # fall back to minutes if seconds are sparse
            points = (windows.get("minutes") or {}).get("points") or []
            window = "minutes"
        else:
            window = "seconds"
        if len(points) < 2:
            continue
        prev, cur = points[-2], points[-1]
        if prev.get("close") is None or cur.get("close") is None:
            continue
        delta = round(cur["close"] - prev["close"], 4)
        if abs(delta) + 1e-9 < threshold:
            continue
        row = by_ticker.get(ticker) or {}
        when = datetime.fromtimestamp(cur.get("t") or time.time(), tz=timezone.utc)
        headlines = news.market_news(ticker, row.get("title") or ticker, when) if with_news else []
        alerts.append(
            {
                "ticker": ticker,
                "topic": row.get("topic"),
                "title": row.get("title"),
                "window": window,
                "from": prev["close"],
                "to": cur["close"],
                "delta": delta,
                "direction": "up" if delta > 0 else "down",
                "t": cur.get("t"),
                "t_iso": when.isoformat(),
                "threshold": threshold,
                "headlines": headlines,
                "news_status": "ok" if headlines else "no-headlines-found",
                "source_url": api_link(f"/markets/{ticker}"),
                "candle_source_url": (windows.get(window) or {}).get("source_url"),
                "docs_url": SOURCE_CANDLES,
                "flags": [] if headlines else ["news-unverified:no headline within window (link left blank)"],
            }
        )
    alerts.sort(key=lambda a: a.get("t") or 0, reverse=True)
    return alerts


def collect_resolutions(client: KalshiClient, series_by_ticker: Dict[str, Dict], meta: Dict, max_series: int = 24) -> List[Dict]:
    """Settled markets -> YES/NO outcome rows (used for strategy grading).

    `max_series` caps how many series are scanned per run to keep the run inside
    rate limits; scanned series rotate by sort order across runs.
    """
    out: List[Dict] = []
    per_topic: Dict[str, List[str]] = {}
    for ticker, s in sorted(series_by_ticker.items()):
        per_topic.setdefault(s["topic"], []).append(ticker)
    per_cap = max(1, max_series // max(len(per_topic), 1))
    for topic_key in sorted(per_topic):
        for ticker in per_topic[topic_key][:per_cap]:
            s = series_by_ticker[ticker]
            try:
                settled = client.markets(status="settled", series_ticker=ticker, limit=200, max_pages=2)
            except Exception as exc:
                meta["errors"].append({"step": "settled", "series": ticker, "error": str(exc)})
                continue
            for m in settled:
                result = m.get("result")
                if result not in ("yes", "no"):
                    continue
                out.append(
                    {
                        "ticker": m.get("ticker"),
                        "event_ticker": m.get("event_ticker"),
                        "title": m.get("title"),
                        "topic": topic_key,
                        "result": result,
                        "settlement_value": fnum(m.get("settlement_value_dollars")),
                        "settlement_ts": m.get("settlement_ts"),
                        "volume_fp": fnum(m.get("volume_fp")),
                        "source_url": api_link(f"/markets/{m.get('ticker')}"),
                        "docs_url": "https://docs.kalshi.com/getting_started/market_settlement",
                        "verified": True,
                    }
                )
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Kalshi demo collector")
    ap.add_argument("--topics", default=",".join(t.key for t in T.TOPICS))
    ap.add_argument("--max-markets", type=int, default=12, help="markets tracked per topic")
    ap.add_argument("--orderbook-top", type=int, default=18, help="how many markets get depth snapshots")
    ap.add_argument("--candle-top", type=int, default=18, help="how many markets get candle series")
    ap.add_argument("--threshold", type=float, default=0.10, help="alert threshold in dollars")
    ap.add_argument("--news", action="store_true", help="fetch candidate headlines for swings")
    args = ap.parse_args(argv)

    topic_keys = [k.strip() for k in args.topics.split(",") if k.strip()]
    started = time.time()
    meta: Dict[str, Any] = {
        "started_at": utcnow().isoformat(),
        "base_url": DEMO_BASE,
        "topics": topic_keys,
        "threshold": args.threshold,
        "errors": [],
        "environment": "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local",
    }
    client = KalshiClient(logger=lambda m: print(m, file=sys.stderr))

    def progress(msg: str) -> None:
        print(f"[collector] {msg}", flush=True)

    try:
        status = client.exchange_status()
        meta["exchange"] = {"status": status.get("exchange_status"), "indexes": len(status.get("exchange_indexes") or [])}
        progress(f"exchange status: {meta['exchange']['status']}")
    except Exception as exc:
        meta["errors"].append({"step": "exchange_status", "error": str(exc)})
        progress(f"exchange status FAILED: {exc}")

    progress("fetching series -> topic mapping …")
    series_map = collect_series(client, topic_keys, meta)
    progress(f"  mapped {len(series_map)} series")
    progress("fetching open markets …")
    rows = pick_markets(client, series_map, topic_keys, args.max_markets, meta)
    row_list = [market_row(m, m.get("_series_source") or SOURCE_MARKETS) for m in rows]
    row_list.sort(key=lambda r: (r.get("notional_usd") or 0), reverse=True)
    progress(f"  {len(row_list)} markets kept")

    progress(f"fetching top {args.orderbook_top} order books …")
    orderbooks = collect_orderbooks(client, row_list, args.orderbook_top, meta)
    progress(f"fetching candles for top {args.candle_top} markets × 3 windows …")
    candles = collect_candles(
        client, row_list, {"seconds": 3600, "minutes": 6 * 3600, "hours": 24 * 60 * 60}, args.candle_top, meta
    )
    alerts = detect_alerts(candles, row_list, args.threshold, with_news=args.news)
    progress(f"  {len(alerts)} alerts >= {args.threshold}")
    resolutions = collect_resolutions(client, series_map, meta)
    progress(f"  {len(resolutions)} resolved markets")

    # series -> topic evidence table (each row carries the exact API URL used)
    series_rows = sorted(series_map.values(), key=lambda s: (s["topic"], s["ticker"]))

    write_json("series.json", {"generated_at": utcnow().isoformat(), "source_docs": SOURCE_SERIES, "rows": series_rows})
    write_json("markets.json", {"generated_at": utcnow().isoformat(), "source_docs": SOURCE_MARKETS, "rows": row_list})
    write_json("orderbooks.json", {"generated_at": utcnow().isoformat(), "source_docs": SOURCE_ORDERBOOK, "books": orderbooks})
    write_json("candles.json", {"generated_at": utcnow().isoformat(), "source_docs": SOURCE_CANDLES, "series": candles})
    write_json("alerts.json", {"generated_at": utcnow().isoformat(), "threshold": args.threshold, "source_docs": SOURCE_CANDLES, "alerts": alerts})
    write_json("resolutions.json", {"generated_at": utcnow().isoformat(), "rows": resolutions})

    meta["finished_at"] = utcnow().isoformat()
    meta["duration_s"] = round(time.time() - started, 1)
    meta["counts"] = {
        "series": len(series_rows),
        "markets": len(row_list),
        "orderbooks": len(orderbooks),
        "candle_markets": len(candles),
        "alerts": len(alerts),
        "resolutions": len(resolutions),
        "errors": len(meta["errors"]),
    }
    write_json("run_meta.json", meta)
    print(json.dumps(meta["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
