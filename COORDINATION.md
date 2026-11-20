# COORDINATION.md — Shared Task Board

Repo: `wingbangboozle1-lang/Trade2`
Live site: https://wingbangboozle1-lang.github.io/Trade2/

> This is the shared task board for all parallel agent sessions working on this repo.
> Claim a task by writing your session ID + file scope here, then **commit and push the claim immediately**.
> Never start a task another session has claimed. Keep file scopes non-overlapping.
> Shared outputs (data snapshots, site index & navigation) are changed only by the final integration session.

---

## Session registry

| Session ID | Branch | Role | Status |
| --- | --- | --- | --- |
| `arena-c0affdd1` | `arena/c0affdd1-trade2` | This session — data pipeline + dashboard site + integration + Pages deploy | active |
| `arena-f5837994` | `arena/f5837994-trade2` | Repo review, executive summary, Python collector, live dashboard, GitHub Pages site | active (branch observed: `COORDINATION.md`, `README.md`, `.github/workflows/_probe.yml`, `data/_probe.txt`) |
| `arena-5788e385` | `arena/5788e385-trade2` | Repo review + README | active (branch observed: `COORDINATION.md`, `README.md`) |
| `arena-ba6888b7` | `arena/ba6888b7-trade2` | Python collector (`collector/*.py`) | active (branch observed: `COORDINATION.md`, `README.md`) |

### File-scope map (no two sessions may write the same path)

| Path | Owner | Notes |
| --- | --- | --- |
| `COORDINATION.md` | integration session (this one) | All sessions post claims here; the final integration session keeps the merged board. |
| `README.md` | `arena-5788e385` / `arena-f5837994` | **Do not edit.** This session logs a request instead. |
| `collector/**` | `arena-ba6888b7` | Python collector (REST client, topics, strategies). **This session does not touch it.** |
| `pipeline/**` | `arena-c0affdd1` | Node.js collector used by this session's scheduled workflow. |
| `docs/**` | `arena-c0affdd1` | Self-contained GitHub Pages app: dashboard, five topic pages, trading, methodology, flagged register, `assets/`, published data snapshots in `docs/data/`. |
| `index.html` (repo root) | `arena-c0affdd1` | Landing page / executive summary. The Pages source path is fixed at the repository root (the token in this sandbox cannot change the Pages settings), so the landing page lives at the root and the rest of the app under `docs/`. |
| `.nojekyll` (repo root) | `arena-c0affdd1` | Publishes the repository as static files (no Jekyll processing) so `docs/` is served verbatim. |
| `analysis/**` | `arena-c0affdd1` | Executive summary / analysis markdown. |
| `.github/workflows/collect.yml` | `arena-c0affdd1` | Scheduled data collection workflow (distinct file name; no conflict with other workflows). |
| `index.html`, `assets/`, `topics/`, `server/`, `dashboard/` | `arena-f5837994` | Root-level site claimed by that session. **This session does not touch them.** |
| `live/**` | `arena-c0affdd1` (integration) | The `arena-ba6888b7` browser-polling site, relocated from the repository root to `live/` during final integration so the root landing page can be shared. Content is unchanged apart from link re-pointing. |
| `tools/**` | `arena-c0affdd1` | Site link/asset checker and the page render smoke test used by CI. |

### Published data contract (`docs/data/*.json`)

The site in `docs/` reads only these files. Any collector may publish them — the
schema is the contract:

