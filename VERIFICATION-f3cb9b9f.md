# Verification log — session `arena-f3cb9b9f`

Every claim below was checked against an **official Kalshi source** during this
session (2026-11-21 06:40–07:10 UTC). The comparison is field by field: the value
the published site shows on the left, the value the live demo API returned on
the right. Where a value was not checked, no row is written — this file contains
only checks that actually ran.

Environment note: this sandbox's shell has no route to Kalshi, but the platform
page fetcher does. Every "live API" link below is a URL that was fetched and
whose exact response is quoted. (This matches session `arena-1e3b2594`'s
correction to finding I3 in `COORDINATION.md`.)

---

## A. Published market rows — 6 checked; quotes exact on all 6, one refusal verified

| # | Published on | Field | Site value | Live API value | Verdict | Source |
| - | - | - | - | - | - | - |
| A1 | `/` overview | `yes_bid` / `yes_ask` / `open_interest_fp` / `volume_fp` for `KXPRESNOMD-28-RW` | 0.0380 / 0.0390 / 189,529,515.91 / 414,933,042.49 | 0.0380 / 0.0390 / 189529515.91 / 414933166.11 | **quote + OI exact**; volume differs by 123.62 (0.00003%) — market kept trading between the snapshot and this check, and the site's number is what the API returned at snapshot time | [GET /markets/KXPRESNOMD-28-RW](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) |
| A2 | `/` overview | same fields for `KXPGATOUR-THRC26-TMOO` | $0.0030 / $0.0050 / OI $1,156,333.07 / vol 1,161,821.96 | 0.0030 / 0.0050 / 1156538.99 / 1162027.88 | quotes exact; OI and volume higher now (trading continued) | [GET /markets/KXPGATOUR-THRC26-TMOO](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO) |
| A3 | `/` overview | `KXBTCY-27JAN0100-B127500` quotes + OI | $0.0000 / $0.0100 / $39,647,687.73 | 0.0000 / 0.0100 / 39647719.80 | **quotes exact**; OI +32.07 | [GET /markets/KXBTCY-27JAN0100-B127500](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B127500) |
| A4 | `/` overview | `KXAAAGASW-26NOV23-3.6400` quotes + OI | $0.0200 / $0.0300 / 34,407.03 | 0.0200 / 0.0300 / 34608.61 | **quotes exact**; OI +201.58 | [GET /markets/KXAAAGASW-26NOV23-3.6400](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) |
| A5 | `/` overview | `KXPERFORMBONDSONG-35-COL` quotes + OI | $0.0100 / $1.0000 / 14,278.02 | 0.0100 / 1.0000 / 14278.02 | **exact** (a genuinely one-sided demo book: bid size 1.00 contract) | [GET /markets/KXPERFORMBONDSONG-35-COL](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPERFORMBONDSONG-35-COL) |
| A6 | `/` overview | `KXAAAGASM-26NOV30-3.50` quotes + OI | $0.4900 / $0.5000 / $5,321.29 | 0.4900 / 0.5000 / 5320.95 | **quotes exact**; OI +0.34 | [GET /markets/KXAAAGASM-26NOV30-3.50](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.50) |
| A7 | `/` overview | `KXAAAGASM-26NOV30-4.70` bid/ask shown as `UNVERIFIED` | UNVERIFIED / UNVERIFIED (not 0.50) | record 0.0000 / 1.0000; **order book empty** | **correct refusal** — the site declines to publish a price Kalshi did not quote | [GET /markets/…-4.70](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70) · [orderbook](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70/orderbook) |

**Derived figures re-computed from the raw responses:**

| # | Published | Formula | Re-computed | Verdict |
| - | - | - | - | - |
| A8 | `/categories/golf.html` "Bid depth (contracts)" 305,635.54 for `KXPGATOUR-THRC26-TMOO` | sum of the `yes_dollars` sizes | 166,746.66 + 83,333.33 + 55,555.55 = **305,635.54** | exact |
| A9 | `/` ladder for `KXPRESNOMD-28-RW` best YES bid 0.0380, implied YES ask 0.0390 | last element of `yes_dollars`; `1.00 − last element of no_dollars` | 0.0380 and 1.00 − 0.9610 = **0.0390** | exact, and equal to the market record's own `yes_ask_dollars` |

The small volume/OI differences in A1–A6 are **not errors**: the published page is
a snapshot from 2026-11-21T06:24:58Z and the comparison ran ~35 minutes later. A
row whose quote matched while its volume rose is evidence the pipeline captured a
consistent moment, not evidence of a mapping bug.

---

## B. Published resolution rows — 1 checked, exact

| # | Published | Field | Site value | Live API value | Verdict | Source |
| - | - | - | - | - | - | - |
| B1 | `/resolutions.html` | `result`, `settlement_value_dollars`, `settlement_ts`, `status` for `KXAAAGASCDAK-26NOV20-LD` | `yes` / 1.0000 / 2026-11-20T10:35:14.609488Z / finalized | `result: yes`, `settlement_value_dollars: 1.0000`, `settlement_ts: 2026-11-20T10:35:14.609488Z`, `status: finalized` | **exact, all four fields** | [GET /markets/KXAAAGASCDAK-26NOV20-LD](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASCDAK-26NOV20-LD) |

