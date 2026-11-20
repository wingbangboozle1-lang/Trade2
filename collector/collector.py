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

ALERTS_VERSION = 3       # bump to discard alerts written by an older rule set
#                          v3 = two-sided-quote integrity gate (MAX_QUOTE_SPREAD)
MAX_ALERTS = 400          # rolling chat buffer
MAX_SUPPRESSED = 40       # held-back alerts shown on Flagged for review
MAX_EQUITY_POINTS = 1500
BAR_SECONDS = 300         # reference bar for swing measurement (5 minutes)
REFERENCE_MARKET_CAP = 50   # markets per topic to ask for a reference bar
TOP_PER_TOPIC = 8           # rows per topic on the overview page
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
    We take the most recent *completed* 1-minute candle whose own quote passes
    the integrity check and use its quote closes (yes_bid and yes_ask) as the
    baseline for the $0.10 swing test, so a gradual move still alerts instead of
    being swallowed between two snapshots. The baseline is a quote mid with its
    spread, never a last-trade price.

    Returns None when no candle in the window is a usable reference, in which
    case the caller falls back to the previous stored observation.
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
    return candle_reference(candles, now)


def settled_events_for_topic(client: KalshiClient, series_tickers: set[str],
                             max_pages: int = 2,
                             limit: int = 200) -> list[dict[str, Any]]:
    """Settled events whose series belongs to one of the tracked topics.

    ``GET /events?status=settled&with_nested_markets=true`` returns the event's
    own ``series_ticker`` together with every market it contained, so a
    resolution can be attributed to a topic exactly instead of by ticker-prefix
    inference. Only events whose series is in ``series_tickers`` are kept.

    This exists because the generic settled scan (``GET /markets?status=settled``)
    is dominated by series we do not track — on the demo exchange the 2,000 most
    recent settlements were mostly soccer, tennis and 15-minute demo markets —
    so in-topic resolutions were being missed even though they existed.

    https://docs.kalshi.com/api-reference/events/get-events
    """
    kept: list[dict[str, Any]] = []
    cursor = None
    for _ in range(max_pages):
        try:
            page = client._request("GET", "/events", {
                "status": "settled", "with_nested_markets": "true",
                "limit": limit, "cursor": cursor,
            })
        except KalshiHTTPError:
            break
        for event in page.get("events") or []:
            series = event.get("series_ticker") or ""
            if series in series_tickers:
                kept.append(event)
        cursor = page.get("cursor") or ""
        if not cursor:
            break
    return kept


def candle_reference(candles: list[dict[str, Any]], now: int) -> dict[str, Any] | None:
    """Newest completed candle that is a usable swing reference.

    A candlestick carries its own bid and ask for that minute, which is the
    exact evidence needed: a print that sits outside its own minute's quote, or
    a minute whose quote is one-sided or wider than MAX_QUOTE_SPREAD, is not a
    price anyone could have traded at.

    Worked example (live, 2026-11-20, KXPRESNOMD-28-AKLO, period ending
    1795200000): ``price.close_dollars`` 0.8030 while
    ``yes_bid.close_dollars`` is 0.0020 and ``yes_ask.close_dollars`` is 0.0030.
    The 0.8030 is a single unpaired print against a 0.2-cent book; using it as
    the reference is what published an "$0.80 crash" every few minutes.
    """
    if not candles:
        return None
    # Never look at a period that has not ended yet: its OHLC is still forming.
    ordered_candles = sorted((c for c in candles
                              if c.get("end_period_ts")
                              and c["end_period_ts"] <= now),
                             key=lambda c: c["end_period_ts"])
    if not ordered_candles:
        return None
    current_bar_start = now - (now % BAR_SECONDS)
    completed = [c for c in ordered_candles if c["end_period_ts"] <= current_bar_start]
    # A market with no completed period inside the window still gets a
    # reference from its most recent *ended* period -- never from a forming one.
    for candle in reversed(completed or ordered_candles):
        bid = _candle_side(candle, "yes_bid")
        ask = _candle_side(candle, "yes_ask")
        print_price = _candle_side(candle, "price")
        if bid is None or ask is None:
            continue                      # one-sided minute: not a reference
        width = round(ask - bid, 4)
        if width > alerts.MAX_QUOTE_SPREAD or width < 0:
            continue                      # not a market price
        if print_price is not None and not (bid - 1e-9 <= print_price <= ask + 1e-9):
            continue                      # print outside its own quote
        mid = round((bid + ask) / 2.0, 4)
        if not (0.0 < mid < 1.0):
            continue
        # ``spread`` is the field the swing rule takes (it must be tighter than
        # ALERT_MAX_SPREAD); the quote and the print travel with it so the alert
        # record can be re-checked later without another API call.
        return {"mid": mid, "ts": float(candle["end_period_ts"]),
                "spread": width, "quote_width": width,
                "bid": bid, "ask": ask, "print": print_price}
    return None


