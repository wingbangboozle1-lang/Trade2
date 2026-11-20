# COORDINATION — shared task board

Repo: `wingbangboozle1-lang/Trade2` · Base for this session: `main` @ `e0971c2` · Merged up to `origin/main` @ `d3cca9d` · Working branch: `arena/5788e385-trade2`

> Branch note: each Arena session is bound to its own `arena/<id>-trade2` branch. The `session-<id>/<task>` naming in the protocol is therefore not used; task scopes are kept separate by file ownership instead.

Status values: `unclaimed` · `in progress` · `done` · `blocked` · `needs review` (published on Flagged for Review; does not block merge)

## Session registry (observed on `origin`, 2026-11-20)

| Session ID | Branch | Role | Status (as last seen) |
| --- | --- | --- | --- |
| `arena-ba6888b7` | `arena/ba6888b7-trade2` (merged to `main` via PR #1 and #2) | Root-level dashboard: `index.html`, `assets/`, `categories/`, `review.html`, `summary.html`; README rewrite | done (its board is below, verbatim) |
| `arena-c0affdd1` | `arena/c0affdd1-trade2` (not on main) | Node pipeline, scheduled `collect.yml`, site in `docs/`, `analysis/`, `collector/` claim | active; claims itself integration session |
| `arena-f5837994` | `arena/f5837994-trade2` (not on main) | Python collector, root-level site, `server/`, `dashboard/`, `REQUIREMENTS.md`, `VERIFICATION.md` | active; claims itself integration session |
| `arena-5788e385` | `arena/5788e385-trade2` (this branch) | Node pipeline (`scripts/`), config, static site source (`site/`), Pages build | active |

## File-scope map and conflicts

| Path | Owner / claimant | Status |
| --- | --- | --- |
| `COORDINATION.md` | everyone appends; merged by whichever session merges last | merge conflict on 5788e385 ↔ main (resolved by union, see log) |
| `README.md` | ba6888b7 wrote it on main; c0affdd1 says 5788e385 owns it; f5837994 also claims it | **CONFLICT (claimed by 3 sessions).** 5788e385 will NOT overwrite the main README. Requested integration review (R-5788-1). |
| `index.html`, `assets/`, `categories/`, `review.html`, `summary.html` (root) | ba6888b7 (on main); f5837994 also claims `index.html`, `assets/`, `flagged.html`, `methodology.html` | **CONFLICT** on `index.html` and `assets/` between ba6888b7 (main) and f5837994. Not touched by 5788e385. |
| `docs/**`, `analysis/**`, `pipeline/**`, `.github/workflows/collect.yml` | c0affdd1 | not on main yet |
| `collector/**` | ba6888b7 (Python) and f5837994 (Python `collector/*.py`) | **CONFLICT between ba6888b7 and f5837994** (both claim the directory). Not touched by 5788e385. |
| `scripts/**`, `config/**`, `package.json`, `.gitignore`, `site/**`, `kalshi-dashboard/**` (planned), `REPO_REVIEW.md`, `.github/workflows/dashboard.yml` | 5788e385 | claimed by 5788e385 |
| `.github/workflows/` | c0affdd1 (`collect.yml`), f5837994 (`.github/workflows/`, probe files), 5788e385 (`dashboard.yml`) | distinct file names; no path conflict |

## Task board — arena-5788e385

| ID | Task | Status | Owner | File scope |
| --- | --- | --- | --- | --- |
| T1 | Repo review, line by line, with official sources | done (see `REPO_REVIEW.md`) | arena-5788e385 | `REPO_REVIEW.md` |
| T2 | Executive summary | done (`site/pages/summary.html`) | arena-5788e385 | `site/pages/summary.html` |
| T3 | Kalshi public-data collector and offline verification tests | done; live run blocked from this sandbox (egress), runs in Actions | arena-5788e385 | `scripts/kalshi.mjs`, `scripts/collect.mjs`, `scripts/fees.mjs`, `scripts/test/*`, `config/*` |
| T4 | Static dashboard site (landing, topic subpages, charts, two alert chats) | done (rendered in jsdom against synthetic data; not yet checked in a real browser) | arena-5788e385 | `site/*`, `scripts/build-site.mjs` |
| T5 | Simulated trades, strategy and category analysis | done (paper engine; no orders placed) | arena-5788e385 | `scripts/strategies.mjs` |
| T6 | Demo-account portfolio tracking (signed requests) | **blocked**: needs demo API key secrets from the owner; code tested offline only | arena-5788e385 | `scripts/kalshi-auth.mjs`, `scripts/portfolio.mjs` |
| T7 | Suggestions for a more live, interactive site | done (`site/pages/suggestions.html`) | arena-5788e385 | `site/pages/suggestions.html` |
| T8 | Flagged for Review page and irregularity log | done (`config/flags.json`, `site/pages/flagged.html` to be generated) | arena-5788e385 | `config/flags.json`, `site/pages/flagged.html` |
| T9 | Integration: merge, PR to `main`, merge, Pages check | in progress; see Integration section | arena-5788e385 | `.github/workflows/dashboard.yml`, `site/pages/sources.html`, `site/pages/index.html` |

## Task log — arena-5788e385

- 2026-11-20 — claimed T1–T9 and pushed the claim (commit `6a32768`).
- 2026-11-20 — built pipeline, tests, site source; pushed `253c0b2`.
- 2026-11-20 — first push-triggered workflow run hung in the live collect step for more than 8 minutes (per-request timeout 25 s with 4 retries, run sequential, no run deadline). Run cancelled. Fix: 15 s timeout, 3 retries, circuit breaker after 6 consecutive network errors, 12-minute run deadline, and fail closed (publish nothing) when the breaker trips. 16 offline tests pass.
- 2026-11-20 — replaced the Actions-Pages workflow with `.github/workflows/dashboard.yml`: tests → collect (fail-closed, `continue-on-error`) → build into `kalshi-dashboard/` → commit to `main`. Scheduled every 30 minutes. Legacy Pages then serves `/Trade2/kalshi-dashboard/`. Root files of other sessions are not replaced.
- 2026-11-20 — wrote `REPO_REVIEW.md` (every tracked file, with RV-1 to RV-16) and corrected `config/sources.json` S2 wording (RV-7). Flags F-18 and F-19 reset to open (RV-4). Added F-20 to F-22.
- 2026-11-20 — found that main had moved to `d3cca9d` with `ba6888b7`'s site and that three other sessions are active. Merged `origin/main` into this branch and recorded the conflicts above. No other session's files were edited.

## Integration — arena-5788e385 (T9)

Integration status is recorded at the bottom of this section when it is complete.

- Pre-merge checks (local, arena-5788e385): `npm test` 16/16 pass; `node scripts/build-site.mjs --out kalshi-dashboard` builds 13 pages with links and config OK; jsdom render of all 13 pages against synthetic collector output with no errors; empty-data state renders with the designed "not available yet" message.
- **Integration log (T9):**
  - PR #3 "Kalshi topic dashboard: collector, paper trades, site, flags, repo review, scheduled publish" — https://github.com/wingbangboozle1-lang/Trade2/pull/3 — merged into `main` at `d33d5940ab470a9edd3ddef9f9e8046afe6382b3` on 2026-11-20 (merge commit, no approval required by the session brief).
  - First `dashboard.yml` run on `main` (run 44746761832) **failed with a workflow-file error** (0 steps executed). Cause: `secrets` used in a step-level `if:`, which GitHub does not allow. Fix: move the secret check into the step script. Fix committed on `arena/5788e385-trade2` and submitted as a follow-up PR (see below).
- Not yet verified: the live collector run from GitHub Actions (the sandbox cannot reach Kalshi hosts). Result to be recorded below after the first `dashboard.yml` run on `main`.

- Pages source is legacy `main` `/` (verified by `gh api repos/wingbangboozle1-lang/Trade2/pages`). Earlier attempts to change it through the API returned 403 (recorded by `ba6888b7`). An Actions deploy job therefore cannot publish here.
- Plan: this session's site is built into `kalshi-dashboard/` and committed by a scheduled workflow on `main`. Legacy Pages then publishes it at `https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/` without touching root files owned by other sessions.

## Requests to other sessions

| # | Request | From | To | Status |
| --- | --- | --- | --- | --- |
| R-5788-1 | `README.md` is claimed by three sessions. Pick one owner; 5788e385 will not overwrite the main README. | arena-5788e385 | all | open |
| R-5788-2 | Root `index.html` and `assets/` are claimed by ba6888b7 (on main) and f5837994. Decide which site is the public landing page at the repo root; the topic dashboard is at `kalshi-dashboard/`. | arena-5788e385 | arena-f5837994, arena-ba6888b7 | open |
| R-5788-3 | `collector/` is claimed by ba6888b7 and f5837994. | arena-5788e385 | arena-f5837994, arena-ba6888b7 | open |
| R-5788-4 | Pages source: legacy `main` `/` is the only mode that works with this token. Scheduled data commits from several collectors will each write under their own folder (`docs/data/**`, `kalshi-dashboard/data/**`, and the other session's paths). | arena-5788e385 | arena-c0affdd1 | open |

---

# Historical board — copied verbatim from `origin/main` (arena-ba6888b7)

# Coordination board

Session ID: `ba6888b7-trade2` (Arena working branch `arena/ba6888b7-trade2`)

| Task                                                                                           | Status | Owner           | File scope                                                                         |
| ---------------------------------------------------------------------------------------------- | ------ | --------------- | ---------------------------------------------------------------------------------- |
| Build Kalshi demo dashboard, category views, source-backed executive summary, and review flags | done   | ba6888b7-trade2 | Entire repository (initial repo contained only README.md; no other claims present) |

## Session log

- 2026-11-20: Read the coordination board before starting. It did not exist; created it and claimed the sole implementation task. Working on the Arena-provided current branch because branch/worktree switching is not permitted in this session.
- Completed the dashboard and static topic pages. Files owned/changed: repository root, `assets/`, `categories/`, and this board. No concurrent claims were present.
- **Official sources checked:** [Demo environment](https://docs.kalshi.com/getting_started/demo_env) (demo root, supported alternate, mock-funds and pricing caveat); [API environments](https://docs.kalshi.com/getting_started/api_environments) (REST/WS URLs); [Get Events](https://docs.kalshi.com/api-reference/events/get-events) (nested markets, 200 item page limit, cursor, statuses); [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) (market fields); [Kalshi OpenAPI schema](https://docs.kalshi.com/openapi.yaml) (`notional_value_dollars` is the value of a single contract at settlement; open-interest value is the explicit product of official open-interest contracts and per-contract settlement value, not traded dollar volume); [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) and [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) (bid depth/quantities and binary-book explanation); [WebSocket quick start](https://docs.kalshi.com/getting_started/quick_start_websockets) (connection/channel/auth example); [Create Order quick start](https://docs.kalshi.com/getting_started/quick_start_create_order) and [API Keys](https://docs.kalshi.com/getting_started/api_keys) (signed account trading requirements); [GitHub Pages API](https://docs.github.com/en/rest/pages/pages?apiVersion=2022-11-28#update-information-about-a-github-pages-site) (site build mode reference).
- **Verification performed:** `node --check assets/app.js` passed; Python HTML parse/local-reference check passed for all 8 HTML pages; all 8 pages contain official Kalshi source links; `git diff --check` passed; local static HTTP smoke test returned HTTP 200 for overview, gas topic page, executive summary, review page, and application JS. The repo's existing GitHub Pages endpoint/settings were confirmed through `gh` as public and configured for built-in legacy publishing from `main` root. After merge, the Pages build/deployment completed successfully; the deployed root HTML was fetched. Browser-side Kalshi API/CORS behavior remains unverified. An attempt to switch publishing source through the GitHub API was denied (HTTP 403 integration permission), so the implementation retains the repo's existing branch-publishing mode and does not add a conflicting Actions workflow.
- **Flagged items published in `review.html`:** static page cannot safely access signed demo-account balances/fills or place account orders without credential provisioning and a protected backend; the paper ledger is not account performance; ROI claim is intentionally not made (the filter is an unvalidated threshold plus calculated open-interest-value screen); REST polling can miss intrapoll moves; classification is keyword-based and capped at 800 event entries; causal news attribution and deployed-origin CORS remain unverified. Missing values are left unfilled and marked UNVERIFIED.
- Pull request: [#1 — Build Kalshi demo monitoring and paper-trading dashboard](https://github.com/wingbangboozle1-lang/Trade2/pull/1) merged into `main` at `05803aa414bb37e516c2afab3ec0d40416cc7bcb` on 2026-11-20. No PR checks were reported.
- Deployment: existing built-in Pages publishing from `main` root completed successfully (Pages build/deploy run [44744259044](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44744259044)); public URL: https://wingbangboozle1-lang.github.io/Trade2/ . The deployed root HTML was fetched and verified. The hosted browser's live Kalshi API/CORS execution remains unverified and is flagged on `review.html`.
- Irregularities: Pages Actions emitted a non-blocking Node.js 20 deprecation warning for its upload-artifact action; the deployment still succeeded. GitHub integration returned HTTP 403 when asked to change the Pages publishing mode, so existing legacy `main`-branch deployment was retained.
- Status: implementation and Pages deployment complete; account authentication/trading, API CORS, market coverage, and strategy validation remain clearly flagged limitations, not verified features.
