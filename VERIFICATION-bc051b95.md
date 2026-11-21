# Verification — session `arena-bc051b95` (branch `arena/bc051b95-trade2`, Board K)

Scope: takeover + integration of the two stale PRs (#28 `arena/dd1da6b5`, #29
`arena/c78c9b36`), the R-1E3-1 workflow fix, and the merge/Pages record. Every
claim below was checked against the official source named in its row. Nothing
is inferred; values that could not be confirmed are left blank and flagged.

Started 2026-11-21T06:45Z · base `main` @ `06738d1` · verification performed
2026-11-21T06:45Z–07:05Z.

## 1. Takeover decisions (with the evidence that justified them)

| # | Claim | Evidence opened | Result |
| - | ----- | --------------- | ------ |
| V1 | PR #28 is stale (> 60 min with no commits) and CONFLICTING, so the board's rule 5 takeover applies | `gh pr view 28` → `mergeStateStatus: DIRTY`, `mergeable: CONFLICTING`, `updatedAt: 2026-11-20T20:00:32Z` (~10.7 h before this session started); its `collect` check red (run 44807390799) | **Verified.** The PR's content (order-book shortlist, swing news links, snapshot verification, topic feeds, site map) is *not* on `main` — `collector/shortlist.py`, `tests/test_shortlist.py`, `tools/verify_snapshot.py`, `tools/seed_mid_history.py`, `data/shortlist.json` all absent from `06738d1`. Main's desk.js already renders a `high_roi_alerts` layer with a signals fallback (merged PR #40), so the side-car completes that contract rather than duplicating it. |
| V2 | PR #29 is stale and CONFLICTING; its content is a documentation-only close-out of T14 (C78) | `gh pr view 29` → `updatedAt 2026-11-20T19:35:08Z`, CONFLICTING, one commit touching `COORDINATION.md` only; diff read in full | **Verified.** Its content is genuine verification evidence (PR #25 checks, Pages build, cache-busted public checks) that main's board lacked, so it was integrated additively into the `arena-c78c9b36` section instead of being closed as redundant. |

## 2. Merge conflict resolutions (all union, no session's work dropped)

| File | Resolution |
| ---- | ---------- |
| `assets/desk.js` | Kept main's `signalRow` published-signals fallback (pinned by `tests/test_chat_rows.py`, `test/desk_render_dc732aa6.mjs`) AND the PR's `newsFor`/`newsLinks`/`modelRows` side-car. Model chat = book-model rows first, then uncovered gated `high_roi_alerts`, then the signals fallback, then the empty state. |
| `site_build/flagpage.py` | Kept main's wide-spread + dedupe findings AND added the PR's verification-mismatch + book-unconfirmed-swing detections (renumbered 5/6). |
| Generated `*.html`, `categories/*.html`, `assets/live.json` | Main's newer 06:30Z snapshot kept, then every page regenerated with the merged builder so committed output == generator output. |
| `data/live.json` | Main's newer snapshot kept (PR's 19:45Z copy dropped). No content was mixed: git's auto-merge of the JSON was inspected and overridden. |
| `data/shortlist.json`, `data/news.json`, `data/verification.json`, `data/mid_history.json` | New files from the PR kept; `shortlist.json` + `mid_history.json` then regenerated locally from the current snapshot (offline module — reads `data/live.json` only). |
| `COORDINATION.md` | Additive union: the PR's Session E section entered the board unchanged; this session's Board K appended; PR #29's T14 close-out applied to the `arena-c78c9b36` section. |

## 3. Defects found during the line-by-line review of the merged code (fixed)

