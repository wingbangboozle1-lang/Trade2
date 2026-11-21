# Verification — session `arena-f3affadb` (2026-11-21)

Independent line-by-line re-verification of the merged tree on branch
`arena/f3affadb-trade2` @ `c264beb`. Every claim below was checked against an
official Kalshi source (docs.kalshi.com, kalshi.com fee schedule, or the live
demo Trade API at `https://external-api.demo.kalshi.co/trade-api/v2`) at the
UTC times shown. Nothing is inferred; anything that could not be confirmed is
left blank/flagged, not filled in.

Branch status at claim time: `arena/f3affadb-trade2` == `origin/main` @
`c264beb` (PR #62 merged). Open PRs from other sessions at claim time: #28,
#29, #59, #60 — their file scopes were respected; this session's scope is the
new verification record below plus the append-only coordination board.

---

## 1. Official endpoints (user-supplied brief vs official docs)

| Claim | Verified value | Official source | Result |
| - | - | - | - |
| Demo REST root | `https://external-api.demo.kalshi.co/trade-api/v2` | [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env) | **Confirmed.** Recommended demo root, verbatim. |
| Demo REST alternative | `https://demo-api.kalshi.co/trade-api/v2` | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments) | **Confirmed.** "Also supported" demo base. |
| Demo WebSocket recommended | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments) + [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) | **Confirmed.** Documented demo WS URL. |
| Demo WebSocket alternative | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [API Environments and Endpoints](https://docs.kalshi.com/getting_started/api_environments) | **Confirmed.** "Also supported" demo WS URL. |
| Brief's bracket form | `wss://[external-api-ws.demo.kalshi.co/trade-api/ws/v2` | — | **Irregular (pre-existing, logged):** the bracket form in the brief is not a valid URL. Canonical forms above confirmed. |
| Demo environment | `https://demo.kalshi.co/`, mock funds, credentials not shared with production | [Test In The Demo Environment](https://docs.kalshi.com/getting_started/demo_env) | **Confirmed.** Warning text: demo prices/behavior may not reflect real markets. |

## 2. Live demo API reachability and exchange state

| Check | Official source | Result |
| - | - | - |
| `GET /exchange/status` (2026-11-21T07:14Z) | [live response](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) | **Confirmed live.** `trading_active: true`; shards: default, "Demo shard 1", "Demo shard 2", one unnamed — all `trading_active: true`, `intra_exchange_transfers_active: true`. |
| Public demo REST responds without auth | same | **Confirmed.** Anonymous GETs returned 200 JSON throughout this session. |

## 3. Orderbook semantics (basis of every price/liquidity figure)

| Claim | Official source | Result |
| - | - | - |
| Book returns bids only; `orderbook_fp.yes_dollars` / `no_dollars`; each level `[price_dollars, count_fp]` as strings | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) | **Confirmed.** Matches `collector/alerts.py`, `assets/desk.js` and the published liquidity ladders. |
| Arrays ascending; best bid = **last** element; NO bid implies YES ask at `1.00 − price` | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) | **Confirmed.** Spread math (`yes_ask = 1 − best_no_bid`) matches the site and `K-03` in the board. |
| Empty book returns `200` with empty arrays (not 404) | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) | **Confirmed live** — see §7. |
| Live pulse design (`GET /markets/orderbooks`, documented cap 100 markets/request) | [Get Multiple Market Orderbooks](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks) | **Confirmed.** The live-pulse panel's source link is the official endpoint reference. |

## 4. Published market rows vs live API

