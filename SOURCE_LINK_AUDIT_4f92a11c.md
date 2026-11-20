# Row-level source-link audit — `arena-4f92a11c` (T20)

Date (UTC): 2026-11-20 · Branch: `arena/4f92a11c-trade2` · Scope: report-only. No published data, page, or pipeline file was edited.

## What was checked

Every row of every published table in the repo was checked by `tools/rowsource_check.py`:

| Check | Rule |
| --- | --- |
| Source link | The row has a primary source URL (`source_url`). |
| Official host | The URL host is a Kalshi host: DEMO `external-api.demo.kalshi.co` / `demo-api.kalshi.co`, or PRODUCTION `external-api.kalshi.com` / `api.elections.kalshi.com`. |
| Demo requirement | The task requires the **demo** endpoint. DEMO = pass, PRODUCTION = flagged. |
| Docs link | Where the table has a docs field, it links `docs.kalshi.com`. |
| Blank values | A blank (`null` or `""`) value is counted as **UNVERIFIED**. It is not filled in. |

Reproduce: `python3 tools/rowsource_check.py` (writes `audit/rowsource-4f92a11c.csv` and `.json`). Unit tests: `python3 -m unittest tests.test_rowsource_check` (15 tests). Full suite: `python3 -m unittest discover -s tests` → 57 run, 1 skipped (pre-existing), 0 failures.

## Results

| Table (file) | Rows | Official Kalshi source link | Demo host | Production host | Docs link | Rows with blank values |
| --- | --: | --: | --: | --: | --: | --: |
| `kd.markets` (`kalshi-dashboard/data/latest.json`) | 354 | 354 | 0 | **354** | n/a | **158** |
| `kd.topic_events` (same file) | 26 | 26 | 0 | **26** | n/a | 0 |
| `kd.resolved_pending` (`kalshi-dashboard/data/resolved.json`) | 19 | 19 | 0 | **19** | n/a | 0 |
| `kd.resolved` (same file) | 0 | — | — | — | — | — |
| `kd.alerts` (`kalshi-dashboard/data/alerts.json`) | 0 | — | — | — | — | — |
| `kd.trade_positions` (`kalshi-dashboard/data/trades.json`) | 0 | — | — | — | — | — |
| `docs.markets` (`docs/data/markets.json`) | 40 | 40 | **40** | 0 | 40/40 | **40** (`expected_expiration`) |
| `docs.resolutions` (`docs/data/resolutions.json`) | 300 | 300 | **300** | 0 | 300/300 | 0 |
| `docs.alerts` (`docs/data/alerts.json`) | 3 | 3 | **3** | 0 | 3/3 | 0 |
| `docs.portfolio_trades` (`docs/data/portfolio.json`) | 6 | 6 | **6** | 0 | n/a | 0 |
| **Total** | **748** | **748 (100 %)** | **349** | **399** | | |

Result against the request:

- **Every row has an official Kalshi source link: PASS (748 / 748).** No row lacks a source, and no primary source is a third-party site.
- **Every row uses the demo endpoint: FAIL (349 / 748).** All 399 rows in the live `kalshi-dashboard/` pipeline (354 markets, 26 topic events, 19 pending resolutions) point to the production host. See F-4F-01.
- **Every value is verified or marked unverified: FAIL in two places.** 158 live-dashboard rows have a blank derived price (F-4F-02). All 40 `docs/` markets have a blank `expected_expiration` (F-4F-05).

## Spot checks against the official API

These three rows were fetched live from the official endpoints in this session. Fetch times are the observation times, and values move between snapshot and fetch.

| Row | Official URL fetched | Snapshot value (repo) | Official value (fetched) | Result |
| --- | --- | --- | --- | --- |
| `KXPGATOUR-THRC26-TMOO` (docs, demo) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO | title "The RSM Classic: Taylor Moore wins"; status open; last 0.005; bid 0.003; ask 0.005; OI 1151640.41 (snapshot 2026-11-20T18:39:58Z) | title identical; status active; last 0.0050; bid 0.0030; ask 0.0050; OI 1151807.75; `expected_expiration_time` 2026-11-22T00:00:00Z | Title and prices match. OI moved. **Repo `expected_expiration` is null; official value exists** (F-4F-05). |
| `KXPGATOUR-THRC26-MTHO` (live dashboard, production) | https://external-api.kalshi.com/trade-api/v2/markets/KXPGATOUR-THRC26-MTHO | last 0.19; bid 0.17; ask 0.19; volume_24h 395885.62; OI 686668.45 (snapshot 2026-11-20T18:53:28Z) | last 0.16; bid 0.16; ask 0.17; volume_24h 395885.62; OI 687317.00 | Confirms the host is **production** and serves live data. Prices moved after the snapshot. |
| `KXDOGE-26NOV2012-T0.2349999` (docs resolutions, demo) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDOGE-26NOV2012-T0.2349999 | result "no"; settlement_value 0.0; settlement_ts 2026-11-20T18:07:44.336487Z | `status` finalized; `result` "no"; `settlement_value_dollars` "0.0000"; `settlement_ts` 2026-11-20T18:07:44.336487Z | **Match.** |

Official rule text for the price step, from the TMOO response: `price_ranges` gives a step of `0.0010` from 0.0000 to 0.1000, `0.0100` from 0.1000 to 0.9000, and `0.0010` from 0.9000 to 1.0000 (`price_level_structure: tapered_deci_cent`). Sub-cent prices are therefore valid, and a cent-only field loses them.

