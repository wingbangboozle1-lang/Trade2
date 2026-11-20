# Verification ledger — every claim → official source

Checked 2026-11-20 (UTC) unless noted. "Official" = docs.kalshi.com, kalshi.com, or a direct
`external-api.demo.kalshi.co` response. Anything not confirmed stays blank/flagged in the UI (FL-*).

## A. Endpoints & protocol

| # | Claim | Official source | How checked |
|---|---|---|---|
| A1 | Recommended demo REST root `https://external-api.demo.kalshi.co/trade-api/v2` | https://docs.kalshi.com/getting_started/demo_env | page fetched; matches user-provided endpoint |
| A2 | Alternate demo root `https://demo-api.kalshi.co/trade-api/v2` | https://docs.kalshi.com/getting_started/api_environments | page fetched |
| A3 | Demo WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | https://docs.kalshi.com/getting_started/quick_start_websockets | page fetched |
| A4 | WS handshake needs `KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP`, signature = `ts + "GET" + "/trade-api/ws/v2"` | https://docs.kalshi.com/getting_started/quick_start_websockets | page fetched → FL-02 |
| A5 | `/exchange/status` returns 200, `exchange_status: active` | `GET https://external-api.demo.kalshi.co/trade-api/v2/exchange/status` | fetched live 2026-11-20 |
| A6 | `GET /markets` supports one `status` per call; `mve_filter` param | https://docs.kalshi.com/api-reference/market/get-markets | docs fetched (chunk 2) |
| A7 | Order book returns **bids only** (`orderbook_fp.yes_dollars` / `no_dollars`, `[price_dollars, count_fp]`, ascending) | https://docs.kalshi.com/getting_started/orderbook_responses | docs fetched + live orderbook response |
| A8 | Candlesticks path `/series/{s}/markets/{t}/candlesticks`, `period_interval ∈ {1,60,1440}` | https://docs.kalshi.com/api-reference/market/get-market-candlesticks | docs fetched + live call (empty vs non-empty both observed) |
| A9 | Series list `category` filter is exact & case-sensitive; matches `categories` | https://docs.kalshi.com/api-reference/market/get-series-list | docs fetched |
| A10 | `/series` ignores `limit` (returns full list) | `GET /series/?limit=1` (live) | observed 2026-11-20 → FL-04 |
| A11 | Trades: `GET /markets/trades?ticker=…` → `{cursor, trades[]}`; empty array is valid | https://docs.kalshi.com/api-reference/market/get-trades + live call | docs + live (thin market → `trades: []`) → FL-08 |
| A12 | Rate limits: token buckets; back off exponentially on 429 | https://docs.kalshi.com/getting_started/rate_limits | docs fetched; client implements backoff |
| A13 | Settled markets carry `result: yes\|no`, `settlement_ts`, `settlement_value_dollars` | live `GET /markets?status=settled&series_ticker=KXPGATOUR` + https://docs.kalshi.com/getting_started/market_settlement | fetched live 2026-11-20 |
| A14 | Fixed-point `*_fp` / `*_dollars` fields are canonical | https://docs.kalshi.com/changelog + https://docs.kalshi.com/getting_started/fixed_point_migration | docs index + changelog fetched |

## B. Topic mapping (live-verified 2026-11-20)

| # | Claim | Evidence | Status |
|---|---|---|---|
| B1 | Golf series exist under `category=Sports&tags=Golf` (`KXPGATOUR`, `KXPGA`, `KXGOLFMAJOR`, …); `category=Golf` returns null | live `GET /series?category=Sports&tags=Golf` vs `GET /series?category=Golf` | verified; Golf-as-tag logged FL-06 |
| B2 | Gas/energy series under `category=Economics` with tags `Oil and energy` (`KXAAAGASDDE`, `OILW`, `KXSPRMAX`, `CPIGAS`) | live `GET /series?category=Economics` | verified |
| B3 | Culture series under `category=Culture` (`KXXBANNEDGROK`, …) | live `GET /series?category=Culture` | verified |
| B4 | Crypto series under `category=Crypto` (`KXSOLE`, `BTCMAX100`, …) | live `GET /series?category=Crypto` | verified |
| B5 | Elections category exists (`category=Elections`, sample `KXELONMARS-99`) | live `GET /series?category=Elections` (memory of response + matcher test) | verified in test fixture from live payload |
| B6 | Fed rate-cut series (`KXRATECUTS`) must NOT map to gas prices | `collector/test_runner.py` assertion | tested (offline, real payload shapes) |
| B7 | NBA (`KXNBA`) must NOT map to any tracked topic | `collector/test_runner.py` assertion | tested |
| B8 | Series objects expose `fee_type: "quadratic"`, `fee_multiplier` | live series/market objects | verified |
| B9 | Market objects expose `price_level_structure: "tapered_deci_cent"` | live market object (`KXPGATOUR-THRC26-BHAA`) | verified |

