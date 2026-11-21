# Verification — session `arena-1e3b2594` (2026-11-20)

Independent, line-by-line re-check of what this repo **publishes**, against
Kalshi's own documentation and the live **demo** API, plus the three defects that
came out of it and the CI reliability work. Nothing here is inferred: every row
below is either a value read out of a fetched response, or a check I ran.

* Session branch: `arena/1e3b2594-trade2` · base `main` @ `eef1243` → rebased `5c75ac0`
  → rebased again onto `ed93060`/`cd48375` (20:31Z) after PRs #48–#52 and #50 landed.
  All statements below are as of **20:45Z**; `main` moves every few minutes in this
  session's window, so run IDs and snapshot timestamps are cited rather than paraphrased.
* Fetch window: 2026-11-20, **20:12Z – 20:45Z UTC**. Published snapshot under test:
  `data/live.json` `generated_at: 2026-11-20T19:58:45Z` (root site) and
  `docs/data/*` `generated_at: 2026-11-20T19:44:12Z` (docs site).
* Method note — **a correction to I3 (Board A) and E2 (`docs/verification/sources.md`)**:
  the sandbox shell still cannot reach Kalshi hosts (allowlisted egress only), but
  the platform's page fetcher **can**. Every "live" row below was retrieved through
  it at the exact official URL, so demo-API verification no longer has to be
  deferred to GitHub Actions. Actions remains the right place for *polling*.

---

## 1. Endpoints and protocol — re-read from the official pages

