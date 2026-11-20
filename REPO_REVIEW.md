# Repository review — `wingbangboozle1-lang/Trade2`

Reviewed by session `arena-5788e385` on 2026-11-20, against `origin/main` @ `d3cca9d` merged with branch `arena/5788e385-trade2`.

**Scope and method.** Every tracked file on the merged branch is listed below with what was checked. Official sources are linked inline. Kalshi API pages were read through the documentation fetcher. The sandbox cannot reach Kalshi hosts directly (TLS failure, see flag F-06), so no live API call was made from here. The live check happens in GitHub Actions. Irregularities are numbered `RV-n` and mirrored on the site's Flagged for Review page (`config/flags.json`). Rows marked **not reviewed** belong to another session and were not checked line by line.

## Legend

- **OK**: checked, no issue found.
- **IRREGULAR**: an issue that is logged and published as a flag, not silently fixed.
- **UNVERIFIED**: a value or claim that could not be confirmed from an official source, and is left blank or flagged.
- **NOT REVIEWED**: outside this session's scope; flagged for the integration session.

## Official sources used

| Ref | Source |
| --- | --- |
| K-ENV | [API environments](https://docs.kalshi.com/getting_started/api_environments) |
| K-DEMO | [Demo environment](https://docs.kalshi.com/getting_started/demo_env) |
| K-FEE | [Kalshi Fee Schedule (PDF), effective July 7, 2026](https://kalshi.com/docs/kalshi-fee-schedule.pdf) |
| K-AUTH | [API keys and request signing](https://docs.kalshi.com/getting_started/api_keys) |
| K-RATE | [Rate limits](https://docs.kalshi.com/getting_started/rate_limits) |
| K-WS | [WebSocket connection](https://docs.kalshi.com/websockets/websocket-connection) |
| K-OB | [Get market orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| K-SDK | [kalshi-typescript on npm (Kalshi-generated SDK, 3.36.0)](https://www.npmjs.com/package/kalshi-typescript) |

## Per-file review

| File | Lines | What it does | Finding | Status | Source |
| --- | ---: | --- | --- | --- | --- |
| `.gitignore` | 10 | Ignores `_site/`, `state/`, logs, `.env*`, `*.pem`, `*.key` | Credential-pattern ignores are good. `kalshi-dashboard/` is deliberately **not** ignored because it is the published output. | OK | — |
| `package.json` | 13 | npm scripts `test`, `collect`, `build`. No runtime dependencies. Node ≥ 20. | `test` lists four test files explicitly, because `node --test <directory>` fails here (RV-6). | OK | — |
| `COORDINATION.md` | 89 | Task board and conflict log | Merge conflict with `main` was resolved by keeping the other session's board verbatim below this session's sections. Three sessions claim overlapping paths (see the file-scope map). | IRREGULAR (RV-1) | — |
| `README.md` (on main, from `ba6888b7`) | 35 | Project overview, run instructions, limitations, official sources | **Not written by this session.** Its text says the dashboard "polls event snapshots every 15 seconds" and reads the demo host from the browser. The browser CORS behaviour is unverified in the file's own text. It still names the old "Kalshi Market Desk" project. Three sessions claim the file. | NOT REVIEWED (RV-2) | K-DEMO |
| `index.html`, `summary.html`, `review.html`, `categories/*.html`, `assets/app.js`, `assets/styles.css` (on main, from `ba6888b7`) | 368 + 337 + 335 + 5×166 + 889 + 1008 | Root-level dashboard and topic pages | **Not reviewed line by line.** These are another session's files. `categories/gas-prices.html` uses a different slug from the `gas` topic in this branch. `index.html` and `assets/` are also claimed by `arena-f5837994`. | NOT REVIEWED (RV-3) | — |
| `config/topics.json` | 138 | Five topics, fee-schedule series tickers, keyword discovery, High-ROI rule, alert threshold, retention | Series tickers were checked against the fee schedule's Non-Standard Fees table (K-FEE). Keywords were narrowed on 2026-11-20 because "president", "primary" and "masters" matched unrelated series. The High-ROI rule is a placeholder, not a validated model (flag F-13). | OK, with flags F-13, F-14 | K-FEE |
| `config/sources.json` | 90 | Source register S1–S12 (id, title, URL, use, verification) | The S2 verification text was corrected. It now says the fee-table rows are checked against the formula in `fees.test.mjs`, not against the PDF text layer (RV-7). | OK, one correction | K-FEE |
| `config/flags.json` | 305 | Flag register F-01 to F-21 (type, title, detail, links, status) | F-18 and F-19 were `resolved` before any action was taken. They are now `open`. F-20 (public demo snapshot) and F-21 (fail-closed collector) were added. | OK after correction (RV-4) | — |
| `scripts/fees.mjs` | 52 | Taker and maker fee formulas in integer cents; `dollarsToCents` | Formulas match K-FEE as printed: taker `round up(M×0.07×C×P×(1−P))`, maker `round up(M×0.0175×C×P×(1−P))`, maker `M` default 0. Rounding is to **whole cents**. The PDF's own text says "rounded to a centicent" (RV-5). | OK, with RV-5 | K-FEE |
| `scripts/test/fees.test.mjs` | 63 | Asserts all 21 rows of the General Trading Fees Table for 1 and 100 contracts, plus two worked examples | The expected values were transcribed from the PDF and are consistent with the formula. The test does not compare against the PDF text layer itself. | OK | K-FEE |
| `scripts/kalshi.mjs` | ~110 | Public GET client with timeout, 429/5xx backoff, run-wide circuit breaker, and exported `PRODUCTION_BASE` and `DEMO_BASE` | 15 s timeout, 3 retries, breaker after 6 consecutive network errors. The first live run hung for 8+ minutes with the earlier settings, which is why these changed. Rate-limit numbers for unauthenticated calls are not published (RV-8). | OK after fix (RV-9) | K-RATE |
| `scripts/collect.mjs` | ~480 | Collector: exchange status, series discovery, events, order books (top 40 by estimated 24h dollars, depth 10), resolution checks (up to 60 per run), alerts (|Δlast| ≥ 10¢), paper trades, state | Reads `KALSHI_BASE` (default production). Fails closed when the breaker trips. Uses `/events?status=open`, but the market status enum differs from the list filter values (RV-10). | OK, with RV-10 | K-ENV, K-OB |
| `scripts/strategies.mjs` | 167 | Paper strategies (follow, fade, high-ROI rule), settlement from the official result, `summarize()` | Settlement uses the market's official `result` field. Fees come from `fees.mjs`. Strategies are rule-based and are not a predictive model. | OK | K-FEE |
| `scripts/kalshi-auth.mjs` | 48 | Loads an Ed25519 or RSA key, pre-signs `timestamp + METHOD + path` (no query), returns headers | Matches K-AUTH: header names, millisecond timestamp, base64 signature, RSA-PSS SHA-256 with salt equal to the digest length. Unit-tested for both key types. The live demo handshake is not verified. | OK, unverified live (RV-11) | K-AUTH |
| `scripts/portfolio.mjs` | 72 | Read-only snapshot of demo balance and positions. Refuses non-demo hosts. Writes `{connected:false}` when secrets are absent. | Refusal check is `/demo/` in the hostname. No order endpoint is called. Endpoints used are the read-only portfolio balance and positions. Demo funds only (K-DEMO). | OK, unverified live (RV-12) | K-DEMO, K-AUTH |
| `scripts/build-site.mjs` | 140 | Builds `site/pages/*.html` fragments plus the shared template into an output folder. Copies assets and `config/*.json` into `data/`. Checks internal links and config. | Writes `.nojekyll`. Exits non-zero on a broken link. Fixed on 2026-11-20 to use `--out` consistently. | OK | — |
| `scripts/test/collect.test.mjs` | 145 | Collector pipeline against a mock API: alerts, settled gate, fee assertion | — | OK | — |
| `scripts/test/auth.test.mjs` | 46 | Pre-sign text, Ed25519 and RSA-PSS round trips, no secrets → not connected, production host refused | — | OK | K-AUTH |
| `scripts/test/breaker.test.mjs` | 32 | Breaker trips after consecutive errors; a success resets the count | Added in this session. | OK | — |
| `site/assets/app.js` | 386 | Data-driven renderer selected by `body data-page` and `data-topic`. Reads `data/*.json`. Stores picker, range and alert filter in `sessionStorage`. | Fixed on 2026-11-20: negative dollar amounts render as `-$0.38`, not `$-0.38`. Tested in jsdom against synthetic data. **Not yet run in a real browser.** | OK, browser test pending (RV-13) | — |
| `site/assets/style.css` | 69 | Dashboard styling. No external resources. | — | OK | — |
| `site/pages/*.html` (13 files) | 2–60 | Page fragments with `<!--meta: {...}-->` headers | `summary.html` and `suggestions.html` are static. The others are rendered by `app.js`. Every external link in `summary.html` and `suggestions.html` points to a source in `config/sources.json` or to K-* above. | OK | see sources |
| `.github/workflows/dashboard.yml` | ~90 | Scheduled every 30 min: tests → collect → build → commit to `main` | Replaces an earlier Actions-Pages workflow that could not be enabled with this token (RV-14). Collect step is `continue-on-error` so a failed run keeps the previous snapshot. | OK, first run pending (RV-15) | — |

## Other sessions' branches (observed, not on `main`)

| Branch | Notable files | Observation |
| --- | --- | --- |
| `arena/c0affdd1-trade2` | `pipeline/**`, `docs/**`, `analysis/**`, `.github/workflows/collect.yml`, `collector/**` | Has its own COORDINATION.md. Claims `README.md` as "owned by 5788e385" (RV-2). Scheduled data commits (`chore(data): refresh Kalshi demo snapshot`) are on that branch, not on `main`. |
| `arena/f5837994-trade2` | `collector/*.py`, `server/`, `dashboard/`, `index.html`, `assets/`, `REQUIREMENTS.md`, `VERIFICATION.md`, `.github/workflows/` | Has its own COORDINATION.md. Its I5 note reports demo series with template settlement text such as `"account holder of "`. That is a Kalshi-side data-quality issue, and it is not handled in this branch (RV-16). |

## Irregularities (RV)

| ID | Irregularity | Handling |
| --- | --- | --- |
| RV-1 | `COORDINATION.md` on `main` said "sole active session". Three other sessions were active. | Registry rebuilt from observed branches. Conflicts logged. |
| RV-2 | `README.md` is claimed by three sessions. | Not overwritten. Request R-5788-1. |
| RV-3 | Root `index.html`, `assets/` and `collector/` are claimed by more than one session. | Not touched. Request R-5788-2 and R-5788-3. |
| RV-4 | F-18 and F-19 were marked `resolved` with no action taken. | Set to `open`. |
| RV-5 | The fee PDF says "rounded to a centicent", but the table and code use whole cents. | Flag F-02. The table matches whole-cent rounding. |
| RV-6 | `node --test <directory>` fails with MODULE_NOT_FOUND on this Node version. | `npm test` lists files explicitly. |
| RV-7 | The S2 claim about the fee table was overstated. | Corrected in `config/sources.json`. |
| RV-8 | Kalshi's public-endpoint rate limit is not stated numerically in the rate-limit page. | Flag F-06. The collector keeps about 7 requests/second and backs off on 429. |
| RV-9 | The first live run hung for more than 8 minutes with 25 s timeouts and 4 retries per call, run sequentially. The second run (on `main`) hung for about 15 minutes: the 429 `Retry-After` wait was not capped and was not checked against the run deadline. | Breaker, 12-minute deadline, 30 s cap on any single wait, deadline checks before every sleep, 14-minute step timeout, fail-closed write. |
| RV-10 | The list filter values (`open`, `closed`, `settled`, …) differ from the market status enum (`active`, `determined`, `finalized`, …). | Flag F-01. The collector only uses `open` for `/events` and treats market status as data. |
| RV-11 | The signed demo handshake has not been run against a live key. | Flag F-08. |
| RV-12 | The demo portfolio snapshot would be published to the public repo once secrets are set. | Flag F-20. |
| RV-13 | The browser renderer has only been tested in jsdom, not in a browser. | Flag F-22 (to add) and an RV-13 test step on the Flagged page. |
| RV-14 | Actions-based Pages deploy cannot be enabled with this token, and a root deploy would replace other sessions' sites. | Publish to `kalshi-dashboard/` instead (flag F-19). |
| RV-15 | Scheduled collection has not yet run from GitHub Actions. | Flag F-21. Result will be recorded in COORDINATION.md. |
| RV-16 | A demo series title contains template text (`"account holder of "`). | Reported by `arena-f5837994`. Not handled here. |

## What this review did not cover

- Live Kalshi responses (the sandbox cannot reach Kalshi hosts).
- A real browser run of the dashboard.
- The root-level site and other sessions' Python and Node code, beyond what is listed above.
