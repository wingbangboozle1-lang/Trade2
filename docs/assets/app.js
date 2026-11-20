/* Kalshi demo dashboard front-end.
   Reads only the JSON written by the collector (docs/data/*.json) via relative
   URLs, so it works on GitHub Pages under /Trade2/. Every table row renders the
   row's own source_url; values that are null are printed as a flagged blank,
   never as a guess. Polling keeps the page live. */
(function () {
  "use strict";

  const TOPICS = [
    { key: "gas-prices", label: "Gas prices", page: "gas-prices.html" },
    { key: "elections",  label: "Elections",  page: "elections.html" },
    { key: "culture",    label: "Culture",    page: "culture.html" },
    { key: "crypto",     label: "Crypto",     page: "crypto.html" },
    { key: "golf",       label: "Golf",       page: "golf.html" },
  ];
  const ALERT_THRESHOLD = 0.10; // official requirement: >= $0.10 either direction
  const POLL_MS = 20000;

  const S = { markets: [], books: {}, alerts: [], resolutions: [], candles: {},
              portfolio: null, meta: null, series: [] };
  let pollTimer = null;

  const $  = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  async function j(path) {
    try {
      const r = await fetch(path + "?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) { return null; }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(x, d) {
    if (x == null || isNaN(x)) return null; // blank cell: caller flags it
    return "$" + Number(x).toFixed(d == null ? 2 : d);
  }
  function num(x, d) {
    if (x == null || isNaN(x)) return null;
    return Number(x).toFixed(d == null ? 0 : d);
  }
  function blank(cell) {
    return '<span class="flag" title="Could not be confirmed from an official source — left blank and flagged">— <span class="badge unv">unv</span></span>';
  }
  function cell(v, fn, d) {
    const s = fn(v, d);
    return s == null ? blank() : esc(s);
  }
  function ts(t) {
    if (!t) return "";
    const dt = typeof t === "number" ? new Date(t * 1000) : new Date(t);
    return dt.toISOString().replace("T", " ").slice(0, 19) + "Z";
  }
  function clock(t) {
    const dt = typeof t === "number" ? new Date(t * 1000) : new Date(t);
    return dt.toISOString().slice(11, 19);
  }
  function srcLink(url, label) {
    if (!url) return blank();
    return `<a class="src" href="${esc(url)}" target="_blank" rel="noopener">${esc(label || "source")} ↗</a>`;
  }
  function badge(verified) {
    return verified
      ? '<span class="badge ok">verified</span>'
      : '<span class="badge unv">unverified</span>';
  }
  function topicLabel(key) {
    const t = TOPICS.find(t => t.key === key);
    return t ? t.label : (key || "");
  }

  /* ------------------------------------------------------------ data load */
  async function loadAll(need) {
    need = need || {};
    const jobs = [];
    const grab = (key, path) => { jobs.push(j(path).then(v => { S[key] = v; })); };
    if (need.markets !== false) {
      grab("markets", "data/markets.json");
      grab("books", "data/orderbooks.json");
      grab("candles", "data/candles.json");
      grab("series", "data/series.json");
    }
    if (need.alerts !== false) grab("alerts", "data/alerts.json");
    if (need.res !== false) grab("resolutions", "data/resolutions.json");
    if (need.portfolio) grab("portfolio", "data/portfolio.json");
    if (need.meta !== false) grab("meta", "data/run_meta.json");
    await Promise.all(jobs);
    if (S.markets && S.markets.rows) S.markets = S.markets.rows;
    if (!Array.isArray(S.markets)) S.markets = [];
    if (S.alerts && S.alerts.alerts) S.alerts = S.alerts.alerts;
    if (!Array.isArray(S.alerts)) S.alerts = [];
    if (S.resolutions && S.resolutions.rows) S.resolutions = S.resolutions.rows;
    if (!Array.isArray(S.resolutions)) S.resolutions = [];
    if (S.books && S.books.books) S.books = S.books.books;
    if (!S.books) S.books = {};
    if (S.candles && S.candles.series) S.candles = S.candles.series;
    if (!S.candles) S.candles = {};
    if (S.series && S.series.rows) S.series = S.series.rows;
    if (!Array.isArray(S.series)) S.series = [];
  }

  function freshness() {
    const el = $("#freshness");
    if (!el) return;
    if (liveMode) {
      el.textContent = `local live stream · ${S.meta && S.meta.finished_at ? "snapshot " + ts(S.meta.finished_at) : "SSE connected"}`;
      el.className = "";
      return;
    }
    const g = S.meta && (S.meta.finished_at || S.meta.generated_at);
    if (!g) {
      el.innerHTML = 'no data yet — waiting for first collector run';
      el.className = "stale";
      return;
    }
    const errs = (S.meta.counts && S.meta.counts.errors) || 0;
    el.textContent = `data: ${ts(g)} · ${errs} error${errs === 1 ? "" : "s"} · ${S.meta.environment || ""}`;
    el.className = "";
  }

  /* ------------------------------------------------- optional local live mode
     When served by live/server.py, an SSE endpoint exists and pushes straight
     from the demo API every 5s. On GitHub Pages that endpoint 404s and we simply
     keep polling the published JSON — no error surfaced to the user. */
  let liveMode = false;
  function fnum(x) { const v = parseFloat(x); return isNaN(v) ? null : v; }
  function parseBook(ob) {
    const fp = (ob && ob.orderbook_fp) || {};
    const yes = fp.yes_dollars || [], no = fp.no_dollars || [];
    const best = levels => levels.length ? Math.max(...levels.map(l => parseFloat(l[0])).filter(v => !isNaN(v))) : null;
    const depth = levels => {
      let c = 0, d = 0;
      levels.forEach(l => { const p = parseFloat(l[0]), n = parseFloat(l[1]); if (!isNaN(p) && !isNaN(n)) { c += n; d += p * n; } });
      return [Math.round(c * 100) / 100, Math.round(d * 100) / 100];
    };
    const [yc, yd] = depth(yes), [nc, nd] = depth(no);
    const yb = best(yes), nb = best(no);
    return {
      yes_levels: yes, no_levels: no, best_yes_bid: yb, best_no_bid: nb,
      implied_yes_ask: nb != null ? Math.round((1 - nb) * 10000) / 10000 : null,
      yes_depth_contracts: yc, yes_depth_usd: yd, no_depth_contracts: nc, no_depth_usd: nd,
      source_url: "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + ob.__ticker,
      docs_url: "https://docs.kalshi.com/getting_started/orderbook_responses",
    };
  }
  function ingest(snap) {
    if (!snap || !Array.isArray(snap.markets)) return;
    const byT = {};
    S.markets.forEach(m => { if (m && m.ticker) byT[m.ticker] = m; });
    snap.markets.forEach(raw => {
      if (!raw || !raw.ticker) return;
      const last = fnum(raw.last_price_dollars);
      const bid = fnum(raw.yes_bid_dollars), ask = fnum(raw.yes_ask_dollars);
      const vol = fnum(raw.volume_fp);
      const px = last != null ? last : (bid != null && ask != null ? (bid + ask) / 2 : null);
      byT[raw.ticker] = {
        ticker: raw.ticker, event_ticker: raw.event_ticker, title: raw.title,
        topic: raw._topic || (byT[raw.ticker] && byT[raw.ticker].topic),
        series_ticker: raw.series_ticker, status: raw.status,
        yes_bid: bid, yes_ask: ask, last_price: last, volume_fp: vol,
        open_interest_fp: fnum(raw.open_interest_fp),
        notional_usd: vol != null && px != null ? Math.round(vol * px * 100) / 100 : null,
        expected_expiration: raw.expected_expiration_ts,
        fee_type: raw.fee_type, price_level_structure: raw.price_level_structure,
        source_url: "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + raw.ticker,
        docs_url: "https://docs.kalshi.com/api-reference/market/get-markets",
        flags: [], verified: true, _live: true,
      };
    });
    S.markets = Object.values(byT);
    Object.entries(snap.books || {}).forEach(([t, ob]) => {
      if (ob) { ob.__ticker = t; S.books[t] = parseBook(ob); }
    });
    if (S.meta) S.meta.finished_at = new Date(snap.fetched_at * 1000).toISOString();
  }
  function tryLiveStream() {
    if (typeof EventSource === "undefined") return;
    let es;
    try { es = new EventSource("api/stream"); } catch (e) { return; }
    es.onopen = () => { liveMode = true; render(); flashDot(); };
    es.onmessage = ev => {
      try { ingest(JSON.parse(ev.data)); render(); flashDot(); } catch (e) { /* ignore partial frame */ }
    };
    es.onerror = () => {
      if (!liveMode) es.close();      // no local server (GitHub Pages) -> keep polling
    };
  }
  function flashDot() {
    const live = $("#live-dot");
    if (live) { live.style.background = "var(--green)"; setTimeout(() => { live.style.background = ""; }, 600); }
  }

  /* --------------------------------------------------------------- charts */
  function drawLine(canvas, pts, opts) {
    opts = opts || {};
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 240;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const c = canvas.getContext("2d");
    if (!c) return; // no canvas context (headless/unsupported): skip drawing
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    if (!pts || pts.length < 2) {
      c.fillStyle = "#6e7681"; c.font = "13px sans-serif"; c.textAlign = "center";
      c.fillText("No official price series for this window yet", w / 2, h / 2);
      return;
    }
    const padL = 46, padR = 12, padT = 12, padB = 26;
    let min = Math.min(...pts.map(p => p.y)), max = Math.max(...pts.map(p => p.y));
    if (min === max) { min -= 0.05; max += 0.05; }
    const minPad = 0.02; // keep at least a 2c band visible
    if (max - min < minPad) { const m = (max + min) / 2; min = m - minPad / 2; max = m + minPad / 2; }
    min = Math.max(0, min - 0.02); max = Math.min(1, max + 0.02);
    const t0 = Math.min(...pts.map(p => p.t)), t1 = Math.max(...pts.map(p => p.t));
    const X = t => padL + (w - padL - padR) * (t1 === t0 ? 0.5 : (t - t0) / (t1 - t0));
    const Y = v => padT + (h - padT - padB) * (1 - (v - min) / (max - min));

    c.strokeStyle = "#2d3340"; c.lineWidth = 1;
    c.fillStyle = "#8b949e"; c.font = "10px monospace"; c.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const v = min + (max - min) * i / 4, y = Y(v);
      c.beginPath(); c.moveTo(padL, y); c.lineTo(w - padR, y); c.stroke();
      c.fillText("$" + v.toFixed(2), padL - 6, y + 3);
    }
    c.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const t = t0 + (t1 - t0) * i / 4, x = X(t);
      const d = new Date(t * 1000);
      const lbl = (opts.window === "hours")
        ? d.toISOString().slice(11, 16)
        : d.toISOString().slice(11, 19);
      c.fillText(lbl, x, h - 8);
    }
    // swing markers (>= $0.10 moves) where we have alert evidence
    (opts.markers || []).forEach(mk => {
      const x = X(mk.t), y = Y(mk.y);
      c.fillStyle = mk.delta > 0 ? "#3fb950" : "#f85149";
      c.beginPath(); c.arc(x, y, 4, 0, Math.PI * 2); c.fill();
      c.strokeStyle = "#0d1117"; c.lineWidth = 1.5; c.stroke();
    });
    // price line
    c.strokeStyle = opts.color || "#58a6ff"; c.lineWidth = 2;
    c.beginPath();
    pts.forEach((p, i) => { const x = X(p.t), y = Y(p.y); i ? c.lineTo(x, y) : c.moveTo(x, y); });
    c.stroke();
    // last dot
    const last = pts[pts.length - 1];
    c.fillStyle = opts.color || "#58a6ff";
    c.beginPath(); c.arc(X(last.t), Y(last.y), 3.5, 0, Math.PI * 2); c.fill();
    c.fillStyle = "#e6edf3"; c.font = "bold 11px monospace"; c.textAlign = "left";
    c.fillText("$" + last.y.toFixed(2) + "  " + clock(last.t) + "Z", Math.min(X(last.t) + 8, w - 90), Y(last.y) - 8);
  }

  function drawDepth(canvas, book) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 200;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const c = canvas.getContext("2d");
    if (!c) return; // no canvas context (headless/unsupported): skip drawing
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    const yes = (book && book.yes_levels) || [], no = (book && book.no_levels) || [];
    if (!yes.length && !no.length) {
      c.fillStyle = "#6e7681"; c.font = "13px sans-serif"; c.textAlign = "center";
      c.fillText("Empty book (official endpoint returned no resting orders)", w / 2, h / 2);
      return;
    }
    const all = yes.concat(no);
    const prices = all.map(l => parseFloat(l[0]));
    const counts = all.map(l => parseFloat(l[1]));
    const pMin = Math.min(...prices), pMax = Math.max(...prices);
    const cMax = Math.max(...counts) || 1;
    const padL = 46, padR = 12, padT = 10, padB = 26;
    const X = p => padL + (w - padL - padR) * (pMax === pMin ? 0.5 : (p - pMin) / (pMax - pMin));
    const Y = v => padT + (h - padT - padB) * (1 - v / cMax);
    c.strokeStyle = "#2d3340";
    c.fillStyle = "#8b949e"; c.font = "10px monospace"; c.textAlign = "right";
    for (let i = 0; i <= 3; i++) {
      const v = cMax * i / 3, y = Y(v);
      c.beginPath(); c.moveTo(padL, y); c.lineTo(w - padR, y); c.stroke();
      c.fillText(String(Math.round(v)), padL - 6, y + 3);
    }
    c.textAlign = "center";
    for (let i = 0; i <= 4; i++) {
      const p = pMin + (pMax - pMin) * i / 4;
      c.fillText("$" + p.toFixed(2), X(p), h - 8);
    }
    const bw = Math.max(4, (w - padL - padR) / Math.max(all.length, 1) * 0.42);
    function bars(levels, color) {
      levels.forEach(l => {
        const p = parseFloat(l[0]), n = parseFloat(l[1]);
        if (isNaN(p) || isNaN(n)) return;
        c.fillStyle = color;
        c.fillRect(X(p) - bw / 2, Y(n), bw, h - padB - Y(n));
      });
    }
    bars(yes, "rgba(63,185,80,.85)");
    bars(no, "rgba(248,81,73,.8)");
    c.font = "bold 11px sans-serif"; c.textAlign = "left";
    c.fillStyle = "#3fb950"; c.fillText("YES bids", padL + 4, padT + 12);
    c.fillStyle = "#f85149"; c.fillText("NO bids", padL + 74, padT + 12);
  }

  /* ---------------------------------------------------------- chat feeds */
  function alertMsg(a, roi) {
    const dir = a.delta >= 0 ? "up" : "down";
    const headlines = (a.headlines || []).map(h =>
      `<a class="news" href="${esc(h.url)}" target="_blank" rel="noopener" title="${esc(h.title)}">📰 ${esc(h.title.slice(0, 90))}</a>`
    ).join("");
    const news = headlines ||
      `<span class="flag" style="font-size:11px">no verified headline in window — link left blank</span>`;
    return `<div class="msg ${roi ? "roi" : dir}">
      <div class="t">${esc(clock(a.t) || ts(a.t_iso))}Z ${roi ? "· high-ROI" : ""}</div>
      <div><span class="hd ${dir}">${a.delta >= 0 ? "▲" : "▼"} ${money(Math.abs(a.delta))}</span>
        <span class="tk">${esc(a.ticker)}</span></div>
      <div>${esc(a.title || "")} · ${esc(topicLabel(a.topic))}</div>
      <div class="tk">${money(a.from) || "—"} → <b>${money(a.to) || "—"}</b> (${esc(a.window)} window)</div>
      ${news}
      <div>${srcLink(a.source_url, "market")} ${a.candle_source_url ? srcLink(a.candle_source_url, "candles") : ""}</div>
    </div>`;
  }

  function roiScore(a) {
    // mirrors trading/engine.py: reversion_share * swing - fee - spread >= roi_min
    const P = (S.portfolio && S.portfolio.parameters) || {};
    const rev = P.reversion_share != null ? P.reversion_share : 0.30;
    const min = P.roi_min != null ? P.roi_min : 0.02;
    const book = S.books[a.ticker];
    if (!book) return null;
    const yb = book.best_yes_bid, nb = book.best_no_bid;
    if (yb == null || nb == null) return null;
    const ask = 1 - nb, spread = ask - yb;
    const price = a.delta >= 0 ? 1 - yb : ask; // fade side price (same as engine)
    const fee = Math.ceil(0.07 * 1 * price * (1 - price) * 100) / 100;
    const score = rev * Math.abs(a.delta) - fee - spread;
    return { score, min, spread, fee };
  }

  function renderChats() {
    const all = $("#feed-all"), roi = $("#feed-roi");
    if (!all || !roi) return;
    const items = S.alerts.slice(0, 60);
    all.innerHTML = items.length
      ? items.map(a => alertMsg(a, false)).join("")
      : '<div class="empty">No ≥ $0.10 swings in the latest collector window.<br>Alerts appear within one poll of an official candlestick move.</div>';
    const P = (S.portfolio && S.portfolio.parameters) || {};
    const roiMin = P.roi_min != null ? P.roi_min : 0.02;
    const roiAlerts = items.filter(a => { const r = roiScore(a); return r && r.score >= roiMin; });
    // engine's actual high-ROI entries, newest first
    const roiTrades = ((S.portfolio && S.portfolio.trades) || [])
      .filter(t => t.action === "open" && t.strategy === "roi_edge").slice(0, 20)
      .map(t => ({
        t: t.ts, ticker: t.ticker, title: t.reason || t.signal, topic: t.topic,
        delta: null, side: t.side, price: t.price, source_url: t.source_url,
        from: null, to: t.price, window: "entry", headlines: [], trade: t,
      }));
    const merged = roiAlerts.map(a => Object.assign({}, a, { _roi: true })).concat(roiTrades);
    roi.innerHTML = merged.length
      ? merged.map(x => x.trade ? roiTradeMsg(x) : alertMsg(x, true)).join("")
      : `<div class="empty">High-ROI filter (score = ${revPct()} × swing − fee − spread ≥ ${money(roiMin)}) found nothing this window.</div>`;
  }
  function revPct() {
    const P = (S.portfolio && S.portfolio.parameters) || {};
    return Math.round((P.reversion_share != null ? P.reversion_share : 0.30) * 100) + "%";
  }
  function roiTradeMsg(t) {
    return `<div class="msg roi">
      <div class="t">${esc(ts(t.ts))} · engine entry</div>
      <div><span class="hd" style="color:var(--purple)">◆ ROI ENTRY</span> <span class="tk">${esc(t.ticker)}</span></div>
      <div>${esc(t.side.toUpperCase())} @ ${money(t.price)} · ${esc(t.trade.signal)} · ${esc(topicLabel(t.topic))}</div>
      <div class="tk">${esc(t.trade.reason || "")}</div>
      <div>${srcLink(t.source_url, "market")}</div>
    </div>`;
  }

  /* -------------------------------------------------------- table: markets */
  function marketRows(list) {
    return list.map(m => {
      const book = S.books[m.ticker] || {};
      const liq = book.yes_depth_usd != null ? money(book.yes_depth_usd) : blank();
      const bid = m.yes_bid != null ? money(m.yes_bid) : blank();
      const ask = m.yes_ask != null ? money(m.yes_ask) : blank();
      const last = m.last_price != null ? money(m.last_price) : blank();
      const vol = m.volume_fp != null ? num(m.volume_fp) : blank();
      const notional = m.notional_usd != null ? money(m.notional_usd) : blank();
      const flags = (m.flags || []).length
        ? `<span class="badge unv" title="${esc(m.flags.join("; "))}">flag</span>` : "";
      return `<tr data-topic="${esc(m.topic)}">
        <td><a href="https://external-api.demo.kalshi.co/trade-api/v2/markets/${encodeURIComponent(m.ticker)}" target="_blank" rel="noopener"><span class="mono">${esc(m.ticker)}</span></a> ${flags}</td>
        <td>${esc(m.title || "")}</td>
        <td>${bid}</td><td>${ask}</td><td>${last}</td>
        <td class="num">${vol}</td><td class="num">${notional}</td><td class="num">${liq}</td>
        <td>${srcLink(m.source_url, "api")} ${srcLink(m.docs_url, "docs")}</td>
      </tr>`;
    }).join("");
  }
  const MARKET_HEAD = `<tr><th data-k="ticker">Market</th><th data-k="title">Title</th>
    <th data-k="yes_bid" class="num">YES bid</th><th data-k="yes_ask" class="num">YES ask</th>
    <th data-k="last_price" class="num">Last</th><th data-k="volume_fp" class="num">Vol</th>
    <th data-k="notional_usd" class="num">$ volume</th><th>Book liquidity</th><th>Source</th></tr>`;

  function renderMarketsTable(el, list, limit) {
    if (!el) return;
    const rows = (limit ? list.slice(0, limit) : list);
    el.innerHTML = `<table class="data"><thead>${MARKET_HEAD}</thead><tbody>${marketRows(rows)}</tbody></table>`;
    wireSort(el, list, renderMarketsTable, limit);
  }

  function wireSort(el, list, rerender, limit) {
    $$("th[data-k]", el).forEach(th => {
      th.onclick = () => {
        const k = th.dataset.k;
        const sorted = list.slice().sort((a, b) => {
          const av = a[k], bv = b[k];
          if (av == null && bv == null) return 0;
          if (av == null) return 1;   // blanks sink: never imply a value
          if (bv == null) return -1;
          return typeof av === "number" ? bv - av : String(bv).localeCompare(String(av));
        });
        rerender(el, sorted, limit);
      };
    });
  }

  /* ------------------------------------------------------- page renderers */
  function renderIndex() {
    const wrap = $("#stats");
    if (!wrap) return;
    const open = S.markets.filter(m => m.status === "open" || m.status === "active");
    const totalVol = open.reduce((s, m) => s + (m.notional_usd || 0), 0);
    const byTopic = {};
    TOPICS.forEach(t => { byTopic[t.key] = { n: 0, vol: 0, top: null }; });
    open.forEach(m => {
      const b = byTopic[m.topic]; if (!b) return;
      b.n++; b.vol += m.notional_usd || 0;
      if (!b.top || (m.notional_usd || 0) > (b.top.notional_usd || 0)) b.top = m;
    });
    const acc = S.portfolio && S.portfolio.account;
    wrap.innerHTML = `
      <div class="stat"><div class="k">Markets tracked</div><div class="v">${open.length}</div>
        <div class="s">across 5 topics · ranked by $ volume</div></div>
      <div class="stat"><div class="k">Swings ≥ $0.10 (last run)</div><div class="v">${S.alerts.length}</div>
        <div class="s">alert threshold, both directions</div></div>
      <div class="stat"><div class="k">Resolved (YES/NO)</div><div class="v">${S.resolutions.length}</div>
        <div class="s">settlement graded in portfolio</div></div>
      <div class="stat"><div class="k">Paper equity</div>
        <div class="v ${acc && acc.equity >= 10000 ? "up" : "down"}">${acc ? money(acc.equity) : blank()}</div>
        <div class="s">${acc ? (acc.equity - 10000 >= 0 ? "+" : "") + money(acc.equity - 10000) + " vs start · fees " + money(acc.fees_paid) : "awaiting engine run"}</div></div>`;

    const tc = $("#topic-cards");
    if (tc) {
      tc.innerHTML = TOPICS.map(t => {
        const b = byTopic[t.key];
        return `<a class="topic-card" href="${t.page}">
          <div class="name">${t.label}</div>
          <div class="meta">${b.n} live market${b.n === 1 ? "" : "s"} · ${money(b.vol)} tracked $ volume</div>
          <div class="big">${b.top ? money(b.top.last_price != null ? b.top.last_price : b.top.yes_bid) : "—"}</div>
          <div class="meta">${b.top ? esc(b.top.ticker) : "no market data yet"}</div>
        </a>`;
      }).join("");
    }
    const top = $("#top-markets");
    if (top) renderMarketsTable(top, open.slice(0, 12));

    const res = $("#recent-resolutions");
    if (res) {
      const rows = S.resolutions.slice(0, 8);
      res.innerHTML = rows.length ? `<table class="data"><thead><tr>
        <th>Market</th><th>Topic</th><th>Outcome</th><th>Settled</th><th>Source</th></tr></thead><tbody>
        ${rows.map(r => `<tr>
          <td><span class="mono">${esc(r.ticker)}</span> ${esc(r.title || "")}</td>
          <td>${esc(topicLabel(r.topic))}</td>
          <td><b class="${r.result === "yes" ? "up" : "down"}">${String(r.result || "").toUpperCase()}</b></td>
          <td>${esc(ts(r.settlement_ts))}</td>
          <td>${srcLink(r.source_url, "api")} ${srcLink(r.docs_url, "rules")}</td></tr>`).join("")}
        </tbody></table>` : '<div class="empty">No settlements in this collector run.</div>';
    }
  }

  function renderTopic(topicKey) {
    const list = S.markets.filter(m => m.topic === topicKey);
    renderMarketsTable($("#markets"), list);

    const alerts = S.alerts.filter(a => a.topic === topicKey);
    const aw = $("#topic-alerts");
    if (aw) {
      aw.innerHTML = alerts.length
        ? `<table class="data"><thead><tr><th>Time (UTC)</th><th>Market</th><th>Move</th>
            <th>From → To</th><th>Possible catalyst headlines</th><th>Source</th></tr></thead><tbody>
        ${alerts.map(a => `<tr>
          <td class="mono">${esc(clock(a.t))}Z</td>
          <td><span class="mono">${esc(a.ticker)}</span><br>${esc(a.title || "")}</td>
          <td><b class="${a.delta >= 0 ? "up" : "down"}">${a.delta >= 0 ? "▲" : "▼"} ${money(Math.abs(a.delta))}</b></td>
          <td class="num">${money(a.from)} → ${money(a.to)}</td>
          <td>${(a.headlines || []).length
              ? a.headlines.map(h => `<a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a><br>`).join("")
              : '<span class="flag">no verified headline in window — left blank</span>'}</td>
          <td>${srcLink(a.source_url, "api")} ${a.candle_source_url ? srcLink(a.candle_source_url, "candles") : ""}</td>
        </tr>`).join("")}</tbody></table>`
        : '<div class="empty">No ≥ $0.10 swings recorded for this topic in the latest run.</div>';
    }

    const res = S.resolutions.filter(r => r.topic === topicKey);
    const rw = $("#topic-resolutions");
    if (rw) {
      rw.innerHTML = res.length ? `<table class="data"><thead><tr>
        <th>Market</th><th>Outcome</th><th>Settlement value</th><th>Settled at</th><th>Volume</th><th>Source</th>
        </tr></thead><tbody>${res.map(r => `<tr>
          <td><span class="mono">${esc(r.ticker)}</span> ${esc(r.title || "")}</td>
          <td><b class="${r.result === "yes" ? "up" : "down"}">${String(r.result || "").toUpperCase()}</b></td>
          <td class="num">${r.settlement_value != null ? money(r.settlement_value) : blank()}</td>
          <td>${esc(ts(r.settlement_ts))}</td>
          <td class="num">${r.volume_fp != null ? num(r.volume_fp) : blank()}</td>
          <td>${srcLink(r.source_url, "api")} ${srcLink(r.docs_url, "rules")}</td></tr>`).join("")}
        </tbody></table>` : '<div class="empty">No resolved markets for this topic yet.</div>';
    }

    // market picker + charts
    const sel = $("#pick-market");
    if (sel) {
      const sorted = list.slice().sort((a, b) => (b.notional_usd || 0) - (a.notional_usd || 0));
      const prev = sel.value;
      sel.innerHTML = sorted.map(m =>
        `<option value="${esc(m.ticker)}">${esc(m.ticker)} — ${esc((m.title || "").slice(0, 70))}</option>`).join("");
      if (prev && sorted.some(m => m.ticker === prev)) sel.value = prev;
      sel.onchange = () => drawTopicCharts(topicKey, sel.value);
      drawTopicCharts(topicKey, sel.value);
    }
  }

  let chartWindow = "minutes";
  function drawTopicCharts(topicKey, ticker) {
    if (!ticker) return;
    const win = chartWindow;
    const series = (S.candles[ticker] || {})[win] || {};
    const pts = (series.points || []).map(p => ({ t: p.t, y: p.close })).filter(p => p.y != null);
    const t0 = pts.length ? Math.min(...pts.map(p => p.t)) : 0;
    const t1 = pts.length ? Math.max(...pts.map(p => p.t)) : 0;
    const markers = S.alerts.filter(a => a.ticker === ticker && a.t >= t0 && a.t <= t1)
      .map(a => ({ t: a.t, y: a.to, delta: a.delta }));
    const cv = $("#price-chart");
    if (cv) drawLine(cv, pts, { window: win, markers });
    const book = S.books[ticker] || {};
    const dv = $("#depth-chart");
    if (dv) drawDepth(dv, book);
    const meta = $("#chart-meta");
    if (meta) {
      const yb = book.best_yes_bid, nb = book.best_no_bid;
      const ask = nb != null ? 1 - nb : null;
      const iv = series.interval;
      const ivLabel = iv === 1 ? "1-minute" : iv === 60 ? "1-hour" : iv === 1440 ? "1-day" : "unknown";
      meta.innerHTML = `
        <span>candles: <b>${ivLabel}</b> (finest official interval)</span>
        <span>best bid <b>${yb != null ? money(yb) : "—"}</b></span>
        <span>best ask <b>${ask != null ? money(ask) : "—"}</b></span>
        <span>spread <b>${yb != null && ask != null ? money(ask - yb) : "—"}</b></span>
        <span>YES depth <b>${book.yes_depth_usd != null ? money(book.yes_depth_usd) + " (" + num(book.yes_depth_contracts) + " ctr)" : "—"}</b></span>
        <span>NO depth <b>${book.no_depth_usd != null ? money(book.no_depth_usd) + " (" + num(book.no_depth_contracts) + " ctr)" : "—"}</b></span>
        ${srcLink(book.source_url, "orderbook api")} ${srcLink(series.source_url, "candles api")}`;
    }
    const newsBox = $("#swing-news");
    if (newsBox) {
      const rel = S.alerts.filter(a => a.ticker === ticker);
      newsBox.innerHTML = rel.length
        ? rel.map(a => `<div class="msg ${a.delta >= 0 ? "up" : "down"}" style="margin-bottom:6px">
            <div class="t">${esc(clock(a.t))}Z · swing ${a.delta >= 0 ? "+" : ""}${money(a.delta)}</div>
            ${(a.headlines || []).length
              ? a.headlines.map(h => `<a class="news" href="${esc(h.url)}" target="_blank" rel="noopener">📰 ${esc(h.title)}</a>`).join("")
              : '<span class="flag">no verified headline in window — link left blank</span>'}
            <div>${srcLink(a.source_url, "market")}</div></div>`).join("")
        : '<div class="empty">No swings ≥ $0.10 for this market in the latest run.</div>';
    }
  }

  function renderPortfolio() {
    const P = S.portfolio;
    const box = $("#pf-stats");
    if (!box) return;
    if (!P) { box.innerHTML = '<div class="stale">Portfolio JSON not found — run the collector workflow once.</div>'; return; }
    const a = P.account, st = P.stats || { all: {} };
    const eq = (st.all && st.all.net_pnl) || 0;
    box.innerHTML = `
      <div class="stat"><div class="k">Equity (simulated)</div><div class="v">${money(a.equity)}</div>
        <div class="s">cash ${money(a.cash)} · start ${money(a.starting_cash)}</div></div>
      <div class="stat"><div class="k">Realized P&amp;L</div>
        <div class="v ${a.realized_pnl >= 0 ? "up" : "down"}">${money(a.realized_pnl)}</div>
        <div class="s">after ${money(a.fees_paid)} official fees</div></div>
      <div class="stat"><div class="k">Closed trades</div><div class="v">${st.all ? st.all.trades : 0}</div>
        <div class="s">win rate ${st.all && st.all.win_rate != null ? (st.all.win_rate * 100).toFixed(0) + "%" : "—"}</div></div>
      <div class="stat"><div class="k">Open positions</div><div class="v">${a.open_positions}</div>
        <div class="s">${a.blocked_today ? '<span class="flag">daily loss cap hit — paused</span>' : "trading per risk limits"}</div></div>`;

    const curve = $("#equity-chart");
    if (curve) {
      const pts = (P.equity_curve || []).map(p => ({ t: Math.floor(new Date(p.ts).getTime() / 1000), y: p.equity }));
      drawLine(curve, pts, { color: "#bc8cff" });
    }

    const bs = $("#stats-by-strategy");
    if (bs) bs.innerHTML = statsTable(P.stats && P.stats.by_strategy, "Strategy");
    const bt = $("#stats-by-type");
    if (bt) bt.innerHTML = statsTable(P.stats && P.stats.by_trade_type, "Trade type");

    const op = $("#open-positions");
    if (op) {
      const pos = P.positions || [];
      op.innerHTML = pos.length ? `<table class="data"><thead><tr>
        <th>Market</th><th>Side</th><th>Contracts</th><th>Avg price</th><th>Strategy</th><th>Opened</th><th>Source</th>
        </tr></thead><tbody>${pos.map(p => `<tr>
          <td><span class="mono">${esc(p.ticker)}</span><br>${esc(topicLabel(p.topic))}</td>
          <td><b class="${p.side === "yes" ? "up" : "down"}">${esc(String(p.side).toUpperCase())}</b></td>
          <td class="num">${num(p.contracts)}</td><td class="num">${money(p.avg_price)}</td>
          <td>${esc(p.strategy)}<br><span class="tk" style="color:var(--muted);font-size:11px">${esc(p.reason || "")}</span></td>
          <td class="mono">${esc(ts(p.opened_at))}</td>
          <td>${srcLink("https://external-api.demo.kalshi.co/trade-api/v2/markets/" + encodeURIComponent(p.ticker), "api")}</td>
        </tr>`).join("")}</tbody></table>` : '<div class="empty">No open positions right now.</div>';
    }

    const tl = $("#trade-log");
    if (tl) {
      const rows = (P.trades || []).slice().reverse().slice(0, 80);
      tl.innerHTML = rows.length ? `<table class="data"><thead><tr>
        <th>Time (UTC)</th><th>Action</th><th>Market</th><th>Side</th><th>Qty</th><th>Price</th>
        <th>Fee</th><th>P&amp;L</th><th>Strategy / type</th><th>Source</th>
        </tr></thead><tbody>${rows.map(t => `<tr>
          <td class="mono">${esc(ts(t.ts))}</td>
          <td>${t.action === "open" ? '<span class="badge topic">buy</span>' : '<span class="badge ok">close</span>'}</td>
          <td><span class="mono">${esc(t.ticker)}</span></td>
          <td>${esc(String(t.side || "").toUpperCase())}</td>
          <td class="num">${num(t.contracts)}</td>
          <td class="num">${money(t.price)}</td>
          <td class="num">${money(t.fee)}</td>
          <td class="num ${t.pnl > 0 ? "up" : t.pnl < 0 ? "down" : ""}">${t.action === "close" ? money(t.pnl) : "—"}</td>
          <td>${esc(t.strategy || "")}<br><span style="color:var(--muted);font-size:11px">${esc(t.trade_type || "")}${t.exit_reason ? " · " + esc(t.exit_reason) : ""}${t.settlement ? " · settled " + esc(t.settlement) : ""}</span></td>
          <td>${srcLink(t.source_url, "api")} ${srcLink(t.fee_schedule_url, "fee pdf")}</td>
        </tr>`).join("")}</tbody></table>` : '<div class="empty">No trades yet.</div>';
    }

    const note = $("#pf-note");
    if (note) note.innerHTML = `
      <b>Mode: simulated paper trading.</b> No API credentials exist in this project (flag FL-01), so no orders
      are ever sent. Fills are simulated against the real demo order book, fees use the official formula
      (${esc((P.parameters || {}).fee_formula || "")}), and outcomes are graded against real settlements.
      Parameters: reversion share ${revPct()}, ROI ≥ ${money((P.parameters || {}).roi_min)}, target/stop
      ±${money((P.parameters || {}).exit_target)} / ${money((P.parameters || {}).exit_stop)}.
      ${srcLink((P.parameters || {}).fee_schedule_url, "official fee schedule PDF")}`;
  }

  function statsTable(obj, keyName) {
    if (!obj || !Object.keys(obj).length) return '<div class="empty">No closed trades yet — stats appear after the first exits.</div>';
    return `<table class="data"><thead><tr><th>${esc(keyName)}</th><th class="num">Trades</th>
      <th class="num">Wins</th><th class="num">Losses</th><th class="num">Win rate</th>
      <th class="num">Net P&amp;L</th><th class="num">Avg P&amp;L</th><th class="num">Fees</th></tr></thead>
      <tbody>${Object.entries(obj).map(([k, v]) => `<tr>
        <td>${esc(k)}</td><td class="num">${v.trades}</td><td class="num">${v.wins}</td>
        <td class="num">${v.losses}</td>
        <td class="num">${v.win_rate == null ? blank() : (v.win_rate * 100).toFixed(0) + "%"}</td>
        <td class="num ${v.net_pnl > 0 ? "up" : v.net_pnl < 0 ? "down" : ""}">${money(v.net_pnl)}</td>
        <td class="num">${v.avg_pnl == null ? blank() : money(v.avg_pnl)}</td>
        <td class="num">${money(v.fees)}</td></tr>`).join("")}</tbody></table>`;
  }

  /* --------------------------------------------------------------- flagged */
  function renderFlagged() {
    const box = $("#dynamic-flags");
    if (!box) return;
    const items = [];
    S.markets.forEach(m => (m.flags || []).forEach(f => items.push({
      kind: "market", id: m.ticker, detail: f, url: m.source_url, docs: m.docs_url, status: "unverified" })));
    S.alerts.forEach(a => (a.flags || []).forEach(f => items.push({
      kind: "alert", id: a.ticker, detail: f, url: a.source_url, docs: a.candle_source_url, status: "unverified" })));
    Object.entries(S.books).forEach(([t, b]) => (b.flags || []).forEach(f => items.push({
      kind: "orderbook", id: t, detail: f, url: b.source_url, docs: b.docs_url, status: "unverified" })));
    (S.resolutions || []).forEach(r => (r.flags || []).forEach(f => items.push({
      kind: "resolution", id: r.ticker, detail: f, url: r.source_url, docs: r.docs_url, status: "unverified" })));
    if (S.meta && S.meta.errors) S.meta.errors.forEach(e => items.push({
      kind: "collector", id: e.step || "run", detail: JSON.stringify(e), url: null,
      docs: "https://docs.kalshi.com/getting_started/rate_limits.md", status: "error" }));
    if (S.portfolio && S.portfolio.account && S.portfolio.account.blocked_today) items.push({
      kind: "risk", id: "daily-loss-cap", detail: "engine paused new entries after the daily loss cap (risk control, not a data problem)",
      url: null, docs: null, status: "info" });

    $("#flag-count").textContent = items.length;
    box.innerHTML = items.length ? `<table class="data"><thead><tr>
      <th>Status</th><th>Kind</th><th>Item</th><th>Detail (why it is flagged)</th><th>Source</th>
      </tr></thead><tbody>${items.map(i => `<tr>
        <td><span class="badge ${i.status === "info" ? "ok" : "unv"}">${esc(i.status)}</span></td>
        <td>${esc(i.kind)}</td><td class="mono">${esc(i.id)}</td>
        <td>${esc(i.detail)}</td>
        <td>${i.url ? srcLink(i.url, "api") : ""} ${i.docs ? srcLink(i.docs, "docs") : (!i.url ? '<span class="flag">no source</span>' : "")}</td>
      </tr>`).join("")}</tbody></table>`
      : '<div class="empty">No unverified values or collector errors in the latest run.</div>';
  }

  /* ---------------------------------------------------------------- pages */
  const page = document.body.dataset.page;

  async function refresh() {
    await loadAll({
      // in local SSE mode the stream owns markets/books; avoid overwriting with stale JSON
      markets: !liveMode,
      portfolio: page === "portfolio" || page === "index",
      meta: true,
    });
    render();
  }

  function render() {
    freshness();
    if (page === "index") { renderIndex(); renderChats(); }
    if (page === "topic") { renderTopic(document.body.dataset.topic); renderChats(); }
    if (page === "portfolio") renderPortfolio();
    if (page === "flagged") renderFlagged();
    flashDot();
  }

  function wireWindowSeg() {
    $$(".seg button[data-win]").forEach(b => {
      b.onclick = () => {
        $$(".seg button[data-win]").forEach(x => x.classList.remove("on"));
        b.classList.add("on");
        chartWindow = b.dataset.win;
        const topic = document.body.dataset.topic;
        const sel = $("#pick-market");
        if (topic && sel) drawTopicCharts(topic, sel.value);
      };
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireWindowSeg();
    refresh();
    tryLiveStream(); // upgrades to 5s SSE pushes when live/server.py is serving
    pollTimer = setInterval(refresh, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { clearInterval(pollTimer); pollTimer = null; }
      else if (!pollTimer) { refresh(); pollTimer = setInterval(refresh, POLL_MS); }
    });
  });
})();
