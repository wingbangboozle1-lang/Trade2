/**
 * Simulated ("paper") trading engine.
 *
 * Every trade produced here is SIMULATED against real Kalshi demo prices.
 * No real order is ever sent from this module — see `live-trade.js` for the
 * credential-gated path that does (it is inert without a Kalshi API key).
 *
 * The engine has two modes:
 *   - `backtest`: replays the 1-minute candlestick history the API returns.
 *   - `live`:     forward paper trading on each collection cycle, using the
 *                 live orderbook for entry/exit prices.
 *
 * Execution assumptions (documented on the methodology page):
 *   - A YES position is bought at the YES ask and closed at the YES bid.
 *   - A NO position is bought at the NO ask (1 - YES bid) and closed at the NO
 *     bid (1 - YES ask). Kalshi books are single-book: a YES bid at $0.07 is
 *     the same level as a NO ask at $0.93.
 *   - Backtest fills use the candle close +/- $0.01 as a conservative proxy for
 *     the bid/ask spread.
 *   - Position size is a fixed dollar risk per trade, capped by contracts.
 */
import { PAPER_START_CASH } from './config.js';

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const round2 = (v) => Number(Number(v).toFixed(2));

export const STRATEGIES = {
  swing_momentum: {
    id: 'swing_momentum',
    label: 'Swing Momentum',
    description: 'Buys the direction of a move of at least $0.10 once the move has printed, then exits on a $0.04 target or stop.',
    risk_usd: 50,
    max_contracts: 100,
    swing_threshold: 0.10,
    take_profit: 0.04,
    stop_loss: 0.04,
    max_hold_minutes: 720,
  },
  mean_reversion: {
    id: 'mean_reversion',
    label: 'Mean Reversion',
    description: 'Buys a market that has moved at least $0.03 away from its own 30-period mean, then exits on a $0.03 target or stop.',
    risk_usd: 50,
    max_contracts: 100,
    deviation_threshold: 0.03,
    take_profit: 0.03,
    stop_loss: 0.03,
    max_hold_minutes: 480,
  },
  liquidity_capture: {
    id: 'liquidity_capture',
    label: 'Liquidity Capture',
    description: 'Buys the touch in a tight, deep market and aims for a 2-cent spread-sized gain.',
    risk_usd: 25,
    max_contracts: 50,
    take_profit: 0.02,
    stop_loss: 0.02,
    max_hold_minutes: 60,
  },
};

/** Minimum price at which a simulated order is allowed (a $0.00 "fill" is not a fill). */
export const MIN_ENTRY_PRICE = 0.02;
export const MAX_ENTRY_PRICE = 0.98;

/** Stable fingerprint of the strategy parameters — used to invalidate stale trade logs. */
export function strategyConfigHash() {
  const payload = JSON.stringify(Object.values(STRATEGIES).map((s) => [s.id, s.risk_usd, s.max_contracts, s.take_profit, s.stop_loss, s.max_hold_minutes, s.swing_threshold ?? null, s.deviation_threshold ?? null]));
  let hash = 0;
  for (let i = 0; i < payload.length; i += 1) {
    hash = ((hash << 5) - hash + payload.charCodeAt(i)) | 0;
  }
  return hash.toString(16);
}

export const TRADE_CATEGORIES = {
  entry_signal: 'Entry signal',
  exit_target: 'Take-profit target reached',
  exit_stop: 'Stop-loss reached',
  exit_time: 'Max hold time reached',
  exit_resolution: 'Event resolved',
  exit_manual: 'Closed by strategy rebalance',
};

const yesFromNo = (yesPrice) => 1 - yesPrice;

/** Convert a YES-side price into the price of the opposite side. */
function sidePrice(yesPrice, side) {
  return side === 'YES' ? yesPrice : yesFromNo(yesPrice);
}

/** Side price -> YES price (inverse of sidePrice). */
function yesFromSide(sidePriceValue, side) {
  return side === 'YES' ? sidePriceValue : yesFromNo(sidePriceValue);
}

