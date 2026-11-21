# Verification record — session `arena-8a8d4294` (Board M8A8)

Branch `arena/8a8d4294-trade2` · rebased onto `main` @ `8718553` · written 2026-11-21 (UTC).

Scope: everything this branch ships. §1–§3 are the defect and the official evidence for fixing it;
§4 is what the code does after the mid-flight collision with `arena-f642a30a`'s scan for the same
file (their design kept, this branch reduced to the gap); §5–§7 the suites, the open items and the
repo irregularities found; §8 and §12 the requests logged to other owners' files; §9 the
demo-account portfolio block; §10 the in-browser live pulse; §11 the Actions run that exercised the
shipped code against the live demo API.

Method, and the constraint that shapes it: this sandbox has no direct egress to `kalshi.co` (TLS is
blocked outside the allowlist — Board A finding I3), so **API facts were read through the platform
page fetcher**, which does reach the demo host, and **documentation claims were read from
`docs.kalshi.com`**. Every probe below is quoted with the exact URL and the field values it
returned. Nothing here is inferred from a field the API did not return.

---

## 1. The defect, measured on the tree before any edit

Checked at `main` @ `c264beb` (local checkout, 2026-11-21T07:13Z file times).

| # | Measured value | File | Note |
| - | -------------- | ---- | ---- |
| D1 | `{"generated_at":"2026-11-21T06:27:09.657Z","resolved":[],"pending":[]}` | `kalshi-dashboard/data/resolved.json` | 70 bytes; **zero** resolutions published |
| D2 | `run: 14`, `resolved_total: 0`, `pending_total: 0`, `resolution_checks_this_run: 0`, `markets_active: 1577`, `history_markets: 79` | `kalshi-dashboard/data/status.json` | the collector ran 14 times and never checked a market for settlement |
| D3 | 14 positions, `status` counter `{'open': 14}`, `settled: 0`, `wins: 0`, `win_rate: null`, `roi_settled: null`, `realized_cents: 0` | `kalshi-dashboard/data/trades.json` | so "analyse the results of the trades and categorise trades" had no graded row to analyse on this pipeline |
| D4 | the publisher succeeded, it did not fail | run [44875581320](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44875581320) (`dashboard.yml`, schedule, `completed success`), recorded as `outcome: success, published: true` in `kalshi-dashboard/data/collector-run.json` | this is a coverage gap, not an outage |

**Root cause (read in `scripts/collect.mjs`, step 9, lines 167–199 at `c264beb`).** The only
resolution path was: take tickers in `state.meta` that are no longer in the active rows, probe
`GET /markets/{ticker}` for up to 60 of them, and publish a row only when the response carries a
`result`. `state.meta` is filled **only** for `tracked` markets — the top `tracked_max` (80) by
24h dollar volume plus alerted tickers — so a market that settles while outside that window is
never looked at, and its simulated position stays open forever.

## 2. Official sources for the fix, opened in this session

