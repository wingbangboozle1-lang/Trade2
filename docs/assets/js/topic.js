/* =========================================================================
   Per-topic page. The topic is read from <body data-topic="...">.
   ========================================================================= */
import {
  loadData, renderNav, renderStatus, fmt, esc, drawChart, buildSeries,
  topicBadge, sourceLinks, TOPICS,
} from './common.js';

const topic = document.body.dataset.topic;
const state = { data: null, ticker: null };

function topicMarkets() {
  return (state.data?.markets || []).filter((m) => (m.topics || []).includes(topic));
}

function changeOf(m) {
  const prev = Number(m.previous_price);
  const last = Number(m.last_price);
  if (!Number.isFinite(prev) || prev <= 0.01) return null;
  return last - prev;
}

function renderStats() {
  const list = topicMarkets();
  const data = state.data;
  const notional = list.reduce((s, m) => s + (m.dollar_amount || 0), 0);
  const volume = list.reduce((s, m) => s + (m.dollar_volume || 0), 0);
  const alerts = (data.alerts || []).filter((a) => (a.topics || []).includes(topic));
  const best = list.slice().sort((a, b) => (b.roi_score ?? 0) - (a.roi_score ?? 0))[0];
  const cards = [
    { k: 'Live markets', v: String(list.length) },
    { k: 'Notional open interest', v: fmt.money(notional, 0) },
    { k: 'Traded notional', v: fmt.money(volume, 0) },
    { k: 'Swings ≥ $0.10', v: String(alerts.length) },
    { k: 'Top ROI score', v: best ? String(best.roi_score) : '—', d: best ? best.ticker : '' },
  ];
  document.getElementById('stats').innerHTML = cards.map((c) => `
    <div class="stat">
      <div class="k">${esc(c.k)}</div>
      <div class="v">${esc(c.v)}</div>
      ${c.d ? `<div class="d">${esc(c.d)}</div>` : ''}
    </div>`).join('');
}

function renderTable() {
  const list = topicMarkets().slice().sort((a, b) => (b.dollar_amount || 0) - (a.dollar_amount || 0));
  const body = document.querySelector('#topicTable tbody');
  body.innerHTML = list.map((m) => {
    const change = changeOf(m);
    const book = state.data.orderbooks?.[m.ticker];
    const depth = Math.max(book?.depth_yes_within_5c || 0, book?.depth_no_within_5c || 0);
    const links = [];
    if (m.kalshi_url) links.push(`<a href="${esc(m.kalshi_url)}" target="_blank" rel="noopener">Kalshi</a>`);
    for (const s of (m.settlement_sources || []).slice(0, 3)) {
      if (s?.url) links.push(`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc((s.name || 'source').slice(0, 24))}</a>`);
    }
    return `<tr>
      <td class="t-title"><a href="${esc(m.kalshi_url || '#')}" target="_blank" rel="noopener">${esc(m.title)}</a><span class="tk">${esc(m.ticker)}</span></td>
      <td class="num">${fmt.cents(m.last_price, 3)}</td>
      <td class="num ${change === null ? 'flat' : change > 0 ? 'up' : 'down'}">${change === null ? '—' : fmt.signed(change, 3)}</td>
      <td class="num">${fmt.cents(m.yes_bid, 2)} / ${fmt.cents(m.yes_ask, 2)}</td>
      <td class="num">${m.spread ? fmt.cents(m.spread, 3) : '—'}</td>
      <td class="num">${fmt.money(m.dollar_amount, 0)}</td>
      <td class="num">${fmt.money(m.dollar_volume, 0)}</td>
      <td class="num">${depth ? fmt.num(depth) : '—'}</td>
      <td class="num">${m.roi_score ?? '—'}</td>
      <td class="num">${m.hours_to_close ? `${Math.round(m.hours_to_close)}h` : '—'}</td>
      <td><div class="src">${links.join('')}</div></td>
    </tr>`;
  }).join('') || '<tr><td colspan="11" class="loading">No live markets matched this topic in the current snapshot.</td></tr>';
  document.getElementById('tableCount').textContent = `${list.length} markets`;
}

function renderAlerts() {
  const alerts = (state.data.alerts || [])
    .filter((a) => (a.topics || []).includes(topic))
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))
    .slice(0, 40);
  const chat = document.getElementById('topicChat');
  chat.innerHTML = alerts.length ? alerts.map((a) => {
    const dir = a.direction === 'up' ? 'up' : 'down';
    const links = sourceLinks(a);
    return `<div class="msg ${dir}">
      <div class="top">
        <span class="px">${fmt.time(a.ts)}</span>
        <span class="mono">${esc(a.ticker)}</span>
        <span class="px ${dir}">${a.direction === 'up' ? '▲' : '▼'} ${fmt.signed(a.delta, 3)}</span>
        <span class="px">${fmt.cents(a.from, 3)} → ${fmt.cents(a.to, 3)}</span>
        ${a.roi_score != null ? `<span class="badge ${a.roi_score >= 60 ? 'live' : ''}">ROI ${a.roi_score}</span>` : ''}
      </div>
      <div class="body">${esc(a.title || '')}</div>
      ${links.length ? `<div class="links">${links.join('')}</div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">No swings recorded for this topic yet.</div>';
}

function renderChart() {
  const list = topicMarkets().slice().sort((a, b) => (b.dollar_amount || 0) - (a.dollar_amount || 0));
  if (!list.length) return;
  const select = document.getElementById('topicChartMarket');
  select.innerHTML = list.map((m) => `<option value="${esc(m.ticker)}">${esc(m.ticker)} — ${esc(m.title.slice(0, 50))}</option>`).join('');
  select.value = state.ticker && list.some((m) => m.ticker === state.ticker) ? state.ticker : list[0].ticker;
  state.ticker = select.value;
  drawTopicChart();
}

function drawTopicChart() {
  const ticker = state.ticker;
  const market = topicMarkets().find((m) => m.ticker === ticker);
  const points = buildSeries(state.data, ticker, { windowSeconds: 21600, unit: 'm' });
  const markers = (state.data.alerts || [])
    .filter((a) => a.ticker === ticker)
    .map((a) => ({ ts: Math.floor(Date.parse(a.ts) / 1000), direction: a.direction }));
  drawChart(document.getElementById('topicChart'), {
    points, markers, unit: 'm', title: market ? `${market.title} — ${fmt.cents(market.last_price, 3)}` : ticker,
  });
  const sources = [];
  if (market?.kalshi_url) sources.push(`<a href="${esc(market.kalshi_url)}" target="_blank" rel="noopener">Kalshi market page</a>`);
  for (const s of (market?.settlement_sources || [])) if (s?.url) sources.push(`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name || 'source')}</a>`);
  document.getElementById('topicSources').innerHTML = sources.join('') || '<span class="loading">No settlement sources published.</span>';
}

async function refresh() {
  state.data = await loadData(true);
  if (!state.data.ok) {
    document.getElementById('stats').innerHTML = '<div class="stat down"><div class="k">Data</div><div class="v">unavailable</div></div>';
    return;
  }
  renderStatus(state.data);
  renderStats();
  renderTable();
  renderAlerts();
  renderChart();
}

renderNav(`topics/${topic}.html`);
document.getElementById('topicChartMarket')?.addEventListener('change', (event) => {
  state.ticker = event.target.value;
  drawTopicChart();
});
window.addEventListener('resize', drawTopicChart);
refresh();
setInterval(refresh, 60000);