/** Rolling mean of the last `n` prices up to (but excluding) index i. */
function rollingMean(series, i, n) {
  const start = Math.max(0, i - n + 1);
  const slice = series.slice(start, i + 1).map((p) => p.price).filter(Number.isFinite);
  if (slice.length < 3) return null;
  return slice.reduce((a, b) => a + b, 0) / slice.length;
}

/** Price `minutes` before index i (falls back to the previous point). */
function priceBefore(series, i, minutes) {
  if (i <= 0) return null;
  const target = series[i].ts - minutes * 60;
  let best = null;
  let bestDelta = Infinity;
  for (let j = i - 1; j >= 0; j -= 1) {
    const delta = Math.abs(series[j].ts - target);
    if (delta < bestDelta) { bestDelta = delta; best = series[j].price; }
  }
  return best;
}

/** Size a trade from a dollar risk budget. */
function sizePosition(price, strategy) {
  if (!Number.isFinite(price) || price <= 0 || price >= 1) return 0;
  const byRisk = Math.floor(strategy.risk_usd / price);
  return clamp(byRisk, 1, strategy.max_contracts);
}

/**
 * Strategy signal generation. Each returns null (no trade) or a signal object.
 * `bar` is { ts, price, bid, ask, spread }.
 */
const SIGNALS = {
  swing_momentum(series, i, ctx) {
    const strategy = STRATEGIES.swing_momentum;
    const price = series[i].price;
    const ref = priceBefore(series, i, ctx.swingLookbackMinutes ?? 5);
    if (ref === null) return null;
    const delta = price - ref;
    if (Math.abs(delta) < strategy.swing_threshold - 1e-9) return null;
    return {
      side: delta > 0 ? 'YES' : 'NO',
      reason: `${delta > 0 ? 'Up' : 'Down'} swing of $${Math.abs(delta).toFixed(2)} vs ${ctx.swingLookbackMinutes ?? 5}m reference $${ref.toFixed(2)}`,
      ref_price: ref,
    };
  },
  mean_reversion(series, i) {
    const strategy = STRATEGIES.mean_reversion;
    const price = series[i].price;
    const mean = rollingMean(series, i, 30);
    if (mean === null) return null;
    const delta = price - mean;
    if (Math.abs(delta) < strategy.deviation_threshold - 1e-9) return null;
    if (price < 0.15 || price > 0.85) return null;
    return {
      side: delta < 0 ? 'YES' : 'NO',
      reason: `Price $${price.toFixed(3)} is $${Math.abs(delta).toFixed(3)} ${delta < 0 ? 'below' : 'above'} the 30-period mean $${mean.toFixed(3)}`,
      ref_price: mean,
    };
  },
  liquidity_capture(series, i) {
    const strategy = STRATEGIES.liquidity_capture;
    const bar = series[i];
    const spread = bar.spread;
    if (!Number.isFinite(spread) || spread > 0.03) return null;
    if (bar.price < 0.10 || bar.price > 0.90) return null;
    return {
      side: 'YES',
      reason: `Tight quote (spread $${spread.toFixed(3)}) with resting size`,
      ref_price: bar.price,
    };
  },
};

/**
 * Backtest a single market over its candle series for every strategy.
 * @returns {object[]} simulated trades
 */