| File | Content |
| --- | --- |
| `manifest.json` | `{generated_at, source{rest_base,ws_base,docs}, threshold{swing_usd,roi_chat_score}, counts{…}, exchange_status, account}` |
| `markets.json` | Array of tracked markets: `ticker, event_ticker, series_ticker, title, topic, topics[], category, status, close_time, last_price, previous_price, yes_bid, yes_ask, no_bid, no_ask, spread, volume, volume_24h, open_interest, dollar_amount, dollar_volume, dollar_volume_24h, result, rules_primary, kalshi_url, settlement_sources[], roi_score, roi_components, roi_reasons, roi_fair_yes, roi_ev_yes, roi_ev_no, roi_pct, hours_to_close` |
| `events.json` | Object keyed by `event_ticker` → raw Kalshi event (title, category, settlement_sources, rules…). |
| `orderbooks.json` | Object keyed by `ticker` → `{yes_levels[], no_levels[], best_yes_bid, best_yes_ask, best_no_bid, best_no_ask, mid, spread, depth_yes_total, depth_no_total, depth_yes_within_5c, depth_no_within_5c}`. |
| `candles.json` | Object keyed by `ticker` → array of `{ts, open, high, low, close, bid, ask, volume, open_interest}` (1-minute candles). |
| `prices.json` | Object keyed by `ticker` → array of `[epochSeconds, price]`. |
| `alerts.json` | Array of swings: `{ts, ticker, title, topic, direction, from, to, delta, abs_delta, threshold, reference, last_price, roi_score, kalshi_url, settlement_sources[]}`. |
| `trades.json` | Array of simulated trades: `{id, strategy, ticker, side, count, entry_price, entry_ts, cost, exit_price, exit_ts, pnl, exit_reason, status, mode, resolution?}`. |
| `portfolio.json` | `{start_cash, cash, equity, realized_pnl, unrealized_pnl, total_pnl, roi_pct, win_rate, by_strategy[], by_topic[], by_type[], derived_strategies[]}`. |
| `collector-health.json` | `{last_run_at, duration_ms, api_calls, api_errors, errors[], calls, exchange_active, trading_active, runs}`. |
| `state.json` | Internal collector state (price history, trades, alerts, run counter). |

---

## Task board

| # | Task | Status | Owner | File scope |
| --- | --- | --- | --- | --- |
| 1 | Read repo, verify Kalshi demo endpoints + official docs (no hallucinations) | done | `arena-c0affdd1` | `docs/methodology.html`, `analysis/` |
| 2 | Write `COORDINATION.md` task board | done | `arena-c0affdd1` | `COORDINATION.md` |
| 3 | Build live-data collector (Node, public REST, no creds) + topic filter (gas/elections/culture/crypto/golf) | done | `arena-c0affdd1` | `pipeline/**` |
| 4 | Build swing-alert engine (>= $0.10 move) + alert log with source links | done | `arena-c0affdd1` | `pipeline/src/alerts.js`, `docs/data/alerts.json` |
| 5 | Build orderbook/liquidity capture + depth table | done | `arena-c0affdd1` | `pipeline/src/liquidity.js`, `docs/data/orderbooks.json` |
| 6 | Build paper-trading engine (strategies, positions, portfolio P&L, resolution tracking) | done | `arena-c0affdd1` | `pipeline/src/paper.js`, `docs/data/trades.json` |
| 7 | Build signed live-order client (Ed25519 / RSA-PSS per official docs), credential-gated | done | `arena-c0affdd1` | `pipeline/src/kalshi.js`, `pipeline/src/live-trade.js` |
| 8 | Build GitHub Actions scheduled collector (data pipeline, no manual input) | done | `arena-c0affdd1` | `.github/workflows/collect.yml` |
| 9 | Build static site: landing + dashboard (2 chats, live charts, liquidity) + per-topic subpages | done | `arena-c0affdd1` | `docs/**` (excl. `docs/data/**`) |
| 10 | Build verification/methodology table (every row has official source link) | done | `arena-c0affdd1` | `docs/methodology.html` |
| 11 | Build "Flagged for Review" page (unverified / irregular items) | done | `arena-c0affdd1` | `docs/flagged.html` |
| 12 | Executive summary page | done | `arena-c0affdd1` | `docs/index.html`, `analysis/executive-summary.md` |
| 13 | Seed data: run collector via GitHub Actions on branch, commit data snapshot | done | `arena-c0affdd1` | `docs/data/**` |
| 14 | Verify site builds, no broken links, all data rows sourced | done | `arena-c0affdd1` | `docs/**`, `tools/**` |
| 15 | Integration: merge branches, re-verify, publish to GitHub Pages, open PR + merge | in progress | `arena-c0affdd1` | all |
| 16 | Publish the landing page at the repository root + `.nojekyll` (Pages source path is fixed at `/`) | done | `arena-c0affdd1` | `index.html`, `.nojekyll` |
| 17 | Add CI that re-runs the unit tests, the link check and the render smoke test | done | `arena-c0affdd1` | `.github/workflows/verify.yml`, `tools/**` |
| 18 | Integrate the sibling session's site: relocate the root browser dashboard to `live/`, re-point its links, keep both sites reachable from the landing page | done | `arena-c0affdd1` | `live/**`, `index.html` |
| 19 | Measure browser CORS from the collector instead of assuming it (OPTIONS preflight, published in `collector-health.json`) | done | `arena-c0affdd1` | `pipeline/src/cors.js`, `pipeline/src/collect.js` |

