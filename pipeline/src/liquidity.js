/**
 * Liquidity (orderbook) helpers.
 *
 * The Kalshi orderbook returns YES bids and NO bids only — a YES bid at $0.07 is
 * the same book level as a NO ask at $0.93 (see
 * https://docs.kalshi.com/getting_started/orderbook_responses and
 * https://docs.kalshi.com/api-reference/market/get-market-orderbook).
 */
import { fp } from './kalshi.js';

/**
 * Normalize one orderbook into levels + summary stats.
 * @param {{yes_dollars?: any[], no_dollars?: any[]}} orderbook raw `orderbook_fp`
 * @param {object} market market snapshot (for mid/price context)
 */
export function summarizeOrderbook(orderbook, market = {}) {
  const round4 = (v) => Number(Number(v).toFixed(4));
  const yes = (orderbook?.yes_dollars || []).map(([price, count]) => ({
    price: round4(fp.dollars(price)),
    count: fp.num(count),
  })).filter((l) => l.price > 0 && l.price < 1);
  const no = (orderbook?.no_dollars || []).map(([price, count]) => ({
    price: round4(fp.dollars(price)),
    count: fp.num(count),
  })).filter((l) => l.price > 0 && l.price < 1);

  // Docs: levels are sorted ascending by price, so the best bid is the last element.
  const bestYesBid = yes.length ? yes[yes.length - 1] : null;
  const bestNoBid = no.length ? no[no.length - 1] : null;

  // YES ask == NO bid (single book). Fall back to the market snapshot.
  const yesAsk = round4(bestNoBid ? 1 - bestNoBid.price : fp.dollars(market.yes_ask_dollars));
  const noAsk = round4(bestYesBid ? 1 - bestYesBid.price : fp.dollars(market.no_ask_dollars));
  const yesBid = round4(bestYesBid ? bestYesBid.price : fp.dollars(market.yes_bid_dollars));
  const noBid = round4(bestNoBid ? bestNoBid.price : fp.dollars(market.no_bid_dollars));

  const mid = round4((yesBid + yesAsk) / 2);
  const spread = yesBid > 0 && yesAsk < 1 ? round4(yesAsk - yesBid) : null;

  const within = (levels, centre, width) => levels
    .filter((l) => Math.abs(l.price - centre) <= width)
    .reduce((sum, l) => sum + l.count, 0);

  const depthYes = yes.reduce((s, l) => s + l.count, 0);
  const depthNo = no.reduce((s, l) => s + l.count, 0);

  return {
    yes_levels: yes.slice(-10).reverse(),
    no_levels: no.slice(-10).reverse(),
    best_yes_bid: yesBid,
    best_yes_ask: yesAsk,
    best_no_bid: noBid,
    best_no_ask: noAsk,
    mid,
    spread,
    depth_yes_total: depthYes,
    depth_no_total: depthNo,
    // contracts resting within 5c of the mid — the number a trader cares about
    depth_yes_within_5c: within(yes, mid, 0.05),
    depth_no_within_5c: within(no, mid, 0.05),
    notional_yes_within_5c: within(yes, mid, 0.05) * mid,
    notional_no_within_5c: within(no, mid, 0.05) * (1 - mid),
  };
}

/** Contracts available at a given price on one side (how many can actually fill). */
export function contractsAtPrice(summary, side, price) {
  const levels = side === 'no' ? summary.no_levels : summary.yes_levels;
  const p = Number(price);
  return levels
    .filter((l) => (side === 'no' ? Math.abs(l.price - p) < 1e-9 : Math.abs(l.price - p) < 1e-9))
    .reduce((sum, l) => sum + l.count, 0);
}

/** Total contracts available between the mid and `price` (inclusive) on one side. */
export function contractsWithin(summary, side, price) {
  const levels = side === 'no' ? summary.no_levels : summary.yes_levels;
  const mid = summary.mid;
  const p = Number(price);
  if (side === 'no') {
    return levels.filter((l) => l.price >= mid && l.price <= p).reduce((s, l) => s + l.count, 0);
  }
  return levels.filter((l) => l.price <= mid && l.price >= p).reduce((s, l) => s + l.count, 0);
}