## Irregularities for review (also published on the Flagged for Review page via the integration session)

| ID | Severity | Observation | Evidence (repo) | Official source | Owner / next step |
| --- | --- | --- | --- | --- | --- |
| F-4F-01 | High | The live `kalshi-dashboard/` snapshot reads the **production** host, but the request is demo-only. 399 rows affected. | `kalshi-dashboard/data/latest.json` → `source.base_url` = `https://external-api.kalshi.com/trade-api/v2`; every row's `source_url` is on `external-api.kalshi.com` | [API environments](https://docs.kalshi.com/getting_started/api_environments): demo REST root is `external-api.demo.kalshi.co`; "demo API keys only work against demo endpoints." [Demo environment](https://docs.kalshi.com/getting_started/demo_env): "Demo's recommended Trade API root is `https://external-api.demo.kalshi.co/trade-api/v2`." | Already claimed as T17 by `arena-e4e8f4e1` and `arena-856e184e` (see R-4f92-2). Not edited here. |
| F-4F-02 | Medium | 158 live rows have a blank `last_cents` even though the official dollar price is present (for example 0.0030, 0.0010, 0.0040). Cent rounding drops sub-cent prices. | `kalshi-dashboard/data/latest.json`: `last_cents` = null, `last_price_dollars` = "0.0030" | Official `price_ranges` for `KXPGATOUR-THRC26-TMOO` (step 0.0010 below $0.10): https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO | Left blank (not filled). Display should use the dollar field for sub-cent prices. Owner: the live-dashboard owner. |
| F-4F-03 | Medium | All 300 resolution rows are `result: "no"`. They are all crypto DOGE range/threshold buckets with zero volume, from one event family. Each row was checked against the official API (one row matches), but the concentration has not been explained. | `docs/data/resolutions.json` | Verified row: https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDOGE-26NOV2012-T0.2349999 . Settlement rules: [Market settlement](https://docs.kalshi.com/getting_started/market_settlement) | Needs review: confirm the family's full settlement set before presenting any YES/NO rate. Do not treat the 300/300 as a finding. |
| F-4F-04 | Medium | Two resolution trackers disagree. The live dashboard shows 0 resolved and 19 pending. The `docs/` tracker shows 300 resolved. | `kalshi-dashboard/data/resolved.json` vs `docs/data/resolutions.json` | Same official endpoints as F-4F-03 | Pipeline owners to reconcile or label which tracker is authoritative. |
| F-4F-05 | Medium | `docs/data/markets.json`: `expected_expiration` is blank in **40 / 40** rows. The official market object provides `expected_expiration_time` (TMOO: 2026-11-22T00:00:00Z). The field name and value are not mapped. | `docs/data/markets.json` → `expected_expiration` = null | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO (field `expected_expiration_time`); [Get Market](https://docs.kalshi.com/api-reference/market/get-market) | Needs the field-mapping fix in `docs/` (owner: arena-c0205283 / `docs/**`). Left blank here. |
| F-4F-06 | Low | `docs/data/markets.json`: `fee_type` is blank in 40 / 40 rows. The TMOO market object has no `fee_type` key. | `docs/data/markets.json` → `fee_type` = null | Market object: https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO . Fee schedule: https://kalshi.com/docs/kalshi-fee-schedule.pdf | Left blank: the market object does not carry it. Fee type belongs to the fee schedule, not this field. |
| F-4F-07 | Info | Demo prices "may not be reflective of those in real markets." The `docs/` tables are demo data, so their prices are not market prices. | `docs/data/markets.json`, `docs/data/resolutions.json` | [Demo environment](https://docs.kalshi.com/getting_started/demo_env): "The price and behavior of markets in the demo environment may not be reflective of those in real markets." | Show this caveat next to every `docs/` table. |
| F-4F-08 | Info | 1,144 settlement-source references across 31 hosts (for example foxsports.com, espn.com, pgatour.com, cfbenchmarks.com, gasprices.aaa.com) are named inside market records. These are third-party references, not official Kalshi sources. | `audit/rowsource-4f92a11c.json` → `settlement_source_hosts` | Market record `settlement_sources` in the official API (see the TMOO URL above) | Kept as informational. The row's own source is the Kalshi API. |
| F-4F-09 | Process | Board conflicts: task ID `T16` is used by two sessions for different work, and `T17` is double-claimed. | `COORDINATION.md` | n/a | Logged as R-4f92-1 and R-4f92-2 on the board. |

## Limits of this audit (not verified)

- Only three rows were checked against the official API (spot checks). The other 745 rows are verified for **source link, host, and blank fields** only, not value by value. Value-by-value verification is T18 (`arena-856e184e`).
- Prices in the snapshots change minute by minute, so "moved since snapshot" is an observation, not a defect.
- The live-dashboard `change_cents` (207 blank) and `prev_last_cents` (199 blank) fields are empty because there is no previous run for those markets. They are not counted as errors here.
- The sandbox cannot reach Kalshi directly. All official observations above came from the `fetch_page` tool, which returns the official responses.

## Files

- `tools/rowsource_check.py` — the checker (stdlib only).
- `tests/test_rowsource_check.py` — 15 offline tests.
- `audit/rowsource-4f92a11c.csv` — one line per row (748 rows) with source class, URL, docs link, blank fields, and status.
- `audit/rowsource-4f92a11c.json` — summary counts, issue list, and settlement-source host counts.
