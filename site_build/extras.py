"""Additional pages for the root site.

Three pages the brief asks for that the original build did not publish:

``resolutions.html``
    Every market the collector has watched settle, with the official YES/NO
    ``result`` field, grouped by topic. This is the "track the live event
    until it resolves" view.

``trades.html``
    The simulated trade ledger, the strategy catalogue, the breakdown by
    strategy / topic / category, and an equity-curve graph.

``suggestions.html``
    Concrete, prioritised ways to make the site more live and interactive,
    each with its status and, where one exists, the official Kalshi source
    that would support it.

Every row on these pages carries a source link to the official demo API
response it was read from. Nothing here is inferred.
"""

from __future__ import annotations

import html
import time
from typing import Any

from .format import (API, count, cents, esc, kalshi_event_url,
                     kalshi_market_url, money, news_search_url, num, pct,
                     result_chip)

TOPIC_ORDER = ["gas-prices", "elections", "culture", "crypto", "golf"]
TOPIC_LABEL = {
    "gas-prices": "Gas prices",
    "elections": "Elections",
    "culture": "Culture",
    "crypto": "Crypto",
    "golf": "Golf",
}

SETTLEMENT_DOC = "https://docs.kalshi.com/getting_started/market_settlement"
FEES_DOC = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
MARKETS_DOC = "https://docs.kalshi.com/api-reference/market/get-markets"


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def series_topic_map(series_cache: dict[str, Any]) -> dict[str, str]:
    """Map every tracked series ticker to the topic it belongs to.

    The full list comes from ``data/series_cache.json`` (the collector's
    discovery cache), not from the trimmed list published in the snapshot.
    """
    out: dict[str, str] = {}
    for slug, payload in (series_cache or {}).items():
        if not isinstance(payload, dict):
            continue
        for row in (payload.get("series") or []):
            ticker = (row or {}).get("ticker")
            if ticker:
                out[ticker] = slug
    return out


def resolution_topic(rec: dict[str, Any], series_map: dict[str, str]) -> str | None:
    """Which topic a settled market belongs to.

    ``GET /markets`` returns market objects with **no** ``series_ticker``
    field, so the collector's own per-topic resolution buckets stayed empty.
    Three sources are tried, most authoritative first:

    1. ``rec["topic"]`` — tagged by the collector's ``migrate_resolutions()``
       (integration fix, session arena-5bbd15fd) from the *event* ticker,
       which is delimiter-anchored and therefore also right for series whose
       own ticker contains ``-``;
    2. the API's ``series_ticker`` when present;
    3. the market-ticker prefix, which is Kalshi's naming convention — with a
       leading ``KX`` stripped as well, because series ``AAAGASD`` publishes
       its events as ``KXAAAGASD-26NOV20`` while the map holds the bare
       series ticker (without this, every gas resolution was dropped here).
    """
    topic = rec.get("topic")
    if topic in TOPIC_ORDER:
        return topic
    declared = rec.get("series_ticker")
    if declared and declared in series_map:
        return series_map[declared]
    ticker = rec.get("ticker") or ""
    prefix = ticker.split("-")[0] if "-" in ticker else ticker
    slug = series_map.get(prefix)
    if slug is None and prefix.startswith("KX"):
        slug = series_map.get(prefix[2:])
    return slug


#: Same threshold as the alert engine: a swing of >= $0.10 in either
#: direction. A quoted spread at or above it means the midpoint sits inside a
#: gap that no resting order fills, so it is displayed but never called
#: executable.
ALERT_THRESHOLD = 0.10


def alert_row_key(a: dict[str, Any]) -> str:
    """Identity of one alert row.

    Two rows are the same alert when market, direction and the
    previous -> current price pair match exactly, i.e. the engine fired on
    the identical step again. Mirrors ``rowKey`` in ``assets/alerts-view.js``;
    ``tests/test_alerts_view_parity.py`` asserts the two agree.
    """
    return "|".join([
        str(a.get("ticker")),
        str(a.get("direction")),
        str(a.get("previous")),
        str(a.get("current")),
    ])


def alert_spread(a: dict[str, Any]) -> float | None:
    """The quoted YES spread in dollars, or None when either side is absent."""
    try:
        bid = float(a.get("yes_bid"))
        ask = float(a.get("yes_ask"))
    except (TypeError, ValueError):
        return None
    return ask - bid


