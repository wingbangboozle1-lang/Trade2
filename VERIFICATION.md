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

---

# Session D verification log — `arena-1011a94f` (2026-11-20)

Scope: line-by-line audit of the snapshot published at
`https://wingbangboozle1-lang.github.io/Trade2/` (commit `1bc32b7`,
snapshot `data/live.json` generated `2026-11-20T18:41:08Z`) against the official
demo Trade API. Every row below states what was checked, what was found, and the
exact URL that shows it. Nothing in this section is inferred.

Environment note: this sandbox's egress allowlist still blocks `*.kalshi.co`
(`curl` → `SSL_ERROR_SYSCALL`, HTTP 000, re-tested 2026-11-20T19:0xZ). Live reads
were made through the platform fetch channel against the same official demo
host, which returns raw JSON; the URL column is the URL that was read.

## D1 — Endpoint and host claims

| # | Claim on the site | Verified against | Result |
| - | - | - | - |
| D1-1 | Recommended demo REST root is `https://external-api.demo.kalshi.co/trade-api/v2`, alternate `https://demo-api.kalshi.co/trade-api/v2` | https://docs.kalshi.com/getting_started/demo_env and https://docs.kalshi.com/getting_started/api_environments | matches, word for word |
| D1-2 | Recommended demo WebSocket is `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`, alternate `wss://demo-api.kalshi.co/trade-api/ws/v2` | same two pages | matches |
| D1-3 | The demo exchange is live and trading | https://external-api.demo.kalshi.co/trade-api/v2/exchange/status | `{"exchange_active":true,"trading_active":true,...}` |
| D1-4 | Demo prices "may not be reflective of those in real markets" | https://docs.kalshi.com/getting_started/demo_env | sentence is present on the official page; the site says the same |

## D2 — Order book maths

| # | Claim | Verified against | Result |
| - | - | - | - |
| D2-1 | Arrays are ascending; best bid is the last element | https://docs.kalshi.com/getting_started/orderbook_responses | matches |
| D2-2 | Implied YES ask = 1.00 − best NO bid | same page (worked example 0.44 − 0.42 = 0.02) | matches; `collector/kalshi_api.implied_yes_ask` implements it |
| D2-3 | Order books are bids only | same page | matches |
| D2-4 | An empty book and an unknown ticker both return 200 with empty arrays | same page | matches; `collector/kalshi_api.orderbooks` documents it |

## D3 — Candlesticks and the swing reference

| # | Claim | Verified against | Result |
| - | - | - | - |
| D3-1 | `period_interval` is **minutes**, valid values 1, 60, 1440 | https://docs.kalshi.com/api-reference/market/get-market-candlesticks | matches |
| D3-2 | A candlestick carries its own `yes_bid` / `yes_ask` / `price` OHLC for that period | same page (200-response schema) + live read | matches |
| D3-3 | The site's swing reference is the most recent completed 1-minute candle | implementation `collector.collector.candle_reference` | matches, and now integrity-checked (D4) |

### D3-4 — IRREGULARITY: a candlestick print that sits outside its own quote

Read: `https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-AKLO/candlesticks?start_ts=1795199400&end_ts=1795200300&period_interval=1`

| `end_period_ts` | `price.close_dollars` | `yes_bid.close_dollars` | `yes_ask.close_dollars` |
| - | - | - | - |
| 1795199940 | 0.0030 | 0.0000 | 0.8030 |
| 1795200000 | **0.8030** | **0.0020** | **0.0030** |
| 1795200060 | 0.0030 | 0.0000 | 0.8030 |
| 1795200120 | 0.0030 | 0.0020 | 0.0030 |
| 1795200300 | 0.8030 | 0.0020 | 0.0030 |

The minute ending 1795200000 prints a close of **0.8030** while the same minute
quotes **0.0020 bid / 0.0030 ask**. A price cannot be 0.8030 when the market is
0.0020/0.0030; this is an unpaired print, and it alternates every other minute.
The collector used that 0.8030 as its swing baseline and published
`▼ $0.8005  $0.8030 → $0.0025` at 15:03, 15:43, 16:51, 17:44 and 18:41 on
2026-11-20. **Handling:** a candle is now only usable as a reference when its
print lies inside its own quoted bid/ask *and* that quote is two-sided and no
wider than `MAX_QUOTE_SPREAD` (0.50). Verifying ticker:
`https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-AKLO`
(`yes_bid_dollars 0.0020`, `yes_ask_dollars 0.0030`, `last_price_dollars 0.0030`).

### D3-5 — IRREGULARITY: alerts produced from one-sided quotes

Read: `https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID`
and `…/KXPRESNOMD-28-JP`.

