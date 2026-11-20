/**
 * The "high ROI" model.
 *
 * This is a transparent, deterministic scoring model — not a prediction
 * guarantee. Every component is documented on the site's methodology page and
 * every score carries the reasons that produced it, so a trader can audit why a
 * market was surfaced in the selective feed.
 *
 * Score = momentum (0-30) + liquidity (0-25) + spread (0-15) + edge (0-15) + time (0-15)
 */
import { fp } from './kalshi.js';

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Price `minutes` ago from a time series [[tsSeconds, price], ...]. */
export function priceMinutesAgo(points, minutes, now = Date.now() / 1000) {
  if (!points || !points.length) return null;
  const target = now - minutes * 60;
  let best = null;
  let bestDelta = Infinity;
  for (const [ts, price] of points) {
    const delta = Math.abs(ts - target);
    if (delta < bestDelta) { bestDelta = delta; best = price; }
  }
  return best;
}

export function mean(values) {
  const list = values.filter((v) => Number.isFinite(v));
  if (!list.length) return null;
  return list.reduce((a, b) => a + b, 0) / list.length;
}

/**
 * Score one market.
 * @param {object} p
 * @param {object} p.market normalized market snapshot
 * @param {object} p.book orderbook summary from `summarizeOrderbook`
 * @param {Array<[number, number]>} p.points price history [[tsSeconds, price]]
 * @param {number} p.now epoch seconds
 */
export function scoreMarket({ market, book, points = [], now = Date.now() / 1000 }) {
  const reasons = [];
  const last = fp.dollars(market.last_price);

  // ---- momentum (0-30): size of the most recent move
  const hourAgo = priceMinutesAgo(points, 60, now);
  const prev = fp.dollars(market.previous_price);
  const moveRef = hourAgo !== null ? hourAgo : (Number.isFinite(prev) && prev > 0 ? prev : null);
  const move = moveRef !== null ? last - moveRef : 0;
  const absMove = Math.abs(move);
  let momentum = clamp((absMove / 0.10) * 30, 0, 30);
  if (absMove >= 0.10) reasons.push(`momentum ${move >= 0 ? '+' : ''}${move.toFixed(2)} vs 1h reference`);
  else reasons.push(`momentum ${move.toFixed(3)} (below the $0.10 swing bar)`);

  // ---- liquidity (0-25): resting size near the mid, log scaled
  const depth = Math.max(book?.depth_yes_within_5c || 0, book?.depth_no_within_5c || 0);
  let liquidity = 0;
  if (depth > 0) {
    liquidity = clamp((Math.log10(Math.max(depth, 1)) - Math.log10(10)) / (Math.log10(3000) - Math.log10(10)) * 25, 0, 25);
    reasons.push(`liquidity ${Math.round(depth)} contracts within 5c of mid`);
  } else {
    reasons.push('no resting size within 5c of mid');
  }

  // ---- spread (0-15): tighter is better
  const spread = book?.spread;
  let spreadScore = 0;
  if (spread !== null && spread !== undefined && Number.isFinite(spread)) {
    spreadScore = clamp((0.10 - spread) / 0.09 * 15, 0, 15);
    reasons.push(`spread $${spread.toFixed(3)}`);
  } else {
    reasons.push('no two-sided quote');
  }

  // ---- edge (0-15): distance of the last price from its own recent mean
  const window = points.filter(([ts]) => ts >= now - 30 * 60).map(([, p]) => p);
  const recentMean = window.length >= 3 ? mean(window) : null;
  const edge = recentMean !== null ? last - recentMean : 0;
  const edgeScore = clamp((Math.abs(edge) / 0.10) * 15, 0, 15);
  if (recentMean !== null) {
    reasons.push(`edge ${edge >= 0 ? '+' : ''}${edge.toFixed(3)} vs 30m mean $${recentMean.toFixed(3)}`);
  } else {
    reasons.push('not enough history for a 30m mean');
  }

  // ---- time (0-15): prefer markets that resolve inside a workable window
  const closeTs = Date.parse(market.close_time) / 1000;
  const hoursToClose = Number.isFinite(closeTs) ? (closeTs - now) / 3600 : null;
  let timeScore = 0;
  if (hoursToClose !== null) {
    if (hoursToClose < 0) {
      timeScore = 0;
      reasons.push('market already past its close time');
    } else if (hoursToClose < 1) {
      timeScore = 4;
      reasons.push(`closes in ${hoursToClose.toFixed(1)}h`);
    } else if (hoursToClose <= 72) {
      timeScore = 15;
      reasons.push(`closes in ${hoursToClose.toFixed(0)}h`);
    } else if (hoursToClose <= 720) {
      timeScore = 15 - ((hoursToClose - 72) / 648) * 9;
      reasons.push(`closes in ${Math.round(hoursToClose / 24)}d`);
    } else {
      timeScore = 6;
      reasons.push(`closes in ${Math.round(hoursToClose / 24)}d (distant)`);
    }
  } else {
    reasons.push('no close time reported');
  }

  const score = Math.round(momentum + liquidity + spreadScore + edgeScore + timeScore);

  // ---- model fair value (heuristic) -> expected value per contract
  // Mean-reversion pull (50%) blended with momentum persistence (30%), damped 20%.
  const pull = recentMean !== null ? (recentMean - last) * 0.5 : 0;
  const persistence = move * 0.3;
  const fairYes = clamp(last + (pull + persistence) * 0.2, 0.01, 0.99);
  const evYes = fairYes - last;
  const evNo = -evYes;
  const roiPct = last > 0 ? (evYes / last) * 100 : 0;

  return {
    ticker: market.ticker,
    score,
    components: {
      momentum: Math.round(momentum),
      liquidity: Math.round(liquidity),
      spread: Math.round(spreadScore),
      edge: Math.round(edgeScore),
      time: Math.round(timeScore),
    },
    fair_yes: Number(fairYes.toFixed(4)),
    ev_yes: Number(evYes.toFixed(4)),
    ev_no: Number(evNo.toFixed(4)),
    roi_pct: Number(roiPct.toFixed(2)),
    hours_to_close: hoursToClose === null ? null : Number(hoursToClose.toFixed(2)),
    reasons,
  };
}
