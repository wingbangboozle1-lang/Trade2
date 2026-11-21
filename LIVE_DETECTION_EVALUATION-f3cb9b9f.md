# Live-detection evaluation — session `arena-f3cb9b9f`

Scope: how this project can detect a **≥ $0.10 contract-price move** sooner than
the scheduled collector does today, without weakening the rule that an alert
must be a move a trader could actually have transacted in.

Everything below was checked against official sources fetched during this
session. Where a claim is about *our* code, it names the file and function.
Where it is about *Kalshi*, it links the page.

---

## 1. What exists today (measured, not assumed)

| Layer | Cadence | What it measures | Where |
| - | - | - | - |
| Scheduled collector | every 5 min (`*/5`), plus 15 min and 30 min workflows | current book mid vs the **previous completed 1-minute candle's quote closes** | `collector/collector.py:bar_reference`, `collector/alerts.py:_swing` |
| Published snapshot | rewritten by each collector run | that run's alerts | `data/live.json` → `assets/live.json` |
| Browser poll of the snapshot | every 30 s | **re-reads the same snapshot**; it cannot see a new move | `assets/desk.js:pollSnapshot` |
| Live pulse (new, this session) | every 45 s, one request | current book mid vs the mid at the **previous pulse reading** | `assets/live-feed.js`, `assets/desk.js:startLivePulse` |
| WebSocket `ticker` channel | — | not used: the handshake requires `KALSHI-ACCESS-*` headers a browser cannot set | documented on `review.html` |

So before this session the *display* refreshed every 30 s but the *measurement*
refreshed only with the collector. That is the gap the pulse closes.

---

## 2. Why the pulse is safe (it reuses the existing rule)

The pulse does not define a new alert rule. `assets/live-feed.js` implements the
same three checks `collector/alerts.py` implements, with the same constants:

