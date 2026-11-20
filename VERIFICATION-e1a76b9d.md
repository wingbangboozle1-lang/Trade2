# VERIFICATION-e1a76b9d — Field-by-field data dictionary check

Session `arena-e1a76b9d` · branch `arena/e1a76b9d-trade2` · base `main` @ `eef1243` (rebased on `origin/main` @ `e8e7b10`)
Board task: **E1-T1** (see `COORDINATION.md`, Board F)

**Scope.** Every key in the published JSON that the Pages tables read (`docs/data/markets.json`, `resolutions.json`, `orderbooks.json`, `candles.json`, `alerts.json`, `series.json`), plus the column headers that a reader sees on the `docs/` and root dashboards. For each one: the code that writes it, the official Kalshi field it is meant to carry, the official definition, and a verdict.

**Read-only.** No HTML page, generator, collector, workflow, `docs/data/*.json`, or other session's file was edited. Problems are published as requests and flags, not fixed here.

**Verdicts used**

| Verdict | Meaning |
| - | - |
| **Verified** | The published key reads an official field, and the official definition matches the label. |
| **Mismatch** | The code reads a key the official object does not carry, or the wrong key, so the published value is wrong or always blank. |
| **Derived** | Computed by this project from official fields. Not an official Kalshi field. The formula is shown. |
| **Normalized** | Official value relabelled for display. |
| **UNVERIFIED** | Could not be confirmed from the official text retrieved this session. Left as an open item, not filled in. |

---

## 1. Official sources used (all retrieved 2026-11-20, UTC)

The sandbox cannot reach `docs.kalshi.com` or the demo API directly (egress allowlist). Each page below was retrieved through the fetch tool at the exact URL shown. Where the retrieved text was cut off, that is stated.

| ID | Official URL | Used for | Retrieval note |
| - | - | - | - |
| S1 | <https://docs.kalshi.com/api-reference/market/get-markets.md> | `Market` object schema (all market fields, `status` enum, `expected_expiration_time`, `title` deprecation, `notional_value_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `result`, `settlement_value_dollars`, `settlement_ts`) | Full schema retrieved across 3 chunks. |
| S2 | <https://docs.kalshi.com/api-reference/market/get-series-list.md> | `Series` object: `fee_type`, `fee_multiplier`, `category`, `categories`, `tags`, `settlement_sources`, `contract_terms_url`; `FeeType` enum | **Partial.** Retrieved text ends after `fee_type`. `fee_multiplier`, `additional_prohibitions` and any `last_updated_ts` are listed as required or used by code but do not appear in the retrieved text. |
| S3 | <https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md> | `period_interval` valid values (1, 60, 1440 minutes); `MarketCandlestick` (`end_period_ts`, `price` OHLC, `yes_bid`/`yes_ask` OHLC, `volume_fp`, `open_interest_fp`) | Full schema retrieved (2 chunks). |
| S4 | <https://docs.kalshi.com/api-reference/market/get-market-orderbook.md> | `orderbook_fp.yes_dollars` / `no_dollars` as `[price, qty]`; best bid is the **last** element | Full schema retrieved. |
| S5 | <https://docs.kalshi.com/api-reference/events/get-event.md> | `EventData.title` ("Full title of the event"), `sub_title` | Retrieved chunk 0 of 3; the fields used are in chunk 0. |
| S6 | <https://docs.kalshi.com/getting_started/market_settlement.md> | YES holders receive $1 per contract on a YES outcome; NO holders receive $1 on a NO outcome | Full page retrieved. |
| S7 | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-MMEI> | Live official demo `Market` object for one published row (spot check) | Live response, retrieved 2026-11-20. |
| S8 | <https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDOGE-26NOV2013-T0.2349999> | Live official demo `Market` object for one published resolution row (spot check) | Live response, retrieved 2026-11-20. |

---

## 2. Live spot checks (S7, S8) against the published snapshot

Snapshot: `docs/data/markets.json` generated `2026-11-20T19:44:12Z`. The live fetch happened later, so small drift in volume and open interest is expected and is **not** treated as an error.

### 2a. `KXPGATOUR-THRC26-MMEI` (S7)

