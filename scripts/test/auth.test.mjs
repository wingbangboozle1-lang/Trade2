// Offline tests for request signing (scripts/kalshi-auth.mjs) and the read-only portfolio module.
// Keys here are generated at test time; no real credentials are used.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { signHeaders, verifyHeaders, preSignText, loadPrivateKey } from '../kalshi-auth.mjs';
import { snapshot } from '../portfolio.mjs';

const URL_WITH_QUERY = 'https://external-api.demo.kalshi.co/trade-api/v2/portfolio/orders?limit=5';

test('pre-sign text is timestamp + METHOD + path without query (docs: api_keys, api_environments)', () => {
  assert.equal(preSignText(1700000000000, 'get', URL_WITH_QUERY), '1700000000000GET/trade-api/v2/portfolio/orders');
});

test('Ed25519 signature verifies against the same pre-sign text', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
  const pem = privateKey.export({ type: 'pkcs8', format: 'pem' });
  const h = signHeaders({ keyId: 'test-key-id', privateKey: loadPrivateKey(pem), method: 'GET', fullUrl: URL_WITH_QUERY, nowMs: 1700000000123 });
  assert.equal(h['KALSHI-ACCESS-KEY'], 'test-key-id');
  assert.equal(h['KALSHI-ACCESS-TIMESTAMP'], '1700000000123');
  assert.equal(Buffer.from(h['KALSHI-ACCESS-SIGNATURE'], 'base64').length, 64); // Ed25519 signatures are 64 bytes (docs)
  assert.equal(verifyHeaders({ publicKey, method: 'GET', fullUrl: URL_WITH_QUERY, headers: h }), true);
  // tampering with the path must fail
  assert.equal(verifyHeaders({ publicKey, method: 'GET', fullUrl: URL_WITH_QUERY.replace('orders', 'balance'), headers: h }), false);
});

test('RSA-PSS SHA-256 signature verifies (salt length = digest length)', () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const pem = privateKey.export({ type: 'pkcs1', format: 'pem' }); // PKCS#1 RSA PEM, as Kalshi generates
  const h = signHeaders({ keyId: 'rsa-id', privateKey: loadPrivateKey(pem), method: 'GET', fullUrl: 'https://external-api.demo.kalshi.co/trade-api/v2/portfolio/balance', nowMs: 1700000000999 });
  assert.equal(Buffer.from(h['KALSHI-ACCESS-SIGNATURE'], 'base64').length, 256);
  assert.equal(verifyHeaders({ publicKey, method: 'GET', fullUrl: 'https://external-api.demo.kalshi.co/trade-api/v2/portfolio/balance', headers: h }), true);
});

test('portfolio: without secrets, reports not connected and makes no request', async () => {
  let called = false;
  const out = await snapshot({ keyId: undefined, pem: undefined, fetchImpl: async () => { called = true; throw new Error('no'); } });
  assert.equal(out.connected, false);
  assert.equal(called, false);
});

test('portfolio: refuses a production host even when secrets exist', async () => {
  const { privateKey } = crypto.generateKeyPairSync('ed25519');
  const pem = privateKey.export({ type: 'pkcs8', format: 'pem' });
  await assert.rejects(snapshot({ base: 'https://external-api.kalshi.com/trade-api/v2', keyId: 'x', pem, fetchImpl: async () => { throw new Error('should not be called'); } }), /not a demo host/);
});
