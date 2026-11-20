/**
 * Swing detection.
 *
 * A swing is a move of at least $0.10 in either direction. Two references are
 * used, both from official sources:
 *   1. `previous_price_dollars` — the previous price Kalshi reports on the market.
 *   2. The collector's own recorded price history (a point at least
 *      `lookbackMinutes` old) so that moves slower than one collection cycle
 *      are still caught.
 */
import { SWING_THRESHOLD } from './config.js';
import { fp } from './kalshi.js';
import { priceMinutesAgo } from './roi.js';

export const SWING_LOOKBACK_MINUTES = 5;

/**
 * @param {object} p
 * @param {object[]} p.markets normalized markets
 * @param {Object<string, Array<[number, number]>>} p.history ticker -> [[ts, price]]
 * @param {number} p.now epoch seconds
 * @returns {object[]} swing events
 */
export function detectSwings({ markets, history = {}, now = Date.now() / 1000 }) {
  const swings = [];
  for (const market of markets) {
    const last = fp.dollars(market.last_price);
    if (!last) continue;

    const candidates = [];
    const prev = fp.dollars(market.previous_price);
    // A previous price of 0 means "no previous print" — it is not a real reference.
    if (prev >= 0.01) candidates.push({ ref: prev, refLabel: 'Kalshi previous_price_dollars' });

    const historical = priceMinutesAgo(history[market.ticker] || [], SWING_LOOKBACK_MINUTES, now);
    if (historical !== null && historical > 0) {
      candidates.push({ ref: historical, refLabel: `price ${SWING_LOOKBACK_MINUTES}m ago` });
    }

    // Compare in integer cents so that exactly $0.10 counts as a swing
    // (floating point 0.60 - 0.50 is 0.09999999999999998).
    const thresholdCents = Math.round(SWING_THRESHOLD * 100);
    let best = null;
    for (const candidate of candidates) {
      const delta = last - candidate.ref;
      const deltaCents = Math.round(Math.abs(delta) * 100);
      if (deltaCents >= thresholdCents) {
        if (!best || deltaCents > Math.round(Math.abs(best.delta) * 100)) {
          best = { ...candidate, delta };
        }
      }
    }
    if (!best) continue;

    swings.push({
      ts: new Date(now * 1000).toISOString(),
      ticker: market.ticker,
      event_ticker: market.event_ticker,
      title: market.title,
      topic: market.topic,
      topics: market.topics,
      category: market.category,
      direction: best.delta > 0 ? 'up' : 'down',
      from: Number(best.ref.toFixed(4)),
      to: Number(last.toFixed(4)),
      delta: Number(best.delta.toFixed(4)),
      abs_delta: Number(Math.abs(best.delta).toFixed(4)),
      threshold: SWING_THRESHOLD,
      reference: best.refLabel,
      last_price: Number(last.toFixed(4)),
      yes_bid: market.yes_bid,
      yes_ask: market.yes_ask,
      no_bid: market.no_bid,
      no_ask: market.no_ask,
      close_time: market.close_time,
      dollar_amount: market.dollar_amount,
      roi_score: market.roi_score ?? null,
      kalshi_url: market.kalshi_url,
      settlement_sources: market.settlement_sources || [],
    });
  }
  return swings.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}

/** Merge new swings into the persisted alert log (dedupe on ticker+direction+minute). */
export function mergeAlerts(existing = [], incoming = [], { max = 400 } = {}) {
  const merged = [...incoming, ...existing];
  const seen = new Set();
  const out = [];
  for (const alert of merged) {
    const minute = Math.floor(Date.parse(alert.ts) / 60000);
    const key = `${alert.ticker}|${alert.direction}|${minute}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(alert);
    if (out.length >= max) break;
  }
  return out;
}

/**
 * Detect swings straight from the trade feed: two consecutive trades on the same
 * market whose YES prices differ by at least $0.10.
 * This is the most precise "live" signal because every point is an actual fill
 * reported by the exchange (`GET /markets/trades`).
 *
 * @param {object} p
 * @param {Object<string, Array<{ts:number, price:number, count:number}>>} p.tradeFeed
 * @param {object[]} p.markets normalized markets (for titles / links)
 */
export function detectTradeSwings({ tradeFeed = {}, markets = [], minGapSeconds = 0 }) {
  const byTicker = new Map(markets.map((m) => [m.ticker, m]));
  const swings = [];
  const thresholdCents = Math.round(SWING_THRESHOLD * 100);

  for (const [ticker, points] of Object.entries(tradeFeed)) {
    if (!points || points.length < 2) continue;
    const sorted = [...points].sort((a, b) => a.ts - b.ts);
    for (let i = 1; i < sorted.length; i += 1) {
      const prev = sorted[i - 1];
      const curr = sorted[i];
      if (curr.ts - prev.ts < minGapSeconds) continue;
      const delta = curr.price - prev.price;
      const cents = Math.round(Math.abs(delta) * 100);
      if (cents < thresholdCents) continue;
      const market = byTicker.get(ticker);
      swings.push({
        ts: new Date(curr.ts * 1000).toISOString(),
        ticker,
        event_ticker: market?.event_ticker || null,
        title: market?.title || ticker,
        topic: market?.topic || null,
        topics: market?.topics || [],
        category: market?.category || null,
        direction: delta > 0 ? 'up' : 'down',
        from: Number(prev.price.toFixed(4)),
        to: Number(curr.price.toFixed(4)),
        delta: Number(delta.toFixed(4)),
        abs_delta: Number(Math.abs(delta).toFixed(4)),
        threshold: SWING_THRESHOLD,
        reference: 'consecutive trade print',
        trade_count: curr.count,
        last_price: Number(curr.price.toFixed(4)),
        close_time: market?.close_time || null,
        dollar_amount: market?.dollar_amount ?? null,
        kalshi_url: market?.kalshi_url || null,
        settlement_sources: market?.settlement_sources || [],
        roi_score: market?.roi_score ?? null,
      });
    }
  }
  return swings.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}