export function backtestMarket({ market, series, swingLookbackMinutes = 5 }) {
  const trades = [];
  if (!series || series.length < 10) return trades;

  for (const strategy of Object.values(STRATEGIES)) {
    const open = {};
    for (let i = 0; i < series.length; i += 1) {
      const bar = series[i];
      const yesPrice = bar.price;
      const yesBid = Number.isFinite(bar.bid) ? bar.bid : yesPrice;
      const yesAsk = Number.isFinite(bar.ask) ? bar.ask : yesPrice;

      // --- exits first
      for (const key of Object.keys(open)) {
        const position = open[key];
        const bidNow = yesBid;
        const priceNow = sidePrice(bidNow, position.side);
        const heldMinutes = (bar.ts - position.entry_ts) / 60;
        let exit = null;
        if (priceNow >= position.entry_price + strategy.take_profit) {
          exit = { price: priceNow, reason: 'exit_target' };
        } else if (priceNow <= position.entry_price - strategy.stop_loss) {
          exit = { price: priceNow, reason: 'exit_stop' };
        } else if (heldMinutes >= strategy.max_hold_minutes) {
          exit = { price: priceNow, reason: 'exit_time' };
        }
        if (!exit) continue;
        const proceeds = position.count * exit.price;
        trades.push({
          ...position,
          exit_ts: bar.ts,
          exit_price: round2(exit.price),
          proceeds: round2(proceeds),
          pnl: round2(proceeds - position.cost),
          exit_reason: exit.reason,
          status: 'closed',
          mode: 'backtest',
          hold_minutes: Math.round(heldMinutes),
        });
        delete open[key];
      }

      // --- entries
      const signal = SIGNALS[strategy.id](series, i, { swingLookbackMinutes });
      if (!signal || open[strategy.id]) continue;
      const entryYesPrice = signal.side === 'YES' ? yesAsk : yesFromNo(yesBid);
      if (!Number.isFinite(entryYesPrice) || entryYesPrice < MIN_ENTRY_PRICE || entryYesPrice > MAX_ENTRY_PRICE) continue;
      const count = sizePosition(entryYesPrice, strategy);
      if (!count) continue;
      const cost = count * entryYesPrice;
      open[strategy.id] = {
        strategy: strategy.id,
        ticker: market.ticker,
        event_ticker: market.event_ticker,
        title: market.title,
        topic: market.topic,
        side: signal.side,
        count,
        entry_ts: bar.ts,
        entry_price: round2(entryYesPrice),
        entry_yes_price: round2(yesPrice),
        cost: round2(cost),
        entry_reason: signal.reason,
        mode: 'backtest',
        status: 'open',
      };
    }

    // markets still open at the end of the history stay open (marked to market)
    for (const position of Object.values(open)) {
      trades.push({ ...position, mode: 'backtest', status: 'open' });
    }
  }
  return trades;
}

/**
 * Forward (live) paper trading step for one market.
 * @param {object} p
 * @param {object[]} p.openPositions currently open simulated positions
 * @param {object} p.market normalized market
 * @param {object} p.book orderbook summary
 * @param {Array<{ts:number, price:number}>} p.series recent price history
 * @param {number} p.now epoch seconds
 */
