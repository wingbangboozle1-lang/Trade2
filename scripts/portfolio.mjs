#!/usr/bin/env node
// READ-ONLY demo-account snapshot. Places NO orders.
//
//   KALSHI_DEMO_KEY_ID=... KALSHI_DEMO_PRIVATE_KEY="$(cat key.pem)" node scripts/portfolio.mjs --out _site/data
//
// Without both secrets it writes { connected: false } so the site can say so (see Flagged for Review, F-08).
// Refuses any host that is not a Kalshi demo host, because demo keys only work on demo endpoints (S3).
//
// Endpoints (official SDK paths, docs/PortfolioApi.md):  GET /portfolio/balance, GET /portfolio/positions
// Response fields: GetBalanceResponse {balance, balance_dollars, portfolio_value, updated_ts}
//                  GetPositionsResponse {market_positions[], event_positions[], cursor}
//                  MarketPosition {ticker, position_fp, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars, total_traded_dollars, last_updated_ts}

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
    position_fp: p.position_fp,
    market_exposure_dollars: p.market_exposure_dollars,
    realized_pnl_dollars: p.realized_pnl_dollars,
    fees_paid_dollars: p.fees_paid_dollars,
    total_traded_dollars: p.total_traded_dollars,
    last_updated_ts: p.last_updated_ts,
    source_url: `${base}/markets/${p.ticker}`,
  }));
  return {
    connected: true,
    generated_at: new Date(nowMs).toISOString(),
    environment: 'Kalshi demo (mock funds)',
    balance_dollars: bal.data.balance_dollars,
    portfolio_value_cents: bal.data.portfolio_value,
    balance_updated_ts: bal.data.updated_ts,
    positions,
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