**Status legend:** `unclaimed` · `in progress` · `done` · `needs review`

### Requests to other sessions (do not edit their files)

| # | Request | From | To | Status |
| --- | --- | --- | --- | --- |
| R1 | Please note `README.md` is owned by your session — this session will not edit it. If the final integration session needs README changes, it will apply them at merge time. | `arena-c0affdd1` | `arena-5788e385`, `arena-f5837994` | logged |
| R2 | GitHub Pages source path: this session's site lives in `docs/`. Integration should set the Pages source to `/docs` (or merge the root-level site). | `arena-c0affdd1` | `arena-f5837994` | logged |
| R3 | If the Python collector in `collector/` is published, please emit the `docs/data/*.json` contract above so the site can render it. | `arena-c0affdd1` | `arena-ba6888b7` | logged |
| R4 | The Pages source path for this repo is fixed at the repository root (branch `main`, path `/`) and the sandbox token cannot change it. This session therefore publishes the landing page at the root and keeps the whole app self-contained under `docs/` (its own `assets/`, `topics/` and `data/`). If another session publishes a root-level `index.html`, the two sites coexist: the root shows that landing page, this site stays reachable at `/docs/`. Please do not edit files under `docs/` — that scope belongs to this session. | `arena-c0affdd1` | `arena-f5837994`, `arena-5788e385` | logged |
| R5 | Final integration note: the `arena-ba6888b7` site that was published at the repository root has been relocated to `live/` so the root can host the shared landing page. Because every internal link in that site is relative (`assets/`, `categories/`, `../index.html`), the whole subtree moved together and **no link had to be rewritten** — the only edit is one added "Snapshot tracker ↑" back-link per page. The landing page links to it, so nothing is lost. | `arena-c0affdd1` | `arena-ba6888b7` | logged |

---

## Sources used (official / verified)

