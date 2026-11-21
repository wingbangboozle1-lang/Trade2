# Audit — session `arena-108b0dfb` (2026-11-21)

Scope: line-by-line review of the merged tree on `main` @ `06738d1`, plus the
changes this session made. Every claim below was reproduced before it was
written down. Official sources are linked inline and listed again at the end.

---

## 1. What was already true when this session started

| Check | Result | How it was checked |
| - | - | - |
| The scheduled collectors are alive | **pass** — four workflows on hourly schedules, all recent runs `success` (`425046729`, `425037570`, `425039796`) | `gh run list --workflow=…` |
| The published snapshot is fresh | **pass** — `generated_at` 2026-11-21T06:28Z, ~1 min old at review time | `GET /Trade2/`, `data/live.json` |
| Every row links to its own API response | **pass** — 750 market rows, each with a `…/markets/{ticker}` link | `index.html`, `tools/rowsource_check.py` |
| The demo API is reachable from a browser, not from this sandbox | **confirmed both ways** — `curl` returns `000` (egress blocked), the preview server and the CI-captured `data/_cors.txt` show a 200 with `access-control-allow-origin` echoed for any Origin | shell + `data/_cors.txt` |
| WebSocket needs credentials | **pass** — the official connection page states API-key auth is required to establish the connection | [websocket-connection](https://docs.kalshi.com/websockets/websocket-connection) |
| Batch order books are 1–100 tickers, `orderbooks[].orderbook_fp` | **pass** — exactly what the spec says, and what `assets/live-probe.js` consumes | [get-multiple-market-orderbooks](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks) |

## 2. Defects found and fixed

### N-01 — duplicated, order-unstable sidebar
`site_build/build.py` rendered "Overview" in **both** nav groups and dropped the
active link from the Research group. Measured on the rendered pages:

```
index.html      : Overview … | Live desk, Summary, Resolved, Trades, …
summary.html    : Overview … | Live desk, Overview, Summary, Resolved, …
live.html       : Overview … | Overview, Summary, Resolved, Trades, …
review.html     : Overview … | Live desk, Summary, …, Methodology      (no self-link)
```

Fixed with one canonical nav (`NAV_TOPICS` / `NAV_RESEARCH`, active row keeps its
slot and carries `aria-current`). Guarded by `tools/navcheck.py` and
`tests/test_nav_canonical.py` (7 tests). `summary.html` is hand-maintained rather
than generated, so its sidebar was aligned by hand and is now covered by the same
check.

### N-02 — the live alert chat could not alert
The brief's central requirement is a live ≥ $0.10 alerting chat. On `main` the
public desk rendered `Swings ≥ $0.10: **0**` and an empty chat, because rows could
only come from a scheduled CI job diffing two snapshots, and
`alerts.alert_record_valid()` had purged every pre-rule row. `data/alerts.json`
was literally `{"version": 3, "alerts": []}`.

Fixed by running the same rule in the visitor's browser
(`assets/live-probe.js`): the demo API is CORS-open, so the tab polls
`GET /markets?tickers=…` and `GET /markets/orderbooks?tickers=…` every five
seconds, computes the documented order-book mid, and requires **both** sides
quoted with a spread under $0.10. Verified end-to-end with the shipped page in
jsdom against a stubbed API (`test/desk_live_probe_dc.mjs`) and 25 logic checks
(`test/live-probe.test.mjs`).

Two bugs in the new code were caught by those tests and fixed before commit:
* an exact 10-cent move measured as `9.999999999999998` cents (prices are now
  rounded to the quote grid before arithmetic);
* a total network failure was reported as a healthy poll with 0 markets.

### N-03 — a published phantom swing on the second dashboard
`docs/data/alerts.json` publishes `KXPRESNOMD-28-BOBA` as a **$0.877** upward
move (`from 0.005 → to 0.882`). At the time of the check the official record was:

```
yes_bid_dollars 0.0010   yes_ask_dollars 0.8860   spread 0.885
```

— an 88.5-cent one-sided quote, not a price move. The row is not edited here
(that pipeline has a different owner) but is published, with both source links,
on the Flagged-for-Review page. This is exactly the class of false positive the
browser probe's two-sided rule refuses by construction.

### N-04 — navigation to a 404
`assets/nav.js` always appended `kalshi-dashboard/index.html` relative to the
current directory. From `/Trade2/docs/` that resolves to
`/Trade2/docs/kalshi-dashboard/index.html`, which does not exist in the tree
(the directory is at the repository root). It now maps a known deployment prefix
to the real path and does nothing elsewhere.

### N-05 — stale pull requests
PR **#28** and PR **#29** have been `DIRTY`/`CONFLICTING` since 2026-11-20 and
have merged nothing. #28's headline features are already on `main` (checked:
`high_roi_alerts` in `collector/alerts.py`, `collector/collector.py`,
`site_build/build.py`; `collector/news.py` present; per-topic feeds present), but
three of its files are **not** on `main`: `collector/shortlist.py`,
`tests/test_shortlist.py`, `tools/verify_snapshot.py`. #29 touches only
`COORDINATION.md`. Recommendation, logged rather than acted on: close both with a
note that their code landed via the follow-on merges, after lifting the three
missing files if anyone wants the tighter snapshot verifier.

### N-06 — the resolutions page looked like it had lost data

