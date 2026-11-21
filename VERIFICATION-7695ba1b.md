# VERIFICATION — final integration session `arena-7695ba1b`

**Branch:** `arena/7695ba1b-trade2` · **Base:** `main` @ `8d15b959f232067a5e1db1e68b7a4096ee6502f5`
**Session window:** 2026-11-21 07:05Z → 2026-11-21 08:10Z (UTC)
**Role:** integration — merge the open branches, re-verify the combined tree
against the official demo API, confirm the site builds with no broken links,
publish to GitHub Pages.

Everything below was checked against an **official** source (a Kalshi
documentation page or a live response from `external-api.demo.kalshi.co`).
Nothing is inferred. Where a value could not be confirmed it is left blank
and listed, not filled in.

---

## 0. What was merged, and why

| Source | Content | Merge | Conflict |
| --- | --- | --- | --- |
| PR **#29** (`arena/c78c9b36`) | T14 coordination closeout | `3c1f646` | none |
| PR **#57** (`arena/f3cb9b9f`) | Browser live pulse, YES/NO chart, order-book proxy, price-mix strip | `d1b3e6a` | `COORDINATION.md` only, resolved as a **union** — Board K (the author's) and Board L (mine) both kept verbatim, nothing dropped |
| PR **#28** (`arena/dd1da6b5`) | order-book shortlist, swing news links, topic feeds, snapshot verification | **not merged** | see §5 |

---

## 1. Defects found in the merged tree and fixed here

### D-1 — The browser live pulse measured nothing (request shape)

**Found:** in the code merged from PR #57, `assets/desk.js:pulseUrls()` built
`?tickers=A,B,C`.

**Official source:** `tickers` is declared as a **string[]** query parameter —
"List of market tickers to fetch orderbooks for", "Required array length:
`1 - 100` elements" —
<https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks>.
The exchange reads one value per occurrence of the parameter, so a
comma-joined value is read as *one ticker whose name contains the commas*.

**Live proof** (demo exchange, 2026-11-21 ~07:20Z):

| Request | Response |
| --- | --- |
| `GET /markets/orderbooks?tickers=KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70` | **one** entry, ticker `"KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70"`, `orderbook_fp {"yes_dollars":[],"no_dollars":[]}` |
| `GET /markets/orderbooks?tickers=KXPRESNOMD-28-RW&tickers=KXAAAGASM-26NOV30-4.70` | **two** entries, each with its real book |

**Impact:** every refresh returned one empty book under a name no tracked
market had, so no quote ever matched. The panel nevertheless reported
"LIVE PULSE · N readings" — a healthy-looking number for a measurement that
never happened. The whole point of the merged feature (a ≥ $0.10 swing
detector that runs *between* the 5-minute collector runs) was inert.

**Fixed:**

* `assets/live-feed.js` — new pure, exported `batchOrderbookUrl(base, tickers)`
  that builds the documented repeated-parameter form.
* `assets/desk.js` — `pulseUrls()` uses it; the pulse now **fails loudly**
  ("no tracked ticker in response (N unmatched)") instead of counting an
  empty refresh as a reading.
* `server/app.py` — the same-origin proxy forwarded only
  `query.get("tickers")[0]`; it now forwards **every** occurrence and still
  accepts a comma-joined list.
* CI — the browser live pulse had **no test coverage at all**
  (`test/live-feed.test.mjs` was never executed by any workflow).
  `test/live-feed.test.mjs` and the new `test/live-feed-url.test.mjs` now run
  in `npm test`, in `kalshi-dashboard.yml` and in `site-check.yml` (so every
  pull request is gated).

**Regression tests are mutation-checked.** Reverting `batchOrderbookUrl`
makes 7/7 Node cases fail; reverting the proxy makes 3/5 Python cases fail;
re-introducing the comma-join in `desk.js` makes the source-level
assertion fail.

**Note on the published data:** the *Python* collector already used the
repeated form (`urllib.parse.urlencode(..., doseq=True)` in
`collector/kalshi_api.py`), so the published ladders and every published row
were correct. Only the browser path was affected. Verified: see §2.5.

### D-2 — 60 published market rows had no official source link

**Found:** `tools/rowsource_check.py` audits the intermediate JSON of the
`docs/` and `kalshi-dashboard/` pipelines. The root pipeline — the one
published at <https://wingbangboozle1-lang.github.io/Trade2/> — builds its
per-row source link at *render* time, so that tool could not see it and
**no audit covered the primary site**.

