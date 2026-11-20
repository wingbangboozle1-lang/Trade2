# Verification log — session `arena-dc732aa6` (2026-11-20 UTC)

Scope: the defects listed in `COORDINATION.md` board D (tasks D1–D5) and the request
**R-D-01** raised by `arena-0b2d2a2a` in `AUDIT_ADDENDUM.md`. Every claim below is
either (a) code with a passing test, (b) a value read from an official Kalshi page or
the official demo API, or (c) explicitly marked unverified. Nothing was inferred.

## 1. Official sources read during this session

| # | Source | What it proves | Where used |
| - | - | - | - |
| V1 | https://docs.kalshi.com/api-reference/market/get-market-candlesticks (fetched 19:05Z) | The candlestick object publishes `yes_bid.{open,low,high,close}_dollars`, `yes_ask.{…}_dollars` **and** `price.{…}_dollars`; `period_interval` is documented as minutes with valid values **1, 60, 1440**; `start_ts`/`end_ts` required; docs cap 5,000 periods | The reference price for a swing is now the candle's **quote** closes, never the last-trade close (`collector/collector.py:bar_reference`) |
| V2 | https://docs.kalshi.com/api-reference/market/get-markets (fetched 19:07Z, chunks 0 and 1) | Market object fields include `yes_bid_dollars`, `yes_ask_dollars`, `yes_bid_size_fp`, `yes_ask_size_fp`, `last_price_dollars`, `previous_yes_bid_dollars`, `previous_yes_ask_dollars`, `previous_price_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `notional_value_dollars`, `result`, `status`; `status` filter options are `unopened, open, paused, closed, settled` | The fallbacks in `alerts.observe()` and the record side of the book-vs-record check read only these documented fields |
| V3 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID (fetched 19:16Z, live) | `last_price_dollars 0.8110`, `yes_bid_dollars 0.0020`, `yes_ask_dollars 0.0030`, `no_bid_dollars 0.9970`, `open_interest_fp 140195146.86`, `volume_fp 537225539.60`, `volume_24h_fp 8077.73`, `notional_value_dollars 1.0000`, `status "active"`, `result ""`, `price_level_structure "deci_cent"` | Fixture in `tests/test_alert_quality_dc732aa6.py::TestBookAgainstRecord`; proves the −$0.4045 "swing" was a book-vs-record artefact, not a trade |
| V4 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID/orderbook (fetched 19:16Z, live) | `yes_dollars` tops out at `["0.0020","83333.33"]`; `no_dollars` runs up to `["0.1890","215.44"]` → implied YES ask `1 − 0.1890 = 0.8110` | Same fixture: book mid `0.4065` vs record mid `0.0025`, gap `0.4040` — published as a **book-vs-record disagreement**, not as a price |
| V5 | https://docs.kalshi.com/getting_started/orderbook_responses (cited by prior sessions; re-read for the bid-only rule) | Books return **bids only**, ascending; best bid is the last element; a NO bid at `p` is a YES ask at `1 − p` | `best_bid`, `implied_yes_ask`, `mid_price` in `collector/kalshi_api.py` (unchanged) and the "Bids only" footnotes on the topic pages |
| V6 | https://docs.kalshi.com/getting_started/api_environments | Demo REST `https://external-api.demo.kalshi.co/trade-api/v2`; demo WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; also-supported `https://demo-api.kalshi.co/trade-api/v2` | `collector/kalshi_api.py:DEMO_REST` is the recommended demo host; the published payload carries `api_root` and every page links to it |
| V7 | https://kalshi.com/docs/kalshi-fee-schedule.pdf (via `tests/test_engine.py`, which asserts all 42 published table rows) | Taker fee `ceil(0.07 × C × P × (1−P))` in cents | The net-ROI figure in the model shortlist (`clears_model_gate`) |
| V8 | https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule | Scheduled workflows are best-effort and can be delayed | Wording of suggestion 2 on `suggestions.html`; the "snapshot is not a tick" age label |

The brief's own URL forms were re-checked against V6: the brief writes
`wss://[external-api-ws.demo.kalshi.co/trade-api/ws/v2](…)` — the bracket/markdown
artefact is not a valid URL; the canonical form in V6 is used.

## 2. Line-by-line: what changed, and the check that proves it

