"""Static site builder.

Reads the collector snapshot (``data/live.json``) and writes every page the
GitHub Pages site serves. The published site must be useful with JavaScript
disabled, so all tables are pre-rendered here from verified data. The JS layer
only adds live polling on top.

Every generated row carries a source link:
  * market rows      -> the exact demo REST response for that market
  * series rows      -> GET /series/{ticker}
  * resolutions      -> GET /markets/{ticker} (which contains ``result``)
  * fee/model claims -> the official docs page that states the rule

Anything we could not read from the API is rendered as UNVERIFIED, never guessed.
"""

from __future__ import annotations

import html
import json
import os
from typing import Any

from collector.alerts import HIGH_ROI_GATE
from collector.collector import LIVE_PATH, load_json
from . import flagpage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://external-api.demo.kalshi.co/trade-api/v2"
SITE = "https://wingbangboozle1-lang.github.io/Trade2"

TOPIC_ORDER = ["gas-prices", "elections", "culture", "crypto", "golf"]

# One definition of "the model likes this" -- imported from the collector so
# the pre-rendered HTML, the browser and the snapshot cannot drift apart.
MODEL_NET_ROI_GATE = HIGH_ROI_GATE
TOPIC_FILE = {t: t for t in TOPIC_ORDER}


def esc(value: Any) -> str:
    if value is None or value == "":
        return '<span class="flag-badge">UNVERIFIED</span>'
    return html.escape(str(value))


def money(value: Any, places: int = 2) -> str:
    if value is None or value == "":
        return '<span class="flag-badge">UNVERIFIED</span>'
    try:
        return f"${float(value):,.{places}f}"
    except (TypeError, ValueError):
        return esc(value)


def cents(value: Any) -> str:
    if value is None or value == "":
        return '<span class="flag-badge">UNVERIFIED</span>'
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return esc(value)