| # | Claim relied on | Official source | Verbatim basis | Result |
| - | --------------- | --------------- | -------------- | ------ |
| S1 | `GET /markets` accepts a `status` filter whose values are `unopened`, `open`, `paused`, `closed`, `settled`, and "Only one `status` filter may be supplied at a time." | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | description block of the endpoint; the `status` schema is `enum: [unopened, open, paused, closed, settled]` | **Confirmed** |
| S2 | `min_settled_ts` = "Filter items that settled after this Unix timestamp"; `max_settled_ts` = "…before…". Compatibility table row: `min_settled_ts, max_settled_ts` ↔ additional status filters `settled`, *empty*. | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | parameter list + the timestamp-compatibility table | **Confirmed** — the scan sends `status=settled` + `min_settled_ts` and nothing else timestamp-shaped |
| S3 | `limit` = "Number of results per page. Defaults to 100. Maximum value is 1000." | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | `limit` schema `minimum: 0, maximum: 1000, default: 100` | **Confirmed** — the scan asks `limit=100`; `resolutionScanPlan` bounds requests, not page size |
| S4 | `series_ticker` = "Filter by series ticker"; `mve_filter` = "'only' returns only multivariate events, 'exclude' excludes multivariate events" | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | parameter descriptions | **Confirmed** — `mve_filter=exclude` keeps combos out of a YES/NO resolution list |
| S5 | Paging: "Pass the cursor exactly as it was returned, and stop when the returned `cursor` is empty." Ordering: "…`min_settled_ts` or `max_settled_ts` sorts by settlement time, latest first." Duplication: "A market whose close time changes while you page … can be skipped or returned twice. **Dedupe by `ticker`.**" | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | "Paging and ordering" block | **Confirmed** — implemented: cursor loop, per-series `seen` set, newest-first retention |
| S6 | Freshness: "Responses are cached for a short time, so prices, sizes and `status` can lag the exchange by several seconds, and filtered listings can lag longer than a read of a single market." | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) | same block | **Accepted, documented** — a settlement can appear up to one run late; the page says where each row came from instead of claiming realtime |
| S7 | History depth: "Markets that settled before the historical cutoff are only available via `GET /historical/markets`." | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets), [Historical Data](https://docs.kalshi.com/getting_started/historical_data) | same block | **Accepted** — the lookback is 30 days and the limit is stated on the page (F-24) |
| S8 | Market `result` is `yes / no / scalar / ""`; `status` is `initialized / inactive / active / closed / determined / disputed / amended / finalized`; `title`, `yes_sub_title`, `close_time`, `settlement_ts`, `settlement_value_dollars`, `volume_fp`, `notional_value_dollars` are documented response fields. | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) 200 response schema | `result.enum`, `status.enum`, required-field list | **Confirmed** — only `yes`/`no` are published as resolutions |
| S9 | Settlement payout: YES holders receive \$1 per contract, NO holders \$1 per contract. | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) | — | **Confirmed** — `payout_cents = size × 100` when the side matches the result, unchanged code path |
| S10 | Demo REST roots | [Demo environment](https://docs.kalshi.com/getting_started/demo_env) | "Demo's recommended Trade API root is `https://external-api.demo.kalshi.co/trade-api/v2`" | **Confirmed** — and `scripts/collect.mjs::assertDemoBase` already refuses any other host, so the new requests cannot be repointed at production |

## 3. Live probes against the demo host (platform fetcher, 2026-11-21 07:25Z–07:27Z UTC)

Each URL below is exactly what the shipped code sends, with the real window.

| # | Request | Response observed | Use |
| - | ------- | ----------------- | --- |
| P1 | `https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled&series_ticker=KXPGATOUR&min_settled_ts=1792653900&limit=5&mve_filter=exclude` | HTTP 200, 5 markets, non-empty `cursor` `CgwIvYnu1wYQ2IbxsAES…`. Row `KXPGATOUR-AUCPBCS26-ZDOU`: `result:"no"`, `status:"finalized"`, `settlement_ts:"2026-11-16T22:33:33.370951Z"`, `settlement_value_dollars:"0.0000"`, `close_time:"2026-11-16T22:29:34Z"`, `title:"Austin Championship presented by Compliance Solutions: Zecheng Dou wins"`, `event_ticker:"KXPGATOUR-AUCPBCS26"` | the request shape is accepted, `limit` is honoured, and a cursor is returned for paging |
| P2 | `…/markets?status=settled&series_ticker=KXAAAGASM&min_settled_ts=1792653900&limit=2&mve_filter=exclude` | HTTP 200, 2 markets + cursor. `KXAAAGASM-25MAR31-US-3.25`: `result:"no"`, `settlement_ts:"2026-11-04T22:32:17.603672Z"`, `title:"Will average **gas prices** be above $3.25?"`, `rules_primary:""` | gas series resolves through the same call; **note** the literal `**` markdown and the empty rules text come from Kalshi — published as **F-25**, the title is printed verbatim and no rule link is invented |
| P3 | `…/markets?status=settled&series_ticker=KXBTCY&min_settled_ts=1792653900&limit=2&mve_filter=exclude` | HTTP 200, `{"cursor":"","markets":[]}` | an empty window is a normal 200 with an empty cursor — the scan must not treat it as an error, and does not |
| P4 | `…/markets?status=settled&series_ticker=KXELECTIRAN&min_settled_ts=1792653900&limit=1&mve_filter=exclude` | HTTP 200, `{"cursor":"","markets":[]}` | the curated elections series in `config/topics.json` has no settlement inside the 30-day window on the demo host; recorded, not padded |
| P5 | `https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDPWORLDTOUR-DPWTC26-THAT` | HTTP 200, `result:"yes"`, `settlement_value_dollars:"1.0000"`, `status:"finalized"`, `settlement_ts:"2026-11-15T14:56:17.490048Z"` | `yes` outcomes exist on the demo host, so a YES/NO page with only `no` rows would have been a coverage bug, not the market's doing |

An **unknown or unpopulated series is not an error** (P3, P4), so no `errors[]` entry is produced
for a quiet topic; a genuine failure is surfaced per series as `first_error` and a row in
`status.json.errors`, and previously published rows survive it.

## 4. What the code does now (after the collision with `arena-f642a30a`), and how each rule is tested

This session's own scan (helper trio `resolutionScanPlan` / `settledRow` / `scanSettledMarkets`) was
**discarded** when the rebase showed that `main` had already merged a settled-market scan for the
same file — `8b2606e`, session `arena-f642a30a`, task F642-T1, the same request R-4f92-4 that this
board had claimed. Two designs for one fix in one file is a worse outcome than one design plus a
patch, so the merged tree keeps theirs and adds only what their code still lacked.

| Rule | Owner in the merged tree | Enforced by |
| ---- | ---------------------- | ----------- |
| Rotating per-topic series slice, request-bounded; accumulate into `state.resolved`; `yes`/`no` only | `arena-f642a30a` (`rotateScanSeries`, `noteResolved`, `RESULT_VALUES`) — kept verbatim | their tests `settled-scan records official results…`, `rotateScanSeries covers every series across consecutive windows`, `pruneResolved keeps the newest per topic…` |
| Pending/watch list for markets that are closed but not yet determined | `arena-f642a30a` (layer b) — this session's draft did not have it | their test `pending rows survive a state wipe, are re-checked each run, then resolve yes` |
| Merging the previously published `resolved.json` back at startup, so history survives Actions state-cache eviction | `arena-f642a30a` (`loadPriorPublished`) — this session's draft did not have it | their test `resolution history survives a state-cache wipe via the published snapshot` |
| **Paging to the end of the cursor.** Their loop read page 1 and page 2 and stopped; the documented protocol is "pass the cursor exactly as returned … stop when the returned `cursor` is empty", so a series with more than two pages silently lost settlements inside a run | this branch | `the scan request is exactly the documented filter set, in the documented order` + `settled scan walks the cursor until it empties…` (5 pages, 10 tickers, last page asserted present) |
| **Hard per-run budget, published.** `RESOLUTION_SCAN_MAX_REQUESTS = 30`; `settled_scan_requests`, `_pages`, `_budget`, `_duplicates_deduped` go into `status.json` so truncation is visible rather than silent | this branch | same test asserts the four counters |
| **Dedupe by ticker inside a run.** The listing documents that a market "can be skipped or returned twice"; `state.resolved[ticker]` alone makes that invisible | this branch | `settled scan dedupes a ticker repeated across listing pages…` — the contradicting second copy (`result: 'yes'`) is asserted to lose, because the first observed official answer must not be re-decided |
| **Never rename a market title into an event title.** Their `resolutionRow` did `event_title ?? m.title`, so a market the desk never saw open published a market-level string in the field a reader trusts as the event name | this branch | `resolutionRow never renames a market title into an event title` (unit, 3 cases) + `settled scan dedupes…` asserting `event_title === null` and `market_title` verbatim |
| **Provenance per row.** `detected_by` + `request_url` (the exact listing URL that returned the row) beside their `via`; the watch path gets `request_url` too. Closes the same gap this session asked of the root pipeline as R-8A8-1 | this branch | the two new tests match the URL pattern, and `site/assets/app.js` renders the link plus the path name |
| `limit=100` (documented default; their code asked 200) and `mve_filter=exclude` | this branch | the documented-param test pins the key set and that `min_settled_ts` is 10 digits (seconds, not ms) |

**Mutation-checked on this tree** — each mutation applied to `scripts/collect.mjs`, the suite run, then
reverted and re-verified (15 pass):

| Mutation | Tests that failed | Verdict |
| -------- | ----------------- | ------- |
| `dupes++` dropped from the dedupe branch (dedupe kept, counter silently wrong) | `settled scan dedupes a ticker repeated across listing pages…` | the published counter is pinned, not decorative |
| pagination forced to stop after one page (`cursor = ''`) | `…walks the cursor until it empties…` **and** the dedupe test (its second page never arrived) | the fix for the two-page cap is pinned by two independent assertions |
| main's `eventTitle ?? m.title` fallback restored | `resolutionRow never renames a market title into an event title` **and** the dedupe test | the title rule is pinned at both the unit and the pipeline level |

Every line this branch added is therefore covered, and the eleven inherited tests still pass with
the changes in place — nothing inherited was weakened to make the new assertions pass.

## 5. Suites and site checks, run on the merged tree (final state of this branch)

| Command | Result |
| ------- | ------ |
| `node --test scripts/test/collect.test.mjs` | **15 pass, 0 fail** (11 inherited from `main` + 4 added here) |
| `npm test` | **64 pass, 0 fail** |
| `python3 -m unittest discover -s tests` | **334 run, OK (skipped=1)** |
| `python3 -m collector.test_runner` | `RUNNER TEST PASSED: {"series": 7, "markets": 7, "orderbooks": 7, "alerts": 7, "resolutions": 1}` |
| `python3 -m trading.test_engine` | `ALL TRADING TESTS PASSED` (fee formula vs every official table row) |
| `node scripts/build-site.mjs --out _site` | `built 13 pages into _site · links and config OK` — the flag-schema validator accepts F-24/F-25/F-26 |
| `python3 tools/linkcheck.py` | `pages=50 internal_links_checked=699 errors=0` |

The 12 → 1 skip difference in the python suite is itself a finding worth recording: with
`node_modules` absent, 11 jsdom-based browser-path tests skip silently and `npm test` still
reports success. Both tests added by this branch skip the same way (verified by moving
`node_modules` aside), deliberately, so a bare checkout is never red; on an installed tree they run.

## 6. What is **not** verified, and stays blank or flagged

| # | Item | Handling |
| - | ---- | -------- |
| U1 | The published `kalshi-dashboard/data/resolved.json` after the fix. A dispatch on this branch collected successfully but publishes only on `main`, and its per-line log output is unreachable from this sandbox (§11). | After merge, read `resolved_total` and the `settled_scan_*` counters from the next scheduled run's `status.json` — this session deliberately wrote no published data by hand |
| U2 | Whether every mapped series is scanned in one run. It is not, by design: 25 requests per run rotated across topics. | Stated on the page and in F-24 |
| U3 | `event_title` for a market the collector never saw open. The settled listing documents a market `title`, not an event title. | Published as `market_title`, labelled as such in the row's note; `event_title` stays null |
| U4 | Settlements older than the API's historical cutoff. | 30-day lookback only; F-24 says so |
| U5 | Any causal link between a ≥ $0.10 swing and a news article. | Still unsatisfied on every pipeline: `cause_link` stays `null`. No source in Kalshi's API maps articles to price moves, and inventing one would break the "never fill in a value" rule |
| U6 | Real demo-account balances, positions and order placement (brief R9/R11). | No credentials exist in this repo or session. The page side is now built and renders whatever `data/portfolio.json` contains, and says plainly when the file is absent; the credential is the only remaining blocker (F-08, status "blocked on owner") |
| U7 | `KXELECTIRAN`, `KXBTCY` settlements in the current window | empty responses (P3, P4) — published as empty, not padded |

## 7. Irregularities in the repo found by this session (besides the defect fixed)

| # | Finding | Disposition |
| - | ------- | ----------- |
| I-1 | `README.md` documents the second pipeline as `collector/` **(client.py**, runner.py, news.py, kalshi.py). `collector/client.py` does not exist; the client module is `collector/kalshi.py` (`runner.py` imports `from collector.kalshi import …`). | Fixed in this branch (one line); every other README claim about that pipeline was re-checked against the tree first |
| I-2 | Three independent pipelines publish near-identical content (root, `docs/`, `kalshi-dashboard/`) and their headline numbers disagree — the standing request **R-3DCF-4** from `arena-3dcf3f13` is still open, and this session's F-24 is another symptom (the same class of defect was fixed in `docs/` by X1 / PR #56 but not here). | Not restructured by this session: `site_build/**` and root pages are inside Board L's and PR #60's claims. Logged as a request to the integration session |
| I-3 | `board` letters collide across sessions (letters A–L are reused). | No change; `arena-1e3b2594` already raised it and suggested keying by session id. After `arena-737bff9c` published its own "# Board M" on `main` mid-rebase, this section was renamed **Board M8A8** and its ids to `8A8-1`…`8A8-4` so the two cannot be confused |
| I-5 | `scripts/collect.mjs` documents its rotation as "every 15 minutes" (`RESOLUTION_WINDOW_S = 900`) while `dashboard.yml` runs `cron: '*/30 * * * *'`, so a full sweep takes twice as long as the comment says. `main`'s README separately claims the collector runs every 5 minutes. | Not silently "fixed": the cadence is a deployment decision owned by the workflow, and the constant is inherited from the `docs/` pipeline. Recorded here so a reviewer decides which number is authoritative |
| I-4 | Kalshi's own demo data carries template/markdown artefacts (`**bold**` inside a market title, empty `rules_primary`). | Published as F-25 with the exact API URL, alongside the existing template-text finding |

## 8. Requests raised by this session (logged, not edited in other owners' files)

| ID | To | Request |
| --| --| ------- |
| **R-8A8-1** | owner of `collector/alerts.py` + `site_build/build.py` (root pipeline; inside PR #60's claim) | The root pipeline's `data/resolutions.json` and `docs/data/resolutions.json` should carry the same `detected_by` / `request_url` provenance this branch adds, so a reviewer can tell a scan row from a probe row. The root `docs/` scan (X1) already fixed coverage but publishes no provenance, so its rows cannot be re-checked with one click. |
| **R-8A8-2** | integration session | `README.md` documents two of the three pipelines (`collector`+`site_build`, and the `docs/` pipeline) but never mentions the `scripts/` + `site/` + `kalshi-dashboard/` pipeline that publishes at `/Trade2/kalshi-dashboard/`, nor `dashboard.yml`. Add a third block, or state which pipeline is canonical and deprecate the others — see I-2. |
| **R-8A8-3** | owner of `docs/assets/live.js` (WS live layer) | The live-probe workflow (`live-probe.yml`, last run [44804363290](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44804363290) at ~20:15Z 2026-11-20) writes `docs/data/capabilities.json`, which `live.js` uses to choose its live mode. On a repo with 5-minute collector churn that file goes stale silently; add an age warning on the page when `capabilities.json` is older than 24 h. |


## 9. Second board item: the demo-account portfolio block (commit `abd72ed`)

The brief asks for the portfolio performance of the Kalshi demo account on the site. Half of that was already built but never connected: `scripts/portfolio.mjs` can write a signed, read-only `kalshi-dashboard/data/portfolio.json`, and `dashboard.yml` already runs it when secrets exist — while the trades page ignored the file and printed a fixed "Not connected" card (F-20's second half).

Read against the two official pages before editing, line by line:

| Source | What it states, verbatim | How the code now behaves |
| ------ | ------------------------ | ------------------------ |
| [Get Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) | "Returns unsettled positions by default, including closed markets awaiting determination or settlement"; items carry `exchange_index`, `netting_enabled`; response carries `event_positions[]` and a `cursor` | `snapshot()` publishes all four instead of dropping them; the page renders an event-position table and says whether more pages sit behind the cursor |
| [Get Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance) | "Both values include all exchange indexes unless `exchange_index` is provided"; documented 200 shape `{balance: 123, balance_dollars: "0.5600", portfolio_value: 123, updated_ts: 123, balance_breakdown: [{exchange_index, balance}]}` — **no unit is given for the integer fields** | `balance_breakdown` is published; `portfolio_value_cents` was **removed** (it invented "cents"); the integers are published unconverted and the page labels them "published unconverted, because the endpoint does not state their unit" → **F-26** |

Three states are rendered and distinguished, because "no data" and "no access" are different facts: no `portfolio.json` at all · the file exists but says `connected: false` (its `reason` is quoted) · connected, with the snapshot time and environment. A missing value is a dash, never a zero. No order-placing code was added.

## 10. Third board item: in-browser live pulse on the alerts page (commit `480dd52`)

The two scrolling chats were only as live as `dashboard.yml`'s `*/30` schedule, so they went quiet for up to 30 minutes while markets moved. The alerts page now also measures in the visitor's browser.

| Rule | Basis | Enforced by |
| ---- | ----- | ----------- |
| One anonymous `GET /markets/orderbooks` per refresh, 45 s apart, capped at 100 markets | `tickers` is "Required array length: `1 - 100` elements" on [Get Multiple Market Orderbooks](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks) | `PULSE_CAP`, `PULSE_EVERY_MS`; the test asserts exactly one request per refresh and the repeated `tickers=` query shape |
| The ≥ $0.10 rule and the quote-integrity refusals are **not re-implemented** | the collector's rule lives in `assets/live-feed.js` (merged in PR #57) | the page loads that file at runtime (`loadScript('../assets/live-feed.js')`); if it cannot load, the panel says "unavailable" and retries at the next re-render instead of looking healthy while measuring nothing — logged as **R-8A8-4** |
| A live row is never presented as a collector row | the two have different reference bases | rows carry `live · browser poll`, "quote mid to quote mid", the executability verdict, and no cause link |
| CORS from this Pages origin is measured, not assumed | [docs/data/capabilities.json](https://github.com/wingbangboozle1-lang/Trade2/blob/main/docs/data/capabilities.json) records `access-control-allow-origin: https://wingbangboozle1-lang.github.io` on a demo-host GET, probed 2026-11-20T19:40:46Z by run [44804363290](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44804363290) | the page cites that file and its age in the panel text; the fallback route (`/api/orderbooks` on the site's own origin, served by `server/app.py`) is left to the root pipeline's desk |
| A ticker that is in the response but not tracked is an error, not a healthy refresh | the same failure mode the root desk guards against (a comma-joined `tickers` value reads as one ticker) | `throw new Error('no tracked ticker in response (N unmatched)')` |

`scripts/test/pulse.test.mjs` runs the real page in jsdom against **synthetic** fixtures and asserts both chats receive the row, the +13¢ mid step is computed from the two books, the High-ROI chat applies the *published* `config/topics.json` rule to the live quote, and the degraded path says "unavailable". Mutation check: removing the pulse rows from the merge kills test 1; restoring it makes 2/2 pass.

## 11. Actions confirmation of the shipped code

| Run | Ref · commit | Result |
| --- | ------------ | ------ |
| [44881459826](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44881459826) (workflow_dispatch, 07:42Z) | `arena/8a8d4294-trade2` @ `63d42ae` — the pre-rebase tree, which contained this session's own scan draft | **completed · success**, every step green: `npm test`, restore state, **collect public Kalshi demo data** (live requests to `https://external-api.demo.kalshi.co/trade-api/v2` from the runner — a host this sandbox cannot reach), save state, record run result, portfolio snapshot step (no secrets ⇒ skipped-with-message, non-fatal), **build site and check every internal link**. `Commit and publish to main` = `skipped`, correct for a non-`main` ref |

Two things are deliberately **not** claimed:

1. The post-rebase tree (`8718553` + 4 commits) has not been dispatched, because its only new
   collector code is the pagination/dedupe/title increment above, which is covered by unit tests
   against a mock, and the next `main` schedule will exercise it live within 30 minutes of the
   merge. The merge record below says which of these is true at the time of writing.
2. The per-line log content of any run. `gh run view --log`, `--log-failed` and
   `GET /actions/jobs/{id}/logs` all fail from this sandbox with a TLS/EOF error because the log
   blob host (`productionresultssa4.blob.core.windows.net`) is outside the egress allowlist. So the
   *existence* of a green live-request run is verified through the API's per-step conclusions, while
   the per-series request counts inside it are not — U1 stays open and must be read from
   `status.json` after the merge, not assumed from here.

## 12. New request raised while wiring the pulse

| ID | To | Request |
| --| --| ------- |
| **R-8A8-4** | owner of the root pipeline's `assets/desk.js` (PR #60's claim) | The root desk implements the same browser pulse independently. This branch now reuses the shared `assets/live-feed.js` from `kalshi-dashboard/`, which closes **R-F3-3** ("keep one copy of the ≥ $0.10 rule"). Two things are still worth doing there, and both are in files this session must not edit: move `live-feed.js` to a location both sites can reference without a relative `../`, and let the desk's `capabilities.json` age warning (R-8A8-3) gate the pulse, not only the WS layer |
