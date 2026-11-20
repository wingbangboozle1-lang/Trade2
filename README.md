# Trade2 — Kalshi Demo Dashboard

Live dashboard for the **highest-dollar-volume events on the Kalshi demo exchange**, limited to five topics:
**gas prices · elections · culture · crypto · golf**.

**Live site:** https://wingbangboozle1-lang.github.io/Trade2/

## What's here

| Path | Purpose |
|---|---|
| `collector/` | Pulls the public demo REST API (markets, series, order books, candlesticks, settlements) and writes `docs/data/*.json`. Topic matchers in `collector/topics.py`. |
| `trading/` | Automated **simulated** trading engine: official fee formula, three strategies, settlement grading, stats by strategy & trade type. |
| `docs/` | The GitHub Pages site: landing page, one subpage per topic, portfolio, executive summary, **Flagged for Review**. |
| `docs/verification/` | Verification ledger — every published claim mapped to an official source URL. |
| `live/server.py` | Optional local server: serves the site with a 5s SSE live stream straight from the demo API. |
| `.github/workflows/collector.yml` | Tests on every push; live collection + data commit every 15 minutes (schedule) or on manual dispatch. |
| `COORDINATION.md` | Shared task board for parallel sessions (claims, status, log, PR record). |
| `EXECUTIVE_SUMMARY.md` | Executive summary of endpoints, rules, model and gaps. |

## Data pipeline

```
GitHub Actions (*/15 min)  →  collector.runner  →  docs/data/*.json  →  trading.engine  →  portfolio.json
                                        ↓
                        GitHub Pages site (polls JSON every 20s)
```

Every table row on the site links the exact official API endpoint it came from. Values that cannot be
confirmed from an official source are left **blank** and flagged — never inferred.

## Run locally

```bash
python3 -m collector.runner            # one collection pass (needs network egress)
python3 -m trading.engine              # simulated trading cycle against collected data
python3 live/server.py                 # site + 5s live stream on http://localhost:8080
```

## Tests (also run in CI before any data is published)

```bash
python3 -m trading.test_engine    # fee formula vs all 42 rows of the official PDF table + engine rules
python3 -m collector.test_runner  # end-to-end collector on real captured API payloads
npm install && python3 test/gen_fixtures.py /tmp/fx && node test/site_smoke.mjs /tmp/fx   # jsdom UI smoke
```

## Key official sources

- Demo REST: `https://external-api.demo.kalshi.co/trade-api/v2` — [docs](https://docs.kalshi.com/getting_started/demo_env)
- Demo WebSocket: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` — [docs](https://docs.kalshi.com/getting_started/quick_start_websockets)
- Fee schedule (PDF, eff. 2026-07-07): https://kalshi.com/docs/kalshi-fee-schedule.pdf
- Settlement rules: https://docs.kalshi.com/getting_started/market_settlement

Full claim-by-claim ledger: [`docs/verification/sources.md`](docs/verification/sources.md) ·
Open items: [Flagged for Review](https://wingbangboozle1-lang.github.io/Trade2/flagged.html)

> Simulated trading only — no API credentials exist in this project (FL-01), no orders are sent, and demo
> prices may not reflect real markets. Not investment advice.
