# Verification — session `arena-27de8294` (task N1)

**Branch:** `arena/27de8294-trade2` · **Base:** `main` @ `3c69da6` · **Date:** 2026-11-21 (UTC)
**Defect fixed:** the previous-snapshot swing fallback could never fire, and an empty
alert chat read as "nothing happened".

Every number below was produced by a command shown next to it, from the committed
snapshot or the official Kalshi documentation. Nothing is inferred. Where a value
could not be confirmed, the cell is blank and the item is listed in §6.

---

## 1. The defect, proven on the committed snapshot

| # | Claim | How it was checked | Result |
| - | ----- | ------------------ | ------ |
| 1.1 | The snapshot payload had **no** `observations` key, so the reader in `collect()` always produced an empty mapping | `python3 -c 'import json; print("observations" in json.load(open("data/live.json")))'` | `False` |
| 1.2 | The reader was the only source of `previous_obs` | `grep -n "previous_obs" collector/collector.py` (before the fix) | lines 525–528 assign from `previous_live.get("observations")`; line 687 reads it |
| 1.3 | The documented fallback therefore could not fire | `grep -n "previous_snapshot_mid" collector/alerts.py` | set only in `_swing()`'s `elif previous is not None:` branch, which needed a non-`None` `previous` Observation |
| 1.4 | Most tracked markets had **no** candle reference, so the fallback is the basis that matters | `python3` count over `data/live.json` (`events` with `observation.ref_ts`) | **98 of 750** have a reference bar, **652 of 750** do not |
| 1.5 | The refusals the snapshot published are the symptom of 1.3 | `data/live.json → suppressed_alerts` | 4 of 4 carry `"reference quote is missing or wider than the $0.10 threshold"` |
| 1.6 | The `docs/` pipeline measured real moves in the same window while the root chat was empty | `docs/data/alerts.json` (`generated_at 2026-11-21T06:24:58Z`) vs `data/alerts.json` (`version 3`) | docs: **6** swing rows (`+0.22`, `+0.877`, `+0.11`, `−0.38`, `−0.21`, `−0.17`); root: **0** rows |

Snapshots used: `data/live.json`, `generated_at = 2026-11-21T07:19:43Z` for 1.1–1.5, and
`2026-11-21T07:27:10Z` after a re-run for 1.6. These files are **generated data** and are
replaced by every scheduled collector run, so the numbers describe those runs, not a
permanent state. The 750 / 98 / 652 split was re-checked on both runs and was identical.

---

## 2. Official sources opened for this change

| Source | Why it is needed here | What it states |
| ------ | --------------------- | -------------- |
| <https://docs.kalshi.com/api-reference/market/get-market-candlesticks> | the reference basis | `GET /series/{series_ticker}/markets/{ticker}/candlesticks` returns `candlesticks[]`; each has `yes_bid`/`yes_ask` with `close_dollars`, and `price` with `close_dollars` **and** `previous_dollars`. `period_interval` is **required** and is one of `1`, `60`, `1440` **minutes**. Quote closes are the only fields used as a swing basis here. |
| <https://docs.kalshi.com/api-reference/market/get-markets> | the measured fields | market objects carry `yes_bid_dollars`, `yes_ask_dollars`, `yes_bid_size_fp`, `yes_ask_size_fp`, `open_interest_fp`, `volume_fp`, `result`, `settlement_value_dollars`, `settlement_ts`, `status`. There is **no** `series_ticker` field on the market object. |
| <https://docs.kalshi.com/getting_started/orderbook_responses> | how a quote is derived | order books are **bids only**; the best bid is the **last** level; implied YES ask = `1.00 − best NO bid`. A book with no levels yields **no** price. |
| <https://docs.kalshi.com/getting_started/market_settlement> | resolution | a YES market pays YES holders \$1; a NO market pays NO holders \$1; settlement timing "can vary". |
| <https://docs.kalshi.com/getting_started/api_environments> | environment | demo REST `https://external-api.demo.kalshi.co/trade-api/v2`, also `https://demo-api.kalshi.co/trade-api/v2`; demo WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`, also `wss://demo-api.kalshi.co/trade-api/ws/v2`. |

Live demo response opened during this session (shape only, one market):

* <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70> —
  2026-11-21, `yes_bid_dollars` `0.0000`, `yes_ask_dollars` `1.0000`,
  `yes_bid_size_fp` `0.00`, `last_price_dollars` `0.0200`, `open_interest_fp` `58062.52`,
  `volume_fp` `58071.52`, `status` `active`, `result` `""`, `close_time`
  `2026-11-30T04:59:00Z`, no `series_ticker` field. This is what a "no book" row means:
  a last trade exists, but **no two-sided quote does**, so the platform publishes a
  blank price for it and the site labels the row `no book`.

---

## 3. What changed

