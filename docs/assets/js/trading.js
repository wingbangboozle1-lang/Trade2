/* =========================================================================
   Simulated trading page.
   ========================================================================= */
import { loadData, renderNav, renderStatus, fmt, esc, topicBadge } from './common.js';

const STRATEGY_META = {
  swing_momentum: {
    label: 'Swing Momentum',
    rule: 'Buys the direction of a move of at least $0.10 once the move has printed.',
    risk: 100,
  },
  mean_reversion: {
    label: 'Mean Reversion',
    rule: 'Buys a market that has moved at least $0.08 away from its own 30-minute mean.',
    risk: 100,
  },
  liquidity_capture: {
    label: 'Liquidity Capture',
    rule: 'Buys the touch in a tight, deep market and aims for a spread-sized gain.',
    risk: 25,
  },
  conviction: {
    label: 'Conviction (model edge)',
    rule: 'Buys YES when the published ROI model puts fair value at least $0.03 above the ask.',
    risk: 50,
  },
};

const state = { data: null, filter: 'all' };

function trades() {
  return state.data?.trades || [];
}

function renderStats() {
  const p = state.data?.portfolio || {};
  const cards = [
    { k: 'Starting cash', v: fmt.usd(p.start_cash ?? 0, 0) },
    { k: 'Equity now', v: fmt.usd(p.equity ?? 0, 0), d: `cash ${fmt.usd(p.cash ?? 0, 0)} + open ${fmt.usd(p.open_value ?? 0, 0)}` },
    { k: 'Realized P&L', v: fmt.usd(p.realized_pnl ?? 0, 0), cls: (p.realized_pnl ?? 0) >= 0 ? 'up' : 'down' },
    { k: 'Unrealized P&L', v: fmt.usd(p.unrealized_pnl ?? 0, 0), cls: (p.unrealized_pnl ?? 0) >= 0 ? 'up' : 'down' },
    { k: 'Total ROI', v: fmt.pct(p.roi_pct ?? 0), cls: (p.total_pnl ?? 0) >= 0 ? 'up' : 'down' },
    { k: 'Trades', v: String(p.total_trades ?? 0), d: `${p.closed_trades ?? 0} closed · ${p.open_positions ?? 0} open` },
    { k: 'Win rate', v: `${fmt.num(p.win_rate, 1)}%`, d: `${p.wins ?? 0}W / ${p.losses ?? 0}L` },
    { k: 'Avg hold', v: `${p.avg_hold_minutes ?? 0} min` },
  ];
  document.getElementById('stats').innerHTML = cards.map((c) => `
    <div class="stat ${c.cls || ''}">
      <div class="k">${esc(c.k)}</div>
      <div class="v">${esc(c.v)}</div>
      ${c.d ? `<div class="d">${esc(c.d)}</div>` : ''}
    </div>`).join('');
}

function renderStrategies() {
  const p = state.data?.portfolio || {};
  const byStrategy = p.by_strategy || [];
  const body = document.querySelector('#strategyTable tbody');
  const ids = [...new Set([...Object.keys(STRATEGY_META), ...byStrategy.map((s) => s.key)])];
  body.innerHTML = ids.map((id) => {
    const meta = STRATEGY_META[id] || { label: id, rule: '—', risk: '—' };
    const row = byStrategy.find((s) => s.key === id) || { trades: 0, closed: 0, open: 0, win_rate: 0, realized_pnl: 0, deployed: 0, roi_pct: 0 };
    return `<tr>
      <td><strong>${esc(meta.label)}</strong></td>
      <td style="max-width:380px">${esc(meta.rule)}</td>
      <td class="num">$${esc(meta.risk)}</td>
      <td class="num">${row.trades}</td>
      <td class="num">${row.closed}</td>
      <td class="num">${row.open}</td>
      <td class="num">${fmt.num(row.win_rate, 1)}%</td>
      <td class="num ${row.realized_pnl >= 0 ? 'up' : 'down'}">${fmt.usd(row.realized_pnl, 2)}</td>
      <td class="num">${fmt.usd(row.deployed, 0)}</td>
      <td class="num ${row.roi_pct >= 0 ? 'up' : 'down'}">${fmt.pct(row.roi_pct)}</td>
    </tr>`;
  }).join('');
}

function renderTopics() {
  const p = state.data?.portfolio || {};
  const body = document.querySelector('#topicTable tbody');
  const rows = p.by_topic || [];
  body.innerHTML = rows.map((r) => `<tr>
    <td>${topicBadge(r.key)}</td>
    <td class="num">${r.trades}</td>
    <td class="num">${r.closed}</td>
    <td class="num">${r.wins}</td>
    <td class="num">${fmt.num(r.win_rate, 1)}%</td>
    <td class="num ${r.pnl >= 0 ? 'up' : 'down'}">${fmt.usd(r.pnl, 2)}</td>
    <td class="num">${fmt.usd(r.deployed, 0)}</td>
    <td class="num ${r.roi_pct >= 0 ? 'up' : 'down'}">${fmt.pct(r.roi_pct)}</td>
  </tr>`).join('') || '<tr><td colspan="8" class="loading">No trades yet.</td></tr>';
}

