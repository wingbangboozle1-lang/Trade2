# Requirements → implementation → evidence

Every line of the brief, what implements it, and how it was checked.
"Live" means it runs against the real Kalshi demo API. "Simulated" means it is a
paper ledger. Nothing here is claimed as working without a link or a test.

| # | Requirement | Implementation | Evidence | Status |
| - | ----------- | -------------- | -------- | ------ |
| R1 | Executive summary outlining important details | `EXECUTIVE_SUMMARY.md`, `summary.html` | every claim links to a Kalshi doc page | done |
| R2 | Dashboard tracks **highest dollar amount** live events | `alerts.rank_events()` ranks by `open_interest_fp × notional_value_dollars` | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets); `tests/test_engine.py::TestRanking` | done |
| R3 | Only gas prices, elections, culture, crypto, golf | `collector/topics.py` — explicit category + matcher rules per topic | verified live: see `VERIFICATION.md` §C | done |
| R4 | Alert on swings ≥ **$0.10** either direction | `alerts.detect_swing()`, `SWING_THRESHOLD = 0.10` (collector) and `observe()` in `assets/live-probe.js` (browser) | 27 JS checks: exactly $0.10 fires, $0.0999 does not, one-sided books never fire | done |
| R5 | Alerting as a simplified scrolling chat, real time | `live.html` two `.chat-feed` panels. Rows come from two sources: the CI collector's buffer, and `assets/live-probe.js` polling the public demo order books from the visitor's browser every 5 s (rows tagged LIVE), because a static page could otherwise not alert while watched. Verified end-to-end by `test/desk_live_probe_dc.mjs` (jsdom, shipped page + real script). | `assets/desk.js`, `assets/live-probe.js` | done |
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
| R17 | Live charts link events and sites that may have caused a jump | alert rows link to the market; series pages list Kalshi's own settlement sources | no article attribution is invented — see `VERIFICATION.md` G4 | **flagged** |
| R18 | Keep topics separate, events within a topic organised together | one page per topic, markets grouped and ranked inside it | `categories/*.html` | done |
| R19 | No manual input required | collector + site build + Pages deploy are fully automated | `.github/workflows/kalshi-dashboard.yml` (cron `*/5`) | done |
| R20 | Review repo, verify from official sources, link for manual review | `VERIFICATION.md`, `COORDINATION.md` | 5 findings logged as irregularities | done |
| R21 | GitHub Pages site, clean landing page, subpages by category | `index.html`, `live.html`, `categories/*.html`, `methodology.html`, `review.html` | `tools/linkcheck.py`: 50 pages, 672 internal links, 0 errors; `tools/navcheck.py`: 13 pages, one canonical sidebar | done |
| R22 | Simple, easy-to-read table format with sources | every generated row carries an "API ↗" link to its own response | `site_build/build.py` | done |
| R23 | Missing values left blank and flagged, never inferred | `esc()`/`money()`/`cents()` emit `UNVERIFIED` | unit-tested rendering path | done |
| R24 | Parallel-session coordination | `COORDINATION.md`, merge conflict resolved keeping both boards | see F6 in `VERIFICATION.md` | done |
| R30 | The in-page detector asks each endpoint for tickers the way that endpoint accepts | `assets/live-probe.js` `tickersQuery(tickers, style)` | `tools/probe_live_check.py` measures all four serialisations and four candidate paths against the live demo host; `tools/probe_shape_assert.py` fails if the host flips; `probe-live.yml` runs hourly | done |
| R25 | Flagged-for-Review page published on the site | `review.html`, generated by `site_build/flagpage.py` | recomputed each run from the snapshot | done |
| R26 | PR → merge → confirm Pages deploy | see `COORDINATION.md` integration record | — | done |
| R27 | Keep topics separate, events within a topic together, and the menu **stable** | one canonical sidebar rendered by `site_build/build.py` for all 13 pages; per-topic tables keep each topic's events adjacent | `tools/navcheck.py`, `tests/test_nav_canonical.py` (7 tests) | done |
| R28 | Do not let a dead chat pass for a live one | live rows are tagged **LIVE** and kept out of the served snapshot; the status pill reads `LIVE · browser poll` only after a successful poll; empty states say which sources ran | `test/desk_live_probe_dc.mjs` | done |
| R29 | Never infer, never fill a blank | values are blank + `UNVERIFIED` when the official record has no two-sided quote; the phantom `$0.877` row published by a second dashboard is flagged, not silently used | `tests/test_rowsource_check.py`, `review.html` | done |

## Not satisfied, and why

* **R9 (demo-account portfolio).** Requires a Kalshi demo API key pair. The repo
  holds none. Faking account data would be fabrication, so the paper ledger is
  labelled SIMULATED throughout and the limitation is on the Flagged page.
* **R11 (execute trades).** Same cause. The adapter is complete and unit-tested
  against a mock; it activates automatically when credentials are present.
* **R17 (news attribution).** No official source maps news articles to Kalshi
  price moves. Rather than guess, alerts link to the market and topic pages list
  Kalshi's own named settlement sources (AAA, CF Benchmarks, ESPN, pgatour.com).
