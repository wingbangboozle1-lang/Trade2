# Verification — session `arena-d6a0282d` (2026-11-21)

Independent, line-by-line re-verification of the published root site and the
`docs/` snapshot against the **live Kalshi demo API**, plus the record of what
was checked to produce the changes in Board K (`COORDINATION.md`).

Everything below was read from a live response or an official page during this
session. Where this session was wrong, the wrongness is recorded too (§5).

---

## 1. Method, and what could and could not be reached

| Fact | Evidence |
| - | - |
| The sandbox **shell** has no route to Kalshi: `curl https://demo-api.kalshi.co/trade-api/v2/exchange/status` fails with `OpenSSL SSL_connect: SSL_ERROR_SYSCALL` (egress allowlist is github.com, codeload, registry.npmjs.org, pypi.org, files.pythonhosted.org). | Command run at 06:42Z this session; reproduced by every prior session (I3, E2, and Board J's correction of them). |
| The platform **document fetcher** does reach both the demo API and `docs.kalshi.com`, and returns the raw JSON body. So live demo verification is possible from this sandbox without deferring to CI. | Nine fetches listed in §3, each with the exact URL. Confirms and extends Board J's note ("the platform fetcher does — 10 live fetches succeeded"). |
| The demo exchange is up and trading: `exchange_active: true`, `trading_active: true`, `intra_exchange_transfers_active: true`, four indexes (0 "Default", 1 "Demo shard 1", 2 "Demo shard 2", 3 with an empty `description`), each with `exchange_active: true` and `trading_active: true`. | https://demo-api.kalshi.co/trade-api/v2/exchange/status (06:44Z) — matches `docs/data/run_meta.json → exchange` field for field, including `indexes: 4`. The per-index `intra_exchange_transfers_active` is dropped by `collector/runner.py::summarize_exchange_status`; noted, not changed (the top-level flag is published and is the one the site quotes). |
| Field-by-field shape of a market object as published today: `yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`, `previous_price_dollars`, `open_interest_fp`, `volume_fp`, `volume_24h_fp`, `notional_value_dollars`, `status`, `result`, `settlement_value_dollars`, `settlement_ts`, `expected_expiration_time`, `price_level_structure`, `rules_primary`. No `series_ticker`, no `fee_type`, no `expected_expiration_ts`. | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70 (06:52Z) and …/markets/KXPGATOUR-THRC26-MTHO (06:56Z). Confirms the collector's documented field choices (H3, R-E1-01/02) against today's response, not just 2026-11-20's. |

---

## 2. Rows checked against the live API

Verdict key: **EXACT** = published value equals the live value; **DRIFT** = the
two differ and the difference is explained by the snapshot being older than the
read (the site publishes its age for exactly this); **WRONG** = the published
value does not follow from the source it cites.

| # | Published value (file → row) | Live response | Verdict |
| - | - | - | - |
| 1 | `index.html` gas row `KXAAAGASM-26NOV30-4.70`: OI `58,062.52`, OI value `$58,062.52`, Volume `58,071.52` | `open_interest_fp "58062.52"`, `notional_value_dollars "1.0000"`, `volume_fp "58071.52"` | **EXACT** — including the arithmetic `58062.52 × 1.0000` and the reason the two columns look identical (see K-F2) |
| 2 | Same row: YES bid `UNVERIFIED`, YES ask `UNVERIFIED` | `yes_bid_dollars "0.0000"`, `yes_ask_dollars "1.0000"` | **WRONG (under-report)** — the cited response *does* return both numbers. Fixed by K2: the cell now shows `$0.0000` / `$1.0000` with an *empty book · nothing resting* note |
| 3 | Same row: no Last price at all | `last_price_dollars "0.0200"` | **WRONG (omission)** — fixed: every table now carries a **Last** column, and it renders `$0.0200` from `observation.last_price` even for rows written before the field was lifted |
| 4 | `docs/data/alerts.json` golf row `KXPGATOUR-THRC26-MTHO`: `from 0.17 → to 0.39`, `delta 0.22`, `t 1795241520`, `t_iso 2026-11-21T06:12:00Z`, `window "seconds"` | Candlesticks at `period_interval=1`: `end_period_ts 1795241460 → price.close_dollars "0.1700"`; `end_period_ts 1795241520 → price.close_dollars "0.3900"`; next bar `1795241580 → "0.1700"` | **EXACT** on all four numbers — https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/markets/KXPGATOUR-THRC26-MTHO/candlesticks?start_ts=1795241400&end_ts=1795241640&period_interval=1 |
| 5 | Why the root site reported **0** swings while that alert existed | The same candle response: `yes_bid.close_dollars` is `0.1600` on every bar in the window and `yes_ask.close_dollars` goes `0.1700 → 0.1700`. Midpoint basis: `0.165 → 0.165`, i.e. **$0.00**, and the current book (row 6) is `0.16/0.17` | **EXACT / consistent** — the two engines were not in conflict about a fact; they measure different things. This is the whole justification for K1 |
| 6 | `docs/data/markets.json` row `KXPGATOUR-THRC26-MTHO`: `last_price 0.17`, `open_interest_fp 58179.95`, `price_level_structure "tapered_deci_cent"`, `expected_expiration "2026-11-22T00:00:00Z"`, `yes_bid 0`, `yes_ask 0.17` | `last_price_dollars "0.1700"`, `open_interest_fp "58179.95"`, `price_level_structure "tapered_deci_cent"`, `expected_expiration_time "2026-11-22T00:00:00Z"`, `yes_bid_dollars "0.1600"`, `yes_ask_dollars "0.1700"` | **EXACT** except `yes_bid` and `volume_fp`: published `0` vs live `0.1600`, published `90917.08` vs live `91170.46` → **DRIFT** (snapshot 06:24Z vs a read ~30 min later; the market traded 253 contracts in between, which is also why its own `updated_time` is older than the trade flow suggests) |
| 7 | `docs/data/markets.json` same row: `notional_usd 2243.47` | not an API field: `volume_24h_fp 13196.86 × last_price 0.17 = 2243.4662 → 2243.47` | **EXACT to its own definition** — a derived product, and the docs table header called it `$ volume`, which reads like an official figure. Fixed: header now `$ volume (derived)` with the formula and both inputs named in its tooltip (this is what `config/flags.json` F-12 already claimed the site does) |
| 8 | `docs/data/markets.json` same row: `status "open"` | the response says `"status": "active"` | **WRONG as published** — a translated word at a URL that shows a different word. Fixed: `api_status` now carries the verbatim value in both the collector (`collector/runner.py`) and the browser path (`docs/assets/app.js`). Re-verified at 07:09:55Z+ with `GET /markets?status=open&limit=1`, whose single market also answers `"status": "active"` |
| 9 | `data/resolutions.json` `KXAAAGASCDAK-26NOV20-LD`: `result "yes"`, `settlement_ts "2026-11-20T10:35:14.609488Z"`, `settlement_value_dollars "1.0000"`, `status "finalized"` | identical, character for character | **EXACT** — https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASCDAK-26NOV20-LD |
| 10 | `data/resolutions.json` `KXAAAGASCDAK-26NOV20-LI`: `result "no"`, `settlement_value_dollars "0.0000"`, same `settlement_ts` | identical | **EXACT** — the NO side of the same event pays $0.0000, which is the settlement rule the site states: https://docs.kalshi.com/getting_started/market_settlement |
| 11 | `data/live.json` liquidity ladder `KXAAAGASW-26NOV23-3.6400`: YES bids `0.02 × 8,333.33`, `0.01 × 16,666.66`; NO bid `0.97 × 4,144.59`; implied YES ask `0.03` | `yes_dollars [["0.0100","16666.66"],["0.0200","8333.33"]]`, `no_dollars [… ["0.9700","3901.62"]]` | **EXACT** on the YES side and on the ordering rule (ascending, best bid last, bids only → `1.00 − 0.97 = 0.03`); **DRIFT** on the NO size at 0.97 (4,144.59 → 3,901.62) — https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400/orderbook?depth=10 |
| 12 | `docs/data/orderbooks.json` same market at 06:24Z: NO level `0.97 × 4163.89` | the root snapshot for the same instant says `4144.59`; live says `3901.62` | **two collectors, same instant, three numbers** — the two reads are seconds apart and the level is genuinely moving. Not an error in either; it is why both files publish `fetched_at`. Reported so a reviewer does not read one as authoritative over the other |

---

## 3. Fetches performed (replayable)

All are `GET`, unauthenticated, public demo data. Times are stated only to the
precision the evidence supports: the session's claim commit is `8c2acb2` at
06:53Z, so anything before it is 06:4xZ; the last read is pinned to the minute
by its own response (that market's `created_time` is `2026-11-21T07:09:54Z`, so
the read is ≥ 07:09:55Z). Ordering is exact.

| When | URL |
| - | - |
| 06:4xZ | https://demo-api.kalshi.co/trade-api/v2/exchange/status |
| 06:5xZ | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70 |
| 06:5xZ | https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/markets/KXPGATOUR-THRC26-MTHO/candlesticks?start_ts=1795238665&end_ts=1795242265&period_interval=1 |
| 06:5xZ | https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/markets/KXPGATOUR-THRC26-MTHO/candlesticks?start_ts=1795241400&end_ts=1795241640&period_interval=1 |
| 06:5xZ | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-MTHO |
| 07:0xZ | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASCDAK-26NOV20-LD |
| 07:0xZ | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASCDAK-26NOV20-LI |
| 07:0xZ | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400/orderbook?depth=10 |
| 07:09:55Z or later | https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open&limit=1 |

The site itself was also read back through the same fetcher, as published
(https://wingbangboozle1-lang.github.io/Trade2/), and that is where rows 2 and 3
were observed: the gas row printed `UNVERIFIED` twice beside an `API ↗` link
that returns both quotes.

Official documentation pages read this session (the claims each one supports is
stated next to it):

| Page | What it settles |
| - | - |
| https://docs.kalshi.com/api-reference/market/get-markets | The `status` **filter** vocabulary and the mutually-exclusive timestamp filter table; the paging rule "when `event_ticker` or `tickers` is the only filter … every matching market is returned in one response"; and the warning that "responses are cached for a short time, so prices, sizes and `status` can lag the exchange by several seconds" — the documented reason rows 6 and 11 are DRIFT rather than WRONG, and the basis of the two new suggestions on `suggestions.html`. |
| https://docs.kalshi.com/getting_started/orderbook_responses | Bids only, ascending, best bid last; the YES ask is implied. This is the source cited by the *empty book* note K2 adds. |
| https://docs.kalshi.com/api-reference/market/get-market-candlesticks | `period_interval` minutes (1 / 60 / 1440) and the `price` / `yes_bid` / `yes_ask` blocks with `close_dollars` — everything the K1 feed reads. |
| https://docs.kalshi.com/getting_started/market_settlement | YES pays $1.0000 and NO pays $0.0000 to the YES holder, verified in rows 9 and 10 by two real settlements of one event. |

---

## 4. What this session changed as a result

| Change | Files | Pinned by |
| - | - | - |
| The all-events chat now carries the published candlestick-close moves, labelled, deduped against the live rows, dropped when stale / below threshold / untracked, each row linking both the market response and the candlestick series. The model shortlist is untouched. | `site_build/swingfeed.py` (new), `site_build/build.py`, `assets/desk.js` | `tests/test_swing_feed_d6a0282d.py` (20 cases) and `test/desk_render_dc732aa6.mjs` (fixture rows + the model-exclusion assertion) |
| Tables show the quote the market response carries, with an *empty book · nothing resting* note, and a new **Last** column; the OI columns are labelled with their formulas. The alert basis is still nulled for an empty book. | `collector/alerts.py`, `site_build/format.py`, `site_build/build.py`, `assets/desk.js` | `tests/test_quote_display_d6a0282d.py` (10 cases, including the guard-must-not-weaken case and the pre-field-row case) |
| `api_status` (verbatim) published beside the mapped `status`, in the collector and the browser path. | `collector/runner.py`, `docs/assets/app.js` | `tests/test_status_verbatim_d6a0282d.py` |
| Derived dollar column labelled as derived. | `docs/assets/app.js` | same file |
| Four new suggestions, each tied to a measurement rather than to taste. | `site_build/extras.py` → `suggestions.html` | rendered and link-checked |

Mutation-proven, in this sandbox, that the tests bite: deleting the
`swingfeed.attach` call from `main()` fails the wiring test; feeding the merged
list to the model loop fails the model-exclusion test; removing the dedupe fails
the duplicate test; removing the staleness guard fails the too-old test;
removing the `quote_bid` fallback fails the cell test. All five restored → green.

---

## 5. Checked and cleared (this session was wrong, twice)

1. **"Resolutions publish a blank settlement value."** A probe of
   `data/resolutions.json` using the key `settlement_value` returned `null` for
   328/328 rows and looked like a site-wide blank column. It is not: that file's
   key is `settlement_value_dollars` and it carries `"1.0000"` / `"0.0000"`,
   which is what `site_build/build.py:594` and `extras.py:323` render. The
   `settlement_value` key belongs to the *other* pipeline
   (`docs/data/resolutions.json`, written by `collector/runner.py:539`), where
   it is populated too. No defect; recorded because the wrong probe is exactly
   the kind of thing a review should be able to see.
2. **"The root site publishes a translated status."** It does not:
   `assets/live.json` carries the verbatim `"active"` (1,484 rows) and
   `"finalized"` (96). Only the `docs/` pipeline mapped it. Fixed where it was
   actually wrong (row 8), not everywhere it looked similar.

---

## 6. Still unverified or blocked after this session

| Item | State | Source / blocker |
| - | --- | - |
| Demo-account portfolio read and order placement | **Not done, still blocked.** No API key pair exists for this repository, so no balance, position or order was ever read or sent by any session. All fills on the site are simulated against real demo order books and are labelled as such. | https://docs.kalshi.com/getting_started/api_keys · F-08 / FL-01 |
| `kalshi-dashboard/data/resolved.json` publishes `{"resolved":[],"pending":[]}` | **Open, mechanism identified.** `scripts/collect.mjs:170` seeds its watch list from `state.meta`, which is only filled by markets seen in the *current* run; on a cold Actions cache the "track until resolved" table can never populate, however many runs happen. R-4f92-4 recorded the symptom. Out of scope for this session (`scripts/collect.mjs` is owned elsewhere) — logged as Board K finding K-F1. | https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled |
| `kalshi-dashboard` market rows: 1,333 of 1,577 have no `last_cents` | Legitimate blanks (no print in the demo market), published blank rather than filled. Not counted as errors; `tools/rowsource_check.py` lists them. | https://external-api.demo.kalshi.co/trade-api/v2/markets |
| Cause of a ≥ $0.10 move | The site links *candidate* headlines it fetched, and says so. No row on the site claims an article caused a price, and none can: the API has no cause field. F-10 stays open by design. | https://docs.kalshi.com/api-reference/market/get-market |
| Sub-second price history | Not available from a static page: the REST answers are cached (`cache-control: public, max-age=5`, measured) and the anonymous WebSocket handshake is refused (`401 Unauthorized`, measured in `docs/data/capabilities.json`). The chart labels its bar size instead. | https://docs.kalshi.com/websockets/websocket-connection |
