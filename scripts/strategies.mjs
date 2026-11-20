// SIMULATED (paper) trading. No real orders are placed by this module.
//
// Each run, every new price-move alert (>= $0.10 move between consecutive collector runs)
// can open a simulated position under each strategy below. Fills are assumed at the
// market's reported ask for the side bought (yes_ask_dollars / no_ask_dollars), for a fixed
// size, with the official taker fee (scripts/fees.mjs). Positions settle at $1.00 per contract
// for the winning side and $0.00 otherwise, using the market's official `result` ("yes" / "no").
// Settlement has no settlement fee (Kalshi Fee Schedule: "There is no settlement fee.").
//
// Limits (documented on the site): no slippage beyond the reported ask, no queue position,
// no order-book depth enforcement in this version. All money is integer cents.

import { takerFeeCents, dollarsToCents } from './fees.mjs';

export const SIM_SIZE_CONTRACTS = 10;
export const COOLDOWN_MS = 60 * 60 * 1000; // at most one open simulated position per strategy+market per hour

export const STRATEGIES = [
  {
    id: 'follow',
    name: 'Follow big moves',
    description: 'After a move of at least $0.10, buy the side the price moved toward (YES after an up-move, NO after a down-move).',
  },
  {
    id: 'fade',
    name: 'Fade big moves',
    description: 'After a move of at least $0.10, buy the opposite side (NO after an up-move, YES after a down-move).',
  },
  {
    id: 'high_roi_rule',
    name: 'High-ROI rule (heuristic)',
    description: 'Only for alerts flagged High-ROI by the rule in config/topics.json (entry <= $0.40, spread <= $0.05, 24h volume >= 100). Buys the side the move points to.',
  },
];

/** Side and entry price for a strategy given an alert and the current market snapshot. */
export function signalFor(strategyId, alert, market, cfg) {
  const upSide = alert.direction === 'up' ? 'yes' : 'no';
  const side = strategyId === 'fade' ? (upSide === 'yes' ? 'no' : 'yes') : upSide;
  const entry = side === 'yes' ? dollarsToCents(market.yes_ask_dollars) : dollarsToCents(market.no_ask_dollars);
  if (entry === null || entry < 1 || entry > 99) return null;
  if (strategyId === 'high_roi_rule') {
    if (!alert.high_roi) return null;
    if (entry > cfg.high_roi_rule.max_entry_price_cents) return null;
  }
  return { side, entry };
}

export function bandOf(entryCents) {
  if (entryCents < 25) return '<25c';
  if (entryCents < 50) return '25-49c';
  if (entryCents < 75) return '50-74c';
  return '75c+';
}

/**
 * Open simulated positions for new alerts.
 * @param {object} state   state.positions (array) is mutated
 * @param {object[]} alerts  alerts created in THIS run
 * @param {Map<string,object>} marketsByTicker  current market rows (from this run)
 * @param {object} cfg     topics config
 * @param {number} nowMs
 */
export function openPositions(state, alerts, marketsByTicker, cfg, nowMs) {
  const opened = [];
  for (const alert of alerts) {
    const market = marketsByTicker.get(alert.ticker);
    if (!market) continue;
    for (const strat of STRATEGIES) {
      const sig = signalFor(strat.id, alert, market, cfg);
      if (!sig) continue;
      const recent = state.positions.find(
        (p) => p.strategy === strat.id && p.ticker === alert.ticker && nowMs - p.opened_ms < COOLDOWN_MS,
      );
      if (recent) continue;
      // Fee uses the series' own fee_type / fee_multiplier (from the API's Series object, which mirrors the
      // official Kalshi Fee Schedule). 'flat' fee types use a separate table not implemented here -> skip & flag.
      if (market.fee_type === 'flat' || market.fee_multiplier === undefined || market.fee_multiplier === null) continue;
      const size = SIM_SIZE_CONTRACTS;
      const fee = takerFeeCents(size, sig.entry, market.fee_multiplier);
      const cost = size * sig.entry + fee;
      const pos = {
        id: `${strat.id}-${alert.ticker}-${nowMs}`,
        strategy: strat.id,
        topic: alert.topic,
        ticker: alert.ticker,
        event_ticker: alert.event_ticker,
        event_title: alert.event_title,
        outcome_label: alert.outcome_label,
        side: sig.side,
        size,
        entry_cents: sig.entry,
        fee_cents: fee,
        cost_cents: cost,
        opened_ms: nowMs,
        opened_at: new Date(nowMs).toISOString(),
        trigger_alert_id: alert.id,
        trigger_direction: alert.direction,
        band: bandOf(sig.entry),
        category: `${alert.topic} · ${alert.direction === 'up' ? 'up-move' : 'down-move'} · ${bandOf(sig.entry)}`,
        status: 'open',
        result: null,
        payout_cents: null,
        pnl_cents: null,
        settled_ms: null,
        source_url: alert.source_url,
      };
      state.positions.push(pos);
      opened.push(pos);
    }
  }
  return opened;
}

/** Settle open positions whose market has an official result, and mark the rest to bid. */
export function updatePositions(state, marketsByTicker, resolvedByTicker, nowMs) {
  for (const p of state.positions) {
    if (p.status === 'open') {
      const res = resolvedByTicker.get(p.ticker);
      if (res && (res.result === 'yes' || res.result === 'no')) {
        p.status = 'settled';
        p.result = res.result;
        p.payout_cents = p.side === res.result ? p.size * 100 : 0;
        p.pnl_cents = p.payout_cents - p.cost_cents;
        p.settled_ms = nowMs;
        p.settled_at = new Date(nowMs).toISOString();
        p.mark_cents = null;
        p.unrealized_cents = null;
        continue;
      }
      const m = marketsByTicker.get(p.ticker);
      const bid = m ? dollarsToCents(p.side === 'yes' ? m.yes_bid_dollars : m.no_bid_dollars) : null;
      if (bid !== null) {
        p.mark_cents = bid;
        p.unrealized_cents = p.size * bid - p.cost_cents; // liquidation at bid, before any exit fee
        p.marked_ms = nowMs;
      }
    }
  }
}

/** Per-strategy and per-category totals (all integer cents, converted to dollars for display). */
export function summarize(positions) {
  const roll = (rows) => {
    const out = { trades: 0, open: 0, settled: 0, wins: 0, cost_cents: 0, settled_cost_cents: 0, realized_cents: 0, unrealized_cents: 0 };
    for (const p of rows) {
      out.trades++;
      out.cost_cents += p.cost_cents;
      if (p.status === 'open') {
        out.open++;
        out.unrealized_cents += p.unrealized_cents ?? 0;
      } else {
        out.settled++;
        out.settled_cost_cents += p.cost_cents;
        out.realized_cents += p.pnl_cents;
        if (p.pnl_cents > 0) out.wins++;
      }
    }
    out.win_rate = out.settled ? out.wins / out.settled : null;
    out.roi_settled = out.settled_cost_cents ? out.realized_cents / out.settled_cost_cents : null;
    return out;
  };
  const byStrategy = STRATEGIES.map((s) => ({ id: s.id, name: s.name, description: s.description, ...roll(positions.filter((p) => p.strategy === s.id)) }));
  const cats = [...new Set(positions.map((p) => p.category))].sort();
  const byCategory = cats.map((c) => ({ category: c, ...roll(positions.filter((p) => p.category === c)) }));
  return { byStrategy, byCategory, overall: roll(positions) };
}