| Ticker | Published alert | Quote recorded with it | Width |
| - | - | - | - |
| KXPRESNOMD-28-HBID | `$0.8110 → $0.4065` (▼ $0.4045) | bid 0.0020 / ask 0.8110 | 0.8090 |
| KXPRESNOMD-28-JP | `$0.9440 → $0.4770` (▼ $0.4670) | bid 0.0100 / ask 0.9440 | 0.9340 |

For HBID the live market record confirms `yes_bid_dollars 0.0020`,
`yes_ask_dollars 0.8110`, `last_price_dollars 0.8110`; for JP `yes_bid_dollars
0.0100`, `yes_ask_dollars 0.9440`, `last_price_dollars 0.9440`. The "mid" of such
a book (0.4065, 0.4770) is not a price anyone can transact at, and the resulting
`$0.40`/`$0.47` "moves" are artefacts of averaging a 0.2-cent bid with an
80-cent ask. **Handling:** both ends of a move must now be verifiable market
prices. The three stored AKLO rows (which carry no baseline quote at all) are
held back and listed on `review.html` with their API links; see D6.

## D4 — Resolutions

### D4-1 — IRREGULARITY: no settlement ever reached a topic page

Read: `https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled&limit=3`

The settled market objects returned by the official API include
`event_ticker`, `result`, `settlement_value_dollars`, `settlement_ts`,
`status` — and **no `series_ticker` field at all**. The collector keyed its
topic mapping on `rec["series_ticker"]`, so the lookup always missed. Evidence
in the published snapshot (`data/live.json`, commit `1bc32b7`):
`resolutions` was `{gas-prices: 0, elections: 0, culture: 0, crypto: 0, golf: 0}`
while `resolutions_count` was `2000`, and all five topic pages rendered
"No resolved market from this topic has been captured yet."
**Handling:** attribution now uses, in order, (a) an explicit `topic_hint`
recorded when the settlement was read from
`GET /events?status=settled&with_nested_markets=true`, whose event object *does*
carry `series_ticker`, (b) the recorded series ticker, (c) the ticker prefix
`SERIES-EVENT[-STRIKE]`. Unattributable settlements are counted and reported,
never guessed.

### D4-2 — Settlements stored are mostly out-of-scope series

Read: `data/resolutions.json` (2,000 entries) grouped by series prefix:
`KXESOCCERGAME` 510, `KXQUICKSETTLE` 110, `KXCRYPTOLEAD15M` 85,
`KXEBASKETBALLGAME` 72, `KXLIGAPROMATCH` 56, … Verified as real demo series:
`https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXNATGAS15M&status=settled&limit=1`
returns a genuine settled energy market (`"title":"Natural Gas price up in next
15 mins?"`, `result":"yes"`, `settlement_value_dollars":"1.0000"`), i.e. these
are legitimate demo contracts outside the five tracked topics. **Handling:** they
are excluded from topic pages and their count is published: the overview now
reads "N of 2,000 stored settlements belong to a tracked topic", with the
remainder named on `review.html`.

## D5 — Topic matching (Culture)

| # | Claim | Verified against | Result |
| - | - | - | - |
| D5-1 | `GET /series?category=Culture` returns very few series | https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture&include_volume=true | returns **2** series (`KXXBANNEDGROK`, `KXXBANNEDMURRAYHILLGUY1`) |
| D5-2 | Culture content is filed under Entertainment / Mentions, which is why the topic page shows content with `category=Culture` nearly empty | same read + `data/series_cache.json` (789 culture series resolved from Entertainment/Mentions) | consistent; the page's "topic category is effectively empty" flag is accurate |

## D6 — Flagged-for-review rows generated from this snapshot

| Row | Source link that proves it |
| - | - |
| 3 × swing held back by the integrity gate (KXPRESNOMD-28-AKLO) | `…/markets/KXPRESNOMD-28-AKLO` |
| 1,920 of 2,000 stored settlements outside the five topics | `…/markets?status=settled` |
| Series `KXGOLFCAT` has the placeholder title `"a"` | https://external-api.demo.kalshi.co/trade-api/v2/series/KXGOLFCAT (confirmed: `"title":"a"`) |
| Culture category effectively empty (2 series) | `…/series?category=Culture` |
| Large open interest on an empty book (elections, crypto) | per-market `…/markets/{ticker}/orderbook` |

## D7 — What this session did not verify

* Authenticated demo endpoints (`/portfolio/*`, order entry, WebSocket handshake):
  no key pair exists in the repository and none was provided. Unchanged from
  sessions B/C; still published on `review.html`.
* Anything requiring the sandbox to reach `kalshi.com` or `docs.kalshi.com`
  directly over TLS: blocked, as above. Reads used the platform fetch channel.