| # | Defect | Fix | Proof |
| - | ------ | --- | ----- |
| F1 | `collector/shortlist.py` reason strings rendered negative dollars as `$-0.0340`, violating the site-wide convention pinned by `tests/test_site_contract.py::TestNegativeMoney`, and leaked to `live.html` | Added `_usd()` (sign outside the symbol) and used it in every reason string | Re-ran shortlist + build → `grep -c '\$-' live.html index.html trades.html resolutions.html` = 0; `TestNegativeMoney` passes |
| F2 | The flagged-page entry "Taker fees use a multiplier of 1 for every series" and the methodology sentence "applies a multiplier of 1 … because it calls `kalshi_fee(price, contracts)` without one" were **false** against the merged tree — `collector/engine.py` threads `fee_multiplier` at both call sites (lines 224, 280; R-79CC-1). This is exactly the staleness request R-1E3-2 (Board J) described | Rewrote both copy sites to state the real behaviour (per-series `fee_multiplier`/`fee_type` from `GET /series` via `alerts.fee_params`, basis printed per row, fallback M=1 when a lookup is unavailable) and kept the *source* disagreement (fee PDF vs API) as the flagged item; updated the two contract tests to pin the corrected copy | `python3 -m unittest tests.test_site_contract` passes; the new assertions pin both the corrected copy and the *absence* of the old false claim |
| F3 | The PR's executive-summary addendum described a six-gate model with constants (`spread ≤ $0.05`, `≥ 50 contracts`, `2× mid`, `20-bar trail`) that do not match the merged module (`MAX_SPREAD=0.20`, `MIN_DEPTH_CONTRACTS=10`, `TRAIL_LEN=12`, `MIN_DRIFT=0.01`) and restated snapshot-dependent counts as facts | Addendum rewritten to match `collector/shortlist.py` exactly; live counts pointed at the pages instead of restated | compared against the module source line by line |
| F4 | `VERIFICATION.md` H2.4 called the book-confirmation rule "Gate 6 of the published model" — the merged module numbers four gates plus the swing/level references | Reworded to the actual rule | module docstring cross-checked |
| F5 | `tools/verify_snapshot.py` is `continue-on-error` in the workflow by design (a mismatch must not stop publishing) — noted, not changed; a mismatch is surfaced on Flagged for Review via `flagpage.py` issue 5 | none (design intent confirmed from workflow + builder) | — |

## 4. Independent re-verification against the official demo API (platform fetcher)

The sandbox shell has no route to the Kalshi hosts (re-confirmed at claim time:
`curl https://demo-api.kalshi.co/trade-api/v2/markets?limit=2` → exit 35, HTTP
000), but the platform fetcher does — the Board J finding holds. The published
snapshot is `2026-11-21T06:28:00Z` (`data/live.json`); each row below re-opens
the official response and compares it field by field. Checks performed
2026-11-21T06:55Z–07:05Z.

| # | Published row | Official URL opened | Result |
| - | ------------- | ------------------- | ------ |
| V3 | `KXPRESNOMD-28-RW` (elections): YES bid `0.038`, YES ask `0.039`, mid `0.0385`, OI `189,529,515.91`, status `active`, result `""`, notional `1.0` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW> | **Bid/ask/OI/status/result/notional EXACT** (`yes_bid_dollars 0.0380`, `yes_ask_dollars 0.0390`, `open_interest_fp 189529515.91`, `notional_value_dollars 1.0000`). Mid = (bid+ask)/2 ✓ arithmetic. Volume: published `414,933,042.49` vs official `volume_fp 414933298.61` → **drift +256.12 contracts (0.0006 %, inside the 2 % tolerance)** — real movement between the 06:28Z snapshot and this check, recorded as drift per the published convention, not an error. |
| V4 | Same market's depth figures | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW/orderbook> | **Verified.** Bids ascending with best bid last (official `orderbook_responses` shape): best YES bid `0.0380` × `13,869.69` — exactly the published depth; best NO bid `0.9610` → implied YES ask `1 − 0.9610 = 0.0390` = published ask. |
| V5 | `KXBTCY-27JAN0100-B47500` (crypto): YES bid `0.09`, YES ask `0.10`, mid `0.095`, OI `26,578,502.95`, status `active` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B47500> | **Bid/ask/status EXACT** (`yes_bid_dollars 0.0900`, `yes_ask_dollars 0.1000`); mid arithmetic ✓; OI `26578722.64` vs published `26578502.95` → **drift +219.69 (0.0008 %, inside tolerance)**. |
| V6 | Flagged-page claim: demo `GET /series/KXBTCY` returns `fee_multiplier 1` while the fee PDF lists the series at 0/0 | <https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY> | **Re-verified 2026-11-21:** `fee_multiplier: 1`, `fee_type: "quadratic"` — the published source-disagreement item stands. PDF side: <https://kalshi.com/docs/kalshi-fee-schedule.pdf> (not fetchable from this sandbox; the disagreement was verified on 2026-11-20 by earlier sessions and is published with both sources). |

