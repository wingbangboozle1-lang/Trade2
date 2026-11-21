# Verification record — session `arena-282a1080` (Board L)

Branch `arena/282a1080-trade2`, final base `main` @ `0ec1e12` (2026-11-21T07:35Z
collector run). Claimed scope: the open requests left by earlier boards —
R-F3-2 (Board K), R-3DCF-2, R-3DCF-3, R-3DCF-6 (Board `arena-3dcf3f13`) — plus
plumbing completion for the R-F3-1 implementation that merged mid-flight, the
standing gates, and the PR/merge/Pages confirmation. This file records every
official source checked, every code change, and every gate result.

## 0. R-F3-1 race — what happened, and what this session shipped

This session claimed R-F3-1 at commit `1621d43` (authored 2026-11-21T07:14:36Z,
pushed immediately) and implemented a **label-only** cross-check. While the
branch was in flight, session `arena-662e1ce8` claimed the same request
(commit `4010642`, authored 07:30:03Z) and opened PR #72 with a
**suppressing** corroboration (`REFERENCE_TRADE_TOLERANCE`); that PR merged to
`main` via the PR #60 integration branch (commit `2257b63`) before this branch
could merge.

Per the board's first-claim rule this session had priority, but re-litigating a
guard that is already merged would churn the tree and force a re-verification
of every published row — the exact concern Board K raised when it declined to
implement the change itself (K4). This session therefore **dropped its own
R-F3-1 variant** and, instead of duplicating the merged guard, completed its
plumbing: the merged code reads `Observation.ref_previous_dollars`
("price.previous_dollars (trade price at the start of the reference bar)"),
but on `main` nothing supplied that field — `bar_reference()` published no
`previous_dollars` key and the collector's reference-attachment block never
assigned it, so the merged guard could only ever fall back to
`price.close_dollars`. This branch wires `price.previous_dollars` through
`bar_reference()` → the reference record → `collect()` → the observation, so
the merged guard runs on the documented basis it was written for. Tests:
`tests/test_board_l_282a1080.py::TestReferencePlumbing` (4 cases, each failing
on pre-change `main`).

## 1. Official sources checked in this session (fetched directly, 2026-11-21 UTC)

The sandbox has no HTTP egress to kalshi.co (standing limitation, VERIFICATION.md
§D4 / flag F-06), so the doc pages were fetched through the platform doc-fetcher.

| # | Claim | Official source | Where used | Result |
| - | ----- | --------------- | ---------- | ------ |
| S1 | Candlestick payload carries a `price` block with `open_dollars`, `close_dollars`, `mean_dollars`, **`previous_dollars`**, `min_dollars`, `max_dollars`; `yes_bid` / `yes_ask` blocks carry `open/low/high/close_dollars` | https://docs.kalshi.com/api-reference/market/get-market-candlesticks (response schema reproduced verbatim on the page) | `bar_reference()` now publishes `previous_dollars`; revert check uses the completed candles' `price.close_dollars` | **Verified** — field name taken verbatim from the schema |
| S2 | `period_interval` valid values are `1` (1 minute), `60` (1 hour), `1440` (1 day) — "Time period length of each candlestick in minutes" | same page (query parameter description) | desk.js window labels / chart-note caption | **Verified** — no second-based candles exist, the factual basis of L5's caption |
| S3 | Demo REST roots `https://external-api.demo.kalshi.co/trade-api/v2` and `https://demo-api.kalshi.co/trade-api/v2` listed as the demo environments | same page ("Try it" base-URL list) | unchanged; re-confirmed | **Verified** |
| S4 | Market schema `market.price_ranges[].step` — "Price step/tick size for this range in dollars" (string, required) | https://docs.kalshi.com/api-reference/market/get-market (schema key `market.price_ranges.items.[INDEX].step`) | `observe()` reads `price_ranges[0].step` into `Observation.tick_size`; `threshold_in_ticks()` divides the $0.10 threshold by it | **Verified** |
| S5 | Prior-verified facts relied on unchanged: orderbook bids-only shape and implied YES ask, settlement $1-per-contract, quote-mid basis rule, the merged corroboration guard | VERIFICATION.md, VERIFICATION-f3cb9b9f.md, VERIFICATION-662e1ce8.md (merged with main) | unchanged code paths | **Asserted by the suites** (345 tests) |