Each topic panel on `resolutions.html` was capped at 40 rows while its heading
said "268 resolved". Three topics showed "0" with no explanation, so a reader saw
428 settled markets claimed and 40 shown. Fixed by rendering the full 328-row
list in a collapsed table built by the same row function as the panels.

### N-07 — the browser swing detector was asking for the wrong thing

Found by the check written to verify it, which is the point of writing it.

The probe batches both endpoints in one poll. The documentation describes
`tickers` as a list for each of them, which makes `?tickers=A&tickers=B` look
right — and it is right for one of them and wrong for the other. Measured on the
live demo host:

| Request | Result |
| - | - |
| `GET /markets?tickers=A,B` | 200, one record per ticker |
| `GET /markets?tickers=A&tickers=B` | **400** `multiple values for single value parameter 'tickers'` |
| `GET /markets/orderbooks?tickers=A,B` | 200, **one** entry, ticker `"A,B"`, empty book |
| `GET /markets/orderbooks?tickers=A&tickers=B` | 200, one entry per ticker, in request order |

The probe originally comma-joined both. That produced a total failure on the
listing endpoint and a silent empty book on the order-book endpoint — the exact
kind of "success" that would show a trader an empty alert chat on a volatile
afternoon while the page still said LIVE. Fixed with a per-endpoint serialiser,
and the check now fails if the host flips which form it accepts:

* `assets/live-probe.js` — `tickersQuery(tickers, style)`; `/markets` gets
  `"comma"`, `/markets/orderbooks` gets `"repeated"`.
* `test/live-probe.test.mjs` — 27 checks, including one asserting the two
  endpoints receive different shapes, so a future "tidy-up" to a shared helper
  fails loudly.
* `tools/probe_live_check.py` — builds the URLs with the shipped module (not by
  hand) and measures all four serialisations plus four candidate paths against
  the real API.
* `tools/probe_shape_assert.py` — pure assertion layer on that report, 8 unit
  tests, including "the host no longer accepts the form the probe uses" and
  "the forms have become equivalent, so re-measure".
* `.github/workflows/probe-live.yml` — runs both hourly and on any change to the
  probe, because this is a fact about a live API and a live API can change.

* `tools/live_e2e.mjs` — loads the shipped module, seeds the watchlist from the
  snapshot exactly as the page does, and runs two real polls, because every
  other test stubs the network and none of them proved the page receives books.

Verification: [run 44879250677](https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44879250677)
passed every step against the demo host, including the end-to-end poll; the same
check on the uncorrected branch failed with the exact 400 above, so the gate is
demonstrably able to fail rather than merely observed to pass.

## 3. Prompt items that cannot be satisfied, and why

| Prompt line | Why not | What is published instead |
| - | - | - |
| "Track the portfolio performance using the kalshi demo account" | Reading an account needs a signed request with an API key pair; the repo holds none and a key must not be shipped to a public page | A paper ledger marked SIMULATED, graded on real demo prices, plus a complete inert adapter that activates when `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` exist. Flagged. |
| "Live charts should include … website links that may have caused a sharp jump" | No official source maps a news article to a Kalshi move; asserting one would be a guess | Alert rows link the market's own Kalshi page and a plainly labelled news search; a headline appears only when CI fetched one, labelled a candidate. Flagged. |
| "Use the WebSocket API" | The documented connection requires API-key auth | Browser-side REST polling, with the trade-off stated on the Flagged page. |

## 4. Verification performed on the changed tree

```
python3 -m unittest discover -s tests     251 tests, OK (1 skipped)   (was 230)
node test/live-probe.test.mjs             27 checks passed
python3 tools/probe_live_check.py         live demo API, run 44878937002 (CI)
node test/desk_live_probe_dc.mjs          all PASS (shipped page, real script)
python3 tools/navcheck.py                 13 pages, 0 problems
python3 tools/linkcheck.py                50 pages, 672 links, 0 errors
node tools/root_pages_render.mjs          ALL PASS, 13 root pages offline
node test/alerts-view.test.mjs            29 pass (npm test)
```

The site was also served over HTTP (`python3 server/app.py`) and every one of the
13 pages was fetched and parsed with jsdom: 200 for all, two nav groups, 13 links,
no duplicate destination, exactly one active link.

## 5. Sources

| # | Source | Used for |
| - | - | - |
| S1 | <https://docs.kalshi.com/getting_started/orderbook_responses> | bids only, ascending, best bid last, implied ask = 1 − best NO bid |
| S2 | <https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks> | `tickers` 1–100, `orderbooks[].orderbook_fp`, empty arrays for unknown tickers |
| S3 | <https://docs.kalshi.com/api-reference/market/get-markets> | `tickers`-only requests are unpaged; field inventory |
| S4 | <https://docs.kalshi.com/getting_started/rate_limits> | unauthenticated limits are separate and unspecified; back off on 429 |
| S5 | <https://docs.kalshi.com/websockets/websocket-connection> | WebSocket requires API-key authentication |
| S6 | <https://kalshi.com/docs/kalshi-fee-schedule.pdf> | `ceil(M × 0.07 × C × P × (1 − P))` |
| S7 | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-BOBA> | the one-sided record behind N-03 |
| S8 | <https://docs.kalshi.com/getting_started/market_settlement> | YES/NO payout rules quoted on the resolutions page |
