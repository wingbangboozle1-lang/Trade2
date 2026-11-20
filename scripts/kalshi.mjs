// Minimal client for the PUBLIC Kalshi Trade API (no authentication).
// Endpoint paths and parameter names are taken from the official SDK generated from
// Kalshi's OpenAPI spec (kalshi-typescript@3.36.0, https://www.npmjs.com/package/kalshi-typescript)
// and the official docs pages listed in SOURCES.md.
//
// Public market-data endpoints (no auth, per the SDK's "No authorization required"):
//   GET /exchange/status, GET /series, GET /events, GET /markets/{ticker},
//   GET /markets/{ticker}/orderbook, GET /search/tags_by_categories

export const PRODUCTION_BASE = 'https://external-api.kalshi.com/trade-api/v2';
export const DEMO_BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';

export class KalshiHttpError extends Error {
  constructor(status, url, body) {
    super(`Kalshi HTTP ${status} for ${url}: ${body?.slice?.(0, 300) ?? ''}`);
    this.status = status;
    this.url = url;
    this.body = body;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * GET a public JSON endpoint with retry/backoff for 429 and 5xx.
 * @returns {Promise<{data:any, url:string, fetchedAt:string}>}
 */
export class KalshiNetworkBreaker extends Error {}

// Run-wide circuit breaker: after too many consecutive network failures the whole run stops
// (so a blocked or down host cannot hang a scheduled job for an hour).
const breaker = { consecutiveNetworkErrors: 0, limit: 6, deadlineMs: Infinity, tripped: false };
export function configureBreaker({ limit = 6, deadlineMs = Infinity } = {}) {
  breaker.consecutiveNetworkErrors = 0;
  breaker.limit = limit;
  breaker.deadlineMs = deadlineMs;
  breaker.tripped = false;
}
export function breakerTripped() {
  return breaker.tripped;
}

export async function getPublic(base, path, params = {}, opts = {}) {
  const { retries = 3, timeoutMs = 15000, minGapMs = 150, fetchImpl = fetch } = opts;
  if (breaker.tripped) throw new KalshiNetworkBreaker('circuit breaker already tripped');
  if (Date.now() > breaker.deadlineMs) {
    breaker.tripped = true;
    throw new KalshiNetworkBreaker('run deadline exceeded');
  }
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '' || v === false) continue;
    qs.set(k, String(v));
  }
  const url = `${base.replace(/\/+$/, '')}${path}${qs.toString() ? `?${qs}` : ''}`;
  let attempt = 0;
  for (;;) {
    attempt++;
    let res;
    try {
      res = await fetchImpl(url, {
        method: 'GET',
        headers: { Accept: 'application/json', 'User-Agent': 'trade2-dashboard/1.0 (public read-only)' },
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (err) {
      if (++breaker.consecutiveNetworkErrors >= breaker.limit) {
        breaker.tripped = true;
        throw new KalshiNetworkBreaker(`${breaker.limit} consecutive network errors; last: ${err.message}`);
      }
      if (attempt > retries) throw err;
      await sleep(backoff(attempt));
      continue;
    }
    breaker.consecutiveNetworkErrors = 0;
    if (res.ok) {
      const data = await res.json();
      if (minGapMs) await sleep(minGapMs);
      return { data, url, fetchedAt: new Date().toISOString() };
    }
    const text = await res.text().catch(() => '');
    const retriable = res.status === 429 || res.status >= 500;
    if (!retriable || attempt > retries) throw new KalshiHttpError(res.status, url, text);
    const ra = Number(res.headers.get('retry-after'));
    await sleep(Number.isFinite(ra) && ra > 0 ? ra * 1000 : backoff(attempt));
  }
}

function backoff(attempt) {
  return Math.min(30000, 1000 * 2 ** attempt);
}
