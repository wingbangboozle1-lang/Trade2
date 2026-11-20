/* Kalshi topic dashboard — renders static pages from JSON produced by scripts/collect.mjs.
   Every number shown is taken from a JSON file in data/ (official Kalshi API output) or is labeled
   "derived" (computed here from official fields, formula stated on the page). No values are typed in by hand. */
(function () {
  'use strict';
  const page = document.body.dataset.page;
  const TOPIC_LABEL = { gas: 'Gas prices', elections: 'Elections', culture: 'Culture & entertainment', crypto: 'Crypto', golf: 'Golf' };
  const TOPIC_PAGE = { gas: 'gas.html', elections: 'elections.html', culture: 'culture.html', crypto: 'crypto.html', golf: 'golf.html' };
  const RANGES = [
    { id: '1h', label: '1 hour', ms: 3600e3, tick: 10 * 60e3 },
    { id: '6h', label: '6 hours', ms: 6 * 3600e3, tick: 3600e3 },
    { id: '24h', label: '24 hours', ms: 24 * 3600e3, tick: 4 * 3600e3 },
    { id: '72h', label: '72 hours', ms: 72 * 3600e3, tick: 12 * 3600e3 },
  ];

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtCents = (c) => (c === null || c === undefined ? '—' : `${c}¢`);
  const fmtDollarsCents = (c) => (c === null || c === undefined ? '—' : `${c < 0 ? '-' : ''}$${(Math.abs(c) / 100).toFixed(2)}`);
  const fmtUsd = (x) => (x === null || x === undefined ? '—' : `$${Number(x).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`);
  const fmtNum = (x) => (x === null || x === undefined ? '—' : Number(x).toLocaleString('en-US', { maximumFractionDigits: 2 }));
  const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');
  const ago = (iso) => {
    if (!iso) return '—';
    const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m} min ago`;
    if (m < 1440) return `${Math.round(m / 60)} h ago`;
    return `${Math.round(m / 1440)} d ago`;
  };
  const link = (href, text) => (href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>` : '<span class="muted">no link</span>');

  async function load(name) {
    try {
      const r = await fetch(`data/${name}?v=${Date.now()}`, { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  function navHighlight() {
    document.querySelectorAll('header.top nav a').forEach((a) => {
      if (a.getAttribute('href') === location.pathname.split('/').pop() || (a.getAttribute('href') === 'index.html' && location.pathname.endsWith('/'))) a.classList.add('on');
    });
  }

  function statusBar(status, latest) {
    const el = $('#status-bar');
    if (!el) return;
    const gen = latest?.generated_at || status?.generated_at;
    const exch = latest?.exchange;
    const parts = [
      `Data updated: <strong>${esc(fmtTime(gen))}</strong> (${esc(ago(gen))})`,
      exch ? `Exchange: ${exch.exchange_active ? 'active' : 'inactive'} · Trading: ${exch.trading_active ? 'open' : 'closed'}` : 'Exchange status: unavailable this run',
      `Source: Kalshi public API (read-only)`,
    ];
    el.innerHTML = parts.map((p) => `<span>${p}</span>`).join('');
    const age = gen ? (Date.now() - new Date(gen).getTime()) / 60000 : Infinity;
    const stale = $('#stale');
    if (stale) {
      stale.style.display = age > 45 ? 'block' : 'none';
      stale.innerHTML = `Data is ${Number.isFinite(age) ? Math.round(age) + ' min old' : 'missing'}. The collector runs on a schedule (about every 30 minutes, subject to GitHub Actions scheduling delays), so this page is near-real-time, not tick-by-tick.`;
    }
  }

  function kpi(label, value, note) {
    return `<div class="card kpi"><div class="v">${value}</div><div class="l">${esc(label)}</div>${note ? `<div class="note">${note}</div>` : ''}</div>`;
  }

  function alertsIn(alerts, sinceMs) {
    return (alerts?.alerts || []).filter((a) => a.t_ms >= sinceMs);
  }

  function sumPnl(trades) {
    return trades?.summary?.overall ? trades.summary.overall : null;
  }

  // ---------- HOME ----------
  async function renderHome() {
    const [latest, alerts, trades, resolved, status] = await Promise.all([load('latest.json'), load('alerts.json'), load('trades.json'), load('resolved.json'), load('status.json')]);
    statusBar(status, latest);
    const main = $('#app');
    if (!latest) {
      main.innerHTML = '<div class="card empty">Live data is not available yet. The collector has not published data.</div>';
      return;
    }
    const markets = latest.markets || [];
    const dayAlerts = alertsIn(alerts, Date.now() - 24 * 3600e3);
    const totalUsd = markets.reduce((s, m) => s + (m.est_volume_24h_usd || 0), 0);
    const ov = sumPnl(trades);
    const topicCards = Object.entries(latest.topics || {}).map(([k, t]) => `
      <a class="card" style="text-decoration:none;color:inherit" href="${TOPIC_PAGE[k]}">
        <div style="font-weight:700;font-size:16px">${esc(t.label)}</div>
        <div class="muted" style="font-size:13px">${t.event_count} events · ${t.market_count} active markets</div>
        <div style="margin-top:6px;font-size:13px">Est. 24h $ volume (derived): <strong>${fmtUsd(t.dollar_volume_24h_usd)}</strong></div>
      </a>`).join('');
    const top = markets.slice(0, 15);
    const topRows = top.map((m, i) => `<tr><td class="num">${i + 1}</td><td>${esc(m.topic ? TOPIC_LABEL[m.topic] : '')}</td><td>${esc(m.event_title)}<div class="note">${esc(m.outcome_label)}</div></td><td class="mono">${esc(m.ticker)}</td><td class="num">${fmtCents(m.last_cents)}</td><td class="num">${fmtNum(m.volume_24h)}</td><td class="num">${fmtUsd(m.est_volume_24h_usd)}</td><td>${link(m.source_url, 'API JSON')}</td></tr>`).join('');
    const recent = dayAlerts.slice(-8).reverse().map(alertLine).join('') || '<div class="empty">No price-move alerts (≥ 10¢) in the last 24 hours.</div>';
    main.innerHTML = `
      <h1>Kalshi live topic dashboard</h1>
      <p class="lead">Live prices, liquidity, ≥ $0.10 move alerts and simulated trades for gas prices, elections, culture, crypto and golf. Read-only public data; no orders are placed.</p>
      <div class="grid">
        ${kpi('Active markets tracked', fmtNum(markets.length), 'Kalshi status "active"')}
        ${kpi('Events tracked', fmtNum(new Set(markets.map((m) => m.event_ticker)).size), '')}
        ${kpi('Est. 24h $ volume (derived)', fmtUsd(totalUsd), 'volume_24h × notional_value_dollars')}
        ${kpi('Price alerts (24h)', fmtNum(dayAlerts.length), '≥ 10¢ between collector runs')}
        ${kpi('Resolved (yes/no)', fmtNum(resolved?.resolved?.length ?? 0), 'official result field')}
        ${kpi('Simulated P&L (all)', ov ? fmtDollarsCents(ov.realized_cents + (ov.unrealized_cents || 0)) : '—', 'paper trades, realized + unrealized')}
      </div>
      <h2>Topics</h2>
      <div class="grid">${topicCards || '<div class="card empty">No topic data yet.</div>'}</div>
      <h2>Highest estimated 24h dollar volume (all topics)</h2>
      <div class="table-wrap"><table><thead><tr><th class="num">#</th><th>Topic</th><th>Event / outcome</th><th>Ticker</th><th class="num">Last</th><th class="num">24h contracts</th><th class="num">Est. 24h $</th><th>Source</th></tr></thead><tbody>${topRows || '<tr><td colspan="8" class="empty">No markets yet.</td></tr>'}</tbody></table></div>
      <p class="note">Est. 24h $ = 24h contracts traded × notional value per contract (both official API fields); it is a derived estimate, not an official Kalshi dollar figure.</p>
      <h2>Latest price-move alerts (≥ 10¢)</h2>
      <div class="card">${recent}</div>
      <p class="note"><a href="alerts.html">Open the live alert chats →</a></p>`;
  }

  // ---------- TOPIC ----------
  async function renderTopic() {
    const key = document.body.dataset.topic;
    const [latest, alerts, history, status] = await Promise.all([load('latest.json'), load('alerts.json'), load('history.json'), load('status.json')]);
    statusBar(status, latest);
    const main = $('#app');
    main.dataset.topic = key;
    const label = TOPIC_LABEL[key];
    const t = latest?.topics?.[key];
    const markets = (latest?.markets || []).filter((m) => m.topic === key);
    const seriesRows = (latest?.series_mapping || []).filter((s) => s.topic === key);
    const topicAlerts = (alerts?.alerts || []).filter((a) => a.topic === key);
    const events = new Map();
    for (const m of markets) {
      if (!events.has(m.event_ticker)) events.set(m.event_ticker, { title: m.event_title, url: m.event_url, close: m.close_time, markets: [] });
      events.get(m.event_ticker).markets.push(m);
    }
    const rows = [...events.entries()].map(([et, ev]) => {
      const head = `<tr class="event-row"><td colspan="10">${esc(ev.title)} <span class="note mono">${esc(et)}</span> · closes ${esc(fmtTime(ev.close))} · ${link(ev.url, 'event JSON')}</td></tr>`;
      const body = ev.markets.map((m) => `<tr>
          <td>${esc(m.outcome_label || '—')}</td>
          <td class="mono">${esc(m.ticker)}</td>
          <td class="num">${fmtCents(m.last_cents)}</td>
          <td class="num">${fmtCents(m.yes_bid_cents)} / ${fmtCents(m.yes_ask_cents)}</td>
          <td class="num">${fmtCents(m.spread_cents)}</td>
          <td class="num">${fmtNum(m.volume_24h)}</td>
          <td class="num">${fmtUsd(m.est_volume_24h_usd)}</td>
          <td class="num">${fmtNum(m.open_interest)}</td>
          <td class="num">${m.change_cents === null || m.change_cents === undefined ? '—' : `<span class="${m.change_cents > 0 ? 'up' : m.change_cents < 0 ? 'down' : ''}">${m.change_cents > 0 ? '+' : ''}${m.change_cents}¢</span>`}</td>
          <td>${link(m.source_url, 'market JSON')}${m.series_terms_url ? ` · ${link(m.series_terms_url, 'terms')}` : ''}</td>
        </tr>`).join('');
      return head + body;
    }).join('');
    const sel = markets.map((m) => `<option value="${esc(m.ticker)}">${esc(m.event_title)} — ${esc(m.outcome_label || m.ticker)}</option>`).join('');
    main.innerHTML = `
      <h1>${esc(label)}</h1>
      <p class="lead">Every event in this topic, grouped by event. Prices are in cents (¢; 100¢ = $1.00). Read-only Kalshi data.</p>
      <div class="grid">
        ${kpi('Events', fmtNum(t?.event_count ?? events.size))}
        ${kpi('Active markets', fmtNum(t?.market_count ?? markets.length))}
        ${kpi('Est. 24h $ volume (derived)', fmtUsd(t?.dollar_volume_24h_usd ?? 0))}
        ${kpi('Alerts (all time kept)', fmtNum(topicAlerts.length), '≥ 10¢ moves')}
      </div>
      <h2>Events and markets</h2>
      <div class="table-wrap"><table><thead><tr><th>Outcome</th><th>Ticker</th><th class="num">Last</th><th class="num">YES bid / ask</th><th class="num">Spread</th><th class="num">24h contracts</th><th class="num">Est. 24h $</th><th class="num">Open interest</th><th class="num">Change since last run</th><th>Source</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="10" class="empty">No active ${esc(label)} markets in the latest run. See the Flagged for Review page if this persists.</td></tr>`}</tbody></table></div>
      <h2>Price chart and liquidity</h2>
      <div class="card">
        <div class="controls">
          <label>Market <select id="pick">${sel || '<option>none</option>'}</select></label>
          <span id="ranges"></span>
        </div>
        <div class="two">
          <div>
            <svg id="chart" class="chart" viewBox="0 0 900 300" preserveAspectRatio="none" role="img" aria-label="Price over time"></svg>
            <p class="note">X axis: time (range above). Y axis: contract price in cents, 0–100¢. Points are collector snapshots (about every 30 minutes), so sub-minute movement is not shown.</p>
          </div>
          <div id="liquidity"></div>
        </div>
      </div>
      <h2>Price-move alerts (≥ 10¢ between collector runs)</h2>
      <div class="table-wrap"><table><thead><tr><th>Time</th><th>Event / outcome</th><th>Move</th><th>High-ROI flag</th><th>Sources</th></tr></thead>
      <tbody>${topicAlerts.slice(-25).reverse().map(alertRow).join('') || '<tr><td colspan="5" class="empty">No alerts for this topic yet.</td></tr>'}</tbody></table></div>
      <h2>Series and rules (official fields from the Kalshi series object)</h2>
      <div class="table-wrap"><table><thead><tr><th>Series</th><th>Title</th><th>Category</th><th>Fee type</th><th class="num">Fee multiplier</th><th>Why mapped</th><th>Sources</th></tr></thead>
      <tbody>${seriesRows.map((s) => `<tr><td class="mono">${esc(s.series_ticker)}</td><td>${esc(s.title)}</td><td>${esc(s.category || '—')}</td><td class="mono">${esc(s.fee_type)}</td><td class="num">${fmtNum(s.fee_multiplier)}</td><td class="note">${esc(s.reason)}</td><td>${link(s.source_url, 'series JSON')} · ${link(s.contract_url, 'contract')} · ${link(s.contract_terms_url, 'terms')}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">No series mapped.</td></tr>'}</tbody></table></div>`;
    const pick = $('#pick');
    let range = RANGES[2];
    const drawRanges = () => {
      $('#ranges').innerHTML = RANGES.map((r) => `<button class="seg ${r.id === range.id ? 'on' : ''}" data-r="${r.id}">${r.label}</button>`).join(' ');
      $('#ranges').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { range = RANGES.find((x) => x.id === b.dataset.r); sessionStorage.setItem(`range-${key}`, range.id); drawRanges(); draw(); }));
    };
    const draw = () => {
      const tk = pick?.value;
      const h = history?.[tk];
      const pts = (h?.points || []).filter((p) => p[0] >= Date.now() - range.ms);
      drawChart($('#chart'), pts, range);
      const m = markets.find((x) => x.ticker === tk);
      const ob = latest?.orderbooks?.[tk];
      $('#liquidity').innerHTML = liquidityHtml(m, ob);
    };
    const saved = sessionStorage.getItem(`pick-${key}`);
    if (saved && markets.some((m) => m.ticker === saved)) pick.value = saved;
    pick?.addEventListener('change', () => { sessionStorage.setItem(`pick-${key}`, pick.value); draw(); });
    const savedRange = sessionStorage.getItem(`range-${key}`);
    if (savedRange) range = RANGES.find((r) => r.id === savedRange) || range;
    drawRanges();
    draw();
  }

  function liquidityHtml(m, ob) {
    if (!m) return '<div class="empty">Select a market.</div>';
    if (!ob) return `<div class="empty">No order book captured for this market in the latest run (order books are fetched only for the top-volume markets in each run).</div>`;
    const lad = (lv) => (lv.length ? lv.map((l) => `<tr><td class="num">${l.price_cents}¢</td><td class="num">${fmtNum(l.contracts)}</td></tr>`).join('') : '<tr><td colspan="2" class="empty">no resting bids</td></tr>');
    return `
      <div class="note mono">${esc(m.ticker)} · ${esc(m.outcome_label || '')}</div>
      <div class="two" style="grid-template-columns:1fr 1fr">
        <div><h3>YES bids</h3><div class="table-wrap"><table><thead><tr><th class="num">Price</th><th class="num">Contracts</th></tr></thead><tbody>${lad(ob.yes_bids)}</tbody></table></div></div>
        <div><h3>NO bids</h3><div class="table-wrap"><table><thead><tr><th class="num">Price</th><th class="num">Contracts</th></tr></thead><tbody>${lad(ob.no_bids)}</tbody></table></div></div>
      </div>
      <p class="note">Resting bids for each side from the official order book (top 10 levels). ${link(ob.source_url, 'order book JSON')}</p>`;
  }

  function drawChart(svg, pts, range) {
    const W = 900, H = 300, L = 46, R = 12, T = 12, B = 30;
    const now = Date.now();
    const t0 = now - range.ms;
    const x = (t) => L + ((t - t0) / range.ms) * (W - L - R);
    const y = (c) => T + (1 - Math.min(100, Math.max(0, c)) / 100) * (H - T - B);
    let out = '';
    for (let c = 0; c <= 100; c += 20) out += `<line x1="${L}" x2="${W - R}" y1="${y(c)}" y2="${y(c)}" stroke="#e6eaf1"/><text x="${L - 6}" y="${y(c) + 4}" font-size="11" text-anchor="end" fill="#5d6679">${c}¢</text>`;
    const step = range.tick;
    for (let tt = Math.ceil(t0 / step) * step; tt <= now; tt += step) {
      const d = new Date(tt);
      const lbl = range.ms <= 6 * 3600e3 ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit' });
      out += `<line x1="${x(tt)}" x2="${x(tt)}" y1="${T}" y2="${H - B}" stroke="#f0f3f8"/><text x="${x(tt)}" y="${H - 10}" font-size="11" text-anchor="middle" fill="#5d6679">${esc(lbl)}</text>`;
    }
    if (!pts.length) {
      out += `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" font-size="14" fill="#5d6679">No price points in the last ${range.label} for this market yet.</text>`;
    } else {
      const path = (idx) => pts.filter((p) => p[idx] !== null && p[idx] !== undefined && p[idx] > 0).map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[idx]).toFixed(1)}`).join(' ');
      out += `<path d="${path(2)}" fill="none" stroke="#9aa6ba" stroke-width="1.5" stroke-dasharray="4 3"/>`;
      out += `<path d="${path(3)}" fill="none" stroke="#c9a0a0" stroke-width="1.5" stroke-dasharray="4 3"/>`;
      out += `<path d="${path(1)}" fill="none" stroke="#0b5ca8" stroke-width="2.5"/>`;
      const last = pts[pts.length - 1];
      out += `<circle cx="${x(last[0])}" cy="${y(last[1])}" r="4" fill="#0b5ca8"/><text x="${Math.min(W - 60, x(last[0]) + 6)}" y="${y(last[1]) - 8}" font-size="12" fill="#0b5ca8" font-weight="700">${last[1]}¢</text>`;
    }
    out += `<text x="${L}" y="${T + 10}" font-size="11" fill="#5d6679">blue = last trade · grey dashed = YES bid · red dashed = YES ask</text>`;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.innerHTML = out;
  }

  // ---------- ALERTS (two chats) ----------
  function alertLine(a) {
    const cls = a.direction === 'up' ? 'up' : 'down';
    const arrow = a.direction === 'up' ? '▲' : '▼';
    return `<div class="msg ${cls}">
      <div class="meta">${esc(fmtTime(a.at))} · <span class="chip">${esc(TOPIC_LABEL[a.topic] || a.topic)}</span>${a.high_roi ? ' <span class="chip hi">High-ROI</span>' : ''}</div>
      <div><strong>${esc(a.event_title)}</strong> — ${esc(a.outcome_label || a.ticker)}</div>
      <div class="${cls}">${arrow} ${a.delta_cents > 0 ? '+' : ''}${a.delta_cents}¢ (${a.from_cents}¢ → ${a.to_cents}¢)</div>
      <div class="links">${link(a.source_url, 'market JSON')} ${link(a.event_url, 'event JSON')} ${link(a.rules_url, 'rules/terms')} <span class="note">cause link: not determined</span></div>
    </div>`;
  }

  function alertRow(a) {
    return `<tr><td>${esc(fmtTime(a.at))}</td><td><strong>${esc(a.event_title)}</strong><div class="note">${esc(a.outcome_label || a.ticker)}</div></td><td><span class="${a.direction === 'up' ? 'up' : 'down'}">${a.delta_cents > 0 ? '+' : ''}${a.delta_cents}¢</span> (${a.from_cents}¢ → ${a.to_cents}¢)</td><td>${a.high_roi ? '<span class="chip hi">High-ROI</span>' : '<span class="note">—</span>'}</td><td>${link(a.source_url, 'market JSON')} · ${link(a.rules_url, 'rules')}</td></tr>`;
  }

  async function renderAlerts() {
    const [latest, alerts, status] = await Promise.all([load('latest.json'), load('alerts.json'), load('status.json')]);
    statusBar(status, latest);
    const main = $('#app');
    const all = alerts?.alerts || [];
    const hi = all.filter((a) => a.high_roi);
    main.innerHTML = `
      <h1>Live alerts</h1>
      <p class="lead">Two scrolling feeds. <strong>All alerts</strong> lists every contract whose last price moved ≥ 10¢ between two collector runs. <strong>High-ROI picks</strong> lists only alerts that pass the rule-based High-ROI heuristic (entry ≤ 40¢, spread ≤ 5¢, 24h volume ≥ 100). The heuristic is not a predictive model; see Suggestions.</p>
      <div class="controls"><label>Topic <select id="tf"><option value="">All topics</option>${Object.entries(TOPIC_LABEL).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label></div>
      <div class="two">
        <div><h2 style="margin-top:6px">All alerts (${all.length})</h2><div class="chat" id="chat-all"></div></div>
        <div><h2 style="margin-top:6px">High-ROI picks (${hi.length})</h2><div class="chat" id="chat-hi"></div></div>
      </div>
      <p class="note">Newest messages are at the bottom. The feed shows the most recent 1,000 alerts kept by the collector. "Cause link: not determined" means the site does not attribute a price move to a news or website source; such links need manual review (see Flagged for Review).</p>`;
    const render = () => {
      const tf = $('#tf').value;
      const f = (a) => !tf || a.topic === tf;
      const chronological = (list) => list.filter(f).slice().reverse();
      const fill = (el, list) => {
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        el.innerHTML = chronological(list).map(alertLine).join('') || '<div class="empty">No alerts yet. Alerts appear when a price moves ≥ 10¢ between two collector runs.</div>';
        if (atBottom || !el.dataset.init) el.scrollTop = el.scrollHeight;
        el.dataset.init = '1';
      };
      fill($('#chat-all'), all);
      fill($('#chat-hi'), hi);
    };
    const savedTf = sessionStorage.getItem('alerts-topic');
    if (savedTf !== null) $('#tf').value = savedTf;
    $('#tf').addEventListener('change', () => { sessionStorage.setItem('alerts-topic', $('#tf').value); render(); });
    render();
  }

  // ---------- TRADES ----------
  async function renderTrades() {
    const [latest, trades, status] = await Promise.all([load('latest.json'), load('trades.json'), load('status.json')]);
    statusBar(status, latest);
    const main = $('#app');
    const s = trades?.summary;
    const strat = (s?.byStrategy || []).map((r) => `<tr><td><strong>${esc(r.name)}</strong><div class="note">${esc(r.description)}</div></td><td class="num">${r.trades}</td><td class="num">${r.open}</td><td class="num">${r.settled}</td><td class="num">${r.win_rate === null ? '—' : (r.win_rate * 100).toFixed(0) + '%'}</td><td class="num">${fmtDollarsCents(r.realized_cents)}</td><td class="num">${fmtDollarsCents(r.unrealized_cents)}</td><td class="num">${fmtDollarsCents(r.cost_cents - r.settled_cost_cents)}</td><td class="num">${r.roi_settled === null ? '—' : (r.roi_settled * 100).toFixed(1) + '%'}</td></tr>`).join('');
    const cats = (s?.byCategory || []).map((r) => `<tr><td>${esc(r.category)}</td><td class="num">${r.trades}</td><td class="num">${r.settled}</td><td class="num">${r.win_rate === null ? '—' : (r.win_rate * 100).toFixed(0) + '%'}</td><td class="num">${fmtDollarsCents(r.realized_cents)}</td><td class="num">${fmtDollarsCents(r.unrealized_cents)}</td></tr>`).join('');
    const pos = (trades?.positions || []).slice(0, 200).map((p) => `<tr><td>${esc(fmtTime(p.opened_at))}</td><td>${esc((STRAT_NAME[p.strategy]) || p.strategy)}</td><td>${esc(TOPIC_LABEL[p.topic] || p.topic)}</td><td>${esc(p.event_title)}<div class="note">${esc(p.outcome_label || p.ticker)}</div></td><td>${esc(p.side.toUpperCase())}</td><td class="num">${p.size}</td><td class="num">${p.entry_cents}¢</td><td class="num">${fmtDollarsCents(p.fee_cents)}</td><td class="num">${fmtDollarsCents(p.cost_cents)}</td><td>${p.status === 'open' ? `<span class="chip">open</span> mark ${fmtCents(p.mark_cents)}` : `<span class="chip ${p.result === p.side ? 'hi' : 'warn'}">settled ${esc(p.result.toUpperCase())}</span>`}</td><td class="num">${p.status === 'open' ? fmtDollarsCents(p.unrealized_cents) : fmtDollarsCents(p.pnl_cents)}</td><td>${link(p.source_url, 'market JSON')}</td></tr>`).join('');
    main.innerHTML = `
      <h1>Simulated trades and analysis</h1>
      <p class="lead">Automated <strong>paper trades</strong> that test three rule-based strategies on every ≥ 10¢ alert. No real orders are placed; Kalshi demo or live account positions are not shown here (see the portfolio note below).</p>
      <div class="card"><strong>Method.</strong> ${esc(trades?.method || '—')} Fee formula: official taker fee from the Kalshi Fee Schedule, rounded up to the cent, multiplied by the series fee multiplier. <a href="sources.html">See sources</a>.</div>
      <h2>Strategy performance</h2>
      <div class="table-wrap"><table><thead><tr><th>Strategy</th><th class="num">Trades</th><th class="num">Open</th><th class="num">Settled</th><th class="num">Win rate</th><th class="num">Realized P&amp;L</th><th class="num">Unrealized (at bid)</th><th class="num">Capital in open trades</th><th class="num">ROI on settled cost</th></tr></thead><tbody>${strat || '<tr><td colspan="9" class="empty">No trades yet.</td></tr>'}</tbody></table></div>
      <p class="note">Each trade costs contracts × entry price + fee. Win rate and ROI stay empty until markets settle with an official yes/no result.</p>
      <h2>Categories (topic · move direction · entry-price band)</h2>
      <div class="table-wrap"><table><thead><tr><th>Category</th><th class="num">Trades</th><th class="num">Settled</th><th class="num">Win rate</th><th class="num">Realized P&amp;L</th><th class="num">Unrealized</th></tr></thead><tbody>${cats || '<tr><td colspan="6" class="empty">No categories yet.</td></tr>'}</tbody></table></div>
      <h2>Recent simulated positions (latest 200)</h2>
      <div class="table-wrap"><table><thead><tr><th>Opened</th><th>Strategy</th><th>Topic</th><th>Event / outcome</th><th>Side</th><th class="num">Contracts</th><th class="num">Entry</th><th class="num">Fee</th><th class="num">Cost</th><th>Status</th><th class="num">P&amp;L</th><th>Source</th></tr></thead><tbody>${pos || '<tr><td colspan="12" class="empty">No positions yet.</td></tr>'}</tbody></table></div>
      <h2>Demo account portfolio</h2>
      <div class="card flag"><strong>Not connected.</strong> Portfolio tracking for the Kalshi demo account needs a demo API key pair stored as repository secrets (<span class="mono">KALSHI_DEMO_KEY_ID</span>, <span class="mono">KALSHI_DEMO_PRIVATE_KEY</span>). No account balance, positions or demo orders are shown on this page. Even when the secrets are set, this section is not yet wired to the snapshot file (flag F-20). See Flagged for Review.</div>`;
  }
  const STRAT_NAME = { follow: 'Follow big moves', fade: 'Fade big moves', high_roi_rule: 'High-ROI rule (heuristic)' };

  // ---------- RESOLVED ----------
  async function renderResolved() {
    const [latest, resolved, status] = await Promise.all([load('latest.json'), load('resolved.json'), load('status.json')]);
    statusBar(status, latest);
    const main = $('#app');
    const rows = (resolved?.resolved || []).map((r) => `<tr><td>${esc(fmtTime(r.detected_at))}</td><td>${esc(TOPIC_LABEL[r.topic] || r.topic)}</td><td>${esc(r.event_title)}<div class="note">${esc(r.outcome_label || r.ticker)}</div></td><td><span class="chip ${r.result === 'yes' ? 'yes' : r.result === 'no' ? 'no' : ''}">${esc(r.result.toUpperCase())}</span></td><td class="mono">${esc(r.status)}</td><td>${esc(fmtTime(r.close_time))}</td><td class="mono">${esc(r.ticker)}</td><td>${link(r.source_url, 'market JSON')}</td></tr>`).join('');
    const pend = (resolved?.pending || []).map((p) => `<tr><td>${esc(TOPIC_LABEL[p.topic] || p.topic || '—')}</td><td>${esc(p.event_title || '')}</td><td class="mono">${esc(p.ticker)}</td><td class="mono">${esc(p.status)}</td><td>${esc(fmtTime(p.close_time))}</td><td>${link(p.source_url, 'market JSON')}</td></tr>`).join('');
    main.innerHTML = `
      <h1>Resolved events — yes or no</h1>
      <p class="lead">Markets the collector followed that now carry an official result. "YES" or "NO" is the market's <span class="mono">result</span> field from the Kalshi API. Markets that have closed but have no result yet are listed below as pending.</p>
      <h2>Resolved (${(resolved?.resolved || []).length})</h2>
      <div class="table-wrap"><table><thead><tr><th>Detected</th><th>Topic</th><th>Event / outcome</th><th>Result</th><th>Status</th><th>Closed</th><th>Ticker</th><th>Source</th></tr></thead><tbody>${rows || '<tr><td colspan="8" class="empty">No followed markets have resolved yet.</td></tr>'}</tbody></table></div>
      <h2>Closed, awaiting result (${(resolved?.pending || []).length})</h2>
      <div class="table-wrap"><table><thead><tr><th>Topic</th><th>Event</th><th>Ticker</th><th>Status</th><th>Closed</th><th>Source</th></tr></thead><tbody>${pend || '<tr><td colspan="6" class="empty">None.</td></tr>'}</tbody></table></div>`;
  }

  // ---------- SOURCES & FLAGS (rendered from config JSON copied into data/) ----------
  async function renderSources() {
    const src = await load('sources.json');
    $('#app').innerHTML = `
      <h1>Sources</h1>
      <p class="lead">Every source used, with the exact official link, what was checked, and when. Verification is line-by-line against these pages; unverified values are blank and listed on Flagged for Review.</p>
      <div class="table-wrap"><table><thead><tr><th>ID</th><th>Official source</th><th>What it was used for</th><th>How it was verified</th><th>Checked on</th></tr></thead><tbody>
      ${(src?.sources || []).map((s) => `<tr><td class="mono">${esc(s.id)}</td><td>${link(s.url, s.title)}<div class="note mono">${esc(s.url)}</div></td><td>${esc(s.used_for)}</td><td>${esc(s.verification)}</td><td>${esc(s.checked_on)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">No sources loaded.</td></tr>'}
      </tbody></table></div>`;
  }

  async function renderFlagged() {
    const f = await load('flags.json');
    const flags = f?.flags || [];
    const card = (x) => `<tr><td class="mono">${esc(x.id)}</td><td><span class="chip ${x.type === 'irregularity' ? 'warn' : ''}">${esc(x.type)}</span></td><td><strong>${esc(x.title)}</strong><div>${esc(x.detail)}</div></td><td>${(x.links || []).map((l) => link(l.url, l.label)).join('<br>') || '<span class="muted">no source link — left unverified</span>'}</td><td>${esc(x.status)}</td></tr>`;
    $('#app').innerHTML = `
      <h1>Flagged for review</h1>
      <p class="lead">Irregularities found in the repository, API, or data, and any value that could not be confirmed from an official source. These items do not block the site. Review them and request changes; each row links its evidence.</p>
      <div class="table-wrap"><table><thead><tr><th>ID</th><th>Type</th><th>Item</th><th>Evidence / source</th><th>Status</th></tr></thead><tbody>${flags.map(card).join('') || '<tr><td colspan="5" class="empty">Nothing flagged.</td></tr>'}</tbody></table></div>`;
  }

  async function renderSimplePage() {
    // static pages (summary, suggestions) are plain HTML; nothing to render
  }

  const routes = { home: renderHome, topic: renderTopic, alerts: renderAlerts, trades: renderTrades, resolved: renderResolved, sources: renderSources, flagged: renderFlagged, static: renderSimplePage };
  navHighlight();
  if (routes[page]) {
    routes[page]().catch((e) => {
      const app = $('#app');
      if (app) app.innerHTML = `<div class="card empty">Could not render this page: ${esc(e.message)}</div>`;
    });
  }
  // live refresh every 60 seconds for pages that show data (re-reads JSON; does not reload the page)
  if (['home', 'topic', 'alerts', 'trades', 'resolved'].includes(page)) {
    setInterval(() => {
      const scroll = window.scrollY;
      routes[page]().then(() => window.scrollTo(0, scroll)).catch(() => {});
    }, 60000);
  }
})();
