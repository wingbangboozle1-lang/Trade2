# Kalshi demo tracker

A static, GitHub Pages-ready tracker for Kalshi **demo**-market data across gas prices, elections,
culture, crypto and golf. Plain HTML/CSS/JavaScript — no build step, no server, no credentials.

Live site: <https://wingbangboozle1-lang.github.io/Trade2/>

## What is in this repository

Two independent implementations of the same brief were built in parallel sessions and are both
published. Neither replaces the other.

| Path | What it is | Data source |
| --- | --- | --- |
| `index.html` | Landing page, executive summary and live findings | committed snapshot |
| `docs/dashboard.html` | Full dashboard: two scrolling chats, swing alerts, interactive charts, orderbook ladders | committed snapshot |
| `docs/topics/*.html` | One page per topic (gas, elections, culture, crypto, golf) | committed snapshot |
| `docs/trading.html` | Strategies, simulated portfolio, derived strategy groups, trade log | committed snapshot |
| `docs/methodology.html` | Requirement traceability, swing rule, ROI specification, verification log, data contract | — |
| `docs/flagged.html` | Every unverified value and irregularity, each with the source needed to review it | — |
| `live/` | The sibling session's **browser-polling** dashboard: overview, topic pages, summary, review | direct from the visitor's browser |
| `pipeline/` | Node collector: discovery, orderbooks, candles, trade feed, swing alerts, paper trading | public Kalshi demo REST API |
| `tools/` | Site link/asset checker and page render smoke test | — |

The snapshot-driven site works without any browser CORS permission and keeps its data across
reloads. The browser-live site is more immediate but depends on the browser being allowed to call
Kalshi directly; the collector measures that permission on every run and publishes the verdict in
`docs/data/collector-health.json`.

## How the data flows

1. `.github/workflows/collect.yml` runs every 10 minutes on GitHub Actions.
2. `pipeline/src/collect.js` reads the public Kalshi demo REST API — no credentials required.
3. The snapshot is committed to `docs/data/*.json`; GitHub Pages serves the result.
4. The site renders that snapshot. No manual step, no server, no API key.

## Run locally

Serve the repository root over HTTP (not `file://`) so relative links and `fetch` calls resolve:

```bash
python3 -m http.server 8000     # then open http://localhost:8000/
```

Run the collector locally with `cd pipeline && npm install && npm run collect`. It needs no
credentials and writes to `docs/data/`. Run the tests with `cd pipeline && npm test`.

## Important limitations

- **No Kalshi account is connected.** Demo signup requires an email inbox that can receive a
  verification message, which is unavailable here. The signed order client
  (`POST /portfolio/events/orders`) and the account portfolio readers are implemented and
  unit-tested against the documented request format, but have never run against a real account.
  Every performance figure on the site comes from the **simulated** engine and is labelled as such.
- **No production trading and no real-money implications.** Nothing here places a real order.
- **Kalshi's `category` filter on `GET /events` is ignored by the service** (verified live), so
  topic classification is performed locally from series and market titles. Kalshi's own category
  strings are stored exactly as returned and are never edited.
- **Simulated fills ignore fees, slippage, order queueing and partial fills**, and are gross of the
  published fee schedule.
- **The ROI model is a documented, unvalidated heuristic** — a transparent weighted sum of five
  public inputs, not a forecast and not advice.
- **A swing's cause is not automatically verifiable.** The site links the official settlement
  sources Kalshi publishes for the event and never asserts a headline caused a move.
- **Values that cannot be officially confirmed are left blank and flagged**, never inferred.
- **Demo pricing and behaviour may differ from production** (Kalshi's own caveat). Demo tickers
  include demo-only strike names.

Every item above is published with its official source on the site's
[Flagged for review](https://wingbangboozle1-lang.github.io/Trade2/docs/flagged.html) page.

## Official sources

- [Demo environment, recommended URLs and mock-funds disclaimer](https://docs.kalshi.com/getting_started/demo_env)
- [API environments and endpoint list](https://docs.kalshi.com/getting_started/api_environments)
- [API keys and request signing](https://docs.kalshi.com/getting_started/api_keys)
- [Events API, nested markets and cursor pagination](https://docs.kalshi.com/api-reference/events/get-events)
- [Markets API fields](https://docs.kalshi.com/api-reference/market/get-markets)
- [Orderbook response semantics](https://docs.kalshi.com/getting_started/orderbook_responses)
- [Candlesticks API](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [Trades feed](https://docs.kalshi.com/api-reference/market/get-trades)
- [WebSocket quick start](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Market settlement](https://docs.kalshi.com/getting_started/market_settlement)

See `docs/methodology.html` for the row-by-row source register and `docs/flagged.html` for the
flagged limitations. `COORDINATION.md` records the task board, the published data contract, the
verification log and the pull-request/deployment results.
