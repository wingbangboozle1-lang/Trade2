# Verification log

Every claim used to build this dashboard, the exact URL that was opened to check
it, and the result. Nothing in this file is inferred. Where a page could not be
checked, it says so.

**Date of checks:** 2026-11-20 (UTC).
**Method:** official Kalshi documentation pages were read directly; live demo
endpoints were fetched and their JSON inspected; the fee formula was checked
against every row of Kalshi's published fee table by an automated test.

---

## A. Endpoint and environment claims

| # | Claim | Source | Result |
| - | ----- | ------ | ------ |
| A1 | Demo REST root is `https://external-api.demo.kalshi.co/trade-api/v2` | <https://docs.kalshi.com/getting_started/demo_env.md> | **Verified.** Quoted: "Demo's recommended Trade API root is `https://external-api.demo.kalshi.co/trade-api/v2`." |
| A2 | `https://demo-api.kalshi.co/trade-api/v2` is also supported | same page | **Verified.** Table row "Also supported". |
| A3 | Demo WebSocket is `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | same page, and <https://docs.kalshi.com/getting_started/api_environments.md> | **Verified.** |
| A4 | Alternate demo WebSocket is `wss://demo-api.kalshi.co/trade-api/ws/v2` | same pages | **Verified.** |
| A5 | The brief's `wss://[external-api-ws.demo.kalshi.co/...]` bracketed form is valid | — | **NOT VERIFIED.** No official page uses brackets. The bracketed string is not a valid URL. Flagged. |
| A6 | Credentials are not shared between demo and production | <https://docs.kalshi.com/getting_started/demo_env.md> | **Verified.** "credentials are not shared between this environment and production." |
| A7 | Demo prices "may not be reflective" of real markets | same page | **Verified.** Quoted in the warning block. |
| A8 | Signing: `timestamp + METHOD + path`, query excluded | <https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md> | **Verified.** Implemented in `sign_message()`, covered by a test. |
| A9 | RSA-PSS/SHA-256 for RSA keys, direct signing for Ed25519 | same page | **Verified.** Both branches implemented. |
| A10 | Headers are `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE` | same page | **Verified.** |
| A11 | Timestamp must be within 30 s of Kalshi's clock | same page (common issues table) | **Verified.** Not exercised: no credentials. |
| A12 | Order book returns **bids only**, ascending, best bid last | <https://docs.kalshi.com/getting_started/orderbook_responses.md> | **Verified**, and reproduced by unit tests using the docs' own example array. |
| A13 | Implied YES ask = `1.00 − best NO bid` | same page (worked example: NO bid 0.56 → YES ask 0.44) | **Verified** by test. |
| A14 | `open_interest_fp` and `notional_value_dollars` are separate official fields | <https://docs.kalshi.com/api-reference/market/get-markets.md> | **Verified.** `notional_value_dollars` = "the total value of a single contract at settlement in dollars". |
| A15 | `result` is `yes`/`no` on settled markets | live `GET /markets?status=settled` | **Verified.** Observed `"result":"no"`, `"status":"finalized"`, `"settlement_ts"`, `"settlement_value_dollars":"0.0000"`. |
| A16 | YES pays $1/contract, NO pays $0 | <https://docs.kalshi.com/getting_started/market_settlement.md> | **Verified.** |
| A17 | Candlesticks accept only `period_interval` 1, 60 or 1440, max 5,000 periods | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md> | **Verified**, enforced in code (raises on other values). |
| A18 | Batch order books: `GET /markets/orderbooks`, max 100 tickers, empty arrays for unknown tickers | <https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md> | **Verified.** Implemented and unit-tested. |
| A19 | Exchange sharding: `exchange_index` identifies the shard; orders route by `market_ticker` | <https://docs.kalshi.com/getting_started/exchange_sharding.md> | **Verified.** Demo status shows indices 0–3. |
| A20 | Unauthenticated requests are "subject to separate limits", no published numbers | <https://docs.kalshi.com/getting_started/rate_limits.md> | **Verified** as stated. The live demo response carried **no** `X-RateLimit-*` headers (checked in CI), so the collector self-limits with a wall-clock budget. |
| A21 | WebSocket channels `ticker`, `trade`, `market_lifecycle_v2` need the authenticated handshake | <https://docs.kalshi.com/getting_started/quick_start_websockets.md> | **Verified.** Not implemented — see G3. |
| A23 | `category` works as a filter on `GET /events` | <https://external-api.demo.kalshi.co/trade-api/v2/events?status=open&category=Crypto&limit=3> | **NOT SUPPORTED — flagged.** The request returned events from `World` and `Elections`, not only Crypto. The parameter is silently ignored. The collector therefore queries `GET /events?series_ticker=…` for the series it matched, which is the documented filter. |
| A22 | Order payload shape (`ticker`, `side`, `count`, `price`, `time_in_force`, `self_trade_prevention_type`, `client_order_id`) | <https://docs.kalshi.com/getting_started/quick_start_create_order.md> | **Verified** and implemented in `LiveDemoBroker`. **Not executed** — no credentials. |

