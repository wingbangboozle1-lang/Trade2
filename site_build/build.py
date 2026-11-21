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
import time
from typing import Any

from collector.collector import LIVE_PATH, load_json
from . import extras, flagpage, swingfeed
from .format import (API, api_market_url, bid_ask_cells, count, cents, esc,
                     kalshi_event_url, kalshi_market_url, last_price_of, money,
                     news_search_url, num, pct, quote_cell, result_chip, safe_url)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://wingbangboozle1-lang.github.io/Trade2"

TOPIC_ORDER = ["gas-prices", "elections", "culture", "crypto", "golf"]
TOPIC_FILE = {t: t for t in TOPIC_ORDER}

# ``cnt`` was the name another session gave the same integer formatter; it is
# kept as an alias so both names resolve to the one implementation.
cnt = count

DATA_DIR = os.path.join(ROOT, "data")
RESOLUTIONS_PATH = os.path.join(DATA_DIR, "resolutions.json")
SERIES_CACHE_PATH = os.path.join(DATA_DIR, "series_cache.json")
PORTFOLIO_STATE_PATH = os.path.join(DATA_DIR, "portfolio_state.json")
# The second collector writes its candlestick swing feed here every run. The
# root site reads it so the all-events chat and the alert history cannot
# disagree about how many ≥ $0.10 moves the exchange showed. See
# site_build/swingfeed.py for why, and what is NOT taken from it.
DOCS_ALERTS_PATH = os.path.join(ROOT, "docs", "data", "alerts.json")


def all_feed(live: dict[str, Any]) -> list[dict[str, Any]]:
    """The all-events chat feed: grouped midpoint moves plus candle-close moves.

    Grouping is ``extras.group_alerts`` — the same rule the browser applies
    (``tests/test_alerts_view_parity.py`` pins the two together). The candle-close
    rows were already deduped against this set in ``swingfeed.attach``, and they
    are never fed to the model chat: a published historical close is not a price
    anyone could have traded.
    """
    grouped = extras.group_alerts(live.get("alerts") or [])
    candle = live.get("candle_alerts") or []
    if not candle:
        return grouped
    merged = list(grouped) + list(candle)
    merged.sort(key=lambda a: float(a.get("ts") or 0), reverse=True)
    return merged


def all_feed_note(live: dict[str, Any]) -> str:
    """One line above the all-events chat saying what the added rows are.

    Printed only when rows were actually added. It states the basis, says the
    model chat excludes them, and gives the run stamp of the file they came
    from, so a reader can tell a 6-minute-old feed from a 6-hour-old one.
    """
    candle = live.get("candle_alerts") or []
    if not candle:
        return ""
    stats = live.get("candle_feed_stats") or {}
    when = str(stats.get("source_generated_at") or "").replace("T", " ")[:16]
    return ('<div class="chat-note"><b>' + count(len(candle)) +
            " row(s) measured on Kalshi's published candlestick closes</b> rather "
            "than a live order-book mid; each row links the candlestick series "
            "behind its two numbers"
            + (f" — that feed is the {esc(when)}Z collector run" if when else "")
            + ". The model chat does not show them.</div>")



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
             ("resolutions.html", "Resolved", "✓"),
             ("trades.html", "Trades", "⇄"),
             ("suggestions.html", "Suggestions", "✦"),
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


