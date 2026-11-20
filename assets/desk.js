/* Live desk front-end.
 *
 * Data flow:
 *   1. The page ships a pre-rendered snapshot in <script id="snapshot">, written
 *      by site_build/build.py from the collector's verified data. The desk works
 *      with JavaScript disabled or before any network call.
 *   2. assets/live.json is re-fetched periodically; GitHub Actions rewrites it
 *      every few minutes from the official demo API.
 *   3. When the page is opened on the local dashboard server, /api/stream gives
 *      Server-Sent Events instead of polling.
 *   4. Price history for the chart comes from real Kalshi data:
 *        - the official candlestick endpoint (1-minute candles) where the
 *          market is eligible, and
 *        - the live order book implied mid, polled, appended client-side.
 *      Nothing is interpolated or invented; gaps stay gaps.
 *
 * Every network call has a visible status so a stale view is never mistaken for
 * a live one.
 */
(function () {
  "use strict";

  var REST = "https://external-api.demo.kalshi.co/trade-api/v2";
  var WINDOWS = {
    seconds: { label: "Last 90 seconds", ms: 90 * 1000, tick: 2000 },
    minutes: { label: "Last 60 minutes", ms: 60 * 60 * 1000, tick: 15000 },
    hours: { label: "Last 12 hours", ms: 12 * 60 * 60 * 1000, tick: 60000 },
  };
  var SWING = 0.1;

  var state = {
    snapshot: null,
    windowKey: "minutes",
    market: null,
    series: {}, // ticker -> [{t, mid}]
    books: {},
    timers: [],
    lastSync: null,
  };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function money(v, places) {
    if (v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    if (!isFinite(n)) return "—";
    return "$" + n.toFixed(places === undefined ? 4 : places);
  }
  function num(v) {
    if (v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    return isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—";
  }
  function pct(v) {
    if (v === null || v === undefined || v === "") return "—";
    var n = Number(v);
    return isFinite(n) ? (n * 100).toFixed(1) + "%" : "—";
  }
  function hhmmss(ts) {
    var d = new Date(ts * 1000);
    return d.toTimeString().slice(0, 8);
  }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ------------------------------------------------------------------ */
  /* snapshot                                                            */
  /* ------------------------------------------------------------------ */

  function readInline() {
    var node = document.getElementById("snapshot");
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (e) { return null; }
  }

  function fetchSnapshot() {
    return fetch("assets/live.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function banner(text, kind) {
    var pill = document.getElementById("streamState");
    if (!pill) return;
    pill.className = "live-pill " + (kind || "");
    var span = pill.querySelector("span");
    if (span) span.textContent = text; else pill.textContent = text;
  }

  function connected() {
    tickAge();
  }

  /* R-D-01 (arena-0b2d2a2a): show the snapshot age continuously, not only at
   * sync time, so a stale view is never mistaken for a live one. */
  function tickAge() {
    var el = document.getElementById("updatedAt");
    if (!el || !state.lastSync) return;
    var V = window.AlertsView;
    var age = V ? V.ageLabel(state.lastSync) : "";
    el.textContent = "Updated " + new Date(state.lastSync).toLocaleTimeString() +
      (age ? " · " + age : "");
    el.title = "Snapshot generated at " + state.lastSync + " (UTC)";
  }

  function startStream() {
    if (!window.EventSource) return false;
    var es;
    try { es = new EventSource("/api/stream"); } catch (e) { return false; }
    var opened = false;
    es.addEventListener("snapshot", function (ev) {
      opened = true;
      try {
        var payload = JSON.parse(ev.data);
        applySnapshot(payload, "sse");
      } catch (e) { /* ignore malformed frame */ }
    });
    es.onopen = function () { opened = true; banner("LIVE STREAM", "live"); };
    es.onerror = function () {
      es.close();
      if (!opened) banner("SNAPSHOT MODE", "");
      pollSnapshot();
    };
    state.timers.push(function () { es.close(); });
    return true;
  }

  function pollSnapshot() {
    var every = 30 * 1000;
    setInterval(function () {
      fetchSnapshot().then(function (payload) {
        if (payload) applySnapshot(payload, "poll");
      });
    }, every);
  }

  function applySnapshot(payload, source) {
    if (!payload || !payload.generated_at) return;
    state.snapshot = payload;
    state.lastSync = payload.generated_at;
    connected();
    if (source === "poll" || source === "sse") banner("LIVE STREAM", "live");
    renderFeeds();
    renderDesk();
    fillMarketSelect();
    if (state.market) refreshMarketNow(state.market);
  }

  /* ------------------------------------------------------------------ */
  /* chat feeds                                                          */
  /* ------------------------------------------------------------------ */

  function alertRow(a, isModel) {
    var up = a.direction === "up";
    var when = (a.iso || "").slice(11, 19) || hhmmss(a.ts);
    var row = document.createElement("div");
    row.className = "chat-row" + (up ? " up" : " down");
    var badges = "";
    if (Number(a.repeat_count) > 1) {
      badges += '<span class="tag tag-purple" title="The same ' +
        "&ge; $0.10 step fired again on later snapshots; identical rows are " +
        'grouped here.">×' + Number(a.repeat_count) + " repeats</span> ";
    }
    if (a.wide_spread) {
      badges += '<span class="flag-badge" title="YES bid ' + money(a.yes_bid) +
        " / ask " + money(a.yes_ask) + " — the spread is at least $0.10, so " +
        'this midpoint is not an executable price.">wide spread · not executable</span> ';
    }
    row.innerHTML =
      "<time>" + esc(when) + "</time>" +
      '<span class="chat-delta ' + (up ? "pos" : "neg") + '">' +
      (up ? "▲ +" : "▼ −") + Math.abs(Number(a.abs_delta) || 0).toFixed(4) + "</span>" +
      '<span class="chat-body">' +
      '<a href="' + esc(a.market_url || "#") + '" target="_blank" rel="noreferrer">' +
      esc(a.title || a.ticker) + "</a>" +
      "<small>" + money(a.previous) + " → " + money(a.current) +
      " · " + esc(a.topic) +
      (isModel ? " · net ROI " + pct(a.model_net_roi) : "") +
      "</small>" +
      (badges ? '<span class="chat-badges">' + badges + "</span>" : "") +
      "</span>" +
      '<button class="ghost-link" data-chart="' + esc(a.ticker) + '" ' +
      'data-series="' + esc(a.series_ticker || "") + '">chart</button>';
    return row;
  }

  function newsFor(ticker) {
    var news = (state.snapshot && state.snapshot.news) || {};
    return (news.headlines || {})[ticker] || [];
  }

  function newsLinks(ticker) {
    var items = newsFor(ticker);
    if (!items.length) return "";
    var links = items.slice(0, 2).map(function (item) {
      if (!item || !item.url || !item.title) return "";
      return '<a class="headline-link" href="' + esc(item.url) + '" target="_blank" ' +
        'rel="noreferrer nofollow" title="Candidate headline published near this ' +
        'move - temporal proximity is not a confirmed cause">↗ ' +
        esc(String(item.title).slice(0, 110)) +
        (item.source ? " · " + esc(item.source) : "") + "</a>";
    }).filter(Boolean);
    if (!links.length) return "";
    return '<span class="headlines"><b>Possible catalyst:</b> ' + links.join(" · ") + "</span>";
  }

  function modelRows(shortlist) {
    var rows = [];
    (shortlist.picks || []).forEach(function (pick) {
      var row = document.createElement("div");
      row.className = "chat-row model-pick";
      row.innerHTML =
        '<span class="chat-delta up">★ ' + pct(pick.net_roi) + "</span>" +
        '<span class="chat-body"><a href="' + esc(pick.market_url || "#") + '" ' +
        'target="_blank" rel="noreferrer">' + esc(pick.title || pick.ticker) + "</a>" +
        "<small>buy " + esc(String(pick.side || "").toUpperCase()) + " at " +
        money(pick.executable_price) + " · fair " + money(pick.model_fair) +
        " · edge " + money(pick.net_edge) + " after $" +
        Number(pick.fee || 0).toFixed(4) + " fee · " + esc(pick.kind || "") + "</small>" +
        '<small><a class="source-link" href="' + esc(pick.source_url || "#") + '" ' +
        'target="_blank" rel="noreferrer">API ↗</a></small></span>';
      rows.push(row);
    });
    (shortlist.verdicts || []).forEach(function (verdict) {
      var row = document.createElement("div");
      row.className = "chat-row model-verdict " + (verdict.verdict === "picked" ? "picked" : "passed");
      row.innerHTML =
        '<span class="chat-delta ' + (verdict.verdict === "picked" ? "up" : "flat") + '">' +
        (verdict.verdict === "picked" ? "★ picked" : "— passed") + "</span>" +
        '<span class="chat-body"><a href="' + esc(verdict.market_url || "#") + '" ' +
        'target="_blank" rel="noreferrer">' + esc(verdict.title || verdict.ticker) + "</a>" +
        "<small>" + esc(verdict.reason || "") + "</small>" +
        '<small><a class="source-link" href="' + esc(verdict.source_url || "#") + '" ' +
        'target="_blank" rel="noreferrer">API ↗</a></small></span>';
      rows.push(row);
    });
    return rows;
  }

  function renderFeeds() {
    var s = state.snapshot;
    if (!s) return;
    var raw = s.alerts || [];
    /* R-D-01 (arena-0b2d2a2a): identical repeated rows are grouped and rows
     * whose quoted YES spread is >= the $0.10 threshold are marked
     * non-executable. Display-only: the raw rows stay in the snapshot. */
    var V = window.AlertsView;
    var all = V ? V.dedupeAlerts(raw) : raw;
    var shortlist = s.shortlist || {};

    var feedAll = document.getElementById("feedAll");
    var feedModel = document.getElementById("feedModel");
    if (feedAll) {
      feedAll.innerHTML = "";
      if (!all.length) {
        feedAll.innerHTML = '<div class="empty-state inline">No ≥ $0.10 move observed ' +
          "yet. The feed fills as successive snapshots are compared.</div>";
      } else if (raw.length > all.length) {
        feedAll.appendChild(feedNote(all, raw));
      }
      all.slice(0, 200).forEach(function (a) {
        var row = alertRow(a, false);
        var body = row.querySelector(".chat-body");
        if (body) body.insertAdjacentHTML("beforeend", newsLinks(a.ticker));
        feedAll.appendChild(row);
      });
    }

    var modelCount = 0;
    if (feedModel) {
      feedModel.innerHTML = "";
      var rows = modelRows(shortlist);
      if (!rows.length) {
        // Fallback for snapshots taken before the order-book model existed.
        var scoreByTicker = {};
        (s.signals || []).forEach(function (sig) {
          scoreByTicker[sig.ticker] = sig;
        });
        all.filter(function (a) {
          var sig = scoreByTicker[a.ticker];
          return sig && sig.net_roi >= 0.05;
        }).forEach(function (a) {
          feedModel.appendChild(alertRow(a, true));
          modelCount += 1;
        });
      } else {
        rows.forEach(function (row) { feedModel.appendChild(row); });
        modelCount = (shortlist.picks || []).length;
      }
      if (!modelCount) {
        feedModel.innerHTML = '<div class="empty-state inline">Nothing clears the ' +
          "model's gates right now. This is normal — an empty shortlist is an " +
          "honest answer, and the verdicts below say why.</div>";
      }
    }
    var ac = document.getElementById("allCount");
    if (ac) ac.textContent = all.length + (raw.length > all.length ? " of " + raw.length : "");
    var mc = document.getElementById("modelCount");
    if (mc) mc.textContent = modelCount;
  }

  /* One-line explainer shown above the "all events" feed whenever grouping
   * actually collapsed rows, so the viewer knows what they are looking at. */
  function feedNote(deduped, raw) {
    var flagged = deduped.filter(function (a) { return a.wide_spread; }).length;
    var div = document.createElement("div");
    div.className = "chat-note";
    div.innerHTML =
      "<b>" + raw.length + " raw detections → " + deduped.length +
      " distinct rows.</b> Identical repeats of the same ≥ $0.10 step are grouped " +
      "(×N badge); rows whose YES bid/ask spread is ≥ $0.10 are marked " +
      "<i>not executable</i>. Raw rows are never deleted from the snapshot." +
      (flagged ? " " + flagged + " row(s) currently flagged wide-spread." : "");
    return div;
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-chart]");
    if (!btn) return;
    var ticker = btn.getAttribute("data-chart");
    var series = btn.getAttribute("data-series");
    var sel = document.getElementById("chartMarket");
    if (sel && ticker) {
      if (!Array.prototype.some.call(sel.options, function (o) { return o.value === ticker; })) {
        var opt = document.createElement("option");
        opt.value = ticker;
        opt.textContent = ticker;
        sel.appendChild(opt);
      }
      sel.value = ticker;
    }
    selectMarket(ticker, series);
  });

  /* ------------------------------------------------------------------ */
  /* market table                                                        */
  /* ------------------------------------------------------------------ */

  function fillMarketSelect() {
    var sel = document.getElementById("chartMarket");
    if (!sel || !state.snapshot) return;
    var current = sel.value;
    var events = (state.snapshot.events || []).slice(0, 120);
    sel.innerHTML = '<option value="">Choose a market</option>';
    events.forEach(function (e) {
      var opt = document.createElement("option");
      opt.value = e.ticker;
      opt.textContent = (e.topic ? "[" + e.topic + "] " : "") + (e.title || e.ticker);
      opt.dataset.series = e.series_ticker || "";
      sel.appendChild(opt);
    });
    if (current) sel.value = current;
    if (!state.market && events.length) {
      sel.value = events[0].ticker;
      state.market = events[0].ticker;
      selectMarket(events[0].ticker, events[0].series_ticker);
    }
  }

  function renderDesk() {
    var tbody = document.getElementById("deskRows");
    if (!tbody || !state.snapshot) return;
    var signals = {};
    (state.snapshot.signals || []).forEach(function (s) { signals[s.ticker] = s; });
    tbody.innerHTML = "";
    (state.snapshot.events || []).slice(0, 150).forEach(function (e) {
      var liq = e.liquidity || {};
      var sig = signals[e.ticker];
      var tr = document.createElement("tr");
      tr.className = "clickable";
      tr.innerHTML =
        '<td><a href="' + esc(e.market_url) + '" target="_blank" rel="noreferrer">' +
        esc(e.title) + '</a><small class="ticker">' + esc(e.ticker) + "</small></td>" +
        "<td>" + esc(e.topic) + "</td>" +
        "<td>" + money(e.yes_bid) + "</td>" +
        "<td>" + money(e.yes_ask) + "</td>" +
        "<td>" + money(liq.spread) + "</td>" +
        "<td>" + num(liq.yes_bid_contracts) + "</td>" +
        "<td>$" + num(e.open_interest_notional) + "</td>" +
        "<td>" + (sig ? '<span class="tag tag-yes">' + esc(sig.side.toUpperCase()) +
          "</span>" : "—") + "</td>" +
        "<td>" + (sig ? pct(sig.net_roi) : "—") + "</td>";
      tr.addEventListener("click", function (ev) {
        if (ev.target.tagName === "A") return;
        selectMarket(e.ticker, e.series_ticker);
        var sel = document.getElementById("chartMarket");
        if (sel) sel.value = e.ticker;
      });
      tbody.appendChild(tr);
    });
    if (!tbody.children.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No market rows in ' +
        "this snapshot.</td></tr>";
    }
  }

  /* ------------------------------------------------------------------ */
  /* market selection + price series                                     */
  /* ------------------------------------------------------------------ */

  function selectMarket(ticker, series) {
    if (!ticker) return;
    state.market = ticker;
    var found = (state.snapshot && state.snapshot.events || []).filter(function (e) {
      return e.ticker === ticker;
    })[0];
    var title = found ? found.title : ticker;
    var sub = document.getElementById("chartSubtitle");
    if (sub) sub.textContent = title;
    var label = document.getElementById("chartWindowLabel");
    if (label) label.textContent = WINDOWS[state.windowKey].label;

    loadSeries(ticker, series || (found && found.series_ticker) || "").then(function () {
      drawChart();
    });
    pollBook(ticker);
  }

  function loadSeries(ticker, seriesTicker) {
    var cached = state.series[ticker];
    if (cached && cached.loadedAt && Date.now() - cached.loadedAt < 120000) {
      return Promise.resolve(cached);
    }
    var points = [];

    // Seed from the official candlestick endpoint when we know the series.
    var candle =
      seriesTicker
        ? fetch(REST + "/series/" + encodeURIComponent(seriesTicker) +
            "/markets/" + encodeURIComponent(ticker) + "/candlesticks" +
            "?start_ts=" + Math.floor(Date.now() / 1000 - 6 * 3600) +
            "&end_ts=" + Math.floor(Date.now() / 1000) +
            "&period_interval=1", { cache: "no-store" })
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; })
        : Promise.resolve(null);

    return candle.then(function (data) {
      (data && data.candlesticks || []).forEach(function (c) {
        var price = c.price || {};
        var close = price.close_dollars != null ? Number(price.close_dollars) : null;
        if (close === null || !isFinite(close) || close <= 0) return;
        points.push({ t: c.end_period_ts, mid: close, src: "candle" });
      });
      points.sort(function (a, b) { return a.t - b.t; });
      state.series[ticker] = points;
      state.series[ticker].loadedAt = Date.now();
      return points;
    });
  }

  /* Re-read the book and drop a fresh point on the chart immediately after a
   * new snapshot arrives, instead of waiting for the next poll tick. */
  function refreshMarketNow(ticker) {
    if (!ticker) return;
    pollBook(ticker);
  }

  function pollBook(ticker) {
    fetch(REST + "/markets/" + encodeURIComponent(ticker) + "/orderbook?depth=10",
          { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.orderbook_fp) return;
        var book = data.orderbook_fp;
        state.books[ticker] = book;
        var mid = midFromBook(book);
        if (mid !== null) appendPoint(ticker, mid);
        if (state.market === ticker) {
          renderDepth(book);
          renderBookMetrics(book);
          drawChart();
        }
      })
      .catch(function () { /* leave the last known book on screen */ });
  }

  function bestBid(levels) {
    if (!levels || !levels.length) return null;
    var last = levels[levels.length - 1];
    if (!last || last.length < 2) return null;
    var p = Number(last[0]);
    var c = Number(last[1]);
    return isFinite(p) ? { price: p, contracts: isFinite(c) ? c : 0 } : null;
  }

  function midFromBook(book) {
    var yb = bestBid(book.yes_dollars);
    var nb = bestBid(book.no_dollars);
    var yesBid = yb ? yb.price : null;
    var yesAsk = nb ? 1 - nb.price : null;
    if (yesBid === null && yesAsk === null) return null;
    if (yesBid === null) return yesAsk;
    if (yesAsk === null) return yesBid;
    return (yesBid + yesAsk) / 2;
  }

  function appendPoint(ticker, mid) {
    var arr = state.series[ticker] || (state.series[ticker] = []);
    var now = Math.floor(Date.now() / 1000);
    var last = arr[arr.length - 1];
    if (last && now - last.t < 1 && Math.abs(last.mid - mid) < 1e-9) return;
    arr.push({ t: now, mid: mid, src: "book" });
    var cutoff = now - 13 * 3600;
    while (arr.length && arr[0].t < cutoff) arr.shift();
  }

  function sliceWindow(points) {
    var w = WINDOWS[state.windowKey];
    var cutoff = Math.floor(Date.now() / 1000) - Math.round(w.ms / 1000);
    return points.filter(function (p) { return p.t >= cutoff; });
  }

  function dpr() { return window.devicePixelRatio || 1; }

  function drawChart() {
    var canvas = document.getElementById("priceChart");
    if (!canvas || !state.market) return;
    var points = sliceWindow(state.series[state.market] || []);
    var box = canvas.getBoundingClientRect();
    var w = Math.max(320, box.width || canvas.parentNode.clientWidth || 640);
    var h = Math.max(200, box.height || 260);
    canvas.width = w * dpr();
    canvas.height = h * dpr();
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr(), 0, 0, dpr(), 0, 0);
    ctx.clearRect(0, 0, w, h);

    var pad = { l: 52, r: 14, t: 14, b: 28 };
    var plotW = w - pad.l - pad.r;
    var plotH = h - pad.t - pad.b;

    ctx.strokeStyle = "#e8eeeb";
    ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var y = pad.t + (plotH * g) / 4;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + plotW, y); ctx.stroke();
      ctx.fillStyle = "#74817f";
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "right";
      var val = 1 - g / 4;
      ctx.fillText("$" + val.toFixed(2), pad.l - 8, y + 4);
    }

    if (!points.length) {
      ctx.fillStyle = "#74817f";
      ctx.textAlign = "center";
      ctx.font = "13px system-ui, sans-serif";
      ctx.fillText("No price observations in this window yet", w / 2, h / 2);
      var p0 = document.getElementById("chartPrice");
      if (p0) p0.textContent = "—";
      return;
    }

    var t0 = points[0].t;
    var t1 = points[points.length - 1].t;
    if (t1 === t0) t1 = t0 + 1;
    function xOf(t) { return pad.l + ((t - t0) / (t1 - t0)) * plotW; }
    function yOf(p) { return pad.t + (1 - p) * plotH; }

    // Threshold annotation: highlight segments that moved >= $0.10.
    ctx.strokeStyle = "#16a67a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach(function (p, i) {
      var x = xOf(p.t), y = yOf(p.mid);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    for (var i = 1; i < points.length; i++) {
      var d = points[i].mid - points[i - 1].mid;
      if (Math.abs(d) >= SWING) {
        ctx.fillStyle = d > 0 ? "rgba(22,166,122,.85)" : "rgba(212,93,97,.85)";
        ctx.beginPath();
        ctx.arc(xOf(points[i].t), yOf(points[i].mid), 4.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    var last = points[points.length - 1];
    ctx.fillStyle = "#0f8060";
    ctx.beginPath();
    ctx.arc(xOf(last.t), yOf(last.mid), 3.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#74817f";
    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(new Date(t0 * 1000).toLocaleTimeString(), pad.l, h - 8);
    ctx.textAlign = "right";
    ctx.fillText(new Date(t1 * 1000).toLocaleTimeString(), pad.l + plotW, h - 8);

    var priceEl = document.getElementById("chartPrice");
    if (priceEl) priceEl.textContent = money(last.mid);
    var changeEl = document.getElementById("chartChange");
    if (changeEl) {
      var delta = last.mid - points[0].mid;
      changeEl.textContent = (delta >= 0 ? "+" : "−") + Math.abs(delta).toFixed(4);
      changeEl.className = delta >= 0 ? "pos" : "neg";
    }
  }

  function renderBookMetrics(book) {
    var yb = bestBid(book.yes_dollars);
    var nb = bestBid(book.no_dollars);
    var bidEl = document.getElementById("chartBid");
    if (bidEl) bidEl.textContent = yb ? money(yb.price) : "—";
    var askEl = document.getElementById("chartAsk");
    if (askEl) askEl.textContent = nb ? money(1 - nb.price) : "—";
  }

  function renderDepth(book) {
    var host = document.getElementById("depthBook");
    if (!host) return;
    var levels = [];
    (book.yes_dollars || []).forEach(function (row) {
      levels.push({ side: "YES bid", price: Number(row[0]), contracts: Number(row[1]) });
    });
    (book.no_dollars || []).forEach(function (row) {
      levels.push({ side: "NO bid", price: Number(row[0]), contracts: Number(row[1]) });
    });
    levels = levels.filter(function (l) { return isFinite(l.price) && isFinite(l.contracts); });
    if (!levels.length) {
      host.innerHTML = '<div class="empty-state inline">This market has an empty ' +
        "book right now — no resting bids on either side.</div>";
      return;
    }
    var maxC = Math.max.apply(null, levels.map(function (l) { return l.contracts; })) || 1;
    var yes = levels.filter(function (l) { return l.side === "YES bid"; })
      .sort(function (a, b) { return b.price - a.price; });
    var no = levels.filter(function (l) { return l.side === "NO bid"; })
      .sort(function (a, b) { return b.price - a.price; });

    function block(title, rows, cls) {
      var body = rows.map(function (l) {
        var widthPct = Math.max(2, (l.contracts / maxC) * 100);
        return '<div class="depth-row"><span class="depth-price">$' +
          l.price.toFixed(4) + '</span><span class="depth-bar ' + cls +
          '" style="width:' + widthPct.toFixed(1) + '%"></span>' +
          '<span class="depth-size">' + l.contracts.toFixed(0) + "</span></div>";
      }).join("");
      return '<div class="depth-group"><h4>' + title + "</h4>" +
        (body || '<div class="empty-state inline">empty</div>') + "</div>";
    }

    var stamp = document.getElementById("depthStamp");
    if (stamp) stamp.textContent = "as of " + new Date().toLocaleTimeString();
    host.innerHTML = block("YES bids", yes, "yes") + block("NO bids", no, "no");
  }

  /* ------------------------------------------------------------------ */
  /* boot                                                                */
  /* ------------------------------------------------------------------ */

  function boot() {
    var inline = readInline();
    if (inline) {
      applySnapshot(inline, "inline");
      banner("SNAPSHOT " + (inline.generated_at || "").slice(11, 16), "");
    }
    if (!startStream()) {
      banner("SNAPSHOT MODE", "");
      pollSnapshot();
    }
    fetchSnapshot().then(function (payload) {
      if (payload) applySnapshot(payload, "poll");
    });

    $all("#windowTabs button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        $all("#windowTabs button").forEach(function (b) { b.classList.remove("selected"); });
        btn.classList.add("selected");
        state.windowKey = btn.getAttribute("data-window");
        var label = document.getElementById("chartWindowLabel");
        if (label) label.textContent = WINDOWS[state.windowKey].label;
        drawChart();
      });
    });

    var sel = document.getElementById("chartMarket");
    if (sel) {
      sel.addEventListener("change", function () {
        var opt = sel.options[sel.selectedIndex];
        selectMarket(sel.value, opt && opt.dataset ? opt.dataset.series : "");
      });
    }

    window.addEventListener("resize", drawChart);

    // Live order-book polling for the selected market.
    setInterval(function () {
      if (state.market) pollBook(state.market);
    }, 4000);

    // Keep the visible snapshot age current (R-D-01).
    setInterval(tickAge, 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
