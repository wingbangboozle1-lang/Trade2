# COORDINATION — shared task board

Repo: `wingbangboozle1-lang/Trade2` · Base: `main` @ `e0971c2` · Working branch: `arena/5788e385-trade2`

Session ID: `arena-5788e385` (sole active session on this repo as of 2026-11-20)

> Branch note: the parallel-session rules ask for `session-<id>/<task>` branches. This session is
> bound to the single branch `arena/5788e385-trade2` by Arena, so all task work and the integration
> happen on that branch. Task scopes below are still kept separate by file ownership.

Status values: `unclaimed` · `in progress` · `needs review` (published on the Flagged for Review page; does not block) · `done`

## Task board

| ID | Task | Status | Owner | File scope |
|----|------|--------|-------|------------|
| T1 | Repo review (line-by-line, sourced) | in progress | arena-5788e385 | `REPO_REVIEW.md`, `README.md` |
| T2 | Executive summary | in progress | arena-5788e385 | `EXECUTIVE_SUMMARY.md`, `site/summary.html` |
| T3 | Kalshi API data collector + verification tests | in progress | arena-5788e385 | `scripts/kalshi.mjs`, `scripts/collect.mjs`, `scripts/fees.mjs`, `scripts/test/*`, `config/*` |
| T4 | Live dashboard site (landing, topic subpages, charts, two alert chats) | in progress | arena-5788e385 | `site/*`, `scripts/build-site.mjs` |
| T5 | Simulated trades, strategy + category analysis | in progress | arena-5788e385 | `scripts/strategies.mjs` |
| T6 | Demo-account portfolio tracking (signed requests) | in progress — blocked on user-supplied demo API key secret | arena-5788e385 | `scripts/kalshi-auth.mjs`, `scripts/portfolio.mjs` |
| T7 | Suggestions for live/interactive site | in progress | arena-5788e385 | `site/suggestions.html` |
| T8 | Flagged for Review page + irregularity log | in progress | arena-5788e385 | `config/flags.json`, `site/flagged.html` |
| T9 | Integration: combined verification, build + link check, PR to `main`, merge, Pages deploy | unclaimed (runs last) | arena-5788e385 | `.github/workflows/pages.yml`, `site/sources.html`, `site/index.html` |

## Task log

- 2026-11-20 — `arena-5788e385` claimed T1–T9. Branch pushed with this claim before any other edits.

## Handoffs / conflicts

- None.

## Requests to other sessions

- None (no other sessions active).
