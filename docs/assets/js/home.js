/* =========================================================================
   Landing page: headline numbers + findings derived from the latest snapshot.
   ========================================================================= */
import { loadData, renderNav, renderStatus, fmt, esc, TOPICS, pageBase } from './common.js';

const TOPIC_BLURBS = {
  gas: 'Retail fuel thresholds and WTI front-month settlement targets.',
  elections: 'Election winners, nominations and ballot outcomes — the deepest book on the demo exchange.',
  culture: 'Awards, box office, albums and celebrity markets — the most volatile book by price.',
  crypto: 'Digital asset price targets and milestones — the deepest resting liquidity.',
  golf: 'Tour events, majors and player props — the fastest clock to resolution.',
};

function renderTopicCards(data) {
  const markets = data.markets || [];
  const counts = {};
  const notional = {};
  for (const m of markets) {
    for (const t of m.topics || []) {
      counts[t] = (counts[t] || 0) + 1;
      notional[t] = (notional[t] || 0) + (m.dollar_amount || 0);
    }
  }
  document.getElementById('topicCards').innerHTML = Object.entries(TOPICS).map(([key, meta]) => `
    <div class="card">
      <h2>${esc(meta.label)}</h2>
      <p style="font-size:13px">${esc(TOPIC_BLURBS[key] || meta.blurb)}</p>
      <div class="kv">
        <dt>Live markets</dt><dd>${counts[key] || 0}</dd>
        <dt>Notional open interest</dt><dd>${fmt.money(notional[key] || 0, 0)}</dd>
      </div>
      <p style="margin-top:12px"><a href="${pageBase()}topics/${key}.html">Open ${esc(meta.short.toLowerCase())} →</a></p>
    </div>`).join('');
}

function renderFindings(data) {
  const markets = data.markets || [];
  const alerts = data.alerts || [];
  const portfolio = data.portfolio || {};
  const orderbooks = data.orderbooks || {};
  const trades = data.trades || [];
  const health = data['collector-health'] || {};

  const top = markets.slice().sort((a, b) => (b.dollar_amount || 0) - (a.dollar_amount || 0)).slice(0, 5);
  const withDepth = markets.filter((m) => (orderbooks[m.ticker]?.depth_yes_total || 0) > 0);
  const swings = alerts.slice().sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 5);
  const settled = trades.filter((t) => t.status === 'settled');
  const open = trades.filter((t) => t.status === 'open');

  const rows = [];
  rows.push(`<p><strong>${markets.length}</strong> live markets across the five topics carry
    <strong>${fmt.money(markets.reduce((s, m) => s + (m.dollar_amount || 0), 0), 0)}</strong> of open-interest notional
    and <strong>${fmt.money(markets.reduce((s, m) => s + (m.dollar_volume || 0), 0), 0)}</strong> of traded notional.</p>`);

  if (top.length) {
    rows.push(`<p><strong>Largest books right now:</strong></p><ul class="tight">${top.map((m) => `
      <li><a href="${esc(m.kalshi_url || '#')}" target="_blank" rel="noopener">${esc(m.title)}</a> —
      ${fmt.money(m.dollar_amount, 0)} open interest notional, last ${fmt.cents(m.last_price, 3)},
      ${fmt.money(m.dollar_volume, 0)} traded.</li>`).join('')}</ul>`);
  }

  rows.push(`<p><strong>Liquidity is concentrated:</strong> ${withDepth.length} of ${markets.length} tracked markets had any resting
    size in the demo orderbook at collection time, so most of the book is quoted rather than funded.</p>`);

  if (swings.length) {
    rows.push(`<p><strong>Largest swings on record:</strong></p><ul class="tight">${swings.map((a) => `
      <li><span class="mono">${esc(a.ticker)}</span> — ${a.direction === 'up' ? '▲' : '▼'}
      ${fmt.signed(a.delta, 3)} (${fmt.cents(a.from, 3)} → ${fmt.cents(a.to, 3)}) ·
      ${esc(a.reference || '')}</li>`).join('')}</ul>`);
  } else {
    rows.push('<p><strong>No $0.10 swing has been recorded yet</strong> in the current alert log '
      + '— the demo books move in single-cent increments most of the time.</p>');
  }

  rows.push(`<p><strong>Simulated book:</strong> ${portfolio.total_trades || 0} trades (${portfolio.closed_trades || 0} closed,
    ${portfolio.open_positions || 0} open, ${settled.length} settled by resolution), equity ${fmt.usd(portfolio.equity || 0, 0)}
    against ${fmt.usd(portfolio.start_cash || 0, 0)} of starting cash (${fmt.pct(portfolio.roi_pct || 0)}).
    ${open.length ? `${open.length} position${open.length === 1 ? '' : 's'} still open and marked to the live bid.` : ''}</p>`);

  rows.push(`<p><strong>Pipeline health:</strong> last collection ${health.last_run_at ? fmt.ago(health.last_run_at) : '—'},
    ${health.api_calls || 0} API calls, ${health.api_errors || 0} errors, exchange trading
    ${health.trading_active === false ? 'paused' : 'active'}.</p>`);

  document.getElementById('findings').innerHTML = rows.join('');
}

async function refresh() {
  const data = await loadData(true);
  if (!data.ok) {
    document.getElementById('stats').innerHTML = '<div class="stat down"><div class="k">Data</div><div class="v">unavailable</div><div class="d">No snapshot published yet.</div></div>';
    return;
  }
  renderStatus(data);
  const markets = data.markets || [];
  const alerts = data.alerts || [];
  const portfolio = data.portfolio || {};
  const cards = [
    { k: 'Live markets', v: String(markets.length), d: 'gas · elections · culture · crypto · golf' },
    { k: 'Notional open interest', v: fmt.money(markets.reduce((s, m) => s + (m.dollar_amount || 0), 0), 0) },
    { k: 'Traded notional', v: fmt.money(markets.reduce((s, m) => s + (m.dollar_volume || 0), 0), 0) },
    { k: 'Swings ≥ $0.10', v: String(alerts.length), d: 'in the published alert log' },
    { k: 'Paper equity', v: fmt.usd(portfolio.equity || 0, 0), d: `${fmt.pct(portfolio.roi_pct || 0)} · simulated` },
    { k: 'Last collection', v: data.manifest?.generated_at ? fmt.ago(data.manifest.generated_at) : '—' },
  ];
  document.getElementById('stats').innerHTML = cards.map((c) => `
    <div class="stat"><div class="k">${esc(c.k)}</div><div class="v">${esc(c.v)}</div>
    ${c.d ? `<div class="d">${esc(c.d)}</div>` : ''}</div>`).join('');
  renderTopicCards(data);
  renderFindings(data);
}

renderNav('index.html');
refresh();
setInterval(refresh, 60000);
