/* =========================================================================
   Live dashboard page.
   - renders the two swing feeds (all swings / high-ROI swings)
   - renders the tracked market table, the price chart and the liquidity book
   - optional "live browser API" mode polls Kalshi directly from the browser
   ========================================================================= */
import {
  loadData, renderNav, renderStatus, fmt, esc, drawChart, buildSeries,
  topicBadge, sourceLinks, TOPICS, dataBase,
} from './common.js';

const state = {
  data: null,
  topic: '',
  minRoi: 60,
  sortBy: 'dollar_amount',
  search: '',
  chartTicker: null,
  chartUnit: 'm',
  chartWindow: 3600,
  live: false,
  liveTimer: null,
  liveSeries: new Map(),   // ticker -> [{ts, price}] collected in live mode
  liveAlerts: new Map(),
};

const DEMO_BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';

function markets() {
  return (state.data?.markets || []).filter((m) => {
    if (state.topic && !(m.topics || []).includes(state.topic)) return false;
    if (state.search) {
      const hay = `${m.ticker} ${m.title}`.toLowerCase();
      if (!hay.includes(state.search.toLowerCase())) return false;
    }
    return true;
  });
}

function changeOf(market) {
  const prev = Number(market.previous_price);
  const last = Number(market.last_price);
  if (!Number.isFinite(prev) || prev <= 0.01) return null;
  return last - prev;
}

/* ------------------------------------------------------------------ stats */
function renderStats() {
  const data = state.data;
  const manifest = data?.manifest || {};
  const portfolio = data?.portfolio || {};
  const all = data?.markets || [];
  const totalDollars = all.reduce((sum, m) => sum + (m.dollar_amount || 0), 0);
  const totalVolume = all.reduce((sum, m) => sum + (m.dollar_volume || 0), 0);
  const alerts = data?.alerts || [];
  const dayAgo = Date.now() - 24 * 3600 * 1000;
  const recent = alerts.filter((a) => Date.parse(a.ts) > dayAgo).length;
  const depth = all.reduce((sum, m) => sum + (data.orderbooks?.[m.ticker]?.depth_yes_within_5c || 0), 0);

  const cards = [
    { k: 'Markets tracked', v: String(all.length), d: `${Object.keys(TOPICS).length} topics` },
    { k: 'Notional open interest', v: fmt.money(totalDollars, 0), d: 'contracts outstanding × price' },
    { k: 'Traded notional', v: fmt.money(totalVolume, 0), d: 'cumulative volume × price' },
    { k: 'Swings ≥ $0.10', v: String(alerts.length), d: `${recent} in the last 24h` },
    { k: 'Resting size ±5¢', v: fmt.num(depth), d: 'contracts within 5¢ of mid' },
    {
      k: 'Paper portfolio',
      v: fmt.usd(portfolio.equity ?? 0, 0),
      d: `${fmt.usd(portfolio.total_pnl ?? 0, 0)} (${fmt.pct(portfolio.roi_pct)}) · simulated`,
      cls: (portfolio.total_pnl ?? 0) >= 0 ? 'up' : 'down',
    },
    { k: 'Open paper positions', v: String(portfolio.open_positions ?? 0), d: `${portfolio.closed_trades ?? 0} closed trades` },
    { k: 'Last collection', v: manifest.generated_at ? fmt.ago(manifest.generated_at) : '—', d: manifest.source?.rest_base || '' },
  ];
  document.getElementById('stats').innerHTML = cards.map((c) => `
    <div class="stat ${c.cls || ''}">
      <div class="k">${esc(c.k)}</div>
      <div class="v">${esc(c.v)}</div>
      <div class="d">${esc(c.d)}</div>
    </div>`).join('');
}