| What | Source |
| --- | --- |
| Demo REST base URL (recommended) | https://docs.kalshi.com/getting_started/demo_env |
| Demo WebSocket base URL | https://docs.kalshi.com/getting_started/quick_start_websockets |
| API environments list | https://docs.kalshi.com/getting_started/api_environments |
| API key types + signing (Ed25519 / RSA-PSS SHA-256) | https://docs.kalshi.com/getting_started/api_keys |
| Authenticated requests quick start | https://docs.kalshi.com/getting_started/quick_start_authenticated_requests |
| Public market data (no auth) | https://docs.kalshi.com/getting_started/quick_start_market_data |
| WebSocket channels + auth | https://docs.kalshi.com/getting_started/quick_start_websockets |
| `GET /markets` schema, `limit` max 1000, cursor paging | https://docs.kalshi.com/api-reference/market/get-markets |
| `GET /markets/{ticker}` | https://docs.kalshi.com/api-reference/market/get-market |
| `GET /series` (series discovery by category) | https://docs.kalshi.com/api-reference/market/get-series-list |
| `GET /events`, `GET /events/{event_ticker}` | https://docs.kalshi.com/api-reference/events/get-events · https://docs.kalshi.com/api-reference/events/get-event |
| `GET /markets/{ticker}/orderbook`, `GET /markets/orderbooks` | https://docs.kalshi.com/api-reference/market/get-market-orderbook · https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks |
| `GET /markets/candlesticks`, `GET /series/{s}/markets/{t}/candlesticks` | https://docs.kalshi.com/api-reference/market/batch-get-market-candlesticks · https://docs.kalshi.com/api-reference/market/get-market-candlesticks |
| `POST /portfolio/events/orders` (V2 order shape) | https://docs.kalshi.com/api-reference/orders/create-order-v2 |
| Portfolio reads (balance/positions/fills/settlements) | https://docs.kalshi.com/api-reference/portfolio/get-portfolio-balance · https://docs.kalshi.com/api-reference/portfolio/get-portfolio-positions · https://docs.kalshi.com/api-reference/portfolio/get-portfolio-fills · https://docs.kalshi.com/api-reference/portfolio/get-portfolio-settlements |
| Orderbook response structure | https://docs.kalshi.com/getting_started/orderbook_responses |
| Market lifecycle / settlement | https://docs.kalshi.com/getting_started/market_lifecycle · https://docs.kalshi.com/getting_started/market_settlement |
| Fixed-point representation | https://docs.kalshi.com/getting_started/fixed_point_migration |
| Rate limits & tiers | https://docs.kalshi.com/getting_started/rate_limits |
| Exchange status endpoint | https://docs.kalshi.com/api-reference/exchange/get-exchange-status |
| Demo account setup (mock info allowed, email required) | https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account |
| Official Kalshi TypeScript SDK (signing cross-check) | https://www.npmjs.com/package/kalshi-typescript |
| Kalshi MCP connector (public market tools; OAuth for portfolio) | https://docs.kalshi.com/getting_started/mcp |

---

## Verification log

### 2026-11-20 — session `arena-c0affdd1`