| Published key | Published value | Live official field (S7) | Live value | Verdict |
| - | - | - | - | - |
| `ticker` | `KXPGATOUR-THRC26-MMEI` | `ticker` | same | Verified |
| `event_ticker` | `KXPGATOUR-THRC26` | `event_ticker` | same | Verified |
| `title` | "The RSM Classic: Mac Meissner wins" | `title` | same (field is **deprecated** in S1) | Verified value, deprecated source. See F-E1-03 |
| `status` | `open` | `status` | `active` | Normalized. See F-E1-06 |
| `yes_bid` | 0.002 | `yes_bid_dollars` | `0.0020` | Verified |
| `yes_ask` | 0.003 | `yes_ask_dollars` | `0.0030` | Verified |
| `last_price` | 0.003 | `last_price_dollars` | `0.0030` | Verified |
| `volume_fp` | 495557.75 | `volume_fp` | 495657.55 | Verified field; snapshot drift +99.80 |
| `volume_24h_fp` | 341469.99 | `volume_24h_fp` | 341446.37 | Verified field; snapshot drift |
| `open_interest_fp` | 347551.77 | `open_interest_fp` | 347651.57 | Verified field; snapshot drift +99.80 |
| `price_level_structure` | `tapered_deci_cent` | `price_level_structure` | same | Verified |
| `expected_expiration` | **null** | `expected_expiration_time` | **`2026-11-22T00:00:00Z`** | **Mismatch.** See F-E1-01 |
| `fee_type` | **null** | *(no such field on the Market object)* | — | **Mismatch.** See F-E1-02 |
| `series_ticker` | `KXPGATOUR` | *(no `series_ticker` on the Market object)* | — | Derived (ticker prefix). See F-E1-13 |
| `notional_usd` | 1024.41 | *(not an official field)* | — | Derived: `volume_24h_fp × last_price` = 341469.99 × 0.003 = 1024.41. Recomputed exactly. See F-E1-04 |
| `source_url` | `…/markets/KXPGATOUR-THRC26-MMEI` | the endpoint itself | returned | Verified (the URL resolves to this object) |

The live object also reports `notional_value_dollars` = `1.0000` (S1: "The total value of a single contract at settlement in dollars"). That is the official input for the root dashboard's "OI value" (see §4).

### 2b. `KXDOGE-26NOV2013-T0.2349999` (S8)

| Published key (`resolutions.json`) | Published value | Live official field (S8) | Live value | Verdict |
| - | - | - | - | - |
| `ticker` | `KXDOGE-26NOV2013-T0.2349999` | `ticker` | same | Verified |
| `event_ticker` | `KXDOGE-26NOV2013` | `event_ticker` | same | Verified |
| `result` | `no` | `result` | `no` | Verified |
| `settlement_value` | 0.0 | `settlement_value_dollars` | `0.0000` | Verified. It is the **YES-side** value. See F-E1-11 |
| `settlement_ts` | `2026-11-20T19:36:33.782757Z` | `settlement_ts` | same | Verified |
| `volume_fp` | 0.0 | `volume_fp` | `0.00` | Verified |
| `status` (not published) | — | `status` = `finalized` | — | Note: settled markets report `finalized`. The page does not show it. |

Consistency with the settlement rule (S6): a `no` result gives a YES-side settlement of 0, and NO holders receive $1. The published row is consistent with S6.

---

## 3. Data dictionary: every published key

Columns: published key · where shown · code that writes it (file:line) · official field and definition · verdict · flag.

### 3a. `docs/data/markets.json` (40 rows, one per tracked market)

