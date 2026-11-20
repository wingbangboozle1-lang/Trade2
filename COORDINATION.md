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
| 4 | Live charting (seconds/minutes/hours) + liquidity/orderbook depth | done | sess-c0205283 | `collector/`, `docs/assets/app.js` (canvas charts) |
| 5 | Simulated trading engine, strategies, scoreboard | done | sess-c0205283 | `trading/`, `docs/data/portfolio.json` (stats by strategy/type) |
| 6 | Live demo-account execution + portfolio tracking | needs review | sess-c0205283 | `trading/execute.py` — **blocked on credentials**, see FL-01 |
| 7 | Event resolution tracking (YES/NO outcome) | done | sess-c0205283 | `collector/`, `docs/data/resolutions.json` |
| 8 | Executive summary | done | sess-c0205283 | `EXECUTIVE_SUMMARY.md`, `docs/summary.html` |
| 9 | Site build (landing + per-category subpages + tables) | done | sess-c0205283 | `docs/` |
| 10 | Flagged for Review page | done | sess-c0205283 | `docs/flagged.html` |
| 11 | Integration: re-verify combined data, build check, PR, merge, Pages deploy | in progress | sess-c0205283 | all — PR link recorded below once opened |

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

### 2026-11-20 — sess-c0205283 — build log (collector, trading, site, CI)

- **Official fee schedule located and verified directly:** https://kalshi.com/docs/kalshi-fee-schedule.pdf
  (effective 2026-07-07). Taker `ceil(0.07·C·P·(1−P))`, maker `ceil(0.0175·C·P·(1−P))` (M defaults 0),
  no settlement/membership fee. `trading/test_engine.py` reproduces **all 42 rows** of the published table.
  Prose-vs-table rounding nuance logged as FL-05.
- **Topic mapping verified live** against `/series` (2026-11-20): Golf is a *tag* (`category=Golf` → null;
  use `category=Sports&tags=Golf`) — FL-06; gas sits in Economics+energy tags; Culture/Crypto/Elections are
  strict categories. `collector/topics.py` implements strict vs broad rules; `collector/test_runner.py` asserts
  inclusion (golf/gas/crypto/culture/elections) and exclusion (`KXRATECUTS` not gas, `KXNBA` not tracked).
- **Candlestick evidence for alerts:** live1-second candles for `KXDEMOFUTHOURLY-26NOV20H14-UP` printed
  0.65→0.35→0.65 sequences (≥$0.10 moves) — the alert rule has a real dataset.
- **Bugs found & fixed by tests (all before any data was published):**
  (a) `collect_series` referenced the pre-refactor `categories_any` attribute → crashed the first CI run;
  (b) `trading/engine.py` reloaded `positions` with `dict(list)` → crash on the *second* cycle (persistence bug);
  (c) ROI score threshold made alert-based entries unreachable → switched to dollar net-edge scoring;
  (d) workflow step name contained an unquoted colon → YAML parse failure.
- **Test gates now run in CI before any data commit:** `python3 -m trading.test_engine` (fee table + engine),
  `python3 -m collector.test_runner` (end-to-end on real captured payloads), `node test/site_smoke.mjs`
  (jsdom: 28 assertions across index/topic/portfolio/flagged/summary pages).
- **CI design:** push runs = tests+site smoke only (no API traffic, no commits → no loops); schedule
  (`*/15 * * * *`, default branch only) + `workflow_dispatch` = collect + engine + commit `docs/data`.
  Adaptive client pacing grows the request interval on HTTP 429 and decays it on success.
- **Live-feel implementation:** `live/server.py` (optional local server) exposes `/api/stream` (SSE, 5s);
  `docs/assets/app.js` auto-detects it and upgrades to push mode, otherwise the Pages site polls the
  published JSON every 20s. Documented on the site; Pages never depends on the local server.
- **Verification ledger:** `docs/verification/sources.md` (claims → official URLs). Flagged page:
  `docs/flagged.html` (live flags + curated FL-01…FL-09).

### 2026-11-20 — sess-c0205283 — live-data bring-up (all verified against the real API from Actions)

Serial diagnosis loop (each fix landed with a regression test before the next run):

1. First live run: `collect_series` referenced a pre-refactor attribute → crashed; fixed; offline fixture test added.
2. Run with real data: **6,651 series matched / 6,522 errors** — Entertainment+Mentions+Elections categories hold
   thousands of series and the request budget was burned on per-series market scans. Fixed: volume-ranked cap
   (`SERIES_PER_TOPIC=12`), budget-aware early stops, error-list cap (100 + total).
3. Golf matcher false-positive: ticker regex `PGA` matched inside `KXATPGAME` (ATP tennis); title regex `masters`
   matched `KXMCMMEN` (ATP Monte-Carlo). Anchored to `PGATOUR|KXPGA` etc.; regression fixtures assert exclusion.
4. Gas matcher too broad: tag `Oil and energy` pulled ERCOT power/oil series. Tightened to gas-specific
   tags/title/ticker; `KXSPRMAX` (WTI) now excluded (regression-tested).
5. Real market objects have **no `series_ticker` field** and report `status:"active"` (not `"open"`) — candles
   silently fetched nothing and the UI filtered every market out. Fixed: derive series from ticker prefix,
   normalize `active`→`open`; both behaviors regression-tested.
6. `include_volume` populates **`volume_fp`** (not `volume`) — ranking was arbitrary until the field name was
   verified against the official schema (docs.kalshi.com Get Series List) and a live response.
7. Candle selection ranked all-time volume → far-dated quiet markets, zero points. Fixed: two-phase fetch
   (probe the 6h window across 2× candidates, enrich only markets with real points) + `min_updated_ts=7d`
   recency filter (with fallback to the full list) + ranking prefers 24h activity.
8. Alert logic only compared the last two *seconds*-window closes → missed swings spanning minutes/hours.
   Now scans windows smallest-first and reports the largest qualifying step with its real window label.
9. Corrected a verification overstatement: `period_interval=1` is **1-minute** candles (observed `end_period_ts`
   steps of exactly 60s), not 1-second. `docs/verification/sources.md` D6 and the chart legend updated.

**Live results after bring-up (run 4476…/ad52ff8, 2026-11-20):** 59 series tracked (12/topic, volume-ranked),
40 markets across all five topics, 10 order books, 11 markets charted with real candles, **4 alerts ≥ $0.10**
(+0.806 elections, ±0.12 culture, −0.21/+0.18 gas), 2 of 4 alerts carrying **real matched headlines**
(e.g. gasoline-price article for the gas swing), 300 latest settlements, paper portfolio with 2 open
`roi_edge` positions, $11.62 fees paid per the official formula, 0 errors, 75s runtime.

**Sources for this phase:** live `external-api.demo.kalshi.co` responses (URLs stored per row) ·
https://docs.kalshi.com/api-reference/market/get-series-list (schema: `volume_fp`, `min_updated_ts`,
`include_volume`) · https://docs.kalshi.com/api-reference/market/get-market-candlesticks ·
https://docs.kalshi.com/getting_started/orderbook_responses · https://kalshi.com/docs/kalshi-fee-schedule.pdf ·
https://news.google.com/rss/search (headline candidates, FL-03 wording applies).