| Published row (site) | Official source | Result |
| - | - | - |
| `KXPRESNOMD-28-RW` — bid $0.0380 / ask $0.0390 / OI 189,529,515.91 | [live GET /markets/KXPRESNOMD-28-RW](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) (2026-11-21T07:15Z) | **Exact.** `yes_bid_dollars 0.0380`, `yes_ask_dollars 0.0390`, `no_bid_dollars 0.9610`, `open_interest_fp 189529515.91`, `notional_value_dollars 1.0000`, `status active`, `close_time 2028-11-07T15:00:00Z`, `price_ranges[0].step 0.0010`. Snapshot volume (414,933,341.41) vs live (414,933,298.61) differs only because volume is cumulative and the snapshot was taken earlier — both are the official field. |
| `KXBTCY-27JAN0100-B47500` — bid $0.0900 / ask $0.1000 / OI $26,578,639.28 | [live GET /markets/KXBTCY-27JAN0100-B47500](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B47500) (2026-11-21T07:16Z) | **Exact** on bid/ask; OI 26,578,809.38 live vs 26,578,639.28 in the 07:09:12Z snapshot (drift of 170 contracts between snapshot and check — both official). Settlement source: CF Benchmarks BRTI (rules text on the live market). |
| `KXAAAGASM-26NOV30-4.70` — no quote shown as UNVERIFIED | [live GET /markets/KXAAAGASM-26NOV30-4.70](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70) | **Confirmed.** Empty book; the site correctly leaves bid/ask blank/UNVERIFIED instead of a phantom mid. |
| Snapshot totals — 750 markets, 150 per topic × 5 | `data/live.json` `events` (generated 2026-11-21T07:09:12Z) | **Consistent.** Topic counts: elections 150, crypto 150, golf 150, culture 150, gas-prices 150. |

## 5. Resolution tracking (yes/no until resolved)

| Claim | Official source | Result |
| - | - | - |
| YES outcome: YES holders receive $1/contract; NO outcome: NO holders $1/contract | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) | **Confirmed.** |
| No settlement fee for simple yes/no | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) | **Confirmed.** |
| `KXAAAGASCDAK-26NOV20-LD` — `result: yes`, `settlement_value_dollars 1.0000`, `settlement_ts 2026-11-20T10:35:14.609488Z`, `status finalized`, settlement source AAA | [live GET /markets/KXAAAGASCDAK-26NOV20-LD](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASCDAK-26NOV20-LD) (2026-11-21T07:15Z) | **Exact.** Matches the published `resolutions.html` row and `data/resolutions.json` row field for field; `rules_primary` names AAA as the settlement source. |
| Resolutions page rows each link to their own official API response | `resolutions.html` (e.g. `…/markets/KXAAAGASCDIL-26NOV20-LD`) | **Confirmed.** Per-row `API ↗` links to `external-api.demo.kalshi.co`. |

## 6. Fees (simulated trading engine)

| Claim | Official source | Result |
| - | - | - |
| Taker fee `round_up(M × 0.07 × C × P × (1−P))`, M default 1 | [Kalshi Fee Schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) (eff. 2026-07-07) | **Confirmed.** Formula verbatim. |
| Maker fee `round_up(M × 0.0175 × C × P × (1−P))`, M default 0 | same | **Confirmed.** |
| No settlement fee, no membership fee | same | **Confirmed.** |
| Table spot-checks (1 contract): $0.50 → $0.02; 100 contracts @ $0.50 → $1.75; $0.01 → $0.01; $0.99 → $0.01 | same table | **Confirmed.** Recomputed by hand from the formula: `0.07×1×0.5×0.5=0.0175→0.02`; `0.07×100×0.5×0.5=1.75`; `0.07×1×0.01×0.99≈0.000693→0.01`. Matches `tests/test_engine.py::TestFees` (42 rows). |
| Non-standard multipliers: `KXBTCY` 0/0, `KXAAAGASM` 1/1 | same table | **Confirmed.** Matches the collector's per-series `fee_multiplier` handling. |

## 7. Flagged irregularities — independent re-check

| Flag | Official source | Result |
| - | - | - |
| `KXPRESNOMD-28-GPLA` "large open interest on an empty book" | [live GET /markets/KXPRESNOMD-28-GPLA/orderbook](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-GPLA/orderbook) (2026-11-21T07:17Z) | **Confirmed.** Live response: `{"orderbook_fp":{"no_dollars":[],"yes_dollars":[]}}` — empty book. The flag is a real Kalshi-side data condition, correctly published on `review.html` with the source link. |
| 48 irregularity rows published on the Flagged page | `review.html` | **Confirmed.** Each row carries an `official API ↗` link to the exact demo endpoint that shows it. |

