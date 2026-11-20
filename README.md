# Trade2 — Kalshi demo monitoring desk

A live monitoring dashboard for **Kalshi's demo environment** covering five
topics only — gas prices, elections, culture, crypto and golf.

**Live site:** <https://wingbangboozle1-lang.github.io/Trade2/>

## What it does

| Capability | Status |
| - | - |
| Highest-dollar open events per topic, ranked by official open-interest value | live |
| Alert on any price swing ≥ **$0.10** either way, as two scrolling chats (all events, model shortlist) | live |
| Price graph with seconds / minutes / hours windows and live order-book depth (contracts at each price) | live |
| Event tracked until it resolves, with the official YES/NO result and settlement value | live |
| Automated simulated trading with four named strategies, scored by strategy, topic and outcome | simulated |
| Placing orders on a demo account | implemented, inert without credentials |

## How to run it

```bash
python3 -m collector.collector      # one collection pass -> data/live.json
python3 -m site_build.build         # regenerate every page from that snapshot
python3 server/app.py               # local dashboard on :8000 (serves the site + SSE)
python3 -m unittest discover -s tests -v
python3 tools/linkcheck.py          # fail on a broken internal link
```

The Python collector, site builder, and Python unit tests have no third-party
requirements; `cryptography` is needed only for signed requests. `npm test`
uses Node's built-in test runner and does not require `npm ci`.

The browser-like UI render/smoke checks use `jsdom`. For jsdom 31, use Node
22.22.2 or later in the 22.x line, 24.15.0 or later in the 24.x line, or
26.0.0 or later. Install the test dependency before running `npm run test:site`,
`node test/root_render.mjs`, `node tools/rendercheck.mjs`, or
`node tests/test_docs_live.mjs`:

```bash
npm ci
```

## Optional: enable real demo trading

The simulator is used unless credentials exist. To switch the order adapter on:

```bash
export KALSHI_API_KEY_ID=<key id from Account & security -> API Keys>
export KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi-key.pem
export KALSHI_ENV=demo
```

Signing follows the [official guide](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md).

## Documents

* [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) — what this is, with every source linked
* [VERIFICATION.md](VERIFICATION.md) — line-by-line check log
* [REQUIREMENTS.md](REQUIREMENTS.md) — requirement → implementation → evidence
* [COORDINATION.md](COORDINATION.md) — shared task board across sessions
* [methodology.html](methodology.html) — the published rules
* [review.html](review.html) — flagged irregularities and unverified items

## Guardrails

Every value shown comes from a documented Kalshi endpoint and links to it.
Unverifiable values are blank and labelled **UNVERIFIED** — never inferred.
Paper trades are labelled SIMULATED everywhere they appear.

---

## Second implementation (session `arena-c0205283`, PR #11)

A parallel, independently verified implementation lives alongside the desk above.
It keeps its site under `docs/` so root files owned by other sessions are never
touched: **<https://wingbangboozle1-lang.github.io/Trade2/docs/>**.

| Path | Purpose |
|---|---|
| `collector/` (client.py, runner.py, news.py, kalshi.py) | Pulls the public demo REST API (markets, series, order books, candlesticks, settlements) and writes `docs/data/*.json`. Topic matchers in `collector/topics.py` (shared module — both pipelines import it). |
| `trading/` | Automated **simulated** trading engine: official fee formula, three strategies, settlement grading, stats by strategy & trade type. |
| `docs/` | GitHub Pages site: landing page, one subpage per topic, portfolio, executive summary, **Flagged for Review** (`docs/flagged.html`). |
| `docs/verification/` | Verification ledger — every published claim mapped to an official source URL. |
| `live/server.py` | Optional local server: serves `docs/` with a 5s SSE live stream straight from the demo API. |
| `.github/workflows/collector.yml` | Tests on every push; live collection + data commit every 15 minutes (schedule) or on manual dispatch. |

```bash
python3 -m collector.runner            # one collection pass (needs network egress)
python3 -m trading.engine              # simulated trading cycle against collected data
python3 live/server.py                 # docs/ site + 5s live stream on :8080
python3 -m trading.test_engine         # fee formula vs all 42 official table rows
python3 -m collector.test_runner       # end-to-end collector on captured API payloads
npm run test:site                      # jsdom UI smoke against docs/data
```

Full claim-by-claim ledger for this implementation: [`docs/verification/sources.md`](docs/verification/sources.md) ·
Flagged items: [`docs/flagged.html`](docs/flagged.html)