def group_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated alert rows, exactly as the browser does.

    The collector compares book midpoints between reference bars, so one
    sustained >= $0.10 move can re-fire on several consecutive snapshots and
    produce identical feed rows. Grouping them keeps first-appearance order,
    the most recent occurrence time, a repeat count, and flags a row whose
    quoted spread is wider than the alert threshold.

    Mirrors ``dedupeAlerts`` in ``assets/alerts-view.js``. The raw rows are
    never deleted from the snapshot; this only shapes what is displayed.
    """
    out: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for a in alerts or []:
        if not isinstance(a, dict):
            continue
        key = alert_row_key(a)
        spread = alert_spread(a)
        row = index.get(key)
        if row is None:
            row = dict(a)
            row["repeat_count"] = 1
            row["last_iso"] = a.get("iso")
            row["last_ts"] = a.get("ts")
            row["spread"] = spread
            row["wide_spread"] = spread is not None and spread >= ALERT_THRESHOLD
            index[key] = row
            out.append(row)
            continue
        row["repeat_count"] = row.get("repeat_count", 1) + 1
        ts = a.get("ts")
        last_ts = row.get("last_ts")
        if isinstance(ts, (int, float)) and (last_ts is None or ts > last_ts):
            row["last_ts"] = ts
        iso = a.get("iso")
        if iso and (not row.get("last_iso") or iso > row["last_iso"]):
            row["last_iso"] = iso
        # Latest quotes win.
        row["yes_bid"] = a.get("yes_bid")
        row["yes_ask"] = a.get("yes_ask")
        row["spread"] = spread
        row["wide_spread"] = spread is not None and spread >= ALERT_THRESHOLD
    return out


def age_label(generated_at: Any, generated_at_ts: Any = None) -> str:
    """Human age of the snapshot, so a stale view is never read as live."""
    ts = None
    if generated_at_ts:
        try:
            ts = float(generated_at_ts)
        except (TypeError, ValueError):
            ts = None
    if ts is None and generated_at:
        try:
            ts = time.mktime(time.strptime(str(generated_at)[:19],
                                            "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            ts = None
    if ts is None:
        return ""
    seconds = max(0, int(time.time() - ts))
    if seconds < 90:
        return f"{seconds}s old"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} min old"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h old"
    return f"{hours // 24} d old"


def equity_svg(points: list[dict[str, Any]], bankroll: float | None = None,
               width: int = 780, height: int = 230) -> str:
    """A small, dependency-free equity-curve chart.

    Plain SVG so the page needs no chart library and still renders with
    JavaScript disabled. Only observed points are drawn — the line is not
    smoothed, resampled or extrapolated.
    """
    pts = [p for p in (points or [])
           if isinstance(p, dict) and p.get("equity") is not None]
    if len(pts) < 2:
        return ('<div class="empty-state inline">The equity curve needs at '
                "least two recorded points. The simulator snapshots equity "
                "on every collector run, so this fills as runs accumulate."
                "</div>")

    pad_l, pad_r, pad_t, pad_b = 64, 18, 16, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    values = [float(p["equity"]) for p in pts]
    if bankroll:
        values.append(float(bankroll))
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    span = hi - lo
    lo -= span * 0.12
    hi += span * 0.12

    t0 = float(pts[0].get("ts") or 0)
    t1 = float(pts[-1].get("ts") or 0)
    if t1 <= t0:
        t1 = t0 + 1

    def x_of(ts: float) -> float:
        return pad_l + ((ts - t0) / (t1 - t0)) * plot_w

    def y_of(value: float) -> float:
        return pad_t + (1 - (value - lo) / (hi - lo)) * plot_h

    parts = [
        f'<svg class="equity-chart" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Simulated equity curve" '
        f'preserveAspectRatio="xMidYMid meet">'
    ]
    # horizontal grid + y labels
    for g in range(5):
        value = lo + (hi - lo) * g / 4
        y = y_of(value)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" class="eq-grid"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" class="eq-label" '
                     f'text-anchor="end">${value:,.0f}</text>')
    # starting bankroll reference
    if bankroll:
        y = y_of(float(bankroll))
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" class="eq-base"/>')
        parts.append(f'<text x="{width - pad_r}" y="{y - 5:.1f}" '
                     f'class="eq-label" text-anchor="end">start '
                     f'${float(bankroll):,.0f}</text>')
    # the curve
    coords = " ".join(f"{x_of(float(p.get('ts') or 0)):.1f},"
                      f"{y_of(float(p['equity'])):.1f}" for p in pts)
    parts.append(f'<polyline points="{coords}" class="eq-line"/>')
    for p in pts:
        parts.append(f'<circle cx="{x_of(float(p.get("ts") or 0)):.1f}" '
                     f'cy="{y_of(float(p["equity"])):.1f}" r="2.6" '
                     f'class="eq-dot"/>')
    # x labels
    parts.append(f'<text x="{pad_l}" y="{height - 10}" class="eq-label">'
                 f'{time.strftime("%H:%M", time.localtime(t0))}</text>')
    parts.append(f'<text x="{width - pad_r}" y="{height - 10}" class="eq-label" '
                 f'text-anchor="end">'
                 f'{time.strftime("%H:%M", time.localtime(t1))}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# resolutions.html
# ---------------------------------------------------------------------------

def build_resolutions(live: dict[str, Any], resolutions: dict[str, Any],
                      series_map: dict[str, str]) -> str:
    store = (resolutions or {}).get("resolutions") or {}
    by_topic: dict[str, list[dict[str, Any]]] = {t: [] for t in TOPIC_ORDER}
    out_of_scope = 0
    for rec in store.values():
        slug = resolution_topic(rec, series_map)
        if slug and slug in by_topic:
            by_topic[slug].append(rec)
        else:
            out_of_scope += 1
    for slug in by_topic:
        by_topic[slug].sort(key=lambda r: r.get("settlement_ts") or "",
                             reverse=True)

    total = sum(len(v) for v in by_topic.values())
    yes = sum(1 for rows in by_topic.values() for r in rows
              if (r.get("result") or "").lower() == "yes")
    no = sum(1 for rows in by_topic.values() for r in rows
             if (r.get("result") or "").lower() == "no")

    panels = []
    for slug in TOPIC_ORDER:
        rows = by_topic[slug]
        body = []
        for rec in rows[:40]:
            ticker = rec.get("ticker") or ""
            body.append(
                "<tr>"
                f'<td><a href="{html.escape(kalshi_market_url(ticker, rec.get("series_ticker"), rec.get("event_ticker")))}" '
                f'target="_blank" rel="noreferrer">{esc(rec.get("title"))}</a>'
                f'<small class="ticker">{esc(ticker)}</small></td>'
                f"<td>{result_chip(rec.get('result'))}</td>"
                f"<td>{cents(rec.get('settlement_value_dollars'))}</td>"
                f"<td>{esc((rec.get('settlement_ts') or '')[:19].replace('T', ' '))}</td>"
                f'<td><a class="source-link" target="_blank" rel="noreferrer" '
                f'href="{html.escape(rec.get("source_url") or API + "/markets/" + ticker)}">API ↗</a></td>'
                "</tr>")
        if not body:
            body.append('<tr><td colspan="5" class="empty-state">'
                        "No market from this topic has settled in the "
                        "tracked window yet.</td></tr>")
        panels.append(f"""
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon green">✓</span><div>
              <h2>{html.escape(TOPIC_LABEL[slug])}</h2>
              <p>{count(len(rows))} resolved · official <code>result</code>
              field, YES or NO</p></div></div>
            <a class="source-link" href="{API}/markets?status=settled" target="_blank"
               rel="noreferrer">Settled markets API ↗</a>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Result</th><th>Settlement value</th>
                <th>Settled at</th><th>Source</th></tr></thead>
              <tbody>{''.join(body)}</tbody>
            </table>
          </div>
        </section>""")

    # These three pages are built here rather than in build.py, so the
    # shared header has to be added explicitly: without it the page carries
    # no breadcrumb, no snapshot-age marker and no #livePill for desk.js to
    # switch to LIVE when a poll or stream lands.
    from .build import topbar  # local import: build.py imports this module

    return f"""{topbar("Resolved", live.get("generated_at", ""),
                       generated_at_ts=live.get("generated_at_ts"))}
        <section class="page-heading">
          <div><div class="eyebrow">SETTLEMENT TRACKING · KALSHI DEMO</div>
          <h1>Resolved events</h1>
          <p>Every tracked market that has settled, with the official YES / NO
          result Kalshi published for it. Settlement pays $1 per winning
          contract and $0 for the losing side.</p></div>
          <a class="button button-primary" href="live.html">◈ Open live desk</a>
        </section>
        <section class="stats-grid" aria-label="Settlement summary">
          <article class="stat-card"><span>Resolved in scope</span>
            <strong>{count(total)}</strong><small>Across the five topics</small></article>
          <article class="stat-card"><span>Resolved YES</span>
            <strong>{count(yes)}</strong>
            <small>{pct(yes / total) if total else "—"} of resolved</small></article>
          <article class="stat-card"><span>Resolved NO</span>
            <strong>{count(no)}</strong>
            <small>{pct(no / total) if total else "—"} of resolved</small></article>
          <article class="stat-card"><span>Tracked but out of scope</span>
            <strong>{count(out_of_scope)}</strong>
            <small>Settled outside the five topics</small></article>
          <article class="stat-card"><span>Total kept on file</span>
            <strong>{count(len(store))}</strong><small>Newest first</small></article>
        </section>
        <div class="notice notice-info">
          <span>ⓘ</span>
          <div><b>Where the result comes from</b>
          <p>The YES/NO chip is the <code>result</code> field of the official
          market response, not an inference from price. Settlement rules:
          <a href="{SETTLEMENT_DOC}" target="_blank" rel="noreferrer">Kalshi
          Market Settlement ↗</a>. A market is only listed here once Kalshi
          has published a settlement, so a still-open market never appears
          here.</p></div>
        </div>
        {''.join(panels)}"""


# ---------------------------------------------------------------------------
# trades.html
# ---------------------------------------------------------------------------

def _strategy_rows(strategies: dict[str, Any], by_strategy: dict[str, Any],
                   categories: dict[str, Any]) -> str:
    rows = []
    for slug, meta in (strategies or {}).items():
        stats = (by_strategy or {}).get(slug, {})
        rows.append(
            "<tr>"
            f'<td><b>{html.escape(meta.get("label", slug))}</b>'
            f'<small class="ticker">{html.escape(slug)}</small></td>'
            f"<td>{esc(meta.get('category'))}</td>"
            f"<td>{esc(meta.get('description'))}</td>"
            f"<td>{count(stats.get('trades'))}</td>"
            f"<td>{pct(stats.get('win_rate')) or '—'}</td>"
            f"<td>{money(stats.get('realized'))}</td>"
            f"<td>{money(stats.get('fees'))}</td>"
            "</tr>")
    if not rows:
        rows.append('<tr><td colspan="7" class="empty-state">No strategies '
                    "defined.</td></tr>")
    return "".join(rows)


def build_trades(live: dict[str, Any], state: dict[str, Any]) -> str:
    portfolio = live.get("portfolio") or {}
    strategies = live.get("strategies") or portfolio.get("strategies") or {}
    overall = portfolio.get("overall") or {}
    trades = portfolio.get("trades") or []
    open_positions = portfolio.get("open_positions_detail") or []
    settled = portfolio.get("settled_positions") or []
    curve = (state or {}).get("equity_curve") or []

    trade_rows = []
    for t in trades:
        ticker = t.get("ticker") or ""
        trade_rows.append(
            "<tr>"
            f"<td>{esc(time.strftime('%Y-%m-%d %H:%M', time.gmtime(t.get('ts') or 0)))}</td>"
            f'<td><a href="{html.escape(kalshi_market_url(ticker))}" target="_blank" '
            f'rel="noreferrer">{esc(ticker)}</a></td>'
            f"<td>{esc(t.get('strategy'))}</td>"
            f"<td>{esc((t.get('side') or '').upper())}</td>"
            f"<td>{esc(t.get('action'))}</td>"
            f"<td>{num(t.get('contracts'))}</td>"
            f"<td>{cents(t.get('price'))}</td>"
            f"<td>{money(t.get('fee'))}</td>"
            f"<td>{money(t.get('realized'))}</td>"
            f"<td>{esc(t.get('note'))}</td>"
            "</tr>")
    if not trade_rows:
        trade_rows.append('<tr><td colspan="10" class="empty-state">No '
                          "simulated trade has been opened yet. The ledger "
                          "fills when a strategy gate fires on a tracked "
                          "market.</td></tr>")

    open_rows = []
    for p in open_positions:
        ticker = p.get("ticker") or ""
        open_rows.append(
            "<tr>"
            f'<td><a href="{html.escape(p.get("market_url") or kalshi_market_url(ticker))}" '
            f'target="_blank" rel="noreferrer">{esc(p.get("title"))}</a>'
            f'<small class="ticker">{esc(ticker)}</small></td>'
            f"<td>{esc(p.get('topic'))}</td>"
            f"<td>{esc(p.get('strategy'))}</td>"
            f"<td>{esc((p.get('side') or '').upper())}</td>"
            f"<td>{num(p.get('contracts'))}</td>"
            f"<td>{cents(p.get('entry_price'))}</td>"
            f"<td>{cents(p.get('current_price'))}</td>"
            f"<td>{money(p.get('unrealized'))}</td>"
            "</tr>")
    if not open_rows:
        open_rows.append('<tr><td colspan="8" class="empty-state">No open '
                         "simulated position.</td></tr>")

    settled_rows = []
    for p in settled:
        ticker = p.get("ticker") or ""
        settled_rows.append(
            "<tr>"
            f'<td><a href="{html.escape(p.get("market_url") or kalshi_market_url(ticker))}" '
            f'target="_blank" rel="noreferrer">{esc(p.get("title"))}</a>'
            f'<small class="ticker">{esc(ticker)}</small></td>'
            f"<td>{esc(p.get('strategy'))}</td>"
            f"<td>{esc((p.get('side') or '').upper())}</td>"
            f"<td>{cents(p.get('entry_price'))}</td>"
            f"<td>{result_chip(p.get('result'))}</td>"
            f"<td class=\"{'positive' if (p.get('realized') or 0) >= 0 else 'negative'}\">"
            f"{money(p.get('realized'))}</td>"
            "</tr>")
    if not settled_rows:
        settled_rows.append('<tr><td colspan="6" class="empty-state">No '
                            "simulated position has resolved yet.</td></tr>")

    topic_rows = []
    for slug, stats in (portfolio.get("by_topic") or {}).items():
        topic_rows.append(
            "<tr>"
            f"<td>{html.escape(TOPIC_LABEL.get(slug, slug))}</td>"
            f"<td>{count(stats.get('trades'))}</td>"
            f"<td>{pct(stats.get('win_rate')) or '—'}</td>"
            f"<td>{money(stats.get('realized'))}</td>"
            f"<td>{money(stats.get('expectancy'))}</td>"
            "</tr>")
    if not topic_rows:
        topic_rows.append('<tr><td colspan="5" class="empty-state">No settled '
                          "trade yet.</td></tr>")

    category_rows = []
    for slug, stats in (portfolio.get("by_category") or {}).items():
        category_rows.append(
            "<tr>"
            f"<td>{html.escape(slug)}</td>"
            f"<td>{count(stats.get('trades'))}</td>"
            f"<td>{pct(stats.get('win_rate')) or '—'}</td>"
            f"<td>{money(stats.get('realized'))}</td>"
            "</tr>")
    if not category_rows:
        category_rows.append('<tr><td colspan="4" class="empty-state">No '
                             "settled trade yet.</td></tr>")

    # These three pages are built here rather than in build.py, so the
    # shared header has to be added explicitly: without it the page carries
    # no breadcrumb, no snapshot-age marker and no #livePill for desk.js to
    # switch to LIVE when a poll or stream lands.
    from .build import topbar  # local import: build.py imports this module

    return f"""{topbar("Trades and strategies", live.get("generated_at", ""),
                       generated_at_ts=live.get("generated_at_ts"))}
        <section class="page-heading">
          <div><div class="eyebrow">SIMULATED EXECUTION · PAPER LEDGER</div>
          <h1>Trades and strategies</h1>
          <p>The simulated book: every trade the rule set opened, the strategy
          that opened it, and how it resolved. Fees use Kalshi's published
          quadratic taker formula.</p></div>
          <span class="tag tag-purple">SIMULATED — NOT THE DEMO ACCOUNT</span>
        </section>
        <section class="stats-grid" aria-label="Portfolio summary">
          <article class="stat-card"><span>Equity</span>
            <strong>{money(portfolio.get('equity'))}</strong>
            <small>from {money(portfolio.get('starting_bankroll'))}</small></article>
          <article class="stat-card"><span>Realised P&amp;L</span>
            <strong>{money(portfolio.get('realized_pnl'))}</strong>
            <small>{count(overall.get('trades'))} settled</small></article>
          <article class="stat-card"><span>Win rate</span>
            <strong>{pct(overall.get('win_rate')) or '—'}</strong>
            <small>{count(overall.get('wins'))}W / {count(overall.get('losses'))}L</small></article>
          <article class="stat-card"><span>Fees paid</span>
            <strong>{money(portfolio.get('fees_paid'))}</strong>
            <small>official quadratic fee</small></article>
          <article class="stat-card"><span>Open positions</span>
            <strong>{count(portfolio.get('open_positions'))}</strong>
            <small>{money(portfolio.get('open_exposure'))} exposure</small></article>
        </section>
        <div class="notice notice-warn">
          <span>⚠</span>
          <div><b>This is a paper ledger, not your Kalshi demo balance</b>
          <p>Portfolio, order and fill endpoints on the demo exchange require
          signed credentials that this repository does not hold, so no order is
          ever sent and no demo-account balance is read. Every figure above is
          produced by the simulator from live public prices and settled from
          the official <code>result</code> field. Fee formula:
          <a href="{FEES_DOC}" target="_blank" rel="noreferrer">official fee
          schedule ↗</a>.</p></div>
        </div>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon green">⌁</span><div>
              <h2>Simulated equity curve</h2>
              <p>One point per collector run, from the ledger's own equity
              snapshot</p></div></div>
          </div>
          {equity_svg(curve, portfolio.get('starting_bankroll'))}
          <div class="table-foot"><span>{count(len(curve))} recorded points</span>
          <span>Only observed points are drawn — no smoothing or extrapolation</span></div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon violet">⚙</span><div>
              <h2>Strategy catalogue</h2>
              <p>The rule set the simulator applies — our model, not a Kalshi
              product</p></div></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Strategy</th><th>Category</th><th>Rule</th>
                <th>Trades</th><th>Win rate</th><th>Realised</th><th>Fees</th></tr></thead>
              <tbody>{_strategy_rows(strategies, portfolio.get('by_strategy') or {}, portfolio.get('by_category') or {})}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">⇄</span><div>
              <h2>Trade ledger</h2>
              <p>Every simulated trade, in order</p></div></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>When (UTC)</th><th>Market</th><th>Strategy</th>
                <th>Side</th><th>Action</th><th>Contracts</th><th>Price</th>
                <th>Fee</th><th>Realised</th><th>Note</th></tr></thead>
              <tbody>{''.join(trade_rows)}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon amber">◷</span><div>
              <h2>Open positions</h2>
              <p>Marked to the latest observed price</p></div></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Topic</th><th>Strategy</th>
                <th>Side</th><th>Contracts</th><th>Entry</th><th>Last</th>
                <th>Unrealised</th></tr></thead>
              <tbody>{''.join(open_rows)}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon green">✓</span><div>
              <h2>Settled positions</h2>
              <p>How each simulated trade actually resolved</p></div></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Strategy</th><th>Side</th>
                <th>Entry</th><th>Result</th><th>P&amp;L</th></tr></thead>
              <tbody>{''.join(settled_rows)}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">▦</span><div>
              <h2>Results by topic</h2>
              <p>Which subject areas the rule set is actually good at</p></div></div>
          </div>
          <div class="table-wrap">
            <table><thead><tr><th>Topic</th><th>Trades</th><th>Win rate</th>
              <th>Realised</th><th>Expectancy</th></tr></thead>
              <tbody>{''.join(topic_rows)}</tbody></table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">▦</span><div>
              <h2>Results by trade type</h2>
              <p>Categorised by the kind of trade the strategy is</p></div></div>
          </div>
          <div class="table-wrap">
            <table><thead><tr><th>Trade type</th><th>Trades</th><th>Win rate</th>
              <th>Realised</th></tr></thead>
              <tbody>{''.join(category_rows)}</tbody></table>
          </div>
        </section>"""


# ---------------------------------------------------------------------------
# suggestions.html
# ---------------------------------------------------------------------------

SUGGESTIONS: list[dict[str, Any]] = [
    {
        "group": "Liveness — how the data arrives",
        "items": [
            {
                "title": "Push the collector cadence from 15 minutes down to 5",
                "what": "A scheduled GitHub Actions run rebuilds the snapshot "
                        "every few minutes, and the browser polls "
                        "<code>assets/live.json</code> every 30 seconds.",
                "why": "A swing of $0.10 on a 30-cent contract is a 33% move. "
                       "At a 15-minute collection gap, most of those swings "
                       "happen between two snapshots and are never observed.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
                "source_label": "Candlestick endpoint (official)",
            },
            {
                "title": "Subscribe to the Kalshi WebSocket feed instead of polling",
                "what": "Replace the REST poll with the documented "
                        "WebSocket channel at "
                        "<code>wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2</code> "
                        "and push every tick straight into the page.",
                "why": "Ticks arrive immediately instead of up to 30 seconds "
                       "late, and the chart stops depending on a GitHub Pages "
                       "rebuild to show a fresh price.",
                "effort": "Medium",
                "status": "next",
                "status_label": "Next",
                "source": "https://docs.kalshi.com/getting_started/quick_start_websockets",
                "source_label": "WebSocket quick start (official)",
            },
            {
                "title": "Run the collector on a schedule that is not GitHub's",
                "why": "GitHub's scheduler is best-effort and can lag behind "
                       "on a busy queue, which is why a snapshot can look "
                       "older than the badge suggests.",
                "what": "Move the same collector script to a small always-on "
                        "host (or a self-hosted runner) and keep GitHub "
                        "Actions as the fallback.",
                "effort": "Medium",
                "status": "next",
                "status_label": "Next",
                "source": "https://docs.kalshi.com/getting_started/api_environments",
                "source_label": "API environments (official)",
            },
        ],
    },
    {
        "group": "Interactivity — what the trader sees",
        "items": [
            {
                "title": "Let the two chats filter by topic and by direction",
                "what": "Add topic chips (gas, elections, culture, crypto, "
                        "golf) and up/down toggles above each chat, and keep "
                        "the filter in the URL so a view can be shared.",
                "why": "Right now the chats mix all five topics into one "
                       "column, so the eye has to do the grouping that the "
                       "page could do.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/api-reference/market/get-markets",
                "source_label": "Get Markets (official)",
            },
            {
                "title": "Add a spread-history strip under the price chart",
                "what": "Plot the implied spread alongside the price line so a "
                        "wide-spread quote is visible next to the move it "
                        "produced.",
                "why": "Several of the largest recorded moves sit on markets "
                       "whose book is effectively empty, where the midpoint "
                       "moves a long way without a fillable price.",
                "effort": "Low",
                "status": "next",
                "status_label": "Next",
                "source": "https://docs.kalshi.com/getting_started/orderbook_responses",
                "source_label": "Order book responses (official)",
            },
            {
                "title": "One-click depth snapshot in every chat row",
                "what": "Render the resting size at the top three price "
                        "levels inside the alert row, not only in the side "
                        "panel, so a trader can judge whether a jump was "
                        "executable.",
                "why": "The brief asks how many contracts are available at a "
                       "given price; that number belongs next to the alert "
                       "that raised the question.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/getting_started/orderbook_responses",
                "source_label": "Order book responses (official)",
            },
            {
                "title": "Keyboard shortcuts and a command palette",
                "what": "Press <kbd>j</kbd>/<kbd>k</kbd> to move through "
                        "markets, <kbd>c</kbd> to chart the selected one, and "
                        "<kbd>/</kbd> to jump to a ticker.",
                "why": "A desk that is watched continuously is faster when the "
                       "common actions need no mouse.",
                "effort": "Low",
                "status": "next",
                "status_label": "Next",
                "source": "",
                "source_label": "",
            },
        ],
    },
    {
        "group": "Alerts — making the ≥ $0.10 signal trustworthy",
        "items": [
            {
                "title": "Show the reference price and window on every alert",
                "what": "Each chat row already prints the two prices it "
                        "compared. Add the explicit reference (bar open or "
                        "previous snapshot) and the elapsed time.",
                "why": "Without the reference, a reader cannot tell a real "
                       "$0.10 move from a change of measurement basis.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
                "source_label": "Candlestick endpoint (official)",
            },
            {
                "title": "Suppress alerts on markets with no executable size",
                "what": "Require a minimum resting size on the side that "
                        "moved before an alert is published.",
                "why": "A midpoint on an empty book can jump a long way and "
                       "still be untradeable, which is noise in a feed meant "
                       "to be actionable.",
                "effort": "Medium",
                "status": "review",
                "status_label": "Flagged for review",
                "source": "https://docs.kalshi.com/getting_started/orderbook_responses",
                "source_label": "Order book responses (official)",
            },
            {
                "title": "Deduplicate repeated alerts for the same market",
                "what": "Collapse repeats of one market inside a reference "
                        "window into a single row that counts its "
                        "occurrences.",
                "why": "The current buffer can show the same market many "
                       "times in a row, which buries the genuinely new "
                       "moves.",
                "effort": "Low",
                "status": "review",
                "status_label": "Flagged for review",
                "source": "",
                "source_label": "",
            },
            {
                "title": "Name the candidate cause, never assert it",
                "what": "Every ≥ $0.10 row links to the Kalshi event page — "
                        "which carries Kalshi's own live news feed for that "
                        "event — and to a news search built from the event "
                        "title.",
                "why": "The brief asks for the links that may have caused a "
                       "jump. Linking to the primary event page and a search "
                       "is honest; claiming an article caused a move is not.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/api-reference/events/get-events",
                "source_label": "Get Events (official)",
            },
        ],
    },
    {
        "group": "Trust — keeping every number checkable",
        "items": [
            {
                "title": "Read the real demo account when credentials exist",
                "what": "The adapter for signed "
                        "<code>GET /portfolio</code>, "
                        "<code>GET /orders</code> and "
                        "<code>GET /fills</code> already exists and is "
                        "unit-tested against a local mock; it activates as "
                        "soon as the demo key id and private key are set.",
                "why": "Until then the portfolio page shows a simulated book "
                       "rather than the demo account the brief asks to track.",
                "effort": "Low (code done)",
                "status": "credentials",
                "status_label": "Needs demo credentials",
                "source": "https://docs.kalshi.com/getting_started/requests_and_responses",
                "source_label": "Requests and authentication (official)",
            },
            {
                "title": "Show the snapshot age on every page",
                "what": "The top bar prints how long ago the published "
                        "snapshot was taken, and the counter keeps ticking "
                        "while the page is open.",
                "why": "A dashboard that refreshes every 15 minutes can be "
                       "half an hour old on a quiet schedule. Saying so is "
                       "cheaper than being wrong.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/getting_started/demo_env",
                "source_label": "Demo environment (official)",
            },
            {
                "title": "Publish the collector run log next to the data",
                "what": "Store the last run's request count, error list and "
                        "coverage numbers as JSON and render them on the "
                        "methodology page.",
                "why": "Coverage gaps are the difference between 'no alerts' "
                       "and 'no alerts were possible'.",
                "effort": "Low",
                "status": "shipped",
                "status_label": "Shipped",
                "source": "https://docs.kalshi.com/api-reference/market/get-markets",
                "source_label": "Get Markets (official)",
            },
        ],
    },
]


def build_suggestions(live: dict[str, Any]) -> str:
    blocks = []
    for group in SUGGESTIONS:
        cards = []
        for item in group["items"]:
            source = ""
            if item.get("source"):
                source = (f'<a class="source-link" href="{html.escape(item["source"])}" '
                          f'target="_blank" rel="noreferrer">'
                          f'{html.escape(item.get("source_label") or "Official source")} ↗</a>')
            cards.append(f"""
            <article class="sug-card">
              <div class="sug-head">
                <h3>{html.escape(item['title'])}</h3>
                <span class="sug-status {html.escape(item['status'])}">{html.escape(item['status_label'])}</span>
              </div>
              <p class="sug-what"><b>What</b> {item['what']}</p>
              <p class="sug-why"><b>Why</b> {item['why']}</p>
              <div class="sug-foot"><span class="sug-effort">Effort: {html.escape(item['effort'])}</span>
              {source}</div>
            </article>""")
        blocks.append(f"""
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon violet">✦</span><div>
              <h2>{html.escape(group['group'])}</h2>
              <p>What would make the desk more live and more usable</p></div></div>
          </div>
          <div class="sug-grid">{''.join(cards)}</div>
        </section>""")

    # These three pages are built here rather than in build.py, so the
    # shared header has to be added explicitly: without it the page carries
    # no breadcrumb, no snapshot-age marker and no #livePill for desk.js to
    # switch to LIVE when a poll or stream lands.
    from .build import topbar  # local import: build.py imports this module

    return f"""{topbar("Suggestions", live.get("generated_at", ""),
                       generated_at_ts=live.get("generated_at_ts"))}
        <section class="page-heading">
          <div><div class="eyebrow">ROADMAP · MAKING THE DESK LIVE</div>
          <h1>Suggestions</h1>
          <p>Prioritised, concrete ways to make this site more live and more
          interactive. Each item states what it is, why it matters, the
          effort it takes, and where it already stands. Where an official
          Kalshi page supports the idea, it is linked.</p></div>
        </section>
        <div class="notice notice-info">
          <span>ⓘ</span>
          <div><b>How to read this page</b>
          <p><span class="sug-status shipped">Shipped</span> is already on the
          site. <span class="sug-status next">Next</span> is a planned change.
          <span class="sug-status review">Flagged for review</span> is an open
          question that needs a decision. <span class="sug-status credentials">Needs
          demo credentials</span> cannot be completed from this repository
          alone.</p></div>
        </div>
        {''.join(blocks)}"""
