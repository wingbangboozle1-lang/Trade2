// Pipeline test with a MOCKED Kalshi API. Fixture values below are SYNTHETIC test data
// (they are not Kalshi market data and are never published to the site). Endpoint shapes
// follow the official SDK models (kalshi-typescript@3.36.0).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { main, resolveTopicSeries } from '../collect.mjs';
import { takerFeeCents } from '../fees.mjs';
import { readFileSync } from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
const cfg = JSON.parse(readFileSync(path.join(here, '..', '..', 'config', 'topics.json'), 'utf8'));
const BASE = 'https://example.invalid/trade-api/v2'; // mock host; never contacted

const SERIES = [
  { ticker: 'KXAAAGASM', title: 'US gas price', category: 'Climate and Weather', categories: [], tags: [], fee_type: 'quadratic', fee_multiplier: 1, contract_url: 'https://kalshi.com/docs/example-contract.pdf', contract_terms_url: 'https://kalshi.com/docs/example-terms.pdf', settlement_sources: [{ name: 'SYNTHETIC SOURCE', url: 'https://example.invalid/source' }] },
  { ticker: 'KXBTCY', title: 'BTC price range EOY', category: 'Crypto', categories: ['Crypto'], tags: [], fee_type: 'quadratic', fee_multiplier: 0, contract_url: 'x', contract_terms_url: 'y', settlement_sources: [] },
  { ticker: 'KXNEWGOLF', title: 'Synthetic PGA invitational', category: 'Sports', categories: ['Sports'], tags: ['golf'], fee_type: 'quadratic', fee_multiplier: 1, contract_url: 'x', contract_terms_url: 'y', settlement_sources: [] },
  { ticker: 'KXUNRELATED', title: 'Weather in Denver', category: 'Climate', categories: [], tags: [], fee_type: 'quadratic', fee_multiplier: 1, contract_url: 'x', contract_terms_url: 'y', settlement_sources: [] },
];

function mkMarket(over) {
  return {
    ticker: 'T-1', event_ticker: 'E-1', market_type: 'binary', yes_sub_title: 'Yes outcome', status: 'active',
    open_time: '2026-11-01T00:00:00Z', close_time: '2026-12-01T00:00:00Z', yes_bid_dollars: '0.4000', yes_ask_dollars: '0.4200',
    no_bid_dollars: '0.5800', no_ask_dollars: '0.6000', last_price_dollars: '0.4100', volume_fp: '5000.00', volume_24h_fp: '500.00',
    open_interest_fp: '800.00', notional_value_dollars: '1.0000', result: '', rules_primary: 'synthetic rules', ...over,
  };
}