def _candle_side(candle: dict[str, Any], key: str) -> float | None:
    """Read ``<side>.close_dollars`` from a candlestick, or None."""
    side = candle.get(key) or {}
    raw = side.get("close_dollars")
    try:
        value = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    if value is None or not (0.0 <= value <= 1.0):
        return None
    return value


def _candle_close(candle: dict[str, Any], side: str) -> float | None:
    """``close_dollars`` of a candle's ``yes_bid`` or ``yes_ask`` block."""
    return _candle_side(candle, side)


def series_of(ticker: str, recorded: Any = None) -> str:
    """Series ticker for a market.

    A settled market object returned by ``GET /markets?status=settled`` carries
    ``event_ticker`` but **no** ``series_ticker`` field (verified live on
    2026-11-20). Kalshi tickers are built as ``SERIES-EVENT[-STRIKE]``, so the
    series is everything before the first hyphen. The recorded value wins when
    the market was discovered through its series.

    https://docs.kalshi.com/api-reference/market/get-markets
    """
    if recorded:
        return str(recorded)
    return (ticker or "").split("-")[0]


def resolutions_by_topic(
    res_map: dict[str, dict[str, Any]],
    series_to_topic: dict[str, str],
    limit: int = 40,
) -> dict[str, list[dict[str, Any]]]:
    """Group resolved markets by topic, newest settlement first.

    Before this existed the grouping keyed on ``rec["series_ticker"]``, which is
    null for every settled market, so the topic pages published "No resolved
    market from this topic has been captured yet" for all five topics while the
    overview reported 2,000 resolutions. A resolution that cannot be attributed
    to any tracked series is left out rather than guessed into a topic.
    """
    out: dict[str, list[dict[str, Any]]] = {t.slug: [] for t in topic_mod.TOPICS}
    valid = {t.slug for t in topic_mod.TOPICS}
    for ticker, rec in (res_map or {}).items():
        series = series_of(ticker, rec.get("series_ticker"))
        # An explicit topic recorded at collection time (the event's own
        # series_ticker matched a tracked series) beats inference.
        topic_slug = rec.get("topic_hint") or series_to_topic.get(series)
        if topic_slug not in valid:
            continue
        out.setdefault(topic_slug, []).append(
            {**rec, "series_ticker": series, "topic": topic_slug})
    for slug in out:
        out[slug] = sorted(out[slug],
                           key=lambda r: r.get("settlement_ts") or "",
                           reverse=True)[:limit]
    return out


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
        prev = alerts.Observation(**prev_row) if prev_row else None
        ref = references.get(obs.ticker)
        alert = alerts.detect_swing(
            prev, obs,
            reference=(ref or {}).get("mid"),
            reference_ts=(ref or {}).get("ts"),
            reference_spread=(ref or {}).get("spread"),
            reference_quote=(({k: ref.get(k) for k in ("bid", "ask", "print", "ts",
                                                       "quote_width")}
                              if ref else None)),
        )
        if alert:
            new_alerts.append(alert)

    existing = alerts_store.get("alerts", [])
    merged = new_alerts + [a for a in existing
                           if a.get("id") not in {n["id"] for n in new_alerts}]
    # A stored alert can predate the current quote rule. Both rules must agree
    # before a row is republished: alert_record_valid() checks the quote basis
    # (the reference must be a quote mid, not a trade print), is_publishable()
    # checks that both ends of the move are verifiable market prices. Rows that
    # fail either are held back rather than deleted, so the Flagged-for-review
    # page can show exactly what was suppressed together with the API link.
    def _keep(a: dict[str, Any]) -> bool:
        return alerts.alert_record_valid(a) and alerts.is_publishable(a)

    suppressed = [a for a in merged if not _keep(a)]
    merged = [a for a in merged if _keep(a)][:MAX_ALERTS]

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
    t_settle = time.time()
    if time.time() < deadline:
        try:
            settled_markets = client.markets(status="settled",
                                             limit=min(1000, settle_scan),
                                             max_pages=3)
        except KalshiHTTPError as exc:
            errors.append(f"settled scan failed ({exc})")

    lap("settled_scan", t_settle)

    # In-topic settlements, attributed through the event's own series_ticker.
    topic_series: dict[str, set[str]] = {}
    for row in series_registry.values():
        if row.get("ticker") and row.get("topic"):
            topic_series.setdefault(row["topic"], set()).add(row["ticker"])
    all_tracked = set().union(*topic_series.values()) if topic_series else set()
    t_topic_settle = time.time()
    settled_from_events: list[dict[str, Any]] = []
    if all_tracked and time.time() < deadline:
        for event in settled_events_for_topic(client, all_tracked):
            topic_slug = next((slug for slug, series in topic_series.items()
                               if event.get("series_ticker") in series), None)
            for market in event.get("markets") or []:
                result = (market.get("result") or "").lower()
                if result not in ("yes", "no"):
                    continue
                settled_from_events.append({
                    **market,
                    "event_ticker": event.get("event_ticker"),
                    "series_ticker": event.get("series_ticker"),
                    "title": (market.get("yes_sub_title")
                              or event.get("title") or market.get("title")),
                    "_topic": topic_slug,
                })
    lap("settled_in_topic", t_topic_settle)

    # In-topic settlements take priority: they carry an explicit series_ticker
    # read from the event, so they are never inferred.
    for market in settled_from_events + settled_markets:
        ticker = market.get("ticker")
        result = (market.get("result") or "").lower()
        if not ticker or result not in ("yes", "no"):
            continue
        resolutions["resolutions"][ticker] = {
            "ticker": ticker,
            "event_ticker": market.get("event_ticker"),
            "series_ticker": market.get("series_ticker") or ticker.split("-")[0],
            "title": market.get("yes_sub_title") or market.get("title"),
            "result": result,
            "settlement_value_dollars": market.get("settlement_value_dollars"),
            "settlement_ts": market.get("settlement_ts"),
            "status": market.get("status"),
            "source_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}",
            "human_url": f"https://kalshi.com/markets/{market.get('event_ticker','')}",
            "topic_hint": market.get("_topic") or "",
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
    series_to_topic = {r["ticker"]: r["topic"] for r in series_registry.values()
                       if r.get("ticker")}
    for slug, cached in (series_cache or {}).items():
        for row in (cached or {}).get("series") or []:
            if row.get("ticker"):
                series_to_topic.setdefault(row["ticker"], slug)
    resolved_by_topic = resolutions_by_topic(resolutions.get("resolutions") or {},
                                             series_to_topic)

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

    # Per-topic top slice of the ranked event table. The overview ranks by
    # open-interest value across every topic, which on the demo exchange means
    # elections (hundreds of millions of contracts) hides golf, culture and gas
    # (thousands). One row set per topic keeps all five visible at the top of
    # the page without inventing a score or a combined ranking.
    ranked_by_topic: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_events:
        bucket = ranked_by_topic.setdefault(row["topic"], [])
        if len(bucket) < TOP_PER_TOPIC:
            bucket.append(row)

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
        "events_by_topic": ranked_by_topic,
        "top_per_topic": TOP_PER_TOPIC,
        "alerts": merged,
        "alerts_suppressed": suppressed[:MAX_SUPPRESSED],
        "alerts_publishable": len(merged),
        "alerts_suppressed_count": len(suppressed),
        "model_gate": alerts.HIGH_ROI_GATE,
        # Same rule as the browser chat: a swing on a market whose modelled net
        # ROI clears the single published gate. Previously this used a score
        # threshold of 0.10 while the front-end used net_roi 0.05, so the two
        # "model likes this" views disagreed.
        "high_roi_alerts": [
            a for a in merged
            if any(s_["ticker"] == a["ticker"]
                   and s_.get("net_roi", 0) >= alerts.HIGH_ROI_GATE
                   for s_ in signal_dicts)],
        "signals": signal_dicts,
        "liquidity": liquidity,
        "portfolio": analytics,
        "resolutions": resolved_by_topic,
        "resolutions_count": len(resolutions["resolutions"]),
        # Stored settlements include markets from series we do not track; they
        # are counted but never forced into a topic. Both numbers are published
        # so "resolved tracked" cannot silently overstate the covered set.
        "resolutions_attributed": sum(len(v) for v in resolved_by_topic.values()),
        "resolutions_unattributed": max(
            0, len(resolutions["resolutions"])
            - sum(len(v) for v in resolved_by_topic.values())),
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

    # Observations are persisted so the NEXT run can compare against a real
    # previous sample. Without this, previous_obs is always empty, the candle
    # reference is the only baseline, and a market whose candles are stale can
    # never alert. Kept compact: the fields detect_swing actually reads.
    # The row shape is exactly Observation()'s field set, so a stored row can be
    # fed straight back into alerts.Observation(**row) on the next run.
    payload["observations"] = [
        {"ts": o.ts, "ticker": o.ticker, "event_ticker": o.event_ticker,
         "topic": o.topic, "title": o.title, "yes_bid": o.yes_bid,
         "yes_ask": o.yes_ask, "mid": o.mid, "last_price": o.last_price,
         "volume": o.volume, "open_interest": o.open_interest,
         "yes_bid_size": o.yes_bid_size, "no_bid": o.no_bid,
         "notional": o.notional, "status": o.status, "result": o.result,
         "series_ticker": o.series_ticker, "close_time": o.close_time}
        for o in observations
    ]

    save_json(LIVE_PATH, payload)
    save_json(os.path.join(DATA_DIR, "alerts.json"),
              {"version": ALERTS_VERSION, "alerts": merged})
    save_json(HISTORY_PATH, history)
    save_json(RESOLUTIONS_PATH, resolutions)
    save_json(os.path.join(DATA_DIR, "series_cache.json"), series_cache)
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
        "errors": payload["errors"],
        "elapsed_s": round(time.time() - started, 1),
    }, indent=1))


if __name__ == "__main__":
    main()