## B. Fee formula

| # | Claim | Source | Result |
| - | ----- | ------ | ------ |
| B1 | Taker fee = `round_up(M × 0.07 × C × P × (1 − P))` | <https://kalshi.com/docs/kalshi-fee-schedule.pdf> | **Verified.** Formula transcribed from the PDF. |
| B2 | Rounding is "such that the fee + positionCost is rounded to a centicent" | same PDF | **Verified** as text. Note: the published table is reproduced exactly by rounding **the fee alone** up to the cent, which is what the implementation does; the centicent wording would not match the table. See F5. |
| B3 | All 21 one-contract rows and all 21 hundred-contract rows of the published table reproduce | same PDF, general trading fees table | **Verified** — `tests/test_engine.py::TestFees::test_all_published_fee_table_rows` asserts all 42 rows. |
| B4 | Series can carry per-series multipliers (0 = fee free, 2 = combos) | same PDF, non-standard fees table | **Verified.** `fee_multiplier` from `GET /series` is used. |
| B5 | Maker fee is `0.0175 × C × P × (1−P)` with default multiplier 0 | same PDF | **Verified** but **not modelled** — the simulator assumes taker fills only. Flagged. |

## C. Topic scoping (live API checks)

| # | Topic | Check | Result |
| - | ----- | ----- | ------ |
| C1 | Gas prices | `GET /series/KXAAAGASD` | **Verified.** Title "US gas price up"; category `Economics`; settlement source `AAA` → <https://gasprices.aaa.com/>. |
| C2 | Gas prices | `GET /series?category=Commodities` | **Verified.** Statewide AAA gasoline series present, e.g. `KXAAAGASDCT` (Connecticut), `KXAAAGASCDWA` (Washington), `KXAAAGASDAR` (Arkansas). |
| C3 | Elections | `GET /series?category=Elections` | **Verified.** 1,450+ series; includes `CONTROLS` "Senate winner" (volume 2,766,653 contracts) and `GOVPARTY*` state races. |
| C4 | Crypto | `GET /series?category=Crypto` | **Verified.** e.g. `BTCMAXY` "How high will Bitcoin get this year?"; settlement source `CF Benchmarks`. |
| C5 | Golf | `GET /series?category=Sports&tags=Golf` | **Verified.** e.g. `KXPGAR3LEAD` "PGA Round 3 Leader"; settlement sources ESPN, Fox Sports, pgatour.com. |
| C6 | Culture | `GET /series?category=Culture` | **Verified** but only **2** series exist (`KXXBANNEDGROK`, `KXXBANNEDMURRAYHILLGUY1`). |
| C7 | Culture | `GET /events?status=open` category histogram | **Verified.** 413 open events carry category `Entertainment`, 2 carry `Culture`. Culture content is filed under Entertainment, so both categories are queried. |
| C8 | Scope excludes everything else | `GET /events?status=open` histogram | **Verified.** Other categories exist (Sports 1,352; Politics 627; Financials 435; Economics 327; …) and are excluded by explicit per-topic rules. |

## D. Live data observed during the build

| # | Observation | Source |
| - | ----------- | ------ |
| D1 | Demo exchange active, trading active, four shards reported | `GET /exchange/status` (also copied in `data/live.json`) |
| D2 | Order-book CORS is permissive: preflight returns 204 with `access-control-allow-origin` echoing the requesting origin, for `https://wingbangboozle1-lang.github.io`, `http://localhost:8000`, an arbitrary host, and `null` | `OPTIONS /markets` with an `Origin` header, run in CI |
| D3 | The demo API is reachable from GitHub-hosted runners | CI run of the collector |
| D4 | The demo API is **not** reachable from the Arena sandbox (TLS blocked by egress policy) | direct `curl` from the sandbox returned `000` |

## E. Model and simulator behaviour

