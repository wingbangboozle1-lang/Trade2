# Verification report — session `arena-479bbd2f` (F-479-1, F-479-2, F-479-3)

Branch `arena/479bbd2f-trade2` → `main` (PR #50, merged 2026-11-20).
Coordination board: Board H in [COORDINATION.md](COORDINATION.md).
Every claim below names the command, run, or endpoint that produced it.

## Method note — where network verification actually runs

This agent sandbox has **no egress to Kalshi hosts** (curl to
`https://external-api.demo.kalshi.co/...` fails at TLS; outbound hosts are
limited to github.com / api.github.com / registry.npmjs.org / pypi.org).
All live-API facts in this report were therefore produced on **GitHub Actions
runners**, which have unrestricted egress:

- workflow `verify rows vs official demo API (479)` — run
  **44812233528** (success, on `arena/479bbd2f-trade2`), committed
  `audit/verify-479.json` + `audit/verify-479.md` at
  2026-11-20T20:32:20Z;
- earlier evidence still on record: capability probe in
  `docs/data/capabilities.json` (runner run 44804363290, 2026-11-20T19:40Z),
  which also supplies the real response shape used to unit-test the verifier
  offline.

## F-479-1 — red CI on `main`: desk render check (repaired)

| Item | Detail |
| - | - |
| Symptom | Run **44808226182** (PR #40 merge) and later push runs failed at step "Desk render check (browser path)"; PR #48 recorded the failure without a fix |
| Reproduction (local, merged tree) | `node test/desk_render_dc732aa6.mjs` → `FAIL model chat uses the published shortlist, not a client-side re-gate — expected 0, got 5` (all other 23 assertions passing) |
| Root cause | `test/desk_render_dc732aa6.mjs` pinned the pre-#40 contract (`modelRows == min(200, len(high_roi_alerts))`). Merged PR #40 (T-D3, pinned by `tests/test_chat_rows.py`) deliberately renders the collector's published `signals` (top ≤ 8) when the gated shortlist is empty — the current snapshot holds `high_roi_alerts: []`, `signals: 5` |
| Fix | Test file only (`assets/desk.js` untouched): assertion aligned with the merged contract; new assertion that signal-only rows are exactly published signal tickers (preserves "no client-side re-gate"); new fixture pinning the fallback, which also documented the two-stage order (swing∩signals first, signal-only second) |
| Result | `node test/desk_render_dc732aa6.mjs` → **26/26 PASS**; post-merge run **44811082933 → success** (the first green desk-render check on `main` since PR #40) |

## F-479-2 — fresh line-by-line verification vs the official demo API

Tool `tools/verify_rows_479.py` (stdlib only) re-fetches, per topic
(gas-prices, elections, culture, crypto, golf), the top **active** event by
published `open_interest_notional` — the brief's "highest dollar" ranking —
and compares, field by field:

- the market row via **GET /markets/{ticker}**
  (https://docs.kalshi.com/api-reference/market/get-market), comparing
  title (`yes_sub_title` fallback, stripped), YES bid/ask (book best bids
  with the record's own `yes_bid_dollars`/`yes_ask_dollars` fallback — the
  exact derivation in `collector.alerts.observe`), `open_interest_fp`,
  `volume_fp`, `notional_value_dollars`, `status`, `close_time`, `result`;
- the ranking value recomputed as `round(oi × notional, 2)` per
  `collector.alerts.rank_events` (documented in-code; fields per
  https://docs.kalshi.com/api-reference/market/get-markets);
- the order book via **GET /markets/{ticker}/orderbook?depth=25**
  (https://docs.kalshi.com/getting_started/orderbook_responses.md),
  comparing best YES bid, best NO bid, implied YES ask (1 − best NO bid), and
  bid-side depth totals, per `collector.alerts.analyse_liquidity`.

### Two tool bugs caught by the tool's own raw evidence (fixed before publishing)

1. **List-endpoint ticker filter.** First run (44811154325) fetched markets
   with `GET /markets?ticker=...`. The demo API **silently ignores** the
   unsupported singular `ticker` param: all five subjects returned the *same*
   newest cross-category market (identical cursor
   `KXNCROSSCATEGORY-S2026F6RZ75LPEYY3KLML5-4CFF5TY3R`, identical
   `created_time`, soccer-flavoured titles — preserved in the run's artifact).
   Fixed to the documented single-market endpoint; re-run 44812233528.
2. **YAML heredoc.** The workflow's step summary used an indented heredoc;
   a zero-indented body line would terminate the `run: |` block scalar, so
   the correct fix is no heredoc at all — the step now `cat`s the tool's own
   report into `$GITHUB_STEP_SUMMARY` (run 44811882990 failed on this; run
   44812233528 passed).

### Verdicts — run 44812233528, evidence `audit/verify-479.md`

**EXACT 47 · DRIFT 12 · UNVERIFIED 16** (75 comparisons over 5 subjects, each
row carrying its official endpoint URL).

- **EXACT (47)** — titles, quotes (e.g. elections `KXPRESNOMD-28-RW` YES
  $0.035/$0.038), book best bids, `status: active`, close times, results,
  notionals equal the fresh payload exactly.
- **DRIFT (12)** — genuine market movement between the snapshot
  (generated 19:58:45Z) and the re-fetch (20:32:20Z): volume +~218 contracts
  (`KXPRESNOMD-28-RW`), open interest +~197 (`KXBTCY-27JAN0100-B127500`,
  `KXPGATOUR-THRC26-TMOO`), book depth shifted by small order flows, and the
  recomputed `oi × notional` tracking the OI drift exactly (the *formula* is
  verified; the *input* moved). Both values are published side by side; nothing
  was equalised or inferred.
- **UNVERIFIED (16)** — blank on **both** sides, never guessed: markets with
  **empty order books** (gas `KXAAAGASM-26NOV30-4.70`, culture
  `KXCRITICSFOREIGN-27-LAB` — `orderbook_fp` both sides `[]`; crypto YES side
  empty). Their published quotes are blank on the site because the collector
  refuses the 0.0000/1.0000 phantom-quote pair (documented at
  `collector/alerts.py`, the "no quotes at all" rule). The fresh fetch confirms
  there is genuinely nothing to quote — **this validates the site's
  blank-means-blank rule against the live exchange**.

## F-479-3 — full battery on the merged tree (final rebase `0673720` + evidence)

| Check | Command | Result |
| - | - | - |
| Python suite | `python3 -m unittest discover -s tests` | **196 OK, 1 skipped** (skip: `cryptography` absent in sandbox, pre-existing) |
| Node suite | `npm test` | **29 pass / 0 fail** |
| Desk render (the repaired check) | `node test/desk_render_dc732aa6.mjs` | **PASSED** (26 assertions) |
| Internal links | `python3 tools/linkcheck.py` | **50 pages / 666 internal links / 0 errors** |
| Page render (offline jsdom) | `node tools/rendercheck.mjs` · `node tools/root_pages_render.mjs` | all ok · **ALL PASS, 13 root pages, 217 files** |
| Collector on captured payloads | `python3 -m collector.test_runner` | **PASSED** (series 7, markets 7, orderbooks 7, alerts 7, resolutions 1) |
| Trading engine + fee formula | `python3 -m trading.test_engine` | **ALL TRADING TESTS PASSED** |
| Docs-site smoke | `npm run test:site` | **ALL SITE SMOKE CHECKS PASSED** |
| Row source links | `python3 tools/rowsource_check.py` | 332 root market rows, 17 topic-event, 3 alert, 5 trade rows — **0 missing source URLs, 0 production-host leaks**; 182 listed issues are blank/unverified cells (published blank by convention, never inferred). Read-only inspection; generated artifacts restored |
| CI on main after merge | run 44811082933 | **success** |
| Pages | `gh api .../pages/builds/latest` after merge | `status: built`, no error (see F-479-3 record on the board) |

## Flagged irregularities (published, not silently fixed)

1. **Demo market churn.** The demo environment creates/rolls markets
   continuously (the wrong-endpoint fetch surfaced a cross-category market
   created 30 s before the probe). Published snapshots are minutes old by
   design; DRIFT rows above are the honest record of that churn.
2. **Empty-book markets rank high by OI.** Two of the five top
   dollar-at-stake events have no resting orders at all (gas, culture). The
   site correctly shows blank quotes, but a trader should read "OI without a
   book" carefully — flagged on the site's Flagged-for-Review page by the
   standing generator, and demonstrated here against the live exchange.
3. **The two-stage model-chat fallback** (swing∩signals before signal-only)
   means "top ≤ 8 published signals" appears only when no swing matches any
   signal — correct per the merged PR #40 contract and now pinned by a fixture,
   but worth a reviewer's eyes.
4. **Standing limitations (unchanged, unverified-by-design):** real
   demo-account balances/fills require credentials that are absent
   (`KALSHI_API_KEY_ID` + private key as secrets, never committed); news-cause
   links are labelled *candidate*, not confirmed; model ROI is a screen, not a
   validated edge.

## Sources (official)

- https://docs.kalshi.com/getting_started/demo_env — demo REST root
- https://docs.kalshi.com/api-reference/market/get-market — single market
- https://docs.kalshi.com/api-reference/market/get-markets — market fields
- https://docs.kalshi.com/getting_started/orderbook_responses.md — bids-only book
- `docs/data/capabilities.json` — committed runner evidence (CORS, anonymous WS 401, response shape)
- `audit/verify-479.json` / `audit/verify-479.md` — this session's fresh row evidence (run 44812233528)
