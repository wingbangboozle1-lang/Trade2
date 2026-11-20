# Executive summary — Kalshi demo tracker (Trade2)

**Scope.** A live dashboard for the highest-dollar live events on the **Kalshi demo exchange**,
restricted to five topics: **gas prices, elections, culture, crypto and golf**. It alerts on any
contract price swing of **$0.10 or more** in either direction, shows liquidity depth, ranks
markets with an explainable ROI model, and runs fully automated **simulated** trades whose
performance is tracked until each market resolves.

**Data source (official).**

| Surface | Endpoint | Source |
| --- | --- | --- |
| REST Trade API | `https://external-api.demo.kalshi.co/trade-api/v2` | https://docs.kalshi.com/getting_started/demo_env |
| REST (also supported) | `https://demo-api.kalshi.co/trade-api/v2` | https://docs.kalshi.com/getting_started/demo_env |
| WebSocket API | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | https://docs.kalshi.com/getting_started/quick_start_websockets |
| WebSocket (also supported) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | https://docs.kalshi.com/getting_started/quick_start_websockets |

Public market data needs no authentication. Authenticated calls (order placement, account
portfolio) need an API key id plus a private key, signed as
`timestamp + METHOD + path` with Ed25519 or RSA-PSS/SHA-256
(https://docs.kalshi.com/getting_started/api_keys).

**How it runs — no manual input anywhere.**

1. `pipeline/src/collect.js` reads the public demo REST API: series discovery
   (`GET /series`), live markets (`GET /markets`), orderbooks (`GET /markets/{ticker}/orderbook`),
   candles (`GET /series/{series}/markets/{ticker}/candlesticks`), the fill feed
   (`GET /markets/trades`) and event metadata (`GET /events/{event_ticker}`).
2. `.github/workflows/collect.yml` runs it every 10 minutes on GitHub Actions and commits the
   snapshot into `docs/data/`.
3. GitHub Pages serves the static site straight from `docs/`, so the dashboard is always current
   without anyone pressing anything.

**Alerting.** A swing is a move of at least $0.10 (compared in integer cents, so exactly $0.10
qualifies). Two independent references are used: the price difference between two consecutive
fills on the Kalshi trade feed, and Kalshi's own `previous_price_dollars` versus the current
price. Alerts appear in two scrolling chats — one with everything, one filtered by the ROI model
(default threshold 60). Every alert links the Kalshi market page and the official settlement
sources Kalshi publishes for that event; the site never asserts what caused a move.

**ROI model (0–100, published on the site).** Momentum 0–30 (size of the last move),
liquidity 0–25 (size resting within 5¢ of the mid), spread 0–15 (cost of crossing), edge 0–15
(distance from the 30-minute mean), time 0–15 (hours to close). The same inputs produce a fair
YES value and a per-contract expected value. It is a transparent ranking heuristic, not advice.

**Simulated trading.** Four strategies are tested: swing momentum, mean reversion, liquidity
capture, and a model-edge "conviction" strategy driven by the ROI model. The engine backtests on
hourly candles and then trades forward on the live book, marks positions to the live bid, and
settles them at $1/$0 when Kalshi reports a resolution of *yes* or *no*. Results are grouped by
strategy, by topic and by trade type (strategy × topic × side); trade-type groups with at least
three closed trades are published as derived strategies.

**What is deliberately not claimed.** No Kalshi account could be provisioned (demo signup needs
an email inbox that can receive a verification message), so the signed order client and the
account-portfolio readers exist and are unit-tested against the documented request format but
have never run against a real account. Every performance figure on the site comes from the
simulation and is labelled as simulated. Other open items — demo-content differences, the ignored
`category` filter, unconfirmed browser CORS, unmodelled fees and the unvalidated ROI model — are
published on the site's **Flagged for review** page with the source links needed to check them.

**Live site.** https://wingbangboozle1-lang.github.io/Trade2/ (Pages source: `main`, path `/docs`).