| Key | Where shown | Written from (code) | Official field / definition | Verdict | Flag |
| - | - | - | - | - | - |
| `ticker` | Market tables | `collector/runner.py:221` `m.get("ticker")` | `Market.ticker` (S1) | Verified | — |
| `event_ticker` | Market tables | `runner.py:222` | `Market.event_ticker` (S1) | Verified | — |
| `title` | Market tables | `runner.py:223` `m.get("title")` | `Market.title` is **`deprecated: true`** in S1. Full event title is `EventData.title` (S5). Market object still returns a value (S7) | Verified value, deprecated source | F-E1-03 |
| `topic` | Market tables | `runner.py:224` `_topic` | Not an official field. Project topic mapping (`collector/topics.py`) | Derived | — |
| `series_ticker` | Market tables | `runner.py:215` (derivation) → `runner.py:225` or the **ticker prefix before the first hyphen** | Not on the `Market` object (S1, S7). The docs do not state that the prefix is the series | **Derived by string split (inferred join)** | F-E1-13 |
| `status` | Market tables | `runner.py:218-219` `active`→`open` | `Market.status` enum is `initialized, inactive, active, closed, determined, disputed, amended, finalized` (S1). `open` is a query-filter value, not an object status | Normalized | F-E1-06 |
| `yes_bid` | Market tables | `runner.py:205` `yes_bid_dollars` | `yes_bid_dollars` "Price for the highest YES buy offer on this market in dollars" (S1) | Verified (S7 match) | — |
| `yes_ask` | Market tables | `runner.py:206` `yes_ask_dollars` | `yes_ask_dollars` "Price for the lowest YES sell offer" (S1) | Verified (S7 match) | — |
| `last_price` | Market tables | `runner.py:204` `last_price_dollars` | `last_price_dollars` "Price for the last traded YES contract" (S1) | Verified (S7 match) | — |
| `volume_fp` | Market tables | `runner.py:209` | `volume_fp` "String representation of the market volume in contracts" (S1) | Verified | — |
| `volume_24h_fp` | Market tables | `runner.py:231` | `volume_24h_fp` "24h market volume in contracts" (S1) | Verified | — |
| `open_interest_fp` | Market tables | `runner.py:233` | `open_interest_fp` "number of contracts bought on this market disconsidering netting" (S1) | Verified | — |
| `notional_usd` | Market tables, "$ volume" header | `runner.py:182-198` `market_notional`; `runner.py:232` | **No official dollar-volume field.** Value is `(volume_24h_fp, or volume_fp if 24h is 0) × last_price_dollars`. The code comment calls it "Dollar volume proxy" | **Derived.** Recomputed for all 40 rows, 0 mismatches. Latent fill-in risk | F-E1-04, F-E1-05 |
| `expected_expiration` | Market tables | `runner.py:234` `m.get("expected_expiration_ts")` | Official field is **`expected_expiration_time`** (ISO date-time, nullable) (S1). The code key does not exist, so the value is always null | **Mismatch.** 40/40 blank, but S7 shows a value | F-E1-01 |
| `fee_type` | Market tables | `runner.py:235` `m.get("fee_type")` | Not on `Market` (S1, S7). It is on **`Series.fee_type`** (S2): `quadratic`, `quadratic_with_maker_fees`, `quadratic_with_combo_maker_fees`, `flat` | **Mismatch.** Always null by construction | F-E1-02 |
| `price_level_structure` | Market tables | `runner.py:236` | `price_level_structure` "Price level structure … defining price ranges and tick sizes" (S1) | Verified (S7 match) | — |
| `source_url` | Every row | `runner.py` `api_link(...)` | Official host, endpoint `/markets/{ticker}` | Verified (S7 resolves) | — |
| `docs_url` | Every row | `runner.py` `SOURCE_MARKETS` | `docs.kalshi.com/api-reference/market/get-markets` (S1) | Verified | — |
| `flags` | Internal | `runner.py:239` | Project-only list of collector flags | Derived | — |
| `verified` | Table column ("verified") | `runner.py:240` `not flags` | **Not a source check.** True only when the collector has no missing-field flags | Derived; label overstates. See F-E1-07 | F-E1-07 |

### 3b. `docs/data/resolutions.json` (300 rows)

| Key | Written from | Official field / definition | Verdict | Flag |
| - | - | - | - | - |
| `ticker`, `event_ticker`, `title`, `topic`, `docs_url`, `source_url` | `runner.py` | As §3a. `title` from deprecated `Market.title` | As §3a | F-E1-03 |
| `result` | `runner.py:461,470` `m.get("result")` (only `yes`/`no` kept) | `Market.result` enum `yes`, `no`, `scalar`, `""` (S1) | Verified | — |
| `settlement_value` | `runner.py:471` `settlement_value_dollars` | "The settlement value of the **YES/LONG side** of the contract in dollars. Only filled after determination" (S1) | Verified. The value is YES-side, so NO outcomes show 0.0 | F-E1-11 |
| `settlement_ts` | `runner.py:472` | `Market.settlement_ts`, "Timestamp when the market was settled" (S1) | Verified (S8 match) | — |
| `volume_fp` | `runner.py` | `volume_fp` (S1) | Verified (S8 match) | — |
| Coverage | — | Cross-check: all 300 rows are `result = no`, `settlement_value = 0.0` | One live spot check (S8) matches. The 300/300 `no` pattern is already flagged as F-4F-03 by `arena-4f92a11c`. This session did not verify the rest | Verified 1 of 300 by live check. See F-E1-14 | F-E1-14 |

