# Verification record — session `arena-f642a30a` (Board L, F642-T1…T4)

Branch `arena/f642a30a-trade2` · base `main` @ `8d15b95` · recorded 2026-11-21T07:30Z.
Convention: every claim below names its official source URL and the UTC session window in
which it was checked (this session ran 2026-11-21 ~07:05–07:35 UTC). Anything that could
not be confirmed from an official source is listed under "Unverified / blocked", never filled in.

## 1. Tasks and the defect each fixes

| ID | Request | Defect (pre-fix evidence) | Fix |
| - | - | - | - |
| F642-T1 | [R-4f92-4] `kalshi-dashboard/data/resolved.json` shows no outcomes | Committed snapshot at `8d15b95` (generated 2026-11-21T06:27:09.657Z, `status.json` run 14): `resolved: []`, `pending: []`, `resolved_total: 0`, `pending_total: 0`, `resolution_checks_this_run: 0`, while `docs/data/resolutions.json` (docs pipeline) carries 300 outcome rows. Root causes: (1) resolution memory existed only in the Actions state cache — the cache key `kalshi-demo-state-${{ github.run_id }}` (`.github/workflows/dashboard.yml`) is best-effort and evicted, which also explains the earlier audit's "19 pending rows" vanishing to 0; (2) detection was only a watch on previously tracked tickers — no settled-market scan; (3) `state.pending` rows were deleted whenever `state.meta` lacked their ticker | `scripts/collect.mjs`: rotating per-topic settled scan via documented `GET /markets` filters; previously published `resolved.json` merged back at startup (durable across cache evictions); watch list includes pending tickers; pending cleared only on resolution or reactivation; open-position tickers exempt from retention pruning |
| F642-T2 | [R-3DCF-5] store the price behind `notional_usd` | `collector/runner.py::market_row` published `notional_usd` = volume × price without recording which price (`last_price_dollars` or the (bid+ask)/2 fallback) | additive fields `notional_basis_price` + `notional_basis` naming the official source field(s); `market_notional()` signature/behaviour unchanged |
| F642-T3 | [R-79CC-2] `age_label` UTC fallback | `site_build/extras.py` used `time.mktime` (reads the ISO-8601 `…Z` stamp as **local** time), skewing the published snapshot age on non-UTC runners | `calendar.timegm` (UTC counterpart), documented at the call site |

## 2. Live checks against official sources (this session)

