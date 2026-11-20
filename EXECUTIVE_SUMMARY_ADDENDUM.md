# Executive summary — addendum (session `arena-93e9da14`, 2026-11-20)

Audience: a trader using the desk, and a reviewer who needs to know what is
verified and what is not. Every figure below is either a value read from the
Kalshi demo API (URL given) or a project rule published in the repo (file given).
Nothing here is estimated. Where a claim could not be checked against an
official source it is labelled **not verified** and it also appears on the
site's [Flagged for review](https://wingbangboozle1-lang.github.io/Trade2/review.html)
page.

This document **adds to** `EXECUTIVE_SUMMARY.md` rather than replacing it, because
that file is under active edit by session `arena-e4e8f4e1` (claim T14 in
`COORDINATION.md`).

---

## 1. What this system is

A monitoring and paper-trading desk for **Kalshi's demo environment**
(`https://external-api.demo.kalshi.co/trade-api/v2`, the recommended demo REST
root per the [official environments page](https://docs.kalshi.com/getting_started/api_environments.md);
`https://demo-api.kalshi.co/trade-api/v2` is also supported).

Scope is deliberately narrow: **gas prices, elections, culture, crypto and golf**.

| Capability | Status today | How it is produced |
| --- | --- | --- |
| Highest-dollar live events per topic | live | `open_interest_fp × notional_value_dollars` from [`GET /markets`](https://docs.kalshi.com/api-reference/market/get-markets), ranked in `collector/alerts.py::rank_events` |
| Alert on any swing ≥ $0.10 either way | live | `collector/alerts.py::detect_swing`, measured between successive observations and against the 5-minute reference candle |
| Two scrolling chats (all events · model shortlist) | live | `assets/desk.js`, fed by `data/live.json` (`alerts`, `model_shortlist`) |
| Price graph, X = time (seconds / minutes / hours), Y = contract price | live | `assets/desk.js` canvas; history seeded from the official [candlestick endpoint](https://docs.kalshi.com/api-reference/market/get-market-candlesticks), then live order-book mids |
| Contracts available at each price | live | [`GET /markets/orderbooks`](https://docs.kalshi.com/getting_started/orderbook_responses.md), rendered as depth bars |
| Track events until they resolve, and how (YES/NO) | live | tracked-market ledger + `GET /markets?tickers=…` → `result`, `settlement_value_dollars` ([settlement docs](https://docs.kalshi.com/getting_started/market_settlement)) |
| Automated simulated trades, several strategies | simulated | `collector/engine.py` (`momentum`, `mean-reversion`, `value`, `resolution-hold`), scored by strategy, topic and trade type |
| Portfolio performance of **your demo account** | **not available** | needs an API key pair; the repo has none. The paper ledger is labelled SIMULATED everywhere |
| Candidate catalyst next to a sharp jump | live, labelled | Google News RSS lookup in `collector/news.py`; a *candidate*, never a proven cause |

## 2. What this session changed, and why it mattered

Four defects were found by reading the published site against the requirements and
reproducing each one from the committed snapshot. All four are fixed on this
branch, each with a regression test.

| # | Defect as published | Root cause (verified) | Fix | Proof |
| --- | --- | --- | --- | --- |
| 1 | Every topic page said **"Resolved captured 0"** while the store held 2,000 settled markets | `GET /markets` returns **no `series_ticker`** field (official schema, [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets); also confirmed in the live demo payload), so settled rows could not be attributed to a topic — and the global settled feed is dominated by demo `KXQUICKSETTLE`/weather series the brief excludes | The collector now keeps a **tracked-market ledger** and asks the exchange how exactly those markets resolved, via the documented `tickers` filter (verified live: `GET /markets?tickers=KXAAAGASW-26NOV16-4.2000,…` returned `result`, `settlement_ts`, `settlement_value_dollars`); topic attribution is recorded at track time and grouped by `alerts.group_resolutions_by_topic` | `tests/test_engine.py::TestSeriesDerivation` (3 tests, incl. real tickers) |
| 2 | The **model chat was permanently empty** — the second of the two required chats | Two different gates: the server kept alerts whose ticker had a same-run signal with `score ≥ 0.10`, the browser kept alerts with `net_roi ≥ 0.05`. A swing and a live signal on the same ticker in the same 5-minute run almost never coincide (snapshot: 29 alerts, 1 signal, `high_roi_alerts: []`) | **One published gate** (`model_gate` in the snapshot, `alerts.MODEL_SCORE_GATE` in code) used by collector and browser; each swing is scored by the model *when it fires*; the verdict persists on a 6-hour watchlist (dropped on settlement), so the shortlist contains both swings and live flags | `TestModelFeed` (6 tests incl. a regression test asserting a watch flag alone populates the feed) |
| 3 | Requirement "live charts should include events and **website links** that may have caused a jump" was declined on this site | No official source maps an article to a price move — so the desk previously printed nothing at all | Swings now carry **candidate headlines** with four explicit states (`ok`, `no-headlines-found`, `unavailable`, `skipped`), a new **"What moved this market"** panel beside the chart, and links in both chats. Causation is never asserted; a failed lookup says so instead of showing a blank | `TestNewsLookup` (4 tests, canned RSS + injected failure), `tools/deskcheck.mjs` (renders the desk in jsdom and fails if the panel or either chat is empty) |
| 4 | Counters rendered as `162.00` | the money formatter was used for counts | whole-number formatting (`cnt()`) — the concurrently merged fix by session `arena-997c9c83` was kept and this session's duplicate helper was dropped | visible in the generated pages |

## 3. Important details about the data itself

* **Demo, not money.** The demo environment's prices "may not be reflective" of
  real markets and credentials are not shared with production
  ([demo docs](https://docs.kalshi.com/getting_started/demo_env.md)). Every trade
  on this desk is a ledger entry, not an order.
* **Bids only.** The order book returns bids, ascending, best bid last; the YES
  ask is implied as `1.00 − best NO bid`, and the mid is the average of the two
  ([order book docs](https://docs.kalshi.com/getting_started/orderbook_responses.md)).
  A market with no book reports `0.0000 / 1.0000`; the desk treats that as *no
  quote* rather than a $0.50 price, which is what previously produced phantom alerts.
* **Fixed-point strings.** Money and size fields arrive as decimal strings
  (`"0.4200"`, `"13.00"`), per the
  [fixed-point migration notes](https://docs.kalshi.com/getting_started/fixed_point_migration.md);
  they are parsed as `Decimal` and converted once.
* **Fees.** Simulated fills pay Kalshi's published taker fee,
  `ceil(M × 0.07 × C × P × (1 − P))` in dollars, from the
  [official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf); all 42
  published table rows are asserted by `tests/test_engine.py`.
* **Settlement.** A YES outcome pays $1.00 per YES contract; a NO outcome pays
  $1.00 per NO contract; the desk reads `result` and `settlement_value_dollars`
  from the market record and never infers an outcome.
* **Coverage is bounded on purpose.** Each run tracks a ranked slice (150 markets
  per topic, up to 300 order books per batch request, a 330-second budget) and
  publishes what it skipped instead of quietly covering less.

## 4. The snapshot committed with this branch

`data/live.json`, generated 2026-11-20T19:09:37Z by the scheduled collector from
the endpoints above.

| Metric | Value | Source |
| --- | --- | --- |
| Markets tracked | 750 (150 per topic) | `GET /events?status=open&with_nested_markets=true` per series |
| Series in scope | gas 162 · elections 1,450 · culture 789 · crypto 158 · golf 104 | `GET /series?category=…` |
| Open events seen | gas 17 · elections 19 · culture 23 · crypto 260 · golf 63 | same |
| Markets with a live book | 750 of 750 requested (batches of 100) | `GET /markets/orderbooks` |
| Swings ≥ $0.10 in the buffer | 3 (after the 2026-11-20 purge of rows without a verifiable quote basis) | `data/alerts.json` |
| Highest-dollar event | `KXPRESNOMD-28-RW` "Raphael Warnock", open-interest value $189,529,515.91 | [`GET /markets/KXPRESNOMD-28-RW`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) |
| Simulated book | equity $9,861.56 from $10,000 · 1 open position · $13.44 fees · realised $0 | `data/portfolio_state.json` (SIMULATED) |
| Resolutions attributable to a topic | 0 at this snapshot; the store is purged to in-scope rows and repopulates as tracked markets settle | `GET /markets?tickers=…` |
| Run health | 112.2 s of 330 s budget · 0 errors | `data/live.json.run_seconds`, `.errors` |

**Open item created by this session's work:** `data/resolutions.json` shrinks on
the first run after deploy (2,000 out-of-scope rows dropped). That is intended —
a resolution table that cannot be linked to a topic page is not evidence — and
the Flagged page states it until tracked markets settle.

## 5. Recommendations to make the desk more live and interactive

Ordered by value per unit of work. Each is a proposal, not a claim that it exists.

1. **Push instead of poll.** The Pages site refreshes a published snapshot every
   30 s; a WebSocket bridge on the documented `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`
   orderbook channel would cut latency to sub-second. Needs a small always-on
   relay (Pages is static) — `server/app.py` already exposes SSE locally, so the
   front-end path exists.
2. **Per-trade alerts.** Emit a chat row when a simulated position is opened,
   marked, taken-profit or settled, so the desk narrates its own book.
3. **Depth-aware execution.** Size simulated fills by the resting contracts at
   the level crossed, instead of assuming the top-of-book price for any size.
4. **Chart annotations that link out.** Draw the ≥ $0.10 timestamps on the price
   line and open the candidate headline on click (the data is now in the
   snapshot; the canvas needs the click map).
5. **Topic swim-lanes.** Group the all-events chat by topic with a one-line
   summary per topic, so a trader reads "what moved in gas" without scrolling.
6. **A second, faster collector pass for crypto/golf minute markets.** The
   15-minute crypto series settle inside the run interval; a short
   high-frequency pass would resolve them within a minute instead of one cycle.
7. **Credential-gated live book.** If `KALSHI_API_KEY_ID` and
   `KALSHI_PRIVATE_KEY_PATH` are added as repo secrets, `LiveDemoBroker` becomes
   active and the portfolio page can show the real demo account instead of the
   simulated ledger. Until then this is **not verified**, not simulated-but-labelled.

## 6. Standing limits, stated plainly

* **No demo-account figures.** No credentials exist in this repository, so no
  balance, fill or position of yours is shown. The simulator is labelled
  SIMULATED on every surface.
* **No causation claims.** A headline near a move is a candidate. No source
  states that an article moved a Kalshi price.
* **No back-filled data.** A value the API did not return renders blank with an
  `UNVERIFIED` badge; historical gaps stay gaps.
* **The model is a screen, not a forecast.** Net ROI after fees with a depth
  penalty; outcomes are published including every loss.
* **One snapshot cadence per pipeline.** The root desk refreshes on a 5-minute
  schedule; `docs/` and `kalshi-dashboard/` are separate collectors from other
  sessions with their own cadence (see `COORDINATION.md`).

## 7. Where to check any of this by hand

* Site: <https://wingbangboozle1-lang.github.io/Trade2/> · live desk `/Trade2/live.html` ·
  methodology `/Trade2/methodology.html` · flags `/Trade2/review.html`
* Line-by-line log: [`VERIFICATION.md`](VERIFICATION.md) §A–§H
* Requirement → implementation → evidence: [`REQUIREMENTS.md`](REQUIREMENTS.md)
* Cross-session board and claims: [`COORDINATION.md`](COORDINATION.md)
* Tests: `python3 -m unittest discover -s tests` (87 pass, 1 skip needs the
  optional `cryptography` package) · `npm test` (18) · `node --test test/alerts-view.test.mjs` ·
  `node tools/deskcheck.mjs --selftest` · `python3 tools/linkcheck.py`
