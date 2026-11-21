# VERIFICATION-3dcf3f13 — independent check, 2026-11-21

Session `arena-3dcf3f13` · branch `arena/3dcf3f13-trade2` · base `main` @ `06738d1`
Scope: claims X1–X3 in `COORDINATION.md`. This file records what was checked, against which official
URL, at what UTC time, and what the result was. Anything that could not be confirmed is marked
**UNVERIFIED**, not filled in.

## 0. Method and reachability

| Path | Result | Time (UTC) |
| - | - | - |
| `bash` → `https://external-api.demo.kalshi.co/trade-api/v2/exchange/status` | **Not reachable from the sandbox shell** (`curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL`, HTTP 000). Same finding as earlier sessions (I3 in `COORDINATION.md`). | 2026-11-21T06:45:39Z |
| Platform fetch tool → the same Kalshi demo URLs | **Reachable.** Used for every live value below. Each fetch is listed with its URL. | 06:4x–06:5x Z |
| Official Kalshi docs (`docs.kalshi.com`) | Read through the fetch tool. Quoted fields are copied from those pages. | 06:5x Z |

Timing: the fetch tool does not return a per-call timestamp. The times written as `06:4x`/`06:5x Z` are the sandbox clock for that batch of calls (approximate, within about 10 minutes, all between 06:40Z and 07:00Z on 2026-11-21). Live numbers below were read from the API at those times. Published numbers come from the
repository files named in each row. Live values move, so a mismatch in a *price* is only a finding when
the field is one that should not move (identity, settlement result, settlement time, the set of
settled markets).

## 1. Checks performed