## 2. What was implemented (request → change → test)

### L1b — plumbing completion for the merged R-F3-1 guard

* `collector/collector.py::bar_reference` publishes the chosen candle's
  documented `price.previous_dollars` under `previous_dollars` and the
  completed candles it already fetched (same single request — no extra API
  calls). `collect()` attaches it to observations (`obs.ref_previous_dollars`).
* No behavioural change to the guard itself — it is owned by the merged
  implementation; this only lets it run on the documented basis it was written
  for. `mark_reverted` (L3) consumes the same `candles` list.
* Tests: `::TestReferencePlumbing`.

### L2 — R-F3-2: tick size (`price_ranges[0].step`)

* `observe()` reads the documented step into `Observation.tick_size`;
  `threshold_in_ticks()` returns `round(threshold / tick, 1)` or `None`.
* Alert rows carry `tick_size` + `threshold_ticks`; event rows (`rank_events`)
  carry `tick_size`; `site_build/build.py::alert_chat_row` and `assets/desk.js`
  render "$0.10 ≈ 10 ticks of $0.0100" when the tick is known and render
  nothing when it is not — never inferred.
* Tests: `::TestTickSize` (6 cases).

### L3 — R-3DCF-3: "reverted within one candle"

* `mark_reverted()` — for each stored alert, the first completed candle
  strictly after its reference bar (or observation time) is "the next candle";
  when that candle's documented trade close is back within $0.10 of the
  alert's previous level the row gains `reverted_within_candle`
  `{candle_end_ts, trade_close, previous_level, check_basis}`. A once-measured
  revert is kept (a fact, not a state).
* `collect()` runs it over the folded buffer each run and reports
  `alert_stats.reverted_annotated_this_run`. The reference window stays at the
  existing 3 × BAR_SECONDS (15 minutes of 1-minute candles per request) — it
  spans two collector runs, so no extra API cost.
* Render: `alert_chat_row` and the desk.js client render add a
  "reverted within one candle" badge with the candle timestamp in the tooltip.
* Tests: `::TestMarkReverted` (5 cases, incl. the 3dcf3f13 example
  0.17 → 0.39 → next candle 0.17).

### L4 — R-3DCF-2: explicit-zero ask size

* When `size_at_top` is an explicit `0` the rows read "no ask size: 0
  contracts resting at the level" (server render + desk.js client path).
  `None` keeps the published wording "no resting size at the level" — a render
  contract pinned by `tests/test_site_render_dc732aa6.py`, left untouched.
* Tests: `::TestAskSizeAndWindowRendering` (3 cases).

### L5 — R-3DCF-6: window labels state data granularity

