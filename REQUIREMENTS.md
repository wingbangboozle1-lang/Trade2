# Requirements → implementation → evidence

Every line of the brief, what implements it, and how it was checked.
"Live" means it runs against the real Kalshi demo API. "Simulated" means it is a
paper ledger. Nothing here is claimed as working without a link or a test.

| # | Requirement | Implementation | Evidence | Status |
| - | ----------- | -------------- | -------- | ------ |
| R1 | Executive summary outlining important details | `EXECUTIVE_SUMMARY.md`, `summary.html` | every claim links to a Kalshi doc page | done |
| R2 | Dashboard tracks **highest dollar amount** live events | `alerts.rank_events()` ranks by `open_interest_fp × notional_value_dollars` | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets); `tests/test_engine.py::TestRanking` | done |
| R3 | Only gas prices, elections, culture, crypto, golf | `collector/topics.py` — explicit category + matcher rules per topic | verified live: see `VERIFICATION.md` §C | done |
| R4 | Alert on swings ≥ **$0.10** either direction | `alerts.detect_swing()`, `SWING_THRESHOLD = 0.10` | unit tests: at-threshold fires, below does not | done |
| R5 | Alerting as a simplified scrolling chat, real time | `live.html` two `.chat-feed` panels, SSE or 30 s polling | `assets/desk.js` | done |
| R6 | Two chats: all events + model's high-ROI shortlist | `#feedAll` and `#feedModel` | model feed filters on `signal.net_roi` | done |
| R7 | Track live events until resolved; how it resolved (yes/no) | collector reads `result` from `GET /markets?status=settled`, pages render it | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement); `data/resolutions.json` | done |
| R8 | Automate simulated trades to test strategies | `collector/engine.py` + `select_trades()`; runs every scheduled collection | 4 strategies: momentum, mean-reversion, value, resolution-hold | done |
| R9 | Track portfolio performance using the demo account | **Not possible without credentials** | see `VERIFICATION.md` G1 | **flagged** |
| R9b | Portfolio performance of the simulated book | `Portfolio.analytics()` → equity, realised P&L, win rate, expectancy, ROI on cost, fees, max drawdown | `summary.html#performance` | simulated |
| R10 | Analyse and categorise results by type of trade | analytics split `by_strategy`, `by_category`, `by_topic` | `summary.html#performance` | done |
| R11 | Execute trades on events and track performance | `LiveDemoBroker` posts to `POST /portfolio/events/orders`; inert without keys | [create order](https://docs.kalshi.com/getting_started/quick_start_create_order) | **flagged** (not executable here) |
| R12 | Interactive price graph, X = time, Y = contract price | canvas chart in `assets/desk.js` | seeds from official candlesticks, then appends polled book mids | done |
| R13 | Choose seconds / minutes / hours window | `#windowTabs` → 90 s / 60 min / 12 h | `WINDOWS` in `desk.js` | done |
| R14 | Show current liquidity: how many contracts at a given price | `alerts.analyse_liquidity()` returns price levels with contract counts and cumulative depth | [Orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses) | done |
| R15 | Make suggestions to be more live/interactive | `EXECUTIVE_SUMMARY.md` §7, `methodology.html` | — | done |
| R16 | Simplified graphs and charts | single-series price chart + horizontal depth bars | no chart library, no bundle | done |
| R17 | Live charts link events and sites that may have caused a jump | every swing row links the Kalshi event page, a news search, and the **candidate headlines** the collector found within ±6 h, labelled "candidate headline, not confirmed"; series pages list Kalshi's own settlement sources | `collector/collector.py::attach_news` (line 300), `site_build/build.py::alert_chat_row` (line 234), `assets/desk.js` (line 269); `VERIFICATION-7695ba1b.md` §2 | done — no article attribution is invented (see `VERIFICATION.md` G4) |
| R18 | Keep topics separate, events within a topic organised together | one page per topic, markets grouped and ranked inside it | `categories/*.html` | done |
| R19 | No manual input required | collector + site build + Pages deploy are fully automated | `.github/workflows/kalshi-dashboard.yml` (cron `*/5`) | done |
| R20 | Review repo, verify from official sources, link for manual review | `VERIFICATION.md`, `COORDINATION.md` | 5 findings logged as irregularities | done |
| R21 | GitHub Pages site, clean landing page, subpages by category | `index.html`, `live.html`, `categories/*.html`, `methodology.html`, `review.html` | `tools/linkcheck.py`: 10 pages, 157 internal links, 0 errors | done |
| R22 | Simple, easy-to-read table format with sources | every generated row carries an "API ↗" link to its own response | `site_build/build.py`, `site_build/extras.py`; audited by `tools/rootsource_check.py`: **888 market rows across 22 published pages, 888 with a demo source link, 0 production links** (`VERIFICATION-7695ba1b.md` §1 D-2) | done |
| R23 | Missing values left blank and flagged, never inferred | `esc()`/`money()`/`cents()` emit `UNVERIFIED` | unit-tested rendering path | done |
| R24 | Parallel-session coordination | `COORDINATION.md`, merge conflict resolved keeping both boards | see F6 in `VERIFICATION.md` | done |
| R25 | Flagged-for-Review page published on the site | `review.html`, generated by `site_build/flagpage.py` — irregularities, standing limitations, refused moves, book-vs-record gaps, **and the last automated re-check of the published rows against the official API** | recomputed each run from the snapshot; `VERIFICATION-7695ba1b.md` §1 D-3 | done |
| R26 | PR → merge → confirm Pages deploy | see `COORDINATION.md` integration record | — | done |
| R27 | Live swing detection **between** collector runs | the browser measures real books with `GET /markets/orderbooks` every 45 s and applies the same $0.10 and quote-integrity rules; the YES/NO chart switch and the same-origin proxy came with it | `assets/live-feed.js`, `assets/desk.js`; request shape verified live in `VERIFICATION-7695ba1b.md` §1 D-1 | done |

## Not satisfied, and why

* **R9 (demo-account portfolio).** Requires a Kalshi demo API key pair. The repo
  holds none. Faking account data would be fabrication, so the paper ledger is
  labelled SIMULATED throughout and the limitation is on the Flagged page.
* **R11 (execute trades).** Same cause. The adapter is complete and unit-tested
  against a mock; it activates automatically when credentials are present.
* **R17 (news attribution) — satisfied, with a stated limit.** No official
  Kalshi source maps an article to a price move, so the site never asserts
  causation. Every swing row carries the Kalshi event page, a news search, and
  any headlines the collector found within ±6 hours, labelled **"candidate
  headline, not confirmed"**. When there is no headline the row says
  *"no verified news link"* and why — it is never filled in.

## Open items recorded, not silently dropped

| Item | Where it is published |
| --- | --- |
| Demo-account balances / positions / fills and real demo orders need a Kalshi demo API key pair, which no one has created yet | `review.html` — standing limitations |
| The Kalshi WebSocket needs signed handshake headers a browser cannot set, so the desk reads the same books over the documented anonymous REST batch endpoint | `live.html` — live-pulse note; `review.html` |
| 411 of the 750 ranked events have no two-sided quote; their price cells stay blank and they are labelled `no book` | `index.html` — price-mix strip; `review.html` |
