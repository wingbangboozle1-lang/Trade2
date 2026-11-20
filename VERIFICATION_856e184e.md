# Verification log — session `arena-856e184e` (2026-11-20)

Branch: `arena/856e184e-trade2` (base `main` @ `1bc32b7`). Scope: tasks T16–T18 on the
coordination board. Other sessions' files (`AUDIT_2026-11-20.md`, `EXECUTIVE_SUMMARY.md`,
`docs/summary.html`) are not edited here.

## Method

- Official data was read through the platform's page-fetch channel, which reaches
  `external-api.demo.kalshi.co` and `docs.kalshi.com`. Direct `curl` from the sandbox to those
  hosts returns HTTP 000 (egress allowlist), so every fetch is recorded below with its URL.
- Each row names the **published value** (where it appears), the **official value** from the
  API response, the **source URL**, and the **result**.
- Some volume values differ slightly between the snapshot and the later API read. That is
  expected because the API keeps trading. Those rows are marked *drift*, not *mismatch*.
- Not every row of every table was re-read in this pass. Unchecked rows are listed in
  "Not verified in this pass" and remain traceable through the API link on each row.

## Official definitions used

| Term | Official wording | Source |
| - | - | - |
| Demo vs production hosts | Demo REST `https://external-api.demo.kalshi.co/trade-api/v2`, production `https://external-api.kalshi.com/trade-api/v2` | https://docs.kalshi.com/getting_started/api_environments.md |
| `open_interest_fp` | "number of contracts bought on this market disconsidering netting" | https://docs.kalshi.com/api-reference/market/get-market.md |
| `notional_value_dollars` | "The total value of a single contract at settlement in dollars" ($1.0000 on these markets) | https://docs.kalshi.com/api-reference/market/get-market.md |
| `yes_bid` / `yes_ask` / `last_price` | Best YES buy offer / lowest YES sell offer / last traded YES contract | https://docs.kalshi.com/api-reference/market/get-market.md |
| Candlestick `price` vs quotes | `price` = OHLC of **trade** YES prices; `yes_bid` and `yes_ask` = OHLC of **offers** | https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md |

## A. Alert and count rows checked this pass

| # | Item | Published value | Official value (API) | Source | Result |
| - | - | - | - | - | - |
| A1 | KXPRESNOMD-28-HBID swing alert, 2026-11-20T18:41:08Z: `previous → current` | 0.811 → 0.4065, delta −0.4045 (`data/alerts.json`) | Candle 1795197600 close: last trade 0.8110; yes_bid close 0.0020; yes_ask close 0.8110. Market: last 0.8110, yes_bid 0.0020, yes_ask 0.8110, no_bid 0.1890. 0.4065 = (0.0020 + 0.8110)/2, a midpoint of a $0.81-wide book, not a trade. | https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-HBID/candlesticks?start_ts=1795190000&end_ts=1795200500&period_interval=60 ; https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID ; https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID/orderbook | **MISMATCH → fixed (T16).** Alert compared a last-trade close with a book midpoint. Current code requires a two-sided quote narrower than $0.10 and compares quote mid with quote mid. The published alert is dropped on the next run. |
| A2 | KXPRESNOMD-28-AKLO swing alert, 18:41:08Z | 0.803 → 0.0025, delta −0.8005 | In the candles ending 1795186800, 1795190400, 1795194000 and 1795197600, `price` close or high reached 0.8030 (trade prints), while `yes_bid` close was 0.0020 and `yes_ask` close 0.0030 in each of them. Quote mid was 0.0025 in every candle, so the quoted price did not move. Market: last 0.0030, yes_bid 0.0020, yes_ask 0.0030. | https://external-api.demo.kalshi.co/trade-api/v2/series/KXPRESNOMD/markets/KXPRESNOMD-28-AKLO/candlesticks?start_ts=1795100000&end_ts=1795200500&period_interval=60 (chunks 1 and 2) ; https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-AKLO | **MISMATCH → fixed (T16).** Trade prints at 0.803 with no matching quotes produced the alert. The quote-based reference removes it. **Irregularity for Kalshi demo data:** trade prints at 0.8030 coincide with quotes of 0.0020/0.0030. Logged for review; not a site defect. |
| A3 | KXPRESNOMD-28-JP swing alert, 18:41:08Z | 0.944 → 0.477, delta −0.467; published bid 0.010, ask 0.944 | Published record only. The spread of the published book is 0.934, which is wider than the $0.10 rule. The live API was **not** re-read for this row. | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-JP | **Removed by the fix on the published bid/ask alone.** Live API not re-read. |
| A4 | Overview stat "Markets tracked" | `750.00` | `observation_count` = 750 (integer count) | `index.html` (before fix) | **Formatting defect → fixed.** Counts were formatted as 2-decimal floats. Now `cnt()` renders whole numbers. Same fix applied to resolved, open-position, strategy-trade and topic counts. Contract volumes and open interest keep their fractional `_fp` values. |
| A5 | Overview stat "Open positions" | `1.00` | 1 open simulated position | `index.html` (before fix) | **Formatting defect → fixed** (as A4). |
| A6 | Overview stat "Resolved tracked" | `2,000.00` | `resolutions_count` = 2000 | `index.html` (before fix) | **Formatting defect → fixed** (as A4). |