/* ------------------------------------------------------------- chat feeds */
function alertHtml(alert, roi) {
  const dir = alert.direction === 'up' ? 'up' : 'down';
  const arrow = alert.direction === 'up' ? '▲' : '▼';
  const links = sourceLinks(alert);
  return `
    <div class="msg ${dir} ${roi ? 'roi' : ''}">
      <div class="top">
        <span class="px">${fmt.time(alert.ts)}</span>
        ${topicBadge(alert.topic)}
        <span class="mono">${esc(alert.ticker)}</span>
        <span class="px ${dir}">${arrow} ${fmt.signed(alert.delta, 3)}</span>
        <span class="px">${fmt.cents(alert.from, 3)} → ${fmt.cents(alert.to, 3)}</span>
        ${alert.roi_score !== null && alert.roi_score !== undefined ? `<span class="badge ${alert.roi_score >= 60 ? 'live' : ''}">ROI ${alert.roi_score}</span>` : ''}
      </div>
      <div class="body">${esc(alert.title || '')}</div>
      <div class="body" style="opacity:.75">${esc(alert.reference || '')}${alert.trade_count ? ` · ${fmt.num(alert.trade_count, 2)} contracts` : ''}</div>
      ${links.length ? `<div class="links">${links.join('')}</div>` : ''}
    </div>`;
}

function renderChats() {
  const alerts = (state.data?.alerts || []).slice().sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  const topicFiltered = alerts.filter((a) => !state.topic || (a.topics || []).includes(state.topic));
  const roiFiltered = topicFiltered.filter((a) => (a.roi_score ?? 0) >= state.minRoi);

  const allEl = document.getElementById('chatAll');
  const roiEl = document.getElementById('chatRoi');
  allEl.innerHTML = topicFiltered.length
    ? topicFiltered.map((a) => alertHtml(a, false)).join('')
    : '<div class="empty">No swings ≥ $0.10 recorded yet. The collector publishes a new snapshot every 10 minutes.</div>';
  roiEl.innerHTML = roiFiltered.length
    ? roiFiltered.map((a) => alertHtml(a, true)).join('')
    : `<div class="empty">No swings scored ≥ ${state.minRoi} by the ROI model yet.</div>`;
  document.getElementById('allCount').textContent = `${topicFiltered.length} alerts`;
  document.getElementById('roiCount').textContent = `${roiFiltered.length} alerts · threshold ${state.minRoi}`;
}

/* ------------------------------------------------------------ market table */
function renderTable() {
  const list = markets().slice();
  const data = state.data;
  const scored = list.map((m) => ({ m, move: Math.abs(changeOf(m) || 0) }));
  const sorters = {
    dollar_amount: (a, b) => (b.m.dollar_amount || 0) - (a.m.dollar_amount || 0),
    dollar_volume: (a, b) => (b.m.dollar_volume || 0) - (a.m.dollar_volume || 0),
    roi_score: (a, b) => (b.m.roi_score ?? 0) - (a.m.roi_score ?? 0),
    abs_move: (a, b) => b.move - a.move,
    spread: (a, b) => (a.m.spread ?? 9) - (b.m.spread ?? 9),
  };
  scored.sort(sorters[state.sortBy] || sorters.dollar_amount);

  const rows = scored.map(({ m, move }) => {
    const change = changeOf(m);
    const book = data?.orderbooks?.[m.ticker];
    const depth = Math.max(book?.depth_yes_within_5c || 0, book?.depth_no_within_5c || 0);
    const links = [];
    if (m.kalshi_url) links.push(`<a href="${esc(m.kalshi_url)}" target="_blank" rel="noopener">Kalshi</a>`);
    for (const s of (m.settlement_sources || []).slice(0, 2)) {
      if (s?.url) links.push(`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc((s.name || 'source').slice(0, 22))}</a>`);
    }
    return `<tr>
      <td>${topicBadge(m.topic)}</td>
      <td class="t-title"><a href="${esc(m.kalshi_url || '#')}" target="_blank" rel="noopener">${esc(m.title)}</a><span class="tk">${esc(m.ticker)}</span></td>
      <td class="num">${fmt.cents(m.last_price, 3)}</td>
      <td class="num ${change === null ? 'flat' : change > 0 ? 'up' : 'down'}">${change === null ? '—' : fmt.signed(change, 3)}</td>
      <td class="num mono">${fmt.cents(m.yes_bid, 2)} / ${fmt.cents(m.yes_ask, 2)}</td>
      <td class="num">${m.spread ? fmt.cents(m.spread, 3) : '—'}</td>
      <td class="num">${fmt.money(m.dollar_amount, 0)}</td>
      <td class="num">${fmt.money(m.dollar_volume, 0)}</td>
      <td class="num">${depth ? fmt.num(depth) : '—'}</td>
      <td class="num">${m.roi_score ?? '—'}</td>
      <td><div class="src">${links.join('')}</div></td>
    </tr>`;
  }).join('');

  document.querySelector('#marketTable tbody').innerHTML = rows
    || '<tr><td colspan="11" class="loading">No markets match the current filter.</td></tr>';
  document.getElementById('marketCount').textContent = `${scored.length} markets`;
}