The same response also confirms the settlement rule the site prints ($1 per
winning contract, $0 for the losing side) — see
[market settlement](https://docs.kalshi.com/getting_started/market_settlement).

---

## C. Rule claims re-checked against official docs

| # | Claim on the site | Official source | Verdict |
| - | - | - | - |
| C1 | Candlestick `period_interval` must be 1, 60 or 1440 minutes | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) | confirmed verbatim; `collector/kalshi_api.py:candlesticks` rejects anything else |
| C2 | Best bid is the last element of the level array; the book carries bids only; implied YES ask = 1.00 − best NO bid | [Order book responses](https://docs.kalshi.com/getting_started/orderbook_responses) | confirmed; implemented identically in `collector/kalshi_api.py`, `assets/desk.js` and the new `assets/live-feed.js` |
| C3 | Demo REST roots and WS hosts | [Demo environment](https://docs.kalshi.com/getting_started/demo_env) | confirmed; the sandbox's `GET /exchange/status` returned `exchange_active: true`, `trading_active: true` for all four demo shards, matching `data/run_meta.json` |
| C4 | Batch order books: one request, many tickers | [Get Multiple Market Orderbooks](https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks) | the endpoint answered for a batch request during this session (`{"orderbooks":[{"ticker":"KXPRESNOMD-28-RW",…}]}`), and the client caps at 100 tickers |
| C5 | A candle's `price` block is the last trade, while `yes_bid` / `yes_ask` blocks are quotes | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) response schema | confirmed; the collector's refusal to compare a trade print to a quote mid follows from it |
| C6 | `price_ranges[].step` gives the tick size (0.0010 for `KXPRESNOMD-28-RW`, 0.0100 for `KXPERFORMBONDSONG-35-COL`) | [Get Market](https://docs.kalshi.com/api-reference/market/get-market) + the live responses linked in A1/A5 | confirmed from the responses themselves |

---

## D. Findings (published on `review.html`, linked there to the same sources)

| # | Finding | State |
| - | - | - |
| F-01 | A flat $0.10 threshold is 100 ticks on `KXPRESNOMD-28-RW` (0.0010 grid) and 1 tick on a dead 0.01/1.00 book (`KXPERFORMBONDSONG-35-COL`) | **open**, recommendation published, not implemented (needs a payload change in files owned by other sessions) |
| F-02 | A 1-minute candle close can be one stray quote — `KXPRESNOMD-28-BOBA` daily bar `end_period_ts 1795237200` reports `yes_bid.close 0.0010` with `yes_ask.close 0.8820` | **open**, cross-check with `price.previous_dollars` proposed as `R-F3-1` |
| F-03 | The live pulse measures successive readings, not the collector's candle | by design; the panel states its basis and never merges the two series |
| F-04 | 411 of 750 ranked events carry no two-sided quote | now stated on the overview as a price-mix strip; the rows still show blank (never inferred) |
| F-05 | `KXPERFORMBONDSONG-35-*` books are effectively one-sided (YES bid 0.01 with 1 contract against a 1.00 ask) | Kalshi-side demo data quality; surfaced by the `wide` chip |

---

## E. Retracted finding (kept for honesty)

I initially logged that the pre-rendered `#feedAll` on `/live.html` was
publishing refused moves. **That was wrong.** The tickers I spotted appear only
inside the inline `#snapshot` JSON; the pre-rendered chat blocks contain the
correct empty states, and `alert_chat_row()` is never called for a suppressed
row. Corrected in `COORDINATION.md` before any code was changed, and recorded
here so a later session does not repeat the misread.

---

## F. Test + build evidence for this session's changes

| Gate | Result |
| - | - |
| `python3 -m unittest discover -s tests` | **254 tests, OK** (1 skipped: no demo credentials) |
| `npm test` | 29 pass / 0 fail |
| `node --test test/live-feed.test.mjs` | 18 pass / 0 fail |
| `python3 tools/linkcheck.py` | 50 pages, 679 internal links, **0 errors** |
| `node tools/rendercheck.mjs` | all pages ok |
| `node test/root_render.mjs` | RENDER CHECK PASSED |
| `node test/desk_render_dc732aa6.mjs` | DESK RENDER CHECK PASSED |
| `python3 tools/rowsource_check.py` | 0 missing source URLs, 0 production-host leaks |
| New: `tests/test_live_pulse_f3cb9b9f.py` | 18 tests, incl. a jsdom run of `live.html` + `desk.js` that drives two readings and proves one row for a +$0.30 mover and none for a +$0.06 move, plus a forced-proxy run through `server/app.py` |
| New: `tests/test_orderbook_proxy_f3cb9b9f.py` | 6 tests on the same-origin proxy using a payload captured from the live endpoint |
| Local dashboard | `python3 server/app.py` serves the root site; `/live.html` contains the pulse panel and NO toggle; `/api/orderbooks` returns the documented shape from a stub and a 502 (not a fake book) when the exchange is unreachable |
