# Verification — session `arena-a3137708` (2026-11-20)

Scope of this session: line-by-line review of the merged tree against the official
Kalshi documentation, plus a GitHub Pages build/PR/merge cycle. No new dashboard
was added — see §1, because that decision is itself a finding.

## 1. A parallel implementation was written, reviewed, and deliberately dropped

At the start of this session the working tree looked like an empty repo (single
squashed commit), so a second, independent pipeline was started under `kalshi/`
(REST client, SQLite store, alert engine, high-ROI screen, paper broker, SSE
dashboard). `COORDINATION.md` shows the repo is in fact far past that: five prior
sessions built `collector/`, `site_build/`, `trading/`, `kalshi-dashboard/`, the
root Pages site and 174 passing tests, and PR #38 already merged.

That parallel package was therefore **removed from the tree rather than merged**,
for two recorded reasons:

| Evidence | Result |
| - | - |
| `python3 tools/linkcheck.py` with `kalshi/` present | `pages=51 … errors=1 — ERROR kalshi/src/kalshi/web/index.html: missing asset -> /assets/app.js` (a new page that fails the repo's own gate) |
| `COORDINATION.md` irregularity **I-R1** (session `arena-8b01a1c4`) | "three parallel dashboards (root, `/kalshi-dashboard/`, `/docs/`) with differing numbers" — a fourth would have made the flagged problem worse |

The package is not in git history (never committed); it stays in the sandbox at
`/tmp/kalshi-ref` only as comparison material. Writing it was still useful: it
produced §3.3 below.

## 2. Findings, each checked against an official source

### F1 — `run_meta.json` exchange summary read two fields the API does not return (fixed)

- Location: `collector/runner.py`, the `exchange_status` step (was
  `status.get("exchange_status")` / `status.get("exchange_indexes")`).
- Official response schema for `GET /exchange/status`:
  <https://docs.kalshi.com/api-reference/exchange/get-exchange-status> —
  `exchange_active`, `trading_active`, `intra_exchange_transfers_active`,
  `exchange_estimated_resume_time`, `exchange_index_statuses[]`. **No
  `exchange_status`, no `exchange_indexes`.**
- Consequence: the audit trail published `"exchange": {"status": null,
  "indexes": 0}` on *every* run while the raw response captured beside it in
  `data/live.json` reported `exchange_active: true`, `trading_active: true` and
  four index statuses (`Default`, `Demo shard 1`, …). Verified by replaying the
  committed capture through the new summary:
  `summarize_exchange_status(live["exchange"])` →
  `{'exchange_active': True, 'trading_active': True, 'indexes': 4}`.
- Fix: `summarize_exchange_status()` in `collector/runner.py` projects the
  documented fields, keeps per-index statuses, attaches the docs URL as
  `source_url`, and preserves `None` for absent fields instead of coercing to
  `False`. Progress line now prints the real flags.
- Endpoint path itself was correct (`/exchange/status`, per the docs sample) and
  was left alone.

### F2 — overview page asserted "not trading" from a missing field (fixed)

- Location: `site_build/build.py` —
  `status = "trading" if exchange.get("trading_active") else "not trading"`.
- Problem: an *absent* field (exchange status call failed, older snapshot,
  partial payload) rendered as the positive claim "not trading". Per this
  project's verification rule, a value that cannot be confirmed must be blank,
  not inferred.
- Fix: render `trading` / `not trading` only when `trading_active` is actually
  present, otherwise `unknown (trading_active not returned)` or
  `unknown (status call failed)` when the collector recorded an error. On the
  current committed snapshot the flag is `true`, so the published text is
  unchanged — this is a false-claim guard, not a data change.

### F3 — units: prices are decimal dollars + `*_fp`/`*_dollars` strings, not integer cents

- The existing client documents and uses this correctly: `collector/kalshi_api.py:14`
  ("Money fields arrive as decimal *strings* in dollars (e.g. `"0.4200"`); counts
  as …"), order book read as `orderbook_fp.{yes_dollars,no_dollars}` per
  <https://docs.kalshi.com/getting_started/orderbook_responses.md>.
- The dropped `kalshi/` package had assumed integer cents for `yes_ask` and would
  have rejected `64` as out-of-range, i.e. **silently blanked every price**. That
  is now a worked example of why the units contract is written down in
  `collector/kalshi_api.py`; no change needed, recorded so it stays pinned.
- `collector/alerts.py` derives the reference mid from the book exactly as the
  docs describe (best YES bid = last element of `orderbook_fp.yes_dollars`; best
  YES ask = `1.00 − last element of no_dollars`), re-checked against the page
  linked above.

## 3. Reviewed and found correct (no change)

| Area | What was checked | Official source |
| - | - | - |
| Demo endpoint table | `https://external-api.demo.kalshi.co/trade-api/v2` recommended, `https://demo-api.kalshi.co/trade-api/v2` also supported; WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; every collector call is against the demo host | <https://docs.kalshi.com/getting_started/demo_env> |
| Swing threshold | `SWING_THRESHOLD = 0.10` USD either direction, configurable and echoed in the UI (`swap_threshold_dollars`) | project brief; API price fields per <https://docs.kalshi.com/getting_started/orderbook_responses.md> |
| Alert hygiene | mid-basis rule + `ALERT_MAX_SPREAD = 0.10` (a spread ≥ the threshold can move the mid without a trade) — a documented *design choice*, labelled as such in the module docstring, not passed off as an API rule | — |
| High-ROI gate | `edge = model_fair − executable_price`, `fee = 0.07·C·P·(1−P)`, `net_roi = (edge − fee)/price`, gated at `MODEL_MIN_NET_ROI = 0.05`; fee polynomial matches the published General fee schedule; explicitly "not a prediction and not a claim of profitability" | <https://docs.kalshi.com/trade-api-v2/api> + Kalshi fee schedule (re-verified against the published PDF in `INTEGRATION_REVIEW.md` §3) |
| News attribution | Google News RSS, headline is a *candidate* only; on failure the link fields stay blank and the item is flagged — matches the "never infer" rule | — |
| Resolution tracking | `collector/resolutions.py` reads the API's own result fields; the test asserts the published result equals the captured value (`RUNNER TEST PASSED … "resolutions": 1`) | <https://docs.kalshi.com/getting_started/market_settlement> |
| Topic scoping | `collector/topics.py` matches only on fields the API returns (`category`, `categories`, `tags`, `title`, `ticker`) and excludes anything outside the five topics; nothing unions topics | <https://docs.kalshi.com/api-reference/market/get-series-list> |
| Trading honesty | `collector/engine.py` never claims an exchange fill; production order fields (`order_type`, `order_effect`, `post_secondary_terms_accepted`) are added **only** for the production host, per the API reference | <https://docs.kalshi.com/trade-api-v2/api> |

## 4. Environment limitations hit during this session

- **Demo API egress failed mid-session.** Early in the session,
  `https://external-api.demo.kalshi.co/trade-api/v2/*` answered from this sandbox;
  later every call to both demo hosts died at the TLS handshake
  (`curl: (35) SSL_ERROR_SYSCALL`, ~30 ms; `ssl.SSLError` from Python), and
  `fetch_page` on the API URL returned an error while `docs.kalshi.com` still
  worked. The sandbox egress allowlist is
  `github.com` / `codeload.github.com` / `api.github.com` / registry.npmjs.org / pypi.org /
  files.pythonhosted.org, so live re-collection is not reproducible here.
  Consequence: **no data file was regenerated by this session**; the published
  snapshot remains the Actions one (`run_meta.json` finished
  `2026-11-20T19:44:12Z`, `errors: 0`), and the corrected exchange summary lands
  on the next scheduled Actions run, which has unrestricted egress.
- `docs/data/live.json` does not exist (the site reads `data/live.json` via
  `site_build/build.py`); `test/site_smoke.mjs docs/data` passes against the
  files actually published in `docs/data/`.

## 5. Commands run, with results

```
python3 -m unittest discover -s tests      -> Ran 180 tests, OK (skipped=1)   [174 before this session's +6]
python3 -m collector.test_runner           -> RUNNER TEST PASSED: {"series": 7, "markets": 7, "orderbooks": 7, "alerts": 7, "resolutions": 1}
python3 -m trading.test_engine             -> ALL TRADING TESTS PASSED
python3 tools/linkcheck.py                 -> pages=50 internal_links_checked=666 errors=0
npm test                                   -> # pass 29  # fail 0
node tools/rendercheck.mjs                 -> ok on every page (e.g. categories/crypto.html rows=143 externalLinks=291)
node test/site_smoke.mjs docs/data         -> ALL SITE SMOKE CHECKS PASSED
python3 -m site_build.build                -> rebuilds from committed data; only snapshot-age strings moved, so regenerated HTML was reverted and left to Actions
```

## 6. Left blank / flagged, not fixed

- `exchange_estimated_resume_time` is `None` in the current capture — the field is
  only populated during maintenance windows, so it is published as absent rather
  than as "no maintenance scheduled".
- Real demo-account balances/fills remain unverified (needs `KALSHI_API_KEY_ID` +
  private key as Actions secrets) and stay on the Flagged-for-Review page; this
  session did not add credentials or claim otherwise.
- News-cause links remain labelled research links, not causes; no headline in the
  current snapshot was promoted to "confirmed cause".