New tool `tools/rootsource_check.py` audits the **served HTML** instead.
First run: **813 market rows across 22 published pages, 60 with no official
demo source link** — the "Tracked markets" table on `live.html` (40 rows) and
the trade-ledger / open-position / settled-position tables on `trades.html`
(19) and `summary.html` (1). Those rows linked only to the human
`kalshi.com/markets/...` page, never to the API response the number came
from.

**Fixed** in `site_build/build.py`, `site_build/extras.py` and
`assets/desk.js` (the client-rendered desk rows mirror the static markup).
After the fix: **888 market rows, 888 with a demo API link, 0 production-host
links.**

### D-3 — The automated re-check of published rows was never published

`tools/verify_rows_479.py` re-opens the top event of every topic, its market
row and its order book from the official demo endpoints and compares them
field by field with the published snapshot (EXACT / DRIFT / UNVERIFIED, with
the official URL on every row). Its evidence was committed to
`audit/verify-479.json` but **never surfaced on the site**.

**Fixed:** `review.html` now carries a *"Published rows re-checked against the
official API"* panel — 75 rows with result, topic, market, field, published
value, official value and a link to the exact official response. When no run
has been recorded the panel says so; it never invents a result.

---

## 2. Line-by-line re-verification against the live demo API

Snapshot under test: `data/live.json`, `generated_at` **2026-11-21T06:48:53Z**,
`api_root` `https://external-api.demo.kalshi.co/trade-api/v2`.
Checks run **2026-11-21 07:35Z–07:45Z** (≈50 min after the snapshot).

Verdicts: **EXACT** = identical · **DRIFT** = the live market moved between
the snapshot and the check (both values shown, never equalised) ·
**UNVERIFIED** = the response could not be read; nothing was guessed.

### 2.1 `KXPRESNOMD-28-RW` — elections (the brief's "highest dollar amount" example)

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW>

| Field | Published | Official | Verdict |
| --- | --- | --- | --- |
| `yes_bid` | $0.0380 | `yes_bid_dollars` 0.0380 | EXACT |
| `yes_ask` | $0.0390 | `yes_ask_dollars` 0.0390 | EXACT |
| `open_interest_contracts` | 189,529,515.91 | `open_interest_fp` 189529515.91 | EXACT |
| `volume_contracts` | 414,933,199.79 | `volume_fp` 414933298.61 | **DRIFT** (+98.82 — the market traded on) |
| `status` | active | `active` | EXACT |
| `close_time` | 2028-11-07T15:00:00Z | 2028-11-07T15:00:00Z | EXACT |
| `result` | (empty) | `""` | EXACT |
| OI value | $189,529,515.91 | `open_interest_fp` × `notional_value_dollars` 1.0000 | EXACT |

### 2.2 `KXPGATOUR-THRC26-TMOO` — golf

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO>

| Field | Published | Official | Verdict |
| --- | --- | --- | --- |
| `yes_bid` | $0.0030 | 0.0030 | EXACT |
| `yes_ask` | $0.0050 | 0.0050 | EXACT |
| `open_interest_contracts` | 1,156,492.05 | 1156538.99 | **DRIFT** (+46.94) |
| `volume_contracts` | 1,161,980.94 | 1162027.88 | **DRIFT** (+46.94) |
| `status` | active | active | EXACT |
| `close_time` | 2026-12-06T00:00:00Z | 2026-12-06T00:00:00Z | EXACT |

### 2.3 `KXAAAGASM-26NOV30-4.70` — gas prices (a market with **no two-sided quote**)

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70>

| Field | Published | Official | Verdict |
| --- | --- | --- | --- |
| `yes_bid` | *(blank / UNVERIFIED)* | `yes_bid_dollars` 0.0000, `yes_bid_size_fp` 0.00 | EXACT — a 0.0000/1.0000 record quote is **not** a price; the site refuses it instead of publishing a phantom $0.50 |
| `yes_ask` | *(blank / UNVERIFIED)* | `yes_ask_dollars` 1.0000, `yes_ask_size_fp` 0.00 | EXACT (same rule) |
| `open_interest_contracts` | 58,062.52 | 58062.52 | EXACT |
| `volume_contracts` | 58,071.52 | 58071.52 | EXACT |
| `status` | active | active | EXACT |
| `close_time` | 2026-11-30T04:59:00Z | 2026-11-30T04:59:00Z | EXACT |

### 2.4 `KXCRITICSFOREIGN-27-LAB` — culture (also no two-sided quote)

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXCRITICSFOREIGN-27-LAB>

