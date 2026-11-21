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

from . import alerts, news
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
# v3 (session arena-dc732aa6): alerts carry a stable per-bar key, an explicit
# price basis and an executability verdict, and the rolling buffer folds repeats
# instead of appending them (29 buffered rows / 8 distinct moves in the
# 2026-11-20T18:41Z snapshot). Stored rows are also re-checked against the
# quote rule by alerts.alert_record_valid, as introduced in 856e184e.
MAX_ALERTS = 400          # rolling chat buffer
MAX_RESOLUTIONS = 2000    # newest in-scope YES/NO records kept in the store
MAX_EQUITY_POINTS = 1500
BAR_SECONDS = 300         # reference bar for swing measurement (5 minutes)
REFERENCE_MARKET_CAP = 50   # markets per topic to ask for a reference bar
# Reserve part of the budget for reference bars, alerts and settlement so the
# discovery phase can never consume the whole run.
DISCOVERY_SHARE = 0.55


def iso(ts: float | None = None) -> str:
    ts = ts if ts is not None else time.time()
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolution_topic(event_ticker: str | None, registry: dict[str, dict[str, Any]],
                     memo: dict[str, str | None] | None = None) -> str | None:
    """Map a settled market's event ticker onto one of the five tracked topics.

    Kalshi market objects returned by ``GET /markets`` carry **no**
    ``series_ticker`` field — every record written by the old code has
    ``series_ticker: null`` (same live finding session c0205283 logged for
    market objects), so keying the topic lookup on it matched nothing and every
    per-topic resolution list on the site stayed empty. The event ticker
    embeds the series ticker as its head:

        ``KXAAAGASD-26NOV20``   -> series ``AAAGASD``   (events sometimes add a
                                                              ``KX`` prefix)
        ``KXPRESNOMD-28-RW``    -> series ``KXPRESNOMD``
        ``KXBTCY-27JAN0100``    -> series ``KXBTCY``

    Each head is tried as-is first, then with a leading ``KX`` removed, and
    only whole ``-``-delimited heads are considered, so one series can never
    swallow a longer sibling (``AAAGAS`` does not match ``KXAAAGASD-…``).
    Returns the topic slug, or None when the event belongs to none of the
    tracked series (e.g. the soccer markets the settled scan also sees).
    """
    if memo is not None and event_ticker in memo:
        return memo[event_ticker]
    if not event_ticker or not registry:
        return None
    found: str | None = None
    # Candidate heads: every "-"-delimited prefix of the ticker (longest last).
    parts = event_ticker.split("-")
    for i in range(1, len(parts) + 1):
        head = "-".join(parts[:i])
        row = registry.get(head)
        if row is None and head.startswith("KX"):
            row = registry.get(head[2:])
        if row is not None and row.get("topic"):
            found = row["topic"]
            break
    if memo is not None:
        memo[event_ticker] = found
    return found