### 3c. `docs/data/orderbooks.json` (10 books)

| Key | Written from | Official field / definition | Verdict | Flag |
| - | - | - | - | - |
| `yes_levels`, `no_levels` | `runner.py:278-279` from `orderbook_fp.yes_dollars` / `no_dollars` | `[price_dollars, contract_qty]` pairs (S4) | Verified | — |
| `best_yes_bid`, `best_no_bid` | `runner.py:280-281` → `kalshi_api.best_bid` | "best (highest) bid is the **last** element" (S4). `best_bid` takes the last element (`collector/kalshi_api.py:352-360`) | Verified (logic matches S4) | — |
| `implied_yes_ask` | `runner.py:290` `1 − best_no_bid` | The documented equivalence: a YES bid at X equals a NO ask at 1−X (S4) | Derived from an official equivalence. Verified | — |
| `yes_depth_usd`, `no_depth_usd` | `kalshi.py:191-201` `depth_usd` = Σ price × contracts | No official dollar-depth field. Derived | Derived. The `_usd` suffix means derived, not official | F-E1-10 |
| `yes_depth_contracts`, `no_depth_contracts` | `kalshi.py:191` Σ contracts | Derived sum of official quantities | Derived | — |

### 3d. `docs/data/candles.json` (per-market windows `seconds` / `minutes` / `hours`)

| Key | Written from | Official field / definition | Verdict | Flag |
| - | - | - | - | - |
| `t` | `runner.py:333` `end_period_ts` | `end_period_ts`, "inclusive end of the candlestick period" (S3) | Verified | — |
| `open`, `high`, `low`, `close` | `runner.py:334-337` from `price.open_dollars` / `high_dollars` / `low_dollars` / `close_dollars` | `price` OHLC = **last traded YES price** per period; "May be null if there was no trade" (S3) | Verified field. Semantics are **last trade**, not a quote | F-E1-09 |
| `volume` | `runner.py:338` `volume_fp` | `volume_fp` (S3) | Verified | — |
| `interval` | `runner.py` window period | Official `period_interval` ∈ {1, 60, 1440} **minutes** (S3) | Verified values. Window names do not match bar size | F-E1-08 |

### 3e. `docs/data/alerts.json` (4 rows)

| Key | Written from | Official field / definition | Verdict | Flag |
| - | - | - | - | - |
| `from`, `to` | `runner.py:419-420` candle `price.close_dollars` | Last traded YES price (S3) | Derived **swing** from last-trade closes. The root pipeline uses quote mids (`collector/alerts.py:89-93`). See F-E1-09 | F-E1-09 |
| `delta`, `threshold` (0.10), `direction` | `runner.py:401` | Not an official field. Project rule: ≥ $0.10 either way (brief) | Derived | — |
| `t`, `t_iso`, `window`, `ticker`, `title`, `topic` | `runner.py` | `t` = candle `end_period_ts`; others as §3a | Verified / Derived as labelled | — |
| `headlines`, `news_status`, `docs_url`, `source_url`, `candle_source_url` | `runner.py` | Third-party news links are **not** Kalshi data. They are research links only | Not verified as causes (see project limits). Labelled as research links | — |

### 3f. `docs/data/series.json` (59 rows)

