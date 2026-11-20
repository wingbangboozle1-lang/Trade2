"""Collector: pull the in-scope Kalshi demo markets, detect swings, run the
simulated strategies, track resolutions, and write the data the dashboard and
GitHub Pages site consume.

Run locally:            python3 -m collector.collector
Run in CI (fast, limited): python3 -m collector.collector --market-cap 120

Endpoints used (all public, no credentials needed):
  GET /exchange/status                     exchange/get-exchange-status
  GET /series                              market/get-series-list
  GET /events?status=open&with_nested_markets=true   events/get-events
  GET /markets/{ticker}/orderbook          market/get-market-orderbook
  GET /markets?status=settled              market/get-markets

Everything that ends up in data/live.json is either observed from those
responses or computed from them with the formulas documented in alerts.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from typing import Any

from . import alerts
from . import topics as topic_mod
from .engine import Portfolio, LiveDemoBroker, select_trades, STRATEGIES
from .kalshi_api import DEMO_REST, KalshiClient, KalshiHTTPError

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_PATH = os.path.join(DATA_DIR, "portfolio_state.json")
LIVE_PATH = os.path.join(DATA_DIR, "live.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
RESOLUTIONS_PATH = os.path.join(DATA_DIR, "resolutions.json")
VERIFIED_PATH = os.path.join(DATA_DIR, "verified_results.json")

MAX_ALERTS = 400          # rolling chat buffer
MAX_EQUITY_POINTS = 1500


def iso(ts: float | None = None) -> str:
    ts = ts if ts is not None else time.time()
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=False)
    os.replace(tmp, path)


def fetch_events_for_topic(client: KalshiClient, topic: topic_mod.Topic,
                           series_tickers: set[str]) -> list[dict[str, Any]]:
    """Open events for one topic.

    Kalshi's GET /events supports ``series_ticker`` and ``category``. We use the
    topic's category where the category is topic-specific, then filter by the
    series we resolved, which keeps scope enforcement in one place.
    """
    events: dict[str, dict[str, Any]] = {}
    per_category: set[str] = set()
    for category, _tags in topic.queries:
        per_category.add(category)
    for category in per_category:
        try:
            batch = client.events(status="open", category=category,
                                  with_nested_markets="true", limit=200)
        except KalshiHTTPError:
            batch = []
        for event in batch:
            series = event.get("series_ticker")
            if series in series_tickers:
                events[event["event_ticker"]] = event
    # Any resolved series whose events did not come back by category (for
    # example because its primary category differs from the discovery category).
    missing = series_tickers - {e.get("series_ticker") for e in events.values()}
    for series in sorted(missing)[:60]:
        try:
            batch = client.events(status="open", series_ticker=series,
                                  with_nested_markets="true", limit=200)
        except KalshiHTTPError:
            continue
        for event in batch:
            events[event["event_ticker"]] = event
    return list(events.values())


def collect(market_cap: int = 150, orderbook_cap: int = 90,
            settle_scan: int = 400, budget_seconds: float = 330.0) -> dict[str, Any]:
    """One collection pass.

    ``budget_seconds`` is a hard wall-clock ceiling. Unauthenticated Kalshi has
    no documented rate-limit headers (verified: the demo REST response carries
    none), so the collector is deliberately self-limiting: when the budget is
    exhausted it stops requesting order books and records that it did, rather
    than being killed mid-run. The dashboard shows the resulting coverage.
    """
    started = time.time()
    deadline = started + budget_seconds
    now = started
    client = KalshiClient(DEMO_REST)

    exchange = {}
    try:
        exchange = client.exchange_status()
    except KalshiHTTPError as exc:
        exchange = {"error": str(exc)}

    previous_live = load_json(LIVE_PATH, {})
    previous_obs: dict[str, dict[str, Any]] = {}
    for row in previous_live.get("observations", []):
        if row.get("ticker"):
            previous_obs[row["ticker"]] = row
    alerts_store = load_json(os.path.join(DATA_DIR, "alerts.json"), {"alerts": []})
    history = load_json(HISTORY_PATH, {"series": {}})
    resolutions = load_json(RESOLUTIONS_PATH, {"resolutions": {}, "meta": {}})

    holdings = {p["ticker"] for p in
                load_json(STATE_PATH, {}).get("positions", [])
                if p.get("status") == "open"}

    observations: list[alerts.Observation] = []
    liquidity: dict[str, dict[str, Any]] = {}
    per_topic: dict[str, Any] = {}
    series_registry: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for topic in topic_mod.TOPICS:
        if time.time() > deadline:
            errors.append(f"budget exhausted before topic {topic.slug}")
            continue
        try:
            series = topic_mod.resolve_series(client, topic)
        except KalshiHTTPError as exc:
            errors.append(f"{topic.slug}: series discovery failed ({exc})")
            series = []
        for row in series:
            series_registry[row["ticker"]] = row
        series_tickers = {r["ticker"] for r in series}

        try:
            events = fetch_events_for_topic(client, topic, series_tickers)
        except KalshiHTTPError as exc:
            errors.append(f"{topic.slug}: event fetch failed ({exc})")
            events = []

        markets: list[dict[str, Any]] = []
        for event in events:
            for market in event.get("markets") or []:
                market = {**market,
                          "event_ticker": event.get("event_ticker"),
                          "series_ticker": event.get("series_ticker")}
                market["_event_title"] = event.get("title")
                market["_event_category"] = event.get("category")
                markets.append(market)

        # Rank by the dollar value actually trading, then cap for runtime.
        # Markets we already hold are always included so positions stay marked.
        def activity(m: dict[str, Any]) -> float:
            return (float(m.get("volume_fp") or 0) + float(m.get("open_interest_fp") or 0))

        markets.sort(key=activity, reverse=True)
        ranked = markets[:market_cap]
        held = [m for m in markets[market_cap:] if m.get("ticker") in holdings]
        selected = ranked + held

        orderbook_budget = orderbook_cap
        for market in selected:
            ticker = market.get("ticker")
            if not ticker:
                continue
            out_of_time = time.time() > deadline
            if out_of_time and ticker not in holdings:
                orderbook_budget = 0
            want_book = (orderbook_budget > 0) or (ticker in holdings)
            book = None
            if want_book:
                if ticker not in holdings:
                    orderbook_budget -= 1
                try:
                    book = client.orderbook(ticker, depth=10)
                except KalshiHTTPError as exc:
                    errors.append(f"orderbook {ticker}: {exc}")
            obs = alerts.observe(market, book, topic.slug, ts=now)
            if book:
                liquidity[ticker] = alerts.analyse_liquidity(book)
            observations.append(obs)

        per_topic[topic.slug] = {
            "label": topic.label,
            "notes": topic.notes,
            "source_url": topic.source_url,
            "series_count": len(series),
            "event_count": len(events),
            "market_count": len(markets),
            "tracked_market_count": len(selected),
            "series": series[:400],
        }

    # -- swaps ------------------------------------------------------------
    new_alerts: list[dict[str, Any]] = []
    for obs in observations:
        prev_row = previous_obs.get(obs.ticker)
        prev = None
        if prev_row:
            prev = alerts.Observation(
                ts=prev_row.get("ts", now - 1), ticker=prev_row["ticker"],
                event_ticker=prev_row.get("event_ticker", ""),
                topic=prev_row.get("topic", obs.topic),
                title=prev_row.get("title", ""),
                yes_bid=prev_row.get("yes_bid"), yes_ask=prev_row.get("yes_ask"),
                mid=prev_row.get("mid"), last_price=prev_row.get("last_price"),
                volume=prev_row.get("volume"),
                open_interest=prev_row.get("open_interest"),
                series_ticker=prev_row.get("series_ticker", ""),
            )
        alert = alerts.detect_swing(prev, obs)
        if alert:
            new_alerts.append(alert)

    existing = alerts_store.get("alerts", [])
    merged = new_alerts + [a for a in existing
                           if a.get("id") not in {n["id"] for n in new_alerts}]
    merged = merged[:MAX_ALERTS]

    # -- signals ----------------------------------------------------------
    signals: list[alerts.Signal] = []
    for obs in observations:
        if obs.mid is None:
            continue
        liq = liquidity.get(obs.ticker, {"spread": None,
                                         "yes_bid_contracts": obs.yes_bid_size or 0,
                                         "no_bid_contracts": 0})
        sig = alerts.score_market(obs, liq)
        if sig:
            signals.append(sig)
    signals.sort(key=lambda s: s.score, reverse=True)
    signal_dicts = [s.as_dict() for s in signals[:60]]

    # -- simulated portfolio ---------------------------------------------
    portfolio = Portfolio(load_json(STATE_PATH, None))
    for obs in observations:
        portfolio.mark(obs.ticker, obs.mid)

    # Settle anything the exchange has already resolved.
    settled_updates: list[dict[str, Any]] = []
    settled_markets = []
    if time.time() < deadline:
        try:
            settled_markets = client.markets(status="settled",
                                             limit=min(1000, settle_scan))
        except KalshiHTTPError as exc:
            errors.append(f"settled scan failed ({exc})")

    for market in settled_markets:
        ticker = market.get("ticker")
        result = (market.get("result") or "").lower()
        if not ticker or result not in ("yes", "no"):
            continue
        resolutions["resolutions"][ticker] = {
            "ticker": ticker,
            "event_ticker": market.get("event_ticker"),
            "series_ticker": market.get("series_ticker"),
            "title": market.get("yes_sub_title") or market.get("title"),
            "result": result,
            "settlement_value_dollars": market.get("settlement_value_dollars"),
            "settlement_ts": market.get("settlement_ts"),
            "status": market.get("status"),
            "source_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}",
            "human_url": f"https://kalshi.com/markets/{market.get('event_ticker','')}",
            "verified_at": iso(now),
        }
        closed = portfolio.settle(ticker, result)
        if closed:
            settled_updates.append(closed.as_dict())
            history.setdefault("series", {}).setdefault(ticker, []).append(
                {"ts": now, "result": result, "price": closed.exit_price})

    # Open new simulated trades from the strategy gate.
    picks = select_trades(signals, new_alerts, portfolio) if new_alerts or signals else []
    opened: list[dict[str, Any]] = []
    for sig, strategy, reason in picks:
        position = portfolio.open(sig, strategy, reason)
        if position:
            opened.append(position.as_dict())

    portfolio.snapshot_equity(now)
    portfolio.equity_curve = portfolio.equity_curve[-MAX_EQUITY_POINTS:]
    save_json(STATE_PATH, portfolio.to_state())

    analytics = portfolio.analytics()

    # -- event table ------------------------------------------------------
    ranked_events = alerts.rank_events(observations)
    for row in ranked_events:
        row["liquidity"] = liquidity.get(row["ticker"])
        row["observation"] = next(
            (o.__dict__ for o in observations if o.ticker == row["ticker"]), None)

    # Highest-dollar events per topic, plus resolved feed per topic.
    resolved_by_topic: dict[str, list[dict[str, Any]]] = {t.slug: [] for t in topic_mod.TOPICS}
    series_to_topic = {r["ticker"]: r["topic"] for r in series_registry.values()}
    for ticker, rec in resolutions["resolutions"].items():
        topic_slug = series_to_topic.get(rec.get("series_ticker") or "")
        if topic_slug:
            resolved_by_topic.setdefault(topic_slug, []).append(rec)
    for slug in resolved_by_topic:
        resolved_by_topic[slug] = sorted(
            resolved_by_topic[slug],
            key=lambda r: r.get("settlement_ts") or "", reverse=True)[:60]

    payload = {
        "generated_at": iso(now),
        "generated_at_ts": now,
        "api_root": DEMO_REST,
        "swap_threshold_dollars": alerts.SWING_THRESHOLD,
        "mode": {
            "market_data": "live (Kalshi demo, public endpoints)",
            "trading": "simulated paper ledger",
            "live_demo_trading_enabled": LiveDemoBroker().enabled,
        },
        "exchange": exchange,
        "topics": per_topic,
        "events": ranked_events,
        "alerts": merged,
        "high_roi_alerts": [a for a in merged
                            if any(s["ticker"] == a["ticker"] and s["score"] >= 0.10
                                   for s in signal_dicts)],
        "signals": signal_dicts,
        "liquidity": liquidity,
        "portfolio": analytics,
        "resolutions": resolved_by_topic,
        "resolutions_count": len(resolutions["resolutions"]),
        "opened_this_run": opened,
        "settled_this_run": settled_updates,
        "observation_count": len(observations),
        "run_seconds": round(time.time() - started, 1),
        "budget_seconds": budget_seconds,
        "errors": errors[:20],
        "strategies": STRATEGIES,
        "sources": {
            "api_environments": "https://docs.kalshi.com/getting_started/api_environments.md",
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets",
            "orderbook": "https://docs.kalshi.com/getting_started/orderbook_responses.md",
            "settlement": "https://docs.kalshi.com/getting_started/market_settlement.md",
            "fees": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
        },
    }

    save_json(LIVE_PATH, payload)
    save_json(os.path.join(DATA_DIR, "alerts.json"), {"alerts": merged})
    save_json(HISTORY_PATH, history)
    save_json(RESOLUTIONS_PATH, resolutions)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-cap", type=int, default=150)
    ap.add_argument("--orderbook-cap", type=int, default=90)
    ap.add_argument("--settle-scan", type=int, default=300)
    ap.add_argument("--budget", type=float, default=330.0)
    args = ap.parse_args()
    started = time.time()
    payload = collect(args.market_cap, args.orderbook_cap, args.settle_scan,
                      args.budget)
    print(json.dumps({
        "generated_at": payload["generated_at"],
        "tracked_markets": payload["observation_count"],
        "alerts_total": len(payload["alerts"]),
        "new_swings": len([a for a in payload["alerts"]
                           if a.get("iso") == payload["generated_at"][:10] + "T"
                           + payload["generated_at"][11:19] + "Z"]),
        "signals": len(payload["signals"]),
        "open_positions": payload["portfolio"]["open_positions"],
        "equity": payload["portfolio"]["equity"],
        "resolutions": payload["resolutions_count"],
        "errors": payload["errors"],
        "elapsed_s": round(time.time() - started, 1),
    }, indent=1))


if __name__ == "__main__":
    main()