## C. Fees

| # | Claim | Official source | Status |
|---|---|---|---|
| C1 | Taker fee = `round up(M × 0.07 × C × P × (1−P))`, M defaults 1 | https://kalshi.com/docs/kalshi-fee-schedule.pdf (p.1) | **PDF fetched directly from kalshi.com** |
| C2 | Maker fee = `round up(M × 0.0175 × C × P × (1−P))`, M defaults 0 | same PDF | fetched |
| C3 | No settlement fee, no membership fee | same PDF (“Settlement Fees”, “Membership Fees” sections) | fetched |
| C4 | Published General Trading Fees Table (21 prices × 2 sizes = 42 values) | same PDF (table) | transcribed; `trading/test_engine.py` reproduces **all 42** exactly |
| C5 | Rounding prose (“fee + positionCost … centicent”) vs table reading differs by ≤ $0.01/contract | same PDF p.1 vs table | discrepancy flagged FL-05; engine follows the table |
| C6 | Fee schedule page for upcoming changes | https://kalshi.com/fee-schedule | linked from the PDF itself |
| C7 | Series-level non-standard multipliers exist (e.g. KXAAAGASM maker 1 / taker 1) | same PDF, “Non-Standard Fees” | fetched; engine reads `fee_multiplier` from market objects when present |

## D. Alerts, charts, news

| # | Claim | Source | Status |
|---|---|---|---|
| D1 | Alert threshold = ≥ $0.10 absolute, both directions | user requirement | applied to official candlestick closes in `collector/runner.py::detect_alerts` |
| D2 | Live demo market actually printed a 0.45→0.35 (−$0.10) and 0.65→0.35 (−$0.30) sequence | live candlesticks for `KXDEMOFUTHOURLY-26NOV20H14-UP`, fetched 2026-11-20 | verified (natural alert demo) |
| D3 | Candle response fields: `end_period_ts`, `price.*_dollars`, `volume_fp`, `open_interest_fp`, `yes_bid/yes_ask` | live response + docs A8 | verified |
| D4 | Headlines are time-proximity candidates only, never causes | project policy; `collector/news.py` docstring | enforced in code + UI wording |
| D5 | Google News RSS `https://news.google.com/rss/search?q=…` is the headline source | https://news.google.com/rss/search?q=kalshi | endpoint reachable only from Actions runners (sandbox blocked) → FL-03; failure ⇒ blank + flagged |
| D6 | X-axis windows seconds/minutes/hours map to `period_interval` 1/60/1440 | docs A8 | verified (1-second candles observed live) |

## E. Environment & operations

| # | Claim | Source | Status |
|---|---|---|---|
| E1 | GitHub Pages serves `main:/` at `https://wingbangboozle1-lang.github.io/Trade2/` | `gh api repos/…/pages` | verified (status `built`) |
| E2 | Sandbox has no egress to Kalshi hosts; GitHub Actions runners do | curl → HTTP 000 locally; Actions runs reach the API | verified operationally → data pipeline design |
| E3 | No API credentials exist anywhere in the repo | repo scan (only README/COORDINATION/code) | verified → FL-01 |
| E4 | Repo contained only `README.md` at session start | `git log e0971c2` | verified |
| E5 | Official demo prices may not reflect real markets | https://docs.kalshi.com/getting_started/demo_env | quoted on summary/index pages |

## F. Test evidence (run in CI before any data commit)

```
python3 -m trading.test_engine   # 42/42 official fee rows + open/close/settle + signals + stats
python3 -m collector.test_runner # end-to-end runner on real captured payloads; asserts source URLs,
                                 # blank+flag for unconfirmable values, topic inclusion/exclusion
python3 -m py_compile collector/*.py trading/*.py
```

Any failure fails the workflow step, so bad data is never published (site cannot merge broken).