/* ------------------------------------------------------------------ chart */
function seriesFor(ticker) {
  if (state.liveSeries.has(ticker)) {
    const live = state.liveSeries.get(ticker);
    const cutoff = Math.floor(Date.now() / 1000) - state.chartWindow;
    const merged = [...live, ...(state.data?.prices?.[ticker] || []).map(([ts, p]) => ({ ts, price: p }))];
    const sorted = merged.sort((a, b) => a.ts - b.ts).filter((p) => p.ts >= cutoff);
    if (sorted.length >= 2) return sorted;
  }
  return buildSeries(state.data, ticker, { windowSeconds: state.chartWindow, unit: state.chartUnit });
}

function renderChart() {
  const ticker = state.chartTicker;
  const canvas = document.getElementById('priceChart');
  if (!ticker) {
    drawChart(canvas, { points: [], unit: state.chartUnit, title: '' });
    document.getElementById('chartSources').innerHTML = '<span class="loading">Select a market to see its sources.</span>';
    return;
  }
  const market = (state.data?.markets || []).find((m) => m.ticker === ticker);
  const points = seriesFor(ticker);
  const markers = (state.data?.alerts || [])
    .filter((a) => a.ticker === ticker)
    .map((a) => ({ ts: Math.floor(Date.parse(a.ts) / 1000), direction: a.direction, delta: a.delta }));
  drawChart(canvas, {
    points,
    markers,
    unit: state.chartUnit,
    title: `${market?.title || ticker} — ${market ? fmt.cents(market.last_price, 3) : ''}`,
  });
  document.getElementById('chartMarketLabel').textContent = market?.ticker || '';
  const note = document.getElementById('chartNote');
  note.textContent = points.length
    ? `${points.length} points · x axis in ${state.chartUnit === 's' ? 'seconds' : state.chartUnit === 'm' ? 'minutes' : 'hours'}`
    : 'no points in range';

  const sources = [];
  if (market?.kalshi_url) sources.push(`<a href="${esc(market.kalshi_url)}" target="_blank" rel="noopener">Kalshi market page</a>`);
  for (const s of (market?.settlement_sources || [])) {
    if (s?.url) sources.push(`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name || 'settlement source')}</a>`);
  }
  document.getElementById('chartSources').innerHTML = sources.length
    ? sources.join('')
    : '<span class="loading">No settlement sources published for this market.</span>';
}