def series_row_for_event(event_ticker: str | None,
                         registry: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The ``GET /series`` row that owns an event ticker, or None.

    Same head scan as :func:`resolution_topic` and for the same reason: a market
    object from ``GET /markets`` has no ``series_ticker`` field
    (https://docs.kalshi.com/api-reference/market/get-markets), so the only way
    back to the series — and therefore to the series' own ``fee_multiplier`` /
    ``fee_type`` (https://docs.kalshi.com/api-reference/series/get-series) — is
    the ticker prefix. Returns the whole registry row so callers can read any
    documented series field, not just the topic.
    """
    if not event_ticker or not registry:
        return None
    parts = event_ticker.split("-")
    for i in range(1, len(parts) + 1):
        head = "-".join(parts[:i])
        row = registry.get(head)
        if row is None and head.startswith("KX"):
            row = registry.get(head[2:])
        if row is not None:
            return row
    return None


def migrate_resolutions(store: dict[str, Any],
                        registry: dict[str, dict[str, Any]]) -> int:
    """Re-tag every stored resolution with its topic and drop out-of-scope ones.

    The settled scan sees the whole exchange (soccer, quicksettle, …); those
    records are outside the brief's five topics and — because the store is
    bounded to the newest ``MAX_RESOLUTIONS`` — they crowd out the tracked
    topics' own YES/NO history. Called once per run after discovery, with the
    full series registry, so records written by the old series_ticker-keyed
    code are re-classified instead of silently kept unviewable. Returns the
    number of records kept.
    """
    res_map = store.get("resolutions") or {}
    if not registry:
        # Discovery failed this run: an empty registry would classify nothing
        # and wipe the store. Keep everything and retry next run.
        return len(res_map)
    memo: dict[str, str | None] = {}
    kept: dict[str, dict[str, Any]] = {}
    for ticker, rec in res_map.items():
        if not isinstance(rec, dict):
            continue
        topic = rec.get("topic") or resolution_topic(
            rec.get("event_ticker") or rec.get("ticker"), registry, memo)
        if topic:
            rec["topic"] = topic
            kept[ticker] = rec
    if len(kept) > MAX_RESOLUTIONS:
        ordered = sorted(kept.items(),
                         key=lambda kv: kv[1].get("settlement_ts") or "",
                         reverse=True)
        kept = dict(ordered[:MAX_RESOLUTIONS])
    store["resolutions"] = kept
    return len(kept)


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
    We take the most recent *completed* 1-minute candle and use its quote closes
    (yes_bid and yes_ask) as the baseline for the $0.10 swing test, so a gradual
    move still alerts instead of being swallowed between two snapshots. The
    baseline is a quote mid with its spread, never a last-trade price.

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
    # Price basis: the swing test compares quote mids, so the reference must be
    # a quote mid too. The candle's ``price`` block is the last *trade*; using it
    # against a book mid produced phantom alerts (e.g. KXPRESNOMD-28-HBID: last
    # trade 0.8110 vs mid of a 0.0020 / 0.8110 book = 0.4065). Use the candle's
    # yes_bid / yes_ask close instead (both documented in the candlestick schema).
    bid = _candle_close(chosen, "yes_bid")
    ask = _candle_close(chosen, "yes_ask")
    if bid is None or ask is None or not (0.0 <= bid <= ask <= 1.0):
        return None
    # ``trade_close`` is published next to the quote mid for transparency only
    # (the chart legend and the methodology page); it is never the basis of a
    # swing alert, which is the point of 856e184e's quote rule.
    return {"mid": round((bid + ask) / 2.0, 4),
            "ts": float(chosen["end_period_ts"]),
            "spread": round(ask - bid, 4),
            "yes_bid": bid, "yes_ask": ask,
            "trade_close": _candle_close(chosen, "price"),
            "period_interval_minutes": 1}


def _candle_close(candle: dict[str, Any], side: str) -> float | None:
    """``close_dollars`` of a candle's ``yes_bid`` or ``yes_ask`` block."""
    block = candle.get(side) or {}
    try:
        return float(block.get("close_dollars"))
    except (TypeError, ValueError):
        return None


NEWS_MAX_PER_RUN = 6      # headline lookups per run (each one is a single GET)
NEWS_TIMEOUT_SECONDS = 6.0
NEWS_WINDOW_HOURS = 6


def _brief(alert: dict[str, Any]) -> dict[str, Any]:
    """The subset of an alert a reviewer needs to audit a refusal."""
    keys = ("ticker", "event_ticker", "series_ticker", "topic", "title",
            "abs_delta", "direction", "yes_bid", "yes_ask", "spread",
            "market_url", "ts", "iso", "threshold")
    out = {k: alert.get(k) for k in keys}
    out["kind"] = "indicative-move" if alert.get("quality") == "indicative" \
        else "midpoint-move"
    return out


def attach_news(new_alerts: list[dict[str, Any]],
                deadline: float | None = None) -> dict[str, Any]:
    """Attach candidate headlines to freshly emitted swing alerts.

    The brief asks for "events and website links that may have caused a sharp
    jump". No official source maps news to Kalshi prices, so this is a
    best-effort keyword lookup against Google News RSS, published as a
    *candidate* with its own publication timestamp and never as a confirmed
    cause. When the lookup fails — blocked network, timeout, no headline in the
    window — the field stays empty and the reason is recorded, instead of a
    plausible-looking guess.

    Only rows that are new or materially bigger are looked up, because the chat
    folds repeats: an ongoing move does not get re-searched on every run.
    """
    stats = {"looked_up": 0, "with_headlines": 0, "skipped": 0, "reason": "",
             "source": "https://news.google.com/rss/search"}
    for alert in new_alerts:
        alert.setdefault("news", [])
        alert.setdefault("news_status", "not looked up this run")
    if not new_alerts:
        return stats
    for alert in new_alerts[:NEWS_MAX_PER_RUN]:
        if deadline is not None and time.time() > deadline - NEWS_TIMEOUT_SECONDS:
            stats["reason"] = "run budget exhausted before the news lookup"
            break
        try:
            when = dt.datetime.fromtimestamp(alert["ts"], dt.timezone.utc)
            found = news.market_news(alert["ticker"], alert.get("title") or "",
                                      when, window_hours=NEWS_WINDOW_HOURS)
        except Exception as exc:                     # never fail a run on news
            stats["reason"] = f"news lookup error ({type(exc).__name__})"
            break
        stats["looked_up"] += 1
        alert["news"] = found
        alert["news_status"] = "matched" if found else "no headline in window"
        if found:
            stats["with_headlines"] += 1
    stats["skipped"] = len(new_alerts) - stats["looked_up"]
    return stats


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
    # Two documented endpoints can disagree on the same market; publish the
    # largest gaps instead of silently preferring one of them.
    gaps: list[dict[str, Any]] = []
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
            # The series row carries this series' own official fee parameters,
            # which the market object does not (see series_row_for_event).
            obs = alerts.observe(market, book_payload, topic.slug, ts=now,
                                 series=series_row_for_event(
                                     market.get("event_ticker") or ticker,
                                     series_registry))
            if book:
                liquidity[ticker] = alerts.analyse_liquidity(book_payload)
                gap = alerts.book_record_divergence(market, book_payload)
                if gap:
                    gap["topic"] = topic.slug
                    gaps.append(gap)
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
    # Attach each market's bar reference to its observation so the alert (and
    # therefore the page) can state which Kalshi-published numbers it used.
    for obs in observations:
        ref = references.get(obs.ticker)
        if ref:
            obs.ref_ts = ref.get("ts")
            obs.ref_yes_bid = ref.get("yes_bid")
            obs.ref_yes_ask = ref.get("yes_ask")
            obs.ref_trade_close = ref.get("trade_close")

    new_alerts: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
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
        ref = references.get(obs.ticker) or {}
        kwargs = dict(reference=ref.get("mid"), reference_ts=ref.get("ts"),
                      reference_spread=ref.get("spread"), bar_seconds=BAR_SECONDS)
        alert = alerts.detect_swing(prev, obs, **kwargs)
        if alert:
            # An alert only means something if there is size at the level you
            # would actually trade. Keep such rows in the chat, but publish the
            # reason they are not actionable instead of hiding them.
            if alert.get("quality") == "indicative":
                alert["news"] = []
                alert["news_status"] = "not looked up: not executable"
                suppressed.append({**_brief(alert),
                                   "reason": alert["quality_reason"]})
            else:
                new_alerts.append(alert)
        else:
            rejection = alerts.swing_rejection(prev, obs, **kwargs)
            if rejection:
                suppressed.append(rejection)

    # Candidate catalysts for the rows that will actually appear in the chat.
    news_stats = attach_news(new_alerts, deadline)

    existing = [a for a in alerts_store.get("alerts", [])
                if alerts.alert_record_valid(a)]
    fold = alerts.fold_alerts(new_alerts, existing, max_alerts=MAX_ALERTS)
    merged = fold["alerts"]

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
    resolution_memo: dict[str, str | None] = {}
    for market in settled_markets:
        ticker = market.get("ticker")
        result = (market.get("result") or "").lower()
        if not ticker or result not in ("yes", "no"):
            continue
        # Settle the simulated book first: a held position must be graded even
        # if its record would fall outside the stored (displayed) scope.
        closed = portfolio.settle(ticker, result)
        if closed:
            settled_updates.append(closed.as_dict())
            history.setdefault("series", {}).setdefault(ticker, []).append(
                {"ts": now, "result": result, "price": closed.exit_price})
        # Store only resolutions inside the five tracked topics. Market objects
        # carry no series_ticker, so the topic comes from the event ticker
        # (see resolution_topic()); everything else is out of scope and would
        # only crowd the bounded store.
        topic = resolution_topic(
            market.get("event_ticker") or ticker, series_registry, resolution_memo)
        if not topic:
            continue
        resolutions["resolutions"][ticker] = {
            "ticker": ticker,
            "event_ticker": market.get("event_ticker"),
            "series_ticker": market.get("series_ticker"),
            "topic": topic,
            "title": market.get("yes_sub_title") or market.get("title"),
            "result": result,
            "settlement_value_dollars": market.get("settlement_value_dollars"),
            "settlement_ts": market.get("settlement_ts"),
            "status": market.get("status"),
            "source_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}",
            "human_url": f"https://kalshi.com/markets/{market.get('event_ticker','')}",
            "verified_at": iso(now),
        }

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
    # First migrate the store: re-tag every record from its event ticker
    # (market objects carry no series_ticker — see resolution_topic()) and
    # drop out-of-scope settlements so the bounded store tracks the five
    # topics the brief asks for.
    migrate_resolutions(resolutions, series_registry)
    resolved_by_topic: dict[str, list[dict[str, Any]]] = {t.slug: [] for t in topic_mod.TOPICS}
    series_to_topic = {r["ticker"]: r["topic"] for r in series_registry.values()}
    for ticker, rec in resolutions["resolutions"].items():
        topic_slug = (rec.get("topic")
                      or series_to_topic.get(rec.get("series_ticker") or "")
                      or resolution_topic(rec.get("event_ticker") or ticker,
                                          series_registry))
        if topic_slug:
            resolved_by_topic.setdefault(topic_slug, []).append(rec)
    for slug in resolved_by_topic:
        resolved_by_topic[slug] = sorted(
            resolved_by_topic[slug],
            key=lambda r: r.get("settlement_ts") or "", reverse=True)[:40]

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
        "high_roi_alerts": alerts.high_roi_alerts(merged, signal_dicts),
        "model_gate": {"min_net_roi": alerts.MODEL_MIN_NET_ROI,
                       "require_executable": True,
                       "source": "https://docs.kalshi.com/getting_started/orderbook_responses.md"},
        "signals": signal_dicts,
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
        "alert_stats": {
            "fired_this_run": len(new_alerts),
            "added": fold["added"],
            "escalated": fold["escalated"],
            "folded_duplicates": fold["folded"],
            "buffer": len(merged),
            "distinct_moves": len({a.get("key") for a in merged}),
            "executable": sum(1 for a in merged if a.get("quality") == "executable"),
            "indicative": sum(1 for a in merged if a.get("quality") == "indicative"),
            "suppressed_this_run": len(suppressed),
        },
        "suppressed_alerts": suppressed[:40],
        "book_record_gaps": sorted(gaps, key=lambda g: g["abs_gap"],
                                    reverse=True)[:40],
        "book_record_gap_count": len(gaps),
        "news_stats": news_stats,
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