## 8. Published site (GitHub Pages) — live fetch

| Page | URL | Result (2026-11-21T07:18Z) |
| - | - | - |
| Overview | https://wingbangboozle1-lang.github.io/Trade2/ | **Serves real data.** 750 markets, 5 topics, 328 resolved, ≥$0.10 swing buffer 0, simulated book $9,249.06, per-row `API ↗` links, UNVERIFIED on no-quote rows. |
| Live desk | https://wingbangboozle1-lang.github.io/Trade2/live.html | **Serves.** Two scrolling chats (all events / model shortlist), seconds/minutes/hours chart with YES/NO toggle, bid ladders for liquidity, live-pulse panel, tracked-markets table. |
| Golf category | https://wingbangboozle1-lang.github.io/Trade2/categories/golf.html | **Serves.** 104 series in scope, 150 markets tracked, ranked by OI value, per-row source links. |
| Executive summary | https://wingbangboozle1-lang.github.io/Trade2/summary.html | **Serves.** Official source register table, simulated performance table by strategy, UNVERIFIED where unconfirmed. |
| Flagged for review | https://wingbangboozle1-lang.github.io/Trade2/review.html | **Serves.** 48 irregularity rows with official API links. |
| Resolutions | https://wingbangboozle1-lang.github.io/Trade2/resolutions.html | **Serves.** Settled rows with YES/NO and per-row API links. |

## 9. Local gates (on the merged tree, 2026-11-21T07:19Z)

| Gate | Result |
| - | - |
| `python3 -m unittest discover -s tests` | **261 tests, OK** (skipped 12) |
| `npm test` (Node built-in runner) | **Pass** |
| `python3 -m collector.test_runner` | **PASSED** (7 series / 7 markets / 7 orderbooks / 7 alerts / 1 resolution) |
| `python3 -m trading.test_engine` | **ALL TRADING TESTS PASSED** (fee formula vs 42 official rows, settlement grading, signal rules, stats) |
| `python3 tools/linkcheck.py` | **50 pages, 679 internal links, 0 errors** |
| `python3 -m site_build.build` | **clean exit 0** |
| GitHub Pages status | `built`, source branch `main`, path `/`, public, https enforced |

## 10. Standing limitations (re-confirmed, do not block)

| Item | Official source | Status |
| - | - | - |
| Demo-account portfolio/orders require a demo API key pair (`KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH`); none exist in this repo or session | [API Keys](https://docs.kalshi.com/getting_started/api_keys) + [Quick Start: Authenticated Requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) | **Flagged.** Portfolio/trading pages are labelled SIMULATED; the live-order adapter is inert without credentials. Not fabricated. |
| WebSocket handshake requires authentication at connect time (public ticker channels still use the authenticated session) | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) | **Confirmed.** Explains why the published site uses server-rendered snapshots + anonymous REST polling instead of a browser WS connection. |
| No official source maps news articles to Kalshi price moves | — | **Flagged (pre-existing).** Alerts link to the Kalshi event page; no causal claim is invented. |

## 11. New findings this session

**None.** The merged tree, published rows, and flagged items all re-verified
against official sources with no new defects or irregularities found. The
pre-existing flags (credentials, news attribution, demo-side template text in
official series records) stand unchanged.

## 12. Session record

| Step | Result |
| - | - |
| Branch | `arena/f3affadb-trade2` @ `c264beb` == `origin/main` |
| Files changed | `VERIFICATION-f3affadb.md` (new), `COORDINATION.md` (append-only board section) |
| PR | see `COORDINATION.md` — session section "arena-f3affadb" |
| Merge / Pages | see `COORDINATION.md` |