function makeMockApi(script) {
  // script: { run: number } drives which state the mock is in
  const calls = [];
  const fn = async (base, p, params = {}) => {
    calls.push(p);
    const ok = (data) => ({ data, url: `${base}${p}`, fetchedAt: 'x' });
    if (p === '/exchange/status') return ok({ exchange_active: true, trading_active: true });
    if (p === '/search/tags_by_categories') return ok({ tags_by_categories: { Crypto: ['bitcoin'] } });
    if (p === '/series') return ok({ series: SERIES });
    if (p === '/events') {
      if (params.series_ticker === 'KXAAAGASM' && script.gasSettled) {
        // after settlement the market is no longer 'open' so GET /events?status=open omits it
        return ok({ events: [], cursor: '' });
      }
      if (params.series_ticker === 'KXAAAGASM') {
        const price = script.gasLast ?? '0.4100';
        const ya = script.gasLast ? String(Number(script.gasLast) + 0.01) : '0.4200';
        return ok({
          events: [{ event_ticker: 'GAS-E1', series_ticker: 'KXAAAGASM', title: 'SYNTHETIC gas event', markets: [
            mkMarket({ ticker: 'GAS-E1-A', event_ticker: 'GAS-E1', last_price_dollars: price, yes_ask_dollars: ya, yes_bid_dollars: String((Number(ya) - 0.02).toFixed(4)), no_ask_dollars: (1 - Number(ya) + 0.02).toFixed(4), no_bid_dollars: (1 - Number(ya)).toFixed(4) }),
            mkMarket({ ticker: 'GAS-E1-B', status: 'closed', event_ticker: 'GAS-E1' }),
          ] }],
          cursor: '',
        });
      }
      if (params.series_ticker === 'KXNEWGOLF') {
        return ok({ events: [{ event_ticker: 'GOLF-E1', series_ticker: 'KXNEWGOLF', title: 'SYNTHETIC golf event', markets: [mkMarket({ ticker: 'GOLF-E1-A', event_ticker: 'GOLF-E1', volume_24h_fp: '10.00' })] }], cursor: '' });
      }
      return ok({ events: [], cursor: '' });
    }
    if (p.endsWith('/orderbook')) {
      return ok({ orderbook_fp: { yes_dollars: [['0.4000', '120.00'], ['0.3900', '40.00']], no_dollars: [['0.5800', '90.00']] } });
    }
    if (p === '/markets/GAS-E1-A') {
      return ok({ market: mkMarket({ ticker: 'GAS-E1-A', status: script.gasSettled ? 'determined' : 'closed', result: script.gasSettled ? 'yes' : '', settlement_ts: script.gasSettled ? '2026-11-20T10:00:00Z' : null }) });
    }
    if (p === '/markets/GAS-E1-B') return ok({ market: mkMarket({ ticker: 'GAS-E1-B', status: 'closed' }) });
    throw new Error(`unexpected mock call ${p}`);
  };
  return { fn, calls };
}

test('topic mapping: curated official rows + keyword discovery, unrelated series excluded', () => {
  const m = resolveTopicSeries(cfg, SERIES);
  assert.equal(m.get('KXAAAGASM').topic, 'gas');
  assert.match(m.get('KXAAAGASM').reason, /curated/);
  assert.equal(m.get('KXBTCY').topic, 'crypto');
  assert.equal(m.get('KXNEWGOLF').topic, 'golf');
  assert.match(m.get('KXNEWGOLF').reason, /keyword "golf"/);
  assert.equal(m.has('KXUNRELATED'), false);
});

