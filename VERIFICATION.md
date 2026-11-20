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
| G4 | Attribution of a price move to a specific news article | Deliberately not attempted: no official source maps articles to moves. The dashboard links to the Kalshi event page (which carries Kalshi's own news feed for that event) and to a news search for the event title, and never names an article as the cause. |
| G5 | A complete census of every Kalshi market | Each run tracks a bounded, ranked slice (top markets per topic) and reports the counts it read. |

---

## H. Session `arena-fb6cb424` — root-site verification (2026-11-20)

Scope of this pass: the root site only (`site_build/`, `assets/desk.js`,
`assets/styles.css`, and the root pages they generate). Every claim below was
checked against the live demo API or an official Kalshi page during this
session; the URL that was opened is given.

| # | Claim | Source opened | Result |
| - | ----- | ------------- | ------ |
| H1 | `GET /markets` publishes `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars` and `no_ask_dollars` as first-class fields | <https://docs.kalshi.com/api-reference/market/get-markets> and the live response for `KXPRESNOMD-28-SAS` | **Verified.** The schema lists all four; the live market object returns all four. |
| H2 | A market with no resting size reports `yes_bid_dollars "0.0000"` and `yes_ask_dollars "1.0000"` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-SAS> | **Verified.** The response carries exactly those values with `yes_bid_size_fp "0.00"` and `yes_ask_size_fp "0.00"`. The site therefore leaves those cells blank and flagged rather than printing a price that cannot be filled; the rule is published on the Flagged page. |
| H3 | Market objects returned by `GET /markets` carry **no** `series_ticker` field | live responses for `KXPRESNOMD-28-SAS`, `KXNATGAS15M-26NOV200900-00`, `KXXRP15M-26NOV200900-00` | **Verified.** None of the three contains the field. This is why the collector's per-topic resolution buckets were empty; the site recovers the series from the market ticker prefix, which is Kalshi's own naming convention. Published as a standing limitation on the Flagged page. |
| H4 | Published resolution for `KXNATGAS15M-26NOV200900-00` is YES with a $1.0000 settlement value, settled at `2026-11-20T14:00:24.608234Z` | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXNATGAS15M-26NOV200900-00> | **Verified.** Live response: `"result":"yes"`, `"settlement_value_dollars":"1.0000"`, `"settlement_ts":"2026-11-20T14:00:24.608234Z"`, `"status":"finalized"`. Identical to the row published on `resolutions.html`. |
| H5 | Published resolution for `KXXRP15M-26NOV200900-00` is YES with a $1.0000 settlement value | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXXRP15M-26NOV200900-00> | **Verified.** Live response: `"result":"yes"`, `"settlement_value_dollars":"1.0000"`, `"status":"finalized"`. Identical to the published row. |
| H6 | `https://kalshi.com/markets/<series>/<event-ticker>` opens the Kalshi event page, which carries Kalshi's own live news feed for that event with named sources | <https://kalshi.com/markets/KXPRESNOMD/KXPRESNOMD-28> | **Verified.** The page resolves to "2028 Democratic presidential nominee", shows the live order ticket and an "AI Digest" news block listing three linked sources (Emerson Polling, The Hill, The Grio). Every ≥ $0.10 row now links to it. |
| H7 | `https://kalshi.com/markets/<series>/<market-ticker>` resolves to that market's event page | <https://kalshi.com/markets/KXPRESNOMD/KXPRESNOMD-28-RW> | **Verified.** Redirects to `…/kxpresnomd/democratic-primary-winner/kxpresnomd-28`. The existing per-row market link is therefore valid. |
| H8 | The Google News RSS search URL used for the "News search" link returns a valid feed for the event title | <https://news.google.com/rss/search?q=Hunter+Biden+elections+Kalshi&hl=en-US&gl=US&ceid=US:en> | **Verified.** Returns a well-formed RSS 2.0 feed whose items include "Could Hunter Biden Run for President? Prediction Market Sparks Online Frenzy" (Latin Times) and "Hunter Biden odds: Will he run for President?" (Kalshi News). The link is a *search*, never an assertion of cause. |
| H9 | `GET /markets?status=settled` returns markets whose `result` is `yes` or `no` | live responses in H4 and H5, plus the 2,000-record settlement store | **Verified.** The store holds 1,250 `no` and 750 `yes`; 339 of them fall inside the five tracked topics (270 gas prices, 69 crypto) and are published with their result chip. |
| H10 | Whole-number counts were being printed with a decimal tail (`750.00`) | the site's own generated markup | **Verified** and **fixed.** A dedicated integer formatter now renders counts without decimals; fractional contract counts and volume keep theirs. |
| H11 | Every root page renders with JavaScript disabled, with no thrown error and no `undefined` / `NaN` / `[object Object]` in the rendered text | `node test/root_render.mjs` (this session) | **Verified.** All 13 root pages pass, including the three new ones. The live desk's market table and both chats are now pre-rendered server-side, so they are populated before any script runs. |
| H12 | No internal link is broken anywhere on the site | `python3 tools/linkcheck.py` | **Verified.** 48 pages, 609 internal links, 0 errors. |
| H13 | The root site's executive summary described a browser-side collector that the root pages do not load | `summary.html` and the page list (`index.html` loads `assets/nav.js` and `assets/desk.js` only) | **Irregularity found and fixed.** The "At a glance" text and the next-steps list were rewritten to describe the architecture that actually runs: scheduled collector → pre-rendered pages → JS polling on top, with a server-side paper ledger rather than browser local storage. |
| H14 | `review.html` did not report repeated alerts for one market | the current snapshot (29 alerts over 3 tickers) | **Irregularity found and flagged.** A literal counting rule now raises "Same swing reported repeatedly" when one ticker appears three or more times in the alert buffer, and the finding is published on the Flagged page with the API URL. The underlying alert rule is owned by another session and is not changed here. |
