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

- Source of truth: official candlestick closes (`price.close_dollars`), shortest available window (seconds, fallback minutes).
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

## 8. How to review manually

- Live site: https://wingbangboozle1-lang.github.io/Trade2/
- Raw data written by each run: `docs/data/*.json` (every object carries `source_url`)
- Verification ledger: `docs/verification/sources.md`
- Task board / PR record: `COORDINATION.md`
- Reproduce any row: open its `source_url` — it is a GET on the public demo API, no key needed.
