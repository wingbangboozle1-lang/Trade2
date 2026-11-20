/* =========================================================================
   Shared helpers for the Kalshi demo dashboard site.
   Plain ES modules — no build step, no external CDN dependency.
   ========================================================================= */

export const TOPICS = {
  gas: { label: 'Gas Prices', short: 'Gas', blurb: 'Retail fuel and crude price contracts.' },
  elections: { label: 'Elections', short: 'Elections', blurb: 'Election, nomination and ballot outcomes.' },
  culture: { label: 'Culture', short: 'Culture', blurb: 'Film, music, awards and celebrity markets.' },
  crypto: { label: 'Crypto', short: 'Crypto', blurb: 'Digital asset price, milestone and regulatory markets.' },
  golf: { label: 'Golf', short: 'Golf', blurb: 'Tour events, majors and player props.' },
};

export const NAV = [
  { href: 'dashboard.html', label: 'Dashboard' },
  { href: 'topics/gas.html', label: 'Gas' },
  { href: 'topics/elections.html', label: 'Elections' },
  { href: 'topics/culture.html', label: 'Culture' },
  { href: 'topics/crypto.html', label: 'Crypto' },
  { href: 'topics/golf.html', label: 'Golf' },
  { href: 'trading.html', label: 'Trading' },
  { href: 'methodology.html', label: 'Methodology' },
  { href: 'flagged.html', label: 'Flagged' },
];

