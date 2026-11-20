# T-FEFA-1 — F-07 confirmation and row spot-check (`arena-fefa9b72`)

Checked: 2026-11-20 ~20:30 UTC. Branch `arena/fefa9b72-trade2`. Read-only: no product code, flags, workflows, or generated data were changed.

## 1. F-07 — is the published snapshot demo-only?

F-07 (`config/flags.json`): "Prior snapshot may contain production data until demo refresh succeeds". The flag asks to inspect `source.base_url` and `generated_at` in the published data.

| Published file (main) | `base_url` / host evidence | Timestamp | Result |
| --- | --- | --- | --- |
| `kalshi-dashboard/data/latest.json` | `source.base_url` = `https://external-api.demo.kalshi.co/trade-api/v2`; 332 markets | `generated_at` 2026-11-20T19:55:06.384Z | Demo |
| `docs/data/run_meta.json` | `base_url` = demo host; 40 markets, 300 resolutions | `finished_at` 2026-11-20T19:44:12Z | Demo |
| `docs/data/markets.json` (40 rows) | every `source_url` on `external-api.demo.kalshi.co` | `generated_at` 2026-11-20T19:44:12Z | Demo |
| All `docs/data/*.json` and `data/*.json` | zero occurrences of `api.elections.kalshi.com` or `trading-api.kalshi.com` | — | No production host found |

Official demo hosts confirmed on the Kalshi API environments page: [API environments](https://docs.kalshi.com/getting_started/api_environments) and [Demo environment](https://docs.kalshi.com/getting_started/demo_env). The demo REST root `https://external-api.demo.kalshi.co/trade-api/v2` returned `exchange_active: true` on `/exchange/status` when fetched during this session.

**Finding:** the published data is demo-sourced. The prior-production concern in F-07 is resolved on the evidence. Flag status should be closed by the owner of `config/flags.json` (see request R-FEFA-1 in `COORDINATION.md`). This session did not change the flag.

**Caveat:** the `kalshi-dashboard` snapshot was generated at 19:55Z and the `docs/` snapshot at 19:44Z. Newer collector runs on main (for example 20:28:55Z) did not update those files. The "demo" label is correct, but the age of the data is not 5 minutes. See R-DC-3 and R-DC-4 in the board.

## 2. Spot-check against the official demo API (line by line)

Each published row was compared with `GET https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}` fetched during this session. The official field names are from the [Get Market](https://docs.kalshi.com/api-reference/market/get-market) reference.

| Topic | Ticker | Published (`docs/data/markets.json`) bid / ask / last | Official `yes_bid_dollars` / `yes_ask_dollars` / `last_price_dollars` (fetched) | Official source link | Result |
| --- | --- | --- | --- | --- | --- |
| golf | KXPGATOUR-THRC26-MMEI | 0.002 / 0.003 / 0.003 | 0.0020 / 0.0030 / 0.0030 | [link](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-MMEI) | Price match. `expected_expiration` published blank, but official `expected_expiration_time` = 2026-11-22T00:00:00Z — **blank despite an official value** (flag). |
| elections | KXPRESNOMD-28-WM | 0.025 / 0.028 / 0.028 | 0.0250 / 0.0280 / 0.0280 | [link](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-WM) | Price match. |
| culture | KXTIME-26-PET | 0.01 / 0.02 / 0.03 | 0.0100 / 0.0200 / 0.0300 | [link](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXTIME-26-PET) | Price match. |
| gas-prices | KXAAAGASW-26NOV23-3.6400 | **0.0 / 0.08 / 0.08** | **0.0200 / 0.0300 / 0.0300** (official `updated_time` 2026-11-15T21:34:40Z; `previous_yes_ask_dollars` 0.0800) | [link](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) | **Mismatch** — published values equal the official *previous* ask, not the current quote. Cannot tell from one sample whether the snapshot is stale or the row is mis-mapped. Flag. |
| crypto | KXBTCMINY-27JAN01-40000.00 | 0.06 / 0.07 / 0.07 | 0.0600 / 0.0700 / 0.0700 | [link](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCMINY-27JAN01-40000.00) | Price match. |

Other observations across the sample:

- **Status label:** every published row says `open`. The official responses for the five fetched markets say `active`. The status enum in the Get Market reference was not fully visible in the fetched chunk, so the mapping is **unverified**, not declared wrong. Flag.
- **Field name:** the published column `expected_expiration` does not appear in the official schema. The official field is `expected_expiration_time`. The mapping needs review. Flag.
- **Volume and open interest drift:** golf `volume_fp` 495557.75 published vs 495742.28 official; `open_interest_fp` 347551.77 vs 347736.30. This is consistent with snapshot timing (19:44Z vs fetch time) and is not treated as an error.
- **Fee type:** `fee_type` is null on all 40 published rows. The fetched official market objects contain no `fee_type` field, so the blank is correct and stays flagged.

## 3. Published-data summary (40 rows)

- `status`: `open` 40/40 (see status note above).
- `expected_expiration`: null 40/40 (official field exists — flagged).
- `fee_type`: null 40/40 (absent from official object — stays blank).
- Topics: golf 8, elections 8, culture 8, gas-prices 8, crypto 8.
- Every `source_url` is on the demo host.

## 4. Irregularities for the Flagged for Review page

| ID | Irregularity | Source | Severity |
| --- | --- | --- | --- |
| FEFA-1 | Gas-prices row KXAAAGASW-26NOV23-3.6400 shows bid 0.0 / ask 0.08, but the official current quote is 0.02 / 0.03 (official `previous_yes_ask` = 0.08). | [official market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) | High (wrong value on a trader-facing row) |
| FEFA-2 | `expected_expiration` published blank 40/40, but official `expected_expiration_time` is populated for the sampled markets (e.g. KXPGATOUR-THRC26-MMEI = 2026-11-22T00:00:00Z). | [Get Market](https://docs.kalshi.com/api-reference/market/get-market) | Medium |
| FEFA-3 | Published `status` = `open` for all rows; official responses show `active`. Mapping unverified against the status enum. | [Get Market](https://docs.kalshi.com/api-reference/market/get-market) | Low (label) |
| FEFA-4 | F-07 can be closed on evidence (demo host + demo timestamps). Flag owner to decide. | [API environments](https://docs.kalshi.com/getting_started/api_environments), [Demo environment](https://docs.kalshi.com/getting_started/demo_env) | Info |
| FEFA-5 | Published snapshot age: docs/ at 19:44Z, kalshi-dashboard/ at 19:55Z, while main collector runs continue. Stale-by-design for the `kalshi-dashboard` pipeline until R-DC-3/R-DC-4 are fixed. | `docs/data/run_meta.json`, `kalshi-dashboard/data/latest.json`, [run list](https://github.com/wingbangboozle1-lang/Trade2/actions) | Medium |

## 5. Limits

- Sample size is 5 of 40 `docs/` rows (one per topic plus the gas row). Results are not a full line-by-line re-verification of all rows.
- Official data was fetched at about 20:30 UTC. Published values are from 19:44Z. Price drift is expected and was not counted as an error except where the published value matches neither the current nor any obvious earlier official state (FEFA-1).
- No demo account, orders, or fills were checked; no credentials are configured in this session.
