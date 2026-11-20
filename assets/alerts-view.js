/* Alerts view helpers — shared, dependency-free, unit-testable.
 *
 * Why this exists (coordination request R-D-01, arena-0b2d2a2a):
 * the collector compares book midpoints between reference bars, so one
 * sustained >= $0.10 move can re-fire on several consecutive snapshots and
 * produce many identical feed rows. It can also fire on markets whose
 * bid/ask spread is wider than the move itself, so the quoted midpoint is
 * not an executable price. This module gives the display layer the tools to
 * be honest about both without touching the engine:
 *
 *   - dedupeAlerts(): collapse exact repeated rows (same market, direction,
 *     and previous->current prices), keeping first-appearance order, the most
 *     recent occurrence timestamp, and a repeat count.
 *   - wideSpread(): a midpoint is flagged when the quoted YES spread is
 *     >= $0.10 — i.e. wider than the alert threshold — so it cannot be
 *     treated as an executable two-sided price.
 *   - ageLabel(): humanized snapshot age so a stale view is never mistaken
 *     for a live one.
 *
 * No inference, no invention: every field used comes straight from the
 * collector snapshot (assets/live.json) or the official API responses.
 */
(function (root) {
  "use strict";

  /* Same threshold as the alert engine: a swing of >= $0.10 in either
   * direction. A spread at or above it means the midpoint sits inside a
   * gap that no resting order fills — display it, but never call it
   * executable. */
  var ALERT_THRESHOLD = 0.1;

  function rowKey(a) {
    return [
      a && a.ticker,
      a && a.direction,
      String(a && a.previous),
      String(a && a.current),
    ].join("|");
  }

  /* Return the quoted YES spread in dollars, or null when either side is
   * missing or not a finite number. */
  function spreadOf(a) {
    var bid = Number(a && a.yes_bid);
    var ask = Number(a && a.yes_ask);
    if (!isFinite(bid) || !isFinite(ask)) return null;
    return ask - bid;
  }

  function wideSpread(a) {
    var s = spreadOf(a);
    return s !== null && s >= ALERT_THRESHOLD;
  }

  /* Collapse exact repeated alert rows.
   *
   * Two rows are "the same alert" when market ticker, direction and the
   * previous->current price pair match exactly — i.e. the collector fired on
   * the identical midpoint step again. Anything else (a new price step, the
   * opposite direction, another market) stays its own row.
   *
   * Order follows first appearance in the feed; each row carries
   *   repeat_count — how many raw rows collapsed into it (>= 1),
   *   last_iso     — the most recent occurrence's ISO time,
   *   spread       — quoted YES spread in dollars (or null),
   *   wide_spread  — true when spread >= $0.10.
   */
  function dedupeAlerts(alerts) {
    var out = [];
    var index = {};
    var list = Array.isArray(alerts) ? alerts : [];
    for (var i = 0; i < list.length; i++) {
      var a = list[i];
      if (!a || typeof a !== "object") continue;
      var key = rowKey(a);
      var s = spreadOf(a);
      var existing = index[key];
      if (!existing) {
        var row = Object.assign({}, a, {
          repeat_count: 1,
          last_iso: a.iso || null,
          last_ts: a.ts !== undefined ? a.ts : null,
          spread: s,
          wide_spread: s !== null && s >= ALERT_THRESHOLD,
        });
        index[key] = row;
        out.push(row);
      } else {
        existing.repeat_count += 1;
        var ts = a.ts !== undefined ? Number(a.ts) : null;
        if (ts !== null && isFinite(ts) &&
            (existing.last_ts === null || ts > existing.last_ts)) {
          existing.last_ts = ts;
        }
        if (a.iso && (!existing.last_iso || a.iso > existing.last_iso)) {
          existing.last_iso = a.iso;
        }
        /* Latest quotes win: refresh spread fields from the newest row. */
        existing.yes_bid = a.yes_bid;
        existing.yes_ask = a.yes_ask;
        existing.spread = s;
        existing.wide_spread = s !== null && s >= ALERT_THRESHOLD;
      }
    }
    return out;
  }

  /* Humanized age of an ISO timestamp. Returns "—" for anything it cannot
   * parse; never guesses. */
  function ageLabel(iso, nowMs) {
    if (!iso) return "—";
    var then = new Date(iso).getTime();
    if (!isFinite(then)) return "—";
    var now = nowMs === undefined ? Date.now() : Number(nowMs);
    if (!isFinite(now)) return "—";
    var s = Math.max(0, Math.floor((now - then) / 1000));
    if (s < 60) return s + "s old";
    var m = Math.floor(s / 60);
    if (m < 60) return m + "m old";
    var h = Math.floor(m / 60);
    if (h < 24) return h + "h " + (m % 60) + "m old";
    var d = Math.floor(h / 24);
    return d + "d " + (h % 24) + "h old";
  }

  var api = {
    ALERT_THRESHOLD: ALERT_THRESHOLD,
    rowKey: rowKey,
    spreadOf: spreadOf,
    wideSpread: wideSpread,
    dedupeAlerts: dedupeAlerts,
    ageLabel: ageLabel,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof root !== "undefined" && root) {
    root.AlertsView = api;
  }
})(typeof window !== "undefined" ? window : null);
