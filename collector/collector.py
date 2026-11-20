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
  GET /markets/orderbooks                  market/get-multiple-market-orderbooks
  GET /markets?tickers=…                   market/get-markets (settlement lookup)
  GET /series/{s}/markets/{t}/candlesticks market/get-market-candlesticks

Settlement tracking asks for *exactly the markets this desk has been watching*
(``GET /markets?tickers=…``, the documented comma-separated filter), rather than
scanning the exchange's global settled feed: the brief asks how *the events we
track* resolved, and a global scan returns thousands of unrelated quick-settle
markets. Verified live 2026-11-20 against

    https://external-api.demo.kalshi.co/trade-api/v2/markets?tickers=KXAAAGASW-26NOV16-4.2000,KXAAAGASW-26NOV16-4.1800

— both markets came back with ``result``, ``settlement_ts`` and
``settlement_value_dollars`` even though they are no longer open.

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
from . import news
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
# The markets this desk has ever seen open. Drives the settlement lookup, so a
# resolution is recorded for the events a trader was actually shown.
TRACKED_PATH = os.path.join(DATA_DIR, "tracked_markets.json")
# The model's open flags (see alerts.attach_models / alerts.model_feed).
MODEL_WATCH_PATH = os.path.join(DATA_DIR, "model_watchlist.json")

ALERTS_VERSION = 2       # bump to discard alerts written by an older rule set
# NOTE: the swing *rule* is unchanged by the model annotation, so the version is
# deliberately NOT bumped — real alerts collected so far stay in the chat.
# alerts.attach_models() re-annotates every stored row on every run instead.
MAX_ALERTS = 400          # rolling chat buffer
MAX_EQUITY_POINTS = 1500
BAR_SECONDS = 300         # reference bar for swing measurement (5 minutes)
REFERENCE_MARKET_CAP = 50   # markets per topic to ask for a reference bar
# Reserve part of the budget for reference bars, alerts and settlement so the
# discovery phase can never consume the whole run.
DISCOVERY_SHARE = 0.55
# Settlement lookup: at most this many 100-ticker batches per run, tracked
# markets walked oldest-first so everything cycles through within a few runs.
SETTLE_BATCHES = 6
SETTLE_BATCH = 100
MAX_TRACKED = 6000        # bounded store; oldest-seen entries are dropped
# Candidate-catalyst lookups are best-effort and cost a request each, so they
# are capped per run and skipped entirely when the budget is tight.
NEWS_LOOKUPS_PER_RUN = 8
NEWS_TIMEOUT_SECONDS = 6.0


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
    return {"mid": round((bid + ask) / 2.0, 4),
            "ts": float(chosen["end_period_ts"]),
            "spread": round(ask - bid, 4)}


