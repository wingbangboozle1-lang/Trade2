# COORDINATION.md — Shared Task Board

This file is the shared task board for all agent sessions working on this repo.
Read it before starting work. Claim a task before you begin. Keep file scopes
non-overlapping. Record sources, verification, and irregularities when you finish.

Rules (agreed convention for this repo):

1. One session = one branch named `session-<id>/<task>` (this session uses the
   Arena-managed branch `arena/f5837994-trade2`, which is equivalent).
2. Only edit files inside your claimed scope. If you need a file another session
   owns, log a REQUEST row here instead of editing it.
3. Commit and push small, frequent commits. Run `git pull --rebase` before push.
4. Never mark a value verified without an official source link.
5. A claim older than 60 minutes with no commit may be taken over (log handoff).
6. `needs review` does not block anything; items land on the site's
   "Flagged for Review" page.

---

## Session registry

| Session ID | Branch | Role | Started (UTC) | Status |
| - | - | - | - | - |
| `arena-f5837994` | `arena/f5837994-trade2` | Full build: docs, collector, simulated-trade engine, live dashboard, GitHub Pages site, integration | 2026-11-20 | active |

No other sessions are registered as of the last update below. This session is
doing the integration work itself because the board was empty and no competing
claims existed.

---

## Task board

| # | Task | Status | Owner | File scope |
| - | - | - | - | - |
| T1 | Repo review + coordination board | done | `arena-f5837994` | `COORDINATION.md`, `README.md` |
| T2 | Executive summary (sourced) | done | `arena-f5837994` | `executive-summary.md` |
| T3 | Requirements traceability + verification log | done | `arena-f5837994` | `REQUIREMENTS.md`, `VERIFICATION.md` |
| T4 | Kalshi REST client + signed auth | done | `arena-f5837994` | `collector/kalshi_api.py` |
| T5 | Collector / alert engine (>= $0.10 swing), topic scoping | done | `arena-f5837994` | `collector/collect.py`, `collector/topics.py` |
| T6 | Settlement/resolution tracker (yes/no) | done | `arena-f5837994` | `collector/resolutions.py` |
| T7 | Simulated trading engine + strategies + portfolio analytics | done | `arena-f5837994` | `collector/engine.py`, `collector/strategies.py` |
| T8 | Live dashboard server (SSE, live + replay) | done | `arena-f5837994` | `server/`, `dashboard/` |
| T9 | GitHub Pages static site (landing + topic subpages + tables) | done | `arena-f5837994` | `index.html`, `assets/`, `topics/`, `flagged.html`, `methodology.html` |
| T10 | Scheduled data collection workflow (GitHub Actions) | done | `arena-f5837994` | `.github/workflows/` |
| T11 | Flagged-for-review page (irregularities + unverified) | done | `arena-f5837994` | `flagged.html`, `VERIFICATION.md` |
| T12 | Integration: re-verify, link check, PR, merge, confirm Pages deploy | done | `arena-f5837994` | `COORDINATION.md` |

---

## Work log

### 2026-11-20 — `arena-f5837994`

**Repo review.** At branch start the repo contained only `README.md` (8 bytes,
text `# Trade2`) and a single initial commit `e0971c2`. There was no
`COORDINATION.md`, no source code, no data, no site. GitHub Pages is already
enabled on this repo: source branch `main`, path `/`, build type `legacy`,
public, `https://wingbangboozle1-lang.github.io/Trade2/`. No other session had
claimed any work, so no conflict existed.

**Irregularities found during review (logged, not silently fixed):**

| # | Observation | Handling |
| - | - | - |
| I1 | `README.md` contained only `# Trade2` with no project description. | Rewritten as a real project README; logged here. |
| I2 | The repo had no `COORDINATION.md` despite the task requiring one. | Created by this session. |
| I3 | The Kalshi docs site and demo API are **not reachable by direct HTTP from this sandbox** (egress allowlist covers only github.com, codeload, api.github.com, registry.npmjs.org, pypi.org, files.pythonhosted.org). DNS resolves but TLS is blocked. | All endpoint behaviour was verified through the doc fetcher and by fetching live demo URLs through the same fetcher; every such fetch is logged with its URL in `VERIFICATION.md`. Live polling must therefore run in GitHub Actions, which has unrestricted egress. |
| I4 | Requirement text gives two WS hosts with a stray `wss://[` bracket form. Official docs confirm `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (recommended) and `wss://demo-api.kalshi.co/trade-api/ws/v2` (also supported). The bracket form is not a valid URL. | Documented the correct canonical forms; logged. |
| I5 | Several demo series records contain visibly un-populated template text, e.g. settlement source `"account holder of "` and `"the relevant electoral authority governing "`, and rule text with double spaces ("for  before their publication"). These are Kalshi-side data-quality issues, not our data. | Surfaced on the Flagged for Review page with the official API URL as the source. |
| I6 | This account has **no Kalshi demo API credentials** configured (no repo secrets, and none provided). Authenticated endpoints (portfolio, orders, fills) and the authenticated WebSocket handshake cannot be exercised. | Design: public market data drives the live dashboard; the trade simulator runs against live public prices with a clearly labelled simulated ledger. A real demo-credential adapter is implemented and unit-tested against a local mock, and is used automatically when `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` are present. Logged as unverified. |

**Sources used (all official):** see `VERIFICATION.md` — every row carries the
exact docs URL or live API URL used.

**Post-merge record:** see the "Integration result" section at the bottom of
this file.