Rows NOT re-checked live this session (left to the standing mechanisms): the
remaining ~740 market rows are re-checked every few minutes by
`tools/verify_snapshot.py` on the scheduled runner (output published in
`data/verification.json` and on the Methodology page — latest run embedded in
`review.html` shows 144 match / 1 drift / 0 mismatch), and `tools/rowsource_check.py`
confirms every published row carries a demo-host source URL (40 market rows +
300 resolution rows + 6 alert rows + 18 portfolio rows, 0 missing, 0
production-host leaks). Demo-account balances/fills remain **UNVERIFIED** — no
credentials exist for this repo (standing flag, unchanged).

## 5. Full battery on the final merged tree (2026-11-21T06:5xZ)

| Check | Result |
| ----- | ------ |
| `python3 -m unittest discover -s tests` | **243 tests OK** (1 skip — `cryptography` unavailable in sandbox), including the 12 new `tests/test_shortlist.py` cases |
| `npm test` (node --test) | **29 pass / 0 fail** |
| `python3 -m collector.test_runner` | PASS (fixtures end-to-end) |
| `python3 -m trading.test_engine` | PASS (fees vs the official 42-row PDF table) |
| `node test/root_render.mjs` | RENDER CHECK PASSED (all root pages offline) |
| `node tools/rendercheck.mjs` | RENDER CHECK PASSED |
| `node test/desk_render_dc732aa6.mjs` | PASSED — real page + real desk.js + published snapshot; three-layer model-chat contract pinned with content teeth |
| `node test/site_smoke.mjs docs/data` + `python3 test/gen_fixtures.py` + smoke on fixtures | ALL PASS |
| `python3 tools/linkcheck.py` | **50 pages / 685 internal links / 0 errors** |
| `python3 tools/rowsource_check.py` | 0 missing source URLs, 0 production-host leaks (blank/unverified cells published by convention) |
| `node --check assets/desk.js`, `node --check assets/alerts-view.js` | OK |
| `python3 -m py_compile collector/*.py trading/*.py site_build/*.py tools/*.py` | OK |

## 6. Irregularities observed (published, none blocking)

| # | Observation | Where published |
| - | ----------- | --------------- |
| I-K-1 | The demo feed prints alternating trades on flat books (e.g. `KXPRESNOMD-28-AKLO` candles alternate 0.8030/0.0030 while the book never moves) — the merged model gates on book confirmation | `review.html` (standing limitation + per-alert verdicts), `VERIFICATION.md` H2 |
| I-K-2 | Large OI against empty books on demo (top events show tens of millions of contracts against 0 resting bid depth) | `review.html` literal-rule table |
| I-K-3 | Fee PDF vs demo `GET /series` multiplier disagreement (KXBTCY 0/0 in PDF vs 1 on demo) — this project follows the API field; production fees would differ | `review.html` (rewritten entry, F2) |
| I-K-4 | No demo credentials exist, so authenticated portfolio endpoints and the authenticated WebSocket remain unexercised; the paper ledger is clearly labelled simulated | `review.html` standing item, README |
| I-K-5 | News links are keyword/publish-time *candidates*; no headline is ever presented as the confirmed cause of a move | `review.html`, alert rows carry the label |
| I-K-6 | The `Desk render check` step sits before `Commit data` in `kalshi-dashboard.yml`, so a red render check still blocks that run's data commit (Board J's ordering recommendation remains open — not restructured here because the checks are green and the ordering change belongs to the publishing workflow owner) | this file + Board K |