| # | Claim | Official source (URL) | Checked | Result |
| - | - | - | - | - |
| V1 | `GET /markets` `status` filter values are `unopened`, `open`, `closed`, `settled`; `min_settled_ts` = "Filter items that settled after this Unix timestamp"; one status filter at a time | https://docs.kalshi.com/api-reference/market/get-markets | 2026-11-21 ~07:15Z (docs fetch) | **CONFIRMED** (quoted from the endpoint's parameter description) |
| V2 | A settled market object carries `result` `"yes"`/`"no"`, `settlement_ts`, `settlement_value_dollars`; terminal objects show `status: "finalized"` | https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXDOGE&status=settled&limit=3&min_settled_ts=1763600000 | 2026-11-21 ~07:18Z (live demo fetch) | **CONFIRMED** — 3 markets, all `result: "no"`, `settlement_ts: 2026-11-21T06:03:37.961447Z`, `settlement_value_dollars: "0.0000"`, `status: "finalized"` |
| V3 | `min_settled_ts` is Unix **seconds** and filters by settlement time | https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXDOGE&status=settled&limit=5&min_settled_ts=1795243500 (= 2026-11-21T06:45Z) and …&min_settled_ts=1795250000 (future) | 2026-11-21 ~07:28Z | **CONFIRMED** — both windows returned `markets: []` (the series' last settlement was 06:03Z, outside the windows); the wide window of V2 returned the 06:03Z rows. Consistent with seconds-since-epoch semantics; an ms value (1.795e12) would be year 58,000+ and could never match |
| V4 | YES holders receive $1 per contract, NO holders $1 per contract | https://docs.kalshi.com/getting_started/market_settlement | 2026-11-21 ~07:29Z (docs fetch) | **CONFIRMED** — "Yes outcome: Yes contract holders receive $1 per contract · No outcome: No contract holders receive $1 per contract". This is the payout rule the paper ledger settles against and the `docs_url` every resolution row carries |
| V5 | The node pipeline's own published snapshot was empty pre-fix | `kalshi-dashboard/data/status.json` + `kalshi-dashboard/data/resolved.json` committed at `8d15b95` (published mirror: https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/data/status.json) | read from the branch base (2026-11-21T06:27:09.657Z snapshot) | **CONFIRMED** — `resolved_total: 0`, `pending_total: 0`, `resolution_checks_this_run: 0`, `resolved: []`, `pending: []` |
| V6 | Demo-only host guard holds on the node pipeline | `kalshi-dashboard/data/status.json` (`base_url`) + `scripts/collect.mjs::assertDemoBase` | branch base snapshot | **CONFIRMED** — `base_url: https://external-api.demo.kalshi.co/trade-api/v2` (see closeouts below) |
| V7 | Docs-pipeline comparison (the "how each event was resolved" requirement is satisfiable) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDOGE-26NOV2100-T0.2349999 (row source in `docs/data/resolutions.json`) | branch base snapshot + V2 | **CONFIRMED** — the same market appears with `result: "no"` in both the published docs row and the live API response (fields match verbatim) |

## 3. Tests and gates run on the final tree

| Gate | Result |
| - | - |
| `python3 -m unittest discover -s tests` | **246 OK** (1 skipped) — was 237 before this session; +9 new (6 notional-basis, 3 age-label) |
| `npm test` | **34/34** — was 29; +5 new (settled scan provenance, state-wipe survival, pending survive/re-check/resolve, rotation coverage, retention protection) |
| `python3 -m collector.test_runner` | PASS |
| `python3 -m trading.test_engine` | PASS |
| `python3 -m site_build.build` | clean |
| `node scripts/build-site.mjs` (site builder + link check) | 13 pages built, links/config OK |
| `python3 tools/linkcheck.py` | 50 pages / 666 internal links / **0 errors** |

Mutation sanity for F642-T1 (each change breaks at least one new test): removing the
prior-published merge breaks "resolution history survives a state-cache wipe"; removing
pending from the watch set breaks "pending rows … are re-checked"; disabling the scan
breaks "settled-scan records official results"; removing the protect-set breaks
"pruneResolved … never drops protected tickers".

## 4. What the fix does *not* claim (limits, honestly stated)

| # | Limit | Handling |
| - | - | - |
| L1 | **Detection latency for untracked markets.** The settled scan rotates ~15 series/run (bounded requests), so a market that resolves in a series not scanned this run is picked up within `ceil(series/perCap)` runs (≤ ~1 h at the `*/30` cadence); markets the collector tracks get the one-run watch path | Stated in code docstring (`rotateScanSeries`); trade positions settle on first observation either way (pruning never drops their rows) |
| L2 | **Rows record the first observed official `result`.** If Kalshi later revises a provisional settlement, the row is not auto-updated | Row keeps `source_url` + `settlement_ts`; a change would show on re-fetch. Not flagged on the site because no such case is known on the demo exchange |
| L3 | Docs say the `status` *filter* value is `settled`, but terminal market objects return `status: "finalized"` | Irregularity I-F642-1 (below) — the code keys on `result` and copies `status` verbatim |
| L4 | Scalar (`result: "scalar"`) outcomes are recorded verbatim but are not a yes/no outcome | Page renders the raw `result` chip; the "Resolved (yes/no)" KPI counts all rows (pre-existing semantics, unchanged) |

## 5. Irregularities flagged (not silently worked around)

| ID | Finding | Evidence | Suggested owner |
| - | - | - | - |
| I-F642-1 | `GET /markets` parameter docs describe the status filter value `settled`, while settled market **objects** return `status: "finalized"` (both checked live, see V2/V3). The docs' example schema also shows `status: "initialized"` | live URLs in V2/V3 + the get-markets docs page | Kalshi-side docs wording; our code follows the live field values verbatim |
| I-F642-2 | The node pipeline's state cache (`kalshi-demo-state-${{ github.run_id }}`, saved only on collect success) silently reset the pipeline's memory — likely why the earlier audit saw 19 pending rows and run 14 saw 0 | `.github/workflows/dashboard.yml` cache config + V5 | mitigated by F642-T1 (published snapshot is now the durable memory); workflow owner may still want a cache-version prefix bump when state shape changes |
| I-F642-3 | `time.mktime` UTC-vs-local fallback in `age_label` (fixed in F642-T3) matches the pattern `extras.age_label` exposed since its first version; any *historical* snapshot ages published by non-UTC runners were skewed by the runner's UTC offset | `site_build/extras.py` history | informational; fix is in this branch |

## 6. Closeouts (requests resolved by evidence here)

| ID | Was | Resolution |
| - | - | - |
| R-4f92-3 | `kalshi-dashboard/data/*` snapshot fetched from the **production** host `external-api.kalshi.com` | **Closed.** `source.base_url` and `status.json.base_url` at `8d15b95` both show `https://external-api.demo.kalshi.co/trade-api/v2` (V6). The demo-only guard (`assertDemoBase`) rejects any other root — regression-tested in `scripts/test/collect.test.mjs` |
| F-07 | open until `main` publishes a successful demo snapshot | **Closed with evidence** (same as V6: snapshot generated 2026-11-21T06:27:09.657Z from the demo host, run 14, `errors: []`). Flag-page copy is updated by the page owner — see request R-F642-1 |

## 7. Requests raised by this session

| ID | To | Request |
| - | - | - |
| R-F642-1 | flagged-page owners (`site_build/flagpage.py` / `docs/flagged.html` / `kalshi-dashboard` flag data) | Update the F-07 / R-4f92-3 flag copy to "resolved 2026-11-21 (demo-host snapshot on main, run 14)" per §6; keep the row for history |
| R-F642-2 | integration session (`arena-1ebe818a`) | R-3DCF-4 (three equity figures across pipelines) is untouched here — the numbers are owned by three separate ledgers and naming them per-pipeline is your call per the board |
| R-F642-3 | alert views owner (PR #57 / `assets/*`) | R-3DCF-3 (mark alerts "reverted within one candle") remains open; the data layer (`collector/alerts.py`) was deliberately not touched here to avoid colliding with live-detection work in flight |

## 8. Unverified / blocked (left blank by convention)

| Item | Why | Where it surfaces |
| - | - | - |
| Real Kalshi demo-account portfolio/balance/fills | Requires an API key pair; none exists in this repo and creating one needs a human at kalshi.com (docs: https://docs.kalshi.com/api-reference/portfolio/get-balance — signed `KALSHI-ACCESS-KEY`/`SIGNATURE`/`TIMESTAMP` headers required) | Blocker B-1 (pre-existing); the portfolio stays labelled SIMULATED |
| Causal news links for ≥ $0.10 swings | No official source attributes a price move to a headline; candidates are labelled as candidates | Pre-existing flag on the site's Flagged page |

## 9. Production verification after merge (2026-11-21T07:35–07:40Z)

PR [#77](https://github.com/wingbangboozle1-lang/Trade2/pull/77) merged to `main` as `7e7fd62`
(checks: `check` pass 17s, `collect` pass 11s). The post-merge `Kalshi dashboard — collect,
build, publish` run collected with the new code and published run 15
(generated 2026-11-21T07:35:43.570Z), verified **live on the deployed Pages site**:

| Check | Live URL | Result |
| - | - | - |
| Pipeline counts | https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/data/status.json | `resolved_total: 143` (pre-fix: 0) · `resolved_added_this_run: 443` · `settled_scan_series: 13` · `settled_scan_markets: 443` · `errors: []` · `base_url: https://external-api.demo.kalshi.co/trade-api/v2`. The new count keys exist only in the merged `scripts/collect.mjs`, so this run cannot be pre-fix output |
| Outcome rows | https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/data/resolved.json | rows carry `result: "yes"|"no"` verbatim + `settlement_ts` + `settlement_value_dollars` + `via` + per-row `source_url` (`…/markets/{ticker}`) + `docs_url`. Example: `KXPGATOUR-AUCPBCS26-CRAM` (Chad Ramey wins) → `result: "yes"`, `settlement_value_dollars: "1.0000"` — consistent with the official $1/contract rule (V4); the other finalists → `result: "no"`, `"0.0000"` |
| Rendered page | https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/resolved.html | "Resolved events — yes or no" table renders **Resolved (143)** with YES/NO chips, `finalized` status, close times, tickers and market JSON links; "Data is 2 min old" age badge (the `age_label` UTC fix under load) |
