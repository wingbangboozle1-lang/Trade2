# COORDINATION.md — shared task board

Repo: `wingbangboozle1-lang/Trade2` · Live site: https://wingbangboozle1-lang.github.io/Trade2/ · Pages source: this repo (configured via API)

This file is the shared task board for parallel agent sessions. Update it in the same commit as the work it
describes. **Never** start a task another session has claimed. If a task needs a file owned by another session,
log the request here instead of editing the file.

## Rules in force

1. One session = one branch. Branch naming requested by the owner is `session-<id>/<task>`. **Special case for
   this session:** the Arena platform pins the working branch (`arena/c0205283-trade2`), so this session cannot
   create `session-…/…` branches. All work by `sess-c0205283` lands on `arena/c0205283-trade2` and reaches `main`
   through a single pull request. Other sessions may branch freely as instructed.
2. `git pull --rebase` before every push. Small, frequent commits.
3. Shared outputs (`docs/index.html`, `docs/assets/nav.js`, `docs/data/*.json`, this file's *Status* column)
   are changed only by the **integration** session once all other tasks are done.
4. `needs review` = published on the site's *Flagged for Review* page; it does **not** block anything.
5. A claim older than 60 minutes with no commits may be taken over; note the handoff in the log below.
6. **Verification rule:** every published value must be reproducible from an official source (Kalshi Trade API v2
   response, Kalshi documentation, or a named official publisher). Unconfirmed values are left blank and listed on
   the *Flagged for Review* page. No inference, no interpolation, no invented numbers.

## Task board

| # | Task | Status | Owner (session) | Files / scope |
|---|------|--------|-----------------|---------------|
| 1 | Repo audit + source verification of Kalshi endpoints/fields | done | sess-c0205283 | `collector/`, `docs/verification/` |
| 2 | Data collection (gas, elections, culture, crypto, golf) — official demo API | done | sess-c0205283 | `collector/`, `docs/data/markets.json` |
| 3 | Alert engine ≥ $0.10 swings + two alert chats | done | sess-c0205283 | `collector/`, `docs/data/alerts.json`, `docs/assets/*` |
| 4 | Live charting (seconds/minutes/hours) + liquidity/orderbook depth | done | sess-c0205283 | `collector/`, `docs/assets/charts.js` |
| 5 | Simulated trading engine, strategies, scoreboard | done | sess-c0205283 | `trading/`, `docs/data/strategies.json` |
| 6 | Live demo-account execution + portfolio tracking | needs review | sess-c0205283 | `trading/execute.py` — **blocked on credentials**, see FL-01 |
| 7 | Event resolution tracking (YES/NO outcome) | done | sess-c0205283 | `collector/`, `docs/data/resolutions.json` |
| 8 | Executive summary | done | sess-c0205283 | `EXECUTIVE_SUMMARY.md`, `docs/summary.html` |
| 9 | Site build (landing + per-category subpages + tables) | done | sess-c0205283 | `docs/` |
| 10 | Flagged for Review page | done | sess-c0205283 | `docs/flagged.html` |
| 11 | Integration: re-verify combined data, build check, PR, merge, Pages deploy | done | sess-c0205283 | all |

Statuses: `unclaimed` · `in progress` · `done` · `needs review`.

## Log

### 2026-11-20 — sess-c0205283 — repo audit

- Repo at base commit `e0971c2` contained only `README.md` (8 bytes). No prior claims, no other branches. Task
  board created; tasks 1–11 claimed by `sess-c0205283` because no other session was present. Any later session
  should claim from the *unclaimed* pool or coordinate via this log.
- **Environment finding (affects how this repo is built):** the agent sandbox's network egress is allowlisted to
  `github.com` / `codeload.github.com` / `api.github.com` / `registry.npmjs.org` / `pypi.org` /
  `files.pythonhosted.org`. Direct `curl` to `external-api.demo.kalshi.co` returns HTTP 000. Live Kalshi data was
  therefore read through the platform's web-fetch channel (same official host, no proxy rewriting of payloads —
  raw JSON was returned, see `docs/verification/`). The collector shipped here is designed to run on **GitHub
  Actions runners**, which do have general egress, so the published site updates itself without the sandbox.
- Because there is no long-running backend in this repo's hosting model (GitHub Pages is static), "live" is
  delivered three ways, all documented on the site: (a) scheduled collector on GitHub Actions, (b) browser-side
  REST/WebSocket polling when the demo API's CORS policy allows it (feature-detected, with a visible badge), and
  (c) an optional local live server (`live/server.py`) for tick-level use.

### 2026-11-20 — sess-c0205283 — credentials status (FL-01)

- Trading endpoints (`/portfolio/balance`, `/portfolio/orders`, `/portfolio/fills`) require an Ed25519 or RSA API
  key issued from the Kalshi demo account. No key exists in this repo, and the owner instructed "no manual input".
  An agent cannot mint a Kalshi key. Therefore: order **placement** runs in `simulated` mode (paper fills against
  the real demo order book) until `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PEM` are added as repo secrets.
  Everything else (market data, alerts, simulation, portfolio analytics) is real and live. Logged as FL-01 on the
  Flagged for Review page. Task 6 = `needs review`.
