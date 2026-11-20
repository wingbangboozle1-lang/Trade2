# COORDINATION.md — Shared Task Board

Repo: `wingbangboozle1-lang/Trade2`
Live site: https://wingbangboozle1-lang.github.io/Trade2/

> This is the shared task board for all parallel agent sessions working on this repo.
> Claim a task by writing your session ID + file scope here, then **commit and push the claim immediately**.
> Never start a task another session has claimed. Keep file scopes non-overlapping.
> Shared outputs (data snapshots, site index & navigation) are changed only by the final integration session.

---

## Sessions

| Session ID | Branch | Notes |
| --- | --- | --- |
| `arena-c0affdd1` | `arena/c0affdd1-trade2` | This session. Owns research, collector, site build, integration, PR + Pages deploy. |

---

## Task board

| # | Task | Status | Owner | File scope |
| --- | --- | --- | --- | --- |
| 1 | Read repo, verify Kalshi demo endpoints + official docs (no hallucinations) | done | `arena-c0affdd1` | `docs/methodology.html`, `analysis/` |
| 2 | Write `COORDINATION.md` task board | done | `arena-c0affdd1` | `COORDINATION.md` |
| 3 | Build live-data collector (Node, public REST, no creds) + topic filter (gas/elections/culture/crypto/golf) | done | `arena-c0affdd1` | `collector/**` |
| 4 | Build swing-alert engine (>= $0.10 move) + alert log with source links | done | `arena-c0affdd1` | `collector/src/alerts.js`, `docs/data/alerts.json` |
| 5 | Build orderbook/liquidity capture + depth table | done | `arena-c0affdd1` | `collector/src/orderbook.js`, `docs/data/liquidity.json` |
| 6 | Build paper-trading engine (strategies, positions, portfolio P&L, resolution tracking) | done | `arena-c0affdd1` | `collector/src/paper.js`, `docs/data/trades.json` |
| 7 | Build signed live-order client (Ed25519 / RSA-PSS per official docs), credential-gated | done | `arena-c0affdd1` | `collector/src/kalshi.js`, `collector/src/live-trade.js` |
| 8 | Build GitHub Actions scheduled collector (data pipeline, no manual input) | done | `arena-c0affdd1` | `.github/workflows/collect.yml` |
| 9 | Build static site: landing + dashboard (2 chats, live charts, liquidity) + per-topic subpages | done | `arena-c0affdd1` | `docs/**` (excl. `docs/data/**`) |
| 10 | Build verification/methodology table (every row has official source link) | done | `arena-c0affdd1` | `docs/methodology.html` |
| 11 | Build "Flagged for Review" page (unverified / irregular items) | done | `arena-c0affdd1` | `docs/flagged.html`, `docs/data/flagged.json` |
| 12 | Executive summary page | done | `arena-c0affdd1` | `docs/index.html`, `analysis/executive-summary.md` |
| 13 | Seed data: run collector via GitHub Actions on branch, commit data snapshot | done | `arena-c0affdd1` | `docs/data/**` |
| 14 | Verify site builds, no broken links, all data rows sourced | done | `arena-c0affdd1` | `docs/**` |
| 15 | Integration: merge branches, re-verify, publish to GitHub Pages, open PR + merge | done | `arena-c0affdd1` | all |

**Status legend:** `unclaimed` · `in progress` · `done` · `needs review`

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
| `GET /markets/{ticker}/orderbook` | https://docs.kalshi.com/api-reference/market/get-market-orderbook |
| `GET /markets/{ticker}/candlesticks` | https://docs.kalshi.com/api-reference/market/get-market-candlesticks |
| `GET /events/{event_ticker}` | https://docs.kalshi.com/api-reference/event/get-events |
| Market lifecycle / settlement | https://docs.kalshi.com/getting_started/market_lifecycle |
| Market settlement | https://docs.kalshi.com/getting_started/market_settlement |
| Orderbook response structure | https://docs.kalshi.com/getting_started/orderbook_responses |
| Fixed-point representation | https://docs.kalshi.com/getting_started/fixed_point_migration |
| Rate limits & tiers | https://docs.kalshi.com/getting_started/rate_limits |
| Demo account setup (mock info allowed, email required) | https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account |
| Exchange status endpoint | https://docs.kalshi.com/api-reference/exchange/get-exchange-status |
| MCP connector (public market tools, OAuth for portfolio) | https://docs.kalshi.com/getting_started/mcp |

---

## Verification log

*(appended by owning session as work completes)*

### 2026-11-20 — session `arena-c0affdd1`
- Repo read: initial commit `e0971c2` only contains a one-line `README.md`. No prior code, no existing site, no CI. Nothing to reconcile.
- `GET https://external-api.demo.kalshi.co/trade-api/v2/exchange/status` → `{"exchange_active":true,...,"trading_active":true}` (verified live).
- `GET /markets?status=open&limit=6` → confirmed demo market schema incl. `last_price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `close_time`, `result`.
- `GET /markets?status=open&limit=1000` returns **newest-created-first**; demo shards generate large volumes of multivariate "combo" markets, so the collector filters with `mve_filter=exclude`.
- `GET /events?category=Crypto&...` → **category filter is ignored by the API** (response returned `category:"World"` events). Collector therefore filters on event/market metadata locally, never trusting a server-side category filter.
- Docs confirm `GET /markets` `limit` maximum is 1000 and paging is cursor-based (`cursor` empty = last page).

### Irregularities / open items (see `docs/flagged.html`)
1. **No Kalshi demo account could be provisioned.** Demo signup (`https://demo.kalshi.co/sign-up`) requires an email inbox that can receive a verification message; no mailbox is available in this environment. Consequence: **live order placement and on-account portfolio reads are implemented and unit-tested against the documented request format but have never been executed against a real Kalshi account** — every execution-path number on the site is from the **simulated (paper) engine**, clearly labelled. Nothing on the site claims a real filled order.
2. **`GET /events` ignores `category`** (see above) — topic classification is done locally from titles/tickers; category strings are recorded as reported by the API and left unedited.
3. **Demo environment content is not identical to production.** Kalshi states demo "price and behavior of markets… may not be reflective of those in real markets" (https://docs.kalshi.com/getting_started/demo_env). Demo tickers observed include demo-only strike names (e.g. `KXNEWPOPE-70`, `KXNEXTNATOSECGEN-99`).
4. **CORS for direct browser → Kalshi REST calls is unconfirmed.** No official statement was found. The site therefore treats the committed snapshot as the source of truth and only upgrades to direct browser polling when the browser permits it; the collector records `access-control-allow-origin` in `docs/data/collector-health.json` so the answer is measured, not guessed.
