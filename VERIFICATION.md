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
| G4 | Attribution of a price move to a specific news article | Deliberately not attempted: no official source maps articles to moves. |
| G5 | A complete census of every Kalshi market | Each run tracks a bounded, ranked slice (top markets per topic) and reports the counts it read. |

---

## H. Verification pass — session `arena-dd1da6b5` (2026-11-20)

Every row below was re-checked by opening the URL in the "Source" column and
reading the response. Nothing is inferred.

### H1. Published table rows re-checked against the official demo API

| # | Published on the site | Source opened | Result |
| - | --------------------- | ------------- | ------ |
| H1.1 | `KXPRESNOMD-28-RW` YES bid `$0.0310`, YES ask `$0.0330`, open interest `189,529,515.91` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW> | **Verified.** `yes_bid_dollars` = `0.0310`, `yes_ask_dollars` = `0.0330`, `open_interest_fp` = `189529515.91`, `notional_value_dollars` = `1.0000`. The site's implied ask (`1.00 − best NO bid` = `1.00 − 0.9670`) equals the official `yes_ask_dollars`. |
| H1.2 | `KXPRESNOMD-28-SAS` YES bid/ask shown as UNVERIFIED | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-SAS> | **Verified as UNVERIFIED.** The official record carries `yes_bid_dollars` = `0.0000` and `yes_ask_dollars` = `1.0000` with `yes_bid_size_fp` = `0.00` and `yes_ask_size_fp` = `0.00` — i.e. no resting size on either side, so there is no quote. The site leaves the value blank and flags it rather than printing a $0.00 bid. |
| H1.3 | `KXAAAGASM-26NOV30-3.60` YES bid `$0.0500`, YES ask `$0.0600`, bid depth `13,100.54` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.60> | **Verified.** `yes_bid_dollars` = `0.0500` (`yes_bid_size_fp` = `3338.33`), `yes_ask_dollars` = `0.0600` (`yes_ask_size_fp` = `2779.58`), `no_bid_dollars` = `0.9400` so the implied YES ask `1.00 − 0.9400` = `0.0600` matches, `open_interest_fp` = `6282.92`, `volume_fp` = `7352.02`. |
| H1.4 | `KXPRESNOMD-28-AKLO` YES bid `$0.0020`, YES ask `$0.0030` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-AKLO> and <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-AKLO/orderbook> | **Verified.** Market record: `yes_bid_dollars` = `0.0020` (`yes_bid_size_fp` = `83333.33`), `yes_ask_dollars` = `0.0030` (`yes_ask_size_fp` = `55554.03`), `open_interest_fp` = `100653948.08`. Order book: best YES bid `0.0020` × `83333.33`, best NO bid `0.9970`, so the implied YES ask is `0.0030`. |

### H2. The demo feed prints alternating trades on a book that never moves

This is the finding that changed how the model is built, so it is recorded in
full with the responses that show it.

| # | Claim | Source opened | Result |
| - | ----- | ------------- | ------ |
| H2.1 | On `KXPRESNOMD-28-AKLO` the traded price alternates between $0.8030 and $0.0030 every minute | <https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-AKLO/candlesticks?start_ts=1795190000&end_ts=1795200500&period_interval=1> | **Verified.** `price.close_dollars` runs 0.8030, 0.0030, 0.8030, 0.0030, 0.8030 … across consecutive one-minute candles. |
| H2.2 | The quoted book on that market does not move at all | same candlestick response | **Verified.** In every one-minute candle `yes_bid.close_dollars` = `0.0020` and `yes_ask.close_dollars` = `0.0030`. The live order book (H1.4) agrees: bid `0.0020`, NO bid `0.9970`. |
| H2.3 | A $0.10 swing measured against the traded price can therefore be a print, not a market move | H2.1 + H2.2 combined | **Verified.** The alert stream compares a traded price with a book mid. On this market the two differ by $0.80 while the market has not moved at all. |
| H2.4 | The model therefore refuses to price a move the book did not confirm | `collector/shortlist.py`, `tests/test_shortlist.py` | **Verified.** Gate 6 of the published model. On the 2026-11-20T18:41:08Z snapshot the model rejected all three alerted tickers with the reason "the book has not moved since the previous snapshot", and the rejection is published on the Flagged for Review page. |
| H2.5 | A market whose book *did* move by $0.10 is priced from the book only | `tests/test_shortlist.py::TestBuild::test_build_prices_a_book_move_and_rejects_a_print_only_move` | **Verified.** A book mid moving 0.50 → 0.30 produces fair value 0.40 and a YES edge of $0.09 at a $0.31 ask. |

### H3. Model, fee and news checks

| # | Claim | Source | Result |
| - | ----- | ------ | ------ |
| H3.1 | Kalshi's published taker fee is `0.07 × C × P × (1 − P)` | <https://kalshi.com/docs/kalshi-fee-schedule.pdf> | **Verified.** All 42 published table rows are asserted by `tests/test_engine.py`. The shortlist uses the same function, so its net edge is the same arithmetic. |
| H3.2 | The order book returns bids only, ascending, best bid last | <https://docs.kalshi.com/getting_started/orderbook_responses> | **Verified.** The live AKLO book confirms it: `yes_dollars` = `[["0.0010", …], ["0.0020", …]]`, so the best bid is the last element (`0.0020`). |
| H3.3 | Candlesticks accept only `period_interval` 1, 60 or 1440 | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks> | **Verified.** Enforced in `collector/kalshi_api.py` and used by the verification tool with `period_interval=1`. |
| H3.4 | Candidate headlines can be fetched for a swing | <https://news.google.com/rss/search?q=Amy+Klobuchar+presidential+nominee&hl=en-US&gl=US&ceid=US:en> | **Verified.** The feed returns items with `title`, `link`, `source` and `pubDate`. Headlines are labelled *candidates* on the site because temporal proximity is not causation, and a headline is never presented as the confirmed cause of a move. |
| H3.5 | A headline is matched to a swing by keyword and publish time only | `collector/news.py` | **Verified** as described. No official source maps an article to a Kalshi price move, so no stronger claim is made. |

### H4. Automated re-check

| # | Item | Result |
| - | ---- | ------ |
| H4.1 | `tools/verify_snapshot.py` re-opens every published market and series response and compares each field with what the site shows | **Verified** by the run recorded on the Methodology page. Each comparison is classified `match`, `drift` (inside the stated tolerance), `mismatch` or `unverified` (the response could not be read), and the exact URL is recorded for each row. |
| H4.2 | Integer counters are printed as integers | **Verified.** `Markets tracked 750`, `Open positions 1`, `Resolved tracked 2,000` — previously `750.00`, `1.00`, `2000.00`. |
| H4.3 | The site has no broken internal links and every page still renders | **Verified.** `tools/linkcheck.py`: 45 pages, 525 internal links, 0 errors. |

### H5. Corrections made to earlier sections of this log

| # | Earlier text | Now |
| - | ------------ | --- |
| H5.1 | G4 said attribution of a move to a news article was "deliberately not attempted". | Still true of *attribution*. What the site now does is attach **candidate** headlines found by keyword and publish time, labelled as candidates, alongside the official Kalshi market link. |
| H5.2 | F2 described large open interest against 1–2 cent bids as an irregularity. | Still true, and now joined by H2.1–H2.3: on some demo markets the *traded* price alternates while the book is flat, so a price-based swing on those markets is an artefact of the feed rather than a market move. |
