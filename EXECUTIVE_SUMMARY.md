# Kalshi Demo Monitoring Desk — Executive Summary

**Project:** `wingbangboozle1-lang/Trade2` · **Live site:** <https://wingbangboozle1-lang.github.io/Trade2/>
**Environment:** Kalshi **demo** only (`https://external-api.demo.kalshi.co/trade-api/v2`)
**Prepared:** 2026-11-20 · Every claim below links to the official source it came from.

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
* **Settlement payout.** YES pays $1.00 per contract, NO pays $0.00.
  Source: [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement).

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
