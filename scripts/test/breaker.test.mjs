// Offline tests for the run-wide circuit breaker in scripts/kalshi.mjs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getPublic, configureBreaker, breakerTripped, KalshiNetworkBreaker } from '../kalshi.mjs';

test('breaker trips after consecutive network errors and stops further calls', async () => {
  configureBreaker({ limit: 3, deadlineMs: Infinity });
  let calls = 0;
  const fetchImpl = async () => { calls++; throw new TypeError('fetch failed'); };
  const opts = { fetchImpl, retries: 0, minGapMs: 0 };
  for (let i = 0; i < 3; i++) {
    await assert.rejects(getPublic('https://x.invalid/trade-api/v2', '/exchange/status', {}, opts));
  }
  assert.equal(breakerTripped(), true);
  const before = calls;
  await assert.rejects(getPublic('https://x.invalid/trade-api/v2', '/exchange/status', {}, opts), KalshiNetworkBreaker);
  assert.equal(calls, before, 'no request is sent after the breaker trips');
});

test('a successful response resets the consecutive-error count', async () => {
  configureBreaker({ limit: 3, deadlineMs: Infinity });
  let n = 0;
  const fetchImpl = async () => {
    n++;
    if (n % 2 === 1) throw new TypeError('flaky');
    return { ok: true, status: 200, headers: new Map(), json: async () => ({ ok: 1 }) };
  };
  for (let i = 0; i < 4; i++) {
    await getPublic('https://x.invalid/trade-api/v2', '/exchange/status', {}, { fetchImpl, retries: 1, minGapMs: 0 }).catch(() => {});
  }
  assert.equal(breakerTripped(), false);
});