function renderTypes() {
  const p = state.data?.portfolio || {};
  const body = document.querySelector('#typeTable tbody');
  const rows = p.by_type || [];
  body.innerHTML = rows.map((r) => {
    const [strategy, topic, side] = r.key.split('|');
    return `<tr>
      <td>${esc((STRATEGY_META[strategy]?.label) || strategy)} · ${esc(topic)} · ${esc(side)}</td>
      <td class="num">${r.closed}</td>
      <td class="num">${fmt.num(r.win_rate, 1)}%</td>
      <td class="num ${r.realized_pnl >= 0 ? 'up' : 'down'}">${fmt.usd(r.realized_pnl, 2)}</td>
      <td class="num">${fmt.usd(r.deployed, 0)}</td>
      <td class="num ${r.roi_pct >= 0 ? 'up' : 'down'}">${fmt.pct(r.roi_pct)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" class="loading">No trades yet.</td></tr>';
}

function renderDerived() {
  const p = state.data?.portfolio || {};
  const list = p.derived_strategies || [];
  const el = document.getElementById('derived');
  if (!list.length) {
    el.innerHTML = '<div class="loading">No strategy × topic × side combination has enough closed trades yet. '
      + 'The engine keeps trading every collection cycle, so this fills in as the demo market resolves.</div>';
    return;
  }
  const qualified = list.filter((d) => d.qualified);
  const watching = list.filter((d) => !d.qualified);
  const block = (title, items, cls) => (items.length ? `<h4 style="margin:14px 0 6px">${esc(title)}</h4>`
    + items.map((d) => `<div class="note ${cls}">
      <strong>${esc(d.title)}</strong> — ${d.trades} closed trades, ${fmt.num(d.win_rate, 1)}% win rate,
      ${fmt.usd(d.realized_pnl, 2)} realized on ${fmt.usd(d.deployed, 2)} deployed
      (${fmt.pct(d.roi_pct)} ROI)<br>${esc(d.description)}
    </div>`).join('') : '');
  el.innerHTML = block('Qualified (≥ 3 closed trades and positive realized P&L)', qualified, 'ok')
    + block('Watching (not yet qualified — shown so nothing is hidden)', watching, 'warn');
}

function renderOpen() {
  const body = document.querySelector('#openTable tbody');
  const open = trades().filter((t) => t.status === 'open');
  body.innerHTML = open.map((t) => `<tr>
    <td class="t-title">${esc(t.title || t.ticker)}<span class="tk">${esc(t.ticker)}</span></td>
    <td>${esc((STRATEGY_META[t.strategy]?.label) || t.strategy)}</td>
    <td>${esc(t.side)}</td>
    <td class="num">${fmt.num(t.count, 0)}</td>
    <td class="num">${fmt.cents(t.entry_price, 3)}</td>
    <td class="num">${t.mark_price ? fmt.cents(t.mark_price, 3) : '—'}</td>
    <td class="num">${fmt.usd(t.cost, 2)}</td>
    <td class="num ${(t.unrealized_pnl ?? 0) >= 0 ? 'up' : 'down'}">${t.unrealized_pnl != null ? fmt.usd(t.unrealized_pnl, 2) : '—'}</td>
    <td class="mono">${fmt.dateTime(t.entry_ts)}</td>
    <td style="max-width:280px">${esc(t.entry_reason || '')}</td>
  </tr>`).join('') || '<tr><td colspan="10" class="loading">No open positions.</td></tr>';
}

function renderLog() {
  const body = document.querySelector('#tradeTable tbody');
  let list = trades().slice();
  if (state.filter === 'closed') list = list.filter((t) => t.status === 'closed');
  else if (state.filter === 'open') list = list.filter((t) => t.status === 'open');
  else if (state.filter === 'settled') list = list.filter((t) => t.status === 'settled');
  else if (state.filter === 'backtest') list = list.filter((t) => t.mode === 'backtest');
  else if (state.filter === 'live') list = list.filter((t) => t.mode === 'live');
  body.innerHTML = list.slice(0, 400).map((t) => `<tr>
    <td class="mono">${fmt.dateTime(t.entry_ts)}</td>
    <td class="t-title">${esc(t.title || t.ticker)}<span class="tk">${esc(t.ticker)}</span></td>
    <td>${topicBadge(t.topic)}</td>
    <td>${esc((STRATEGY_META[t.strategy]?.label) || t.strategy)}</td>
    <td>${esc(t.side)}</td>
    <td class="num">${fmt.num(t.count, 0)}</td>
    <td class="num">${fmt.cents(t.entry_price, 3)}</td>
    <td class="num">${t.exit_price != null ? fmt.cents(t.exit_price, 3) : '—'}</td>
    <td class="num">${fmt.usd(t.cost, 2)}</td>
    <td class="num ${(t.pnl ?? 0) >= 0 ? 'up' : 'down'}">${t.pnl != null ? fmt.usd(t.pnl, 2) : '—'}</td>
    <td>${esc(t.exit_reason || (t.status === 'open' ? 'open' : '—'))}${t.resolution ? ` <span class="badge">resolved ${esc(t.resolution)}</span>` : ''}</td>
    <td class="mono">${esc(t.mode || '')}</td>
  </tr>`).join('') || '<tr><td colspan="12" class="loading">No trades match this filter yet.</td></tr>';
}

async function refresh() {
  state.data = await loadData(true);
  if (!state.data.ok) {
    document.getElementById('stats').innerHTML = '<div class="stat down"><div class="k">Data</div><div class="v">unavailable</div></div>';
    return;
  }
  renderStatus(state.data);
  renderStats();
  renderStrategies();
  renderTopics();
  renderTypes();
  renderDerived();
  renderOpen();
  renderLog();
}

renderNav('trading.html');
document.getElementById('tradeFilter').addEventListener('change', (event) => {
  state.filter = event.target.value;
  renderLog();
});
refresh();
setInterval(refresh, 60000);