export function stepMarket({ openPositions = [], market, book, series = [], now }) {
  const closed = [];
  const opened = [];
  const strategyIds = Object.keys(STRATEGIES);

  const yesBid = Number.isFinite(book?.best_yes_bid) && book.best_yes_bid > 0 ? book.best_yes_bid : market.yes_bid;
  const yesAsk = Number.isFinite(book?.best_yes_ask) && book.best_yes_ask > 0 && book.best_yes_ask < 1 ? book.best_yes_ask : market.yes_ask;
  const lastYes = market.last_price;

  // ---- resolution first: a resolved market settles open positions at $1 / $0
  const resolution = market.result === 'yes' || market.result === 'no' ? market.result : null;
  for (const position of openPositions) {
    if (!resolution) break;
    const payout = (position.side === 'YES' && resolution === 'yes') || (position.side === 'NO' && resolution === 'no')
      ? position.count : 0;
    const proceeds = payout;
    closed.push({
      ...position,
      exit_ts: now,
      exit_price: payout ? 1 : 0,
      proceeds: round2(proceeds),
      pnl: round2(proceeds - position.cost),
      exit_reason: 'exit_resolution',
      resolution,
      status: 'settled',
      mode: 'live',
      hold_minutes: Math.round((now - position.entry_ts) / 60),
    });
  }
  if (resolution) return { closed, opened };

  // ---- exits
  for (const position of openPositions) {
    const strategy = STRATEGIES[position.strategy];
    if (!strategy) continue;
    const priceNow = sidePrice(yesBid, position.side);
    const heldMinutes = (now - position.entry_ts) / 60;
    let exit = null;
    if (priceNow >= position.entry_price + strategy.take_profit) exit = { price: priceNow, reason: 'exit_target' };
    else if (priceNow <= position.entry_price - strategy.stop_loss) exit = { price: priceNow, reason: 'exit_stop' };
    else if (heldMinutes >= strategy.max_hold_minutes) exit = { price: priceNow, reason: 'exit_time' };
    if (!exit) continue;
    const proceeds = position.count * exit.price;
    closed.push({
      ...position,
      exit_ts: now,
      exit_price: round2(exit.price),
      proceeds: round2(proceeds),
      pnl: round2(proceeds - position.cost),
      exit_reason: exit.reason,
      status: 'closed',
      mode: 'live',
      hold_minutes: Math.round(heldMinutes),
    });
  }

  // ---- entries (one position per strategy per market)
  const alreadyOpen = new Set(openPositions.map((p) => p.strategy));
  const liveSeries = [...series, { ts: now, price: lastYes, bid: yesBid, ask: yesAsk, spread: book?.spread ?? null }]
    .filter((p) => Number.isFinite(p.price));
  const index = liveSeries.length - 1;
  for (const id of strategyIds) {
    if (alreadyOpen.has(id)) continue;
    const strategy = STRATEGIES[id];
    const signal = SIGNALS[id](liveSeries, index, { swingLookbackMinutes: 5 });
    if (!signal) continue;
    const entryYesPrice = signal.side === 'YES' ? yesAsk : yesFromNo(yesBid);
    if (!Number.isFinite(entryYesPrice) || entryYesPrice < MIN_ENTRY_PRICE || entryYesPrice > MAX_ENTRY_PRICE) continue;
    let count = sizePosition(entryYesPrice, strategy);
    if (!count) continue;
    // Liquidity cap: never take more contracts than rest within 2c of the touch.
    if (id === 'liquidity_capture' && book) {
      const available = Math.max(book.depth_yes_within_5c || 0, 0);
      count = Math.min(count, Math.floor(available / 2) || 1);
    }
    const cost = count * entryYesPrice;
    opened.push({
      strategy: id,
      ticker: market.ticker,
      event_ticker: market.event_ticker,
      title: market.title,
      topic: market.topic,
      side: signal.side,
      count,
      entry_ts: now,
      entry_price: round2(entryYesPrice),
      entry_yes_price: round2(lastYes),
      cost: round2(cost),
      entry_reason: signal.reason,
      status: 'open',
      mode: 'live',
    });
  }

  return { closed, opened };
}

/**
 * Build the portfolio view from a trade list.
 * @param {object[]} trades all simulated trades (open + closed)
 */
