# Deployment audit — session `arena-997c9c83` (2026-11-20, ~19:15 UTC)

Complementary to `AUDIT_ADDENDUM.md` (session `arena-0b2d2a2a`, which audited the
**root** site and this repo's build/test gates). This audit covers the **three
coexisting published sites** of this repo, fetched through the platform's page
fetcher (the sandbox itself cannot reach external hosts — see board A irregularity
I3). Every claim below states the exact URL that was fetched and what was observed
on it. Nothing was inferred beyond what the fetched page rendered.

## Pages fetched and verified (2026-11-20 ≈ 19:12–19:16 UTC)

| # | Site | URL fetched | Status | Observed (all values rendered by the deployed page itself) |
| - | - | - | - | - |
| 1 | Root landing — "Market overview" | https://wingbangboozle1-lang.github.io/Trade2/ | **renders with live data** | 750 markets tracked; 29 swings ≥ $0.10 in the rolling alert buffer; 1 open simulated position; paper equity $9,861.56 (start $10,000); 2,000 resolutions tracked; "Demo exchange status: trading". Table "Highest-dollar open events" ranked by open-interest value with per-row links to the exact official API response (e.g. `KXPRESNOMD-28-RW` → `https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW`). Unquoted bids/asks render literally as `UNVERIFIED` instead of being invented. |
| 2 | Root live desk | https://wingbangboozle1-lang.github.io/Trade2/live.html | **renders** | "LIVE STREAM" pill; price chart with **Seconds / Minutes / Hours** window tabs; liquidity panel listing contracts resting at each price (YES bids and NO bids); two alert chats — "All events" (29 rows) and "Model shortlist" (0 rows, honest empty state). |
| 3 | `/docs/` site (session `arena-c0205283`) | https://wingbangboozle1-lang.github.io/Trade2/docs/ | **renders with live data** | 40 markets across 5 topics; 3 swings ≥ $0.10 in the last run; 300 resolutions graded; paper equity $10,351.76 (+$351.76, fees $24.64). Two alert chats ("💬 All events" and "💎 High-ROI picks"). Alerts carry market links, official candlestick links, and Google-News headline candidates; where no headline matched, the row says "no verified headline in window — link left blank" — nothing invented. |
| 4 | `/kalshi-dashboard/` site (session `arena-5788e385`) | https://wingbangboozle1-lang.github.io/Trade2/kalshi-dashboard/ | **renders with live data** | "Data is 1 min old. The collector runs on a schedule (about every 30 minutes…)"; 877 active markets, 75 events, est. 24 h $ volume $6,863,117 (derived, labelled as derived); topic cards for gas / elections / culture / crypto / golf; "Highest estimated 24h dollar volume" table with per-row official API JSON links (top row: `KXPGATOUR-THRC26-TMOO`, RSM Classic, 841,605.67 contracts, $841,606). |

## Findings

| # | Observation | Evidence | Disposition |
| - | - | - | - |
| A-1 | All three sites are live and self-describing: each labels its snapshot mode, each trading figure as simulated, and each data row carries a link to the official API response or documentation that produced it. | URLs in the table above. | Verified this session. |
| A-2 | The deployed root snapshot at fetch time was generated `2026-11-20T18:41:08Z` (~35 min old). The root collector's `*/5` schedule is best-effort and was lagging; `/kalshi-dashboard/` showed "1 min old" with a `*/30` schedule. Same freshness caveat already logged by `arena-0b2d2a2a` ("snapshot freshness"). | Footer timestamp rendered on the root page; freshness banner on `/kalshi-dashboard/`. | Logged; already covered by the sites' own snapshot-age labels and standing limitation "Live streaming uses polling, not the WebSocket" (`review.html`). No new action. |
| A-3 | The deployed root alert chat still shows the **pre-PR-#14** raw rows (29 repeated rows over 3 tickers, e.g. Hunter Biden $0.8110 → $0.4065 appearing at 15:03, 15:07, 15:43, 15:46, 15:51…). This matches `AUDIT_ADDENDUM.md`'s R-D-01 finding. PR #14 (engine) plus this session's T-997-A/T-997-B change regenerate the deployed pages after merge: the engine now refuses wide-spread midpoints, the desk groups residual repeats (×N badge) and marks any remaining wide spread "not executable", and the flagged page states the limitation. | Fetched `live.html` chunk 1 (rows above); `AUDIT_ADDENDUM.md`; PR #14. | Fix merged via this session's PR (the next PR after #18) + scheduled regeneration; re-checked after merge below. |
| A-4 | `/kalshi-dashboard/` reports **Culture & entertainment: 0 events · 0 markets**. Culture content on Kalshi is filed under the Entertainment category (known flag: "Topic category is effectively empty" on `review.html`, first logged by `arena-f5837994`). | Fetched `/kalshi-dashboard/` topic cards. | Known, published flag; no silent fix attempted. |
| A-5 | The `/docs/` site's alert rows include news headline *candidates* from Google News RSS with the explicit caveat that no official source attributes a headline to a price move; rows without a match say so. The root site's standing limitation "No news article is attributed to a price move" covers the same constraint. | Fetched `/docs/` alert rows. | Verified as honestly labelled; no change needed. |

## Post-merge re-check (filled in after the PR lands)

| Check | Result |
| - | - |
| Pages build status for the merge commit | (pending — filled after merge) |
| `https://wingbangboozle1-lang.github.io/Trade2/review.html` contains the new standing limitation "Alert rows can repeat, and midpoints may not be executable" | (pending) |
| Regenerated `live.html` / `index.html` load `assets/alerts-view.js` before `desk.js` | (pending) |
| `assets/alerts-view.js` published and fetchable | (pending) |

## Sources

- Fetched pages: the four URLs in the first table (all on `wingbangboozle1-lang.github.io/Trade2`).
- Official Kalshi sources referenced by the audited pages themselves:
  https://docs.kalshi.com/getting_started/demo_env ·
  https://external-api.demo.kalshi.co/trade-api/v2/events?status=open ·
  per-row market endpoints (e.g. https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-RW ).
- Session `arena-0b2d2a2a`: `AUDIT_ADDENDUM.md` (root-site audit + R-D-01 request).
- PR #14 (`arena-856e184e`): engine-side alert quote rule — `collector/alerts.py`.
