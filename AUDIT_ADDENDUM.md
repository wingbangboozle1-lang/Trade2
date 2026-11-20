# Fresh integration audit — 2026-11-20 UTC

This addendum records a fresh audit of the already merged GitHub Pages deliverable and its current operating state. It does **not** claim a new line-by-line audit of every historical implementation: the repository's existing [`REPO_REVIEW.md`](REPO_REVIEW.md), [`VERIFICATION.md`](VERIFICATION.md), and [`COORDINATION.md`](COORDINATION.md) contain the prior file-by-file reviews. This pass independently rechecked the public demo endpoint, deployed pages, build/test gates, current snapshot, and live workflow/deploy metadata.

## Executive outcome

The public site is deployed and the core requirements are represented: five topic categories, ranked open markets, a live desk with price charts and order-book depth, two alert feeds, resolution/results tracking, simulated trades, an executive summary, and a flagged-review page. Automated checks pass when run with the intended fixture directory.

The audit also found **three operational issues that should remain visible for review**:

1. **Snapshot freshness:** at 2026-11-20 19:01 UTC, the root dashboard's `data/live.json` was generated at 18:41:08 UTC (about 20 minutes old). The latest observed successful `kalshi-dashboard.yml` run on `main` was 18:40:59 UTC. Pages had a successful build at 18:53:55 UTC, but that build did not make the root snapshot newer. The 5-minute schedule is best-effort, not a delivery guarantee. The root page does identify itself as a snapshot; do not treat the deployed snapshot as tick-level live data.
2. **Repeated alert rows and non-executable midpoint swings:** the snapshot has 29 alerts but only three distinct tickers; Hunter Biden and Jared Polis each occur 12 times, Amy Klobuchar 5 times, with repeated same-direction/same-price changes. The alert implementation compares midpoints, while observed rows include very wide YES bid/ask spreads (for example, Hunter Biden `$0.002` / `$0.811`, with alert midpoint `$0.4065`). These rows can represent repeated alerts on one sustained move and/or a midpoint change that was not executable at the displayed size. They require deduplication and a consistent, depth-aware executable-price rule before being treated as actionable alerts.
3. **No authenticated demo-account execution:** the deployed ledger is labelled simulated and `live_demo_trading_enabled` is false. No account credentials were available to this session, so live account balances, fills, and order placement remain unverified and are not claimed as complete.

The full audit trail for these items is logged in `COORDINATION.md` as request **R-D-01** for the collector/alert owners; this session did not edit their claimed code or the public flagged page.

## Fresh verification evidence

### Official endpoint and schemas

- Kalshi's official demo-environment page was fetched on 2026-11-20 and confirms the requested recommended REST root `https://external-api.demo.kalshi.co/trade-api/v2`, the supported REST alternative, and both correctly formed WebSocket roots. It also states that demo uses mock funds and demo market behavior may not reflect real markets: [Demo environment](https://docs.kalshi.com/getting_started/demo_env).
- The official market endpoint reference describes `open_interest_fp`, `volume_fp`, `volume_24h_fp`, `notional_value_dollars`, prices, status and result: [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets).
- The official events endpoint documents nested markets and paginated events: [Get Events](https://docs.kalshi.com/api-reference/events/get-events).
- The official order-book reference returns bid levels for YES and NO and fixed-point contract counts: [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook). A fresh response from the recommended demo host for `KXPRESNOMD-28-RW` showed `yes_dollars` and `no_dollars` arrays; this verifies that the dashboard's depth display is grounded in official book levels, not inferred ask-side rows.
- The official candle reference specifies valid periods of 1 minute, 1 hour, or 1 day: [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks).
- The official authenticated-request guide confirms signed requests, headers, timestamp units, and the signing path: [Quick start: authenticated requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests). This only verifies the documented signing method and locally tested adapter; it does not verify live authentication without an account key.

### Live response cross-check

The official demo response for [market `KXPRESNOMD-28-RW`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW), fetched during this audit, returned status `active`, YES bid `$0.0310`, YES ask `$0.0330`, open interest `189,529,515.91`, all-time volume `414,910,564.18`, 24-hour volume `8,018.95`, and notional value `$1.0000` per contract. The corresponding [official order book](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW/orderbook) supplies the resting quantity by price. This independently confirms the displayed field names, while also illustrating that open-interest notional is not the same as recent traded-dollar volume or immediately available liquidity.

### Automated checks run against this checkout

- `python3 -m unittest discover -s tests -v` — **42 passed, 1 skipped**. The skip is the Python signing test because `cryptography` is not installed in this environment; Node auth tests ran separately.
- `npm test` — **18 passed**.
- `python3 -m collector.test_runner` — **passed** (captured/fixture pipeline).
- `python3 -m trading.test_engine` — **passed** (fee schedule, simulated positions, settlement, and analytics).
- `node test/site_smoke.mjs docs/data` — **passed**; index, topic, portfolio, flagged, and summary renderer checks passed, including official API links on market rows.
- `python3 tools/linkcheck.py` — **45 pages, 503 internal links, 0 errors**.
- `python3 -m site_build.build` — **passed**; no generated changes were needed.
- GitHub Pages latest build metadata at audit time: commit `1bc32b745cc2d8f5c7e6261caf05423857d7ef01`, status `built`, created 2026-11-20 18:53:55 UTC. The deployed landing, live desk, summary, and flagged page were fetched successfully at `https://wingbangboozle1-lang.github.io/Trade2/`.

A first smoke-test invocation used root `data/` as a fixture for the different `docs/` renderer and failed on incompatible test data. Rerunning with the renderer's documented fixture directory, `docs/data`, passed; this was a test invocation error, not a reported product regression.

## Scope interpretation and remaining limits

- The dashboard's “highest-dollar” sort is explicitly **open-interest notional** (`open_interest_fp × notional_value_dollars`), not verified traded-dollar volume. Kalshi's API response provides volume in contracts, not a traded-dollar total. Keep that distinction in labels and decisions.
- A high-ROI shortlist is an experimental heuristic. In the observed root snapshot it was empty (0 signals); no positive ROI or predictive performance is established.
- The alert rows include market links but do not establish an external news source as the cause of a price move. Do not infer causality from temporal coincidence.
- Kalshi's demo environment itself is a mock environment; its demo market behavior may not reflect production markets.
- A separate GitHub branch `arena/e4e8f4e1-trade2` had successful collector runs near 18:59 UTC but is not the branch audited here and was not merged into this checkout. Its owner/scope was not listed in the existing coordination registry; this session did not inspect or edit its work.

## Required follow-up

See `COORDINATION.md` request **R-D-01**: the alert-owning session should deduplicate repeated ticker/reference-window alerts, avoid treating wide midpoints as executable swings, surface data freshness prominently, and add the issue to the site's Flagged for Review page. Live demo account operations remain blocked until the account owner supplies demo API credentials through a secure secret channel; credentials must never be committed or placed in the browser.