# Strategy lab — simulated-trade analysis and reference backtests
_Generated 2026-11-20T19:20:33Z by `tools/strategy_lab.py` from the repo's published simulated-trade data and recorded demo candlesticks. All figures are **computed from simulated/demo data** — not verified live performance, not investment advice. Kalshi's demo environment uses mock funds and its market behaviour may not reflect production ([Demo environment](https://docs.kalshi.com/getting_started/demo_env))._
Fee model used throughout: taker fee = round_up(0.07 * C * P * (1 - P)) to the cent (https://kalshi.com/docs/kalshi-fee-schedule.pdf).
## 1. Data sources (provenance)
| Book | Engine file | Round-trips (closed / open) | Rows carry official source links |
| --- | --- | --- | --- |
| docs-sim book | `docs/data/portfolio.json (roi_edge)` | 1 / 5 | yes |
| root book | `data/live.json portfolio + data/portfolio_state.json` | 0 / 2 | yes |
| kalshi-dashboard book | `kalshi-dashboard/data/trades.json` | 0 / 0 | n/a (no rows) |
## 2. Performance by strategy
| Strategy | Trades | Closed | Open | Wins | Losses | Win rate | Net P&L | Fees | ROI on cost | Max drawdown | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| roi_edge | 6 | 1 | 5 | 1 | 0 | 100.0% | $548.48 | $65.24 | 274.2% | $0.00 | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.50) |
| value | 2 | 0 | 2 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
## 3. Performance by trade type (strategy | signal | side)
| Trade type | Trades | Closed | Open | Wins | Losses | Win rate | Net P&L | Fees | ROI on cost | Max drawdown | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| roi_edge|high-roi-fade|yes | 3 | 1 | 2 | 1 | 0 | 100.0% | $548.48 | $65.24 | 274.2% | $0.00 | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) |
| roi_edge|book-undervalued-no|no | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.50) |
| roi_edge|book-undervalued-yes|yes | 2 | 0 | 2 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMR-28-MR) |
| value|None|yes | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
| value|settlement|yes | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
## 4. Performance by topic
| Topic | Trades | Closed | Open | Wins | Losses | Win rate | Net P&L | Fees | ROI on cost | Max drawdown | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gas-prices | 4 | 1 | 3 | 1 | 0 | 100.0% | $548.48 | $65.24 | 274.2% | $0.00 | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.50) |
| (blank) | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
| crypto | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
| culture | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXRT-FUR-85) |
| elections | 1 | 0 | 1 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMR-28-MR) |
## 5. Performance by book
| Book | Trades | Closed | Open | Wins | Losses | Win rate | Net P&L | Fees | ROI on cost | Max drawdown | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| docs-sim book | 6 | 1 | 5 | 1 | 0 | 100.0% | $548.48 | $65.24 | 274.2% | $0.00 | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.50) |
| root book | 2 | 0 | 2 | 0 | 0 | — | $0.00 | $0.00 | — | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
## 6. Trade ledger (every simulated round-trip)
| Entry ts (UTC) | Book | Ticker | Topic | Strategy | Side | Status | Result | Entry | Exit | Contracts | Net P&L | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| — | root book | KXBTCY-27JAN0100-B87500 | — (unverified) | value | yes | open | open | — | — | 5000.0 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
| 2026-11-20T14:58:49 | docs-sim book | KXAAAGASM-26NOV30-3.50 | gas-prices | roi_edge | no | open | open | $0.50 | — | 400 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.50) |
| 2026-11-20T15:18:44 | docs-sim book | KXRT-FUR-85 | culture | roi_edge | yes | open | open | $0.17 | — | 1176 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXRT-FUR-85) |
| 2026-11-20T15:53:00 | root book | KXBTCY-27JAN0100-B87500 | crypto | value | yes | open | open | $0.04 | — | 5000.0 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B87500) |
| 2026-11-20T16:06:09 | docs-sim book | KXAAAGASW-26NOV23-3.6400 | gas-prices | roi_edge | yes | open | open | $0.02 | — | 10000 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) |
| 2026-11-20T16:06:09 | docs-sim book | KXAAAGASW-26NOV23-3.6400 | gas-prices | roi_edge | yes | closed | win | $0.02 | $0.08 | 10000 | $548.48 | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) |
| 2026-11-20T18:39:58 | docs-sim book | KXAAAGASW-26NOV23-3.6400 | gas-prices | roi_edge | yes | open | open | $0.02 | — | 10000 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6400) |
| 2026-11-20T18:39:58 | docs-sim book | KXPRESNOMR-28-MR | elections | roi_edge | yes | open | open | $0.22 | — | 909 | — | [source](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMR-28-MR) |
## 7. Published-stats cross-check
Discrepancies between the books' published aggregates and a recomputation from their own trade rows — **flagged for review**, not silently reconciled:
| Book | Metric | Published | Recomputed | Source |
| --- | --- | --- | --- | --- |
| docs-sim book | fees (entry+exit) | 51.52 | 65.24 | `docs/data/portfolio.json (roi_edge)` |
## 8. Reference backtests over recorded demo candles
Three deterministic rules replayed over the recorded `docs/data/candles.json` closes. Both stored windows are replayed separately: the `minutes` window (`period_interval=60`, i.e. **hourly** candles) and the `hours` window (`period_interval=1440`, i.e. **daily** candles); per the [official candlestick reference](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) the period is expressed in minutes. Fixed 100 contracts per trade, hold ≤ 12 bars, swing threshold $0.10, taker fees both sides. Every generated row links to its candle API source. These are **model comparisons on recorded demo data** — recorded histories are only 3+ bars long so far and demo behaviour may not reflect production.
| Rule | Trades | Wins | Losses | Win rate | Gross | Fees | Net | ROI on cost | Max drawdown | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| momentum | 1 | 1 | 0 | 100.0% | $5.00 | $1.93 | $3.07 | 3.8% | $0.00 | [source](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASW/markets/KXAAAGASW-26NOV23-3.6200/candlesticks?start_ts=1794940766&end_ts=1795199966&period_interval=1440) |
| mean-reversion | 1 | 0 | 1 | 0.0% | $-5.00 | $1.93 | $-6.93 | -8.6% | $6.93 | [source](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASW/markets/KXAAAGASW-26NOV23-3.6200/candlesticks?start_ts=1794940766&end_ts=1795199966&period_interval=1440) |
| breakout | 0 | 0 | 0 | — | $0.00 | $0.00 | $0.00 | — | — | — (unverified) |
### Backtest trade rows
| Rule | Ticker | Side | Entry ts | Exit ts | Entry | Exit | Contracts | Gross | Fees | Net | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| momentum | KXAAAGASW-26NOV23-3.6200 | yes | 2026-11-19T05:00:00Z | 2026-11-20T05:00:00Z | $0.81 | $0.86 | 100 | $5.00 | $1.93 | $3.07 | [source](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASW/markets/KXAAAGASW-26NOV23-3.6200/candlesticks?start_ts=1794940766&end_ts=1795199966&period_interval=1440) |
| mean-reversion | KXAAAGASW-26NOV23-3.6200 | no | 2026-11-19T05:00:00Z | 2026-11-20T05:00:00Z | $0.81 | $0.86 | 100 | $-5.00 | $1.93 | $-6.93 | [source](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASW/markets/KXAAAGASW-26NOV23-3.6200/candlesticks?start_ts=1794940766&end_ts=1795199966&period_interval=1440) |
## 9. Strategy playbook (rules by trade type)
| Trade type observed | Rule family | Standing rule | Source |
| --- | --- | --- | --- |
| roi_edge|high-roi-fade|yes | book-edge / value | Enter the side whose modelled fair value minus price clears the net-edge threshold after fees, only when the spread is inside the limit and the book shows real depth. | [source](https://docs.kalshi.com/getting_started/demo_env) |
| roi_edge|book-undervalued-no|no | book-edge / value | Enter the side whose modelled fair value minus price clears the net-edge threshold after fees, only when the spread is inside the limit and the book shows real depth. | [source](https://docs.kalshi.com/getting_started/demo_env) |
| roi_edge|book-undervalued-yes|yes | book-edge / value | Enter the side whose modelled fair value minus price clears the net-edge threshold after fees, only when the spread is inside the limit and the book shows real depth. | [source](https://docs.kalshi.com/getting_started/demo_env) |
| value|None|yes | quiet-value | No swing needed; buy the side with the largest modelled edge after fees when the spread is tight and depth is real. | [source](https://docs.kalshi.com/getting_started/demo_env) |
| value|settlement|yes | quiet-value | No swing needed; buy the side with the largest modelled edge after fees when the spread is tight and depth is real. | [source](https://docs.kalshi.com/getting_started/demo_env) |
## 10. Limitations and flagged items
- Sample sizes are small (a handful of simulated round-trips across engines); no statistical ROI claim is made.
- The root book aggregates report `trades: 0` for closed trades while open positions exist; win-rate columns are therefore empty there and left blank rather than inferred.
- Backtests are in-sample on recorded demo candles and are not validated out of sample; they compare rules mechanically, they do not predict performance.
- The candle store's window labels (`minutes`/`hours`) are misleading: the stored `interval` values are 60 and 1440 **minutes** (hourly and daily candles) per the official candlestick reference. Flagged as a data-label quirk; the labels were not changed by this tool.
- Kalshi demo market behaviour may not reflect production ([docs](https://docs.kalshi.com/getting_started/demo_env)).
- Where a row had no official source URL, the cell is blank and marked (unverified); nothing was inferred.
