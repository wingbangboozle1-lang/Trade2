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
from .engine import (Portfolio, LiveDemoBroker, STRATEGIES, exit_signals as select_exits,
                     select_trades)
from .kalshi_api import DEMO_REST, KalshiClient, KalshiHTTPError

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_PATH = os.path.join(DATA_DIR, "portfolio_state.json")
LIVE_PATH = os.path.join(DATA_DIR, "live.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
RESOLUTIONS_PATH = os.path.join(DATA_DIR, "resolutions.json")
VERIFIED_PATH = os.path.join(DATA_DIR, "verified_results.json")

ALERTS_VERSION = 2       # bump to discard alerts written by an older rule set
MAX_ALERTS = 400          # rolling chat buffer
MAX_EQUITY_POINTS = 1500
BAR_SECONDS = 300         # reference bar for swing measurement (5 minutes)
REFERENCE_MARKET_CAP = 50   # markets per topic to ask for a reference bar
# Reserve part of the budget for reference bars, alerts and settlement so the
# discovery phase can never consume the whole run.
DISCOVERY_SHARE = 0.55


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


_series_volume: dict[str, float] = {}


def fetch_events_for_topic(client: KalshiClient, topic: topic_mod.Topic,
                           series_tickers: set[str],
                           max_series: int = 40,
                           deadline: float | None = None) -> list[dict[str, Any]]:
    """Open events for one topic, queried by series.

    ``category`` is NOT a working filter on ``GET /events``: requesting
    ``?status=open&category=Crypto`` returns events from *every* category
    (verified 2026-11-20 — the first page came back with World, Elections and
    other categories). Filtering by the documented ``series_ticker`` parameter
    is both correct and far faster, and it keeps topic scoping in one place: a
    series only belongs to a topic because ``topics.resolve_series`` matched it.

    ``max_series`` bounds the work per run; the series are walked busiest-first
    using the volume Kalshi reports on each series record.
    """
    series_tickers = {t for t in series_tickers if t}
    if not series_tickers:
        return []
    # Busiest series first: volume_fp is an official field on GET /series and is
    # the honest proxy for where activity is. Unknown volume sorts last.
    ordered = sorted(series_tickers, key=lambda t: -_series_volume.get(t, 0.0))
    events: dict[str, dict[str, Any]] = {}
    for index, series in enumerate(ordered):
        if index >= max_series:
            break
        if deadline is not None and time.time() > deadline:
            break
        try:
            batch = client.events(status="open", series_ticker=series,
                                  with_nested_markets="true")
        except KalshiHTTPError:
            continue
        for event in batch:
            if event.get("series_ticker") == series:
                events[event["event_ticker"]] = event
    return list(events.values())


def bar_reference(client: KalshiClient, market: dict[str, Any],
                  deadline: float) -> dict[str, Any] | None:
    """Price at the start of the current bar, from official candlesticks.

    ``GET /series/{series_ticker}/markets/{ticker}/candlesticks`` returns OHLC
    per period (https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md).
    We take the most recent *completed* 1-minute candle's close and its timestamp
    and use that as the baseline for the $0.10 swing test, so a gradual move
    still alerts instead of being swallowed between two snapshots.

    Returns None when the market has no trade history in the window, in which
    case the caller falls back to the previous snapshot.
    """
    series = market.get("series_ticker")
    ticker = market.get("ticker")
    if not series or not ticker or time.time() > deadline:
        return None
    now = int(time.time())
    try:
        data = client.candlesticks(series, ticker, now - 3 * BAR_SECONDS,
                                  now, period_interval=1)
    except KalshiHTTPError:
        return None
    candles = [c for c in (data.get("candlesticks") or [])
               if c.get("end_period_ts")]
    if not candles:
        return None
    candles.sort(key=lambda c: c["end_period_ts"])
    current_bar_start = now - (now % BAR_SECONDS)
    completed = [c for c in candles if c["end_period_ts"] <= current_bar_start]
    chosen = completed[-1] if completed else candles[0]

    def _px(block: dict[str, Any] | None) -> float | None:
        raw = (block or {}).get("close_dollars")
        try:
            v = float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            v = None
        return v

    # The candle carries both the traded price and the quote at bar close.
    # The swing test needs a *quote* on both ends, so the reference is built
    # from yes_bid/yes_ask exactly as the order book builds it:
    #   YES bid = yes_bid.close_dollars
    #   YES ask = yes_ask.close_dollars  (= 1 - no_bid, already the implied ask
    #                                     in Kalshi's own candle schema)
    # The traded price (``price``) is kept separately for display and is never
    # compared against an order-book mid.
    yes_bid = _px(chosen.get("yes_bid"))
    yes_ask = _px(chosen.get("yes_ask"))
    traded = _px(chosen.get("price"))
    ref: dict[str, Any] = {
        "ts": float(chosen["end_period_ts"]),
        "traded": traded,
        "quote_source": "none",
        "mid": None,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
    }
    if (yes_bid is not None and yes_ask is not None
            and 0.0 < yes_bid < 1.0 and 0.0 < yes_ask <= 1.0
            and yes_ask >= yes_bid):
        ref["quote_source"] = "book"
        ref["mid"] = round((yes_bid + yes_ask) / 2.0, 4)
    return ref


def collect(market_cap: int = 150, orderbook_cap: int = 300,
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
    timings: dict[str, float] = {}

    def lap(label: str, since: float) -> float:
        mark = time.time()
        timings[label] = round(timings.get(label, 0.0) + mark - since, 2)
        return mark
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
    alerts_store = load_json(os.path.join(DATA_DIR, "alerts.json"),
                             {"alerts": [], "version": 0})
    if alerts_store.get("version") != ALERTS_VERSION:
        # The rule that produced the stored alerts changed (a phantom 0.50 mid
        # from unquoted markets). Keeping them would publish known-bad rows.
        alerts_store = {"alerts": [], "version": ALERTS_VERSION}
    history = load_json(HISTORY_PATH, {"series": {}})
    resolutions = load_json(RESOLUTIONS_PATH, {"resolutions": {}, "meta": {}})

    series_cache = load_json(os.path.join(DATA_DIR, "series_cache.json"), {})
    holdings = {p["ticker"] for p in
                load_json(STATE_PATH, {}).get("positions", [])
                if p.get("status") == "open"}

    observations: list[alerts.Observation] = []
    liquidity: dict[str, dict[str, Any]] = {}
    per_topic: dict[str, Any] = {}
    series_registry: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    discovery_deadline = started + budget_seconds * DISCOVERY_SHARE
    t_prev = time.time()
    for topic in topic_mod.TOPICS:
        if time.time() > discovery_deadline:
            errors.append(f"discovery budget exhausted before topic {topic.slug}")
            continue
        try:
            series = topic_mod.cached_series(client, topic, series_cache)
        except KalshiHTTPError as exc:
            errors.append(f"{topic.slug}: series discovery failed ({exc})")
            series = []
        t_mark = lap(f"series:{topic.slug}", t_prev)
        for row in series:
            series_registry[row["ticker"]] = row
            try:
                _series_volume[row["ticker"]] = float(row.get("volume_fp") or 0)
            except (TypeError, ValueError):
                _series_volume[row["ticker"]] = 0.0
        series_tickers = {r["ticker"] for r in series}

        try:
            events = fetch_events_for_topic(
                client, topic, series_tickers,
                max_series=topic.event_series_scan,
                deadline=discovery_deadline)
        except KalshiHTTPError as exc:
            errors.append(f"{topic.slug}: event fetch failed ({exc})")
            events = []
        t_mark = lap(f"events:{topic.slug}", t_mark)

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

        # Order books are fetched in batches of up to 100 tickers, using the
        # documented GET /markets/orderbooks endpoint. One request per batch
        # instead of one per market is what keeps the run inside its budget.
        wanted = [m.get("ticker") for m in selected[:orderbook_cap] if m.get("ticker")]
        for held in holdings:
            if held not in wanted:
                wanted.append(held)
        books: dict[str, dict[str, Any]] = {}
        for start in range(0, len(wanted), 100):
            if time.time() > deadline:
                errors.append(f"{topic.slug}: order-book budget exhausted "
                              f"({len(wanted) - start} markets without a book)")
                break
            chunk = wanted[start:start + 100]
            try:
                books.update(client.orderbooks(chunk))
            except KalshiHTTPError as exc:
                errors.append(f"{topic.slug}: orderbooks {start}-{start + len(chunk)} "
                              f"failed ({exc})")

        for market in selected:
            ticker = market.get("ticker")
            if not ticker:
                continue
            book = books.get(ticker)
            book_payload = {"orderbook_fp": book} if book is not None else None
            obs = alerts.observe(market, book_payload, topic.slug, ts=now)
            if book:
                liquidity[ticker] = alerts.analyse_liquidity(book_payload)
            observations.append(obs)
        t_mark = lap(f"books:{topic.slug}", t_mark)

        per_topic[topic.slug] = {
            "label": topic.label,
            "notes": topic.notes,
            "source_url": topic.source_url,
            "series_count": len(series),
            "event_count": len(events),
            "market_count": len(markets),
            "tracked_market_count": len(selected),
            "series_resolved_at": (series_cache.get(topic.slug) or {}).get("resolved_at"),
            # Events discovered for this topic this run, so settlements whose
            # series_ticker is null can be attributed from an official field,
            # and so the topic pages can group markets under their event.
            "events": [
                {"event_ticker": e.get("event_ticker"),
                 "title": e.get("title"),
                 "series_ticker": e.get("series_ticker"),
                 "market_count": len(e.get("markets") or [])}
                for e in events[:120] if e.get("event_ticker")
            ],
            "series": series[:400],
        }

    # -- reference bars ---------------------------------------------------
    # Ask for an official candle for the busiest markets in each topic, so a
    # gradual move across snapshots can still cross the $0.10 threshold.
    references: dict[str, dict[str, Any]] = {}
    per_topic_seen: dict[str, list[alerts.Observation]] = {}
    for obs in observations:
        per_topic_seen.setdefault(obs.topic, []).append(obs)
    for topic_slug, obs_list in per_topic_seen.items():
        for obs in obs_list[:REFERENCE_MARKET_CAP]:
            if time.time() > deadline:
                errors.append(f"{topic_slug}: reference bars truncated by budget")
                break
            stub = {"series_ticker": obs.series_ticker, "ticker": obs.ticker}
            ref = bar_reference(client, stub, deadline)
            if ref:
                references[obs.ticker] = ref
    t_mark = lap("reference_bars", t_mark)

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
        ref = references.get(obs.ticker)
        alert = alerts.detect_swing(prev, obs, reference=ref)
        if alert:
            new_alerts.append(alert)

    # One row per (market, reference bar, direction). Re-running inside the same
    # bar used to append the same move again (7 duplicate HBID rows were
    # published on 2026-11-20), which floods the chat and inflates the count.
    existing = alerts_store.get("alerts", [])
    seen_ids = {a["id"] for a in new_alerts}
    merged = new_alerts + [a for a in existing if a.get("id") not in seen_ids]
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

    # Every registered series -> its topic. Built here because the settlement
    # loop below needs it: Kalshi's settled records often omit series_ticker.
    series_to_topic = {r["ticker"]: r["topic"] for r in series_registry.values()}
    # Events this run actually discovered per topic. Only these can attribute a
    # settlement whose series_ticker came back null (official fields only, no
    # ticker-string parsing — see alerts.resolution_topic).
    event_to_topic: dict[str, str] = {}
    for _slug, _payload in per_topic.items():
        for _ev in _payload.get("events") or []:
            if _ev.get("event_ticker"):
                event_to_topic[_ev["event_ticker"]] = _slug

    # -- simulated portfolio ---------------------------------------------
    portfolio = Portfolio(load_json(STATE_PATH, None))
    for obs in observations:
        portfolio.mark(obs.ticker, obs.mid)

    # Settle anything the exchange has already resolved.
    settled_updates: list[dict[str, Any]] = []
    settled_markets = []
    t_settle = time.time()
    if time.time() < deadline:
        try:
            settled_markets = client.markets(status="settled",
                                             limit=min(1000, settle_scan),
                                             max_pages=3)
        except KalshiHTTPError as exc:
            errors.append(f"settled scan failed ({exc})")

    lap("settled_scan", t_settle)
    for market in settled_markets:
        ticker = market.get("ticker")
        result = (market.get("result") or "").lower()
        if not ticker or result not in ("yes", "no"):
            continue
        settle_event = market.get("event_ticker") or ""
        settle_series = market.get("series_ticker")
        resolutions["resolutions"][ticker] = {
            "ticker": ticker,
            "event_ticker": settle_event,
            "series_ticker": settle_series,
            # Kalshi's settled records often carry series_ticker: null, so the
            # topic is resolved from the registry at settle time and stored with
            # the row (see alerts.resolution_topic for the documented order).
            "topic": alerts.resolution_topic(settle_series, settle_event,
                                             series_to_topic, event_to_topic),
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

    # Manage open simulated positions: bank favourable swings, cut adverse ones.
    obs_by_ticker = {o.ticker: o for o in observations}
    closed_now: list[dict[str, Any]] = []
    for pos, exit_price, why in select_exits(portfolio, obs_by_ticker):
        closed = portfolio.close(pos.ticker, exit_price, now, why)
        if closed:
            closed_now.append(closed.as_dict())

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
    unattributed: list[dict[str, Any]] = []
    for ticker, rec in resolutions["resolutions"].items():
        topic_slug = rec.get("topic") or alerts.resolution_topic(
            rec.get("series_ticker"), rec.get("event_ticker"),
            series_to_topic, event_to_topic)
        if topic_slug in resolved_by_topic:
            resolved_by_topic[topic_slug].append({**rec, "topic": topic_slug})
        else:
            unattributed.append(rec)
    for slug in resolved_by_topic:
        resolved_by_topic[slug] = sorted(
            resolved_by_topic[slug],
            key=lambda r: r.get("settlement_ts") or "", reverse=True)[:40]

    # Keep the resolutions store bounded. Open-interest-free sports markets
    # settle constantly, and an unbounded map grew the file past 8 MB in the
    # first hour. Newest 2,000 are kept; older entries drop out.
    res_map = resolutions.get("resolutions", {})
    if len(res_map) > 2000:
        ordered = sorted(res_map.items(),
                         key=lambda kv: kv[1].get("settlement_ts") or "", reverse=True)
        resolutions["resolutions"] = dict(ordered[:2000])

    # Keep the published snapshot lean: full series metadata (settlement source
    # URLs, contract terms) is valuable on the topic pages up to a point, but
    # shipping 400 rows x 5 topics of it dominates the file. Each topic publishes
    # its top 60 series with sources; the full list stays in data/series_cache.json.
    for slug, topic_payload in per_topic.items():
        topic_payload["series"] = topic_payload.get("series", [])[:60]
        topic_payload["series_listed"] = len(topic_payload["series"])

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
        # The model chat: tradeable swings plus scored signals, each row tagged
        # with what it is (see alerts.model_shortlist).
        "high_roi_alerts": alerts.model_shortlist(merged, signal_dicts),
        "signals": signal_dicts,
        "unattributed_resolutions": sorted(
            unattributed,
            key=lambda r: r.get("settlement_ts") or "", reverse=True)[:40],
        "liquidity": liquidity,
        "portfolio": analytics,
        "resolutions": resolved_by_topic,
        "resolutions_count": len(resolutions["resolutions"]),
        "opened_this_run": opened,
        "settled_this_run": settled_updates,
        "closed_this_run": closed_now,
        "observation_count": len(observations),
        "reference_bar_seconds": BAR_SECONDS,
        "reference_bars_used": len(references),
        "run_seconds": round(time.time() - started, 1),
        "timings": timings,
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

    # Fail closed. If the whole run produced no observation (network blocked,
    # API down, every book fetch failed) the payload is empty, and writing it
    # would replace a good published snapshot with "0 markets". That happened
    # while testing this collector offline on 2026-11-20. The run still reports
    # its errors and exits non-zero, but the last good snapshot survives.
    if not observations:
        payload["published"] = False
        payload["publish_skipped"] = (
            "no market was observed this run; the previous snapshot is kept")
        return payload

    save_json(LIVE_PATH, payload)
    save_json(os.path.join(DATA_DIR, "alerts.json"),
              {"version": ALERTS_VERSION, "alerts": merged})
    save_json(HISTORY_PATH, history)
    save_json(RESOLUTIONS_PATH, resolutions)
    save_json(os.path.join(DATA_DIR, "series_cache.json"), series_cache)
    payload["published"] = True
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market-cap", type=int, default=150)
    ap.add_argument("--orderbook-cap", type=int, default=300)
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
        "published": payload.get("published"),
        "publish_skipped": payload.get("publish_skipped"),
        "errors": payload["errors"],
        "elapsed_s": round(time.time() - started, 1),
    }, indent=1))
    if payload.get("published") is False:
        # Fail the step so a broken run is visible in Actions instead of
        # silently committing an empty dashboard.
        raise SystemExit(2)


if __name__ == "__main__":
    main()