| # | Claim | How checked | Result |
| - | ----- | ----------- | ------ |
| E1 | A swing of exactly $0.10 alerts; $0.09 does not | unit test | **Verified.** |
| E2 | Missing quotes never alert | unit test | **Verified.** |
| E3 | A gradual move across snapshots alerts against the bar-open reference | unit test | **Verified.** |
| E4 | Stale penny quotes with no depth are excluded | replay of 300 real collected markets | **Verified.** 299 of 300 rejected; the survivors are genuine. |
| E5 | Positions settle from the official `result` and losses are recorded | unit tests | **Verified.** |
| E6 | Fee arithmetic is exact | 42-row table test | **Verified.** |
| E7 | The simulator reproduces demo-account performance | — | **NOT VERIFIED.** It is a paper ledger. Flagged. |
| E8 | The model is profitable | — | **NOT CLAIMED.** No settled trade history long enough to say. Flagged. |
| E9 | A NO-side position is marked, exited and valued on its own side's price | unit tests (`TestExits`, added 2026-11-20) + hand reproduction | **Verified after fix.** A NO position's value is `1 − YES mid`; `mark()` stores that held-side value, `exit_signals()` tests the held-side swing, and `equity` agrees with `unrealized`. See F7. |

## F. Irregularities found (also published on the site)

| # | Finding | Handling |
| - | ------- | -------- |
| F1 | Template text left in live demo records: settlement source named `"account holder of "`, `"the relevant electoral authority governing "`, and rule text reading "for  before their publication". | Shown verbatim on the Flagged page with the API URL. |
| F2 | Elections markets show open interest in the hundreds of millions against 1–2 cent bids with almost no resting size. | Tradability gate added; documented in Methodology. |
| F3 | Culture as a Kalshi category effectively does not exist (2 series). | Entertainment also queried; documented on the Culture page. |
| F4 | No published unauthenticated rate limits and no rate-limit headers on demo responses. | Collector enforces its own budget and reports skips. |
| F5 | The fee PDF's rounding prose ("fee + positionCost … centicent") and its published table disagree in the 4th decimal. The table is authoritative for pricing ($0.0001 is the tick size that matters), so the implementation matches the table. | Documented here and in the code. |
| F6 | Repository had no `COORDINATION.md` and other sessions were editing it concurrently; a merge conflict occurred. | Resolved without discarding the other board's content; both are kept in the file. |
| F7 | **Defect found and fixed (session `arena-8a0899e5`, 2026-11-20).** `collector/engine.py` marked a NO-side position with the **YES mid** and compared the NO entry price to the **YES mid** in `exit_signals()`. Because `obs.mid` is the YES mid and a NO position's value is `1 − mid`, a NO position entered at $0.30 with the YES mid at $0.75 (a **−$0.05** loss) was read as a **+$0.45** favourable swing and force-closed at a loss, and `equity` overstated the open value. Reproduced before the fix (`equity $10,290.19` vs the correct `$9,956.86`; exit decision `+$0.45 favourable swing — take profit` on a losing trade). | Fixed in `collector/engine.py`: `mark()` now stores the **held-side** value in `current_price`, and `exit_signals()` computes the swing as `(YES mid for YES, 1 − YES mid for NO) − entry_price`. Regression tests added to `tests/test_engine.py::TestExits` (hold on a real NO loss, take profit on a real NO gain, equity uses the held-side value). All 45 unit tests pass. |

## G. Not verified / not implemented

| # | Item | Why |
| - | ---- | --- |
| G1 | Demo-account balance, fills, positions | Requires API credentials the repo does not have. |
| G2 | Placing real demo orders | Same. Adapter exists and is unit-tested against a mock only. |
| G3 | WebSocket streaming in the running site | The handshake requires the same signed headers as REST. Polling is used instead; the endpoint and channels are documented and linked. |
| G4 | Attribution of a price move to a specific news article | **Still not claimed.** Since session `arena-93e9da14` the desk attaches *candidate* headlines to a swing (title + link + publish time, plus an explicit state when none was found or the lookup failed), because the brief asks for links near a jump. No official source maps an article to a Kalshi price move, so causation is never asserted — see §H2h. |
| G5 | A complete census of every Kalshi market | Each run tracks a bounded, ranked slice (top markets per topic) and reports the counts it read. |

---

## H. Session `arena-93e9da14` — defect verification (2026-11-20, UTC)

Every row below was checked by opening the listed URL in this session. "Live"
means the demo API response was read, not the documentation's description of it.

### H1. The defects, as published