| Change | File | Verification |
| - | - | - |
| One alert row per (market, direction, reference bar); repeats fold into it and count themselves; a later bar only opens a row when the move grows by ≥ $0.10; reversals always get a row | `collector/alerts.py:fold_alerts`, called from `collector/collector.py` | `tests/test_alert_quality_dc732aa6.py::TestFoldAlerts` (7 tests: same-bar fold, bigger-move replace, sustained-move fold, escalation, reversal, bounded+sorted buffer, legacy rows without keys preserved) |
| Swing reference is the candle's **quote** mid (`yes_bid.close_dollars`, `yes_ask.close_dollars`), with `price.close_dollars` returned but never used as a basis | `collector/collector.py:bar_reference` | `TestBarReference` (asserts `mid == 0.31` and *not* the 0.25 trade close) + `tests/test_alerts_basis.py` (other session's 15 tests, still passing) |
| Every alert states `reference_basis`, `spread`, `size_at_top`, `quality` and `quality_reason`; a move with no size at the level is labelled `indicative` | `collector/alerts.py:_swing` | `TestPriceBasis`, `TestExecutability`, `TestPayloadContract` (all rendered keys asserted) |
| Midpoint moves that the quote rule refuses are **published with their reason**, not dropped | `collector/alerts.py:swing_rejection` → `live.json:suppressed_alerts` → `site_build/flagpage.py` | `TestPriceBasis.test_last_trade_reference_is_never_an_alert_but_is_reported`, `TestExecutability` refusals, `tests/test_site_render_dc732aa6.py::TestFlaggedPage` |
| Candidate headlines attached to new/escalated swings only, capped at 6 lookups/run, blank + reason when unavailable | `collector/collector.py:attach_news`, `collector/news.py` (previously **dead code** in this pipeline) | `TestNewsLookup` (window filter, offline failure returns `[]`, never an exception) |
| Untrusted RSS URLs are http(s)-only in the generator **and** the browser | `site_build/format.py:safe_url`, `assets/desk.js:safeUrl` | `tests/test_site_render_dc732aa6.py::test_no_html_injection_from_api_supplied_text` — this test found the hole (a `javascript:` href was emitted before the fix) |
| One model gate (`net_roi ≥ 0.05`) for generator, payload and browser | `collector/alerts.py:MODEL_MIN_NET_ROI`, `clears_model_gate`, `high_roi_alerts`; `assets/desk.js` reads `snapshot.high_roi_alerts` | `TestModelFeed` (boundary inclusive, indicative excluded, weak signal empties rather than pads) + `test/desk_render_dc732aa6.mjs` check "model chat uses the published shortlist, not a client-side re-gate" |
| Book-vs-record divergence published per market (new, from V3+V4) | `collector/alerts.py:book_record_divergence` → `review.html#book-vs-record` | `TestBookAgainstRecord` (4 tests, values copied from the live responses) |
| Snapshot age shown on every page; amber past 10 minutes; missing 2D context no longer aborts boot | `site_build/build.py:topbar`, `assets/desk.js:showAge/drawChart` guard | `test/desk_render_dc732aa6.mjs`: "snapshot age label is computed from the payload timestamp", "a stale snapshot is announced as stale", "a missing canvas does not take the chats down with it" |
| Overview gains the second (model) chat; topic pages gain their own swing feed | `site_build/build.py:build_overview`, `build_topic` | `tests/test_site_render_dc732aa6.py::TestFoldedBufferNarration`; `node tools/rendercheck.mjs` (10/10 pages render, no `undefined`/`NaN`/`[object Object]`) |
| `suggestions.html` — six prioritised suggestions, each with the number that motivates it and what blocks it | `site_build/build.py:build_suggestions` | built page + link check; every claim in it is a pointer to V1–V8 or to a field in the snapshot |

## 3. Automated checks run on this branch (final state)

| Command | Result |
| - | - |
| `python3 -m unittest discover -s tests` | **119 tests, OK (1 skipped)** — the skip is the RSA-signing test, which needs the `cryptography` package that is not installed here (pre-existing, unchanged) |
| `npm test` | **29/29 pass** (fee, auth, collect, breaker, and the `alerts-view` parity suite) |
| `node test/desk_render_dc732aa6.mjs` | **24 checks pass** — three passes: the published snapshot, a fixture snapshot that exercises every row rule, and the same fixture with no 2D context |
| `python3 tools/rendercheck.mjs` | **13/13 pages ok** (now globs every generated page, so `suggestions.html`, `resolutions.html` and `trades.html` are covered too) |
| `python3 tools/linkcheck.py` | 48 pages, 621 internal links, **0 errors** |
| `python3 -m collector.test_runner` | PASS (`{"series": 7, "markets": 7, "orderbooks": 7, "alerts": 7, "resolutions": 1}`) |
| `python3 -m trading.test_engine` | PASS (fee table, positions, settlement, analytics) |
| `python3 -m site_build.build`, `node --check assets/desk.js` | clean |

## 3a. Merge with PR #21 (`arena-fb6cb424`) — what was kept, what was dropped

`git pull --rebase origin main` landed in the middle of another session's site
integration. Two sessions had built the same layer; the resolution is recorded here so
no work is silently lost.