* The brief asks for seconds/minutes/hours x-axis windows, so the tab words
  stay; the desk now states what each window's data **is**: tooltips on the
  tabs, a `chart-note` caption under the tabs ("Window lengths, not candle
  sizes… smallest period is 1 minute" with the candlesticks docs link), and
  `WINDOWS` labels in `assets/desk.js` ("Last 90 seconds · live book quotes",
  "Last 60 minutes · 1-minute candles + live quotes", "Last 12 hours ·
  1-minute candles + live quotes").
* **Deviation from the request's literal wording, logged:** R-3DCF-6 asked to
  relabel the seconds window as "1-minute candles". That would be factually
  wrong — the seconds window demonstrably plots live polled book quotes
  (2-second ticks, `desk.js::pollBook`), not candles (Board K re-verified this
  in K1). The honest label states both facts. Source: S2 above.
* `assets/styles.css` gained a `.chart-note` rule (scope addendum, logged in
  COORDINATION.md).

## 3. Files touched by this session

`collector/alerts.py`, `collector/collector.py`, `site_build/build.py`,
`assets/desk.js`, `assets/styles.css` (addendum), `tests/test_board_l_282a1080.py`
(new, 22 tests), regenerated root pages (outputs of `site_build.build` on
main's snapshot), `VERIFICATION-282a1080.md` (this file), `COORDINATION.md`
(claim + record). Not touched: `docs/**`, `kalshi-dashboard/**`, `live/**`,
`trading/**`, `scripts/**`, `EXECUTIVE_SUMMARY.md`, `VERIFICATION.md`,
`collector/runner.py`, `collector/news.py`, `.github/workflows/*`.

## 4. Gates (final run on the rebased branch, base `0ec1e12`)

| Gate | Result |
| - | ---- |
| `python3 -m unittest discover -s tests` | **345 run, OK, 0 skipped** (22 new tests are Board L's; `npm ci` for jsdom and `cryptography` installed locally) |
| `npm test` | **59 pass, 0 fail** |
| `node --test test/live-feed.test.mjs` | **18 pass, 0 fail** |
| `python3 -m site_build.build` | clean exit 0 |
| `python3 tools/linkcheck.py` | **50 pages, 698 internal links, 0 errors** |
| `node tools/rendercheck.mjs` | PASSED |
| `node test/root_render.mjs` | PASSED |
| `node test/desk_render_dc732aa6.mjs` | PASSED (render contract re-verified against the new wording) |
| fixture `site_smoke` (`test/gen_fixtures.py` + `node test/site_smoke.mjs`) | ALL SITE SMOKE CHECKS PASSED |
| `python3 -m collector.test_runner` | PASSED (docs pipeline unaffected) |
| `python3 -m trading.test_engine` | ALL TRADING TESTS PASSED |
| `python3 tools/rowsource_check.py` | exit 0 — **0 rows missing a source URL, 0 production-host leaks** |

Earlier runs in this session (pre-rebase) additionally passed with the
label-only R-F3-1 variant: 289 then 322 tests OK, npm 54, linkcheck 679/0.
Those variants are no longer part of this branch.

## 5. Irregularities and pre-existing observations (logged, not hidden)

| # | Observation | Handling |
| - | ----------- | -------- |
| I-1 | R-3DCF-6's literal wording ("relabel seconds as 1-minute candles") conflicts with the desk's own measured behaviour (the seconds window plots live polled quotes). | Implemented the honest variant; deviation recorded here and in COORDINATION.md. |
| I-2 | The merged R-F3-1 guard could never see `price.previous_dollars`: nothing supplied `Observation.ref_previous_dollars` on `main` (its own test constructs the observation by hand). | **Fixed by this branch** (`TestReferencePlumbing`); the guard now runs on the documented basis its comments describe. No guard behaviour changed beyond what the merged implementation defines. |
| I-3 | First-claim race on R-F3-1: this session's claim commit (07:14:36Z) predates `arena-662e1ce8`'s (07:30:03Z), but their PR merged first via the PR #60 integration. | Dropped this session's label-only variant; kept the merged design; recorded in COORDINATION.md so the history is auditable. |
| I-4 | `kd.markets` publishes rows with blank `last_cents` (markets with no last-trade price in the third pipeline's snapshot) — by-design UNVERIFIED blanks, each row still carrying its demo API source link. | Pre-existing; no change (out of scope). |
| I-5 | Standing blockers unchanged: demo-account portfolio and order placement need a Kalshi demo key pair (FL-01/FL-18/G1/G2); news attribution stays "candidate, not confirmed" (G4/R17). | Restated; nothing new claimed. |

## 6. PR / merge / Pages record

Recorded at the bottom of this session's COORDINATION.md section once the pull
request is merged and Pages is confirmed deployed.