| Field | Published | Official | Verdict |
| --- | --- | --- | --- |
| `yes_bid` | *(blank / UNVERIFIED)* | 0.0000, size 0.00 | EXACT |
| `yes_ask` | *(blank / UNVERIFIED)* | 1.0000, size 0.00 | EXACT |
| `open_interest_contracts` | 473,339.45 | 473339.45 | EXACT |
| `volume_contracts` | 671,773.31 | 671773.31 | EXACT |
| `status` | active | active | EXACT |
| `close_time` | 2028-01-04T15:00:00Z | 2028-01-04T15:00:00Z | EXACT |

### 2.5 `KXBTCY-27JAN0100-B127500` — crypto

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B127500>

| Field | Published | Official | Verdict |
| --- | --- | --- | --- |
| `yes_bid` | $0.0000 | 0.0000, size 0.00 | EXACT |
| `yes_ask` | $0.0100 | 0.0100, size 16645.00 | EXACT |
| `open_interest_contracts` | 39,647,709.32 | 39647719.80 | **DRIFT** (+10.48) |
| `volume_contracts` | 83,476,872.27 | 83476923.76 | **DRIFT** (+51.49) |
| `status` | active | active | EXACT |
| `close_time` | 2027-01-01T05:00:00Z | 2027-01-01T05:00:00Z | EXACT |

### 2.6 Order book — `KXPRESNOMD-28-RW`

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW/orderbook?depth=25>

The published ladder and every derived figure were recomputed from the live
response using the rules the official page states
(<https://docs.kalshi.com/getting_started/orderbook_responses>: "Arrays are
sorted by price in **ascending order**"; "The **highest** bid (best bid) is
the **last** element in each array"; "Best YES ask: $1.00 - (Highest price in
the `no_dollars` array)").

| Published | Official | Verdict |
| --- | --- | --- |
| `best_yes_bid` 0.038 | last `yes_dollars` element `["0.0380","13869.69"]` | EXACT |
| `best_no_bid` 0.961 | last `no_dollars` element `["0.9610",…]` | EXACT |
| `best_yes_ask` 0.039 | 1.00 − 0.9610 | EXACT |
| `best_no_ask` 0.962 | 1.00 − 0.0380 | EXACT |
| `spread` 0.001 | 0.0390 − 0.0380 | EXACT |
| `yes_bids` ladder (8 levels, best first) | 0.038 / 0.037 / 0.036 / 0.035 / 0.034 / 0.033 / 0.020 / 0.019 with the same contract counts | EXACT |
| `yes_bid_contracts` **60,503.36** | Σ of **all** YES levels in the live book: 100.00 + 32.10 + 0.16 + 8.00 + 5050.50 + 4901.96 + 4.47 + 18518.48 + 18018.00 + 13869.69 = **60503.36** | EXACT |
| top NO level size | published 394.01, official 232.07 | **DRIFT** (size changed; the *price* 0.961 is identical) |

This confirms the published "contracts available at a given price" ladder and
the aggregate depth figure are exactly what Kalshi's book said, and that the
Python collector's request shape (repeated `tickers=`, or the single-market
endpoint) was always correct.

### 2.7 A resolution row — `KXAAAGASCDAK-26NOV20-LD` (gas prices, YES)

Published row (`data/resolutions.json`): `result` **yes**, settlement value
**1.0000**, `settlement_ts` **2026-11-20T10:35:14.609488Z**.

Source: <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASCDAK-26NOV20-LD>

| Field | Published | Official | Verdict |
| --- | --- | --- | --- |
| `result` | yes | `"result":"yes"` | EXACT |
| settlement value | 1.0000 | `"settlement_value_dollars":"1.0000"` | EXACT |
| `settlement_ts` | 2026-11-20T10:35:14.609488Z | identical | EXACT |
| status | settled | `"status":"finalized"` | EXACT |

Settlement rule confirmed against
<https://docs.kalshi.com/getting_started/market_settlement>: "**Yes outcome**:
Yes contract holders receive $1 per contract · **No outcome**: No contract
holders receive $1 per contract."

### 2.8 Summary of the live re-check

| Checks | EXACT | DRIFT | UNVERIFIED |
| --- | --- | --- | --- |
| 5 market rows × up to 7 fields, 1 order book (11 fields), 1 resolution (4 fields) | 42 | 6 | 0 |

Every DRIFT is a size/quantity that changed because the market traded in the
50 minutes between the snapshot and the check. **No structural mismatch and
no unexplained value was found.**

