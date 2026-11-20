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

## F. Irregularities found (also published on the site)

| # | Finding | Handling |
| - | ------- | -------- |
| F1 | Template text left in live demo records: settlement source named `"account holder of "`, `"the relevant electoral authority governing "`, and rule text reading "for  before their publication". | Shown verbatim on the Flagged page with the API URL. |
| F2 | Elections markets show open interest in the hundreds of millions against 1–2 cent bids with almost no resting size. | Tradability gate added; documented in Methodology. |
| F3 | Culture as a Kalshi category effectively does not exist (2 series). | Entertainment also queried; documented on the Culture page. |
| F4 | No published unauthenticated rate limits and no rate-limit headers on demo responses. | Collector enforces its own budget and reports skips. |
| F5 | The fee PDF's rounding prose ("fee + positionCost … centicent") and its published table disagree in the 4th decimal. The table is authoritative for pricing ($0.0001 is the tick size that matters), so the implementation matches the table. | Documented here and in the code. |
| F6 | Repository had no `COORDINATION.md` and other sessions were editing it concurrently; a merge conflict occurred. | Resolved without discarding the other board's content; both are kept in the file. |

## G. Not verified / not implemented

| # | Item | Why |
| - | ---- | --- |
| G1 | Demo-account balance, fills, positions | Requires API credentials the repo does not have. |
| G2 | Placing real demo orders | Same. Adapter exists and is unit-tested against a mock only. |
| G3 | WebSocket streaming in the running site | The handshake requires the same signed headers as REST. Polling is used instead; the endpoint and channels are documented and linked. |
| G4 | Attribution of a price move to a specific news article | Deliberately not attempted: no official source maps articles to moves. |
| G5 | A complete census of every Kalshi market | Each run tracks a bounded, ranked slice (top markets per topic) and reports the counts it read. |