| Key | Written from | Official field / definition | Verdict | Flag |
| - | - | - | - | - |
| `ticker`, `title`, `category`, `categories`, `tags`, `settlement_sources`, `contract_terms_url` | `runner.py:112-125` | `Series` fields (S2), with `title`, `category`, `categories`, `tags`, `settlement_sources`, `contract_terms_url` all listed as required | Verified (names). Values per official schema | — |
| `volume` | `runner.py:124` `volume_fp` | S2 documents `include_volume` as "total volume traded across all events in each series", but the retrieved text does not show a `volume_fp` property on `Series` | **UNVERIFIED field name** (code comment says `volume_fp`) | F-E1-12 |
| `last_updated` | `runner.py:125` `last_updated_ts` | Not in the retrieved S2 text | **UNVERIFIED** | F-E1-12 |
| `fee_type` | not written | `Series.fee_type` is required (S2) | **Omitted.** Official field exists and is not published on the series table. See F-E1-02 | F-E1-02 |
| `topic`, `source_url`, `verified` (`True` constant) | `runner.py:128-130` | Not official. `verified: True` is a constant, not a check | Derived. `verified` is a constant label | F-E1-07 |

### 3g. `docs/data/portfolio.json`, `trades`, `strategy_lab.json`

| Keys | Verdict | Note |
| - | - | - |
| `cash`, `equity`, `fees_paid`, `positions`, `trades`, `stats`, `pnl`, `equity_curve`, `backtest`, `aggregates` | **Simulated** (`mode = simulated-paper`, `credentials = none`) | No official portfolio data was read. Account-level values need authenticated endpoints, which this project does not use. Not verified against an official account. Labelled SIMULATED in the source. |
| Fees inside simulation (`fee_formula`) | Derived from the official fee schedule as cited by other sessions. Not re-verified here | Out of scope for this session |

---

## 4. Displayed labels (what a reader sees)

| Label | Where | What it actually computes | Official? | Verdict | Flag |
| - | - | - | - | - | - |
| **$ volume** / "tracked $ volume" / "ranked by $ volume" | `docs/` markets and topic summaries (`docs/assets/app.js:426`, `:467`, `:482`) | `volume_24h_fp (or volume_fp) × last_price` | No official dollar-volume field | Derived proxy. Needs a footnote saying so | F-E1-04 |
| **OI value** / "Open interest" | Root overview (`site_build/build.py:286,300,418,557`) | `open_interest_fp × notional_value_dollars`, i.e. contracts × the $ settlement value of one contract | Both inputs are official (S1). The product is a **notional** figure | Derived. Already flagged as F-856-4 | F-E1-04 |
| **Book liquidity**, bid depth, depth $ | `docs/` and root | Σ price × contracts on the book (`kalshi.py:191`) | Derived from official levels (S4) | Derived | F-E1-10 |
| **verified** | `docs/` tables | `not flags` (collector) or constant `True` (series) | Not a source verification | Misleading label | F-E1-07 |
| **Settlement value** | `docs/` resolutions | YES-side settlement (S1) | Official, but the label does not say YES side | Verified, label unclear | F-E1-11 |
| **seconds / minutes / hours** chart windows | `docs/` charts | `seconds` = 1-minute bars, `minutes` = 60-minute bars (or live 1-minute bars when present, per `docs/assets/app.js:565-567`), `hours` = 1440-minute (daily) bars | Official periods are 1, 60, 1440 minutes; **no sub-minute REST candle exists** (S3) | Window names overstate their bar size. Already tracked as T15 by `arena-e4e8f4e1` | F-E1-08 |
| **Win rate, Expectancy, ROI on cost, Net ROI, Avg P&L, P&L, Realised, Unrealised** | Strategy and portfolio pages | Project simulation metrics (`trading/`, `tools/strategy_lab.py`) | Not Kalshi fields | Derived / simulated. No official definition exists, so none can be "verified" | F-E1-15 |

---

## 5. Irregularities (for the Flagged for Review page)

Each item cites its source and the file that needs the fix. Nothing here was changed in this session.

