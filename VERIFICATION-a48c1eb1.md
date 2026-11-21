# VERIFICATION — session `arena-a48c1eb1` (final integration, 2026-11-21)

Branch `arena/a48c1eb1-trade2`. Every value below was read from the source named
in its row during this session (fetch-tool reads of the official demo API and of
the repository); nothing is filled from memory. Where a value could not be
confirmed it is left blank and marked UNVERIFIED.

## 1. Live spot-checks against the official demo API

All fetches performed 2026-11-21 between 06:43Z and 07:50Z via the platform
page fetcher (the sandbox shell has no route to Kalshi hosts — see
`COORDINATION.md` irregularity I3).

| # | Published value (page / file) | Official API read | Result | Source URL |
| - | - | - | - | - |
| V-1 | `exchange_active` / `trading_active` shown as live on the desk | `exchange_active:true`, `trading_active:true` on all four exchange indexes | **match** | https://external-api.demo.kalshi.co/trade-api/v2/exchange/status |
| V-2 | Fee item: demo `GET /series/KXBTCY` returns `fee_multiplier` 1 (stated on `review.html`, re-checked wording this session) | `{"fee_type":"quadratic","fee_multiplier":1}` | **match** | https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY |
| V-3 | Overview row `KXPGATOUR-THRC26-MPEN`: YES bid **$0.0830**, YES ask **$0.0880**, OI value 419,786.51 | `yes_bid_dollars:"0.0830"`, `yes_ask_dollars:"0.0880"`, `open_interest_fp:"419786.51"` | **exact match** | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-MPEN |
| V-4 | Overview row `KXBTCY-27JAN0100-B47500`: YES bid **$0.0900**, YES ask **$0.1000**, OI value 26,578,902.61 | `yes_bid_dollars:"0.0900"`, `yes_ask_dollars:"0.1000"`, `open_interest_fp:"26578962.11"` | quotes **exact**; OI differs by 59.50 contracts (0.0002 %) — inside the published 2 % live-drift tolerance (a live book moves between snapshot and check) | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B47500 |
| V-5 | `resolutions.html` row `KXNATGAS15M-26NOV200900-00`: **YES**, $1.0000, settled 2026-11-20 14:00:24 | `"result":"yes"`, `"status":"finalized"`, `settlement_value_dollars:"1.0000"`, `settlement_ts:"2026-11-20T14:00:24.608234Z"` | **exact match** | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXNATGAS15M-26NOV200900-00 |
| V-6 | Candlestick source link published on `review.html` for the alternating-trade item | 3 daily candles returned; last (`end_period_ts` 1795237200) close 0.8820 / low 0.0030 — the erratic demo prints the item describes | **source reachable, data shape confirmed** | https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-BOBA/candlesticks?start_ts=1794983000&end_ts=1795243400&period_interval=1440 |
| V-7 | Candlestick example cited in `VERIFICATION-1e3b2594.md` (KXPGATOUR-THRC26-TMOO, 60-minute) | 2 candles returned; second has `yes_ask.high_dollars:"1.0000"` with close 0.0050 | **source reachable, prior citation reproducible** | https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/markets/KXPGATOUR-THRC26-TMOO/candlesticks?start_ts=1795200000&end_ts=1795207200&period_interval=60 |
| V-8 | Anonymous browser WebSocket handshake is refused (site never claims WS liveness) | not re-run this session; capability probe evidence retained from `docs/data/capabilities.json` (run 44804363290) | carried forward, see `docs/data/capabilities.json` | https://docs.kalshi.com/getting_started/quick_start_websockets |

## 2. Repository line-by-line checks (this session's merged tree)