| Claim in this repo | Official source | Result |
| --- | --- | --- |
| Demo REST root `https://external-api.demo.kalshi.co/trade-api/v2` (recommended); `https://demo-api.kalshi.co/trade-api/v2` also supported; demo WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`, `wss://demo-api.kalshi.co/trade-api/ws/v2` also supported | [getting_started/demo_env.md](https://docs.kalshi.com/getting_started/demo_env.md) (fetched in full) | **Confirmed, character for character**, including the brief's two-surface table. The brief's `wss://[external-api-ws…]` bracket form is not a URL; the canonical forms are the ones above (already flagged as I4). |
| Demo credentials are separate from production, and demo prices may not reflect real markets | same page | **Confirmed** — the page says "credentials are not shared between this environment and production" and warns "The price and behavior of markets in the demo environment may not be reflective of those in real markets." Both sentences are quoted on the site's flagged pages. |
| The four API roots (2 production + 2 demo) are the server list on every endpoint schema | `servers:` block of [get-markets.md](https://docs.kalshi.com/api-reference/market/get-markets.md) and [get-series-list.md](https://docs.kalshi.com/api-reference/market/get-series-list.md), both fetched | **Confirmed.** Our clients point at the demo pair only; `scripts/collect.mjs` additionally rejects production bases (F-17 work). |
| Exchange is up | `GET https://external-api.demo.kalshi.co/trade-api/v2/exchange/status` at ~20:12Z | **Confirmed:** `exchange_active: true`, `trading_active: true`, shards 0–3 all active. Matches the snapshot's `exchange` block exactly. |

## 2. Field-level checks against live demo responses

Seven published rows were re-fetched by ticker and compared field by field.
"Drift" = the live response differs, and the difference is a real trade or quote
change between `19:58:45Z` (our snapshot) and the fetch. Nothing was rounded,
converted, or adjusted — the snapshot stores the API's own strings. All seven
responses carry `expected_expiration_time` (e.g. `"2026-11-22T00:00:00Z"`,
`"2027-01-04T15:00:00Z"`) and none carries `expected_expiration_ts` — the
evidence for §3.1 — and each row's `notional_value_dollars` is `"1.0000"`, which
is why the root site's "Open interest" and "OI value" columns show the same
number for every event.

| Published row (topic) | Field | Snapshot | Live demo API | Verdict |
| --- | --- | --- | --- | --- |
| [`KXPRESNOMD-28-RW`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) (elections, rank 1 by dollars) | `open_interest_fp` | 189,529,515.91 | 189,529,515.91 | **exact** |
| | `yes_bid_dollars` / `yes_ask_dollars` | 0.0350 / 0.0380 | 0.0350 / 0.0380 | **exact**; mid 0.0365 recomputes |
| | `volume_fp` | 414,925,171.17 | 414,925,221.76 | drift +50.59 (trades after the snapshot) |
| [`KXBTCY-27JAN0100-B127500`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B127500) (crypto, rank 1) | `open_interest_fp` | 39,622,305.88 | 39,622,355.46 | drift +49.58 |
| | quotes + `notional_value_dollars` | 0.0000 / 0.0100, $1.00 | same | **exact**; OI$ = OI × notional reproduces the published "OI value" column |
| [`KXPGATOUR-THRC26-TMOO`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO) (golf, rank 1) | bid/ask, `no_bid_dollars` | 0.003 / 0.005, 0.995 | 0.0030 / 0.0050, 0.9950 | **exact** |
| | `yes_bid_size_fp` vs the depth we publish | 305,555.54 cumulative; top level 55,555.55 | `yes_bid_size_fp` 55,555.55 | **exact cross-check** of book vs record |
| [`KXAAAGASM-26NOV30-4.70`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70) (gas prices, rank 1) | `open_interest_fp`, `volume_fp` | 58,062.52 / 58,071.52 | identical | **exact**; book is empty, so the site prints `UNVERIFIED` for bid/ask instead of the record's 0.00/1.00 placeholders — verified as intended behaviour, and it is the correct call |
| [`KXCRITICSFOREIGN-27-LAB`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXCRITICSFOREIGN-27-LAB) (culture, rank 1) | `open_interest_fp`, `volume_fp` | 473,339.45 / 671,773.31 | identical | **exact**. Kalshi-side quirk re-observed: `subtitle: ":"`, and the gas title still carries raw markdown `**gas prices**` (I-R2/I-R3 stand). |
| [`KXXRP15M-26NOV200900-00`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXXRP15M-26NOV200900-00) (a row on the resolutions page) | `result`, `settlement_value_dollars`, `settlement_ts`, `status` | `yes`, `1.0000`, `2026-11-20T14:00:04.608936Z`, finalized | identical | **exact** — resolution tracking matches the official record |
| [`KXPGATOUR-THRC26-MMEI`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-MMEI) (a row on the **docs** site) | `expected_expiration` | **blank** | `2026-11-22T00:00:00Z` | **defect, not missing data** — see §3.1 |
| | OI / volume / quotes | 347,551.77 / 495,557.75 / 0.002–0.003 | 347,736.30 / 495,742.28 / same | quotes exact, size drift is trading |
| | published `$ volume` 1,024.41 | 341,469.99 × 0.003 | — | **derivation reproduces exactly** from the two official fields the row links |

Order book and depth semantics, [`/markets/KXBTCY-27JAN0100-B127500/orderbook`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B127500/orderbook)
at ~20:30Z: `orderbook_fp.no_dollars = [[0.9700,5555.55],[0.9800,8333.33],[0.9900,16447.90]]`,
`yes_dollars = []`.

* ascending with the **best bid last** → our `best_bid()` takes the last element ✓;
* implied YES ask = 1 − 0.99 = **0.0100**, and the market record's own
  `yes_ask_dollars` is 0.0100 ✓ ([orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses));
* `yes_dollars: []` is why the site shows no YES bid instead of inventing one ✓;
* the snapshot's 0.99 level held 16,497.13 contracts, now 16,447.90 (−49.23),
  while the OI on that market rose by +49.58 in the same window — the book and
  the trade print move together, which is what "live depth" is supposed to mean.

Candlesticks, [`/series/KXPGATOUR/markets/KXPGATOUR-THRC26-TMOO/candlesticks?start_ts=1795200000&end_ts=1795207200&period_interval=60`](https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/markets/KXPGATOUR-THRC26-TMOO/candlesticks?start_ts=1795200000&end_ts=1795207200&period_interval=60):
two hourly bars; the bar ending 20:00Z carries `yes_bid.close_dollars 0.0030` and
`yes_ask.close_dollars 0.0050`, i.e. mid **0.0040 — the exact mid our 19:58Z
snapshot publishes for that market**, so the reference bar the alert rule measures
against is the one Kalshi itself printed. The response carries precisely the six
documented required fields (`end_period_ts`, `yes_bid`, `yes_ask`, `price`,
`volume_fp`, `open_interest_fp`)
([get-market-candlesticks.md](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md)).
The same page fixes `period_interval` to the enum **1 / 60 / 1440 minutes**
(`validate: required,oneof=1 60 1440`, 400 otherwise) — so a "seconds" chart
window cannot be candles: our `seconds` window is a 1-minute-bar **window**,
already flagged (F-5b, F-E1-08) and left as a labelling item for the site owner.

## 3. Defects found, fixed, and how each fix was proven

Three defects surfaced. All three are "published value is wrong or blank when the
official value exists" problems, which is the class this repo must not carry.

### 3.1 `expected_expiration` read a key the API does not return (docs site)

`collector/runner.py:234` and `docs/assets/app.js:189` both read
`expected_expiration_ts`. Six live market objects (§2) each return
`expected_expiration_time` (ISO string); none returns the `_ts` form. Consequence:
the docs tables published a blank "expected expiration" column for **40/40 rows**
and labelled it unconfirmable (F-4F-05) — the value was there the whole time.
Independent confirmation: session `arena-e1a76b9d` reached the same conclusion
from the schema side (F-E1-01 / R-E1-01 / R-E1-02) while I reached it from live
responses; this change implements both requests.

Fixed in both paths (Python collector + browser live layer), value copied
verbatim, no conversion. Proven by mutation: reverting the key makes
`python3 -m collector.test_runner` exit 1 with
`AssertionError: {'expected_expiration': None, …}`, and reverting the JS line makes
`node tests/test_docs_live.mjs` report `FAIL: live row keeps the API's
expected_expiration_time verbatim`. Restoring either turns them green again.

### 3.2 The simulated ledger assumed one fee multiplier for every series

The official schedule is `fees = round_up(M × 0.07 × C × P × (1 − P))`
([kalshi-fee-schedule.pdf](https://kalshi.com/docs/kalshi-fee-schedule.pdf),
"Last updated and effective: July 7, 2026"; re-read this session, including the
21-row General Trading Fees table, "Settlement Fees: There is no settlement fee",
"Membership Fees: There is no membership fee", and the Non-Standard Fees table's
per-series maker/taker multipliers). `M` is published per series in the API too —
`fee_multiplier` and `fee_type` are **required** fields of `Series`
([get-series-list.md](https://docs.kalshi.com/api-reference/market/get-series-list.md)).

`trading/engine.py` (docs pipeline) already read the series value;
`collector/engine.py` / `collector/alerts.py` (root pipeline, the one the landing
page publishes) called `kalshi_fee(price, contracts)` with the default M=1 — a
difference the site itself was already flagging ("Taker fees use a multiplier of 1
for every series", `review.html`). So the model could screen a fee-free series out
on a fee it does not pay, and the two dashboards could disagree about one trade.

Fix: `alerts.fee_params()` resolves `(M, basis)` from the market's own series row
(the collector now finds that row through `series_row_for_event`, because
`GET /markets` objects carry no `series_ticker`), the signal carries both, the
position stores them, entry and exit charge with them, and a non-quadratic
`fee_type` (the schedule's "flat" = Specific Trading Fees Table) is charged **0 and
labelled** rather than guessed. Historical positions keep M=1 — that is what they
were actually charged — so no published P&L is restated.

**No number on the site changes today**, and that is checked, not asserted: all
**300** series the collector tracks report `fee_type: quadratic`, `fee_multiplier: 1`
in the current snapshot, and `kalshi_fee(p, c, 1.0) == kalshi_fee(p, c)` is pinned by
`tests/test_fee_multiplier.py` (18 tests, incl. fee-free → net ROI = gross ROI,
M=2 → exactly double, settle → no fee at all, old state file still loads).

**Flagged, not resolved:** the two official sources *disagree* for the very series
the crypto board leads with — the PDF lists `KXBTCY` at maker 0 / taker 0, while
[`GET /series/KXBTCY`](https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY)
returns `fee_multiplier: 1`, `fee_type: "quadratic"`, `last_updated_ts:
2026-10-07` (after the PDF's July 7 effective date; the PDF defers to
[kalshi.com/fee-schedule](https://kalshi.com/fee-schedule) for later changes).
We follow the API field, because that is what the environment being simulated
reports, and every fee row now prints which basis it used.

### 3.3 A made-up $0.50 could reach a published dollar column

`market_notional()` filled `price = 0.5` when a response had no last price and no
bid/ask, and the same function feeds the row's `notional_usd` (F-E1-05,
R-E1-02). Now it returns `None`, the column stays blank and is flagged
`notional-unverified:…`, and the fallback survives only inside `market_rank`, where
0.0 is a sort convention no reader can mistake for a value. 0 of 40 docs rows hit
the path today. Covered by `tests/test_market_row_mapping.py` (10 tests).

### 3.4 Which standing board requests these close

| Request | Asked for | This session |
| --- | --- | --- |
| R-79CC-1 (`arena-79cc0bd5` → `arena-856e184e`) | "Thread `fee_multiplier` into the two `kalshi_fee(...)` sites in `collector/engine.py` (`topics.py` already caches it); the plumbing crosses `collector/collector.py`" | **Implemented** (§3.2), plus the third site in `alerts.py` the request did not know about. 18 tests. |
| R-DC-3 (`arena-dc732aa6`) | scheduled collector runs starved by a shared concurrency group | **Implemented** for `collector.yml` + `dashboard.yml`; `kalshi-dashboard.yml` left to PR #28 → V1. |
| R-DC-4 (`arena-dc732aa6`) | data-commit steps fail the run on a superseded regenerated snapshot | **Implemented** for both files, behaviour verified in a scratch repo (§4). `kalshi-dashboard.yml` already had it (that is `63a12595`, merged). |
| R-E1-01 / R-E1-02 (`arena-e1a76b9d`, Board G) | `expected_expiration_time` in `docs/assets/app.js:189` and `collector/runner.py:234`; `runner.py:197/232` null instead of a $0.50 fill | **Implemented** (§3.1, §3.3). The two sub-items *not* done, deliberately: taking series `fee_type` into `docs/data/series.json`/market rows (needs a second endpoint's join + its own source link; V5) and relabeling "$ volume"/"verified" headers (site-copy owner's call). |
| R-901-02 (`arena-901c3b83` → PR #28 owner) | "reconcile the model-chat render contract and rerun the browser-path CI check before treating the pipeline as green"; the record notes "this audit does not infer which" side is wrong | **Resolved in favour of the merged product behaviour**, with the reason and the mutation evidence in §4. `assets/desk.js` untouched — it needed no change. |

## 4. Why the "live" site had stopped being live, and the fix

The root site's own publisher (`Kalshi dashboard — collect, build, deploy`) has
been red on `main` since PR #40 — every run from `44808974745` (20:10:45Z) to
`44810878098` (20:23:09Z) is `failure`, with `44809122838`, `44809455693`,
`44809872442` `cancelled` in between. Because that step sits **before** the commit
step, a red X there means: collect runs, data is built, **nothing is published**.
Measured: the deployed landing page still served the `19:58:45Z` snapshot ~40
minutes later, and its own age badge said "23m old" / "24 min" when I re-ran the
check locally.

* Failing step, checked rather than assumed: `gh run view 44810878098 --json jobs`
  → exactly one failed step, `Desk render check (browser path)`; same step is
  recorded for `44810053873` in `arena-901c3b83`'s integration record. (GitHub's
  log download still returns `EOF` for these runs, so step-level detail comes from
  the API and a local reproduction, not from a log.)

* Reproduced locally: `FAIL model chat uses the published shortlist, not a
  client-side re-gate — expected 0, got 5`.
* Cause: the check predates PR #40's merged contract (pinned by
  `tests/test_chat_rows.py`): the model chat may show the labelled
  "no ≥ \$0.10 swing yet" signal fallback when no swing clears the gate, because
  intersecting alerts with signals left the brief's second chat permanently empty.
  `assets/desk.js` labels every fallback row, so the product is behaving as merged.
* The check itself also had **no teeth**: forcing `model = []` in `assets/desk.js`
  (ignoring the published shortlist entirely) left it green, because the fixture's
  shortlist row was reproducible from the fallback path. So the fix is not a
  loosening — the fixture gained a shortlist row below the gate with no matching
  signal, and I re-ran both mutations (ignore the shortlist; re-gate client-side):
  each turns the file red, clean tree green.
* **Concurrent fix, kept rather than overwritten.** While this section was being
  written, session `arena-479bbd2f` landed PR #50 (merge `5f1bdf3`, 20:24:26Z),
  which reaches the same conclusion about the same assertion — aligned with the
  merged PR #40 contract, `assets/desk.js` untouched — and added a fixture case
  for the signal fallback. Its next run `44811082933` (20:24:29Z) is the first
  green one in that window: `Desk render check (browser path)` **and**
  `Commit data` both succeeded, and the publisher resumed —
  `data/live.json` advanced to `2026-11-20T20:29:48Z` (from the 19:58:45Z that had
  been stuck), `docs/data/markets.json` to `20:31:13Z`, and Pages built `ed93060`
  at `20:31:57Z` with `error: null`. I rebased onto it, took **their** version of
  the assertion, and kept only what was additive in mine (below). Logged as an
  overlap: neither session had claimed `test/desk_render_dc732aa6.mjs`, so the
  board's file-claim mechanism did not prevent two fixes converging on one file.
* What mine adds on top of theirs: the fixture's shortlist case had no teeth —
  its one shortlist row was `KXBTC-1`, which is also `fixture.signals[0]` and
  `fixture.alerts[0]`, so the fallback path could produce the same single row.
  Verified by mutating `assets/desk.js`: forcing `model = []` (ignoring
  `high_roi_alerts` completely) still passed. The fixture now carries a second
  shortlist member (`KXETH-1`, `model_net_roi` 0.02 — below `model_gate.min_net_roi`
  0.05, with no matching signal), which *only* a faithful render of the published
  shortlist can produce, and the assertion identifies rows by content. Both
  mutations (ignore the shortlist; re-gate it client-side) now fail the file; the
  clean tree passes. `assets/desk.js` was never modified.
* `.github/workflows/collector.yml` and `dashboard.yml` (R-DC-3, R-DC-4):
  the group key now includes `github.event_name`, because GitHub cancels a
  *pending* run when a newer one enters its group and `cancel-in-progress: false`
  protects only the running one
  ([official rule](https://github.com/github/docs/blob/main/data/reusables/actions/actions-group-concurrency.md))
  — which is why scheduled runs `44804717748`, `44804612803` died whenever a merge
  landed; and both data-commit steps now treat a rebase conflict confined to their
  own regenerated output as "snapshot superseded" (notice, reset to remote, exit 0),
  while a conflict touching anything else, or a rejected push, still fails.
  Behavior verified by executing the extracted step against a scratch repo:
  clean publish → exit 0; same-file conflict → `::notice::snapshot superseded`,
  exit 0, tree reset to the concurrent snapshot; edits outside the published
  directory → discarded, never published.

### 4.1 Scheduled runs: what is actually happening, and a correction to R-DC-3

Group names on `main` before my change: `collector.yml` → `collector-${{ github.ref }}`,
`dashboard.yml` → `kalshi-dashboard`, `kalshi-dashboard.yml` → `collect`. The three
collectors therefore never shared a group, so R-DC-3's framing ("different collector
workflows share a group") is **not** what the data shows. Every cancellation I could
pin down sits *inside one* workflow's own group, on the file PR #28 owns:

| Run | Workflow | Event | Created | Outcome |
| --- | --- | --- | --- | --- |
| `44804612803` | `kalshi-dashboard.yml` | push | 19:42:19Z | `cancelled` |
| `44804717748` | `kalshi-dashboard.yml` | **schedule** | 19:43:00Z | `cancelled` ~17 s in |
| `44809122838`, `44809455693`, `44809872442` | `kalshi-dashboard.yml` | push | 20:11–20:16Z | `cancelled` (replaced by the next merge's run in group `collect`) |
| `44805016315`, `44805392264` | `kalshi-dashboard.yml` | push | 19:44–19:47Z | `failure` at the data-commit step (before `63a12595` made it conflict-tolerant) |

That is GitHub's pending-replacement rule working as documented — a queued run in a
group is cancelled when a newer run enters, `cancel-in-progress: false`
notwithstanding
([official rule](https://github.com/github/docs/blob/main/data/reusables/actions/actions-group-concurrency.md)).
My `github.event_name` key removes it for the two files I claimed (a queued
schedule/dispatch run can then only be superseded by another queued schedule/dispatch
run), and R-1E3-1 asks the owner of `kalshi-dashboard.yml` — where the evidence lives —
to take the same one-line change. I did not edit it.

The larger cause is repo-wide runner-queue pressure, and **no concurrency key fixes
that**. Measured from `GET /repos/…/actions/runs?per_page=100` covering
20:10:45Z–20:34:44Z: **70 `push` runs, 11 `pull_request`, 13 Pages builds — and 2
`schedule` runs** (`collector.yml` 20:29:34, `kalshi-dashboard.yml` 20:29:39). For a
`*/5` cron that window should hold ~4 scheduled runs; `dashboard.yml`'s `*/30` got
none at all, and because its push trigger is filtered to `scripts/**`, `config/**`,
`site/**`, `dashboard.yml`, the ~70 pushes never compensate. Result on `main`:
`kalshi-dashboard/data/latest.json` is still `19:55:06Z` while `data/live.json`
advanced to `20:29:48Z`. GitHub documents exactly this — scheduled runs can be
delayed or skipped during busy periods
([`on.schedule`](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions#onschedule)) —
and the repo's own comment says so: `cron: '*/30 * * * *'  # GitHub may delay
scheduled runs (flag F-09)`. So the honest summary for the board is: this PR removes
the mechanism the repo controls and makes the publisher conflict-tolerant; the
residual staleness is a scheduling-policy question (fewer push-triggered data jobs,
or accept the lag and keep labelling it, which the snapshot-age badge already does)
and is left flagged rather than "fixed" by pretending the cron fired.

## 5. Deployed-site pass (GitHub Pages, cache-busted)

`GET https://wingbangboozle1-lang.github.io/Trade2/?v=58f1446` (fetched 20:2xZ, while
the `19:58:45Z` snapshot was still the newest published one) renders the real
overview: 750 markets tracked, 0 swings in the current buffer, 4 open simulated
positions, equity $9,659.02 against a $10,000 start, 328 resolved events, the
"Demo exchange status: trading" banner, five topic links, and per-row `API ↗`
links — including `UNVERIFIED` cells for the markets whose books are empty, which
is the intended rule rather than a gap.
`GET /Trade2/docs/?v=58f1446` renders the second desk with **4 live ≥ \$0.10
alerts**, two scrolling chats (All events / High-ROI picks), candidate-news links
labelled as headlines rather than causes, per-row market + candlestick links, and
the paper-account banner. After PR #50 unblocked the publisher, `main`'s payload advanced to `20:29:48Z`
(6 open simulated positions, equity $9,325.42, still 0 buffered swings, 328 resolved)
and Pages built `ed93060` at 20:31:57Z with `error: null` — so the pages above are
the *stale-snapshot* rendering, which is exactly what the age badge is for.
`tools/linkcheck.py` on the same tree: **50 pages, 666 internal links, 0 errors**; `tools/rendercheck.mjs` and
`test/root_render.mjs`: all pages render; `npm test` 29/29;
`node tests/test_docs_live.mjs` ALL PASS; `node test/site_smoke.mjs docs/data`
ALL PASS; `python3 -m unittest discover -s tests` **224 pass, 1 skipped**
(the skip is `cryptography`, absent in this sandbox — signed requests stay
unexercised here and are exercised in CI).

## 6. Left flagged — not silently "fixed"

| # | Item | Why it stays a flag |
| --- | --- | --- |
| V1 | `kalshi-dashboard.yml` still puts its `*/5` schedule and its push runs in one `collect` group — and that is where **all** the measured cancellations actually live (§4.1) | Open PR #28 edits that file, so it was not touched here: logged as request **R-1E3-1** with the exact one-line change and the run IDs. This also corrects R-DC-3's premise (the three collector workflows never shared a group). |
| V2 | `review.html` / `methodology.html` still say the collector ledger "applies a multiplier of 1 to every series" | True when written; §3.2 makes it stale. The text lives in `site_build/flagpage.py` / `build.py`, owned by PR #28 → request **R-1E3-2** with the replacement wording. Until then the page under-describes the code, which is the safer direction of error. |
| V3 | Three dashboards (`/`, `/docs/`, `/kalshi-dashboard/`) rank "highest dollar" differently: root = OI × notional, docs = 24h volume × last price (e.g. `KXPGATOUR-THRC26-MMEI`: $347,651.57 vs $1,024.41) | Both are honest derivations of official fields and each is labelled; unifying them is a product decision for the integration owner (already I-R1 / F-E1-04). |
| V4 | Root ranking is per *market* while the column reads "event" | `alerts.rank_events()` scores one market's OI and labels it with its event ticker; the event's aggregate is larger for multi-market events. Changing it rewrites every published table, so it is reported, not done here. |
| V5 | `docs/data/markets.json` `fee_type` blank 40/40 | Correct: it is a series field, not a market field. Filling it means a second endpoint join with its own source link — recommended, not done (would touch the docs generator). |
| V6 | Kalshi-side data quirks in the demo responses | Re-observed live today: [`KXCRITICSFOREIGN-27-LAB`](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXCRITICSFOREIGN-27-LAB) returns `subtitle: "::"` and an `updated_time` frozen at its `open_time` (`2026-10-06T23:38:00.181638Z`) even though its `last_price_dollars` is 0.19 and 671,773.31 contracts have traded — so `updated_time` cannot be used to detect staleness; the docs pipeline prints a market title with raw markdown (`Will average \*\*gas prices\*\* be above $3.6400?`), which is the API's own `title`. Not ours to fix, and we do not clean it silently: the rows show what the exchange returns. |
| V8 | The scheduled refresh cadence cannot be met as configured (§4.1: 2 scheduled runs in a 24-minute window against `*/5` + `*/15` + `*/30`, `dashboard.yml` skipped twice) | Cause is GitHub-side queue behaviour under ~70 push runs from the parallel sessions, plus a same-file pending-replacement rule. Reducing push-triggered data jobs (paths filters, `[skip ci]` — added to the dashboard publish commit here) is the only in-repo lever, and the site already labels the lag. **Flagged, not asserted fixed.** |
| V7 | Checked and **cleared**: the landing page's "Open positions 4" tile vs `data/live.json` `positions_count: 5` | Not an inconsistency: `collector/engine.py:398/414` publishes `open_positions` (4 live) and `positions_count` = every position ever opened (4 open + 1 settled). Verified against `data/portfolio_state.json` (5 positions, 4 open, 6 trades). Reported because a reader comparing the two numbers would otherwise flag it. |

## 7. Unverified by design

* **Real demo-account portfolio and order execution.** No credentials exist in
  this repo and none were requested or stored; `GET /portfolio/…` and order entry
  are therefore unexercised here. Everything labelled SIMULATED is a paper ledger
  matched against live public prices.
* **News causation.** The docs feed shows Google News headlines as *candidate*
  catalysts with the fetch labelled in the row; no headline is presented as the
  cause of a move, and empty link cells say so.
* **Model edge.** The high-ROI screen is a filter, not a forecast; the published
  book shows every loss.
* **WebSocket.** Anonymous browser handshakes remain out of scope (the site never
  claims WS liveness); I did not re-probe the handshake this session, so the
  existing `docs/data/capabilities.json` probe record stands as the evidence.

## 8. Reproduce

```bash
python3 -m unittest discover -s tests          # 224 pass, 1 skip
python3 -m unittest -v tests.test_fee_multiplier tests.test_market_row_mapping
python3 -m collector.test_runner               # offline end-to-end on captured payloads
python3 -m trading.test_engine                 # 42 official fee rows
npm test && node test/desk_render_dc732aa6.mjs && node tests/test_docs_live.mjs
python3 tools/linkcheck.py && node tools/rendercheck.mjs && node test/site_smoke.mjs docs/data
python3 -m site_build.build                    # regenerates every page from data/live.json
```

Every official URL quoted above was fetched in this session between 20:12Z and
20:45Z UTC on 2026-11-20; the live demo API is a moving dataset, so re-running
later will show trade drift (and should show *no* unexplained mismatch).