/* ------------------------------------------------------------------- book */
function renderBook() {
  const ticker = state.chartTicker;
  const book = state.data?.orderbooks?.[ticker];
  const market = (state.data?.markets || []).find((m) => m.ticker === ticker);
  document.getElementById('bookLabel').textContent = ticker || '';

  const renderSide = (tableId, levels, side) => {
    const body = document.querySelector(`#${tableId} tbody`);
    if (!levels || !levels.length) {
      body.innerHTML = `<tr><td colspan="3" class="loading">No resting ${side.toUpperCase()} bids in the demo book.</td></tr>`;
      return;
    }
    const max = Math.max(...levels.map((l) => l.count), 1);
    body.innerHTML = levels.map((l) => `<tr>
      <td class="num">${fmt.cents(l.price, 3)}</td>
      <td class="num">${fmt.num(l.count, 2)}</td>
      <td class="num">${fmt.money(l.count * l.price, 0)}</td>
    </tr>
    <tr><td colspan="3" style="padding:0;border:none"><span class="bar ${side === 'no' ? 'down' : ''}" style="width:${Math.max(2, (l.count / max) * 100)}%"></span></td></tr>`).join('');
  };
  renderSide('yesBook', book?.yes_levels, 'yes');
  renderSide('noBook', book?.no_levels, 'no');

  const kv = document.getElementById('marketKv');
  if (!market) { kv.innerHTML = '<dt>Market</dt><dd>—</dd>'; return; }
  const rows = [
    ['Ticker', market.ticker],
    ['Event', market.event_ticker],
    ['Category', market.category || '—'],
    ['Status', market.status],
    ['Last price', fmt.cents(market.last_price, 4)],
    ['YES bid / ask', `${fmt.cents(market.yes_bid, 3)} / ${fmt.cents(market.yes_ask, 3)}`],
    ['NO bid / ask', `${fmt.cents(market.no_bid, 3)} / ${fmt.cents(market.no_ask, 3)}`],
    ['Open interest', `${fmt.num(market.open_interest, 2)} contracts`],
    ['Volume (total / 24h)', `${fmt.num(market.volume, 2)} / ${fmt.num(market.volume_24h, 2)}`],
    ['Closes', fmt.dateTime(market.close_time)],
    ['ROI score', `${market.roi_score ?? '—'} (${Object.entries(market.roi_components || {}).map(([k, v]) => `${k} ${v}`).join(', ')})`],
    ['Model fair YES', fmt.cents(market.roi_fair_yes, 3)],
    ['Model EV (YES / NO)', `${fmt.signed(market.roi_ev_yes, 3)} / ${fmt.signed(market.roi_ev_no, 3)}`],
    ['Resolution (result)', market.result ? market.result.toUpperCase() : 'not resolved'],
  ];
  kv.innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
}

/* -------------------------------------------------------------- selections */
function fillChartSelect() {
  const select = document.getElementById('chartMarket');
  const list = markets();
  const previous = state.chartTicker;
  select.innerHTML = list.map((m) => `<option value="${esc(m.ticker)}">${esc(m.ticker)} — ${esc(m.title.slice(0, 60))}</option>`).join('');
  if (previous && list.some((m) => m.ticker === previous)) select.value = previous;
  state.chartTicker = select.value || list[0]?.ticker || null;
}

