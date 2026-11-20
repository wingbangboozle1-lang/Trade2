# Independent review — session `arena/cbb7cbec-trade2`

Date: 2026-11-20. Branch: `arena/cbb7cbec-trade2`, based on `main` @ `1bc32b7`
and merged up to `main` @ `a19c467` (PRs #1–#20).

This is a *targeted* review, not a re-audit of every file. It covers the four
things a trader actually reads on the page — the alert feed, the model feed, the
resolution table and the "highest dollar" ranking — plus the claims those
sections make. Every finding below was reproduced from an **official** source
fetched during the session, and each one names the exact URL.

**How the checks were run.** This sandbox cannot open TCP connections to Kalshi
hosts (`curl` returns HTTP 000). All live Kalshi values below were therefore
fetched through the platform's page fetcher, against the same official demo
host, and the raw JSON is quoted verbatim. Repository-level checks were run
locally: `python3 -m unittest discover -s tests`, `npm test`,
`python3 -m collector.test_runner`, `python3 -m trading.test_engine`,
`node test/site_smoke.mjs`, `node tools/rendercheck.mjs`, `python3 tools/linkcheck.py`.

---

## 1. What was wrong, and the line of code that caused it

### P1 — Phantom ≥ $0.10 alerts (High)

**Symptom.** The "All events" chat published 29 rows, all in the *elections*
topic. The most visible was:

| Market | previous | current | delta |
| - | - | - | - |
| `KXPRESNOMD-28-HBID` (Hunter Biden) | 0.811 | 0.4065 | −0.4045 |

**Cause.** Two *different quantities* were subtracted:

* the reference was the candle's `price.close_dollars` — the **last traded
  price**;
* the current value was the **midpoint of the order book**.

**Official evidence (fetched 2026-11-20T19:04Z).**

* `GET https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID`
  → `yes_bid_dollars "0.0020"`, `yes_ask_dollars "0.8110"`,
  `last_price_dollars "0.8110"`.
* `GET …/markets/KXPRESNOMD-28-HBID/orderbook?depth=5`
  → `yes_dollars [["0.0010","166666.66"],["0.0020","83333.33"]]`,
  `no_dollars […["0.1890","271.49"]]`.
  By the documented reciprocal (<https://docs.kalshi.com/getting_started/orderbook_responses>)
  best YES bid = 0.0020 and implied YES ask = 1 − 0.1890 = 0.8110, so the mid
  is 0.4065 — arithmetically correct, but a **0.809-wide book**: a price nobody
  can deal on.
* `GET …/series/KXPRESNOMD/markets/KXPRESNOMD-28-HBID/candlesticks?period_interval=1`
  → every one-minute bar in the window shows `price.close_dollars "0.8110"`
  while `yes_bid.close_dollars "0.0020"` and `yes_ask.close_dollars "0.8110"`.
  The "0.811" was never a quote.

The official candlestick schema
(<https://docs.kalshi.com/api-reference/market/get-market-candlesticks>) defines
`price` as *trade* OHLC and `yes_bid` / `yes_ask` as separate bid/ask
distributions — the two are not interchangeable.

**Fix (this branch, merged with session `856e184e`'s independent fix).**

* `collector/alerts.py::observe` only builds a mid when the book has **both**
  bid sides; a market-record quote is kept for display but never priced.
* `detect_swing` requires `swing_quotes_ok(current)` **and** a reference whose
  own spread is strictly below `ALERT_MAX_SPREAD` (0.10).
* The bar reference is now the candle's `yes_bid` / `yes_ask` closes, never
  `price`.
* Stored alerts that fail the rule are purged on the next run
  (`alert_record_valid`).

**Verified after the fix** (offline replay with the payloads above):
the HBID case produces `alertable=False` and `detect_swing(...) is None`.
A genuine 0.41 → 0.52 move on a 0.02-wide book still alerts (test
`test_alert_at_exact_threshold`, `test_tight_two_sided_book_does_alert`).

### P2 — The same move was appended seven times (High)

**Symptom.** `data/live.json` contained 7 rows for `KXPRESNOMD-28-HBID` with
identical `previous` / `current`, two of them with **negative**
`observed_gap_seconds` (−3.8 s), which is impossible for a forward-looking
comparison.

**Cause.** Alert ids were `ticker:<current timestamp second>`, and the run
compared against the same 5-minute bar reference each time. Every 5-minute run
inside a bar produced a "new" id for the *same* move.

**Fix.** Alert id is now `ticker:<bar_start>:<direction>`, so a re-run inside a
bar recomputes the same id and the merge step cannot append a duplicate. The
client additionally groups identical rows that already exist in older snapshots
(`AlertsView.dedupeAlerts`, display-only, added by session `0b2d2a2a`).

### P3 — The "model shortlist" chat was structurally empty (Medium)

**Symptom.** With 29 alerts and one scored signal, the model chat showed
`high_roi_alerts: []`.

**Cause.** The feed was built by intersecting alerts with signals **on the same
ticker**. In the published snapshot the alert tickers and signal tickers had an
empty intersection — a 10-cent move happens on markets whose books are too wide
to score, and the scorer only trades tight books. The intersection can
therefore never be populated in practice.

**Fix.** `collector/alerts.py::model_shortlist()` builds the feed from
(a) every swing whose own book is tradeable and (b) every scored signal above
the net-ROI gate, tagging each row `swing`, `swing+signal` or `signal`. The page
says which is which. A regression test asserts a signal with no alert on its
ticker still reaches the chat.

### P4 — 2,000 settlements stored, 0 published (Medium)

**Symptom.** Every topic page's "Resolved — how each event ended" table was
empty, and the overview reported 0 resolutions, while `data/resolutions.json`
held 2,000 rows with an official `result`.

**Cause.** Resolution rows were attributed to a topic **only** by
`series_ticker`, and every row in the store had `series_ticker: null`.

**Official evidence.** `GET …/markets/KXQUICKSETTLE-20NOV26H1310-3` (fetched
2026-11-20T19:07Z) returns `"series_ticker"` absent and `"result":"no"`,
`"settlement_value_dollars":"0.0000"`, `"status":"finalized"`,
`"settlement_ts":"2026-11-20T18:40:57.114235Z"`.

**Fix.** `alerts.resolution_topic()` attributes a settlement using only official
fields, in this order: the market's `series_ticker` against the topic-scoped
series registry, then the `event_ticker` against events **this run actually
discovered** for a topic. It deliberately does **not** parse ticker strings —
the official glossary says *"do not parse ticker strings to infer
relationships"* (<https://docs.kalshi.com/getting_started/terms#ticker-conventions>).
Rows that match neither are published as *unattributed* on the Flagged page
rather than guessed into a topic. Topic pages now show why a table can be empty
and how many rows are unattributed.

### P5 — An unquotable book could score as a high-ROI signal (Medium)

`score_market` defaulted `spread` to `0.02` when a market had no book, so a
stale 1-cent quote on an empty book scored an "edge". It now returns `None`
when the spread is unknown: no book, no price.

### P5b — The chart plotted trade prints on a quote axis (High)

**Symptom.** Selecting a market drew a line with steps such as 0.002 → 0.811 →
0.002 that no quote ever moved through, and the line disagreed with the alert
feed for the same market.

**Cause.** `assets/desk.js` seeded the series from the candle's
`price.close_dollars` — the **last traded price** — while `pollBook()` appended
*quote mids*. The chart therefore plotted two different quantities on one axis.
`midFromBook()` had a second defect: on a one-sided book it returned the single
side, inventing a "price" for a market that had only a bid.

**Official evidence.** The candlestick schema defines `price` as trade OHLC and
`yes_bid` / `yes_ask` as the quote OHLC
(<https://docs.kalshi.com/api-reference/market/get-market-candlesticks>). For
`KXPRESNOMD-28-HBID` every minute in the fetched window has
`price.close_dollars "0.8110"` with `yes_bid.close_dollars "0.0020"` and
`yes_ask.close_dollars "0.8110"`
(<https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-HBID/candlesticks>).

**Fix.** The chart now seeds from the candle's `yes_bid` / `yes_ask` closes
(`blockClose`, `candleMid`) and `midFromBook` requires **both** sides. A candle
with no two-sided quote, or a crossed quote, contributes no point at all — gaps
stay gaps. `tests/test_desk_chart.mjs` asserts both rules against documented
payload shapes and now runs in the `kalshi-dashboard.yml` workflow.

### P6 — A network outage could publish an empty dashboard (Medium)

Running the collector in this sandbox (no Kalshi egress) rewrote
`data/live.json` with `tracked_markets: 0`. The collector now **fails closed**:
if a run observes no market it keeps the previous snapshot, reports
`published: false` with the reason, and exits non-zero so the Actions step goes
red instead of quietly committing an empty site.

---

## 2. Claims checked against official sources

| # | Claim on the site | Official source fetched | Result |
| - | - | - | - |
| C1 | Demo REST root is `https://external-api.demo.kalshi.co/trade-api/v2`, alternate `https://demo-api.kalshi.co/trade-api/v2` | <https://docs.kalshi.com/getting_started/demo_env> | **Confirmed verbatim** |
| C2 | Demo WebSocket is `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`, alternate `wss://demo-api.kalshi.co/trade-api/ws/v2` | same page | **Confirmed verbatim** (the brief's `wss://[…]` bracket form is not a valid URL) |
| C3 | Demo markets use mock funds and are not reflective of real markets | same page ("price and behavior of markets in the demo environment may not be reflective") | **Confirmed** |
| C4 | Order book returns **bids only**; best bid is the **last** element; implied YES ask = 1 − best NO bid | <https://docs.kalshi.com/getting_started/orderbook_responses> | **Confirmed**, and the code's `best_bid` / `implied_yes_ask` implement exactly this |
| C5 | A ticker with no resting orders returns HTTP 200 with empty arrays, not 404 | same page | **Confirmed** |
| C6 | Candlestick `period_interval` accepts **1, 60 or 1440 minutes only**; one request spans ≤ 5,000 periods; most recent candle can lag trades by a few seconds | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks> | **Confirmed** — the chart's "seconds" window is therefore *polled book mids*, not second candles; this is labelled on the page |
| C7 | `price` in a candle is **trade** OHLC; `yes_bid` / `yes_ask` are separate bid/ask distributions | same schema | **Confirmed** — the basis of the P1 fix |
| C8 | 429 responses carry rate-limit headers but **not** `Retry-After`; apply exponential backoff | <https://docs.kalshi.com/getting_started/rate_limits> | **Confirmed**. Both clients (`collector/kalshi_api.py`, `scripts/kalshi.mjs`) already fall back to exponential backoff when the header is absent — checked, no change needed |
| C9 | Unauthenticated public request limits are **not** published numerically | same page ("subject to separate limits") | **Confirmed** — the earlier flag "no documented number" is accurate |
| C10 | A market has `open_interest_fp`, `volume_fp`, `notional_value_dollars`, `yes_bid_dollars`, `yes_ask_dollars`, `result`, `status`, `settlement_value_dollars`, `settlement_ts` | <https://docs.kalshi.com/api-reference/market/get-markets> | **Confirmed** in the schema |
| C11 | Do not parse ticker strings to infer relationships | <https://docs.kalshi.com/getting_started/terms> | **Confirmed** — changed my own first draft of P4 to comply |
| C12 | Series/event/market hierarchy: market → event → series | same page | **Confirmed**; used for the event grouping on topic pages |

### Findings that are *not* verified, and are published as such

| Item | Why it cannot be verified here | Where it is published |
| - | - | - |
| Demo-account balance, fills and positions | Requires signed requests with an API key pair; none is configured for this repo, and the brief forbids manual input. An agent cannot mint a Kalshi key. | `review.html` standing limitations; `REQUIREMENTS.md` R9 |
| Live order placement on the demo account | Same cause. The adapter is implemented and unit-tested against a mock; it activates only when credentials exist. | `review.html`; `REQUIREMENTS.md` R11 |
| A WebSocket-driven feed | The documented WS hosts are known (C2) but the sandbox cannot open a TLS socket to them, so a WS client could not be tested end to end. The site uses polling + SSE instead and says so. | `review.html`; Methodology |
| Which news article *caused* a price jump | No official source maps articles to Kalshi price moves. Alerts link the market; topic pages list Kalshi's own named settlement sources. | `review.html` |

---

## 3. Irregularities in Kalshi's own demo records (not our data)

These are published on the Flagged for Review page with the API URL that shows
each one:

* Series records with unfilled template text in `settlement_sources`
  (`"account holder of "`, `"the relevant electoral authority governing "`).
* Settled markets with `series_ticker` absent (P4) — handled by attribution,
  not silently dropped.
* Very large `open_interest_fp` on books quoted 0.002 / 0.811 — the figures are
  official, but they cannot be liquidated at the quoted mid.

---

## 4. Checks run on the merged tree

| Check | Result |
| - | - |
| `python3 -m unittest discover -s tests` | 94 tests, 1 skipped (pre-existing), 0 failures |
| `python3 -m collector.test_runner` | PASS (7 series, 7 markets, 7 books, 7 alerts, 1 resolution) |
| `python3 -m trading.test_engine` | ALL PASS (fee table vs the official PDF, stats aggregation) |
| `npm test` (Node pipeline) | 29 pass, 0 fail |
| `node test/site_smoke.mjs docs/data` | ALL SITE SMOKE CHECKS PASSED |
| `node tools/rendercheck.mjs` | every page renders, no `undefined` / `NaN` / `[object Object]` |
| `python3 tools/linkcheck.py` | 45 pages, 513 internal links, 0 errors |
| `node --check assets/desk.js` | OK |
| `node tests/test_desk_chart.mjs` | DESK CHART BASIS OK |

## 5. What this review does **not** claim

* It does not claim any strategy is profitable. The ROI figure is a documented
  screen (mid shrunk toward 0.50 by the spread, minus the published taker fee),
  and every settled outcome is published including losses.
* It does not claim the demo prices resemble real markets (C3).
* It does not claim the paper ledger is demo-account performance.