| Check | Command | Result |
| - | - | - |
| Unit suite | `python3 -m unittest discover -s tests` | **250+ OK, 1 skipped** (grew to include peers' tests after each main merge; final run on the merged tree: OK) |
| Collector fixtures | `python3 -m collector.test_runner` | **PASSED** (series 7, markets 7, orderbooks 7, alerts 7, resolutions 1, errors 0) |
| Trading engine + fee table | `python3 -m trading.test_engine` | **ALL PASSED** |
| Front-end unit tests | `npm test` | **59 pass / 0 fail** |
| Desk JS syntax | `node --check assets/desk.js` | OK |
| Offline render of every root page | `node tools/root_pages_render.mjs` | **ALL PASS — 13 pages, 272 files linked** |
| Internal links | `python3 tools/linkcheck.py` | **50 pages / 698 internal links / 0 errors** |
| Generated-page render check | `node tools/rendercheck.mjs` | 13 ok / 0 fail |
| Desk render contract (browser path) | `node test/desk_render_dc732aa6.mjs` | **PASSED** (after the model-chat priority fix; contract extended for the order-book side-car) |
| Site smoke (jsdom) | `npm run test:site` | **ALL PASSED** |
| Docs live layer | `node tests/test_docs_live.mjs` | **ALL PASS** |
| Generator determinism | `python3 -m site_build.build` twice, md5 compare | identical; the only wall-clock element across time is the snapshot-age label (by design) |
| Negative-money form | `grep -rln '\$-' --include='*.html'` | **no hits** (root + docs pages) |
| Conflict markers | repo-wide grep | **no hits** |

## 3. Defects found and fixed during this integration

| # | Defect | Fix | Proof |
| - | - | - | - |
| D-A1 | Merged model chat rendered order-book shortlist rows **and** signal rows together (6 rows where 3 were published) | `assets/desk.js`: priority = side-car rows + uncovered gated alerts → else gated → else signals (top 8) → else empty | `test/desk_render_dc732aa6.mjs` extended and green |
| D-A2 | `collector/shortlist.py` reasons printed `$-0.0182` (banned inner-sign form) | `_usd()` helper (main's PR #60 version is authoritative; this session's duplicate helper dropped) + stored `data/shortlist.json` reasons corrected, values unchanged | site-contract test green; HTML sweep clean |
| D-A3 | `review.html` / `methodology.html` claimed the ledger "applies M = 1 everywhere … until the engine threads the value through" — false since PR #54 threaded `fee_multiplier` (request **R-1E3-2**) | texts rewritten to the verified behaviour (fee_params → `GET /series`, entry+exit threading, 1 only when absent); KXBTCY PDF-vs-API disagreement kept with both official links | V-2 above; `tests/test_site_contract.py` pins updated to the true texts |
| D-A4 | `tools/strategy_lab.py` money() emitted `$-155.00` (request **R-79CC-5**) | sign outside the symbol; `STRATEGY_ANALYSIS.md`, `docs/strategies.html`, `docs/data/strategy_lab.json` regenerated offline | HTML sweep clean; regen deterministic apart from `generated_at` |
| D-A5 | Published root pages were stale relative to the committed snapshot (site-check advisory drift) | regenerated with `python3 -m site_build.build` on the merged tree | generator output committed; only the wall-clock age label moves afterwards |

## 4. Integration handling (transparency)

* **PR #28** (`arena/dd1da6b5`, stale >10 h): this session independently merged
  and verified it (commits `d2c78d1`, `1242f24`, `8d32d23`) before discovering
  that session `arena-bc051b95` was doing the same. Their **PR #60 landed first**
  with equivalent resolutions (same desk-chat priority, same `$-` fix, same fee
  texts — independently converged). This branch then merged main and kept **only
  the unique pieces**: the R-79CC-5 strategy-lab fix + regenerated outputs, the
  claim/record section in `COORDINATION.md`, and page freshness. Nothing from
  PR #60 was discarded.
* **PR #29** was merged by its own session (2026-11-21T07:16Z) — not touched here.
* Conflicts with main were resolved union-style in `COORDINATION.md` (every peer
  board kept verbatim) and by taking main's verified versions everywhere else.

## 5. Standing limitations (unchanged, published on `review.html`)

No Kalshi demo API credentials exist in this repository, so demo-account
portfolio reads and order execution remain **UNVERIFIED** and are flagged on the
Flagged-for-Review page; the site runs on public demo market data plus a clearly
labelled simulated ledger. WebSocket liveness is not claimed (anonymous WS
handshake is refused by the official API — see `docs/data/capabilities.json`).
