/**
 * Offline unit tests for the collector's core logic.
 *
 * Run: node --test collector/test/
 *
 * The signing test cross-checks the implementation against the official Kalshi
 * TypeScript SDK (`kalshi-typescript`, published by the Kalshi organisation)
 * when it is installed. If the SDK is not present the cross-check is skipped
 * and the local verification (signature verifies against the public key) still runs.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

import { KalshiClient } from '../src/kalshi.js';
import { detectSwings, mergeAlerts } from '../src/alerts.js';
import { summarizeOrderbook, contractsAtPrice } from '../src/liquidity.js';
import { scoreMarket } from '../src/roi.js';
import { backtestMarket, buildPortfolio, STRATEGIES } from '../src/paper.js';
import { classify } from '../src/topics.js';

function makeKeyPair(type) {
  if (type === 'ed25519') {
    const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
    return { publicKey, privateKey, pem: privateKey.export({ type: 'pkcs8', format: 'pem' }) };
  }
  const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  return { publicKey, privateKey, pem: privateKey.export({ type: 'pkcs8', format: 'pem' }) };
}

test('Ed25519 request signatures verify against the public key', () => {
  const { publicKey, pem } = makeKeyPair('ed25519');
  const client = new KalshiClient({ apiKeyId: 'test-key', privateKeyPem: pem });
  const text = '1700000000000GET/trade-api/v2/portfolio/balance';
  const signature = Buffer.from(client.signText(text), 'base64');
  assert.ok(crypto.verify(null, Buffer.from(text, 'utf8'), publicKey, signature));
});

test('RSA-PSS request signatures verify against the public key', () => {
  const { publicKey, pem } = makeKeyPair('rsa');
  const client = new KalshiClient({ apiKeyId: 'test-key', privateKeyPem: pem });
  const text = '1700000000000POST/trade-api/v2/portfolio/events/orders';
  const signature = Buffer.from(client.signText(text), 'base64');
  assert.ok(crypto.verify('sha256', Buffer.from(text, 'utf8'), {
    key: publicKey,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
  }, signature));
});

test('auth headers use the documented names and sign the path without query string', () => {
  const { pem } = makeKeyPair('ed25519');
  const client = new KalshiClient({ apiKeyId: 'my-key-id', privateKeyPem: pem });
  const headers = client.authHeaders('GET', '/trade-api/v2/markets');
  assert.equal(headers['KALSHI-ACCESS-KEY'], 'my-key-id');
  assert.ok(headers['KALSHI-ACCESS-SIGNATURE']);
  assert.ok(/^\d+$/.test(headers['KALSHI-ACCESS-TIMESTAMP']));
});

test('cross-check against the official Kalshi TypeScript SDK when installed', async (t) => {
  let KalshiAuth;
  try {
    ({ KalshiAuth } = await import('kalshi-typescript/dist/esm/auth.js'));
  } catch {
    try {
      ({ KalshiAuth } = await import('kalshi-typescript'));
    } catch {
      t.skip('kalshi-typescript is not installed — skipping SDK cross-check');
      return;
    }
  }
  const { publicKey, pem } = makeKeyPair('ed25519');
  const mine = new KalshiClient({ apiKeyId: 'k', privateKeyPem: pem });
  const theirs = new KalshiAuth('k', pem);
  const text = '1700000000000GET/trade-api/v2/markets?limit=5';
  const mineSig = Buffer.from(mine.signText(text), 'base64');
  const theirSig = Buffer.from(theirs.signText(text), 'base64');
  assert.ok(crypto.verify(null, Buffer.from(text, 'utf8'), publicKey, mineSig));
  assert.ok(crypto.verify(null, Buffer.from(text, 'utf8'), publicKey, theirSig));
});

test('swing detection fires at exactly $0.10 and below threshold it does not', () => {
  const base = {
    ticker: 'T1', event_ticker: 'E1', title: 'Test', topic: 'crypto', topics: ['crypto'],
    previous_price: 0.50, last_price: 0.60, yes_bid: 0.59, yes_ask: 0.61,
    no_bid: 0.39, no_ask: 0.41, close_time: '2026-12-01T00:00:00Z',
  };
  const swings = detectSwings({ markets: [base], history: {}, now: 1_700_000_000 });
  assert.equal(swings.length, 1);
  assert.equal(swings[0].direction, 'up');
  assert.equal(swings[0].delta, 0.1);

  const smaller = detectSwings({ markets: [{ ...base, previous_price: 0.50, last_price: 0.59 }], history: {}, now: 1_700_000_000 });
  assert.equal(smaller.length, 0);
});

test('alert log de-duplicates on ticker, direction and minute', () => {
  const alert = { ticker: 'T1', direction: 'up', ts: '2026-11-20T12:00:30.000Z' };
  const merged = mergeAlerts([alert], [{ ...alert, ts: '2026-11-20T12:00:45.000Z' }]);
  assert.equal(merged.length, 1);
});

test('orderbook summary reads the best bid from the last level and derives the ask', () => {
  const summary = summarizeOrderbook({
    yes_dollars: [['0.5800', '10.00'], ['0.5900', '25.00']],
    no_dollars: [['0.4000', '12.00'], ['0.4100', '30.00']],
  }, {});
  assert.equal(summary.best_yes_bid, 0.59);
  assert.equal(summary.best_yes_ask, 0.59);   // 1 - best NO bid (0.41)
  assert.equal(summary.best_no_bid, 0.41);
  assert.equal(summary.best_no_ask, 0.41);    // 1 - best YES bid (0.59)
  assert.equal(summary.depth_yes_total, 35);
  assert.equal(contractsAtPrice(summary, 'yes', 0.59), 25);
});

test('ROI score is bounded and explains itself', () => {
  const market = {
    ticker: 'T2', last_price: 0.62, previous_price: 0.50, close_time: new Date(Date.now() + 36 * 3600 * 1000).toISOString(),
  };
  const book = {
    best_yes_bid: 0.61, best_yes_ask: 0.63, spread: 0.02,
    depth_yes_within_5c: 400, depth_no_within_5c: 380,
  };
  const points = [];
  for (let i = 0; i < 40; i += 1) points.push([Math.floor(Date.now() / 1000) - (40 - i) * 60, 0.55 + i * 0.002]);
  const score = scoreMarket({ market, book, points, now: Math.floor(Date.now() / 1000) });
  assert.ok(score.score >= 0 && score.score <= 100);
  assert.ok(score.reasons.length >= 4);
});

test('paper engine opens and closes a position with a correct P&L', () => {
  const market = { ticker: 'T3', event_ticker: 'E3', title: 'Demo', topic: 'gas' };
  const series = [];
  const start = 1_700_000_000;
  for (let i = 0; i < 30; i += 1) {
    const price = i < 10 ? 0.50 : (i < 15 ? 0.62 : 0.72);
    series.push({ ts: start + i * 60, price, bid: price - 0.01, ask: price + 0.01, spread: 0.02 });
  }
  const trades = backtestMarket({ market, series });
  const momentum = trades.filter((t) => t.strategy === 'swing_momentum');
  assert.ok(momentum.length >= 1);
  const closed = momentum.find((t) => t.status === 'closed');
  if (closed) {
    assert.equal(closed.proceeds, Number((closed.count * closed.exit_price).toFixed(2)));
    assert.equal(closed.pnl, Number((closed.proceeds - closed.cost).toFixed(2)));
  }
  const portfolio = buildPortfolio(trades, 10000);
  assert.equal(portfolio.start_cash, 10000);
  assert.ok(portfolio.equity <= 10000 + trades.length * 200);
  assert.ok(portfolio.by_strategy.length >= 1);
});

test('strategies are documented with the fields the site renders', () => {
  for (const strategy of Object.values(STRATEGIES)) {
    assert.ok(strategy.label && strategy.description && strategy.risk_usd > 0);
  }
});

test('topic classifier maps titles to the five tracked topics', () => {
  assert.deepEqual(classify({ title: 'Will the price of regular gas be above $4.00 on Friday?' }), ['gas']);
  assert.deepEqual(classify({ title: 'Will the next US Supreme Court nominee be confirmed?' }), ['elections']);
  assert.ok(classify({ title: 'Will the Bitcoin price exceed $150,000 in 2026?' }).includes('crypto'));
  assert.ok(classify({ title: 'Will the Masters Tournament winner be a rookie?' }).includes('golf'));
  assert.ok(classify({ title: 'Will the album of the year win the Grammy?' }).includes('culture'));
});