| ID | Sev. | Finding | Evidence | Owner / request |
| - | - | - | - | - |
| **F-E1-01** | **High** | `expected_expiration` is always blank because the collector reads a key the official Market object does not carry. The official field is `expected_expiration_time`. For a live sample, the official value is present. The 40/40 blank is a **code defect**, not missing source data. | Code: `collector/runner.py:234` reads `expected_expiration_ts`; `docs/assets/app.js:189` reads `raw.expected_expiration_ts`. Official: S1 `expected_expiration_time` (nullable). Live: S7 `"expected_expiration_time":"2026-11-22T00:00:00Z"` for `KXPGATOUR-THRC26-MMEI`. | R-E1-01 |
| **F-E1-02** | Medium | `fee_type` is always blank on markets, because `fee_type` is not a `Market` field. It is a required `Series` field (S2). The series table does not publish it either. | Code: `runner.py:235` `m.get("fee_type")`; `topics.py:289` gets it from the series, but `runner.py` series rows (`:112-130`) drop it. Live S7: no `fee_type` key on the market object. | R-E1-01, R-E1-02 |
| **F-E1-03** | Low | Market `title` is marked `deprecated: true` in the official schema (S1). The value is still returned (S7). The full event title is `EventData.title` (S5). The published "Title" comes from the deprecated field. | S1 `title` deprecated. S5 "Full title of the event". Code: `runner.py:223`. | R-E1-01 |
| **F-E1-04** | Medium | Two incompatible "highest dollar" rankings are published. `docs/` ranks by `volume_24h × last price` ("$ volume"). The root site ranks by `open_interest × notional value` ("OI value"). For the same market they differ by orders of magnitude. Neither is an official Kalshi dollar figure. | Example `KXPGATOUR-THRC26-MMEI`: published "$ volume" = **$1,024.41** (341,469.99 × 0.003). OI value (live S7: 347,651.57 × 1.0000) = **$347,651.57**. Code: `runner.py:182-198`, `site_build/build.py:286`. | R-E1-01, R-E1-03 |
| **F-E1-05** | Low (latent) | `market_notional` falls back to an **invented price of 0.5** when a market has no last, bid or ask price, and the result is written as `notional_usd`. This is a fill-in, which the brief forbids. It affects **0 of 40** published rows, because every published row has a last price. | `runner.py:197` `price = 0.5  # ranking fallback only; the displayed value stays null in tables`. The comment is wrong: `runner.py:232` writes the value to the row. | R-E1-02 |
| **F-E1-06** | Low | `status` shows `open` for every market. The official object status is `active` (S1, S7). `open` is only a query-filter value. The collector silently renames the value. | `runner.py:218-219`. S1 `Market.status` enum. S7 `"status":"active"`. | R-E1-01 (show the raw status, or label it "normalized") |
| **F-E1-07** | Medium-low | The "verified" column means "no collector flags". It does not mean a source check was performed. Series rows set `verified: True` as a constant. | `runner.py:240` `"verified": not flags`; `runner.py:130` `"verified": True`. | R-E1-01 |
| **F-E1-08** | Medium | Chart window names overstate bar size. `seconds` shows **1-minute** bars, `minutes` shows **60-minute** bars (or live 1-minute bars when present), and `hours` shows **daily** bars. Official candlesticks have no sub-minute period. | S3: valid `period_interval` values 1, 60, 1440 minutes. `docs/data/candles.json` `interval` 1 / 60 / 1440. `docs/assets/app.js:565-567`. Already claimed as T15 by `arena-e4e8f4e1`; this session confirms the data still shows it. | R-E1-01 (or T15 owner) |
| **F-E1-09** | Medium-low | Two different swing definitions run side by side. The `docs/` pipeline (`alerts.json`) measures swings between **last-trade** closes (`price.close_dollars`, which can be null). The root pipeline (`collector/alerts.py`) measures **quote mids** and explicitly rejects last-trade closes (`alerts.py:89-93`). An alert can appear on one dashboard and not the other. | `runner.py:334`, `:396-420`; `collector/alerts.py:89-93`; S3 (`price.close_dollars` "Last traded YES contract price … May be null"). | R-E1-01 |
| **F-E1-10** | Info | `yes_depth_usd` / `no_depth_usd` are derived as Σ price × contracts. The `_usd` suffix can be read as an official figure. | `collector/kalshi.py:191-201`. S4 has no dollar-depth field. | Labelling only |
| **F-E1-11** | Low | Settlement value is the **YES-side** value. A NO outcome shows `0.0`, which is correct, but the label does not say so. | S1 "settlement value of the YES/LONG side". S6: NO holders receive $1. S8 matches. | Label change, R-E1-01 |
| **F-E1-12** | Low | Two Series fields have no confirmed official name in the retrieved text: `volume` ← `volume_fp` and `last_updated` ← `last_updated_ts`. | `runner.py:124,125`. S2 retrieved text ends after `fee_type` (§1). | UNVERIFIED. Re-check S2 chunk 2 or the live API |
| **F-E1-13** | Medium | `series_ticker` on each market is **derived by splitting the ticker** at the first hyphen. The official Market object has no `series_ticker`, and the docs retrieved here do not state that the prefix is the series. The candlestick endpoint requires `series_ticker` in its path, so this inferred join drives candle requests. | `runner.py:213-215`. S1 and S7 have no `series_ticker`. S3 path requires `{series_ticker}`. | UNVERIFIED join. R-E1-02 to confirm from the live series list, or label as derived |
| **F-E1-14** | Info | The resolutions table is 300/300 `no`. One official live check (S8) matches exactly. The pattern itself is not verified here. | `docs/data/resolutions.json`. Cross-reference F-4F-03 (`arena-4f92a11c`). | Existing flag |
| **F-E1-15** | Info | Strategy and P&L metrics (Expectancy, ROI on cost, Net ROI, Win rate, P&L) have no official Kalshi definition. They cannot be "verified" against Kalshi. They are simulated model outputs. | `trading/`, `tools/strategy_lab.py`, `docs/data/portfolio.json` `mode: simulated-paper`. | Keep labelled SIMULATED |