| # | Observation | Evidence | Result |
| - | ----------- | -------- | ------ |
| H1a | Topic pages published **"Resolved captured 0"** for every topic | <https://wingbangboozle1-lang.github.io/Trade2/categories/gas-prices.html> fetched 2026-11-20T19:0xZ: "Resolved captured **0.00** YES/NO logged" | **Confirmed on the live site.** |
| H1b | The resolution store held 2,000 settled markets that could not be attributed to any topic | `data/resolutions.json` at commit `1bc32b7`: 2,000 rows, `series_ticker: null` on **all** of them | **Confirmed.** All 2,000 were demo `KXQUICKSETTLE` / weather series — none in scope. |
| H1c | The model chat could never fill | `data/live.json` at `1bc32b7`: 29 alerts, **1** signal, `high_roi_alerts: []`; server gate `score >= 0.10`, browser gate `net_roi >= 0.05` | **Confirmed.** The two feeds required a swing *and* a same-run signal on the same ticker. |
| H1d | Counters rendered as decimals ("Series in scope **162.00**") | same fetch of the live gas-prices page | **Confirmed** (independently fixed by session `997c9c83` as `cnt()`; this session's duplicate helper was dropped in favour of theirs). |

### H2. Official-source checks behind each fix

| # | Claim used by the code | Source | Result |
| - | ---------------------- | ------ | ------ |
| H2a | A market record from `GET /markets` has **no** `series_ticker` field (only `ticker` and `event_ticker`) | <https://docs.kalshi.com/api-reference/market/get-markets> response schema, read 2026-11-20 | **Verified.** The published field list contains `ticker`, `event_ticker`, … `exchange_index` and no series field. |
| H2b | Same conclusion from the live payload | `https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=2&status=settled` fetched 2026-11-20 | **Verified.** Returned keys contain `event_ticker` and `ticker`, no `series_ticker`; `status` reads `finalized`, `result` reads `yes`/`no`. |
| H2c | A market ticker is `SERIES-EVENT-MARKET`, so the series is the prefix before the first `-` | live: `https://external-api.demo.kalshi.co/trade-api/v2/events?series_ticker=KXAAAGASM&status=open&with_nested_markets=true&limit=1` → market `KXAAAGASM-26NOV30-2.50` under event `KXAAAGASM-26NOV30`, and `…/markets?tickers=…` response above | **Verified** by string inspection of real tickers; implemented as `alerts.series_from_ticker()` (a split, not a lookup table). |
| H2d | `GET /markets` accepts a comma-separated `tickers` filter, and `status=settled` may be combined with `series_ticker` | <https://docs.kalshi.com/api-reference/market/get-markets> query parameters: `tickers` — "Comma-separated list of market tickers to retrieve"; `series_ticker` — "Filter by series ticker"; `min_settled_ts` also documented | **Verified** in the docs **and** live: `…/markets?tickers=KXAAAGASW-26NOV16-4.2000,KXAAAGASW-26NOV16-4.1800` returned both closed markets with `result: "no"`, `settlement_ts`, `settlement_value_dollars: "0.0000"`, `status: "finalized"`. |
| H2e | Settlement semantics: a YES outcome pays $1 per YES contract, a NO outcome pays $1 per NO contract | <https://docs.kalshi.com/getting_started/market_settlement> | **Verified** (unchanged from §A; the resolution table shows `result` and `settlement_value_dollars` exactly as returned). |
| H2f | `events` objects carry `series_ticker`, so tracked markets are attributed to a series without parsing | live `GET /events?series_ticker=KXAAAGASM&with_nested_markets=true` response above | **Verified**; the collector copies `event.series_ticker` onto each nested market. |
| H2g | Model gate value is a project rule, not a Kalshi field | `collector/alerts.py` `MODEL_SCORE_GATE = 0.10`, published in the snapshot as `model_gate` and documented on <https://wingbangboozle1-lang.github.io/Trade2/methodology.html> | **Verified** as internally consistent: one constant, read by the collector and the browser. No profit claim is made. |
| H2h | Candidate headlines are not an official mapping | Google News RSS is a public search feed; no Kalshi page maps articles to price moves | **Not verified as causation, by design.** Rows are labelled "candidate catalyst — timing only"; a failed lookup is published as `unavailable`, never as "nothing was found". |
| H2i | Fee arithmetic used by the model (0.07 · C · P · (1−P), rounded up to the cent) | <https://kalshi.com/docs/kalshi-fee-schedule.pdf>, all 42 published rows asserted in `tests/test_engine.py` | **Unchanged and still passing** (87 tests, 1 skipped for the optional `cryptography` dependency). |

### H2j. End-to-end run on GitHub Actions (real demo traffic)

The sandbox this repo is edited in cannot open a socket to Kalshi (only the
documented fetcher can), so the pipeline's live behaviour is verified from a
workflow run that prints its own summary and commits its snapshot:

| Step | Evidence |
| ------ | -------- |
| Run | `.github/workflows/kalshi-dashboard.yml` on `arena/93e9da14-trade2` — <https://github.com/wingbangboozle1-lang/Trade2/actions/runs/44800744776> |
| Result | see the table appended below after the run completes (event counts, resolutions captured per topic, model shortlist size, headline lookup states) |

Until that table is filled, the fixes are verified by (a) the official-source
checks above, (b) 87 unit tests including new regression tests for every
behaviour changed here, and (c) `tools/deskcheck.mjs`, which renders the desk in
jsdom against a fixture and fails if either chat does not populate.
