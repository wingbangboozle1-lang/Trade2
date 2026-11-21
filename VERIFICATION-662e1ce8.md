# VERIFICATION-662e1ce8 — R-F3-1 trade-price corroboration

Session `arena-662e1ce8` · branch `arena/662e1ce8-trade2` · task Y1–Y4 in
`COORDINATION.md` (section keyed by session id). Scope: `collector/alerts.py` and a new regression
test module. Every claim below is mapped to the official Kalshi documentation
page that defines the field or endpoint it depends on. Nothing is inferred.

## 1. What changed

The swing detector (`collector/alerts.py`) compares two **quote mids**. A quote
mid can move on a single stray, un-arbitraged level with no trade behind it —
the artefact class recorded for `KXPRESNOMD-28-BOBA`, whose candle bar
`1795237200` shows a `yes_ask.close` of `0.8820` against a trade price of
`0.0050`. The candlestick schema also publishes the bar's trade price, so the
detector now cross-checks the reference quote mid against it and refuses a
candidate swing the trade price does not corroborate. The refusal is published
(returned through `swing_rejection()`, never hidden), consistent with the
repo's existing "publish the refusal" rule.

Changes, all in `collector/alerts.py`:

| # | Change | Official source |
| - | ------- | --------------- |
| C1 | New `Observation.ref_previous_dollars` field, populated in `observe()` from `reference["previous_dollars"]`. This maps to the candle's documented `price.previous_dollars`. | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) — response schema: `"price": { "previous_dollars": "0.5600", ... }` |
| C2 | New constant `REFERENCE_TRADE_TOLERANCE = SWING_THRESHOLD` (0.10 USD), so the corroboration gap is measured on the same scale as the alert rule. | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) (`price.previous_dollars`, `price.close_dollars`); the $0.10 threshold is the project brief's `SWING_THRESHOLD` |
| C3 | In `_swing()`, when the reference is a candle quote (`basis == "candle_quote_mid"`), the reference mid is compared with the bar's trade price (`price.previous_dollars` if present, else the already-populated `price.close_dollars`). A gap ≥ the tolerance refuses the swing with a precise reason; the record carries `trade_price`, `trade_price_basis`, `trade_price_gap`, `corroboration="uncorroborated"`. | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) (trade price fields); the quote-mid rule is the repo's documented alert basis |
| C4 | When the trade price agrees, the alert record carries `trade_price`, `trade_price_basis`, `trade_price_gap` and `corroboration="corroborated"` for transparency. | same as C3 |
| C5 | The guard is deliberately **not** applied to the `previous_snapshot_mid` basis: that fallback carries no candle trade price, so it is left untouched. | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) — the trade price only exists on a candle |

## 2. Verification performed (all local, offline)

| Check | Command | Result |
| ------ | ------- | ------ |
| Import + constant | `python3 -c "import collector.alerts; ..."` | import ok, `REFERENCE_TRADE_TOLERANCE == 0.1` |
| New regression tests | `python3 -m unittest tests.test_trade_corroboration_662e1ce8 -v` | **7 OK** |
| Full Python suite | `python3 -m unittest discover -s tests` | **268 OK**, 12 skipped (was 261 OK before the 7 new tests) |
| JS suite | `npm test` | **29/29** |
| Internal links | `python3 tools/linkcheck.py` | **50 pages / 679 links / 0 errors** |
| Site build | `python3 -m site_build.build` | clean (generated pages reverted afterward — see §4) |
| Collector end-to-end (captured payloads) | `python3 -m collector.test_runner` | **PASS** (7 series / 7 markets / 7 books / 7 alerts / 1 resolution) |
| Trading engine | `python3 -m trading.test_engine` | **ALL TRADING TESTS PASSED** |

The new tests pin:

1. a tight reference quote mid not corroborated by the trade price is refused
   at the source (`KXPRESNOMD-28-BOBA`-class artefact);
2. `price.previous_dollars` is preferred over `price.close_dollars`;
3. `price.close_dollars` is the fallback basis;
4. a trade-corroborated swing still alerts and is labelled `corroborated`;
5. the previous-snapshot fallback is unchanged (`corroboration` is `None`);
6. a sub-threshold move produces neither an alert nor a refusal;
7. the tolerance boundary (`== 0.10` refuses, `0.099` does not).

## 3. Official sources

| Claim | Source URL | What it confirms |
| ----- | ---------- | ---------------- |
| `price.previous_dollars`, `price.close_dollars` exist on a candle | https://docs.kalshi.com/api-reference/market/get-market-candlesticks | The candlestick response schema contains `"price": { "previous_dollars", "close_dollars", ... }` and the `yes_bid`/`yes_ask` blocks with `close_dollars`. Fetched 2026-11-21. |
| The reference must be a quote mid, not a last-trade price | https://docs.kalshi.com/getting_started/orderbook_responses | The existing quote-mid basis (bid/ask) the corroboration guard protects. |
| The $0.10 swing threshold | project brief / `SWING_THRESHOLD` in `collector/alerts.py` | The alert threshold the corroboration tolerance is aligned to. |
| Demo REST/WS endpoints | https://docs.kalshi.com/getting_started/demo_env | The environment this detector runs against (unchanged by this task). |

## 4. Irregularities and limitations (logged, not silently fixed)

| ID | Observation | Handling |
| -- | ----------- | -------- |
| F-662E-1 | The `KXPRESNOMD-28-BOBA` example is refused by the **reference-spread** check before the corroboration guard is reached (its reference spread is 0.8810, already ≥ `ALERT_MAX_SPREAD`). The corroboration guard therefore catches the *tight-quote-but-uncorroborated* sub-class, not BOBA itself. | Logged honestly. Both rules refuse the move; the corroboration reason is the more specific one for references that clear the spread check. No behaviour change for BOBA. |
| F-662E-2 | The collector's `bar_reference()` (`collector/collector.py`) does not yet populate `previous_dollars`, so in production the guard currently runs on `price.close_dollars`. | `collector/collector.py` is claimed by open PR #59 (`arena/bbfedfd5-trade2`); per the board rule this session logged request **R-662E-1** instead of editing it. The guard is fully active today on `price.close_dollars`, which is the same candle trade price. |
| F-662E-3 | The guard can, in principle, refuse a genuine quote-driven move on an illiquid market whose reference bar's `price.close_dollars` is a stale carried-forward trade. | Only the candle basis is gated, the gap must be ≥ the $0.10 threshold, and every refusal is published via `swing_rejection()` rather than hidden. Recorded as a limitation; not worked around. |
| F-662E-4 | `python3 -m site_build.build` regenerated the root `*.html` pages with a new snapshot-age string (time drift only). | Reverted with `git checkout -- '*.html'`; the commit is scoped to `collector/alerts.py` + the new test. |