def topbar(crumb: str, generated: str, prefix: str = "",
           generated_at_ts: Any = None) -> str:
    age = extras.age_label(generated, generated_at_ts)
    age_html = (f'<span class="snap-age" id="snapshotAge" '
                f'data-generated-ts="{html.escape(str(generated_at_ts or ""))}">'
                f'{html.escape(age)}</span>'
                if age else "")
    return f"""        <header class="topbar">
          <div class="breadcrumb">Workspace <span>/</span> {html.escape(crumb)}</div>
          <div class="top-actions">
            <span class="live-pill" id="livePill"><i></i> SNAPSHOT</span>
            <time id="updatedAt">Snapshot {html.escape(generated or '')}</time>
            {age_html}
          </div>
        </header>"""


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def model_shortlist(live: dict[str, Any]) -> list[dict[str, Any]]:
    """The swing rows the model likes, with its net ROI attached.

    One gate for every renderer. The collector publishes ``high_roi_alerts`` from
    ``alerts.MODEL_MIN_NET_ROI``, so the overview, the live desk and the browser
    cannot each invent their own threshold. For a snapshot written before that
    field existed the published number is still read out of ``model_gate`` rather
    than hard-coded a second time.
    """
    published = live.get("high_roi_alerts")
    if isinstance(published, list) and published:
        return published
    gate = (live.get("model_gate") or {}).get("min_net_roi")
    threshold = float(gate) if gate is not None else 0.05
    signals = {x.get("ticker"): x for x in (live.get("signals") or [])
               if x.get("ticker")}
    out = []
    for a in (live.get("alerts") or []):
        sig = signals.get(a.get("ticker"))
        if sig and (sig.get("net_roi") or 0) >= threshold:
            row = dict(a)
            row["model_net_roi"] = sig.get("net_roi")
            out.append(row)
    return out


def _source_links(a: dict[str, Any], ticker: str) -> str:
    """Per-row source links: the API response the numbers came from, and the
    candlestick series behind a candle-close row.

    Every chat row gets one, so a trader can check the number behind the claim
    without leaving the feed — the same rule the tables follow.
    """
    out = []
    api = safe_url(a.get("source_url") or api_market_url(ticker)) if ticker else ""
    if api:
        out.append(f'<a href="{api}" target="_blank" rel="noreferrer noopener">'
                   f'API row ↗</a>')
    candle = safe_url(a.get("candle_source_url"))
    if candle:
        out.append(f'<a href="{candle}" target="_blank" rel="noreferrer noopener" '
                   f'title="The official Kalshi candlestick series the two closes '
                   f'were read from.">candle series ↗</a>')
    return "".join(out)