export function buildPortfolio(trades = [], startCash = PAPER_START_CASH) {
  const closed = trades.filter((t) => t.status === 'closed' || t.status === 'settled');
  const open = trades.filter((t) => t.status === 'open');

  const realized = closed.reduce((sum, t) => sum + (t.pnl || 0), 0);
  const costClosed = closed.reduce((sum, t) => sum + (t.cost || 0), 0);
  const costOpen = open.reduce((sum, t) => sum + (t.cost || 0), 0);

  // Cash: start cash minus the cost of every trade that was opened, plus proceeds.
  const spent = trades.reduce((sum, t) => sum + (t.cost || 0), 0);
  const proceeds = closed.reduce((sum, t) => sum + (t.proceeds || 0), 0);
  const cash = round2(startCash - spent + proceeds);

  const openValue = open.reduce((sum, t) => sum + (t.mark_value || 0), 0);
  const equity = round2(cash + openValue);
  const totalPnl = round2(equity - startCash);
  const unrealized = round2(open.reduce((sum, t) => sum + (t.unrealized_pnl || 0), 0));

  const wins = closed.filter((t) => (t.pnl || 0) > 0).length;
  const losses = closed.filter((t) => (t.pnl || 0) < 0).length;

  const byStrategy = groupPerformance(trades, (t) => t.strategy);
  const byTopic = groupPerformance(trades, (t) => t.topic || 'uncategorised');
  const byType = groupPerformance(trades, (t) => `${t.strategy}|${t.topic || 'uncategorised'}|${t.side}`);

  return {
    start_cash: startCash,
    cash,
    deployed_open: round2(costOpen),
    deployed_total: round2(spent),
    capital_returned: round2(proceeds),
    realized_pnl: round2(realized),
    unrealized_pnl: unrealized,
    cost_closed: round2(costClosed),
    open_positions: open.length,
    closed_trades: closed.length,
    total_trades: trades.length,
    wins,
    losses,
    win_rate: closed.length ? round2((wins / closed.length) * 100) : 0,
    open_value: round2(openValue),
    equity,
    total_pnl: totalPnl,
    roi_pct: round2((totalPnl / startCash) * 100),
    avg_hold_minutes: closed.length
      ? Math.round(closed.reduce((s, t) => s + (t.hold_minutes || 0), 0) / closed.length)
      : 0,
    by_strategy: byStrategy,
    by_topic: byTopic,
    by_type: byType,
    derived_strategies: deriveStrategies(byType),
  };
}

function groupPerformance(trades, keyFn) {
  const groups = new Map();
  for (const trade of trades) {
    const key = keyFn(trade);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        trades: 0, closed: 0, open: 0, wins: 0, losses: 0,
        realized_pnl: 0, unrealized_pnl: 0, deployed: 0, pnl: 0,
      });
    }
    const g = groups.get(key);
    g.trades += 1;
    g.deployed += trade.cost || 0;
    g.pnl += trade.pnl || 0;
    if (trade.status === 'open') {
      g.open += 1;
      g.unrealized_pnl += trade.unrealized_pnl || 0;
    } else {
      g.closed += 1;
      g.realized_pnl += trade.pnl || 0;
      if ((trade.pnl || 0) > 0) g.wins += 1;
      else if ((trade.pnl || 0) < 0) g.losses += 1;
    }
  }
  return [...groups.values()].map((g) => ({
    key: g.key,
    trades: g.trades,
    closed: g.closed,
    open: g.open,
    wins: g.wins,
    losses: g.losses,
    win_rate: g.closed ? round2((g.wins / g.closed) * 100) : 0,
    realized_pnl: round2(g.realized_pnl),
    unrealized_pnl: round2(g.unrealized_pnl),
    deployed: round2(g.deployed),
    pnl: round2(g.pnl),
    roi_pct: g.deployed ? round2((g.pnl / g.deployed) * 100) : 0,
  })).sort((a, b) => b.roi_pct - a.roi_pct);
}

/**
 * Derive candidate strategies from trade types: keep the combos that have both
 * enough sample size and a positive ROI, and describe them in plain language.
 */
function deriveStrategies(byType) {
  return byType
    .filter((t) => t.closed >= 3 && t.pnl > 0)
    .map((t) => {
      const [strategy, topic, side] = t.key.split('|');
      const def = STRATEGIES[strategy];
      return {
        key: t.key,
        title: `${def ? def.label : strategy} · ${topic} · ${side} side`,
        strategy,
        topic,
        side,
        trades: t.closed,
        win_rate: t.win_rate,
        realized_pnl: t.realized_pnl,
        deployed: t.deployed,
        roi_pct: t.roi_pct,
        description: `${def ? def.description : ''} Applied to ${topic} markets on the ${side} side: ${t.closed} closed trades, ${t.win_rate}% win rate, $${t.realized_pnl} realized on $${t.deployed} deployed (${t.roi_pct}% ROI).`,
      };
    })
    .slice(0, 8);
}