test('pipeline: >= $0.10 move creates alert, high-ROI flag, simulated positions; resolution settles them', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'k-test-'));
  const stateDir = path.join(dir, 'state');
  const outDir = path.join(dir, 'out');
  const t0 = Date.parse('2026-11-20T12:00:00Z');

  // run 1: baseline price 41c, no alert expected
  const r1 = makeMockApi({ gasLast: undefined });
  await main({ base: BASE, stateDir, outDir, configPath: path.join(here, '..', '..', 'config', 'topics.json'), getFn: r1.fn, nowMs: t0 });
  let alerts = JSON.parse(await readFile(path.join(outDir, 'alerts.json'), 'utf8')).alerts;
  assert.equal(alerts.length, 0, 'no alert on first observation');

  // run 2: price jumps to 53c (+12c) within 30 minutes -> alert (up), entry ask 54c -> high-ROI false (entry > 40c)
  const r2 = makeMockApi({ gasLast: '0.5300' });
  await main({ base: BASE, stateDir, outDir, configPath: path.join(here, '..', '..', 'config', 'topics.json'), getFn: r2.fn, nowMs: t0 + 30 * 60e3 });
  alerts = JSON.parse(await readFile(path.join(outDir, 'alerts.json'), 'utf8')).alerts;
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].direction, 'up');
  assert.equal(alerts[0].delta_cents, 12);
  assert.equal(alerts[0].high_roi, false);
  let trades = JSON.parse(await readFile(path.join(outDir, 'trades.json'), 'utf8'));
  const opened = trades.positions.filter((p) => p.status === 'open');
  assert.equal(opened.length, 2, 'follow + fade open one position each; high-ROI rule does not (entry > 40c)');
  const follow = opened.find((p) => p.strategy === 'follow');
  assert.equal(follow.side, 'yes');
  assert.equal(follow.entry_cents, 54);
  assert.equal(follow.fee_cents, takerFeeCents(10, 54, 1)); // official formula, multiplier 1
  assert.equal(follow.cost_cents, follow.size * 54 + follow.fee_cents);
  const fade = opened.find((p) => p.strategy === 'fade');
  assert.equal(fade.side, 'no');

  // run 3: market resolves YES -> follow (YES) wins, fade (NO) loses
  const r3 = makeMockApi({ gasLast: '0.5300', gasSettled: true });
  await main({ base: BASE, stateDir, outDir, configPath: path.join(here, '..', '..', 'config', 'topics.json'), getFn: r3.fn, nowMs: t0 + 2 * 3600e3 });
  const resolved = JSON.parse(await readFile(path.join(outDir, 'resolved.json'), 'utf8')).resolved;
  assert.equal(resolved.length, 1);
  assert.equal(resolved[0].result, 'yes');
  assert.equal(resolved[0].ticker, 'GAS-E1-A');
  trades = JSON.parse(await readFile(path.join(outDir, 'trades.json'), 'utf8'));
  const settledFollow = trades.positions.find((p) => p.strategy === 'follow' && p.ticker === 'GAS-E1-A');
  assert.equal(settledFollow.status, 'settled');
  assert.equal(settledFollow.payout_cents, 10 * 100);
  assert.equal(settledFollow.pnl_cents, 1000 - settledFollow.cost_cents);
  const settledFade = trades.positions.find((p) => p.strategy === 'fade' && p.ticker === 'GAS-E1-A');
  assert.equal(settledFade.payout_cents, 0);
  assert.equal(settledFade.pnl_cents, -settledFade.cost_cents);
});

test('high-ROI rule flags a small-entry alert with tight spread and enough volume', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'k-test2-'));
  const t0 = Date.parse('2026-11-20T12:00:00Z');
  // Build the alert logic directly through the exported pipeline by simulating two runs
  const a = makeMockApi({ gasLast: '0.2000' });
  await main({ base: BASE, stateDir: path.join(dir, 's'), outDir: path.join(dir, 'o'), configPath: path.join(here, '..', '..', 'config', 'topics.json'), getFn: a.fn, nowMs: t0 });
  const b = makeMockApi({ gasLast: '0.3100' }); // +11c, ask 0.32 <= 40c, spread 2c, volume 500
  await main({ base: BASE, stateDir: path.join(dir, 's'), outDir: path.join(dir, 'o'), configPath: path.join(here, '..', '..', 'config', 'topics.json'), getFn: b.fn, nowMs: t0 + 10 * 60e3 });
  const alerts = JSON.parse(await readFile(path.join(dir, 'o', 'alerts.json'), 'utf8')).alerts;
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].high_roi, true);
});

test('capSeries keeps curated series first, then highest-volume keyword matches, up to max', async () => {
  const { capSeries } = await import('../collect.mjs');
  const m = new Map();
  m.set('CUR1', { topic: 'gas', series: { ticker: 'CUR1', volume_fp: '1' }, reason: 'curated: official fee schedule row "x"' });
  m.set('KW_LOW', { topic: 'culture', series: { ticker: 'KW_LOW', volume_fp: '5' }, reason: 'keyword "emmy"' });
  m.set('KW_HIGH', { topic: 'culture', series: { ticker: 'KW_HIGH', volume_fp: '900' }, reason: 'keyword "emmy"' });
  const out = capSeries(m, 2);
  assert.deepEqual([...out.keys()], ['CUR1', 'KW_HIGH']);
  assert.equal(capSeries(m, 10), m, 'no change when under the cap');
});