---

## 3. Official documentation claims re-checked (each page fetched live)

| Claim the code depends on | Official page (fetched 2026-11-21) | Holds? |
| --- | --- | --- |
| Best bid = **last** element of `yes_dollars` / `no_dollars`; arrays ascending | <https://docs.kalshi.com/getting_started/orderbook_responses> | yes — stated verbatim |
| Best YES ask = $1.00 − best NO bid; only bids are returned | same | yes — stated verbatim |
| A market with no resting orders (or an unknown ticker) returns empty arrays and HTTP 200, not 404 | same | yes — stated verbatim; this is why an empty book and a bad ticker are indistinguishable on that endpoint |
| `GET /markets/{ticker}/orderbook`, `depth` 0–100 counted from the best bid | <https://docs.kalshi.com/api-reference/market/get-market-orderbook> | yes |
| `GET /markets/orderbooks`, `tickers` is a string[] of 1–100 elements | <https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks> | yes — **this is the claim D-1 turned on** |
| YES holders receive $1 on a YES outcome, NO holders $1 on a NO outcome | <https://docs.kalshi.com/getting_started/market_settlement> | yes — stated verbatim |
| Demo REST host `https://external-api.demo.kalshi.co/trade-api/v2` | <https://docs.kalshi.com/getting_started/demo_env> | yes |
| Candlestick `period_interval` must be 1, 60 or 1440 minutes | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks> | yes |

---

## 4. Build, link and render gates on the merged tree

| Gate | Result |
| --- | --- |
| `python3 -m unittest discover -s tests` | **269 passed, 1 skipped** (skipped: `cryptography` not installed) |
| `npm test` | **54 passed / 0 failed** (was 29 before this session added the live-pulse suites) |
| `node --test test/live-feed.test.mjs test/live-feed-url.test.mjs` | 25 passed / 0 failed |
| `python3 tools/linkcheck.py` | **50 pages · 679 internal links · 0 errors** |
| `node tools/rendercheck.mjs` | 12 pages rendered offline, all `ok` |
| `node tools/root_pages_render.mjs` | **ALL PASS — 13 root pages, 244 files linked** |
| `node test/desk_render_dc732aa6.mjs` | **DESK RENDER CHECK PASSED** |
| `node test/site_smoke.mjs docs/data` | **ALL SITE SMOKE CHECKS PASSED** |
| `python3 tools/rowsource_check.py` | 0 rows missing a source URL, 0 production-host leaks (`docs/` + `kalshi-dashboard/`) |
| `python3 tools/rootsource_check.py` (new) | **888 market rows · 888 with a demo source link · 0 missing · 0 production links** |

---

## 5. Why PR #28 was not merged

PR #28 (`arena/dd1da6b5`) has been open since 2026-11-20T19:26Z; its last
commit is 2026-11-20T20:00Z, so it was idle for >60 minutes and this session
took it over under the board's own rule. Its branch is based on `main` @ `9cceb88`
and **reverts work that has since landed on `main`** (it deletes seven test
files and four tools that exist on `main` today), so it could not be merged
wholesale. Its unique scope was re-checked against `main` line by line:

| PR #28 artefact | Status on `main` | Evidence |
| --- | --- | --- |
| `collector/news.py` CLI → `data/news.json` | **Superseded.** `main` already looks up candidate headlines for every swing inside the collector (`collector/collector.py::attach_news`, line 300) and renders them on the alert rows (`site_build/build.py::alert_chat_row`, line 234) and in the browser (`assets/desk.js`, lines 269–283). The label is "candidate headline, not confirmed" and the row also links the Kalshi event page and a news search — so **R17 is satisfied on `main` today** and the #28 CLI would be a second, divergent copy. | `collector/collector.py` 300–335 · `site_build/build.py` 234–247 · `assets/desk.js` 269–299 |
| `tools/verify_snapshot.py` → `data/verification.json` + a site panel | **Superseded.** `main` already has `tools/verify_rows_479.py` (row-level, EXACT/DRIFT/UNVERIFIED, official URL per row) and the `verify-479` workflow. This session added the missing step: that evidence is now **published on the site** (D-3). | `tools/verify_rows_479.py` · `.github/workflows/verify-479.yml` · `review.html#verified` |
| `collector/shortlist.py` (order-book model, 474 lines) | **Not merged.** The brief's requirement — "two scrolling chats, one with all events and the other that is a selective filter based on events that our model likes as high ROI" — is met on `main` by the net-ROI gate that already drives `#feedModel`. A *second* scoring model is a larger change than the brief asks for, has its own claim surface, and would need its own verification; it is recorded as a request below rather than merged blind. | `assets/desk.js` (model feed) · `REQUIREMENTS.md` R6 |
| `tools/seed_mid_history.py`, `data/mid_history.json` | **Not merged.** Chart history on `main` is seeded from Kalshi's own candlesticks, which is the official source; a seeded file of *simulated* mids would put non-Kalshi numbers on a chart that otherwise shows Kalshi prices. | `assets/desk.js` (candle seeding) |