def num(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return esc(value)


def cnt(value: Any) -> str:
    """Whole-number count (markets, positions, trades). Never shown as 750.00."""
    if value is None or value == "":
        return ""
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return esc(value)


def pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return esc(value)


def result_chip(result: str) -> str:
    r = (result or "").lower()
    if r == "yes":
        return '<span class="tag tag-yes">YES</span>'
    if r == "no":
        return '<span class="tag tag-no">NO</span>'
    return '<span class="flag-badge">UNVERIFIED</span>'


def nav(active: str, prefix: str = "") -> str:
    items = [("index.html", "Overview", "◫")]
    for slug in TOPIC_ORDER:
        label = {"gas-prices": "Gas prices", "elections": "Elections",
                 "culture": "Culture", "crypto": "Crypto", "golf": "Golf"}[slug]
        icon = {"gas-prices": "⌁", "elections": "◉", "culture": "✳",
                "crypto": "₿", "golf": "⛳"}[slug]
        items.append((f"categories/{slug}.html", label, icon))
    out = []
    for href, label, icon in items:
        cls = ' class="active"' if href == active else ""
        out.append(f'<a{cls} href="{prefix}{href}"><span>{icon}</span> {label}</a>')
    return "\n          ".join(out)


def research_nav(active: str, prefix: str = "") -> str:
    items = [("live.html", "Live desk", "◈"),
             ("index.html", "Overview", "◫"),
             ("summary.html", "Executive summary", "▤"),
             ("methodology.html", "Methodology", "⚙"),
             ("review.html", "Flagged for review", "⚑")]
    out = []
    for href, label, icon in items:
        if href == active:
            continue
        out.append(f'<a href="{prefix}{href}"><span>{icon}</span> {label}</a>')
    return "\n          ".join(out)


def page(title: str, active: str, body: str, prefix: str = "",
         description: str = "Kalshi demo market monitor, alerts and paper trading.") -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#f5f8f7" />
    <meta name="description" content="{html.escape(description)}" />
    <title>{html.escape(title)}</title>
    <link rel="stylesheet" href="{prefix}assets/styles.css" />
  </head>
  <body>
    <div class="shell">
      <aside class="sidebar">
        <a class="brand" href="{prefix}index.html"
          ><span class="brand-mark">K</span
          ><span><b>Market Desk</b><small>Kalshi · Demo monitor</small></span></a
        >
        <div class="side-label">Topics</div>
        <nav class="side-nav" aria-label="Topics">
          {nav(active, prefix)}
        </nav>
        <div class="side-label">Research</div>
        <nav class="side-nav" aria-label="Research">
          {research_nav(active, prefix)}
        </nav>
        <div class="side-label">Other workbooks</div>
        <nav class="side-nav" aria-label="Other workbooks">
          <a href="{prefix}kalshi-dashboard/"><span>◱</span> Topic workbook</a>
          <a href="{prefix}docs/"><span>◰</span> Live-data workbook</a>
        </nav>
        <div class="sidebar-foot">
          <span class="dot"></span><span>Public demo data</span
          ><a href="https://demo.kalshi.co/" target="_blank" rel="noreferrer"
            >Open Kalshi demo ↗</a
          >
        </div>
      </aside>
      <main class="main-content">
{body}
        <footer class="site-footer">
          <span>Simulated trading and public demo market data. Not investment advice.</span>
          <span><a href="{prefix}methodology.html">Methods &amp; sources</a>
          <a href="{prefix}review.html">Flagged for review</a></span>
        </footer>
      </main>
    </div>
    <script src="{prefix}assets/alerts-view.js" defer></script>
    <script src="{prefix}assets/nav.js" defer></script>
    <script src="{prefix}assets/desk.js" defer></script>
  </body>
</html>
"""


def topbar(crumb: str, generated: str, prefix: str = "") -> str:
    return f"""        <header class="topbar">
          <div class="breadcrumb">Workspace <span>/</span> {html.escape(crumb)}</div>
          <div class="top-actions">
            <span class="live-pill" id="livePill"><i></i> SNAPSHOT</span>
            <time id="updatedAt">Snapshot {html.escape(generated or '')}</time>
          </div>
        </header>"""


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def build_overview(live: dict[str, Any]) -> str:
    generated = live.get("generated_at", "")
    events = live.get("events", [])[:25]
    portfolio = live.get("portfolio", {})
    alerts = live.get("alerts", [])[:12]
    exchange = live.get("exchange", {})

    def event_row(e: dict[str, Any]) -> str:
        return (
            "<tr>"
            f'<td><a href="{html.escape(e.get("market_url",""))}" target="_blank" '
            f'rel="noreferrer">{esc(e.get("title"))}</a>'
            f'<small class="ticker">{esc(e.get("ticker"))}</small></td>'
            f"<td>{esc(e.get('topic'))}</td>"
            f"<td>{cents(e.get('yes_bid'))}</td>"
            f"<td>{cents(e.get('yes_ask'))}</td>"
            f"<td>{num(e.get('open_interest_contracts'))}</td>"
            f"<td>{money(e.get('open_interest_notional'))}</td>"
            f"<td>{num(e.get('volume_contracts'))}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{API}/markets/{html.escape(e.get("ticker",""))}">API ↗</a></td>'
            "</tr>"
        )

    # Group the ranked slice by topic so all five subjects stay visible. The
    # per-topic lists come pre-ranked from the collector; if an older snapshot
    # has no such key the page falls back to the flat top-25 list.
    by_topic = live.get("events_by_topic") or {}
    rows = []
    if by_topic:
        for slug in TOPIC_ORDER:
            bucket = by_topic.get(slug) or []
            if not bucket:
                continue
            label = {"gas-prices": "Gas prices", "elections": "Elections",
                     "culture": "Culture", "crypto": "Crypto",
                     "golf": "Golf"}.get(slug, slug.title())
            rows.append(
                f'<tr class="group-row"><td colspan="8">'
                f'<a href="categories/{slug}.html">{html.escape(label)}</a>'
                f'<span class="group-count">{len(bucket)} highest-value markets '
                f'· open the topic ↗</span></td></tr>')
            rows.extend(event_row(e) for e in bucket)
    else:
        rows.extend(event_row(e) for e in events)
    if not rows:
        rows.append('<tr><td colspan="8" class="empty-state">'
                    "No snapshot yet — the collector has not completed a run.</td></tr>")

    # Model shortlist: the same rule the live desk applies, evaluated here so
    # the overview page shows both chats without JavaScript.
    score_by_ticker = {s["ticker"]: s for s in (live.get("signals") or [])
                       if s.get("ticker")}
    model_alerts = [a for a in (live.get("alerts") or [])
                    if (score_by_ticker.get(a.get("ticker")) or {})
                    .get("net_roi", 0) >= MODEL_NET_ROI_GATE]

    alert_rows = []
    for a in alerts:
        arrow = "▲" if a.get("direction") == "up" else "▼"
        cls = "up" if a.get("direction") == "up" else "down"
        alert_rows.append(
            f'<div class="chat-row"><time>{html.escape((a.get("iso") or "")[11:19])}</time>'
            f'<span class="chat-delta {cls}">{arrow} {cents(a.get("abs_delta"))}</span>'
            f'<span class="chat-body"><a href="{html.escape(a.get("market_url",""))}" '
            f'target="_blank" rel="noreferrer">{esc(a.get("title"))}</a> '
            f'<small>{cents(a.get("previous"))} → {cents(a.get("current"))} · '
            f'{esc(a.get("topic"))}</small></span></div>'
        )
    if not alert_rows:
        alert_rows.append('<div class="empty-state inline">No ≥ $0.10 swing observed '
                          "in the current window yet. The feed fills as the "
                          "collector compares successive snapshots.</div>")

    # Resolutions across the five topics, newest first.
    resolution_rows = []
    all_resolutions = []
    for slug, bucket_res in (live.get("resolutions") or {}).items():
        for r in bucket_res or []:
            all_resolutions.append({**r, "topic": r.get("topic", slug)})
    all_resolutions.sort(key=lambda r: r.get("settlement_ts") or "", reverse=True)
    for r in all_resolutions[:20]:
        resolution_rows.append(
            "<tr>"
            f'<td><a href="{html.escape(r.get("human_url",""))}" target="_blank" '
            f'rel="noreferrer">{esc(r.get("title"))}</a>'
            f'<small class="ticker">{esc(r.get("ticker"))}</small></td>'
            f'<td>{esc(r.get("topic"))}</td>'
            f"<td>{result_chip(r.get('result'))}</td>"
            f"<td>{cents(r.get('settlement_value_dollars'))}</td>"
            f"<td>{esc((r.get('settlement_ts') or '')[:19].replace('T', ' '))}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{html.escape(r.get("source_url",""))}">API ↗</a></td>'
            "</tr>")

    model_rows = []
    for a in model_alerts[:12]:
        sig = score_by_ticker[a["ticker"]]
        arrow = "▲" if a.get("direction") == "up" else "▼"
        cls = "up" if a.get("direction") == "up" else "down"
        model_rows.append(
            f'<div class="chat-row"><time>{html.escape((a.get("iso") or "")[11:19])}</time>'
            f'<span class="chat-delta {cls}">{arrow} {cents(a.get("abs_delta"))}</span>'
            f'<span class="chat-body"><a href="{html.escape(a.get("market_url",""))}" '
            f'target="_blank" rel="noreferrer">{esc(a.get("title"))}</a> '
            f'<small>{cents(a.get("previous"))} → {cents(a.get("current"))} · '
            f'{esc(a.get("topic"))} · net ROI {pct(sig.get("net_roi"))}</small></span></div>'
        )
    if not model_rows:
        model_rows.append('<div class="empty-state inline">Nothing clears the '
                          f"model&rsquo;s net-ROI gate ({MODEL_NET_ROI_GATE:.0%}) right "
                          "now. An empty feed is an honest answer, not an error.</div>")

    status = "trading" if exchange.get("trading_active") else "not trading"
    # Resolutions whose series belongs to one of the five tracked topics. The
    # rest are real settlements from series we do not track (demo 15-minute
    # markets, other sports) and are reported, never guessed into a topic.
    attributed = live.get("resolutions_attributed")
    if attributed is None:
        attributed = sum(len(v or []) for v in
                         (live.get("resolutions") or {}).values())
    unattributed = live.get("resolutions_unattributed") or 0
    return f"""{topbar("Overview", generated)}
        <section class="page-heading">
          <div>
            <div class="eyebrow">KALSHI DEMO · LIVE MONITOR</div>
            <h1>Market overview</h1>
            <p>Highest-dollar open events across gas prices, elections, culture,
            crypto and golf — with ≥ $0.10 swing alerts and a simulated book.</p>
          </div>
          <a class="button button-primary" href="live.html">◈ Open live desk</a>
        </section>
        <section class="stats-grid" aria-label="Summary">
          <article class="stat-card"><span>Markets tracked</span>
            <strong>{cnt(live.get("observation_count"))}</strong>
            <small>This snapshot</small></article>
          <article class="stat-card"><span>Swings ≥ $0.10</span>
            <strong>{len(live.get("alerts", []))}</strong>
            <small>Rolling alert buffer</small></article>
          <article class="stat-card"><span>Open positions</span>
            <strong>{cnt(portfolio.get("open_positions"))}</strong>
            <small>Simulated</small></article>
          <article class="stat-card"><span>Equity</span>
            <strong>{money(portfolio.get("equity"))}</strong>
            <small>Start {money(portfolio.get("starting_bankroll"))}</small></article>
          <article class="stat-card"><span>Resolutions in a topic</span>
            <strong>{cnt(attributed)}</strong>
            <small>of {cnt(live.get("resolutions_count"))} stored · YES/NO from
            the official result field</small></article>
        </section>
        <div class="notice notice-info">
          <span>ⓘ</span>
          <div><b>Demo exchange status: {html.escape(status)}</b>
          <p>Market data is live from <code>{API}</code>. Trades are simulated;
          no order is ever sent. Every row links to the exact API response it
          came from.</p></div>
        </div>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">⌕</span><div>
              <h2>Highest-dollar open events, by topic</h2>
              <p>Each topic ranked by open-interest value (official
              open_interest_fp × notional_value_dollars). Topics are kept
              separate; a single cross-topic ranking would show elections only.</p></div></div>
            <a class="source-link" href="{API}/events?status=open" target="_blank"
               rel="noreferrer">Events API ↗</a>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Event / market</th><th>Topic</th><th>YES bid</th>
                <th>YES ask</th><th>Open interest</th><th>OI value</th>
                <th>Volume</th><th>Source</th></tr></thead>
              <tbody>{''.join(rows)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>Updated {html.escape(generated or 'n/a')}
          · {cnt(attributed)} of {cnt(live.get("resolutions_count"))} stored
          settlements belong to a tracked topic ({cnt(unattributed)} are from
          series outside the five topics and are listed on
          <a href="review.html">Flagged for review</a>)</span>
          <span>YES ask is implied as 1.00 − best NO bid (bids only, per docs)</span></div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon green">✓</span><div>
              <h2>Resolved — how each event ended</h2>
              <p>The official <code>result</code> field (YES or NO) with its
              settlement value, newest first, for markets whose series belongs
              to one of the five topics</p></div></div>
            <span class="source-link">{cnt(attributed)} resolutions from
            {cnt(live.get("resolutions_count"))} stored</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Topic</th><th>Result</th>
                <th>Settlement value</th><th>Settled at</th><th>Source</th></tr>
              </thead>
              <tbody>{''.join(resolution_rows) or
                '<tr><td colspan="6" class="empty-state">No resolved market from '
                'a tracked topic has been captured yet.</td></tr>'}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>read from
          <code>GET /markets?status=settled</code> and
          <code>GET /events?status=settled&amp;with_nested_markets=true</code></span>
          <span>YES pays $1.00, NO pays $0.00 per contract</span></div>
        </section>
        <section class="desk-grid two-chats">
          <article class="panel chat-panel alert-panel">
            <div class="panel-title">
              <div><span class="section-icon amber">◉</span><div>
                <h2>Swing chat — all events</h2>
                <p>Every observed move of at least $0.10 either way</p></div></div>
              <a class="source-link" href="live.html">Full live desk →</a>
            </div>
            <div class="chat-feed">{''.join(alert_rows)}</div>
          </article>
          <article class="panel chat-panel model-chat">
            <div class="panel-title">
              <div><span class="section-icon violet">★</span><div>
                <h2>Model shortlist</h2>
                <p>Swings on markets the model scores above a
                {MODEL_NET_ROI_GATE:.0%} net-ROI gate</p></div></div>
              <a class="source-link" href="methodology.html">Model rules →</a>
            </div>
            <div class="chat-feed">{''.join(model_rows)}</div>
            <div class="alert-note">Rule-based edge after Kalshi&rsquo;s published
            taker fee — a screen, not a prediction. Every outcome is scored on the
            <a href="summary.html#performance">performance table</a>.</div>
          </article>
        </section>"""


# ---------------------------------------------------------------------------
# Topic pages
# ---------------------------------------------------------------------------

def build_topic(slug: str, live: dict[str, Any]) -> str:
    generated = live.get("generated_at", "")
    topic = (live.get("topics") or {}).get(slug, {})
    label = topic.get("label") or slug.replace("-", " ").title()
    events = [e for e in live.get("events", []) if e.get("topic") == slug]
    resolutions = (live.get("resolutions") or {}).get(slug, [])

    market_rows = []
    for e in events[:60]:
        market_rows.append(
            "<tr>"
            f'<td><a href="{html.escape(e.get("market_url",""))}" target="_blank" '
            f'rel="noreferrer">{esc(e.get("title"))}</a>'
            f'<small class="ticker">{esc(e.get("ticker"))}</small></td>'
            f"<td>{cents(e.get('yes_bid'))}</td>"
            f"<td>{cents(e.get('yes_ask'))}</td>"
            f"<td>{num((e.get('liquidity') or {}).get('yes_bid_contracts'))}</td>"
            f"<td>{money(e.get('open_interest_notional'))}</td>"
            f"<td>{num(e.get('volume_contracts'))}</td>"
            f"<td>{esc((e.get('close_time') or '')[:16].replace('T',' '))}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{API}/markets/{html.escape(e.get("ticker",""))}">API ↗</a></td>'
            "</tr>")
    if not market_rows:
        market_rows.append('<tr><td colspan="8" class="empty-state">'
                           "No markets from this topic are in the current snapshot."
                           "</td></tr>")

    res_rows = []
    for r in resolutions[:40]:
        res_rows.append(
            "<tr>"
            f'<td><a href="{html.escape(r.get("human_url",""))}" target="_blank" '
            f'rel="noreferrer">{esc(r.get("title"))}</a>'
            f'<small class="ticker">{esc(r.get("ticker"))}</small></td>'
            f"<td>{result_chip(r.get('result'))}</td>"
            f"<td>{cents(r.get('settlement_value_dollars'))}</td>"
            f"<td>{esc((r.get('settlement_ts') or '')[:19].replace('T',' '))}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{html.escape(r.get("source_url",""))}">API ↗</a></td>'
            "</tr>")
    if not res_rows:
        res_rows.append('<tr><td colspan="5" class="empty-state">'
                        "No resolved market from this topic has been captured yet."
                        "</td></tr>")

    series_rows = []
    for s in (topic.get("series") or [])[:40]:
        sources = ", ".join(
            f'<a href="{html.escape(x.get("url",""))}" target="_blank" '
            f'rel="noreferrer">{html.escape(x.get("name") or "")}</a>'
            for x in (s.get("settlement_sources") or [])[:3]) or \
            '<span class="flag-badge">UNVERIFIED</span>'
        series_rows.append(
            "<tr>"
            f'<td>{esc(s.get("ticker"))}<small class="ticker">{esc(s.get("title"))}</small></td>'
            f"<td>{esc(s.get('frequency'))}</td>"
            f"<td>{esc(s.get('fee_type'))}</td>"
            f"<td>{sources}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{API}/series/{html.escape(s.get("ticker",""))}">API ↗</a></td>'
            "</tr>")

    return f"""{topbar(label, generated, "")}
        <section class="category-hero">
          <div class="eyebrow">TOPIC MONITOR · KALSHI DEMO</div>
          <h1>{html.escape(label)}</h1>
          <p>{esc(topic.get("notes"))}</p>
        </section>
        <section class="stats-grid">
          <article class="stat-card"><span>Series in scope</span>
            <strong>{cnt(topic.get("series_count"))}</strong><small>Matched live</small></article>
          <article class="stat-card"><span>Open events</span>
            <strong>{cnt(topic.get("event_count"))}</strong><small>This snapshot</small></article>
          <article class="stat-card"><span>Markets tracked</span>
            <strong>{cnt(topic.get("tracked_market_count"))}</strong><small>With order book</small></article>
          <article class="stat-card"><span>Resolved captured</span>
            <strong>{cnt(len(resolutions))}</strong><small>YES/NO logged</small></article>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">⌕</span><div>
              <h2>{html.escape(label)} markets</h2>
              <p>Ranked by open-interest value</p></div></div>
            <a class="source-link" href="{html.escape(topic.get('source_url') or API + '/series')}"
               target="_blank" rel="noreferrer">Series discovery API ↗</a>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Event / market</th><th>YES bid</th><th>YES ask</th>
                <th>Bid depth (contracts)</th><th>OI value</th><th>Volume</th>
                <th>Close</th><th>Source</th></tr></thead>
              <tbody>{''.join(market_rows)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>{cnt(topic.get("market_count"))} markets matched;
          top {len(events)} shown</span><span>Bid depth = resting YES bid contracts</span></div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon green">✓</span><div>
              <h2>Resolved — how each event ended</h2>
              <p>Official <code>result</code> field, YES or NO, with settlement value</p>
              </div></div>
            <a class="source-link" href="{API}/markets?status=settled" target="_blank"
               rel="noreferrer">Settled markets API ↗</a>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Result</th><th>Settlement value</th>
                <th>Settled at</th><th>Source</th></tr></thead>
              <tbody>{''.join(res_rows)}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">▤</span><div>
              <h2>Series in scope and settlement sources</h2>
              <p>Every series matched for this topic, with Kalshi's own named
              settlement source</p></div></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Series</th><th>Frequency</th><th>Fee type</th>
                <th>Settlement source</th><th>Source</th></tr></thead>
              <tbody>{''.join(series_rows) or '<tr><td colspan="5" class="empty-state">None matched</td></tr>'}</tbody>
            </table>
          </div>
        </section>"""


# ---------------------------------------------------------------------------
# Live desk
# ---------------------------------------------------------------------------

def build_live(live: dict[str, Any]) -> str:
    from collector.alerts import MAX_QUOTE_SPREAD

    # Market picker, grouped by topic with <optgroup>, so a trader picks a
    # subject first instead of scrolling 120 flat options. Populated here so the
    # control works with JavaScript disabled; desk.js rewrites it on new data.
    market_options = ['<option value="">Choose a market</option>']
    for slug in TOPIC_ORDER:
        rows = ((live.get("events_by_topic") or {}).get(slug)
                or [e for e in (live.get("events") or [])
                    if e.get("topic") == slug])[:12]
        if not rows:
            continue
        label = {"gas-prices": "Gas prices", "elections": "Elections",
                 "culture": "Culture", "crypto": "Crypto",
                 "golf": "Golf"}.get(slug, slug.title())
        market_options.append(f'<optgroup label="{html.escape(label)}">')
        for e in rows:
            market_options.append(
                f'<option value="{html.escape(e.get("ticker",""))}" '
                f'data-series="{html.escape(e.get("series_ticker") or "")}">'
                f'{html.escape((e.get("title") or e.get("ticker") or ""))}</option>')
        market_options.append("</optgroup>")
    market_options = "\n                  ".join(market_options)
    MAX_QUOTE_SPREAD_TEXT = f"{MAX_QUOTE_SPREAD:.2f}"
    generated = live.get("generated_at", "")
    portfolio = live.get("portfolio", {})
    # The browser applies the same shortlist rule as the pre-rendered page.
    # Publishing the threshold in the snapshot means there is one number, not
    # a constant duplicated in Python and JavaScript that can drift apart.
    snapshot = dict(live, model_gate=live.get("model_gate", MODEL_NET_ROI_GATE))
    payload = json.dumps(snapshot, default=str).replace("</", "<\\/")
    return f"""{topbar("Live desk", generated)}
        <section class="page-heading">
          <div>
            <div class="eyebrow">REAL-TIME · SIMULATED BOOK</div>
            <h1>Live desk</h1>
            <p>Price graph with seconds / minutes / hours windows, live order-book
            depth, and two scrolling alert chats: everything and the model's
            high-ROI shortlist.</p>
          </div>
          <span class="live-pill" id="streamState"><i></i> <span>connecting…</span></span>
        </section>
        <section class="desk-grid">
          <article class="panel chart-panel">
            <div class="panel-title">
              <div><span class="section-icon green">⌁</span><div>
                <h2>Contract price</h2>
                <p id="chartSubtitle">Select a market from the table or a chat row</p>
              </div></div>
              <div class="control-row">
                <select id="chartMarket" aria-label="Market">{market_options}
                </select>
                <div class="filter-tabs" id="windowTabs">
                  <button data-window="seconds">Seconds</button>
                  <button data-window="minutes" class="selected">Minutes</button>
                  <button data-window="hours">Hours</button>
                </div>
              </div>
            </div>
            <div class="chart-metrics">
              <div><small>Last</small><strong id="chartPrice">—</strong></div>
              <div><small>Change in window</small><strong id="chartChange">—</strong></div>
              <div><small>Best YES bid</small><strong id="chartBid">—</strong></div>
              <div><small>Implied YES ask</small><strong id="chartAsk">—</strong></div>
              <div class="chart-legend"><i></i> YES price</div>
            </div>
            <div class="chart-frame"><canvas id="priceChart" role="img"
              aria-label="Contract price over time"></canvas></div>
            <div class="chart-foot"><span>X: time · Y: YES price in dollars ·
            plotted from official 1-minute candles and live order-book mids</span>
            <span id="chartWindowLabel">Last 60 minutes</span></div>
          </article>
          <article class="panel depth-panel">
            <div class="panel-title">
              <div><span class="section-icon amber">▤</span><div>
                <h2>Liquidity</h2>
                <p id="depthSubtitle">Contracts resting at each price</p></div></div>
            </div>
            <div id="depthBook" class="depth-book">
              <div class="empty-state inline">Select a market to see its book.</div>
            </div>
            <div class="chart-foot"><span>Bids only — YES ask = 1.00 − best NO bid</span>
            <span id="depthStamp"></span></div>
          </article>
        </section>
        <section class="desk-grid two-chats">
          <article class="panel chat-panel">
            <div class="panel-title">
              <div><span class="section-icon">◉</span><div>
                <h2>All events</h2><p>Every swing ≥ $0.10, newest first</p></div></div>
              <span class="count-badge" id="allCount">0</span>
            </div>
            <div class="chat-feed tall" id="feedAll" aria-live="polite"></div>
          </article>
          <article class="panel chat-panel model-chat">
            <div class="panel-title">
              <div><span class="section-icon violet">★</span><div>
                <h2>Model shortlist</h2>
                <p>Swing alerts on markets clearing a {MODEL_NET_ROI_GATE:.0%}
                net-ROI gate after the published taker fee</p></div></div>
              <span class="count-badge" id="modelCount">0</span>
            </div>
            <div class="chat-feed tall" id="feedModel" aria-live="polite"></div>
            <div class="alert-note">Rule-based edge after Kalshi's published taker
            fee. Not a prediction of profit — outcomes are scored on the
            <a href="summary.html#performance">performance table</a>.</div>
          </article>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon amber">⚑</span><div>
              <h2>How a swing qualifies</h2>
              <p>Why an 80-cent print is not an 80-cent move</p></div></div>
          </div>
          <div style="padding: 4px 16px 14px; max-width: 980px; line-height: 1.55;">
            <p style="margin:0 0 8px;">An alert is published when the reference
            price of a market moves by at least <b>$0.10</b> either way
            <i>and</i> the quote it moves to is a real market price: two-sided,
            with a bid–ask width of at most <b>${MAX_QUOTE_SPREAD_TEXT}</b>.
            A quote with only one side is not published either: with no
            opposite side there is nothing to check it against.</p>
            <p style="margin:0; color:#7b8884; font-size:11px;">Without that
            gate the feed filled with phantom crashes: e.g.
            <code>KXPRESNOMD-28-AKLO</code> has a real book of
            <b>$0.002 bid / $0.003 ask</b>, yet a lone <b>$0.8030</b> ask prints
            for a single minute and reverts, and the mid swings
            $0.8030 → $0.0025 → $0.8030 every few minutes. Kalshi returns bids
            only, so a single unpaired print has no opposite side to check
            against — see
            <a href="https://docs.kalshi.com/getting_started/orderbook_responses"
               target="_blank" rel="noreferrer">Orderbook Responses ↗</a>. Those
            rows are kept in the
            <a href="review.html">Flagged for review</a> log with their API
            links, not deleted.</p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">⇄</span><div>
              <h2>Tracked markets</h2>
              <p>Click a row to chart it. Ranked by open-interest value.</p></div></div>
            <span class="tag tag-purple">SIMULATED BOOK · {money(portfolio.get("equity"))}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Topic</th><th>YES bid</th><th>YES ask</th>
                <th>Spread</th><th>Bid depth</th><th>OI value</th><th>Model side</th>
                <th>Net ROI</th></tr></thead>
              <tbody id="deskRows"></tbody>
            </table>
          </div>
        </section>
        <script id="snapshot" type="application/json">{payload}</script>"""


# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------

def build_methodology(live: dict[str, Any]) -> str:
    from collector.alerts import MAX_QUOTE_SPREAD
    return f"""{topbar("Methodology", live.get("generated_at", ""))}
        <section class="page-heading">
          <div><div class="eyebrow">HOW EVERY NUMBER IS PRODUCED</div>
          <h1>Methodology</h1>
          <p>Each rule below is implemented in code and tested. Nothing is
          estimated silently.</p></div>
        </section>
        <section class="panel text-panel">
          <h2>Endpoints in use</h2>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Purpose</th><th>Endpoint</th><th>Official source</th></tr></thead>
              <tbody>
                <tr><td>Exchange status</td><td><code>GET /exchange/status</code></td>
                  <td><a href="https://docs.kalshi.com/api-reference/exchange/get-exchange-status" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Series discovery</td><td><code>GET /series?category=…</code></td>
                  <td><a href="https://docs.kalshi.com/api-reference/market/get-series-list" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Open events</td><td><code>GET /events?status=open&amp;with_nested_markets=true</code></td>
                  <td><a href="https://docs.kalshi.com/api-reference/events/get-events" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Markets</td><td><code>GET /markets</code></td>
                  <td><a href="https://docs.kalshi.com/api-reference/market/get-markets" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Order books</td><td><code>GET /markets/{{ticker}}/orderbook</code></td>
                  <td><a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Candlesticks</td><td><code>GET /series/{{s}}/markets/{{t}}/candlesticks</code></td>
                  <td><a href="https://docs.kalshi.com/api-reference/market/get-market-candlesticks" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Settlement results</td><td><code>GET /markets?status=settled</code> → <code>result</code></td>
                  <td><a href="https://docs.kalshi.com/getting_started/market_settlement" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>Demo environment</td><td><code>{API}</code></td>
                  <td><a href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
                <tr><td>WebSocket (documented, not required)</td><td><code>wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2</code></td>
                  <td><a href="https://docs.kalshi.com/getting_started/quick_start_websockets" target="_blank" rel="noreferrer">docs ↗</a></td></tr>
              </tbody>
            </table>
          </div>
          <h2>Price, spread and depth</h2>
          <p>Kalshi returns <strong>bids only</strong>. Arrays are ascending, so the
          best bid is the <em>last</em> element. The implied YES ask is
          <code>1.00 − best NO bid</code> and the YES mid is the average of the two.
          Contract depth is the sum of <code>count_fp</code> at every resting price
          level, reported as contracts available at each price.</p>
          <h2>Swing threshold</h2>
          <p>An alert is raised when the reference price moves by at least
          <strong>${live.get("swap_threshold_dollars", 0.10):.2f}</strong> in either
          direction. The reference is the close of the most recent completed
          1-minute candle where one exists (<a
          href="https://docs.kalshi.com/api-reference/market/get-market-candlesticks"
          target="_blank" rel="noreferrer">Get Market Candlesticks</a>, where
          <code>period_interval</code> is in minutes and the valid values are
          1, 60 and 1440), and the previous stored observation otherwise. Measuring
          against the candle rather than only against the previous sample is what
          lets a gradual 20-cent drift alert, instead of being swallowed between
          two polls. Missing quotes are skipped, never treated as zero. A $0.10
          move on a $1 contract is 10 cents of settlement value.</p>
          <h2>Swing integrity gate</h2>
          <p>An alert is published only if the price it moves <em>to</em> is a real
          market price: two-sided, and no wider than
          <strong>${MAX_QUOTE_SPREAD:.2f}</strong>, and one-sided quotes are not
          published at all — with no opposite side there is nothing to check them
          against. This exists because
          the demo exchange prints single unpaired quotes on otherwise 0.2-cent
          markets: <code>KXPRESNOMD-28-AKLO</code> has a $0.002/$0.003 book yet a
          lone $0.8030 ask prints for one minute and reverts, repeatedly. Those were
          published as $0.80 crashes before the gate was added; they are logged on
          <a href="review.html">Flagged for review</a> with their API links. Kalshi
          returns bids only (<a
          href="https://docs.kalshi.com/getting_started/orderbook_responses"
          target="_blank" rel="noreferrer">Orderbook Responses</a>), so a quote with
          no opposite side has nothing to be checked against — which is exactly why
          it is not treated as a move.</p>
          <h2>Resolution tracking</h2>
          <p>A market is reported resolved from its official <code>result</code>
          field (<code>yes</code> or <code>no</code>) plus
          <code>settlement_value_dollars</code> and <code>settlement_ts</code>,
          read from <a href="https://docs.kalshi.com/api-reference/market/get-markets"
          target="_blank" rel="noreferrer">Get Markets</a> with
          <code>status=settled</code>. The demo API returns no
          <code>series_ticker</code> on settled markets, so the series is taken
          from the ticker prefix (<code>SERIES-EVENT[-STRIKE]</code>) and mapped
          through the series list. A settlement whose series is not one of the five
          tracked topics is counted but never assigned to a topic; both totals are
          printed on the overview and on <a href="review.html">Flagged for
          review</a>.</p>
          <h2>Fees</h2>
          <p>Simulated fills use Kalshi's published taker fee,
          <code>ceil(M × 0.07 × C × P × (1 − P))</code> to the cent, from the
          <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank"
          rel="noreferrer">official fee schedule</a>. All 42 published rows of that
          table are reproduced exactly by the implementation and are asserted in
          <code>tests/test_engine.py</code>. Fee-free series (multiplier 0) are
          respected via each series' own <code>fee_multiplier</code>.</p>
          <h2>The high-ROI filter</h2>
          <p>Fair value is the mid, pulled toward 0.50 in proportion to the spread —
          a wide book means the mid is unreliable. Edge is fair value minus the price
          actually paid to cross the spread. Net ROI divides edge after fees by that
          price. A market is shortlisted only when net ROI clears the published
          gate of <strong>{MODEL_NET_ROI_GATE:.0%}</strong> and the spread is tight.
          That single number is what the overview chat, the live desk chat and
          <code>high_roi_alerts</code> in the snapshot all use. This is a screen, not a forecast; the
          performance table shows realised results including every loss.</p>
          <h2>Settlement</h2>
          <p>Positions settle from the market's official <code>result</code> field:
          YES pays $1.00 per contract, NO pays nothing, as documented in
          <a href="https://docs.kalshi.com/getting_started/market_settlement"
          target="_blank" rel="noreferrer">Market Settlement</a>.</p>
          <h2>What is deliberately not claimed</h2>
          <ul>
            <li>No news article is attributed to a price move. The alert links to
            the market, not to a cause we cannot verify.</li>
            <li>The paper ledger is not your demo account balance. Authenticated
            portfolio endpoints require credentials this repo does not hold.</li>
            <li>Unadjusted open interest is not traded dollar volume.</li>
          </ul>
        </section>"""


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def build_performance_section(live: dict[str, Any]) -> str:
    p = live.get("portfolio", {})
    strategies = live.get("strategies", {})
    rows = []
    for slug, s in strategies.items():
        a = (p.get("by_strategy") or {}).get(slug, {})
        rows.append(
            "<tr>"
            f"<td><b>{html.escape(s.get('label', slug))}</b>"
            f"<small class=\"ticker\">{html.escape(s.get('description',''))}</small></td>"
            f"<td>{cnt(a.get('trades'))}</td><td>{cnt(a.get('wins'))}</td>"
            f"<td>{cnt(a.get('losses'))}</td><td>{pct(a.get('win_rate'))}</td>"
            f"<td>{money(a.get('realized'))}</td><td>{money(a.get('expectancy'))}</td>"
            f"<td>{pct(a.get('roi_on_cost'))}</td><td>{money(a.get('fees'))}</td></tr>")
    topic_rows = []
    for slug, a in (p.get("by_topic") or {}).items():
        topic_rows.append(
            "<tr>"
            f"<td>{html.escape(slug)}</td><td>{cnt(a.get('trades'))}</td>"
            f"<td>{pct(a.get('win_rate'))}</td><td>{money(a.get('realized'))}</td>"
            f"<td>{money(a.get('expectancy'))}</td></tr>")
    settled_rows = []
    for pos in (p.get("settled_positions") or [])[:50]:
        settled_rows.append(
            "<tr>"
            f"<td><a href=\"{html.escape(pos.get('market_url',''))}\" target=\"_blank\" "
            f"rel=\"noreferrer\">{esc(pos.get('title'))}</a>"
            f"<small class=\"ticker\">{esc(pos.get('ticker'))}</small></td>"
            f"<td>{esc(pos.get('strategy'))}</td><td>{esc(pos.get('side'))}</td>"
            f"<td>{cents(pos.get('entry_price'))}</td>"
            f"<td>{result_chip(pos.get('result'))}</td>"
            f"<td class=\"{'pos' if (pos.get('realized') or 0) >= 0 else 'neg'}\">"
            f"{money(pos.get('realized'))}</td></tr>")
    if not settled_rows:
        settled_rows.append('<tr><td colspan="6" class="empty-state">No simulated '
                            "position has resolved yet. The ledger fills as tracked "
                            "markets settle.</td></tr>")
    overall = p.get("overall", {})
    return f"""        <section class="panel" id="performance">
          <div class="panel-title">
            <div><span class="section-icon violet">⇄</span><div>
              <h2>Simulated portfolio performance</h2>
              <p>Paper ledger · every position, including losses</p></div></div>
            <span class="tag tag-purple">SIMULATED</span>
          </div>
          <section class="stats-grid compact">
            <article class="stat-card"><span>Equity</span>
              <strong>{money(p.get('equity'))}</strong>
              <small>from {money(p.get('starting_bankroll'))}</small></article>
            <article class="stat-card"><span>Realised P&amp;L</span>
              <strong>{money(p.get('realized_pnl'))}</strong>
              <small>{cnt(overall.get('trades'))} settled</small></article>
            <article class="stat-card"><span>Win rate</span>
              <strong>{pct(overall.get('win_rate'))}</strong>
              <small>{cnt(overall.get('wins'))}W / {cnt(overall.get('losses'))}L</small></article>
            <article class="stat-card"><span>Fees paid</span>
              <strong>{money(p.get('fees_paid'))}</strong>
              <small>official quadratic fee</small></article>
            <article class="stat-card"><span>Max drawdown</span>
              <strong>{pct(p.get('max_drawdown'))}</strong>
              <small>on simulated equity</small></article>
          </section>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Strategy</th><th>Trades</th><th>Wins</th><th>Losses</th>
                <th>Win rate</th><th>Realised</th><th>Expectancy</th>
                <th>ROI on cost</th><th>Fees</th></tr></thead>
              <tbody>{''.join(rows)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>Categorised by strategy type</span>
          <span>Blank cells mean the strategy has not traded yet</span></div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">▦</span><div>
              <h2>Results by topic</h2><p>Which subject areas the model is
              actually good at</p></div></div>
          </div>
          <div class="table-wrap">
            <table><thead><tr><th>Topic</th><th>Trades</th><th>Win rate</th>
              <th>Realised</th><th>Expectancy</th></tr></thead>
              <tbody>{''.join(topic_rows) or '<tr><td colspan="5" class="empty-state">No settled trades yet</td></tr>'}</tbody>
            </table>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon green">✓</span><div>
              <h2>Settled positions</h2><p>How each simulated trade actually
              resolved</p></div></div>
          </div>
          <div class="table-wrap">
            <table><thead><tr><th>Market</th><th>Strategy</th><th>Side</th>
              <th>Entry</th><th>Result</th><th>P&amp;L</th></tr></thead>
              <tbody>{''.join(settled_rows)}</tbody>
            </table>
          </div>
        </section>"""


def main() -> dict[str, Any]:
    live = load_json(LIVE_PATH, {})
    written = []

    def write(path: str, content: str) -> None:
        full = os.path.join(ROOT, path)
        os.makedirs(os.path.dirname(full) or ROOT, exist_ok=True)
        previous = None
        if os.path.exists(full):
            with open(full, encoding="utf-8") as fh:
                previous = fh.read()
        if previous != content:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        written.append(path)

    overview = build_overview(live)
    write("index.html", page("Kalshi Monitor — Overview", "index.html", overview,
                             description="Live Kalshi demo market monitor across gas "
                                         "prices, elections, culture, crypto and golf."))

    for slug in TOPIC_ORDER:
        write(f"categories/{slug}.html",
              page(f"{slug.replace('-', ' ').title()} — Kalshi Monitor",
                   f"categories/{slug}.html", build_topic(slug, live), prefix="../"))

    write("live.html", page("Live desk — Kalshi Monitor", "live.html",
                            build_live(live)))

    perf = build_performance_section(live)
    try:
        with open(os.path.join(ROOT, "summary.html"), encoding="utf-8") as fh:
            summary = fh.read()
    except FileNotFoundError:
        summary = ""
    if summary and "SIMULATED-PORTFOLIO-START" in summary:
        head, rest = summary.split("SIMULATED-PORTFOLIO-START", 1)
        _, tail = rest.split("SIMULATED-PORTFOLIO-END", 1)
        summary = head + "SIMULATED-PORTFOLIO-START" + \
            "\n<!-- generated:performance -->\n" + perf + \
            "<!-- SIMULATED-PORTFOLIO-END" + tail
        write("summary.html", summary)

    write("methodology.html", page("Methodology — Kalshi Monitor", "methodology.html",
                                   build_methodology(live)))

    write("review.html", page("Flagged for review — Kalshi Monitor", "review.html",
                              flagpage.render(live),
                              description="Unverified items and data irregularities "
                                          "found in Kalshi demo records."))

    # Write a machine-readable copy next to the site so the JS can fetch it
    # without hitting the Pages JSON mime restrictions.
    write("assets/live.json", json.dumps(live, default=str, indent=1))
    return {"written": written, "generated_at": live.get("generated_at")}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
