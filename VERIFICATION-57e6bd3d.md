# VERIFICATION-57e6bd3d — root-pipeline resolution coverage (E57-T1)

Session `arena-57e6bd3d` · branch `arena/57e6bd3d-trade2` · checks run 2026-11-21 (UTC).
Scope: `collector/collector.py` (settlement block and its helpers), `tests/test_root_resolution_coverage_57e6.py`, this file, and the `COORDINATION.md` section for E57-T1/T2.

## 1. Defect, measured before the change

| Check | Value | How obtained |
| - | - | - |
| Stored YES/NO rows in `data/resolutions.json` | 328 (80 yes, 248 no) | local read of the committed file |
| Rows by topic | `gas-prices` 268, `crypto` 60, **elections 0, culture 0, golf 0** | local read; the `topic` field of each stored record |
| Rows with `series_ticker` set | 0 (all `null`) | local read; consistent with the `GET /markets` schema below |
| Series tracked per topic (`data/series_cache.json`) | gas 162 · elections 1,451 · culture 789 · crypto 159 · golf 104 = **2,665** | local read |
| Cause | `collect()` settled scan = `client.markets(status="settled", limit≤1000, max_pages=3)`: one exchange-wide newest-first window | `collector/collector.py` (pre-change line ~603) |

A per-series sweep was rejected. At the 24-series-per-run rotation that X1 used in the docs pipeline, one full pass over 2,665 series takes about 111 runs, roughly 9 hours at the 5-minute cadence.

## 2. Official sources checked (opened directly, 2026-11-21 UTC)

| # | URL | What it establishes | Result |
| - | - | - | - |
| C1 | https://docs.kalshi.com/api-reference/market/get-market | `GET /markets/{ticker}` returns `{"market": {...}}` with `result`, `status`, `settlement_ts`, `event_ticker` | **Match** — the implementation reads `payload["market"]`. |
| C2 | https://docs.kalshi.com/api-reference/market/get-markets | Market object fields. No `series_ticker` field is listed | **Match** — the reason the topic is derived from the event ticker (R-FB-01). |
| C3 | https://docs.kalshi.com/getting_started/market_settlement | "Yes outcome: Yes contract holders receive $1 per contract"; "No outcome: No contract holders receive $1 per contract"; "timing can vary based on market type, data source availability, and manual review" | **Match.** The timing wording is why the 14-day give-up horizon is a stated design choice, not a documented figure. |
| C4 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDPWORLDTOUR-DPWTC26-THAT | Golf: `result` "yes", `status` "finalized", `settlement_ts` 2026-11-15T14:56:17.490048Z, `close_time` 2026-11-15T14:52:33Z | **Match.** A settled golf market the root store did not hold. |
| C5 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXCAGOVPRIMARY1ST-26JUN02-1ST-XBEC | Elections: `result` "yes", `status` "finalized", `settlement_ts` 2026-07-11T00:45:14.689883Z, `close_time` 2026-07-11T00:12:24Z | **Match.** Elections outcome, absent from the store. |
| C6 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBIGBROTHER-26DEC31-RIC | Culture: `result` "yes", `status` "finalized", `settlement_ts` 2026-10-02T04:20:30.143779Z, `close_time` 2026-10-02T03:47:33Z | **Match.** Culture outcome, absent from the store. |
| C7 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70 | Open gas market: `result` "" and `status` "active", `close_time` 2026-11-30T04:59:00Z (in the future) | **Match.** Not due, so it stays pending. |

Offline checks of the code path use fixtures shaped like C4–C7. The live responses above were used to confirm the field names and value types.

## 3. What the change does (E57-T1)

1. Every market the collector watches (`observations`) is registered in `resolutions.json` under `pending`, with its topic, event ticker, and close time.
2. Once a pending market's `close_time` has passed, it is re-read by ticker (`GET /markets/{ticker}`). At most **60** lookups run per cycle, least-recently-checked first.
3. A `yes` or `no` result writes a row in the same shape as the existing settled scan, with the topic from the watch list. The simulated position is graded through the same `Portfolio.settle()` call, so a market graded by the scan is not graded twice.
4. A market with no result **14 days** after close is dropped and reported in `errors`. This horizon is a design choice, not a documented figure.
5. A failed lookup keeps the market pending. A run-budget stop is reported as partial.
6. The published `live.json` gains an additive `resolution_tracking` object (pending, lookups, resolved, dropped, cap). No existing key is removed or renamed.
7. The whole step is wrapped so an exception is logged to `errors` and the rest of the run continues.

## 4. Tests

| Command | Result |
| - | - |
| `python3 -m unittest tests/test_root_resolution_coverage_57e6.py -v` | **20 OK** (5 timestamp/record/fetch, 7 tracking/resolve, 2 portfolio grading, 1 end-to-end `collect()` smoke test with every path redirected to a temp dir). |
| `python3 -m unittest discover -s tests` | **OK (skipped=12)**. The skips are environmental: `cryptography` is not installed, and jsdom is unavailable in this sandbox (`ERR_MODULE_NOT_FOUND`). The baseline skip count recorded on the board was 1, so the sandbox differs from the earlier environment. The skipped tests are not run here, so their result is unverified in this session. |
| `python3 -m collector.test_runner` | **RUNNER TEST PASSED** |
| Mutation check, 4 mutants | Each mutant makes at least one test fail: (a) due-check removed → FAIL; (b) `del pending[ticker]` removed after a resolution → FAIL (2); (c) give-up branch disabled → FAIL; (d) open result treated as final → FAIL. Original code restored and re-run: OK. |

The smoke test runs the real `collect()` with a fake client and a seeded pending golf market. It checks that the store row has `topic: golf` and `result: yes`, the market leaves `pending`, and `resolution_tracking.resolved_this_run == 1`. It does not touch `data/`.

## 5. Irregularities and limits (for review)

| ID | Item | Source |
| - | - | - |
| F-57-1 | **Coverage starts now, not retroactively.** The change tracks markets observed from the first run after merge, so settlements of markets that were never watched are not recovered. The published file will gain elections, culture and golf rows only as watched markets settle. | §3 |
| F-57-2 | **The published data changes only on the next scheduled collector run after merge.** This session cannot run the live collector (the sandbox cannot reach the Kalshi hosts from bash). Live behaviour is verified by the offline tests and the official-endpoint checks in §2, not by a live run. | §2 |
| F-57-3 | **The 14-day give-up horizon** is a design choice (C3 says settlement timing varies). A market whose result arrives later than 14 days after close would be dropped from tracking. | C3 |
| F-57-4 | **Two pipelines disagree.** The root store holds 328 rows and the docs pipeline publishes 300 (R-3DCF-4). This change touches only the root pipeline. | COORDINATION.md |
| F-57-5 | **Environmental test skips** (see §4). The jsdom and `cryptography` tests were not run here. | §4 |
| F-57-6 | **`series_ticker` on settled rows stays `null`.** The official market object has no such field (C2), and the code does not infer it. | C2 |

## 6. Requests closed or left open

| Request | Status after this session |
| - | - |
| R-3DCF-1 (root settled-scan coverage) | **Addressed in code** by tracked-market lookup, not by the series rotation the request named. Reason in §1. Live effect pending the next scheduled run (F-57-1, F-57-2). |
| R-FB-01 (series_ticker in buckets) | Already handled on `main` by `resolution_topic()` (event-ticker fallback). Not changed here. |
| R-3DCF-2, R-3DCF-3, R-3DCF-5, R-3DCF-6 | Untouched. Owners of the table and chart code are not in this session's scope. |