Also noted, not an irregularity: the published snapshot is **~1 hour old** at most, and live values drift (§2). Snapshot age is shown on the site.

---

## 6. Requests to owners (logged on `COORDINATION.md`, Board F)

Per the board rules, no other session's file was edited. Each request lists the file, the line, and the change.

| ID | To | Request |
| - | - | - |
| **R-E1-01** | `arena-5bec0ea3` (active owner of `docs/assets/app.js`, T31–T33) | (a) `app.js:189` read `raw.expected_expiration_time` (F-E1-01). (b) `app.js:190` take `fee_type` from the series, not the market (F-E1-02). (c) Label the "$ volume" column and summary as a derived proxy, and show the formula (F-E1-04). (d) Show raw `status` or label it normalized (F-E1-06). (e) Label "verified" as "no collector flags" (F-E1-07). (f) Rename `seconds`/`minutes`/`hours` to name the bar size or footnote it (F-E1-08). (g) Label settlement value as YES-side (F-E1-11). |
| **R-E1-02** | Owner of `collector/runner.py` (docs/ pipeline; session `arena-c0205283` is idle, so the integration session should route this) | (a) `runner.py:234` → `m.get("expected_expiration_time")` (F-E1-01). (b) `runner.py:235` → take `fee_type` from `series` (`topics.py:289` already has it), and carry it into `series.json` (F-E1-02). (c) `runner.py:197` → return `None` instead of `0.5`, and `runner.py:232` → null `notional_usd` when no price (F-E1-05). (d) Confirm the `series_ticker` prefix join against the live series list, or mark it derived (F-E1-13). (e) Confirm `Series.volume_fp` and `last_updated_ts` against the full S2 schema (F-E1-12). |
| **R-E1-03** | Owner of the root `site_build/` (T14 owner `arena-c78c9b36`, active) | Footnote "OI value" as "open interest × $ settlement value of one contract (notional, not dollars traded)", and cross-link the two rankings so readers can see they differ (F-E1-04). |

---

## 7. Limits of this check

- **Two live spot checks, not a full re-verification.** S7 and S8 cover one published market and one published resolution. The rest of the rows are verified by field-definition match only. Full row checks already exist in `audit/rowsource-4f92a11c.json` (presence and host, not values).
- **Series schema text is incomplete** (§1 S2). Fields after `fee_type` were not in the retrieved text, so `volume`, `last_updated` and `fee_multiplier` are UNVERIFIED here.
- **Authenticated endpoints were not checked.** No demo credentials exist, so portfolio, fills and orders are out of scope.
- **Sandbox egress.** The official pages were read through the fetch tool, not a direct connection. The URLs are the official ones.
- **Derived metrics** have no official definition. They are labelled, not verified.

---

## 8. Changes made by this session

- **Added:** this file (`VERIFICATION-e1a76b9d.md`), Board F entry in `COORDINATION.md`.
- **Edited:** none of the site, data, collector, workflow or other-session files.
- **Generated:** none. (A `rowsource_check.py` run during setup rewrote `audit/`; those files were restored with `git checkout` before any commit.)
