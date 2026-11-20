# Kalshi Market Desk

A static, GitHub Pages-ready dashboard for monitoring Kalshi demo-market data across gas prices, elections, culture, crypto, and golf. The dashboard is built with plain HTML/CSS/JavaScript and pulls public market snapshots directly from Kalshi’s recommended demo API. It includes source-linked topic tables, local threshold alerts, price history charts, selected-market orderbook depth, an experimental alert shortlist, and a local paper-trading ledger.

## Pages

- `index.html` — overview, live market scanner, alert feeds, chart, depth, and paper strategy lab.
- `categories/*.html` — topic-specific market pages.
- `summary.html` — executive summary, source register, implementation and next-step notes.
- `review.html` — flagged, unverified, and intentionally out-of-scope items.

## Run locally

Open `index.html` from a local static web server (for example `python3 -m http.server 8000`) rather than relying on `file://`; browser cross-origin rules and the Kalshi demo API affect live loading. The dashboard requests `https://external-api.demo.kalshi.co/trade-api/v2` and polls event snapshots every 15 seconds. No example or synthetic market prices are inserted if the API fails.

## Important limitations

- This is a monitor and paper simulator, not a Kalshi account client. It does not place real/demo account orders or retrieve balances/fills. Signed credentials are intentionally not requested or stored in this static site.
- Automatic “Momentum replay” is a locally simulated YES entry on an observed upward move of at least $0.10. Simulated fills ignore fees, slippage, order queueing, and partial fills. The ledger is stored in browser local storage.
- Alerts start after two observed quotes in the current browser and can miss moves between 15-second polls. Price history does not survive outside that browser.
- Topic tags use a transparent local keyword matcher. Only the first four pages of up to 200 open events each are scanned per refresh; this is not a claim of complete market coverage.
- The “Model shortlist” is a preliminary threshold-move plus calculated open-interest value filter, not an ROI model, strategy recommendation, or validated signal. Open-interest value is open_interest_fp × notional_value_dollars (single-contract settlement value), not traded-dollar volume.
- Missing values remain unverified. Demo-market pricing may differ from live markets.

## Official sources

- [Demo environment, recommended URLs and mock-funds disclaimer](https://docs.kalshi.com/getting_started/demo_env)
- [API environments and endpoint list](https://docs.kalshi.com/getting_started/api_environments)
- [Events API, nested markets and cursor pagination](https://docs.kalshi.com/api-reference/events/get-events)
- [Markets API fields](https://docs.kalshi.com/api-reference/market/get-markets)
- [Orderbook response semantics](https://docs.kalshi.com/getting_started/orderbook_responses)
- [WebSocket quick start](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Authenticated demo order quick start](https://docs.kalshi.com/getting_started/quick_start_create_order)

See `summary.html` for the row-by-row source register and `review.html` for flagged limitations.
