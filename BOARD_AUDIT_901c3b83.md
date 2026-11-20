# Coordination and delivery audit — 2026-11-20

**Session:** `arena-901c3b83`  
**Branch:** `arena/901c3b83-trade2`  
**Scope:** coordination-board integrity, current published build/CI evidence, and a read-only check of source-link/verification tooling. No collector, dashboard, trade, market-data, or generated-site implementation was changed.

## Executive result

The requested Kalshi demo dashboard and the published GitHub Pages site already exist on the current `main` tree. The official Kalshi demo documentation confirms the recommended REST root (`https://external-api.demo.kalshi.co/trade-api/v2`) and the supported alternate (`https://demo-api.kalshi.co/trade-api/v2`), as well as both demo WebSocket hosts. The code's demo endpoint values match that official table.

At audit time, GitHub Pages reported `built` for `main` commit `eef1243977f90205021faedc3507a697dc83f109` at `2026-11-20T20:01:16Z`. The published root is <https://wingbangboozle1-lang.github.io/Trade2/>. Current-tree local verification passed: Python tests (174 passed, one skipped), npm tests (29 passed), root-render checks (13 pages), render checks (13 pages), site smoke checks, collector fixtures, trading-engine checks, and the internal-link checker (50 pages, 666 links, zero errors).

The verification is not equivalent to a fresh authenticated demo-account test. No account credentials are configured in the repository; the current branch-push collector run passed but skipped the demo-probe and collection steps, as expected for that event. Account balances, real orders/fills, and authenticated account WebSocket activity remain unverified and must stay labelled that way.

## Evidence and flagged items

| Finding | Evidence and official source | Assessment |
| --- | --- | --- |
| Demo REST/WS endpoints | [Kalshi demo environment](https://docs.kalshi.com/getting_started/demo_env) and [API environments](https://docs.kalshi.com/getting_started/api_environments); compared with `collector/kalshi_api.py` and `kalshi-dashboard/data/latest.json`. | Confirmed: both supported REST roots and both supported WebSocket URLs match the official docs. |
| GitHub Pages publication | [Latest Pages build API](https://api.github.com/repos/wingbangboozle1-lang/Trade2/pages/builds/latest) reported `built`, `error: null`, commit `eef1243…`; deployed root: [Trade2 Pages](https://wingbangboozle1-lang.github.io/Trade2/). | Published. This proves build status, not freshness of every underlying market quote. |
| Current branch CI | [Collector run 44807952089](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44807952089) completed successfully on this branch. The run summary shows the demo API probe, collection, simulator, and data commit were skipped for the branch-push event. | Code/test job green; no new demo data was fetched by this run. |
| Row-level source audit | `python3 tools/rowsource_check.py` reported 332/332 root dashboard market rows and 40/40 `docs/` market rows with demo-host sources, zero missing source URLs, and 182 rows with some issue/partial-verification note. Root market rows with blank value fields: 142; `docs/` market rows with blank value fields: 40. The checker leaves blanks intact and labels them unverified; see [the row-source audit tool](https://github.com/wingbangboozle1-lang/Trade2/blob/main/tools/rowsource_check.py). | No missing primary source was found in those tables. The blank cells are intentionally not inferred; they remain flagged, not verified values. |
| Open model/alert PR has a failing check | [PR #28](https://github.com/wingbangboozle1-lang/Trade2/pull/28) showed one successful and one failed `collect` check. Failed run [44807390799](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44807390799) identifies `Desk render check (browser path)` as the failing step. `gh run view --log-failed` could not retrieve the signed log (EOF), so the cause could not be verified here. | **Flag for owner review.** This session made no changes to PR #28 or its workflow/code. Do not claim its check is green based on the separate successful run. |
| PR #29 remains open | [PR #29](https://github.com/wingbangboozle1-lang/Trade2/pull/29) was open at audit time with its `collect` check successful. | Open peer work; no action taken from this branch. |
| Stale task status in the coordination board | The `arena-5bec0ea3` T34 row still says `in progress`, while the same board contains a final T34 integration record stating PRs #30 and #33 merged, post-merge verification passed, and Pages built. Compare [PR #30](https://github.com/wingbangboozle1-lang/Trade2/pull/30) and [PR #33](https://github.com/wingbangboozle1-lang/Trade2/pull/33). | Board inconsistency, not a product defect. Recorded as a review request; the peer-owned task row was not edited. |
| Demo account and live trading boundary | [Kalshi demo environment](https://docs.kalshi.com/getting_started/demo_env) states demo credentials are separate and demo market behavior may not reflect production. Repo test [auth coverage](https://github.com/wingbangboozle1-lang/Trade2/blob/main/scripts/test/auth.test.mjs) checks no-secret behavior and rejects a production host. | Public-market dashboard and simulated ledger are testable; real demo account balances, orders, and fills remain unverified without configured secrets. |

## Verification performed

- `python3 -m unittest discover -s tests` — 174 passed, 1 skipped.
- `npm test` — 29 passed.
- `python3 -m collector.test_runner` and `python3 -m trading.test_engine` — passed.
- `node test/root_render.mjs` — 13 pages passed.
- `node tools/rendercheck.mjs` — 13 pages passed.
- `node test/site_smoke.mjs docs/data` — all checks passed, including source-link checks for sampled market rows, chats, strategy tables, and the flagged page.
- `python3 tools/linkcheck.py` — 50 pages, 666 internal links, 0 errors.
- `python3 tools/rowsource_check.py` — source host and blank-value audit described above. Its generated CSV/JSON outputs were restored after inspection; this audit added no generated data.
- Fetched the two official Kalshi endpoint pages listed above and compared their endpoint tables with the repository's endpoint configuration.

## Post-merge integration follow-up

PR [#41](https://github.com/wingbangboozle1-lang/Trade2/pull/41) was merged at `2026-11-20T20:07:06Z` as `5c75ac090215cbfa6d37539858aba26125f03996`. The Pages workflow [44808427503](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44808427503) completed successfully and the Pages build API reported `built` for that merge commit.

A post-merge root collector workflow, [44808428309](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44808428309), **failed** at `Desk render check (browser path)`. GitHub's signed log download returned EOF, but I reproduced the failing check locally against an archive of `origin/main`: the published `high_roi_alerts` list was empty while `assets/desk.js` rendered five model-chat rows; the assertion expected zero. This is a model-chat contract/test mismatch, not a verified exchange fact. The same browser-path step failed again in main run [44809219644](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44809219644), after the next snapshot refresh. PR [#28](https://github.com/wingbangboozle1-lang/Trade2/pull/28) owns overlapping `assets/desk.js`, workflow, snapshot, and model-shortlist scope, so I did not edit those files. Request R-901-02 is logged in `COORDINATION.md` asking that owner to reconcile the contract and rerun the browser-path CI check.

The post-merge site-check workflow [44808428279](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44808428279) succeeded. Its advisory generated-page comparison emitted a warning because rebuilding recalculates the humanized snapshot age (`4 min old` became `12 min old`) even though the source timestamp stayed the same; an isolated archive-and-rebuild reproduced that exact age-only diff. This is a nondeterministic display-age comparison, not evidence of changed market values. The step is configured `continue-on-error` in `.github/workflows/site-check.yml`.

## Scope boundary

This report does not certify model profitability, news causation, real demo-account trading, or quote freshness beyond the published snapshot metadata. Model-ranked events are a heuristic shortlist, not proven high ROI. Rows with missing values remain blank and flagged. The PR #28 render-check failure, the stale T34 board status, and the model-chat contract mismatch are explicitly left for their owners to review.
