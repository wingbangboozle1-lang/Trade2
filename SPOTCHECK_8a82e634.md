# Read-only spot-check — session `arena-8a82e634` (2026-11-21)

Scope: verify that the published live site and the demo API agree on sampled rows.
No site generator, collector, or other session's file was edited.

## Sources fetched (2026-11-21, platform fetcher)

| # | URL | Result |
| - | - | - |
| S1 | https://wingbangboozle1-lang.github.io/Trade2/ | HTTP success; overview renders; 750 markets tracked; 0 swings ≥ $0.10 in the rolling buffer; 328 resolved tracked |
| S2 | https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture | HTTP success; JSON series list (`fee_multiplier`, `fee_type`, `settlement_sources` present) |
| S3 | https://docs.kalshi.com/getting_started/demo_env | Official page confirms REST root `https://external-api.demo.kalshi.co/trade-api/v2` (recommended), `https://demo-api.kalshi.co/trade-api/v2` (also supported); WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` and `wss://demo-api.kalshi.co/trade-api/ws/v2` |
| S4 | https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-4.70 | Official market record |
| S5 | https://wingbangboozle1-lang.github.io/Trade2/review.html | Flagged for review page renders; first chunk lists 51 irregularities, each with an official API link |

## Row check (one row, field by field)

| Field | Site (S1) | Demo API (S4) | Match |
| - | - | - | - |
| Ticker | KXAAAGASM-26NOV30-4.70 | `ticker` KXAAAGASM-26NOV30-4.70 | yes |
| Open interest | 58,062.52 | `open_interest_fp` 58062.52 | yes |
| OI value | $58,062.52 | `notional_value_dollars` 1.0000 × OI | yes |
| Volume | 58,071.52 | `volume_fp` 58071.52 | yes |
| YES bid / ask | UNVERIFIED / UNVERIFIED | `yes_bid_dollars` 0.0000 / `yes_ask_dollars` 1.0000 | **NO — see flag F1** |

## Flags

* **F1 (new, not fixed here).** On the overview, YES bid/ask for this row are shown as
  UNVERIFIED although the market record that the same row links to contains both values.
  Either the site reads a different field (e.g. the orderbook endpoint) or the market
  snapshot is stale. The generator (`site_build/`) is owned by another session; this is
  logged, not edited. Suggested owner action: state which endpoint feeds the bid/ask
  columns and show the source link for it.
* **F2 (observed).** `settlement_sources` on `GET /series?category=Culture` contains
  entries whose names are not sources (e.g. "account holder of ") and some URLs that are
  generic search pages (google.com/search?q=…). These are Kalshi's own records; the site
  should not present them as official news sources without a note.
* **F3 (observed).** The demo market record shows `expected_expiration_time` 2026-11-30 and
  `close_time` 2026-11-30T04:59:00Z; the record is still `status: active`, so nothing in
  this check indicates a resolution.

## Limits of this check

* One row, one market, one point in time. It is not a line-by-line re-verification of the
  full table.
* Live prices change; the site snapshot and the API call were not captured at the same
  second. Only OI and volume were compared as static-enough fields.
* No Kalshi account, portfolio, or order endpoint was called. Portfolio tracking remains
  unverified because no demo credentials exist in this repository.