def alert_chat_row(a: dict[str, Any], model_roi: float | None = None) -> str:
    """One row of a swing chat.

    Every ≥ $0.10 move carries two extra links: the Kalshi event page (which
    shows Kalshi's own live news feed for that event) and a news search built
    from the event title. Neither asserts a cause — they are places to look.
    """
    arrow = "▲" if a.get("direction") == "up" else "▼"
    cls = "up" if a.get("direction") == "up" else "down"
    ticker = a.get("ticker") or ""
    title = a.get("title") or ticker
    topic = a.get("topic") or ""
    topic_label = extras.TOPIC_LABEL.get(topic, topic)
    market_url = a.get("market_url") or kalshi_market_url(
        ticker, a.get("series_ticker"), a.get("event_ticker"))
    # An event link needs the event ticker the API actually returned. A feed
    # whose rows carry only a market ticker gets no event link — inventing one
    # would be a guess dressed up as a source.
    event_ticker = str(a.get("event_ticker") or "").strip()
    event_url = (kalshi_event_url(event_ticker, a.get("series_ticker"))
                 if event_ticker else "")
    news_url = news_search_url(title, topic_label)
    roi = f" · net ROI {pct(model_roi)}" if model_roi is not None else ""
    badges = ""
    repeats = int(a.get("repeat_count") or 1)
    if repeats > 1:
        badges += (f'<span class="tag tag-purple" title="The same step fired '
                   f'again on later snapshots; identical rows are grouped.">'
                   f'×{repeats} repeats</span> ')
    if a.get("wide_spread"):
        badges += ('<span class="flag-badge" title="The quoted YES spread is at '
                   'least $0.10, so this midpoint is not an executable price.">'
                   'wide spread · not executable</span> ')
    # The collector stamps a verdict on every row it writes. A row without one
    # predates the rule and is labelled as such instead of being assumed
    # executable — the same no-claim discipline the tables use for blanks.
    quality = a.get("quality")
    if quality == "executable":
        badges += ('<span class="tag tag-yes" title="Both sides quoted, and the '
                   'YES spread is tighter than the $0.10 threshold, so the midpoint '
                   'sits inside a range a trader could transact in.">executable'
                   '</span> ')
    elif quality == swingfeed.CANDLE_QUALITY:
        badges += (f'<span class="flag-badge" title="'
                   f'{esc(a.get("quality_reason") or "")}">candlestick close · '
                   f'not a live mid</span> ')
    elif quality == "indicative":
        badges += (f'<span class="flag-badge" title="'
                   f'{esc(a.get("quality_reason") or "")}">indicative · not '
                   f'executable</span> ')
    elif quality is None:
        badges += ('<span class="tag tag-grey" title="Written before the collector '
                   'stated a price basis per row; no executability claim is made '
                   'either way.">pre-rule row</span> ')
    badge_html = (f'<span class="chat-badges">{badges}</span>' if badges else "")
    # What the two numbers being subtracted actually are. Stated on the row so a
    # mid-vs-mid step is never mistaken for two prints.
    basis = str(a.get("reference_basis") or "").strip()
    basis_html = f" · {esc(basis)}" if basis else ""
    depth_html = ""
    if a.get("spread") is not None:
        size = a.get("size_at_top")
        depth = (f"{count(size)} contracts at the level" if size is not None
                 else "no resting size at the level")
        depth_html = f' · YES spread {cents(a.get("spread"))} · {depth}'
    # Headlines the collector found inside ± six hours of the move. Labelled
    # candidates: no row on this site claims that an article caused a price.
    causes = []
    for head in (a.get("news") or [])[:2]:
        href = safe_url(head.get("url"))
        label = str(head.get("title") or "").strip()
        if href and label:
            causes.append(f'<a href="{href}" target="_blank" rel="noreferrer noopener">'
                          f'{esc(label)} ↗</a>')
    if causes:
        news_html = ('<span class="cause-links"><span class="cause-label">candidate '
                     'headline, not confirmed:</span>' + " ".join(causes) + "</span>")
    else:
        why = str(a.get("news_status") or "no news lookup recorded for this row").strip()
        news_html = (f'<span class="cause-links"><span class="cause-none" title="'
                     f'{esc(why)}">no verified news link · {esc(why)}</span></span>')
    links = [_source_links(a, ticker)]
    if event_url:
        links.append(f'<a href="{html.escape(event_url)}" target="_blank" '
                     f'rel="noreferrer">Event page ↗</a>')
    links.append(f'<a href="{html.escape(news_url)}" target="_blank" '
                 f'rel="noreferrer">News search ↗</a>')
    return (
        f'<div class="chat-row"><time>{html.escape((a.get("iso") or "")[11:19])}</time>'
        f'<span class="chat-delta {cls}">{arrow} {cents(a.get("abs_delta"))}</span>'
        f'<span class="chat-body"><a href="{safe_url(market_url) or "#"}" '
        f'target="_blank" rel="noreferrer">{esc(title)}</a> '
        f'<small>{cents(a.get("previous"))} → {cents(a.get("current"))} · '
        f'{esc(topic)}{roi}{basis_html}{depth_html}</small>'
        f'{badge_html}'
        f'{news_html}'
        f'<span class="cause-links">' + "".join(links) + '</span>'
        f'</span></div>'
    )