| # | Check | Official source (exact URL) | Published value (file) | Live value (time) | Result |
| - | - | - | - | - | - |
| C1 | Exchange trading status | `https://external-api.demo.kalshi.co/trade-api/v2/exchange/status` ([docs](https://docs.kalshi.com/api-reference/exchange/get-exchange-status)) | `trading_active: true`, 4 indexes (`docs/data/run_meta.json`) | `exchange_active: true`, `trading_active: true`, 4 indexes (06:4x Z) | **MATCH** |
| C2 | Market identity and quote, `KXAAAGASW-26NOV23-3.6600` | `https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6600` ([docs](https://docs.kalshi.com/api-reference/market/get-market)) | last 0.02, bid 0.0, ask 1.0, OI 26934.78, volume 37250.81 (`docs/data/markets.json`) | last 0.0200, bid 0.0000, ask 1.0000, OI 26934.78, volume 37250.81 (06:5x Z) | **MATCH** on all five fields. See irregularity I-2 (ask 1.00 with size 0.00). |
| C3 | Dollar-volume proxy `notional_usd` for C2 | Derived by our code (24 h volume × last price). Inputs: C2 URL. | published **54.11** | recomputed from current inputs = 2569.96 × 0.0200 = **51.40** | **UNVERIFIED.** The price used at snapshot time is not stored, so 54.11 cannot be reproduced from the file. See I-6. |
| C4 | Settlement of `KXDOGE-26NOV2100-T0.2349999` | `https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDOGE-26NOV2100-T0.2349999` ([docs](https://docs.kalshi.com/getting_started/market_settlement)) | result `no`, settlement value 0.0, settlement_ts `2026-11-21T06:03:37.961447Z` (`docs/data/resolutions.json`) | `result: "no"`, `settlement_value_dollars: "0.0000"`, `settlement_ts: "2026-11-21T06:03:37.961447Z"`, status `finalized` (06:5x Z) | **MATCH** |
| C5 | Settled markets in the golf, culture, elections and gas topics | `https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled&series_ticker=KXDPWORLDTOUR&limit=5` (also `KXBIGBROTHER`, `KXCAGOVPRIMARY1ST`, `KXAAAGASD`) | **0 rows** for these topics; **0 `yes` rows** in the whole file (`docs/data/resolutions.json`) | `KXDPWORLDTOUR-DPWTC26-THAT` → `result: "yes"`, settlement 2026-11-15T14:56:17.490048Z; `KXBIGBROTHER-26DEC31-RIC` → `"yes"`, 2026-10-02T04:20:30.143779Z; `KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC` → `"yes"`, 2026-07-11T00:45:14.689883Z; `KXAAAGASD-26NOV20-3.7600` → `"no"`, 2026-11-20T13:14:49.617968Z (06:4x Z) | **MISMATCH — defect.** Cause and fix: X1 (`collector/runner.py`). |
| C6 | Golf swing alert `KXPGATOUR-THRC26-MTHO` (published 0.17 → 0.39 at `t=1795241520`, 06:12:00Z, delta +0.22) | `https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/markets/KXPGATOUR-THRC26-MTHO/candlesticks?start_ts=1795238665&end_ts=1795242265&period_interval=1` ([docs](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)) | alert in `docs/data/alerts.json` | 1-minute candle `end_period_ts 1795241520`: open 0.17, **high 0.39, low 0.17, close 0.39**, volume 10.98. Next candle `end_period_ts 1795241580`: open 0.17, previous 0.39, **close 0.17**, volume 3.18 (06:4x Z) | **CONFIRMED, with a caveat.** The spike is real in the API, but it lasted one minute and the next candle closed back at 0.17. The alert does not say so. See I-3. |
| C7 | Alert delta arithmetic | — | delta 0.22 = 0.39 − 0.17 | — | **MATCH** |
| C8 | Simulated equity shown on the two published sites | No external source (simulated ledger). Compared with itself. | root `data/live.json`: equity **9,205.84** (generated 2026-11-21T06:28:00Z, 8 open); `docs/data/portfolio.json`: equity **11,549.01** (8 open, 5 closed trades); `data/portfolio_state.json`: bankroll **8,277.59** | — | **INCONSISTENT** across three files. See I-4. |
| C9 | Count of resolved events | No external source. Compared with itself. | root `data/live.json` `resolutions_count` = **328**; `docs/data/resolutions.json` = **300** | — | **INCONSISTENT.** See I-4. |
| C10 | Topic coverage of the root pipeline's resolutions | Same settled-market endpoints as C5 | `data/resolutions.json`: 328 rows; gas-prices 268, crypto 60, **elections 0, culture 0, golf 0**; yes 80, no 248 | — | **MISMATCH.** See I-5 and request R-3DCF-1. |
| C11 | Candlestick `period_interval` values | `https://docs.kalshi.com/api-reference/market/get-market-candlesticks` (page description: "Time period length of each candlestick in minutes. Valid values: 1 (1 minute), 60 (1 hour), 1440 (1 day).") | UI labels a **"seconds"** window (`collector/runner.py` builds it from 1-minute candles) | — | **MISMATCH.** No second-level candles exist in the API. See I-7. |
| C12 | Portfolio and balance endpoints need credentials | `https://docs.kalshi.com/api-reference/portfolio/get-balance` — required headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP`; 401 without them | site labels the portfolio "simulated" (FL-01) | — | **CONFIRMED.** A real demo-account portfolio cannot be shown without a key pair. Blocker B-1. |
| C13 | `min_settled_ts` filter (used by the X1 fix) | `https://docs.kalshi.com/api-reference/market/get-markets` — "min_settled_ts: Filter items that settled after this Unix timestamp". Live check: `…/markets?status=settled&series_ticker=KXDPWORLDTOUR&limit=200&mve_filter=exclude&min_settled_ts=1792651800` returned the `KXDPWORLDTOUR-DPWTC26-*` settled rows from 2026-11-15, including `-THAT` `yes`. A 30-day window on `KXBIGBROTHER` (last settled 2026-10-02) returned an empty list. | — | — | **CONFIRMED** (parameter accepted and filters by time). |

## 2. Irregularities (flagged; published on `docs/flagged.html` as FL-10 onward)

| ID | Irregularity | Status |
| - | - | - |
| I-1 | `docs/data/resolutions.json` contains only crypto (DOGE) rows, all `no`, from the last ~3 hours. Golf, culture, elections and gas have no rows, and no `yes` appears anywhere. Causes: the same first-N series per topic every run (rotation promised in a code comment but not implemented); a global newest-300 cut that let crypto fill the file; no accumulation across runs. | **Fixed in code on this branch (X1).** The published file changes only when the scheduled collector runs after merge. |
| I-2 | Quote-only ask: `yes_ask_dollars 1.0000` with `yes_ask_size_fp 0.00` on `KXAAAGASW-26NOV23-3.6600` (live, 06:5x Z). The published table shows the ask as 1.00 with no flag. A 1.00 ask with zero size is a placeholder, not a fill price. | Open. Request R-3DCF-2 to the owner of the market table. |
| I-3 | Swing alert shows the spike, not the reversion (C6). | Open. Request R-3DCF-3 to the owner of alerts. |
| I-4 | Three different simulated-equity figures and two different resolved counts across the published pipelines (C8, C9). The site does not say which pipeline a number comes from, so a reader may compare them. | Open. Recommend one pipeline per site. Request R-3DCF-4. |
| I-5 | The root pipeline's resolutions have no elections, culture or golf rows (C10). Its settlement scan (`collector/collector.py`, `settle_scan`) is exchange-wide and not per topic. | Open. Request R-3DCF-1. |
| I-6 | `notional_usd` is derived from the last price at snapshot time, which is not stored. The figure cannot be reproduced from the file (C3). | Open. Request R-3DCF-5: store the price used. |
| I-7 | The chart's "seconds" window is a 1-hour view of 1-minute candles. Kalshi's candlestick periods are 1 minute, 1 hour or 1 day (C11). The label overstates the resolution. | Open. Request R-3DCF-6: relabel as "1-min candles". |
| I-8 | Ordering of the `status=settled` list is observed to be newest-first for several series (KXDOGE, KXDPWORLDTOUR, KXBIGBROTHER, KXAAAGASD), but the docs do not state it. A series that settles more than 400 markets in 30 days can therefore lose some older rows in one run. The per-run merge reduces this but does not remove it. | Open, disclosed. |
| I-9 | The strategy lab's own cross-check still shows a fee mismatch (published fees 51.52 vs recomputed 65.24, `docs/data/strategy_lab.json` `crosscheck_issues`). Not re-derived in this session. | Open, self-reported by the pipeline. |
| I-10 | Four separate site generators sit in one repository (`site_build/` → root pages, `docs/` hand-written pages, `site/` builder, `kalshi-dashboard/` output). They publish different numbers (I-4). | Open. Recommend consolidating to one. Not changed here. |

## 3. Blockers that cannot be fixed from this sandbox

| ID | Blocker | Why it cannot be worked around |
| - | - | - |
| B-1 | Real Kalshi **demo-account** portfolio, balance, positions and orders | The endpoints need a signed key pair (C12). Creating a demo account and API key needs a person at kalshi.com. No key exists in the repository or the session. The site keeps labelling the portfolio as simulated. |
| B-2 | Bash-side live polling from this sandbox | Egress to the Kalshi demo host is blocked from the shell (§0). Scheduled collection runs in GitHub Actions, which can reach it. |

## 4. Requirement coverage (state at this session, from the checks above)

| Requirement | State | Evidence |
| - | - | - |
| Highest-dollar events per topic (gas, elections, culture, crypto, golf) | Implemented; ranking uses open interest × notional | C2 values match; `docs/data/markets.json` |
| ≥ $0.10 swing alerts, two scrolling chats (all / model shortlist) | Implemented | `docs/data/alerts.json` (6 alerts at threshold 0.10); C6, C7 |
| Track events until they resolve, YES or NO | **Partly.** Docs pipeline was broken (I-1, fixed in code). Root pipeline lacks three topics (I-5). | C4, C5, C10 |
| Simulated trades, strategies, categorised results | Implemented (simulated ledger) | `docs/strategies.html`, `trading/` |
| Portfolio on the Kalshi demo account | **Blocked** (B-1) | C12 |
| Price chart, time window selectable | Implemented, but the "seconds" window is 1-minute candles (I-7) | C11 |
| Liquidity: contracts available at each price | Implemented (bid-side resting size; asks implied, see FL-07) | `docs/data/orderbooks.json` |
| Catalyst links for ≥$0.10 moves | Implemented as time-proximity headline links (Google News RSS), never claimed as cause (FL-03) | `docs/data/alerts.json` `headlines` |
| Executive summary | Exists from earlier sessions (`EXECUTIVE_SUMMARY.md`). Not re-written here. | — |
| Flagged-for-review page with source links | Exists (`docs/flagged.html`). Extended with FL-10 onward in this session. | §2 |

## 5. Tests run for this session

* `python3 -m unittest discover -s tests` → 237 run, OK (1 skipped, pre-existing).
* `python3 -m unittest tests.test_resolutions_coverage -v` → 7/7 OK.
* Mutation check on X1: removing rotation, removing the per-topic cap, or removing accumulation each makes at least one test fail (verified locally, then reverted).
* `python3 -m collector.test_runner` → RUNNER TEST PASSED.
* `python3 -m trading.test_engine` → ALL TRADING TESTS PASSED.
* Not run here: browser (jsdom) checks and `tools/linkcheck.py` on the site. They are run before PR merge (see COORDINATION record).

## 6. What still needs a human

1. A Kalshi demo API key pair (B-1), if a real demo-account portfolio is wanted.
2. Decision on whether the four site generators (I-10) should be reduced to one.
3. Review of the flagged items above, using the source links in §1.
