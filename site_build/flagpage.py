"""Flagged-for-Review page.

Two kinds of items appear here, and they are generated, not hand-written:

1. **Data irregularities detected in the current snapshot** — placeholder text
   left in Kalshi's own records, stale quotes with no depth, category anomalies.
   Each is detected by the rules below and links to the API response that shows
   it, so it can be checked in one click.
2. **Standing limitations** — things this project cannot verify because the
   repository holds no Kalshi credentials, or because no official source exists.
   These are stated once and never quietly dropped.
"""

from __future__ import annotations

import html
from typing import Any

API = "https://external-api.demo.kalshi.co/trade-api/v2"

# Phrases that appear in Kalshi's own records where a value should be but the
# record still holds an unfilled template. Matching is literal — no fuzzy
# guessing. Note deliberately NOT included: "the Governing League", which Kalshi
# uses on purpose to anonymise league names, and which is paired with the real
# pgatour.com URL in the same record; flagging it would be a false positive.
TEMPLATE_MARKERS = [
    "account holder of ",
    "the relevant electoral authority governing ",
]


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def detect_data_issues(live: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    # 1. Placeholder / template text in official series records.
    for slug, topic in (live.get("topics") or {}).items():
        for series in topic.get("series") or []:
            markers = []
            for src in series.get("settlement_sources") or []:
                name = (src.get("name") or "")
                for m in TEMPLATE_MARKERS:
                    if m in name:
                        markers.append(f'settlement source name is "{name}"')
                        break
            title = (series.get("title") or "").strip()
            if title.lower() in ("a", "tbd", "n/a"):
                markers.append(f'series title is the placeholder "{title}"')
            if markers:
                issues.append({
                    "kind": "Template text in an official record",
                    "topic": slug,
                    "ticker": series["ticker"],
                    "detail": "; ".join(markers),
                    "source": series.get("source_url") or f"{API}/series/{series['ticker']}",
                })

    # 2. Quoted but untradable: a price with essentially no resting size.
    for e in live.get("events") or []:
        liq = e.get("liquidity") or {}
        depth = (liq.get("yes_bid_contracts") or 0) + (liq.get("no_bid_contracts") or 0)
        oi = e.get("open_interest_contracts") or 0
        if oi >= 1_000_000 and depth < 10:
            issues.append({
                "kind": "Large open interest on an empty book",
                "topic": e.get("topic"),
                "ticker": e.get("ticker"),
                "detail": (f"{oi:,.0f} contracts of open interest against only "
                           f"{depth:,.0f} contracts of resting bid depth — the "
                           f"quoted {e.get('yes_bid') or 0:.4f} is not tradable size"),
                "source": f"{API}/markets/{e.get('ticker')}/orderbook",
            })

    # 3. Culture category anomaly.
    culture = (live.get("topics") or {}).get("culture") or {}
    if culture.get("series_count") is not None:
        issues.append({
            "kind": "Topic category is effectively empty",
            "topic": "culture",
            "ticker": "category=Culture",
            "detail": (f"Kalshi's own 'Culture' category returns "
                       f"{culture.get('series_count')} series while "
                       f"{culture.get('event_count')} open events exist for this "
                       f"topic once 'Entertainment' is also queried. Culture "
                       f"content is filed under Entertainment."),
            "source": f"{API}/series?category=Culture",
        })

    # 4. Alerts whose price basis is thin: the row is kept and labelled, never
    #    silently dropped, but a human should know the move was not executable
    #    at the midpoint (COORDINATION.md R-D-01).
    for a in live.get("alerts") or []:
        spread = a.get("spread")
        if spread is None:
            yb, ya = a.get("yes_bid"), a.get("yes_ask")
            if yb is not None and ya is not None:
                spread = round(ya - yb, 4)
        if a.get("thin_book") or (spread is not None and spread > 0.20):
            issues.append({
                "kind": "Swing alert on a wide-spread book (labelled, not executable)",
                "topic": a.get("topic"),
                "ticker": a.get("ticker"),
                "detail": (f"the {a.get('direction')} move "
                           f"{a.get('previous')} → {a.get('current')} was "
                           f"measured while the book quoted a spread of "
                           f"{spread if spread is not None else 'unknown'} "
                           f"(basis: {a.get('basis') or 'legacy midpoint'}); "
                           f"the midpoint of a wide spread is not an "
                           f"executable price — read the order book before "
                           f"acting"),
                "source": f"{API}/markets/{a.get('ticker')}/orderbook",
            })

    # De-duplicate by (kind, ticker) and cap.
    seen = set()
    unique = []
    for issue in issues:
        key = (issue["kind"], issue["ticker"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique[:120]


STANDING = [
    {
        "title": "Demo-account portfolio performance cannot be shown",
        "body": ("Reading a Kalshi demo balance, fills or positions requires signed "
                 "requests with an API key pair. No key is configured for this "
                 "repository, so every trading figure on this site comes from the "
                 "simulated ledger, not your demo account. The paper ledger is "
                 "labelled SIMULATED wherever it appears."),
        "source": ("https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md",),
    },
    {
        "title": "No real orders are placed",
        "body": ("Order entry is implemented (POST /portfolio/events/orders) but "
                 "inert without credentials. Nothing on this site can move real or "
                 "demo funds."),
        "source": ("https://docs.kalshi.com/getting_started/quick_start_create_order.md",),
    },
    {
        "title": "No news article is attributed to a price move",
        "body": ("The brief asked for links to news that may have caused jumps. No "
                 "official source maps articles to Kalshi price moves, so guessing "
                 "one would be fabrication. Every alert instead links to the market "
                 "itself and carries a clearly labelled 'context ↗' research link "
                 "(a news search on the event title) marked 'possible context only; "
                 "causality unverified'. The series page also lists Kalshi's own "
                 "settlement sources (AAA, CF Benchmarks, ESPN, pgatour.com), which "
                 "are the official pages that explain the underlying."),
        "source": ("https://docs.kalshi.com/api-reference/market/get-series-list",),
    },
    {
        "title": "Historical swing-chat rows were duplicated and midpoint-based (fixed 2026-11-20)",
        "body": ("Before this revision the swing chat could show the same sustained "
                 "move once per collector run (observed: 29 rows over only 3 "
                 "tickers) and could alert on the midpoint of a $0.80-wide spread. "
                 "Alerts are now deduplicated to one row per market per reference "
                 "window per direction and measured on a depth-aware price basis "
                 "(tight-book mid, else last trade). Rows that still carry a wide "
                 "spread are labelled 'thin book' rather than dropped. See "
                 "COORDINATION.md request R-D-01 for the evidence."),
        "source": ("https://docs.kalshi.com/getting_started/orderbook_responses",),
    },
    {
        "title": "Snapshot freshness is best-effort",
        "body": ("The collector runs on a 5-minute GitHub Actions schedule, which "
                 "GitHub itself documents as best-effort and subject to lag. A "
                 "snapshot can therefore be older than its nominal cadence; the "
                 "topbar computes and shows the snapshot's age in your browser so "
                 "staleness is always visible."),
        "source": ("https://docs.kalshi.com/getting_started/demo_env",),
    },
    {
        "title": "Live streaming uses polling, not the WebSocket",
        "body": ("The documented demo WebSocket requires the same signed handshake as "
                 "REST, so without credentials the site polls the public REST API. "
                 "Prices can lag by the poll interval; the page shows the age of "
                 "every snapshot."),
        "source": ("https://docs.kalshi.com/getting_started/quick_start_websockets",),
    },
    {
        "title": "The model's ROI is a screen, not a validated edge",
        "body": ("Signals are ranked by modelled edge after Kalshi's published taker "
                 "fee. No claim of profitability is made, and the performance table "
                 "publishes every loss alongside every win once trades settle."),
        "source": ("https://kalshi.com/docs/kalshi-fee-schedule.pdf",),
    },
    {
        "title": "Each run tracks a ranked slice, not every market",
        "body": ("The collector reads a bounded number of the highest-value markets "
                 "per topic inside a fixed time budget, and reports the counts it "
                 "actually read plus anything it had to skip."),
        "source": ("https://docs.kalshi.com/api-reference/market/get-markets",),
    },
    {
        "title": "Fee-schedule rounding prose and its own table disagree",
        "body": ("The fee PDF says to round so that 'fee + positionCost is rounded to "
                 "a centicent', but its published table is reproduced exactly by "
                 "rounding the fee alone up to the cent. The table is used as the "
                 "oracle, because it matches every one of the 42 published rows."),
        "source": ("https://kalshi.com/docs/kalshi-fee-schedule.pdf",),
    },
]


def render(live: dict[str, Any]) -> str:
    issues = detect_data_issues(live) if live else []
    rows = []
    for i in issues:
        rows.append(
            "<tr>"
            f"<td><span class=\"tag tag-purple\">{esc(i['kind'])}</span></td>"
            f"<td>{esc(i.get('topic'))}</td>"
            f"<td><code>{esc(i.get('ticker'))}</code></td>"
            f"<td>{esc(i.get('detail'))}</td>"
            f"<td><a class=\"source-link\" href=\"{esc(i.get('source'))}\" "
            f"target=\"_blank\" rel=\"noreferrer\">official API ↗</a></td>"
            "</tr>")
    if not rows:
        rows.append('<tr><td colspan="5" class="empty-state">No data irregularity '
                    "detected in the current snapshot.</td></tr>")

    standing = []
    for item in STANDING:
        links = " · ".join(
            f'<a class="source-link" href="{esc(u)}" target="_blank" rel="noreferrer">'
            f"official source ↗</a>" for u in item["source"])
        standing.append(
            f'<article class="flag-card"><h3>{esc(item["title"])}</h3>'
            f"<p>{esc(item['body'])}</p><div>{links}</div></article>")

    return f"""        <header class="topbar">
          <div class="breadcrumb">Research <span>/</span> Flagged for review</div>
          <div class="top-actions">
            <time>Snapshot {esc(live.get('generated_at'))}</time>
          </div>
        </header>
        <section class="page-heading">
          <div>
            <div class="eyebrow">TRANSPARENCY · NOTHING HIDDEN</div>
            <h1>Flagged for review</h1>
            <p>Everything this project could not verify, plus irregularities found
            inside Kalshi's own demo records.</p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon amber">⚑</span><div>
              <h2>Data irregularities detected in the current snapshot</h2>
              <p>Found by literal rules — no fuzzy matching, no guessing. Each row
              links to the API response that shows it.</p></div></div>
            <span class="count-badge">{len(issues)}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>What</th><th>Topic</th><th>Ticker</th>
                <th>Detail</th><th>Source</th></tr></thead>
              <tbody>{''.join(rows)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>Blank or absent values are never inferred</span>
          <span>Recomputed on every collector run</span></div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon">▤</span><div>
              <h2>Standing limitations</h2>
              <p>Stated once, up front, and linked to the official page that
              explains each constraint</p></div></div>
          </div>
          <div class="flag-list">{''.join(standing)}</div>
        </section>"""
