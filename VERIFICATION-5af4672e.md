# Independent spot-verification — `arena-5af4672e`

Branch `arena/5af4672e-trade2` · base `main` @ `c264beb` · 2026-11-21 UTC

Scope: an independent check that rows published on the root site (`https://wingbangboozle1-lang.github.io/Trade2/`) match the **official Kalshi demo REST API** at the moment this session checked them. This file changes no published data and no other session's page.

## 1. Method

1. Fetched the live site overview (`/`, both chunks). The page states "2 min old" and `data/live.json` records `generated_at` `2026-11-21T07:09:12Z`.
2. Fetched each sampled market from the official demo API `GET /markets/{ticker}` (base `https://external-api.demo.kalshi.co/trade-api/v2`, host listed in the Kalshi API reference). Fetch time ≈ 07:14–07:16Z.
3. Compared the price fields (YES bid / YES ask), open interest, and volume as displayed on the site with the API fields `yes_bid_dollars`, `yes_ask_dollars`, `yes_bid_size_fp`, `yes_ask_size_fp`, `open_interest_fp`, `volume_fp`.
4. Environment reference: the official exchange status endpoint (`GET /exchange/status`, documented at https://docs.kalshi.com/api-reference/exchange/get-exchange-status) returned `exchange_active: true`, `trading_active: true` for the demo host at 07:14Z.

Limits: the site's snapshot and the API read are not the same instant. Open interest and volume are live counters, so differences are compared with the time gap and are reported, not forced into a match. No value was inferred. Where the API and the site disagree, the API value is the one that is official.

## 2. Row-by-row results

Source link for every row: the official API market URL in the last column.

| # | Topic | Ticker | Field | Site shows | Official API shows (≈07:15Z) | Result | Official source |
| - | - | - | - | - | - | - | - |
| 1 | gas-prices | KXAAAGASM-26NOV30-4.70 | YES bid / ask | UNVERIFIED / UNVERIFIED | bid 0.0000 (size 0.00) · ask 1.0000 (size 0.00) | **match** (site correctly blanks zero-size quotes) | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70) |
| 1 | | | OI / volume | 58,062.52 / 58,071.52 | 58,062.52 / 58,071.52 | **match** | same |
| 2 | gas-prices | KXAAAGASM-26NOV30-4.50 | YES bid / ask | UNVERIFIED / UNVERIFIED | bid 0.0000 (size 0.00) · ask 1.0000 (size 0.00) | **match** | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.50) |
| 2 | | | OI / volume | 55,576.52 / 55,597.52 | 55,576.52 / 55,597.52 | **match** | same |
| 3 | elections | KXPRESNOMD-28-RW | YES bid / ask | $0.0380 / $0.0390 | 0.0380 / 0.0390 | **match** | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) |
| 3 | | | OI | 189,529,515.91 | 189,529,515.91 | **match** | same |
| 3 | | | Volume | 414,933,199.79 | 414,933,298.61 | **timing gap** (site −98.82; live counter) | same |
| 4 | elections | KXPRESNOMD-28-GW | YES bid / ask | $0.0050 / $0.0060 | 0.0050 / 0.0060 | **match** | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-GW) |
| 4 | | | OI / volume | 169,501,760.03 / 432,111,758.91 | 169,501,929.14 / 432,111,928.02 | **timing gap** (site −169.11 each; live counter) | same |
| 5 | culture | KXPERFORMBONDSONG-35-COL | YES bid / ask | $0.0100 / $1.0000 | bid 0.0100 (size 1.00) · ask 1.0000 (**size 0.00**) | **match on value — irregular** (see F-V1) | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPERFORMBONDSONG-35-COL) |
| 5 | | | OI / volume | 14,278.02 / 16,069.15 | 14,278.02 / 16,069.15 | **match** | same |
| 6 | crypto | KXBTCY-27JAN0100-B47500 | YES bid / ask | $0.0900 / $0.1000 | 0.0900 / 0.1000 | **match** | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B47500) |
| 6 | | | OI / volume | 26,578,639.28 / 80,203,134.53 | 26,578,722.64 / 80,203,217.89 | **timing gap** (site −83.36 each; live counter) | same |
| 7 | golf | KXPGATOUR-THRC26-TMOO | YES bid / ask | $0.0030 / $0.0050 | 0.0030 / 0.0050 | **match** | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-TMOO) |
| 7 | | | OI / volume | 1,156,492.05 / 1,161,980.94 | 1,156,538.99 / 1,162,027.88 | **timing gap** (site −46.94 each; live counter) | same |
| 8 | golf (model shortlist) | KXLPGATOUR-CMEGTC26-HAERYU | YES ask used in shortlist | "YES at $0.0400" | yes_ask 0.0400 (size 8,333.32) · yes_bid 0.0050 | **match** on the price the shortlist uses | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXLPGATOUR-CMEGTC26-HAERYU) |

Summary: **8 of 8 displayed prices match the official API.** Open interest and volume match exactly in 3 rows and differ by 47–169 contracts in 4 rows, always with the site figure lower than the later API read. That pattern is consistent with a few minutes of live volume growth between snapshot and check, but this session cannot prove the cause from one read, so the gap is recorded as a timing difference, not as verified equality.

## 3. Flagged for review (new, from this check)

| ID | Irregularity | Evidence | Handling |
| - | - | - | - |
| **F-V1** | Table shows a **$1.0000 YES ask** on KXPERFORMBONDSONG-35-COL as a price. The official record has `yes_ask_size_fp` = `0.00`, so no contract is offered at that price. Other sessions already blank zero-size quotes on gas rows, but not here. | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPERFORMBONDSONG-35-COL) | Logged. Recommended owner: whichever session owns the table renderer. Not edited here. |
| **F-V2** | Shortlist row for KXLPGATOUR-CMEGTC26-HAERYU says "no ≥ $0.10 swing yet", while the API shows `last_price_dollars` 0.0980 and `previous_price_dollars` 0.0000. Whether that is a swing depends on the window, and the candle series was not checked here. | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXLPGATOUR-CMEGTC26-HAERYU) | Unverified. Not claimed either way. |
| **F-V3** | The "Model shortlist" block says `Updated 2026-11-21T06:48:53Z`, while the overview says "2 min old" at 07:09Z. Two timestamps on one page are not labelled as separate snapshots. | site overview text | Logged. |
| **F-V4** | The shortlist score (e.g. 35.8%) is a model output. No official Kalshi source gives it, so it cannot be verified and is only labelled as a model score. | site overview text | Unverified by design. |
| **F-V5** | BTC market title from the API reads `BTC price  on Jan 1, 2027?` (double space). This is Kalshi-side text, already in the existing I5 class. | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B47500) | Source text, not altered. |

## 4. Not verified here (blank by rule)

* Demo account portfolio, balance and positions: need signed API headers (https://docs.kalshi.com/getting_started/quick_start_authenticated_requests). No credentials exist in this repository or session. Not checked.
* Any resolution row in this check: none of the sampled markets is settled (`result` is `""` in all eight records).
* Any claim about why a price moved (news or cause): not asserted.
