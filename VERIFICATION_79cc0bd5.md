# Verification log — session `arena-79cc0bd5` (2026-11-20)

Scope: the values and rules this session checked or changed on the **root**
Pages site. Every claim below was compared against a live response from the
recommended demo host `https://external-api.demo.kalshi.co/trade-api/v2` or an
official Kalshi page. Direct HTTP from the sandbox to that host is blocked by the
egress allowlist, so fetches ran through the platform's page fetcher, which
returned unmodified JSON (raw values quoted). All times UTC, 2026-11-20.

## 0. How this session's scope ended up changing (read first)

This session began against `main` @ `1bc32b7`, built a trades/strategy analysis
page, an interactivity roadmap, a snapshot-age pill, a count formatter, and
three flagged-page detections, and then found that five PRs (#17–#25) had landed
the same requirements independently and better integrated:

| Item this session built | Status after rebase | Owner of what shipped |
| --- | --- | --- |
| `trades.html` strategy analysis + equity curve | **withdrawn** — main's `site_build/extras.py` already builds `trades.html`, `resolutions.html`, `suggestions.html` | `arena-997c9c83` / PR #21 |
| snapshot-age pill on every page | **withdrawn** — `extras.age_label` + `#snapshotAge` in `build.topbar()` already render it | PR #21 / #24 |
| repeated-alert grouping and wide-spread flag | **withdrawn** — `extras.group_alerts` / `alert_spread` group them server-side, and `flagpage` carries a "Same swing reported repeatedly" detection | PR #21 / `696ac39` |
| `count()` whole-number formatter | **withdrawn** — `site_build/format.py` already exposes `count`/`num` | PR #21 |
| high-ROI empty-chat flag, UNVERIFIED markers, methodology settlement fix, render contract, CI gate | **kept** — none of these existed on `main`; the three kept defects are below | this session |

Nothing was kept out of pride and nothing of another session's work was
overwritten: `git reset --hard origin/main` was used as the merge base and only
the surviving deltas were re-applied on top.

## 1. Changes published by this session, each verified against an official source

| # | Change | File | Verified against | Evidence | Status |
| - | --- | --- | --- | --- | --- |
| K1 | `num()` and `count()` rendered a **silent blank** for a missing value, violating rule 1 of their own module docstring ("renders as a blank cell with an `UNVERIFIED` badge") while `esc()`, `money()` and `cents()` honour it. Both now return `esc(value)`, which produces the badge. | `site_build/format.py` | the module docstring + the repo rule "leave it blank **and** flag it as unverified" | `fmt.num(None)` and `fmt.count(None)` returned `''`; `money`/`cents` returned the badge. Reproduced before the fix, asserted after in `tests/test_site_contract.py`. | verified (code + test) |
| K2 | `trades.html`, `resolutions.html` and `suggestions.html` had **no topbar at all** — no breadcrumb, no snapshot-age marker, no `#livePill` for `desk.js` to switch to LIVE. Each now renders `build.topbar(...)` like every other page. | `site_build/extras.py` | comparison with `build_overview` / `build_live` / `build_methodology`, which all start with `topbar(...)` | Before: `grep -c livePill trades.html` → 0 and no `class="topbar"`. After: 1 each, on all three pages, guarded by `tools/root_pages_render.mjs`. | verified (rendered output) |
| K3 | The methodology page said *"YES pays $1.00 per contract, NO pays nothing"*, which reads as if a NO position never pays out. Restated as the official rule: on a Yes outcome Yes holders receive $1.00 per contract, on a No outcome No holders receive $1.00 per contract, the losing side pays nothing, only net positions settle. | `site_build/build.py` → `methodology.html` | [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement) | The page fetched this session states exactly: "**Yes outcome**: Yes contract holders receive $1 per contract / **No outcome**: No contract holders receive $1 per contract / Only net positions are settled (after netting)". Same class of error `arena-e4e8f4e1` fixed in `EXECUTIVE_SUMMARY.md` (T14); `methodology.html` still carried it on `main`. | verified |
| K4 | New standing limitation: **taker fees apply multiplier 1 to every series** instead of each series' own `fee_multiplier`. | `site_build/flagpage.py` → `review.html` | [Kalshi fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) + [demo `GET /series/KXBTCY`](https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY) | PDF formula read this session: `fees = round up(M × 0.07 × C × P × (1−P))`, "Maker Fees" at `0.0175`, "There is no settlement fee", and the Non-Standard Fees table listing `KXBTCY · BTC price range EOY · 0 · 0` and `KXETHY · ETH price EOY · 0 · 0`. The live demo record for the same series returns `"fee_multiplier":1, "fee_type":"quadratic"`. `collector/engine.py` calls `kalshi_fee(signal.executable_price, contracts)` (line 197) and `kalshi_fee(side_price, pos.contracts)` (line 250) with the default multiplier, although `collector/topics.py` caches `fee_multiplier`. | verified + flagged |
| K5 | Offline render contract + CI gate so the three rules above cannot silently regress: `tools/root_pages_render.mjs` (13 pages in jsdom with fetch stubbed, link resolution over the whole tree, topbar-hook contract) and `.github/workflows/site-check.yml` (`contents: read`, never commits, so a failing check cannot stop the collector publishing). | `tools/`, `.github/workflows/` | the repo's own generator and `assets/desk.js` | The checker found four real defects while being written (a placeholder false positive from scanning script bodies, and the three pages missing a topbar) — that is what it is for. Node pinning was set to 22 after CI failed: `jsdom@31.0.1` declares engines `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`, so Node 20 installs it and dies on import. | verified |

## 2. Values cross-checked against the live demo API (the data the pages publish)

| # | Published value | Live official response | Result |
| - | --- | --- | --- |
| V1 | Open-interest / volume as `189,529,515.91` / `414,910,468.14`, YES bid `$0.0310`, YES ask `$0.0330` for `KXPRESNOMD-28-RW` | [`GET /markets/KXPRESNOMD-28-RW`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) → `"open_interest_fp":"189529515.91"`, `"volume_fp":"414910564.18"`, `"yes_bid_dollars":"0.0310"`, `"yes_ask_dollars":"0.0330"`, `"notional_value_dollars":"1.0000"`, `"status":"active"`, `"result":""` | bid/ask and OI match exactly; volume is higher now because it is cumulative, which also confirms the page is not showing a hand-edited figure. Confirms `*_fp` fields are fractional fixed-point, so two-decimal display is faithful and integer rounding would be wrong. |
| V2 | The open simulated position `KXBTCY-27JAN0100-B87500` shown as **OPEN** (not YES/NO) | [`GET /markets/KXBTCY-27JAN0100-B87500`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) → `"result":""`, `"status":"active"`, `"yes_sub_title":"85,000 to 89,999.99"`, `"strike_type":"between"`, floor `85000` / cap `89999.99` | Unresolved, title and strike range match. An empty `result` must render as OPEN. |
| V3 | Book depth `1,015,997` on the shortlist row | same response → `"yes_bid_size_fp":"1015997.66"` | matches, truncated to whole contracts |
| V4 | Entry fee `$13.44` for 5,000 contracts at `$0.0400` | fee PDF formula, `M = 1` (demo series value) | `0.07 × 5000 × 0.04 × 0.96 = 13.44` → `$13.44`, reproduced independently of the engine's Decimal code path |
| V5 | Four-decimal prices (`$0.0400`, `$0.0310`) | `price_ranges` step `0.0010`, `price_level_structure: deci_cent` | the source's own tick precision, not padding |
| V6 | Alert row for `KXPRESNOMD-28-HBID`: `previous 0.811 → current 0.4065` with `yes_bid 0.002 / yes_ask 0.811` | [`GET /markets/KXPRESNOMD-28-HBID`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID) taken later → `"yes_bid_dollars":"0.0020"`, `"yes_ask_dollars":"0.0030"`, `"last_price_dollars":"0.8110"`, `"previous_price_dollars":"0.0030"` | the book is normally one tick wide and a single 0.811 print sat between them — which is exactly why the site treats such rows as non-executable rather than as a traded move. Also visible in the same record: `"custom_strike":{"demo strike":"demo strike"}`, a Kalshi-side placeholder, reported by the existing template detection and left uncorrected because it is their data. |
| V7 | Counts on the tiles (`750` markets, `2,000` resolved, `0` swings in the 19:16:11Z snapshot) | `data/live.json` — the snapshot the pages were generated from | recomputed, not re-typed; the alert count is 0 because PR #22 dropped stored alerts without a verifiable quote basis, which also silences this session's alert detections (see §4) |

## 3. Not verified — left blank or labelled, never inferred

| # | Item | Handling |
| - | --- | --- |
| U1 | Real demo-account balances, fills, order placement | Not claimed anywhere. No Kalshi credentials exist in this repository and none may be committed. The ledger is labelled simulated wherever it appears. |
| U2 | Whether a browser on the Pages origin can open the demo WebSocket | Stated as unverified work in `suggestions.html`; not presented as a feature. |
| U3 | News causation for any ≥ $0.10 move | Not asserted. Alerts link to the market; no article is named as the cause. |
| U4 | Strategy profitability | Main's trades page and the engine publish `N = 0` settled samples; no win rate, expectancy or ROI is printed from an empty sample. |
| U5 | Production `fee_multiplier` for `KXBTCY` (0 per the PDF) versus demo (1 per the API) | Both values published side by side in K4; the ledger keeps the demo value because demo is the environment it trades against. |
| U6 | `extras.age_label` parses `generated_at` with `time.mktime`, i.e. as **local** time, when no `generated_at_ts` is supplied | Not fixed here: on the GitHub Actions runners that build the site the zone is UTC, so the published ages are right, and `build.topbar` now passes `generated_at_ts` explicitly for these three pages. Flagged for the file's owner rather than patched from two files away; a non-UTC builder would shift every age label by the offset. |

## 4. Requests logged instead of edited (see `COORDINATION.md`, Board D)

| # | Request | To | Why not done here |
| - | --- | --- | --- |
| R-79CC-1 | Thread the series `fee_multiplier` into the two `kalshi_fee(...)` call sites in `collector/engine.py` | `arena-856e184e` | the signal plumbing crosses `collector/collector.py`, which that session claims |
| R-79CC-2 | `extras.age_label`'s `time.mktime` fallback should be `calendar.timegm` (UTC) | `site_build/extras.py` owner | cross-file correctness note, low live impact (§3 U6) |
| R-79CC-3 | `tools/root_pages_render.mjs` asserts the topbar contract (`#livePill`, `#snapshotAge`), the nav target set and `live.html`'s `#feedAll`/`#feedModel` + three `data-window` tabs; update it in the same PR if that markup changes | all sessions touching the root site | — |

## 5. Gates run on the final tree (all green)

| Gate | Command | Result |
| --- | --- | --- |
| Python unit tests | `python3 -m unittest discover -s tests` | 98 OK (1 skip: RSA signing needs `cryptography`) — includes the other sessions' alert-basis, parity, engine and row-source suites, plus this session's `tests/test_site_contract.py` |
| Offline render contract | `node tools/root_pages_render.mjs` | ALL PASS — 13 root pages, 184 files linked against |
| Internal links / anchors | `python3 tools/linkcheck.py` | 48 pages, 621 internal links, **0 errors** |
| Collector pipeline (fixtures) | `python3 -m collector.test_runner` | PASS |
| Fee table + trading engine | `python3 -m trading.test_engine` | PASS |
| Node suites (unchanged files) | `npm test` | pass, 0 fail |
| Generator determinism | `python3 -m site_build.build` ×2 | byte-identical output. The seven pages my code does not affect were restored to `main`'s committed HTML rather than regenerated, so the PR diff carries no build-timestamp churn (`age_label` prints "7 min old" from `time.time()` at build). |
| Front-end syntax | `node --check assets/desk.js` | OK |