| This session's piece | Outcome |
| - | - |
| Collector semantics (fold rule, price basis, executability verdict, published refusals, single model gate, news lookup, `book_record_divergence`) | **kept** — no other session implemented these in the engine |
| `safe_url` / `safeUrl` scheme allowlist on every third-party `href` | **kept**, and extended across `site_build/format.py` → `build.py` + `extras.py` + `assets/desk.js` (their renderer was the one inserting `market_url` from the payload unchecked) |
| Row-level basis / spread / depth / verdict / candidate-headline line | **kept**, written *into* `extras`-style renderer (`alert_chat_row` and its browser mirror) rather than as a parallel renderer |
| Published shortlist as the only model gate (`model_shortlist()` in the generator, `state.snapshot.high_roi_alerts` in the browser) | **kept** — replaced the two client-side `>= 0.05` re-gates |
| Empty feed pointing at `review.html#refused` when moves were refused | **kept** |
| This session's `suggestions.html`, `.chat-meta`/`.q-badge` CSS, standalone `#snapAge` label, `data-snapshot` attribute, client-side `×K sightings` renderer | **dropped in favour of PR #21's equivalents** (`extras.build_suggestions` cards, `.cause-links`, server-rendered `#snapshotAge` + `AlertsView.ageLabel`, `extras.group_alerts` with `tests/test_alerts_view_parity.py`) — duplicated renderers are how the polled and pre-rendered views start disagreeing |
| `assets/alerts-view.js`, `AUDIT_ADDENDUM.md` (owned by `arena-0b2d2a2a`) | **not edited**, used as evidence; the client-side dedupe they added is kept as a second safety net |

Two off-by-one notes for the owners of the display grouping (not edited here, per the
board rules): `extras.group_alerts` / `alerts-view.dedupeAlerts` reset `repeat_count`
to 1 on the first sighting, so a row that arrived already folded by the collector
displays one fewer sighting than the engine counted, and its grouping key is
`ticker|direction|previous|current` where the engine's is
`ticker|direction|bar_start`. Both are display-only; the engine's buffer is unchanged.

## 4. Irregularities found by this session (all published on `review.html`)

| # | Finding | Status |
| - | - | - |
| N1 | The published alert buffer held 29 rows for 8 distinct moves — one sustained swing re-fired on every run because ids carry the run timestamp | fixed (fold rule) + standing item on the flagged page |
| N2 | **The demo order book and the demo market record disagree on the same market**: for `KXPRESNOMD-28-HBID` at 19:16Z the book implies a YES ask of `0.8110` (mid `0.4065`) while `yes_ask_dollars` says `0.0030` (mid `0.0025`) — a $0.4040 gap at one instant. Kalshi-side data quality, not ours | published as a new "Kalshi's order book and its market record disagree" table with both source links per row; not silently resolved in favour of either endpoint |
| N3 | The alert engine's reference was a *trade* close compared against a *quote* mid (fixed in PR #14 by `arena-856e184e`); this session added the executability verdict and the refusal publication on top | merged: both sessions' rules are in `collector/alerts.py` and both test suites pass |
| N4 | `collector/news.py` was written but never called by the root collector, so the brief's "links that may have caused the jump" was unimplemented on the deployed site while the flagged page said it was deliberately absent | fixed; the stale "no news article is attributed" wording was replaced by what the code now does |
| N5 | The server gated the model shortlist on `score ≥ 0.10` while the browser gated it on `net_roi ≥ 0.05` — the same feed, two definitions | fixed (one constant) |
| N6 | `drawChart` assumed a 2D context; a browser (or harness) without one threw inside `boot()`, which would have taken the chat feeds down with it | fixed (guard + shared metric renderer) and asserted by a test |
| N7 | Third-party news URLs were inserted into `href` without a scheme check (found by my own new test, not by a reporter) | fixed in both renderers |
| N8 | The root snapshot's cadence: at 19:16Z the published snapshot was 35 minutes old even though the workflow is `*/5` | not a bug in our code — GitHub scheduling is best-effort (V8); mitigated by showing the age instead of implying liveness |

## 5. Left blank / unverified on purpose

| Item | Why it is not filled in |
| - | - |
| Real demo-account balances, positions, fills, order placement | No API key pair exists in this repository and none was provided; the adapter is code-complete and unit-tested against a mock only. Marked on the flagged page and in suggestion 5. |
| Whether the news RSS lookup returns *useful* headlines for a given swing | The lookup only runs where egress is allowed (GitHub Actions). Locally, with egress blocked, `headlines_near` returns `[]` and the row prints "no verified news link · not looked up this run". No headline is claimed until it comes back from a real run. |
| Whether any headline *caused* a move | Never claimed. Rows say "possible catalyst, not confirmed". |
| `kalshi-dashboard/` and `docs/` alert semantics | Their alert paths measure trade prices; PR #14 flagged them and their owners have not merged a change. This session did not edit those pipelines (board rule), and the item stays on the flagged page. |
| ROI of the model as a predictor | Still a screen, not a validated edge. Realised outcomes (including losses) are the only performance claim, on the summary page. |