def build_overview(live: dict[str, Any]) -> str:
    generated = live.get("generated_at", "")
    events = live.get("events", [])
    portfolio = live.get("portfolio", {})
    alerts = live.get("alerts", [])
    exchange = live.get("exchange", {})
    signals = {s.get("ticker"): s for s in (live.get("signals") or [])
               if s.get("ticker")}

    # -- highest-dollar events, grouped by topic --------------------------
    # Topics stay separate and the events inside a topic stay together, so a
    # trader reads one subject at a time instead of one long mixed list.
    by_topic: dict[str, list[dict[str, Any]]] = {t: [] for t in TOPIC_ORDER}
    for e in events:
        slug = e.get("topic")
        if slug in by_topic:
            by_topic[slug].append(e)
    for slug in by_topic:
        by_topic[slug].sort(
            key=lambda r: r.get("open_interest_notional") or 0, reverse=True)

    topic_blocks = []
    for slug in TOPIC_ORDER:
        rows = []
        for e in by_topic[slug][:6]:
            bid_cell, ask_cell = bid_ask_cells(e)
            rows.append(
                "<tr>"
                f'<td><a href="{safe_url(e.get("market_url","")) or "#"}" target="_blank" '
                f'rel="noreferrer">{esc(e.get("title"))}</a>'
                f'<small class="ticker">{esc(e.get("ticker"))}</small></td>'
                f"<td>{bid_cell}</td>"
                f"<td>{ask_cell}</td>"
                f"<td>{cents(last_price_of(e))}</td>"
                f"<td>{num(e.get('open_interest_contracts'))}</td>"
                f"<td>{money(e.get('open_interest_notional'))}</td>"
                f"<td>{num(e.get('volume_contracts'))}</td>"
                f'<td><a class="source-link" target="_blank" rel="noreferrer" '
                f'href="{API}/markets/{html.escape(e.get("ticker",""))}">API ↗</a></td>'
                "</tr>")
        if not rows:
            rows.append('<tr><td colspan="8" class="empty-state">'
                        "No open market from this topic in the current "
                        "snapshot.</td></tr>")
        topic_meta = (live.get("topics") or {}).get(slug, {})
        topic_blocks.append(f"""
          <tbody class="topic-group">
            <tr class="topic-head"><th colspan="8">
              <a href="categories/{slug}.html">{html.escape(extras.TOPIC_LABEL.get(slug, slug))}</a>
              <span class="topic-head-meta">Top {count(len(by_topic[slug][:6]))} of
                {count(topic_meta.get("tracked_market_count"))} tracked markets ·
                {count(topic_meta.get("series_count"))} series in scope</span>
            </th></tr>
            {''.join(rows)}
          </tbody>""")
    if not events:
        topic_blocks.append('<tbody><tr><td colspan="8" class="empty-state">'
                            "No snapshot yet — the collector has not completed "
                            "a run.</td></tr></tbody>")

    topic_jump = " · ".join(
        f'<a href="categories/{slug}.html">{html.escape(extras.TOPIC_LABEL.get(slug, slug))}</a>'
        for slug in TOPIC_ORDER)

    # -- the two chats -----------------------------------------------------
    # Grouped with the same rule the browser uses (assets/alerts-view.js), so
    # the server-rendered feed and the live one agree.
    grouped = extras.group_alerts(alerts)
    # The all-events chat additionally carries the candlestick-close moves the
    # other collector published for these same markets (site_build/swingfeed.py).
    # The model chat deliberately does not: it stays gated on an executable
    # midpoint, because that is the one claim a trader acts on.
    feed = all_feed(live)
    feed_note = all_feed_note(live)
    alert_rows = [alert_chat_row(a) for a in feed[:14]]
    if not alert_rows:
        refused_n = len(live.get("suppressed_alerts") or [])
        alert_rows.append(
            '<div class="empty-state inline">No ≥ $0.10 swing on a two-sided book in '
            "the current buffer, and no candlestick-close move in the window. "
            + (f"{refused_n} midpoint move{'s' if refused_n != 1 else ''} the quote "
               'rule refused '
               f'{"are" if refused_n != 1 else "is"} listed with the reason on '
               '<a href="review.html#refused">Flagged for review</a>. '
               if refused_n else
               "The feed fills as the collector compares successive snapshots. ")
            + "</div>")
    if feed_note and alert_rows:
        alert_rows.insert(0, feed_note)

    model_rows = []
    shortlist = {a.get("ticker"): a for a in model_shortlist(live)}
    for a in grouped:
        pick = shortlist.get(a.get("ticker"))
        if pick is not None:
            model_rows.append(alert_chat_row(a, pick.get("model_net_roi")))
    if not model_rows:
        picks = sorted(signals.values(),
                       key=lambda s: s.get("score") or 0, reverse=True)[:8]
        for sig in picks:
            model_rows.append(
                f'<div class="chat-row"><time>{html.escape((sig.get("ts") and time.strftime("%H:%M", time.gmtime(sig["ts"])) or ""))}</time>'
                f'<span class="chat-delta up">★ {pct(sig.get("net_roi"))}</span>'
                f'<span class="chat-body"><a href="{safe_url(sig.get("market_url","")) or "#"}" '
                f'target="_blank" rel="noreferrer">{esc(sig.get("title"))}</a> '
                f'<small>{esc((sig.get("side") or "").upper())} at '
                f'{cents(sig.get("executable_price"))} · {esc(sig.get("topic"))} · '
                f'no ≥ $0.10 swing yet</small></span></div>')
    if not model_rows:
        model_rows.append('<div class="empty-state inline">Nothing clears the '
                           "model's net-ROI gate right now. An empty feed is an "
                           "honest answer.</div>")

    # Only assert a trading state when the API actually reported the documented
    # ``trading_active`` boolean; an absent field is *unknown*, not "not trading".
    if "trading_active" in exchange:
        status = "trading" if exchange.get("trading_active") else "not trading"
    elif exchange.get("error"):
        status = f"unknown (status call failed)"
    else:
        status = "unknown (trading_active not returned)"
    return f"""{topbar("Overview", generated, generated_at_ts=live.get("generated_at_ts"))}
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
            <strong>{count(live.get("observation_count"))}</strong>
            <small>This snapshot</small></article>
          <article class="stat-card"><span>Swings ≥ $0.10</span>
            <strong>{count(len(all_feed(live)))}</strong>
            <small>{count(len(live.get("alerts", [])))} live mid ·
              {count(len(live.get("candle_alerts") or []))} candle close</small></article>
          <article class="stat-card"><span>Open positions</span>
            <strong>{count(portfolio.get("open_positions"))}</strong>
            <small>Simulated</small></article>
          <article class="stat-card"><span>Equity</span>
            <strong>{money(portfolio.get("equity"))}</strong>
            <small>Start {money(portfolio.get("starting_bankroll"))}</small></article>
          <article class="stat-card"><span>Resolved tracked</span>
            <strong>{count(live.get("resolutions_count"))}</strong>
            <small>YES/NO from official result</small></article>
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
              <h2>Highest-dollar open events</h2>
              <p>Grouped by topic, each topic ranked by open-interest value
              (official open_interest_fp × notional_value_dollars)</p></div></div>
            <a class="source-link" href="{API}/events?status=open" target="_blank"
               rel="noreferrer">Events API ↗</a>
          </div>
          <div class="topic-jump">{topic_jump}</div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Event / market</th><th>YES bid</th>
                <th>YES ask</th><th>Last</th>
                <th title="open_interest_fp from the same market record, in contracts">OI (contracts)</th>
                <th title="open_interest_fp × notional_value_dollars, both official fields of the same market record. Where a series settles at $1.00 a contract — most binary series do — this equals the contract column, which is arithmetic, not a duplicated number.">OI value</th>
                <th title="volume_fp, contracts traded. The API publishes no traded-dollar figure, so none is shown.">Volume</th>
                <th>Source</th></tr></thead>
              {''.join(topic_blocks)}
            </table>
          </div>
          <div class="table-foot"><span>Updated {html.escape(generated or 'n/a')}</span>
          <span>YES ask is implied as 1.00 − best NO bid (bids only, per docs)</span></div>
        </section>
        <section class="desk-grid two-chats">
          <article class="panel alert-panel">
            <div class="panel-title">
              <div><span class="section-icon amber">◉</span><div>
                <h2>Swing chat — all events</h2>
                <p>Every observed move of at least $0.10 either way</p></div></div>
              <a class="source-link" href="live.html">Full live desk →</a>
            </div>
            <div class="chat-feed tall">{''.join(alert_rows)}</div>
            <div class="alert-note">Each row links to the Kalshi event page —
            which carries Kalshi's own news feed for that event — and to a
            news search for the event title. Neither asserts a cause.</div>
          </article>
          <article class="panel alert-panel model-chat">
            <div class="panel-title">
              <div><span class="section-icon violet">★</span><div>
                <h2>Model shortlist — high ROI</h2>
                <p>Only the swings the model scores as high ROI</p></div></div>
              <a class="source-link" href="trades.html">How it is scored →</a>
            </div>
            <div class="chat-feed tall">{''.join(model_rows)}</div>
            <div class="alert-note">Rule-based edge after Kalshi's published
            taker fee. Not a prediction of profit — outcomes are scored on the
            <a href="trades.html">trades page</a>.</div>
          </article>
        </section>"""


