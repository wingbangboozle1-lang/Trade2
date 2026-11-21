#!/usr/bin/env node
// READ-ONLY demo-account snapshot. Places NO orders.
//
//   KALSHI_DEMO_KEY_ID=... KALSHI_DEMO_PRIVATE_KEY="$(cat key.pem)" node scripts/portfolio.mjs --out _site/data
//
// Without both secrets it writes { connected: false } so the site can say so (see Flagged for Review, F-08).
// Refuses any host that is not a Kalshi demo host, because demo keys only work on demo endpoints (S3).
//
// Endpoints (official docs, opened 2026-11-21 by session arena-8a8d4294):
//   GET /portfolio/balance    https://docs.kalshi.com/api-reference/portfolio/get-balance
//       "Returns the balance and portfolio value for a member. Both values include all exchange
//        indexes unless `exchange_index` is provided."  -> this snapshot asks for no exchange_index
//       and no subaccount, i.e. the aggregate of index 0..n, primary account.
//       Response: {balance, balance_dollars, portfolio_value, updated_ts, balance_breakdown[{exchange_index, balance}]}
//   GET /portfolio/positions  https://docs.kalshi.com/api-reference/portfolio/get-positions
//       "Returns unsettled positions by default, including closed markets awaiting determination or
//        settlement."  -> settlement_status is deliberately NOT sent, so the default is used.
//       Response: {market_positions[{ticker, exchange_index, total_traded_dollars, position_fp, market_exposure_dollars,
//                  realized_pnl_dollars, fees_paid_dollars, last_updated_ts, netting_enabled}],
//                  event_positions[{event_ticker, total_cost_dollars, total_cost_shares_fp, event_exposure_dollars,
//                  realized_pnl_dollars, fees_paid_dollars}], cursor}
// Values are published exactly as the API returns them. The docs do not state a unit for the integer
// `balance` / `portfolio_value` on this page, so they are NOT converted to dollars here (see flag F-26).

import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { DEMO_BASE } from './kalshi.mjs';
import { loadPrivateKey, signHeaders } from './kalshi-auth.mjs';

const argv = process.argv.slice(2);
const outIdx = argv.indexOf('--out');
const OUT = outIdx >= 0 ? argv[outIdx + 1] : './_site/data';
const BASE = process.env.KALSHI_DEMO_BASE || DEMO_BASE;

export async function snapshot({ base = BASE, keyId = process.env.KALSHI_DEMO_KEY_ID, pem = process.env.KALSHI_DEMO_PRIVATE_KEY, fetchImpl = fetch, nowMs = Date.now() } = {}) {
  if (!keyId || !pem) {
    return { connected: false, reason: 'KALSHI_DEMO_KEY_ID and KALSHI_DEMO_PRIVATE_KEY secrets are not set.', generated_at: new Date(nowMs).toISOString() };
  }
  if (!/demo/.test(new URL(base).hostname)) {
    throw new Error(`Refusing portfolio read: ${base} is not a demo host`);
  }
  const key = loadPrivateKey(pem);
  const get = async (p) => {
    const url = `${base}${p}`;
    const headers = signHeaders({ keyId, privateKey: key, method: 'GET', fullUrl: url, nowMs: Date.now() });
    const res = await fetchImpl(url, { headers: { ...headers, Accept: 'application/json' }, signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error(`GET ${p} -> HTTP ${res.status}`);
    return { data: await res.json(), url };
  };
  const bal = await get('/portfolio/balance');
  const pos = await get('/portfolio/positions?limit=200');
  const positions = (pos.data.market_positions || []).map((p) => ({
    ticker: p.ticker,
    exchange_index: p.exchange_index ?? null,
    position_fp: p.position_fp,
    market_exposure_dollars: p.market_exposure_dollars,
    realized_pnl_dollars: p.realized_pnl_dollars,
    fees_paid_dollars: p.fees_paid_dollars,
    total_traded_dollars: p.total_traded_dollars,
    last_updated_ts: p.last_updated_ts,
    netting_enabled: p.netting_enabled ?? null,
    source_url: `${base}/markets/${p.ticker}`,
  }));
  const eventPositions = (pos.data.event_positions || []).map((e) => ({
    event_ticker: e.event_ticker,
    total_cost_dollars: e.total_cost_dollars,
    total_cost_shares_fp: e.total_cost_shares_fp,
    event_exposure_dollars: e.event_exposure_dollars,
    realized_pnl_dollars: e.realized_pnl_dollars,
    fees_paid_dollars: e.fees_paid_dollars,
    source_url: `${base}/events/${e.event_ticker}`,
  }));
  return {
    connected: true,
    generated_at: new Date(nowMs).toISOString(),
    environment: 'Kalshi demo (mock funds) — read-only snapshot, no orders placed',
    balance_dollars: bal.data.balance_dollars ?? null,
    balance: bal.data.balance ?? null,
    portfolio_value: bal.data.portfolio_value ?? null,
    balance_updated_ts: bal.data.updated_ts ?? null,
    balance_breakdown: (bal.data.balance_breakdown || []).map((b) => ({
      exchange_index: b.exchange_index ?? null,
      balance: b.balance ?? null,
    })),
    positions,
    event_positions: eventPositions,
    positions_cursor: pos.data.cursor || null,
    note: 'market_positions are the API default (settlement_status=unsettled): closed markets awaiting settlement can appear with non-zero quantities.',
    fields: {
      balance: 'https://docs.kalshi.com/api-reference/portfolio/get-balance',
      positions: 'https://docs.kalshi.com/api-reference/portfolio/get-positions',
    },
    source_urls: [bal.url, pos.url],
  };
}

if (process.argv[1] && import.meta.url === new URL(`file://${path.resolve(process.argv[1])}`).href) {
  snapshot().then(async (out) => {
    await mkdir(OUT, { recursive: true });
    await writeFile(path.join(OUT, 'portfolio.json'), JSON.stringify(out, null, 1));
    console.log(out.connected ? `portfolio: ${out.positions.length} positions` : `portfolio: not connected (${out.reason})`);
  }).catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
}