def _candle_close(candle: dict[str, Any], side: str) -> float | None:
    """``close_dollars`` of a candle's ``yes_bid`` or ``yes_ask`` block."""
    block = candle.get(side) or {}
    try:
        return float(block.get("close_dollars"))
    except (TypeError, ValueError):
        return None


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
    alerts_store = load_json(os.path.join(DATA_DIR, "alerts.json"),
                             {"alerts": [], "version": 0})
    if alerts_store.get("version") != ALERTS_VERSION:
        # The rule that produced the stored alerts changed (a phantom 0.50 mid
        # from unquoted markets). Keeping them would publish known-bad rows.
        alerts_store = {"alerts": [], "version": ALERTS_VERSION}
    history = load_json(HISTORY_PATH, {"series": {}})
    resolutions = load_json(RESOLUTIONS_PATH, {"resolutions": {}, "meta": {}})
    tracked = load_json(TRACKED_PATH, {"markets": {}, "meta": {}})
    if not isinstance(tracked.get("markets"), dict):
        tracked = {"markets": {}, "meta": {}}
    model_watch = load_json(MODEL_WATCH_PATH, {}).get("entries", {})

    # The previous observation of each market, for the run-over-run swing test.
    # Defect found and fixed here (2026-11-20): this used to read
    # ``data/live.json["observations"]``, a key the collector never writes, so
    # ``previous_obs`` was empty on every run and only the reference-bar path
    # could raise an alert. The tracked-market ledger now carries the last
    # observation, and the old lookup stays as a fallback for hand-built files.
    previous_obs: dict[str, dict[str, Any]] = {}
    for ticker, rec in tracked["markets"].items():
        row = rec.get("last_obs")
        if row and row.get("mid") is not None:
            previous_obs[ticker] = row
    for row in previous_live.get("observations", []):
        if row.get("ticker") and row["ticker"] not in previous_obs:
            previous_obs[row["ticker"]] = row

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

    # -- tracked-market ledger -------------------------------------------
    # Remember every market we have shown as open, with the topic and series it
    # belongs to. This is what lets the next run ask the exchange, precisely,
    # "how did the events we track resolve?" instead of guessing.
    for obs in observations:
        if not obs.ticker:
            continue
        prev = tracked["markets"].get(obs.ticker) or {}
        tracked["markets"][obs.ticker] = {
            "ticker": obs.ticker,
            "event_ticker": obs.event_ticker,
            "series_ticker": obs.series_ticker or alerts.series_from_ticker(obs.ticker),
            "topic": obs.topic,
            "title": obs.title,
            "close_time": obs.close_time or prev.get("close_time", ""),
            "first_seen": prev.get("first_seen") or iso(now),
            "last_open_seen": iso(now),
            "last_mid": obs.mid,
            "notional_per_contract": obs.notional,
            "open_interest_contracts": obs.open_interest,
            "volume_contracts": obs.volume,
            # What the swing detector needs on the *next* run. Kept in this
            # bounded ledger rather than the published snapshot so live.html
            # does not carry a second copy of every observation.
            "last_obs": {
                "ts": now,
                "ticker": obs.ticker,
                "event_ticker": obs.event_ticker,
                "topic": obs.topic,
                "title": obs.title,
                "yes_bid": obs.yes_bid,
                "yes_ask": obs.yes_ask,
                "mid": obs.mid,
                "last_price": obs.last_price,
                "volume": obs.volume,
                "open_interest": obs.open_interest,
                "series_ticker": obs.series_ticker,
            },
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
        alert = alerts.detect_swing(
            prev, obs,
            reference=(ref or {}).get("mid"),
            reference_ts=(ref or {}).get("ts"),
            reference_spread=(ref or {}).get("spread"),
        )
        if alert:
            new_alerts.append(alert)

    existing = alerts_store.get("alerts", [])
    merged = new_alerts + [a for a in existing
                           if a.get("id") not in {n["id"] for n in new_alerts}]
    # Drop stored alerts that fail the current quote rule (written before it).
    merged = [a for a in merged if alerts.alert_record_valid(a)]
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

    # -- the model's verdict on every swing, and the shortlist feed -------
    # One gate (alerts.MODEL_SCORE_GATE) decides both the server-side feed and
    # the browser's filter, so the two chats can never disagree about what the
    # model likes. Rows are copies; the stored alert dicts are not mutated.
    merged, model_watch = alerts.attach_models(
        merged, observations, liquidity, model_watch,
        gate=alerts.MODEL_SCORE_GATE, now=now)
    settled_tickers = {t for t, rec in resolutions["resolutions"].items()
                       if (rec.get("result") or "").lower() in ("yes", "no")}
    model_watch = alerts.prune_watchlist(model_watch, now, settled=settled_tickers)
    price_by_ticker = {o.ticker: o.mid for o in observations}
    model_shortlist = alerts.model_feed(
        merged, model_watch, price_by_ticker,
        gate=alerts.MODEL_SCORE_GATE, now=now)
    high_roi_alerts = [r for r in model_shortlist if r.get("kind") == "swing"]

    # -- candidate catalysts ------------------------------------------------
    # Best-effort only: a headline near a swing is a candidate, never a proven
    # cause. Requests are capped per run and skipped when the budget is short,
    # and a failed lookup is published as "unavailable" rather than an empty
    # field that would read as "we checked and found nothing".
    new_ids = {a["id"] for a in new_alerts}
    news_counts = {"ok": 0, "no-headlines-found": 0, "unavailable": 0, "skipped": 0}
    pending_news = [r for r in merged if r.get("id") in new_ids and not r.get("news_status")]
    if pending_news:
        if time.time() > deadline - 25:
            for row in pending_news:
                row["news_status"] = "skipped: run budget"
                news_counts["skipped"] += 1
            errors.append("headline lookup skipped: run budget exhausted")
        else:
            for row in pending_news[:NEWS_LOOKUPS_PER_RUN]:
                when = dt.datetime.fromtimestamp(float(row.get("ts") or now),
                                                 dt.timezone.utc)
                found = news.lookup(row.get("title") or "", when,
                                    max_items=3, timeout=NEWS_TIMEOUT_SECONDS,
                                    ticker=row.get("ticker") or "")
                row["headlines"] = found["items"][:3]
                row["news_status"] = found["status"]
                row["news_query"] = found["query"]
                # Publish the search the collector actually ran, so every
                # headline row is reproducible: desk.js links it as
                # "re-check" (chat-news-query). Before this, only the parsed
                # headlines were published and the query itself was
                # unrecoverable — you could not tell what had been asked.
                row["news_url"] = found["url"]
                if found["status"] == "ok":
                    news_counts["ok"] += 1
                elif found["status"] == "no-headlines-found":
                    news_counts["no-headlines-found"] += 1
                else:
                    news_counts["unavailable"] += 1
                    row["news_error"] = found["error"]
            for row in pending_news[NEWS_LOOKUPS_PER_RUN:]:
                row["news_status"] = "skipped: per-run cap"
                news_counts["skipped"] += 1
            if news_counts["unavailable"]:
                errors.append("headline lookup unavailable for "
                              f"{news_counts['unavailable']} swing(s) — links left blank")

    # -- simulated portfolio ---------------------------------------------
    portfolio = Portfolio(load_json(STATE_PATH, None))
    for obs in observations:
        portfolio.mark(obs.ticker, obs.mid)

    # Settle positions and record how each tracked event finished.
    #
    # This asks the exchange about *our* tickers (the documented ``tickers``
    # filter on GET /markets, comma-separated, up to 100 per request) instead of
    # paging the global settled feed. Two reasons, both verified live on
    # 2026-11-20: (1) the global feed is dominated by demo quick-settle and
    # weather series the brief excludes, and (2) the global feed is what left the
    # topic pages publishing "0 resolved" while the store held 2,000 rows none
    # of them could be attributed to a topic.
    settled_updates: list[dict[str, Any]] = []
    resolution_rows: list[dict[str, Any]] = []
    resolutions_before = len(resolutions["resolutions"])
    t_settle = time.time()
    held_now = set(portfolio.open_tickers)
    open_now = {o.ticker for o in observations if o.ticker}
    cutoff_now = iso(now)

    def _due_for_lookup(t: str, rec: dict[str, Any]) -> bool:
        if (resolutions["resolutions"].get(t) or {}).get("result"):
            return False                       # already settled and recorded
        if t in held_now:
            return True                        # the book must never go stale
        if t not in open_now:
            return True                        # no longer offered as open
        close = (rec.get("close_time") or "")[:19]
        if rec.get("awaiting_result"):
            # Asked once, the exchange had no result yet. Keep asking for a day
            # — Kalshi settles within minutes — then stop polling a market that
            # the demo never settles, and say so on the flagged page instead.
            try:
                stamp = dt.datetime.fromisoformat(close + "+00:00")
            except ValueError:
                return True
            age = dt.datetime.now(dt.timezone.utc) - stamp
            return age.total_seconds() < 24 * 3600
        return bool(close) and close <= cutoff_now[:19]   # closed on the clock

    pending = [t for t, rec in tracked["markets"].items() if _due_for_lookup(t, rec)]

    def _pending_key(t: str) -> tuple[int, str]:
        rec = tracked["markets"].get(t) or {}
        return (0 if t in held_now else 1, rec.get("last_open_seen") or "")

    pending.sort(key=_pending_key)
    # ``settle_scan`` keeps its CLI meaning (how much settlement work one run
    # may do) but now bounds tickers examined rather than pages of a global
    # feed. Rotating oldest-seen-first means the whole ledger is covered within
    # a few runs while every open position is checked on every run.
    pending = pending[:max(SETTLE_BATCH, int(settle_scan))]
    batches = 0
    for start in range(0, len(pending), SETTLE_BATCH):
        if batches >= SETTLE_BATCHES:
            errors.append(f"settlement lookup truncated: {len(pending) - start} "
                          f"tracked market(s) wait for the next run "
                          f"(batches={batches}, cap={settle_scan} tickers)")
            break
        if time.time() > deadline - 15:
            errors.append("settlement lookup truncated by run budget")
            break
        chunk = pending[start:start + SETTLE_BATCH]
        try:
            resolution_rows.extend(client.markets(tickers=",".join(chunk), max_pages=1))
        except KalshiHTTPError as exc:
            errors.append(f"settlement lookup failed ({exc})")
            break
        batches += 1

    lap("settled_scan", t_settle)
    for market in resolution_rows:
        ticker = market.get("ticker")
        if not ticker:
            continue
        rec = tracked["markets"].get(ticker) or {}
        result = (market.get("result") or "").lower()
        if result not in ("yes", "no"):
            # Not settled yet: keep it on the list so the desk still shows the
            # event as tracked-but-unresolved rather than dropping it silently.
            if market.get("status") in ("closed", "finalized") and ticker in tracked["markets"]:
                tracked["markets"][ticker]["awaiting_result"] = True
            continue
        series_ticker = rec.get("series_ticker") or alerts.series_from_ticker(ticker)
        resolutions["resolutions"][ticker] = {
            "ticker": ticker,
            "event_ticker": market.get("event_ticker") or rec.get("event_ticker"),
            "series_ticker": series_ticker,
            "topic": rec.get("topic") or "",
            "title": market.get("yes_sub_title") or market.get("title") or rec.get("title"),
            "result": result,
            "settlement_value_dollars": market.get("settlement_value_dollars"),
            "settlement_ts": market.get("settlement_ts"),
            "status": market.get("status"),
            "open_interest_contracts": rec.get("open_interest_contracts"),
            "source_url": f"{DEMO_REST}/markets/{ticker}",
            "human_url": f"https://kalshi.com/markets/{series_ticker}/{ticker}",
            "verified_at": iso(now),
        }
        closed = portfolio.settle(ticker, result)
        if closed:
            settled_updates.append(closed.as_dict())
            history.setdefault("series", {}).setdefault(ticker, []).append(
                {"ts": now, "result": result, "price": closed.exit_price})

    # Bound the tracked ledger: keep everything still open plus the most recent
    # settled ones, so a long-running desk cannot grow the file without limit.
    if len(tracked["markets"]) > MAX_TRACKED:
        keep = sorted(tracked["markets"].items(),
                      key=lambda kv: kv[1].get("last_open_seen") or "", reverse=True)
        open_rows = [(t, r) for t, r in tracked["markets"].items()
                     if not (resolutions["resolutions"].get(t) or {}).get("result")]
        merged_rows = {t: r for t, r in open_rows}
        for t, r in keep:
            if len(merged_rows) >= MAX_TRACKED:
                break
            merged_rows.setdefault(t, r)
        tracked["markets"] = merged_rows

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
                       if r.get("ticker") and r.get("topic")}
    for slug, rows in (series_cache or {}).items():
        for row in (rows or {}).get("series") or []:
            if row.get("ticker") and row.get("topic"):
                series_to_topic.setdefault(row["ticker"], row["topic"])
    resolved_by_topic = alerts.group_resolutions_by_topic(
        resolutions["resolutions"], series_to_topic,
        [t.slug for t in topic_mod.TOPICS])

    # Migration for the first version of this store, which kept *every* settled
    # market on the exchange (demo quick-settle, weather, sports) and could then
    # attribute none of them to a topic — the topic pages published "0 resolved"
    # beside a store of 2,000 rows. Rows without a YES/NO result, or without a
    # topic, are dropped; nothing belonging to a tracked topic is removed.
    resolutions["resolutions"] = {
        t: r for t, r in resolutions["resolutions"].items()
        if (r.get("result") or "").lower() in ("yes", "no") and r.get("topic")
    }
    resolutions["meta"] = {
        "scope": "markets this desk has tracked while open",
        "stored": len(resolutions["resolutions"]),
        "updated_at": iso(now),
        "lookup": f"GET {DEMO_REST}/markets?tickers=… (batches of {SETTLE_BATCH}, "
                  f"max {SETTLE_BATCHES} per run)",
    }

    # Keep the resolutions store bounded. Resolved markets accumulate forever;
    # the newest 2,000 in-scope results are kept, older ones drop out.
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
        # The model chat's rows, decided here (server) and rendered as-is in the
        # browser, from one gate. "high_roi_alerts" is the swing subset; the
        # full shortlist, including flagged markets that have not swung yet, is
        # "model_shortlist".
        "high_roi_alerts": high_roi_alerts,
        "model_shortlist": model_shortlist,
        "model_gate": alerts.MODEL_SCORE_GATE,
        "model_watch_count": len(model_watch),
        "news_lookups": news_counts,
        "signals": signal_dicts,
        "liquidity": liquidity,
        "portfolio": analytics,
        "resolutions": resolved_by_topic,
        "resolutions_count": len(resolutions["resolutions"]),
        "resolutions_this_run": (len(resolutions["resolutions"])
                                 - resolutions_before),
        "settlement_lookup_batches": batches,
        "tracked_markets": len(tracked["markets"]),
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

    save_json(LIVE_PATH, payload)
    save_json(os.path.join(DATA_DIR, "alerts.json"),
              {"version": ALERTS_VERSION, "alerts": merged})
    save_json(HISTORY_PATH, history)
    save_json(RESOLUTIONS_PATH, resolutions)
    save_json(TRACKED_PATH, tracked)
    save_json(MODEL_WATCH_PATH, {
        "updated_at": iso(now),
        "gate": alerts.MODEL_SCORE_GATE,
        "ttl_seconds": alerts.WATCHLIST_TTL_SECONDS,
        "entries": model_watch,
    })
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