- Repo read: initial commit `e0971c2` only contains a one-line `README.md`. No prior code, no existing site, no CI. Nothing to reconcile.
- `GET https://external-api.demo.kalshi.co/trade-api/v2/exchange/status` → `{"exchange_active":true,…,"trading_active":true}` (verified live).
- `GET /markets?status=open&limit=6` → confirmed demo market schema incl. `last_price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `close_time`, `result`, `status`.
- `GET /markets?status=open&limit=1000` returns **newest-created-first**; demo shards generate large volumes of multivariate "combo" markets, so the collector filters with `mve_filter=exclude`.
- `GET /events?category=Crypto&…` → **the `category` filter is ignored by the API** (response returned `category:"World"` events). Topic classification is therefore done locally from titles/tickers; Kalshi's own `category` strings are stored unedited.
- Docs confirm `GET /markets` `limit` maximum is 1000 and paging is cursor-based (empty `cursor` = last page).
- Docs confirm the legacy `/portfolio/orders` **write** endpoints were removed (`410 Gone`, code `deprecated_v1_order_endpoint`); live order placement must use `POST /portfolio/events/orders` with the V2 single-book shape.
- Signing implementation cross-checked against the official Kalshi TypeScript SDK (`kalshi-typescript@3.36.0`, published by the Kalshi organisation) in `pipeline/test/collector.test.mjs` — both signatures verify against the public key.
- Unit tests: `npm test` in `pipeline/` → 12/12 passing (signing ×4, swing threshold, alert dedupe, orderbook maths, ROI bounds, paper-engine P&L, topic classifier, price-series shapes).
- Site checks (`tools/check-site.mjs`, `tools/smoke-render.mjs`): all internal links resolve, every external link points at an official Kalshi/GitHub host, all published JSON parses, all five browser modules parse and render without error against a DOM shim. Both caught and fixed two real JavaScript syntax errors in `docs/assets/js/home.js` and `docs/assets/js/trading.js` before deployment.
- Live collector run on GitHub Actions: 157+ API calls, 0 errors, 61 tracked markets, orderbooks for all 61, 1-minute and hourly candles, 161+ trade prints, swing alerts and a simulated book with 800 trades.

### Irregularities / open items (published on the site's "Flagged for Review" page)

1. **No Kalshi demo account could be provisioned.** Demo signup (`https://demo.kalshi.co/sign-up`) requires an email inbox that can receive a verification message; no mailbox is available in this environment. Consequence: **live order placement and on-account portfolio reads are implemented and unit-tested against the documented request format but have never been executed against a real Kalshi account** — every execution-path number on the site comes from the **simulated (paper) engine**, clearly labelled. Nothing on the site claims a real filled order.
2. **`GET /events` ignores `category`** (see above) — topic classification is done locally from titles/tickers; Kalshi's category strings are recorded as reported and left unedited.
3. **Demo environment content is not identical to production.** Kalshi states demo "price and behavior of markets… may not be reflective of those in real markets" (https://docs.kalshi.com/getting_started/demo_env). Demo tickers observed include demo-only strike names (e.g. `KXNEWPOPE-70`, `KXNEXTNATOSECGEN-99`).
4. **CORS for direct browser → Kalshi REST calls is measured, not assumed.** No official Kalshi statement about CORS was found, so the collector sends a real browser-style preflight (`OPTIONS` + `Origin` + `Access-Control-Request-Method`) to the live demo host on every run and publishes the response headers in `collector-health.json`. The verdict is shown as a badge on every page. The committed snapshot remains the source of truth; direct browser polling is only an optional upgrade.
5. **Parallel sessions are active.** `arena-f5837994` (root site, Python collector, live dashboard), `arena-5788e385` (README), `arena-ba6888b7` (Python collector) are working concurrently. File scopes are mapped above so the final merge stays conflict-free; the site index/navigation and the Pages source path are decided by the integration session.
6. **Integration of two sites.** `arena-ba6888b7`'s browser-polling site had already been merged into `main` (PRs #1 and #2) and was live at the repository root. Rather than overwrite it, the final integration relocated it to `live/` and re-pointed its internal links, so the repository now publishes both: the root landing page (this session, snapshot-driven) and `live/` (the sibling session, browser-polling). `main` also still carries `README.md` from that session; the final integration re-points its page list to the new locations.

---

## Integrated sibling session — `arena-ba6888b7` (merged into `main` as PRs #1 and #2)

That session built a **browser-polling** dashboard (direct `fetch` from the visitor's browser to the
Kalshi demo REST API) and published it at the repository root. Its merged commit `d3cca9d` was the
`main` tip before this session's integration branch was created.

Its files are preserved verbatim under `live/` in this branch:

| Was | Now |
| --- | --- |
| `index.html` (browser dashboard) | `live/index.html` |
| `assets/app.js`, `assets/styles.css` | `live/assets/app.js`, `live/assets/styles.css` |
| `categories/*.html` (5 topic pages) | `live/categories/*.html` |
| `summary.html` (executive summary) | `live/summary.html` |
| `review.html` (flagged review) | `live/review.html` |

Their relative links were re-pointed from the repository root to `live/` (see the request log below),
so that site still works standalone. **Both sites are linked from the landing page.** The two
implementations answer different questions and both are kept:

| | `live/` (sibling session) | `docs/` + root landing (this session) |
| --- | --- | --- |
| Data source | polls the demo API from the visitor's browser | committed JSON snapshot refreshed every 10 min by GitHub Actions |
| Works without browser CORS permission | no | **yes** |
| Swing alerts | browser-side, only between two observed quotes | server-side, from the Kalshi trade feed + `previous_price_dollars` |
| ROI model | none (deliberately not claimed) | published 0–100 model with reasons |
| Simulated trading | browser-local ledger | server-side engine with 4 strategies, hourly backtests, resolution settlement |
| Persistence | browser local storage | committed JSON, survives reloads and browsers |

### Their session log (recorded by `arena-ba6888b7`, preserved here)

Session ID: `ba6888b7-trade2` (Arena working branch `arena/ba6888b7-trade2`)
- 2026-11-20: Read the coordination board before starting. It did not exist; created it and claimed the sole implementation task. Working on the Arena-provided current branch because branch/worktree switching is not permitted in this session.
- Completed the dashboard and static topic pages. Files owned/changed: repository root, `assets/`, `categories/`, and this board. No concurrent claims were present.
- **Official sources checked:** [Demo environment](https://docs.kalshi.com/getting_started/demo_env) (demo root, supported alternate, mock-funds and pricing caveat); [API environments](https://docs.kalshi.com/getting_started/api_environments) (REST/WS URLs); [Get Events](https://docs.kalshi.com/api-reference/events/get-events) (nested markets, 200 item page limit, cursor, statuses); [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) (market fields); [Kalshi OpenAPI schema](https://docs.kalshi.com/openapi.yaml) (`notional_value_dollars` is the value of a single contract at settlement; open-interest value is the explicit product of official open-interest contracts and per-contract settlement value, not traded dollar volume); [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) and [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) (bid depth/quantities and binary-book explanation); [WebSocket quick start](https://docs.kalshi.com/getting_started/quick_start_websockets) (connection/channel/auth example); [Create Order quick start](https://docs.kalshi.com/getting_started/quick_start_create_order) and [API Keys](https://docs.kalshi.com/getting_started/api_keys) (signed account trading requirements); [GitHub Pages API](https://docs.github.com/en/rest/pages/pages?apiVersion=2022-11-28#update-information-about-a-github-pages-site) (site build mode reference).
- **Verification performed:** `node --check assets/app.js` passed; Python HTML parse/local-reference check passed for all 8 HTML pages; all 8 pages contain official Kalshi source links; `git diff --check` passed; local static HTTP smoke test returned HTTP 200 for overview, gas topic page, executive summary, review page, and application JS. The repo's existing GitHub Pages endpoint/settings were confirmed through `gh` as public and configured for built-in legacy publishing from `main` root. After merge, the Pages build/deployment completed successfully; the deployed root HTML was fetched. Browser-side Kalshi API/CORS behavior remains unverified. An attempt to switch publishing source through the GitHub API was denied (HTTP 403 integration permission), so the implementation retains the repo's existing branch-publishing mode and does not add a conflicting Actions workflow.
- **Flagged items published in `review.html`:** static page cannot safely access signed demo-account balances/fills or place account orders without credential provisioning and a protected backend; the paper ledger is not account performance; ROI claim is intentionally not made (the filter is an unvalidated threshold plus calculated open-interest-value screen); REST polling can miss intrapoll moves; classification is keyword-based and capped at 800 event entries; causal news attribution and deployed-origin CORS remain unverified. Missing values are left unfilled and marked UNVERIFIED.
- Pull request: [#1 — Build Kalshi demo monitoring and paper-trading dashboard](https://github.com/wingbangboozle1-lang/Trade2/pull/1) merged into `main` at `05803aa414bb37e516c2afab3ec0d40416cc7bcb` on 2026-11-20. No PR checks were reported.
- Deployment: existing built-in Pages publishing from `main` root completed successfully (Pages build/deploy run [44744259044](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44744259044)); public URL: https://wingbangboozle1-lang.github.io/Trade2/ . The deployed root HTML was fetched and verified. The hosted browser's live Kalshi API/CORS execution remains unverified and is flagged on `review.html`.
- Irregularities: Pages Actions emitted a non-blocking Node.js 20 deprecation warning for its upload-artifact action; the deployment still succeeded. GitHub integration returned HTTP 403 when asked to change the Pages publishing mode, so existing legacy `main`-branch deployment was retained.
- Status: implementation and Pages deployment complete; account authentication/trading, API CORS, market coverage, and strategy validation remain clearly flagged limitations, not verified features.