## B. Market rows checked against the official API

These are rows from the live overview table (`index.html`, "Highest-dollar open events").
Published values were read from the overview page at 2026-11-20T18:41:08Z.

| # | Market | Field | Published | Official (API read time) | Source | Result |
| - | - | - | - | - | - | - |
| B1 | KXPRESNOMD-28-RW (Raphael Warnock) | YES bid | $0.0310 | `yes_bid_dollars` 0.0310 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW | Match |
| B1 | | YES ask | $0.0330 | `yes_ask_dollars` 0.0330 | (same) | Match |
| B1 | | Open interest | 189,529,515.91 | `open_interest_fp` 189529515.91 | (same) | Match |
| B1 | | Volume | 414,910,468.14 | `volume_fp` 414910564.18 | (same) | Drift (+96.04 contracts after snapshot) |
| B2 | KXPRESNOMD-28-GW (Gretchen Whitmer) | YES bid / ask | $0.0050 / $0.0060 | 0.0050 / 0.0060 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-GW | Match |
| B2 | | Open interest | 169,497,438.62 | 169497438.62 | (same) | Match |
| B2 | | Volume | 432,107,027.52 | 432107162.44 | (same) | Drift (+134.92 contracts) |
| B3 | KXBTCY-27JAN0100-B127500 (BTC 125,000–129,999.99) | YES bid / ask | $0.0000 / $0.0100 | 0.0000 / 0.0100 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B127500 | Match |
| B3 | | Open interest | 39,622,137.23 | 39622137.23 | (same) | Match |
| B3 | | Volume | 83,444,025.31 | 83444025.31 | (same) | Match |

Irregularities seen in these rows (flagged, not changed):
- Overview headline "Highest-dollar" ranks by "OI value" = open interest × $1 notional. This is a notional
  figure, not dollars traded (see definitions above). Flagged on the Flagged page.
- Market title text contains a double space: `"BTC price  on Jan 1, 2027?"` (KXBTCY-27JAN0100-B127500, API `title`). This is an upstream
  data-quality irregularity, not a site defect.

## C. Pipeline and source-of-data checks

| # | Item | Finding | Source | Result |
| - | - | - | - | - |
| C1 | kalshi-dashboard collector host | `scripts/collect.mjs` defaulted to `PRODUCTION_BASE`. Published `kalshi-dashboard/data/status.json` records `base_url` `https://external-api.kalshi.com/trade-api/v2`. The brief asked for demo. | https://docs.kalshi.com/getting_started/api_environments.md ; https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/data/status.json | **Fixed (T17).** Default is `DEMO_BASE`. A production base now requires `--base` or `KALSHI_BASE`, and the page label says so. Test added in `scripts/test/collect.test.mjs`. |
| C2 | Root Python collector host | `collector/collector.py` uses `DEMO_REST`. | https://docs.kalshi.com/getting_started/api_environments.md | Match (no change) |
| C3 | Trading ledger | 1 open simulated position (`KXBTCY-27JAN0100-B87500`, strategy `value`), not swing-based. No simulated trade in the current ledger came from a phantom alert. | `data/portfolio_state.json` | Checked. No effect from the alert bug. |
| C4 | `docs/` alerts (trade-price closes) | Three hourly trade-price moves, e.g. KXRT-FUR-85 0.43 → 0.05. Not checked against quotes. | https://wingbangboozle1-lang.github.io/Trade2/docs/data/alerts.json | **Open.** Flagged on the Flagged page. |

## Tests after this pass

- `python3 -m unittest discover -s tests` → 54 tests, OK (1 skipped, pre-existing). Includes the
  new `tests/test_alerts_basis.py` (12 tests: HBID/AKLO regressions, quote-only reference, rule boundaries,
  stored-record purge). `tests/test_engine.py::test_reference_bar_catches_a_gradual_move` now passes
  `reference_spread`, because a reference is only valid with its own quote spread.
- `python3 -m collector.test_runner` → PASS.
- `python3 -m trading.test_engine` → PASS.
- `npm test` → 19/19 pass (includes the new demo-default test).
- `python3 -m site_build.build` → regenerated pages differ only in count formatting and the new
  Flagged entries (verified by `git diff`).
- `python3 tools/linkcheck.py` → 0 broken internal links.

## Not verified in this pass (kept as open items)

- Only 3 of the 25 overview market rows and 3 of the 29 stored alerts were re-read from the official
  API. The remaining rows are not re-verified here. They are generated from API responses and link to the
  API URL on each row.
- The alert count after the fix is expected to fall, but this has not been observed. It will be observed
  on the first scheduled run of the root pipeline after merge (`kalshi-dashboard.yml`, every 5 min).
- Demo trade prints that disagree with quotes (A2) are a Kalshi demo data observation. Their cause has not
  been established.
- No Kalshi demo credentials exist in this repository, so no authenticated demo-account balance, fill or
  order was read or placed.
