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

    # 4. A published value that the automated re-check could not confirm.
    for row in ((live.get("verification") or {}).get("mismatches") or []):
        issues.append({
            "kind": "Published value disagrees with the official API",
            "topic": None,
            "ticker": row.get("field"),
            "detail": (f"the re-check read {row.get('official')!r} from the official "
                       f"response while the site publishes {row.get('published')!r}"
                       + (f" — {row.get('detail')}" if row.get("detail") else "")),
            "source": row.get("url"),
        })

    # 5. A published swing that the order book does not confirm.
    # The Kalshi demo feed prints alternating trades on some markets while the
    # quoted book stays flat. A price move the book did not make is a trade
    # print, not a change in the market, so it is flagged here rather than
    # presented as a swing. The model's verdict for each alert says the same
    # thing on the live desk.
    for verdict in ((live.get("shortlist") or {}).get("verdicts") or []):
        if verdict.get("verdict") == "picked":
            continue
        reason = verdict.get("reason") or ""
        if "book has not moved" not in reason:
            continue
        ticker = verdict.get("ticker")
        issues.append({
            "kind": "Swing not confirmed by the order book",
            "topic": verdict.get("topic"),
            "ticker": ticker,
            "detail": ("the alert stream reports a >= $0.10 move for this market, "
                       "but the quoted book did not move between the last two "
                       "snapshots — the demo feed printed an alternating trade. "
                       "The model passes on it and the row is labelled as an "
                       "unconfirmed print."),
            "source": f"{API}/markets/{ticker}/orderbook",
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
        "title": "Moves the alert rule refuses are listed below, not hidden",
        "body": ("A midpoint move of $0.10 or more on a one-sided or wide book does not "
                 "become an alert, because no trade made it: on KXPRESNOMD-28-HBID the "
                 "bid and ask were 0.0020 and 0.8110, so the mid could print 0.4065 "
                 "while nothing traded. Those refusals are now counted and the individual "
                 "ones are published in the 'Refused midpoint moves' table with the reason, "
                 "so a reviewer can disagree with the rule using the same numbers."),
        "source": ("https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID",
                   "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID/orderbook"),
    },
    {
        "title": "The model shortlist and the generator now share one gate",
        "body": ("The page filtered the shortlist on net ROI >= 0.05 while the collector "
                 "published it on model score >= 0.10, so the same feed had two "
                 "definitions and the overview chat looked emptier than the data. Both "
                 "sides now read one constant, alerts.model.MODEL_MIN_NET_ROI = 0.05, "
                 "and the browser renders the published list rather than re-deriving "
                 "it. Rows marked indicative are excluded from the shortlist on purpose: "
                 "a shortlist is something a trader would act on."),
        "source": ("https://wingbangboozle1-lang.github.io/Trade2/methodology.html",
                   "https://docs.kalshi.com/getting_started/orderbook_responses"),
    },
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
                 "official order book and snapshot time before acting. The engine "
                 "rule behind that wording, in full: one row per market, direction and "
                 "reference bar; a repeat inside the same bar updates that row and "
                 "counts itself in 'N sightings'; a later bar only opens a new row "
                 "when the move has grown by a further $0.10; a reversal is always a "
                 "new row; and a midpoint move the quote rule refuses is published in "
                 "the refusal table below rather than dropped. The $0.10 narrow-spread "
                 "rule and the folding rule are this project's design choices, not "
                 "Kalshi rules — nothing here is Kalshi's fault."),
        "source": (
            "https://docs.kalshi.com/getting_started/orderbook_responses",
            "https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md",
            "https://wingbangboozle1-lang.github.io/Trade2/data/alerts.json",
        ),    },
    {
        "title": "News links are candidate catalysts, never confirmed causes",
        "body": ("The brief asked for links to news that may have caused a jump. No "
                 "official source maps an article to a Kalshi price move, so "
                 "causality is never asserted. Two mechanisms are published instead: "
                 "every ≥ $0.10 row links to the Kalshi event page — which carries "
                 "Kalshi's own live news feed for that event, with its sources — and "
                 "to a news search built from the event title; and the collector "
                 "attaches up to six RSS headlines published within ± six hours of "
                 "the alert, printed under the row as 'candidate headline, not "
                 "confirmed'. A row with no result says so with the reason instead of "
                 "a plausible guess, and settlement sources (AAA, CF Benchmarks, "
                 "ESPN, pgatour.com) remain the only officially named references. "
                 "Headline lookup needs outbound network access, so on a run without "
                 "it every row shows the reason it is empty rather than a link."),
        "source": ("https://docs.kalshi.com/api-reference/events/get-events",
                   "https://docs.kalshi.com/api-reference/market/get-series-list",
                   "https://news.google.com/rss/search"),
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
        "source": ("https://docs.kalshi.com/api-reference/market/get-markets",)
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

        "title": "The demo feed prints alternating trades on some markets",
        "body": ("On several demo markets the traded price oscillates between two "
                 "levels every minute while the quoted order book never changes. "
                 "For example the one-minute candles for KXPRESNOMD-28-AKLO "
                 "alternate between $0.8030 and $0.0030 while the book stays at "
                 "$0.0020 x $0.0030 for the whole window. A move the book did not "
                 "make is a trade print rather than a market move, so the model "
                 "rejects it and it is listed on this page."),
        "source": ("https://external-api.demo.kalshi.co/trade-api/v2/series/"
                   "KXPRESNOMD/markets/KXPRESNOMD-28-AKLO/candlesticks",),
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
        "title": "Taker fees use a multiplier of 1 for every series",
        "body": ("Kalshi's quadratic taker fee is round-up(M x 0.07 x C x P x (1-P)), "
                 "and the published schedule sets M per series — 0 for fee-free "
                 "series such as the yearly Bitcoin and Ether ranges, 2 for "
                 "uncorrelated combos. The simulated ledger applies M = 1 everywhere "
                 "instead of reading each series' own value "
                 "(collector/engine.py calls kalshi_fee(price, contracts) with the "
                 "default multiplier at both the entry and the exit site, although "
                 "collector/topics.py already caches fee_multiplier per series). This "
                 "was checked against the live demo record for KXBTCY on 2026-11-20, "
                 "which returns fee_multiplier 1, so the fee shown for the open "
                 "position on that series is correct for the demo environment — the "
                 "exposure is to series whose demo multiplier is not 1, and to "
                 "production, where the same series is listed at 0. Fees on those "
                 "rows would be mis-stated until the engine threads the value "
                 "through."),
        "source": ("https://kalshi.com/docs/kalshi-fee-schedule.pdf",
                   "https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY"),
    },
    {
        "title": "Each run tracks a ranked slice, not every market",
        "body": ("The collector reads a bounded number of the highest-value markets "
                 "per topic inside a fixed time budget, and reports the counts it "
                 "actually read plus anything it had to skip."),
        "source": ("https://docs.kalshi.com/api-reference/market/get-markets",),
    },
    {
        "title": "Three scheduled workflows collect the same data, and the most "
                 "frequent one rarely runs",
        "body": ("Verified from the repository and the Actions API, not inferred. "
                 "Three workflows collect from the demo API and commit to `main`: "
                 "`kalshi-dashboard.yml` (cron `*/5`), `collector.yml` (`*/15`) and "
                 "`dashboard.yml` (`*/30`). The `*/5` one groups its runs under "
                 "`concurrency: collect` with `cancel-in-progress: false`, and on a "
                 "repository this busy a run in that group spends longer than five "
                 "minutes than not — so new runs replace queued ones instead of "
                 "waiting. Two runs of it on 2026-11-20 ended `cancelled` after 17 s "
                 "and 43 s (runs 44804717748 and 44804612803), while the `collector` "
                 "workflow triggered by the same merge completed in 19 s. Consequence "
                 "for a trader: the published snapshot's age is what the top bar shows, "
                 "not five minutes. Reading of the queueing behaviour above is this "
                 "project's interpretation of the workflow configuration and the two "
                 "cancelled runs, not a confirmed GitHub guarantee — see the "
                 "concurrency documentation for the rule."),
        "source": ("https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44804717748",
                   "https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44804612803",
                   "https://github.com/wingbangboozle1-lang/Trade2/blob/main/.github/workflows/kalshi-dashboard.yml"),
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

    refused = []
    for rec in (live or {}).get("suppressed_alerts", []) or []:
        refused.append(
            "<tr>"
            f"<td><code>{esc(rec.get('ticker'))}</code>"
            f"<small>{esc(rec.get('title'))}</small></td>"
            f"<td>{esc(rec.get('topic'))}</td>"
            f"<td>{esc(rec.get('direction'))}</td>"
            f"<td>{('$' + format(float(rec['abs_delta']), '.4f')) if rec.get('abs_delta') is not None else '—'}</td>"
            f"<td>{esc(rec.get('yes_bid'))} / {esc(rec.get('yes_ask'))}</td>"
            f"<td>{esc(rec.get('reason'))}</td>"
            f"<td>{esc(rec.get('iso'))}</td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{esc((live or {}).get("api_root") or "https://external-api.demo.kalshi.co/trade-api/v2")}'
            f'/markets/{esc(rec.get("ticker"))}">API ↗</a></td>'
            "</tr>")
    if not refused:
        refused.append('<tr><td colspan="8" class="empty-state">No midpoint move was '
                       "refused by the quote rule in the last collector run, or the "
                       "snapshot predates that reporting.</td></tr>")
    gaps = (live or {}).get("book_record_gaps") or []
    gap_rows = []
    for g in gaps:
        gap_rows.append(
            "<tr>"
            f"<td><code>{esc(g.get('ticker'))}</code>"
            f"<small>{esc(g.get('title'))}</small></td>"
            f"<td>{esc(g.get('topic'))}</td>"
            f"<td>{esc(g.get('book_yes_bid'))} / {esc(g.get('book_yes_ask'))}</td>"
            f"<td>{esc(g.get('book_mid'))}</td>"
            f"<td>{esc(g.get('record_yes_bid'))} / {esc(g.get('record_yes_ask'))}</td>"
            f"<td>{esc(g.get('record_mid'))}</td>"
            f"<td><b>{esc(g.get('gap'))}</b></td>"
            f'<td><a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{esc(g.get("source_book"))}">book ↗</a> '
            f'<a class="source-link" target="_blank" rel="noreferrer" '
            f'href="{esc(g.get("source_record"))}">record ↗</a></td>'
            "</tr>")
    if not gap_rows:
        gap_rows.append('<tr><td colspan="8" class="empty-state">No tracked market '
                        "shows a ≥ $0.10 disagreement between the order-book "
                        "response and the market record in this snapshot.</td></tr>")
    gap_count = (live or {}).get("book_record_gap_count")
    gap_note = (f"{gap_count} of the tracked markets show such a gap"
                if gap_count is not None else "coverage depends on how many books "
                "the run had budget to fetch")
    alert_stats = (live or {}).get("alert_stats") or {}
    refused_note = (
        f"{alert_stats.get('suppressed_this_run', '—')} refused this run · "
        f"{alert_stats.get('folded_duplicates', '—')} repeat sightings folded · "
        f"{alert_stats.get('buffer', '—')} buffered rows · "
        f"{alert_stats.get('distinct_moves', '—')} distinct moves"
        if alert_stats else "no alert statistics in this snapshot yet")

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
            <div><span class="section-icon amber">⊘</span><div>
              <h2 id="refused">Refused midpoint moves (audit the rule, not the data)</h2>
              <p>Moves of $0.10 or more that did <b>not</b> become alerts, with the
              reason. {esc(refused_note)}</p></div></div>
            <a class="source-link" target="_blank" rel="noreferrer"
               href="https://docs.kalshi.com/getting_started/orderbook_responses">Book
               semantics ↗</a>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Topic</th><th>Direction</th>
                <th>Midpoint move</th><th>YES bid / ask</th><th>Why it was refused</th>
                <th>Seen at</th><th>Source</th></tr></thead>
              <tbody>{''.join(refused)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>Recomputed on every collector run</span>
          <span>A refusal is a judgement by this project's rule, not by Kalshi</span></div>
        </section>
        <section class="panel">
          <div class="panel-title">
            <div><span class="section-icon amber">≠</span><div>
              <h2 id="book-vs-record">Kalshi's order book and its market record disagree</h2>
              <p>Same market, same moment, two official endpoints, both linked.
              {esc(gap_note)} The chart and the swing rule read the <em>book</em>;
              the market record carries its own summary quote. Neither is
              discarded — the gap is published so nobody has to trust which one
              the dashboard picked.</p></div></div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Market</th><th>Topic</th><th>Book YES bid / ask</th>
                <th>Book mid</th><th>Record YES bid / ask</th><th>Record mid</th>
                <th>Gap</th><th>Sources</th></tr></thead>
              <tbody>{''.join(gap_rows)}</tbody>
            </table>
          </div>
          <div class="table-foot"><span>Threshold: the same $0.10 as the alert rule</span>
          <span>A gap is Kalshi demo data, not a calculation by this project</span></div>
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
