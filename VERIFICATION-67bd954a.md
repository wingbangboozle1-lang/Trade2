# VERIFICATION-67bd954a — root resolution coverage (R1–R3)

Session `arena-67bd954a`, branch `arena/67bd954a-trade2`, base `main` @ `8d15b95`.
Claim and scope: `COORDINATION.md` → "Session claim — `arena-67bd954a`".

This file records what was checked, when (UTC), against which official URL, and the result.
A result is **MATCH** only when the published value equals the official record field for field.
Anything that could not be checked is marked **UNVERIFIED**, not filled in.

## 1. What changed (code)

| Item | Where | Official basis |
| - | - | - |
| Settled read is time-bounded (`min_settled_ts`, now − 2 h), `mve_filter=exclude`, cursor paging, `truncated` flag | `collector/collector.py::scan_settled` | https://docs.kalshi.com/api-reference/market/get-markets (params `min_settled_ts`, `max_settled_ts`, `mve_filter`, `limit` ≤ 1000, `cursor`) |
| Resolution watchlist: every in-scope market seen open, plus open simulated positions, checked **by ticker** (`tickers=`, 50 per request, ≤ 30 requests per run, least-recently-checked first). Unseen for 14 days → dropped | `collector/collector.py::update_watchlist`, `pick_watchlist`, `lookup_settled_tickers` | same page, param `tickers` ("Comma-separated list of market tickers to retrieve") |
| Per-topic floor: each topic keeps its newest 100 rows first; the global cap (2,000) is unchanged | `collector/collector.py::migrate_resolutions` | internal design; existing test `tests/test_resolutions.py` still passes |
| Finalized markets are not published as live events (`status` ∈ finalized, settled, determined) | `collector/collector.py::is_live_market` | status values as returned by https://docs.kalshi.com/api-reference/market/get-markets and by the live market objects below |
| Tests | `tests/test_root_settled_scan_67bd954a.py` (20 tests: request parameters, paging, truncation, watchlist rules, ticker lookup, per-topic floor, live-market rule, offline end-to-end `collect()`) | — |

Test results at the last code commit: `python3 -m unittest discover -s tests` → OK (skipped=12, the usual jsdom/optional skips); `npm test` → 29/29; `python3 -m collector.test_runner` → PASSED.
Mutation checks (run on the code at each step): removing `mve_filter` fails the request-parameter tests; disabling the watchlist lookup fails the end-to-end test; the earlier global-cut variant failed the retention test.

## 2. Live runs (GitHub Actions, official demo API)

The sandbox cannot reach `external-api.demo.kalshi.co` (TLS blocked, see COORDINATION I3), and GitHub Actions logs and artifacts are not retrievable from it. Each run therefore used a **temporary** workflow, `.github/workflows/verify-67bd954a.yml`, that ran `python3 -m collector.collector` (the same command as `kalshi-dashboard.yml`) and committed `data/` and `verify-67bd954a-run.json` back to this branch with `[skip ci]`. Both the workflow file and these outputs are removed before the PR.

| Run | Commit | UTC | Code | Scan | Watchlist | Store (2,000 rows) | Finding |
| - | - | - | - | - | - | - | - |
| R-A | `853278f` | 07:19:27 | scan only, 2 h window, cap 10,000 | 10 pages, **10,000 markets, truncated** | — | crypto no 1,899 · crypto yes 1 · gas no 80 · gas yes 20 · **elections 0 · culture 0 · golf 0** | The exchange-wide window is not enough. It is dominated by 15-minute crypto. The watchlist is needed. |
| R-B | `34c94c8` | 07:23:46 | + watchlist | 3 pages, 3,000, truncated | 751 checked, **8 resolved** | unchanged from R-A | Resolved tickers were not listed in this run; the names are in R-C below. |
| R-C | `5863b92` | 07:26:35 | + seeds (see §3) | 3 pages, truncated | 753 checked, 10 resolved | crypto no 1,897 · crypto yes 1 · gas no 80 · gas yes 20 · **elections yes 1 · golf yes 1** | The watch pass resolved 6 `KXBTCMAX100-*` and 2 `KXAAAGASMAXCA-*` markets plus the 2 seeds (names logged in `watch_resolved_tickers`). The 6+2 did not enter the store. KXBTCMAX100-26-APR was read officially as settled 2026-05-02, older than the retained window; the others were not read individually. The seeded ticker path does return official yes results, and they are stored. |
| R-D | `81d68b1` | 07:38:39 | + finalized-market rule | 3 pages, truncated | 753 checked, 2 resolved (seeds) | same as R-C | Published live events: **750 of 750 `active`**; before the fix, 8 of 750 were `finalized`. |

Seeds (test only, R-C and R-D): `KXDPWORLDTOUR-DPWTC26-THAT` (golf) and `KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC` (elections) were written into the watchlist of the checkout before the collector ran, so the ticker path had to return them. They are settled, so they could not appear in the open-market observations.

