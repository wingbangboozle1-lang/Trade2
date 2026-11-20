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

No third-party packages are needed for the collector, site build or tests.
`cryptography` is only required for signed requests.

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
