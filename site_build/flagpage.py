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
from collections import Counter
from typing import Any

from collector.alerts import QUOTE_BASES

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

    # 3. Culture is a dashboard topic spanning two separate Kalshi categories.
    # Do not substitute the combined topic count for the category=Culture result.
    culture = (live.get("topics") or {}).get("culture") or {}
    if culture.get("series_count") is not None:
        issues.append({
            "kind": "Culture topic combines categories",
            "topic": "culture",
            "ticker": "Culture + Entertainment",
            "detail": ("The dashboard's Culture topic includes series from both "
                       "Kalshi categories, Culture and Entertainment. Its "
                       "topic-level totals are combined and are not the result "
                       "of the Culture-only query. Review both official series "
                       "queries separately."),
            "sources": [
                {"label": "Culture series API", "url": f"{API}/series?category=Culture"},
                {"label": "Entertainment series API", "url": f"{API}/series?category=Entertainment"},
            ],
        })

    # 4. Repeated midpoint alerts are not evidence of executable fills. Publish
    # a review item whenever the current snapshot repeats a ticker so traders
    # can inspect the official current book before acting.
    alert_rows = live.get("alerts") or []
    alert_counts = Counter(a.get("ticker") for a in alert_rows if a.get("ticker"))
    unverified_basis_count = sum(
        a.get("reference_basis") not in QUOTE_BASES for a in alert_rows)
    repeated_alerts = sorted(
        ((ticker, n) for ticker, n in alert_counts.items() if n > 1),
        key=lambda item: (-item[1], item[0]),
    )
    if repeated_alerts:
        sources = [
            {"label": f"{ticker} order book", "url": f"{API}/markets/{ticker}/orderbook"}
            for ticker, _ in repeated_alerts[:5]
        ]
        sources.append({
            "label": "Orderbook format and bid/ask explanation",
            "url": "https://docs.kalshi.com/getting_started/orderbook_responses",
        })
        repeated_summary = "; ".join(
            f"{ticker} ({n} alerts)" for ticker, n in repeated_alerts[:5])
        topics = sorted({a.get("topic") for a in alert_rows if a.get("topic")})
        unique_word = "ticker" if len(alert_counts) == 1 else "tickers"
        repeat_word = "ticker" if len(repeated_alerts) == 1 else "tickers"
        issues.append({
            "kind": "Repeated midpoint alerts — review before trading",
            "topic": ", ".join(topics) or "unverified",
            "ticker": repeated_summary,
            "detail": (f"The current snapshot has {len(alert_rows)} alert rows across "
                       f"{len(alert_counts)} distinct {unique_word}, with repeated rows "
                       f"for {len(repeated_alerts)} {repeat_word}. "
                       f"{unverified_basis_count} stored row(s) lack a recognized "
                       f"quote reference basis, so their original price comparison "
                       f"cannot be verified. Alerts are detections, not executed "
                       f"fills; the collector drops rows without a verifiable basis "
                       f"on its next run. Check current bid/ask prices, resting "
                       f"contracts, and snapshot time before treating a swing as "
                       f"actionable."),
            "sources": sources,
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
        "title": "Swing alerts compared a trade price with a quote midpoint (fixed on branch arena/856e184e-trade2)",
        "body": ("Until this fix, a >= $0.10 alert compared the candle's last-trade close with the "
                 "midpoint of the current bid and ask. On KXPRESNOMD-28-HBID the last trade and the ask were "
                 "0.8110 while the bid was 0.0020, so the midpoint 0.4065 produced a 'swing' of -$0.4045 that no "
                 "trade made. Alerts now compare quote mid with quote mid, require a two-sided quote narrower "
                 "than $0.10, and drop stored alerts that fail that rule on the next run. The same rule removes "
                 "trade prints the quotes do not support: KXPRESNOMD-28-AKLO printed 0.8030 in the hour before its "
                 "alert while its bid and ask stayed at 0.0020 and 0.0030. The $0.10 narrow-spread rule is a design "
                 "choice of this project, not a Kalshi rule."),
        "source": (
            "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
            "https://docs.kalshi.com/api-reference/market/get-market.md",
            "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID",
            "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID/orderbook",
        ),
    },
    {
        "title": "The kalshi-dashboard snapshot was collected from the production host",
        "body": ("This project is scoped to the Kalshi demo endpoint. The kalshi-dashboard collector "
                 "(scripts/collect.mjs) defaulted to the production host external-api.kalshi.com. The default is "
                 "now the demo host. Until the next scheduled run, the published status file still records the "
                 "production base_url. The workflow step label still says 'production by default' (request "
                 "logged on the coordination board)."),
        "source": (
            "https://docs.kalshi.com/getting_started/api_environments.md",
            "https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/data/status.json",
        ),
    },
    {
        "title": "'OI value' is a notional figure, not dollars traded",
        "body": ("The overview ranks markets by open_interest_fp x notional_value_dollars. Kalshi defines "
                 "open interest as the number of contracts bought on the market (disregarding netting) and "
                 "notional value as the value of one contract at settlement ($1.00). The product is the "
                 "settlement value of open contracts. It is not dollars traded and not dollars currently at "
                 "risk. The site labels it that way. Ranking by it is one reading of 'highest dollar amount'."),
        "source": ("https://docs.kalshi.com/api-reference/market/get-market.md",),
    },
    {
        "title": "Trade-price alerts in two other pipelines are not checked against quotes (open)",
        "body": ("The docs/ pipeline (collector/runner.py) and the kalshi-dashboard pipeline alert on "
                 "consecutive trade-price closes, so the quote rule above does not cover them. The docs/ alerts "
                 "currently list hourly trade-price moves such as KXRT-FUR-85 0.43 to 0.05. Those moves have not "
                 "been checked against the quotes and are not changed by this branch."),
        "source": (
            "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
            "https://wingbangboozle1-lang.github.io/Trade2/docs/data/alerts.json",
        ),
    },
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
        "title": "Swing alerts are detections, not executed fills",
        "body": ("The root collector compares quote midpoints from two-sided books, "
                 "using the candle-opening quote or the previous snapshot as its "
                 "reference, and rejects books with a spread of $0.10 or more. "
                 "Stored rows without a recognized reference_basis are dropped on "
                 "the next collector run. The live desk groups repeated rows for "
                 "display and marks wide-spread rows as not executable, but no alert "
                 "or display badge records an order or fill. Inspect the current "
                 "official order book and snapshot time before acting."),
        "source": (
            "https://docs.kalshi.com/getting_started/orderbook_responses",
            "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
        ),
    },
    {
        "title": "No news article is attributed to a price move",
        "body": ("The brief asked for links to news that may have caused jumps. No "
                 "official source maps an article to a Kalshi price move, so the "
                 "dashboard never asserts one. Every ≥ $0.10 row instead links to "
                 "the Kalshi event page — which carries Kalshi's own live news feed "
                 "for that event, with its sources — and to a news search built "
                 "from the event title. Those are places to look, not claims of "
                 "cause."),
        "source": ("https://docs.kalshi.com/api-reference/events/get-events",),
    },
    {
        "title": "A book with no resting size is shown as UNVERIFIED, not as $0.0000",
        "body": ("For markets with no size on either side Kalshi reports "
                 "yes_bid_dollars 0.0000 and yes_ask_dollars 1.0000. A full 0-to-1 "
                 "book is not a price — averaging it produces a phantom $0.50 "
                 "midpoint — so the collector treats it as no quote at all and the "
                 "site leaves those cells blank and flagged rather than printing a "
                 "price that cannot be filled. Check the linked market response to "
                 "see the raw values."),
        "source": ("https://docs.kalshi.com/getting_started/orderbook_responses",),
    },
    {
        "title": "Topic grouping of resolved markets uses the ticker prefix",
        "body": ("GET /markets returns market objects with no series_ticker field, "
                 "so a settled market cannot be filed under a topic from that "
                 "response alone. The series ticker is recovered from the market "
                 "ticker prefix, which is Kalshi's own naming convention, and the "
                 "API value is preferred whenever it is present. Settled markets "
                 "outside the five tracked topics are counted separately rather "
                 "than dropped without trace."),
        "source": ("https://docs.kalshi.com/api-reference/market/get-markets",),
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
    from .extras import age_label
    age = age_label(live.get("generated_at"), live.get("generated_at_ts"))
    rows = []
    for i in issues:
        sources = i.get("sources") or [{"label": "official API", "url": i.get("source")}]
        source_links = " · ".join(
            f'<a class="source-link" href="{esc(source.get("url"))}" '
            f'target="_blank" rel="noreferrer">{esc(source.get("label") or "official API")} ↗</a>'
            for source in sources)
        rows.append(
            "<tr>"
            f"<td><span class=\"tag tag-purple\">{esc(i['kind'])}</span></td>"
            f"<td>{esc(i.get('topic'))}</td>"
            f"<td><code>{esc(i.get('ticker'))}</code></td>"
            f"<td>{esc(i.get('detail'))}</td>"
            f"<td>{source_links}</td>"
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
            <span class="live-pill" id="livePill"><i></i> SNAPSHOT</span>
            <time id="updatedAt">Snapshot {esc(live.get('generated_at'))}</time>
            <span class="snap-age" id="snapshotAge" data-generated-ts="{esc(live.get('generated_at_ts'))}">{esc(age)}</span>
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