| Check | Collector | Pulse | Official source |
| - | - | - | - |
| best bid = **last** element of the level list | `kalshi_api.best_bid` | `bestBid` | [orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| implied YES ask = `1.00 − best NO bid` | `kalshi_api.implied_yes_ask` | `quoteFromBook` | same page |
| a 0.0000 / 1.0000 pair is **no quote**, never a 0.50 mid | `alerts.observe` | `quoteFromBook` | same page (bids only; a market with no bids has no price) |
| both quotes two-sided and spread **strictly** under $0.10 | `alerts.swing_quotes_ok` | `quotesOk` | project rule, logged in `VERIFICATION_856e184e.md` |
| ≥ 1 contract resting at the level you would trade | `alerts.MIN_ACTIONABLE_SIZE` | `size < 1 → indicative` | book response gives size per level |
| one row per move, not per reading | `alerts` fold by `key` | baseline resets after firing | project rule (R-D-01) |

Node tests: `test/live-feed.test.mjs` (18 cases) — the boundary cases are the
strictly-below-spread case at 0.0999 vs 0.10, the phantom-0.50 case, the
one-sided refusal, and "a sustained move does not re-fire".

---

## 3. The finding that changes what a trader should do (F-01)

**The $0.10 threshold is not the same distance on every market.**

A contract quoted 0.02 / 0.03 has a **one-cent spread**. For its mid to move
$0.10 it must move about **ten ticks** — a real repricing. A contract quoted
0.00 / 0.50 has a **fifty-cent spread** (the demo has many: `KXPERFORM…` rows
today publish bid $0.01 / ask $1.00). Ten cents there is **one tick**.

The project already refuses to call a wide-spread move *executable*
(`quality == "indicative"`). What it does not do — and what no page states — is
show the threshold in the units a trader thinks in. Two published fields make
that possible with no new data:

```
ticks needed to move $0.10  =  ceil(0.10 / price_step)     # price_ranges[].step
$0.10 as a share of the market =  0.10 / (mid × (1 − mid))  # max at 0.50, min at the tails
```

Both are derived from fields already in `GET /markets/{ticker}`
(`price_ranges[0].step`, documented on
[Get Market](https://docs.kalshi.com/api-reference/market/get-market)) and from
the mid we already publish. Recommendation: show "≈ N ticks" on alert rows, and
sort/flag by it. **Not implemented in this session** — it needs a per-row source
link for `price_ranges` and a schema change to the collector payload owned by
other sessions. Logged as a request, not silently done.

Worked examples from today's snapshot (values verified live this session):

| Market | Quote | Spread | Mid | Ticks per $0.10 | Step | Source |
| - | - | - | - | - | - | - |
| `KXPRESNOMD-28-RW` | 0.0380 / 0.0390 | $0.001 | 0.0385 | **100 ticks** | 0.0010 | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW) |
| `KXPRESNOMD-28-EWAR` | 0.0000 / 0.0100 | $0.01 | — (one-sided) | 10 ticks | 0.0100 | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-EWAR) |
| `KXPERFORMBONDSONG-35-COL` | 0.0100 / 1.0000 | $0.99 | 0.505 | 1 tick (wide book) | 0.0100 | [market](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPERFORMBONDSONG-35-COL) |

Read that table again: the **largest open-interest market in the demo** needs a
hundred-tick move to fire a $0.10 alert, while a dead book fires on one tick.
A dashboard that ranks by open-interest value and alerts at a flat $0.10 is
therefore comparing incomparable things. This is the single most useful change
available, and it is a display change, not a data change.

---

## 4. Better reference than a 1-minute candle (F-02)

`collector/collector.py:bar_reference` asks for `period_interval=1`. The docs
allow exactly `1`, `60`, `1440` minutes
([candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)),
so one minute is the finest official bar — it cannot be shortened further.

But a 1-minute candle's `yes_bid.close` is an **instantaneous quote**, not a
time-weighted price. Today's `KXPRESNOMD-28-BOBA` candle makes the point: the
bar closed with `yes_bid 0.0010` and `yes_ask 0.8820` — one stray NO bid at
0.118 made a 0.88 ask on a two-cent market. The rule correctly refuses the
resulting $0.877 "move", but it refuses it *at the last possible moment*, after
the number has already been built.

Three options, in increasing robustness:

| Option | What it needs | Verdict |
| - | - | - |
| A. Use `price.previous_dollars` (documented, present on every candle) as a cross-check | nothing new — the field is already in the response | **cheap, recommended**; flag a swing whose direction contradicts the documented previous close |
| B. Use `price.mean_dollars` (documented time-weighted mean) instead of the close | docs list it; needs a field-name audit per response | promising, but changes the measured quantity — needs its own verification |
| C. More/longer candles for coverage | more requests; the run has a 330 s budget and reference bars already take 62 s of a 110 s run | not free; only if A and B prove insufficient |

Option A is a correctness guard rather than a new measurement, which is why it
is the one proposed for adoption. **Not implemented here**: it changes the alert
payload (`collector/alerts.py` is shared with the `docs/` pipeline through the
same module) and every published row would need re-verification. Logged as
`R-F3-1` on the board.

---

## 5. Latency budget, honestly

| Source of delay | Size | Can this project remove it? |
| - | - | - |
| GitHub schedule jitter (`*/5` cron) | minutes; measured 5–17 min gaps between runs today | no — GitHub-documented best-effort scheduling |
| Run length | ~110 s of collection + ~80 s of tests | partly — collector already caps reference bars by budget |
| Commit + Pages build | ~40 s | no |
| Browser poll of a stale snapshot | up to 30 s | removed by the pulse (measures the book directly) |
| Pulse cadence | 45 s by design | tunable via `data-pulse-interval-ms`; lower is impolite and undocumented for limits |

The honest summary: **the pulse brings detection down from "one collector run"
to "one 45-second interval",** and that is the floor for an anonymous REST
client. Sub-second detection needs the WebSocket `ticker` channel, which needs
credentials — the same blocker recorded as FL-01 on the Flagged page.
