/**
 * Cross-origin (CORS) probe for the Kalshi demo REST API.
 *
 * The site can optionally upgrade from the committed snapshot to direct
 * browser polling. Whether a browser is *allowed* to do that is a property
 * of the Kalshi API's CORS policy, not of this repository — so we measure it
 * from the collector instead of guessing.
 *
 * The probe issues the same preflight a browser would send for a cross-origin
 * GET (OPTIONS + Origin + Access-Control-Request-Method) and reports the
 * response headers verbatim. The result is published in
 * `docs/data/collector-health.json` so the site can state the measured
 * outcome rather than an assumption.
 */

/** Origins the published site can be served from. */
export const PROBE_ORIGINS = [
  'https://wingbangboozle1-lang.github.io',
  'https://wingbangboozle1-lang.github.io/Trade2',
];

/**
 * @param {string} baseUrl Kalshi REST base, e.g. https://external-api.demo.kalshi.co/trade-api/v2
 * @param {object} [options]
 * @param {string[]} [options.origins] origins to test
 * @param {string} [options.path] a cheap GET path to preflight
 * @param {number} [options.timeoutMs]
 * @returns {Promise<object>} structured probe result
 */
export async function probeCors(baseUrl, options = {}) {
  const {
    origins = PROBE_ORIGINS,
    path = '/markets',
    timeoutMs = 15000,
  } = options;

  const results = [];
  for (const origin of origins) {
    const url = `${baseUrl.replace(/\/$/, '')}${path}?status=open&limit=1`;
    const startedAt = Date.now();
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      const response = await fetch(url, {
        method: 'OPTIONS',
        headers: {
          Origin: origin,
          'Access-Control-Request-Method': 'GET',
          'Access-Control-Request-Headers': 'accept',
        },
        signal: controller.signal,
      });
      clearTimeout(timer);
      const allowed = response.headers.get('access-control-allow-origin');
      const methods = response.headers.get('access-control-allow-methods');
      results.push({
        origin,
        reachable: true,
        status: response.status,
        allow_origin: allowed,
        allow_methods: methods,
        allowed: allowed === origin || allowed === '*',
        duration_ms: Date.now() - startedAt,
        error: null,
      });
    } catch (error) {
      // The host itself was unreachable from the runner — that is a network
      // limitation of the collector, NOT a CORS decision by the Kalshi API.
      results.push({
        origin,
        reachable: false,
        status: null,
        allow_origin: null,
        allow_methods: null,
        allowed: false,
        duration_ms: Date.now() - startedAt,
        error: String(error?.message || error),
      });
    }
  }

  const reachable = results.filter((r) => r.reachable);
  return {
    checked_at: new Date().toISOString(),
    endpoint: `${baseUrl}${path}`,
    method: 'OPTIONS preflight (Origin + Access-Control-Request-Method: GET)',
    results,
    host_reachable: reachable.length > 0,
    browser_direct_allowed: reachable.length > 0 && reachable.every((r) => r.allowed),
    verdict: reachable.length === 0
      ? 'unverified — the Kalshi demo host was unreachable from the collector runner, so no CORS decision could be observed'
      : reachable.every((r) => r.allowed)
        ? 'allowed — the Kalshi demo API returned an Access-Control-Allow-Origin header matching the published site origin'
        : 'not allowed — the Kalshi demo API did not return an Access-Control-Allow-Origin header matching the published site origin',
  };
}
