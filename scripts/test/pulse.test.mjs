/* Live-pulse render check for the kalshi-dashboard alerts page (session arena-8a8d4294).
 *
 * What it proves, in one DOM:
 *   1. the page still renders its two scrolling chats from the published snapshot;
 *   2. the browser pulse loads the site root's shared detector (assets/live-feed.js) rather than
 *      re-implementing the ≥ $0.10 rule (request R-F3-3), measures a second reading, and its row
 *      appears in BOTH chats — the all-events feed and the High-ROI feed — carrying a `live` label
 *      and the market link, never a cause link;
 *   3. with the shared module missing the page degrades to the collector rows and says the pulse
 *      is unavailable instead of going silent.
 *
 * Prices are SYNTHETIC fixtures, not Kalshi data. jsdom is an optional devDependency
 * (`npm ci`); without it the whole file skips, so `npm test` stays green on a bare checkout.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';

let jsdom = null;
try {
  jsdom = await import('jsdom');
} catch {
  jsdom = null;
}

const LATEST = {
  generated_at: '2026-11-21T07:00:00Z',
  source: { base_url: BASE },
  markets: [{
    ticker: 'SYN-GAS-1', event_ticker: 'SYN-E1', series_ticker: 'KXAAAGASM', topic: 'gas',
    event_title: 'SYNTHETIC gas event', outcome_label: 'Above 3.25', volume_24h: 500,
    source_url: `${BASE}/markets/SYN-GAS-1`,
  }],
};
const RULE = { high_roi_rule: { max_entry_price_cents: 40, max_spread_cents: 5, min_volume_24h_contracts: 100 } };
const COLLECTOR_ALERTS = { alerts: [] };

// Two readings 45 s apart in production, back to back here. YES mid 0.2050 -> 0.3350 = +13c.
const BOOK_ONE = { orderbooks: [{ ticker: 'SYN-GAS-1', orderbook_fp: { yes_dollars: [['0.2000', '100.00']], no_dollars: [['0.7900', '100.00']] } }] };
const BOOK_TWO = { orderbooks: [{ ticker: 'SYN-GAS-1', orderbook_fp: { yes_dollars: [['0.3300', '100.00']], no_dollars: [['0.6600', '100.00']] } }] };

async function render({ withLiveFeed }) {
  const { JSDOM, VirtualConsole } = jsdom;
  const frag = readFileSync(path.join(ROOT, 'site', 'pages', 'alerts.html'), 'utf8')
    .replace(/^<!--meta:.*-->\n?/, '');
  const appJs = readFileSync(path.join(ROOT, 'site', 'assets', 'app.js'), 'utf8');
  const feedJs = withLiveFeed ? readFileSync(path.join(ROOT, 'assets', 'live-feed.js'), 'utf8') : '';
  const html = `<!doctype html><html><body data-page="alerts">${frag}<script>${feedJs}</script><script>${appJs}</script></body></html>`;

  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => errors.push(`jsdomError: ${e.message}`));

  const counter = { polls: 0 };
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: `${BASE.replace(/\/trade-api.*/, '')}/Trade2/kalshi-dashboard/alerts.html`,
    virtualConsole: vc,
    beforeParse(window) {
      window.fetch = async (url) => {
        const u = String(url);
        if (u.includes('data/latest.json')) return { ok: true, json: async () => LATEST };
        if (u.includes('data/topics.json')) return { ok: true, json: async () => RULE };
        if (u.includes('data/alerts.json')) return { ok: true, json: async () => COLLECTOR_ALERTS };
        if (u.includes('data/status.json')) return { ok: true, json: async () => ({ counts: {}, generated_at: LATEST.generated_at }) };
        if (u.includes('data/resolved.json') || u.includes('data/trades.json')) return { ok: true, json: async () => null };
        if (u.includes('/markets/orderbooks')) {
          counter.polls += 1;
          // the request must be the documented shape: one `tickers=` occurrence per ticker
          assert.match(u, /markets\/orderbooks\?tickers=SYN-GAS-1$/, `unexpected poll URL ${u}`);
          return { ok: true, json: async () => (counter.polls === 1 ? BOOK_ONE : BOOK_TWO) };
        }
        throw new Error(`unexpected fetch ${u}`);
      };
    },
  });
  const waitFor = async (fn, ms = 3000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      if (fn()) return true;
      await new Promise((r) => setTimeout(r, 25));
    }
    return false;
  };
  await waitFor(() => dom.window.document.querySelector('#chat-all')?.textContent);
  return { dom, errors, counter, waitFor };
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

test('live pulse: the shared detector measures a second reading and its row reaches both chats', { skip: jsdom ? false : 'jsdom is not installed (run `npm ci`)' }, async () => {
  const { dom, errors, counter, waitFor } = await render({ withLiveFeed: true });
  const { window } = dom;
  const doc = window.document;
  try {
    assert.equal(errors.length, 0, `no page errors: ${errors.join(' | ')}`);
    assert.equal(typeof window.LiveFeed, 'object', 'the shared module is what the page uses');
    assert.match(doc.querySelector('#chat-all').textContent, /No alerts yet/, 'before a second reading there is nothing to show');

    // a second reading: the panel toggle off/on triggers pulseRefresh() exactly as an operator would
    const toggle = doc.querySelector('#pulse-on');
    assert.ok(toggle, 'the pulse panel offers an opt-out');
    toggle.checked = false;
    toggle.dispatchEvent(new window.Event('change'));
    toggle.checked = true;
    toggle.dispatchEvent(new window.Event('change'));
    await waitFor(() => /live · browser poll/.test(doc.querySelector('#chat-all').innerHTML), 1500);

    const all = doc.querySelector('#chat-all').innerHTML;
    const hi = doc.querySelector('#chat-hi').innerHTML;
    assert.match(all, /live · browser poll/, 'the live row is labelled as a browser measurement');
    assert.match(all, /\+13¢ mid 21¢ → 34¢/, 'the ≥ $0.10 step is measured from the two books (YES mid = best YES bid and the implied ask 1 − best NO bid)');
    assert.ok(all.includes('href="https://external-api.demo.kalshi.co/trade-api/v2/markets/SYN-GAS-1"'), 'the row links its own market');
    assert.match(all, /cause link: not determined/, 'a live row claims no cause');
    assert.match(all, /executable/, 'top-of-book size is reported, per the collector rule');
    assert.match(hi, /High-ROI rule/, 'the published High-ROI rule (config) flags the 34c implied ask in the second chat too');
    assert.match(doc.querySelector('#pulse-state').textContent, /2 readings · 1 live swing/, 'the panel states how many readings were taken');
    assert.equal(counter.polls, 2, 'exactly one anonymous request per refresh — no polling storm');
  } finally {
    dom.window.close();
  }
});

test('live pulse: a page without the shared module degrades to collector rows and says so', { skip: jsdom ? false : 'jsdom is not installed (run `npm ci`)' }, async () => {
  const { dom, errors, waitFor } = await render({ withLiveFeed: false });
  const { window } = dom;
  try {
    assert.equal(errors.length, 0, `no page errors: ${errors.join(' | ')}`);
    await wait(40);
    assert.match(window.document.querySelector('#chat-all').textContent, /No alerts yet/, 'the collector feed still renders');
    assert.ok(await waitFor(() => /offline/.test(window.document.querySelector('#pulse-state').textContent), 4000), 'the panel reports the pulse is unavailable');

    assert.match(window.document.querySelector('#pulse-state').textContent, /assets.live-feed.js/, 'and says what is missing');
  } finally {
    dom.window.close();
  }
});