/* ------------------------------------------------------------- live (browser) */
async function tryLiveApi() {
  const button = document.getElementById('liveBtn');
  button.disabled = true;
  button.textContent = 'Testing…';
  try {
    const tickers = markets().slice(0, 20).map((m) => m.ticker);
    const res = await fetch(`${DEMO_BASE}/markets?tickers=${encodeURIComponent(tickers.join(','))}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    if (!body.markets) throw new Error('unexpected payload');
    state.live = true;
    document.getElementById('dataSource').textContent = 'live browser API';
    document.getElementById('dataSource').className = 'badge live';
    button.textContent = 'Live mode on';
    button.className = 'ghost';
    applyLiveMarkets(body.markets);
    clearInterval(state.liveTimer);
    state.liveTimer = setInterval(pollLive, 15000);
  } catch (error) {
    state.live = false;
    document.getElementById('dataSource').textContent = 'snapshot (browser API blocked)';
    document.getElementById('dataSource').className = 'badge warn';
    button.textContent = `Live API blocked: ${error.message}`;
    button.className = 'ghost';
  } finally {
    button.disabled = false;
  }
}

async function pollLive() {
  try {
    const tickers = markets().slice(0, 20).map((m) => m.ticker);
    if (!tickers.length) return;
    const res = await fetch(`${DEMO_BASE}/markets?tickers=${encodeURIComponent(tickers.join(','))}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    applyLiveMarkets(body.markets || []);
  } catch (error) {
    document.getElementById('dataSource').textContent = `live error: ${error.message}`;
  }
}

function applyLiveMarkets(liveMarkets) {
  const byTicker = new Map(liveMarkets.map((m) => [m.ticker, m]));
  const nowTs = Math.floor(Date.now() / 1000);
  for (const market of state.data.markets || []) {
    const live = byTicker.get(market.ticker);
    if (!live) continue;
    const price = Number(live.last_price_dollars);
    if (!Number.isFinite(price)) continue;
    const previous = Number(market.last_price);
    if (Math.abs(price - previous) >= 0.1) {
      const alert = {
        ts: new Date().toISOString(),
        ticker: market.ticker,
        title: market.title,
        topic: market.topic,
        topics: market.topics,
        direction: price > previous ? 'up' : 'down',
        from: previous,
        to: price,
        delta: Number((price - previous).toFixed(4)),
        reference: 'browser live poll',
        roi_score: market.roi_score,
        kalshi_url: market.kalshi_url,
        settlement_sources: market.settlement_sources,
      };
      const key = `${market.ticker}|${alert.direction}`;
      if (!state.liveAlerts.has(key)) {
        state.liveAlerts.set(key, alert);
        state.data.alerts = [alert, ...(state.data.alerts || [])].slice(0, 400);
      }
    }
    market.last_price = price;
    market.yes_bid = Number(live.yes_bid_dollars);
    market.yes_ask = Number(live.yes_ask_dollars);
    market.no_bid = Number(live.no_bid_dollars);
    market.no_ask = Number(live.no_ask_dollars);
    market.previous_price = previous;
    const list = state.liveSeries.get(market.ticker) || [];
    list.push({ ts: nowTs, price });
    state.liveSeries.set(market.ticker, list.slice(-600));
  }
  renderStats();
  renderChats();
  renderTable();
  renderChart();
}

/* -------------------------------------------------------------------- init */
function wire() {
  document.getElementById('topicFilter').addEventListener('change', (event) => {
    state.topic = event.target.value;
    fillChartSelect();
    renderChats();
    renderTable();
    renderChart();
    renderBook();
  });
  document.getElementById('roiFilter').addEventListener('change', (event) => {
    state.minRoi = Number(event.target.value);
    renderChats();
  });
  document.getElementById('sortBy').addEventListener('change', (event) => {
    state.sortBy = event.target.value;
    renderTable();
  });
  document.getElementById('marketSearch').addEventListener('input', (event) => {
    state.search = event.target.value;
    fillChartSelect();
    renderTable();
    renderChart();
    renderBook();
  });
  document.getElementById('chartMarket').addEventListener('change', (event) => {
    state.chartTicker = event.target.value;
    renderChart();
    renderBook();
  });
  document.getElementById('chartWindow').addEventListener('change', (event) => {
    state.chartWindow = Number(event.target.value);
    renderChart();
  });
  document.querySelectorAll('#chartUnit button').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('#chartUnit button').forEach((b) => b.classList.remove('on'));
      button.classList.add('on');
      state.chartUnit = button.dataset.unit;
      renderChart();
    });
  });
  document.getElementById('refreshBtn').addEventListener('click', () => refresh(true));
  document.getElementById('liveBtn').addEventListener('click', tryLiveApi);
  window.addEventListener('resize', () => renderChart());
}

async function refresh(force = false) {
  state.data = await loadData(force);
  if (!state.data.ok) {
    document.getElementById('stats').innerHTML = '<div class="stat down"><div class="k">Data</div><div class="v">unavailable</div><div class="d">No snapshot has been published yet.</div></div>';
    return;
  }
  renderStatus(state.data);
  fillChartSelect();
  renderStats();
  renderChats();
  renderTable();
  renderChart();
  renderBook();
}

renderNav('dashboard.html');
wire();
refresh();
setInterval(() => refresh(true), 60000);