Collector errors in R-A to R-D: none (`live_errors: []`).

## 3. Row-by-row checks against the official record

Each row was read from the official market endpoint with the fetch tool during this session (after run R-C; exact read times were not recorded) and compared with the stored row in run R-C/R-D.

| Ticker | Stored row (topic, result, settlement_value, settlement_ts, status) | Official record (URL, read UTC) | Result |
| - | - | - | - |
| `KXDPWORLDTOUR-DPWTC26-THAT` | golf, yes, 1.0000, 2026-11-15T14:56:17.490048Z, finalized, title "Tyrrell Hatton" (= `yes_sub_title`) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDPWORLDTOUR-DPWTC26-THAT (read 2026-11-21) — `result: yes`, `settlement_value_dollars: 1.0000`, `settlement_ts: 2026-11-15T14:56:17.490048Z`, `status: finalized`, `yes_sub_title: Tyrrell Hatton` | **MATCH** |
| `KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC` | elections, yes, 1.0000, 2026-07-11T00:45:14.689883Z, finalized, title "Xavier Becerra" (= `yes_sub_title`) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC (read 2026-11-21) — `result: yes`, `settlement_value_dollars: 1.0000`, `settlement_ts: 2026-07-11T00:45:14.689883Z`, `status: finalized` | **MATCH** (see FL on `custom_strike`) |
| `KXBIGBROTHER-26DEC31-RIC` | **not stored** (root culture matcher does not classify the series) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBIGBROTHER-26DEC31-RIC (read 2026-11-21) — `result: yes`, `settlement_ts: 2026-10-02T04:20:30.143779Z`, `status: finalized` | **Coverage gap, logged** (FL) |
| `KXBTCMAX100-26-APR` | observed as an open event before R-D; **not stored** (older than retention cut) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCMAX100-26-APR (read 2026-11-21) — `status: finalized`, `result: no`, `settlement_ts: 2026-05-02T23:30:46.123332Z`, `open_interest_fp: 694493.16` | Published as a live event before the fix (8 rows) — **fixed in R-D** (FL) |

Live events, R-D: 750 rows, `status` = `active` for all 750 (`data/live.json` at `81d68b1`). Before the fix (`data/live.json` on `main` at `95f0031`, the 07:11Z collector run): 8 rows `finalized`, all with open interest > 0 and no quote.

Not verified in this session: the store's resolution rows for `gas-prices`, `crypto` and `elections` beyond the rows above. Those rows were already present before this change; they were not re-read one by one. **UNVERIFIED** for this session.

## 4. Requests and limitations (logged, not fixed here)

1. **No backfill.** Outcomes that settled before a market joined the watchlist are not in the store. No pipeline on this site holds verified earlier elections, culture or golf outcomes to backfill from. Coverage for those topics builds forward from the first run that observes them open. Published on the Flagged page.
2. **Topic scope (culture).** `KXBIGBROTHER` is labelled culture in `docs/data/series.json` but is not matched by the root culture matcher in `collector/topics.py`. Not changed (the matcher is shared by both pipelines). Published on the Flagged page for a decision.
3. **Retention (cause of the watch-resolved gap, fixed on this branch).** Diagnosed from the store: the 2,000-row bound is filled by 1,898 crypto rows settled within 30 minutes (2026-11-21 07:04Z to 07:33Z), so the global cut sits at 07:04Z. The eight watch-resolved outcomes settled between 2026-03-01 and 2026-11-01 and were evicted in the run that stored them. The topic lookup and the settlement window were not the cause: `resolution_topic()` maps all eight (checked offline against `data/series_cache.json`). Fix: watched outcomes (`source: "watch"`) rank ahead of bulk rows, up to the newest 1,000. Offline check on the R-D store plus the eight official records: 8 of 8 kept, 8 bulk rows evicted and counted in `meta.retention`. Live check: pending the next verify run.
4. **Placeholder text (Kalshi-side).** `KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC` has `custom_strike: {"demo strike": "demo strike"}`. The result fields are populated and match. Published on the Flagged page.
5. **Process.** The shared `collect` concurrency group cancelled my dispatched run twice when `main` queued newer runs (already on the Flagged page as a standing item). A temporary workflow with its own group was used for R-A to R-D.
6. **Portfolio on the Kalshi demo account.** Still blocked: no demo API key pair exists in this repository or session (see COORDINATION B-1).

## 5. Sources (official unless marked)

- Get markets (params, statuses): https://docs.kalshi.com/api-reference/market/get-markets
- Market settlement (YES/NO payout): https://docs.kalshi.com/getting_started/market_settlement (cited by earlier sessions; **not re-read in this session**)
- Market objects read in §3: the four `external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}` URLs above.
- Run evidence (this repo, not an official source): commits `853278f`, `34c94c8`, `5863b92`, `81d68b1` on `arena/67bd954a-trade2`, each with `verify-67bd954a-run.json`.
