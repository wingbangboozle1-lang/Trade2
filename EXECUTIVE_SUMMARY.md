# Kalshi Demo Monitoring Desk — Executive Summary

**Project:** `wingbangboozle1-lang/Trade2` · **Live site:** <https://wingbangboozle1-lang.github.io/Trade2/>
**Environment:** Kalshi **demo** only (`https://external-api.demo.kalshi.co/trade-api/v2`)
**Prepared:** 2026-11-20 · **Updated:** 2026-11-21 (session `arena-108b0dfb`) ·
Every claim below links to the official source it came from.

---

## 1. What this is

A dashboard that watches the highest-dollar live Kalshi **demo** markets in five
topics only — **gas prices, elections, culture, crypto, golf** — raises an alert
on any price swing of **$0.10 or more** in either direction, tracks each event
until it resolves YES or NO, and runs an automated **simulated** trading book that
scores its own results by strategy and by topic.

Two things it deliberately is **not**: it does not place real orders, and it does
not claim any news article caused a price move.

---

## 2. The API surface, verified

| Surface | Recommended demo endpoint | Also supported | Source |
| --- | --- | --- | --- |
| REST Trade API | `https://external-api.demo.kalshi.co/trade-api/v2` | `https://demo-api.kalshi.co/trade-api/v2` | [Kalshi: API Environments](https://docs.kalshi.com/getting_started/api_environments.md) · [Demo env](https://docs.kalshi.com/getting_started/demo_env.md) |
| WebSocket API | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | `wss://demo-api.kalshi.co/trade-api/ws/v2` | same two pages |

The brief listed the WebSocket host in a bracketed form
(`wss://[external-api-ws.demo.kalshi.co/...]`). That is not a valid URL; the
canonical form is the one in the table above, per the docs. **Flagged on the
site's Flagged-for-Review page.**

Live demo exchange status at build time, read from
`GET /exchange/status`: `exchange_active: true`, `trading_active: true`, four
Demo shards reported (indices 0–3). Source: the [exchange status
endpoint](https://docs.kalshi.com/api-reference/exchange/get-exchange-status).

---

## 3. What is live vs. what is simulated

| Capability | Status | Evidence |
| --- | --- | --- |
| Market data (events, markets, order books, candlesticks) | **Live** from the demo REST API | Collector runs in GitHub Actions; every table row links to its API response |
| Price-swing alerting (≥ $0.10) | **Live**, computed from successive order-book mids | `collector/alerts.py`, 32 unit tests |
| Event resolution (YES/NO) | **Live**, from the official `result` field | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) |
| Trading | **Simulated** paper ledger | No Kalshi credentials are configured in this repo |
| Demo-account portfolio performance | **Not available — UNVERIFIED** | Requires signed requests with an API key |

**Why trading is simulated.** Every portfolio and order endpoint requires the
signed headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` and
`KALSHI-ACCESS-SIGNATURE` ([authenticated requests
guide](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md)),
created from a key pair stored under *Account & security → API Keys*
([API keys](https://docs.kalshi.com/getting_started/api_keys.md)). This
repository holds **no such key**, and no key was supplied. Rather than fake it,
the paper ledger records modelled intent against **real observed prices**, and a
complete demo-order adapter (`LiveDemoBroker`, using
`POST /portfolio/events/orders` exactly as in the [create-order
quick start](https://docs.kalshi.com/getting_started/quick_start_create_order.md))
switches on automatically the moment `KALSHI_API_KEY_ID` and
`KALSHI_PRIVATE_KEY_PATH` exist.

---

## 4. How the numbers are produced

* **Price.** Kalshi returns **bids only**. Arrays are ascending, so the best bid is
  the *last* element; the implied YES ask is `1.00 − best NO bid`; the mid is the
  average. Source: [Orderbook
  responses](https://docs.kalshi.com/getting_started/orderbook_responses).
* **"Highest dollar amount".** Open-interest value = `open_interest_fp ×
  notional_value_dollars`, both official fields. `notional_value_dollars` is *"the
  total value of a single contract at settlement in dollars"*. Source: [Get
  Markets](https://docs.kalshi.com/api-reference/market/get-markets). Traded
  volume is shown in **contracts**, because the API publishes no traded-dollar
  figure.
* **Swing.** |mid₂ − mid₁| ≥ **$0.10**. Missing quotes are skipped, never treated
  as zero.
* **Fees.** The published taker fee `ceil(M × 0.07 × C × P × (1 − P))` from the
  [official fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf).
  All 42 published rows are reproduced exactly by the code and asserted in
  `tests/test_engine.py`.
* **Settlement payout.** The winning side receives $1.00 per contract (YES holders
  when the result is YES; NO holders when the result is NO); losing-side contracts
  receive no payout. Source: [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement).

A worked correction worth recording: the first implementation computed the fee in
binary floating point and produced **$1.76** where Kalshi's own table says
**$1.75** for 100 contracts at $0.50. Exact decimal arithmetic fixed it. The test
suite now pins all 42 rows, so the regression cannot come back.

---

## 5. The five topics, verified against the API

| Topic | Kalshi category / tag used | Verified | Series matched |
| --- | --- | --- | --- |
| Gas prices | `category=Economics` + `category=Commodities`, matched on `KXAAAGAS*` and gas keywords | `GET /series/KXAAAGASD` → *"US gas price up"*, settlement source **AAA**, <https://gasprices.aaa.com/> | 162 |
| Elections | `category=Elections` | `GET /series?category=Elections` returns 1,450+ series (e.g. `CONTROLS` "Senate winner", `GOVPARTY*` state governors) | 1,450 |
| Culture | `category=Culture` **and** `category=Entertainment` | Culture itself holds only 2 series; Kalshi files most culture content under **Entertainment** (413 open events observed) | see site |
| Crypto | `category=Crypto` | e.g. `BTCMAXY` "How high will Bitcoin get this year?", settlement source **CF Benchmarks** | 158 |
| Golf | `category=Sports&tags=Golf` | e.g. `KXPGAR3LEAD` "PGA Round 3 Leader", settlement sources ESPN / Fox Sports / pgatour.com | 104 |

Everything else on Kalshi — sports games, weather, financials — is out of scope
and is excluded by an explicit per-topic rule set in `collector/topics.py`.

---

## 6. Data-quality findings (all logged, none hidden)

1. **Template text left in production records.** Several demo series carry
   unfilled placeholders, e.g. settlement source named `"account holder of "` and
   `"the relevant electoral authority governing "`, and rule text reading
   *"for  before their publication"*. Surfaced with the source URL on the
   Flagged-for-Review page.
2. **Stale penny quotes on huge open interest.** Elections markets show open
   interest in the hundreds of millions of contracts against 1–2 cent bids with
   essentially no resting size. A naive ROI model turns these into "+480% ROI"
   trades. A tradability gate (minimum $0.01 price, ≥10 contracts of resting
   depth, ≥1 contract at the top level) was added after replaying 300 real
   markets: **299 of 300 drop out**, which is the correct answer — they were never
   tradable.
3. **No published rate limits for unauthenticated calls.** The demo REST response
   carries no `X-RateLimit-*` headers, and the docs state only that unauthenticated
   requests "are subject to separate limits"
   ([Rate limits](https://docs.kalshi.com/getting_started/rate_limits)). The
   collector therefore enforces its **own** wall-clock budget and reports anything
   it had to skip.
4. **Exchange sharding is real.** The demo advertises four exchange indices; orders
   route by `market_ticker` ([Exchange
   sharding](https://docs.kalshi.com/getting_started/exchange_sharding)). Market
   rows carry `exchange_index`, so cross-shard assumptions are not baked in.

---

## 7. Suggestions to make the site more live and interactive

* **WebSocket instead of polling.** The documented `ticker` and `orderbook_delta`
  channels over `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` push
  updates continuously; the socket handshake needs the same signed headers as
  REST. This is the single biggest latency win and is already scaffolded.
* **Candlestick backfill.** `GET /series/{s}/markets/{t}/candlesticks` returns
  OHLC per period (1/60/1440 minutes, max 5,000 periods per request). The desk
  already seeds its graph from it, so a chart is populated the moment a market is
  selected instead of waiting for the first polls.
* **Pin the graph to the event's resolution.** When `result` flips to `yes`/`no`,
  draw the settlement line on the chart and close the alert thread with the
  outcome.
* **Structured-cause links.** Instead of guessing a news cause, surface the
  series' own `settlement_sources` (AAA, CF Benchmarks, ESPN, pgatour.com) next
  to each alert — those are the official pages that will explain the move.
* **Watchlist-driven alerts.** Let a trader pin markets so the all-events feed
  stays global while the shortlist feed follows what they care about.
* **Throttle the chat instead of the data.** Keep every alert in the JSON store
  but collapse bursts visually, so a fast market does not flood the reader.

The first item used to read "WebSocket instead of polling". That is still the
right answer for latency, but it is **blocked on credentials, not effort**: the
official connection page states that authentication is required to establish a
WebSocket connection, so a public page cannot use it. The shipped compromise is
a browser-side REST poll of the public order books (`assets/live-probe.js`),
which is live only while the page is open. The trade-off is stated on the
Flagged-for-Review page rather than glossed over.

---

## 7b. Update 2026-11-21 — what was wrong, and what changed

Four defects were reproduced before anything was edited, and each now has a
test that fails if it returns.

| # | Defect found on `main` | Evidence | Fix |
| - | - | - | - |
| N-01 | Every page rendered "Overview" **twice** in the sidebar, and the menu order changed from page to page because the active link was dropped instead of marked. | parsed all 13 generated pages | one canonical nav in `site_build/build.py`; `tools/navcheck.py` + 7 tests |
| N-02 | The published desk showed **0** swings ≥ $0.10 and an empty chat, because alerts could only be produced by a scheduled CI job diffing successive snapshots. | `data/alerts.json` = `[]`; live page fetch | `assets/live-probe.js` polls the public order books from the visitor's browser (demo API is CORS-open), applies the same rule, tags rows **LIVE**; 25 JS checks + a jsdom end-to-end test |
| N-03 | A second published dashboard reports a **$0.877** swing on `KXPRESNOMD-28-BOBA`; the official record at that time was `yes_bid 0.0010` / `yes_ask 0.8860`, i.e. no two-sided market. | [market record](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-BOBA) | logged on Flagged for Review with the source; that pipeline has another owner |
| N-04 | The site never used the demo API's permissive CORS policy, although CI had captured proof of it. | `data/_cors.txt`, `data/capabilities.json` | the basis for the N-02 fix |

Two defects were also found **in this session's own new code** by its tests and
fixed before shipping: an exact 10-cent move measured as 9.999999999999998 cents
in binary floating point (prices are now rounded to the quote grid at capture),
and a total network failure that was reported as a healthy poll with 0 markets.

### Why the browser poll is safe

* It builds only two URLs, both documented unauthenticated GETs:
  `GET /markets?tickers=…` and `GET /markets/orderbooks?tickers=…`
  ([Get Markets](https://docs.kalshi.com/api-reference/market/get-markets),
  [order books](https://docs.kalshi.com/getting_started/orderbook_responses)).
* It contains no `POST`, no `Authorization` header and no portfolio path; a
  test strips comments and asserts the absence of all three.
* A swing only counts on a **two-sided** book with a spread under $0.10, so a
  stale one-sided quote cannot fake a move (that is exactly N-03).
* It backs off exponentially (5s → 60s) on any failure and stops entirely when
  the tab is hidden, per the documented advice to back off on `429`
  ([rate limits](https://docs.kalshi.com/getting_started/rate_limits)).

---

## 8. Source index

| # | Source | Used for |
| --- | --- | --- |
| S1 | <https://docs.kalshi.com/getting_started/api_environments.md> | REST + WebSocket base URLs, signed path rule |
| S2 | <https://docs.kalshi.com/getting_started/demo_env.md> | Demo root, mock funds, pricing caveat |
| S3 | <https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md> | Signature construction, headers, common errors |
| S4 | <https://docs.kalshi.com/getting_started/quick_start_market_data.md> | Unauthenticated market data walkthrough |
| S5 | <https://docs.kalshi.com/getting_started/orderbook_responses.md> | Bid-only book, ascending arrays, implied ask, spread maths |
| S6 | <https://docs.kalshi.com/api-reference/market/get-markets.md> | Market fields, statuses, pagination rules |
| S7 | <https://docs.kalshi.com/api-reference/market/get-series-list.md> | Series discovery, `fee_type`, settlement sources |
| S8 | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md> | OHLC candles, period limits |
| S9 | <https://docs.kalshi.com/getting_started/market_settlement.md> | YES/NO payout mechanics |
| S10 | <https://docs.kalshi.com/getting_started/exchange_sharding.md> | Exchange indices, routing |
| S11 | <https://docs.kalshi.com/getting_started/rate_limits.md> | Token buckets, unauthenticated caveat |
| S12 | <https://docs.kalshi.com/getting_started/quick_start_create_order.md> | Order payload shape for the live adapter |
| S13 | <https://kalshi.com/docs/kalshi-fee-schedule.pdf> | Fee formula + the 42-row oracle table |
| S14 | <https://docs.kalshi.com/getting_started/quick_start_websockets.md> | WS auth, channels, keep-alive |
| S15 | <https://external-api.demo.kalshi.co/trade-api/v2/exchange/status> | Live status at build time |
| S16 | <https://docs.kalshi.com/websockets/websocket-connection> | WebSocket requires API-key auth (why the public page polls instead) |
| S17 | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-BOBA> | The one-sided record behind the published phantom swing (N-03) |

---

# Appendix — Executive summary (session `arena-c0205283`, kept verbatim)

The section below is the summary produced by the session that built the
`docs/` site and the `trading/` engine (PR #11). It is kept unchanged; where
it overlaps with the summary above, both are authoritative for their own
implementation.

# Executive Summary — Kalshi Demo Dashboard

**Repo:** https://github.com/wingbangboozle1-lang/Trade2 · **Site:** https://wingbangboozle1-lang.github.io/Trade2/
**Data source:** Kalshi **demo** Trade API v2 (public market data, no credentials required)
**Status:** automated collector runs on GitHub Actions every 15 minutes; trading is simulated (paper only).

---

## 1. What was built

| Deliverable | Where | Notes |
|---|---|---|
| Live dashboard, highest-$-volume events, 5 topics only | `docs/index.html` + `docs/{gas-prices,elections,culture,crypto,golf}.html` | topics separated; events grouped inside each topic; ranked by dollar volume |
| Swing alerts ≥ $0.10 both directions, two scrolling chats | Home page: **All events** + **High-ROI picks** | driven by official candlestick closes; threshold exactly 0.10 |
| Track events to resolution (YES/NO) | per-topic **Resolutions** tables + home feed | outcome taken from the API's `result` field only |
| Simulated strategy trading + performance | `docs/portfolio.html`, `trading/engine.py` | fills vs. real demo order book; official fees; stats by strategy **and** trade type |
| Interactive charts: X = time (s/m/h), Y = price | per-topic chart panel | windows: seconds / minutes / hours toggle |
| Liquidity at each price | depth chart (contracts resting at price) + depth $ columns | from the official order-book endpoint |
| Catalyst headlines for ≥$0.10 jumps | alerts tables + chat messages | time-matched headlines with links; blank + flagged when none verify |
| Executive summary | this file + `docs/summary.html` | |
| Flagged for Review page | `docs/flagged.html` | live scan of all `flags` arrays + curated irregularities FL-01…FL-09 |
| Verification ledger | `docs/verification/sources.md` | every claim → official URL |
| Coordination board | `COORDINATION.md` | claim log, task status, PR/merge record |

## 2. Endpoints (official)

| Use | URL | Docs |
|---|---|---|
| REST (recommended demo) | `https://external-api.demo.kalshi.co/trade-api/v2` | [demo_env](https://docs.kalshi.com/getting_started/demo_env) |
| REST (alternate demo) | `https://demo-api.kalshi.co/trade-api/v2` | [api_environments](https://docs.kalshi.com/getting_started/api_environments) |
| WebSocket | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [WS quick start](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Markets | `GET /markets?status=open` | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| Trades | `GET /markets/trades?ticker=…` | [Get Trades](https://docs.kalshi.com/api-reference/market/get-trades) |
| Candlesticks | `GET /series/{s}/markets/{t}/candlesticks?start_ts&end_ts&period_interval=1\|60\|1440` | [Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |
| Order book | `GET /markets/{t}/orderbook?depth=…` | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Series (topic mapping) | `GET /series/?category=…` | [Get Series List](https://docs.kalshi.com/api-reference/market/get-series-list) |
| Fees (formula) | — | [Official fee schedule PDF, eff. 2026-07-07](https://kalshi.com/docs/kalshi-fee-schedule.pdf) |

**WebSocket caveat (FL-02):** the WS handshake requires signed `KALSHI-ACCESS-*` headers, so without credentials
the live layer polls REST. This is documented on the Flagged page rather than hidden.

## 3. Topic mapping (verified against live demo API, 2026-11-20)

| Topic | Official selector | Sample series seen live |
|---|---|---|
| Gas prices | `category=Economics/Commodities` + energy tags or “gas” in title | `KXAAAGASDDE`, `KXAAAGASMINCA`, `CPIGAS`, `OILW`, `KXSPRMAX` |
| Elections | `category=Elections` (strict) or `Politics` + election keywords | `KXELONMARS-99` (sample) |
| Culture | `category=Culture/Entertainment/Mentions` (strict) | `KXXBANNEDGROK`, `KXXBANNEDMURRAYHILLGUY1` |
| Crypto | `category=Crypto` (strict) or `Financials` + crypto keywords | `KXSOLE`, `BTCMAX100`, `KXHYPEPERP`, `KXSOLABOVE150BY` |
| Golf | `category=Golf` (strict) or `Sports` + tag/title/ticker golf | `KXPGATOUR`, `KXPGA`, `KXGOLFMAJOR`, `KXGENESISINVITATIONAL` |

Rules live in `collector/topics.py` (readable, conservative: broad categories require a secondary keyword match).
**Every series→topic row in `docs/data/series.json` carries the exact API URL that proves it.**
Irregularity: “Golf” is a **tag**, not a category (`category=Golf` → null) — logged as FL-06.

## 4. Alerting rule

- Source of truth: official candlestick closes (`price.close_dollars`). Windows are scanned smallest-first
  (1h → 6h → 72h spans) and the largest qualifying step is reported with its window label. Finest official
  candle interval is **1 minute** (`period_interval=1`); the UI's seconds/minutes/hours buttons select the
  *time span* shown, and the chart states the real candle interval.
- Alert when `|close_t − close_{t−1}| ≥ $0.10` — either direction, exactly the requested threshold.
- Each alert stores: ticker, topic, from/to, delta, window, candle source URL, and candidate headlines (±6 h).
- **Headlines are candidate catalysts by time proximity only — never asserted as causes.** No headline verified → cell blank + flagged.

## 5. Trading model (simulated)

- **No credentials exist (FL-01)** → no orders are sent; fills are simulated against the real demo book as taker.
- Fee (official PDF): `ceil(0.07 × C × P × (1 − P))`, maker `0.0175` (multiplier defaults 0), no settlement/membership fee.
  `trading/test_engine.py` reproduces **all 42 rows** of the official fee table.
- Strategies (parameters explicit, results measured):
  - `swing_momentum` — follow a ≥$0.10 move; exit on ±$0.05 target/stop, stall, or 40 periods.
  - `swing_reversal` — fade the move (assumed reversion share **30% — an assumption, not a forecast**).
  - `roi_edge` (high-ROI feed) — enter only when `30% × swing − fee − spread ≥ $0.02`/contract (or book-imbalance equivalent).
- Risk: max 8 open, $200/position, daily loss cap pauses entries.
- Settlement grading: positions settle at the API's official `result` ($1 or $0).
- Stats published by **strategy** and by **trade type** (`strategy|signal|side`) for iteration.

## 6. Verification policy (enforced in code)

1. Every table row renders its own `source_url` (official API endpoint) and, where relevant, a docs link.
2. Values that cannot be confirmed are stored as JSON `null` → rendered as a blank cell with an **unverified** badge.
3. Blanks sink to the bottom of sorted tables (never treated as a number).
4. Collector errors land in `run_meta.json` and appear on the **Flagged for Review** page.
5. Nothing is inferred: `notional_usd` is labeled a *derived ranking metric* (`volume_fp × last price`, both official
   fields) — the raw official fields sit in the same row.

## 7. Known gaps → Flagged for Review

FL-01 no credentials (paper only) · FL-02 WS needs auth → REST polling · FL-03 news RSS unverifiable from sandbox ·
FL-04 `/series` ignores `limit` · FL-05 fee PDF prose-vs-table rounding nuance (≤$0.01) · FL-06 topic≠category
mapping (Golf is a tag) · FL-07 book is bids-only (asks implied) · FL-08 thin markets return empty series ·
FL-09 pinned-branch exception to the session-branch protocol. Full detail with links: **docs/flagged.html**.

## 8. Suggestions for a more live / interactive feel (implemented + roadmap)

**Implemented now**
- Two-speed data: 15-minute collector cadence on Pages, plus an optional local mode (`live/server.py`)
  that pushes a fresh order-book snapshot every **5 seconds over SSE** — the page auto-detects and upgrades.
- Swing markers drawn directly on the price chart (green ▲ / red ▼ dots at every ≥$0.10 point in view).
- Clickable catalyst headlines under each swing, with an explicit “not causation” disclaimer.
- Sortable tables (click a header); blanks always sink so an unverified value can’t be mistaken for a low one.
- Chart window segmented control (seconds / minutes / hours) and a market picker per topic.
- Depth chart showing contracts resting at each price (YES bids vs NO bids side by side).
- LIVE pulse dot + freshness chip (last run time, error count, environment).

**Good next steps (not built)**
- Browser Notification / sound alert when a ≥$0.10 swing hits the selected topic.
- Watchlist + “only my topics” personalization stored in localStorage.
- WebSocket tick streaming (needs an API key — FL-01/FL-02) for true sub-second updates on Pages.
- Strategy lab: parameter sliders (reversion share, ROI threshold) re-running the backtest in-browser.
- News correlation view: aggregate all swing headlines into a single timeline per topic.
- Email/Slack webhook alerts from the collector run (Actions secret).

## 9. How to review manually

- Live site: https://wingbangboozle1-lang.github.io/Trade2/
- Raw data written by each run: `docs/data/*.json` (every object carries `source_url`)
- Verification ledger: `docs/verification/sources.md`
- Task board / PR record: `COORDINATION.md`
- Reproduce any row: open its `source_url` — it is a GET on the public demo API, no key needed.