/* ------------------------------------------------------------------ paths */
export function dataBase() {
  const attr = document.body?.dataset?.dataBase;
  if (attr) return attr.endsWith('/') ? attr : `${attr}/`;
  const depth = (location.pathname.match(/\//g) || []).length;
  return depth > 2 ? '../data/' : 'data/';
}
export function pageBase() {
  const depth = (location.pathname.match(/\//g) || []).length;
  return depth > 2 ? '../' : './';
}

/* -------------------------------------------------------------- formatting */
export const fmt = {
  money(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    const n = Number(value);
    const abs = Math.abs(n);
    if (abs >= 1000000) return `$${(n / 1000000).toFixed(2)}M`;
    if (abs >= 1000) return `$${(n / 1000).toFixed(1)}k`;
    return `$${n.toFixed(digits)}`;
  },
  usd(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    const n = Number(value);
    return `${n < 0 ? '-' : ''}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
  },
  pct(value, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    return `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(digits)}%`;
  },
  cents(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    return `$${Number(value).toFixed(digits)}`;
  },
  num(value, digits = 0) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    return Number(value).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },
  time(ts) {
    if (!ts) return '—';
    const d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
    return d.toLocaleTimeString('en-US', { hour12: false });
  },
  dateTime(ts) {
    if (!ts) return '—';
    const d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
    return d.toLocaleString('en-US', { hour12: false, month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  },
  ago(ts) {
    if (!ts) return '—';
    const t = typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts;
    const secs = Math.max(0, (Date.now() - t) / 1000);
    if (secs < 60) return `${Math.floor(secs)}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
  },
  signed(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return '—';
    const n = Number(value);
    return `${n > 0 ? '+' : ''}${n.toFixed(digits)}`;
  },
};

export function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* ------------------------------------------------------------------ loader */
const cache = {};

export async function loadData(force = false) {
  const base = dataBase();
  if (!force && cache.loaded) return cache.loaded;
  const names = ['manifest', 'markets', 'events', 'orderbooks', 'candles', 'prices', 'alerts', 'trades', 'portfolio', 'collector-health'];
  const entries = await Promise.all(names.map(async (name) => {
    try {
      const res = await fetch(`${base}${name}.json`, { cache: 'no-cache' });
      if (!res.ok) return [name, null];
      return [name, await res.json()];
    } catch (error) {
      return [name, null];
    }
  }));
  const data = Object.fromEntries(entries);
  data.base = base;
  data.ok = Boolean(data.manifest);
  cache.loaded = data;
  return data;
}

/* --------------------------------------------------------------------- nav */
export function renderNav(activeHref) {
  const nav = document.querySelector('nav.main');
  if (!nav) return;
  const base = pageBase();
  nav.innerHTML = NAV.map((item) => {
    const cls = item.href === activeHref ? ' class="active"' : '';
    return `<a href="${base}${item.href}"${cls}>${esc(item.label)}</a>`;
  }).join('');
}

export function renderStatus(data) {
  const el = document.querySelector('[data-role="status"]');
  if (!el) return;
  const m = data.manifest;
  const health = data['collector-health'];
  const parts = [];
  if (m?.generated_at) parts.push(`<span class="badge live">snapshot ${fmt.ago(m.generated_at)}</span>`);
  if (m?.counts) parts.push(`<span class="badge">${m.counts.topic_markets ?? 0} markets</span>`);
  if (m?.counts) parts.push(`<span class="badge">${m.counts.alerts_total ?? 0} swings</span>`);
  if (m?.exchange_status?.trading_active !== undefined) {
    parts.push(`<span class="badge ${m.exchange_status.trading_active ? 'live' : 'danger'}">demo trading ${m.exchange_status.trading_active ? 'active' : 'paused'}</span>`);
  }
  if (health?.api_errors) parts.push(`<span class="badge ${health.api_errors > 5 ? 'warn' : ''}">${health.api_errors} API errors</span>`);
  el.innerHTML = parts.join(' ');
}

/* ------------------------------------------------------------------- chart */
/**
 * Draw a price-over-time chart on a canvas.
 * @param {HTMLCanvasElement} canvas
 * @param {object} opts
 * @param {{ts:number, price:number}[]} opts.points
 * @param {{ts:number, direction:string, delta:number, label?:string}[]} opts.markers swing markers
 * @param {string} opts.unit 's' | 'm' | 'h' — x-axis granularity/labels
 * @param {string} opts.title
 */
export function drawChart(canvas, opts = {}) {
  const { points = [], markers = [], unit = 'm', title = '' } = opts;
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || 600;
  const cssHeight = canvas.clientHeight || 320;
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const pad = { l: 48, r: 12, t: 16, b: 26 };
  const w = cssWidth - pad.l - pad.r;
  const h = cssHeight - pad.t - pad.b;

  ctx.fillStyle = '#0c121a';
  ctx.fillRect(0, 0, cssWidth, cssHeight);

  if (!points.length) {
    ctx.fillStyle = '#64748b';
    ctx.font = '13px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No price points in range', cssWidth / 2, cssHeight / 2);
    return;
  }

  const xs = points.map((p) => p.ts);
  const ys = points.map((p) => p.price);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  let minY = Math.min(...ys);
  let maxY = Math.max(...ys);
  const padY = Math.max(0.01, (maxY - minY) * 0.15);
  minY = Math.max(0, minY - padY);
  maxY = Math.min(1, maxY + padY);
  if (maxY - minY < 0.02) { const mid = (maxY + minY) / 2; minY = Math.max(0, mid - 0.01); maxY = Math.min(1, mid + 0.01); }

  const sx = (t) => (maxX === minX ? pad.l + w / 2 : pad.l + ((t - minX) / (maxX - minX)) * w);
  const sy = (p) => pad.t + h - ((p - minY) / (maxY - minY)) * h;

  // grid + y axis
  ctx.strokeStyle = '#1c2635';
  ctx.fillStyle = '#64748b';
  ctx.font = '11px ui-monospace, monospace';
  ctx.textAlign = 'right';
  ctx.lineWidth = 1;
  const yTicks = 5;
  for (let i = 0; i <= yTicks; i += 1) {
    const price = minY + ((maxY - minY) * i) / yTicks;
    const y = sy(price);
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
    ctx.fillText(`$${price.toFixed(2)}`, pad.l - 7, y + 4);
  }

  // x axis ticks
  ctx.textAlign = 'center';
  const xTicks = Math.max(3, Math.min(7, Math.floor(w / 110)));
  for (let i = 0; i <= xTicks; i += 1) {
    const t = minX + ((maxX - minX) * i) / xTicks;
    const x = sx(t);
    ctx.strokeStyle = '#141d29';
    ctx.beginPath();
    ctx.moveTo(x, pad.t);
    ctx.lineTo(x, pad.t + h);
    ctx.stroke();
    ctx.fillText(formatAxisTime(t, unit), x, cssHeight - 8);
  }

  // swing markers
  for (const marker of markers) {
    if (marker.ts < minX || marker.ts > maxX) continue;
    const x = sx(marker.ts);
    ctx.strokeStyle = marker.direction === 'up' ? 'rgba(52,211,153,.55)' : 'rgba(248,113,113,.55)';
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, pad.t);
    ctx.lineTo(x, pad.t + h);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = marker.direction === 'up' ? '#34d399' : '#f87171';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(marker.direction === 'up' ? '▲' : '▼', x, pad.t + 10);
  }

  // price line
  const gradient = ctx.createLinearGradient(0, pad.t, 0, pad.t + h);
  gradient.addColorStop(0, 'rgba(0,182,122,.30)');
  gradient.addColorStop(1, 'rgba(0,182,122,0)');
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = sx(p.ts);
    const y = sy(p.price);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#00b67a';
  ctx.lineWidth = 1.8;
  ctx.stroke();
  ctx.lineTo(sx(points[points.length - 1].ts), pad.t + h);
  ctx.lineTo(sx(points[0].ts), pad.t + h);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // last price dot
  const last = points[points.length - 1];
  ctx.fillStyle = '#00b67a';
  ctx.beginPath();
  ctx.arc(sx(last.ts), sy(last.price), 3.2, 0, Math.PI * 2);
  ctx.fill();

  if (title) {
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(title, pad.l + 2, 11);
  }

  // crosshair interaction
  canvas.onmousemove = (event) => {
    const rect = canvas.getBoundingClientRect();
    const mx = event.clientX - rect.left;
    const my = event.clientY - rect.top;
    drawChart(canvas, { points, markers, unit, title });
    const t = minX + ((mx - pad.l) / w) * (maxX - minX);
    let nearest = points[0];
    for (const p of points) {
      if (Math.abs(p.ts - t) < Math.abs(nearest.ts - t)) nearest = p;
    }
    const x = sx(nearest.ts);
    const y = sy(nearest.price);
    ctx.strokeStyle = 'rgba(148,163,184,.45)';
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(x, pad.t);
    ctx.lineTo(x, pad.t + h);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#e8eef6';
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
    ctx.fill();

    const tip = canvas.parentElement?.querySelector('.chart-tip');
    if (tip) {
      tip.style.opacity = '1';
      tip.style.left = `${Math.min(Math.max(x - 60, 4), rect.width - 130)}px`;
      tip.style.top = `${Math.max(y - 40, 4)}px`;
      tip.textContent = `${formatAxisTime(nearest.ts, unit)} · $${nearest.price.toFixed(3)}`;
    }
  };
  canvas.onmouseleave = () => {
    const tip = canvas.parentElement?.querySelector('.chart-tip');
    if (tip) tip.style.opacity = '0';
    drawChart(canvas, { points, markers, unit, title });
  };
}

export function formatAxisTime(ts, unit) {
  const d = new Date(ts * 1000);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  if (unit === 's') return `${hh}:${mm}:${ss}`;
  if (unit === 'h') return `${hh}:00`;
  return `${hh}:${mm}`;
}

/** Combine candle history + recorded price points into one sorted series. */
export function buildSeries(data, ticker, { windowSeconds = 6 * 3600, unit = 'm' } = {}) {
  const candles = (data.candles?.[ticker] || []).map((c) => ({ ts: c.ts, price: c.close }));
  const points = (data.prices?.[ticker] || []).map(([ts, price]) => ({ ts, price }));
  const merged = [...candles, ...points].sort((a, b) => a.ts - b.ts);
  const cutoff = Math.floor(Date.now() / 1000) - windowSeconds;
  const inWindow = merged.filter((p) => p.ts >= cutoff);
  const series = inWindow.length >= 2 ? inWindow : merged.slice(-120);
  if (unit === 'h') return aggregateByHour(series);
  return series;
}

export function aggregateByHour(series) {
  const buckets = new Map();
  for (const point of series) {
    const key = Math.floor(point.ts / 3600) * 3600;
    const bucket = buckets.get(key);
    if (!bucket) buckets.set(key, { ts: key, price: point.price, n: 1 });
    else { bucket.price = (bucket.price * bucket.n + point.price) / (bucket.n + 1); bucket.n += 1; }
  }
  return [...buckets.values()].sort((a, b) => a.ts - b.ts);
}

export function topicBadge(topic) {
  const meta = TOPICS[topic];
  if (!meta) return `<span class="badge">${esc(topic || 'unclassified')}</span>`;
  return `<span class="badge topic-${esc(topic)}">${esc(meta.short)}</span>`;
}

export function sourceLinks(alert) {
  const links = [];
  if (alert.kalshi_url) links.push(`<a href="${esc(alert.kalshi_url)}" target="_blank" rel="noopener">Kalshi market</a>`);
  for (const source of (alert.settlement_sources || []).slice(0, 3)) {
    if (source?.url) links.push(`<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.name || 'source')}</a>`);
  }
  return links;
}

export function setText(selector, value) {
  document.querySelectorAll(selector).forEach((el) => { el.textContent = value; });
}

export function element(tag, className, html) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (html !== undefined) el.innerHTML = html;
  return el;
}