| File | Change | Scope note |
| ---- | ------ | ---------- |
| `collector/collector.py` | new `observation_store()` and `previous_observations()`; the payload now publishes `"observations"`; new additive `"snapshot_fallback"` counters | settlement block untouched (owner `arena-57e6bd3d`, done); the swing *rule* in `collector/alerts.py` untouched (owner `arena-856e184e`) — only the caller that feeds it |
| `assets/desk.js` | new `emptyAllFeedHtml()`; the "All events" chat states how many markets were measured, how many had a candle reference, and how many earlier rows the fallback could use | chat empty state only; detector, chart and pulse untouched |
| `site_build/build.py` | new `empty_all_feed()`, used for the pre-rendered (JavaScript-disabled) chat | one call site inside `build_live()` |
| `tests/test_snapshot_fallback_27de.py` | new, 11 tests, all offline | new file |
| `test/desk_render_dc732aa6.mjs` | one assertion replaced: the empty chat must **state the counts**, not merely mention `0.10` | that single assertion |

`data/**`, `docs/data/**`, `categories/**` and the root `*.html` in this branch are
**generated** by `python3 -m site_build.build`; they are not hand-edited.

---

## 4. Verification performed

| Gate | Command | Result |
| ---- | ------- | ------ |
| New regression suite | `python3 -m unittest tests.test_snapshot_fallback_27de -v` | **11 / 11 OK** |
| Full Python suite | `python3 -m unittest discover -s tests` | **305 ran, OK (skipped=12)** — the 12 skips are the same environmental ones recorded by earlier sessions (`cryptography` absent, jsdom not installed in that runner) |
| Node suite | `npm test` | **54 / 54, 0 fail** |
| Desk render (real `desk.js` in jsdom) | `node test/desk_render_dc732aa6.mjs` | **PASSED** |
| Root pages render | `node test/root_render.mjs` | **RENDER CHECK PASSED** — 13 pages |
| Render check | `node tools/rendercheck.mjs` | **ok** on every page |
| Internal links | `python3 tools/linkcheck.py` | **50 pages / 680 links / 0 errors** |
| Per-row source links | `python3 tools/rootsource_check.py` | **892 rows / 892 with a demo source / 0 production links** |
| Site build | `python3 -m site_build.build` | exit 0 |

### Mutation check (the tests must actually catch a regression)

| Mutant | Effect | Result |
| ------ | ------ | ------ |
| M1: payload key renamed `observations` → `observations_typo` | the next run reads nothing again | **caught** (`FAILED (failures=1)`) |
| M2: reader reverted to `previous_obs = {}` | the fallback is dead again | **caught** (`FAILED (failures=1)`) |
| Restored file | — | **OK** |

### End-to-end proof in the tests (not just units)

`tests/test_snapshot_fallback_27de.py::CollectEndToEndTests` runs the real `collect()`
twice against a fake client that serves one market with quotes `0.20 / 0.22` on run 1
and `0.40 / 0.42` on run 2, and whose candlestick endpoint returns an **empty** list
(the exact condition the live demo returned for 652 of 750 markets). On run 2 the
collected alert is:

* `direction` = `up`, `delta` = **+0.20**, `reference_basis` = **`previous_snapshot_mid`**,
* `bar_start` a multiple of 300 s, and `market_url` pointing at the exchange's page.

Without either half of the fix this test fails.

---

## 5. Live effect and its limit

| # | Item |
| - | ---- |
| 5.1 | The published `data/live.json` in this branch is **regenerated** by the scheduled collector (`kalshi-dashboard.yml`, cron `*/5`). The next run after this merges writes the `observations` array and the `snapshot_fallback` counters. Until then the chat says **"no earlier rows yet"** — the honest answer, not an invented baseline. |
| 5.2 | The `docs/` pipeline (`docs/data/alerts.json`, 6 rows) is a **separate** store with its own cadence and its own topic rotation. This change does not merge the two stores; differences between them stay visible on the site rather than being levelled (carried forward as R-57-4). |
| 5.3 | No Kalshi demo API key exists in this repository, so no demo-account balance, position or fill is claimed anywhere. The paper book stays labelled **SIMULATED**. |

---

## 6. Flagged for review (not blocking, published on `review.html`)

| ID | Item |
| -- | ---- |
| F-27-1 | **The before-fix state is recoverable from git only.** `data/*.json` is generated, so the 07:19Z snapshot described in §1 exists in this branch but is replaced by the next run. The verification was performed on it before the fix landed. |
| F-27-2 | **The `docs/` chat and the root chat still measure different sets** (root: 750 markets ranked by open-interest value; docs: 12 series per topic). Both publish their own source links; the numbers are not comparable one-to-one and the site does not imply that they are. |
| F-27-3 | **`period_interval=1` is one minute, not "seconds".** The desk's *Seconds / Minutes / Hours* buttons are time **windows** (90 s / 60 min / 12 h) over 1-minute candles plus live book polls; they are not sub-minute candles, because Kalshi's endpoint does not offer one (`period_interval` ∈ {1, 60, 1440} minutes). Unchanged by this task; restated so it is not misread as fixed here. |
| F-27-4 | **12 environmental test skips** in this sandbox (`cryptography` not installed, jsdom absent from the bare runner). They are skipped, not passed. |
| F-27-5 | **Cross-check against `previous_dollars` is still open** — carried forward from R-F3-1. A candle publishes `price.previous_dollars`; using it to cross-check swing direction would catch a single stray quote at the source. That belongs to `collector/alerts.py`, owned by another session's task. Logged, not implemented here. |