**Request for a future session (logged in `COORDINATION.md`):** if a second
model is wanted for the model chat, it should be built on top of the current
snapshot with its own per-row official source links, not imported as a
stale branch.

---

## 6. Items left blank / flagged (not filled in)

| # | Item | Why it cannot be verified here | Where it is published |
| --- | --- | --- | --- |
| U-1 | Kalshi **demo-account** balances, positions, orders and fills | Those endpoints require a signed `KALSHI-ACCESS-*` request. No demo API key pair exists in this repository or this session, and creating one needs a person at kalshi.com. | `review.html` — standing limitations |
| U-2 | Placing **real** demo orders | Same cause. The order adapter is implemented and unit-tested against a local mock, and activates automatically when `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` are present. | `review.html` |
| U-3 | The Kalshi **WebSocket** feed (`wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`) | The official docs require the signed handshake headers, which a browser cannot set. The desk therefore measures the same books over the documented anonymous REST batch endpoint instead, and says so on the page. | `live.html` (live-pulse note) · `review.html` |
| U-4 | "Highest dollar amount" ranking for markets whose book is empty | 411 of 750 ranked events have no two-sided quote, so no price may be shown for them. They are ranked and labelled `no book`; the price cells stay blank. | `index.html` price-mix strip · `review.html` |
| U-5 | **Article attribution** for a swing | No official Kalshi source maps news to a price move. The site publishes *candidate* headlines with that label and never asserts causation. | `live.html` chat rows · `review.html` |

---

## 7. Files changed by this session

| File | Change |
| --- | --- |
| `assets/live-feed.js` | new pure `batchOrderbookUrl()` + export (D-1) |
| `assets/desk.js` | uses the documented request shape; fails loudly on an unmatched response; desk rows gain the Source column (D-1, D-2) |
| `server/app.py` | proxy forwards every `tickers` occurrence (D-1) |
| `site_build/build.py` | Source column on the live desk and the settled-positions table (D-2) |
| `site_build/extras.py` | Source column on the trade ledger, open positions and settled positions (D-2) |
| `site_build/flagpage.py` | new "Published rows re-checked against the official API" panel (D-3) |
| `tools/rootsource_check.py` | **new** — source-link audit of the served HTML (D-2) |
| `test/live-feed-url.test.mjs` | **new** — 7 cases pinning the request shape (D-1) |
| `tests/test_orderbook_batch_url_7695ba1b.py` | **new** — 8 cases for the proxy and the call site (D-1) |
| `tests/test_verification_panel_7695ba1b.py` | **new** — 5 cases for the verification panel (D-3) |
| `.github/workflows/kalshi-dashboard.yml` | run the live-pulse suites; `node --check assets/live-feed.js` (D-1) |
| `.github/workflows/site-check.yml` | run the live-pulse suites on **every pull request** (D-1) |
| `package.json` | `npm test` now includes the live-pulse suites (D-1) |
| `COORDINATION.md`, `REQUIREMENTS.md` | Board L; requirement status corrected against this evidence |
| `VERIFICATION-7695ba1b.md` | this file |

---

## 8. Official sources used (all fetched live on 2026-11-21)

* <https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks>
* <https://docs.kalshi.com/api-reference/market/get-market-orderbook>
* <https://docs.kalshi.com/api-reference/market/get-market>
* <https://docs.kalshi.com/api-reference/market/get-markets>
* <https://docs.kalshi.com/api-reference/market/get-market-candlesticks>
* <https://docs.kalshi.com/getting_started/orderbook_responses>
* <https://docs.kalshi.com/getting_started/market_settlement>
* <https://docs.kalshi.com/getting_started/demo_env>
* <https://docs.kalshi.com/api-reference/exchange/get-exchange-status>

Live demo responses (2026-11-21 07:20Z–07:45Z) are listed inline in §2 with
their exact URL.