# ---------------------------------------------------------------------------
# Topic pages
# ---------------------------------------------------------------------------

def build_topic(slug: str, live: dict[str, Any],
               resolutions: list[dict[str, Any]] | None = None) -> str:
    generated = live.get("generated_at", "")
    topic = (live.get("topics") or {}).get(slug, {})
    label = topic.get("label") or slug.replace("-", " ").title()
    events = [e for e in live.get("events", []) if e.get("topic") == slug]
    if resolutions is None:
        resolutions = (live.get("resolutions") or {}).get(slug, [])

    market_rows = []
    for e in events[:60]:
        bid_cell, ask_cell = bid_ask_cells(e)
        market_rows.append(
            "<tr>"
            f'<td><a href="{safe_url(e.get("market_url","")) or "#"}" target="_blank" '
            f'rel="noreferrer">{esc(e.get("title"))}</a>'
            f'<small class="ticker">{esc(e.get("ticker"))}</small></td>'
            f"<td>{bid_cell}</td>"
            f"<td>{ask_cell}</td>"
            f"<td>{cents(last_price_of(e))}</td>"
            f"<td>{num((e.get('liquidity') or {}).get('yes_bid_contracts'))}</td>"
            f"<td>{money(e.get('open_interest_notional'))}</td>"
            f"<td>{num(e.get('volume_contracts'))}</td>"
            f"<td>{esc((e.get('close_time') or '')[:16].replace('T',' '))}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{API}/markets/{html.escape(e.get("ticker",""))}">API ↗</a></td>'
            "</tr>")
    if not market_rows:
        market_rows.append('<tr><td colspan="9" class="empty-state">'
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
            f'href="{safe_url(r.get("source_url","")) or "#"}">API ↗</a></td>'
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

    if slug == "culture":
        culture_url = f"{API}/series?category=Culture"
        entertainment_url = f"{API}/series?category=Entertainment"
        discovery_sources = (
            f'<a class="source-link" href="{html.escape(culture_url)}" '
            f'target="_blank" rel="noreferrer">Culture series API ↗</a> · '
            f'<a class="source-link" href="{html.escape(entertainment_url)}" '
            f'target="_blank" rel="noreferrer">Entertainment series API ↗</a>')
    else:
        discovery_url = topic.get("source_url") or f"{API}/series"
        discovery_sources = (
            f'<a class="source-link" href="{html.escape(discovery_url)}" '
            'target="_blank" rel="noreferrer">Series discovery API ↗</a>')

    return f"""{topbar(label, generated, "", live.get("generated_at_ts"))}
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
            {discovery_sources}
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Event / market</th><th>YES bid</th><th>YES ask</th>
                <th>Last</th><th>Bid depth (contracts)</th><th>OI value</th><th>Volume</th>
                <th>Close</th><th>Source</th></tr></thead>
              <tbody>{''.join(market_rows)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>{cnt(topic.get("market_count"))} markets matched;
          top {len(events)} shown</span><span>Bid depth = resting YES bid contracts · '
          'bid/ask/Last are the values this row's own market response carries</span></div>
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
    generated = live.get("generated_at", "")
    portfolio = live.get("portfolio", {})
    payload = json.dumps(live, default=str).replace("</", "<\\/")

    # Pre-render the desk so it is useful with JavaScript disabled. The JS
    # layer replaces these blocks when it boots; until then, and for readers
    # who never enable it, the table and both chats still carry real data.
    signals = {s.get("ticker"): s for s in (live.get("signals") or [])
               if s.get("ticker")}
    alerts = extras.group_alerts(live.get("alerts") or [])
    feed_rows = all_feed(live)
    feed_all = "".join(alert_chat_row(a) for a in feed_rows[:40])
    if not feed_all:
        feed_all = ('<div class="empty-state inline">No ≥ $0.10 move observed yet. '
                    "The feed fills as successive snapshots are compared.</div>")
    else:
        feed_all = all_feed_note(live) + feed_all
    model_rows = []
    shortlist = {a.get("ticker"): a for a in model_shortlist(live)}
    for a in alerts:
        pick = shortlist.get(a.get("ticker"))
        if pick is not None:
            model_rows.append(alert_chat_row(a, pick.get("model_net_roi")))
    if not model_rows:
        model_html = ('<div class="empty-state inline">Nothing clears the '
                      "model's net-ROI gate right now. An empty feed is an "
                      "honest answer.</div>")
    else:
        model_html = "".join(model_rows[:40])

    desk_rows = []
    for e in (live.get("events") or [])[:40]:
        liq = e.get("liquidity") or {}
        sig = signals.get(e.get("ticker"))
        side_cell = "—"
        roi_cell = "—"
        if sig:
            side_cell = ('<span class="tag tag-yes">'
                         + html.escape(str(sig.get("side") or "").upper())
                         + "</span>")
            roi_cell = pct(sig.get("net_roi"))
        bid_cell, ask_cell = bid_ask_cells(e)
        desk_rows.append(
            "<tr>"
            f'<td><a href="{safe_url(e.get("market_url","")) or "#"}" target="_blank" '
            f'rel="noreferrer">{esc(e.get("title"))}</a>'
            f'<small class="ticker">{esc(e.get("ticker"))}</small></td>'
            f"<td>{esc(e.get('topic'))}</td>"
            f"<td>{bid_cell}</td>"
            f"<td>{ask_cell}</td>"
            f"<td>{cents(last_price_of(e))}</td>"
            f"<td>{cents(liq.get('spread'))}</td>"
            f"<td>{num(liq.get('yes_bid_contracts'))}</td>"
            f"<td>{money(e.get('open_interest_notional'))}</td>"
            f"<td>{side_cell}</td>"
            f"<td>{roi_cell}</td>"
            "</tr>")
    if not desk_rows:
        desk_rows.append('<tr><td colspan="10" class="empty-state">No market '
                         "rows in this snapshot.</td></tr>")

    return f"""{topbar("Live desk", generated, "", live.get("generated_at_ts"))}
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
                <select id="chartMarket" aria-label="Market"><option value="">Choose a market</option></select>
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
            <div class="chart-notes" id="chartNotes" aria-live="polite"></div>
            <div class="chart-foot"><span>X: time · Y: YES price in dollars</span>
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
                <h2>All events</h2><p>Every swing ≥ $0.10, newest first — live
                midpoint moves plus the published candlestick-close moves</p></div></div>
              <span class="count-badge" id="allCount">0</span>
            </div>
            <div class="chat-feed tall" id="feedAll" aria-live="polite">{feed_all}</div>
          </article>
          <article class="panel chat-panel model-chat">
            <div class="panel-title">
              <div><span class="section-icon violet">★</span><div>
                <h2>Model shortlist</h2>
                <p>Filtered to signals the model scores as high ROI</p></div></div>
              <span class="count-badge" id="modelCount">0</span>
            </div>
            <div class="chat-feed tall" id="feedModel" aria-live="polite">{model_html}</div>
            <div class="alert-note">Rule-based edge after Kalshi's published taker
            fee. Not a prediction of profit — outcomes are scored on the
            <a href="summary.html#performance">performance table</a>.</div>
          </article>
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
                <th>Last</th><th>Spread</th><th>Bid depth</th><th>OI value</th>
                <th>Model side</th><th>Net ROI</th></tr></thead>
              <tbody id="deskRows">{''.join(desk_rows)}</tbody>
            </table>
          </div>
        </section>
        <script id="snapshot" type="application/json">{payload}</script>"""


# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------

def build_methodology(live: dict[str, Any]) -> str:
    return f"""{topbar("Methodology", live.get("generated_at", ""), "", live.get("generated_at_ts"))}
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
          <p>An alert is raised when the YES mid moves by at least
          <strong>${live.get("swap_threshold_dollars", 0.10):.2f}</strong> between two
          consecutive observations of the same market. Missing quotes are skipped,
          never treated as zero. A $0.10 move on a $1 contract is 10 cents of
          settlement value.</p>
          <h2>Fees</h2>
          <p>Simulated fills use Kalshi's published taker fee,
          <code>ceil(M × 0.07 × C × P × (1 − P))</code> to the cent, from the
          <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank"
          rel="noreferrer">official fee schedule</a>. All 42 published rows of that
          table are reproduced exactly by the implementation and are asserted in
          <code>tests/test_engine.py</code>. The <code>trading/</code> engine
          respects each series' own <code>fee_multiplier</code>; the collector's
          simulated ledger, which is what <code>trades.html</code> publishes,
          applies a multiplier of 1 to every series because it calls
          <code>kalshi_fee(price, contracts)</code> without one — that difference
          is listed on <a href="review.html">Flagged for review</a> rather than
          left implicit.</p>
          <h2>The high-ROI filter</h2>
          <p>Fair value is the mid, pulled toward 0.50 in proportion to the spread —
          a wide book means the mid is unreliable. Edge is fair value minus the price
          actually paid to cross the spread. Net ROI divides edge after fees by that
          price. A market is shortlisted only when net ROI clears the strategy's
          threshold and the spread is tight. This is a screen, not a forecast; the
          performance table shows realised results including every loss.</p>
          <h2>Settlement</h2>
          <p>Positions settle from the market's official <code>result</code> field.
          On a <b>Yes</b> outcome, Yes contract holders receive $1.00 per contract;
          on a <b>No</b> outcome, No contract holders receive $1.00 per contract —
          the losing side pays nothing. Only net positions are settled. Source:
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
            f"<td><a href=\"{safe_url(pos.get('market_url','')) or '#'}\" target=\"_blank\" "
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


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def main() -> dict[str, Any]:
    live = load_json(LIVE_PATH, {})
    resolutions_store = load_json(RESOLUTIONS_PATH, {"resolutions": {}})
    series_cache = load_json(SERIES_CACHE_PATH, {})
    portfolio_state = load_json(PORTFOLIO_STATE_PATH, {})
    written = []

    # Fold in the candlestick-close swing feed so the all-events chat reports
    # the moves the exchange published even when no live midpoint crossed the
    # threshold. Modelled in site_build/swingfeed.py; the model chat is not
    # given these rows, and the stats say what was dropped and why.
    swingfeed.attach(live, load_json(DOCS_ALERTS_PATH, {}))

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

    # Resolutions, grouped by topic. The market objects returned by
    # GET /markets carry no series_ticker, so the collector's own per-topic
    # buckets stay empty; the series ticker is recovered from the market
    # ticker prefix, which is Kalshi's documented naming convention.
    series_map = extras.series_topic_map(series_cache)
    resolved_by_topic: dict[str, list[dict[str, Any]]] = {
        slug: [] for slug in TOPIC_ORDER}
    for rec in (resolutions_store.get("resolutions") or {}).values():
        slug = extras.resolution_topic(rec, series_map)
        if slug in resolved_by_topic:
            resolved_by_topic[slug].append(rec)
    for slug in resolved_by_topic:
        resolved_by_topic[slug].sort(
            key=lambda r: r.get("settlement_ts") or "", reverse=True)

    overview = build_overview(live)
    write("index.html", page("Kalshi Monitor — Overview", "index.html", overview,
                             description="Live Kalshi demo market monitor across gas "
                                         "prices, elections, culture, crypto and golf."))

    for slug in TOPIC_ORDER:
        write(f"categories/{slug}.html",
              page(f"{slug.replace('-', ' ').title()} — Kalshi Monitor",
                   f"categories/{slug}.html",
                   build_topic(slug, live, resolved_by_topic.get(slug, [])),
                   prefix="../"))

    write("live.html", page("Live desk — Kalshi Monitor", "live.html",
                            build_live(live)))

    write("resolutions.html",
          page("Resolved events — Kalshi Monitor", "resolutions.html",
               extras.build_resolutions(live, resolutions_store, series_map),
               description="Every tracked Kalshi demo market that has settled, "
                           "with the official YES or NO result."))

    write("trades.html",
          page("Trades and strategies — Kalshi Monitor", "trades.html",
               extras.build_trades(live, portfolio_state),
               description="Simulated Kalshi demo trade ledger, strategy "
                           "breakdown and equity curve."))

    write("suggestions.html",
          page("Suggestions — Kalshi Monitor", "suggestions.html",
               extras.build_suggestions(live),
               description="Prioritised ways to make the Kalshi monitor more "
                           "live and interactive."))

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
    return {"written": written, "generated_at": live.get("generated_at"),
            "resolutions_by_topic": {k: len(v) for k, v in resolved_by_topic.items()}}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
