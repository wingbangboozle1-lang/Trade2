/* Browser live layer (task T31, session arena-5bec0ea3 — see COORDINATION.md).
   Modes, chosen by *verified* facts only (docs/data/capabilities.json, written
   by tools/live_probe.py on a GitHub runner, plus a runtime self-check):

     "ws"       — anonymous WebSocket accepted (ticker channel per
                  https://docs.kalshi.com/getting_started/quick_start_websockets).
                  Expected OFF: the official docs require KALSHI-ACCESS-*
                  handshake headers, which browsers cannot send.
     "rest"     — direct polling of the demo REST API from this page
                  (self-checked at runtime; the probe records the CORS headers).
     "snapshot" — no direct reachability: fall back to the published
                  docs/data/*.json snapshot (existing app.js behaviour) and
                  SAY SO in the freshness badge. Never pretend to be live.

   Everything visible flows through window.__desk (app.js), so every row keeps
   its official source link and any unconfirmed value stays blank + flagged.
   Swing rule: |mid - baseline| >= $0.10 -> one alert, then the baseline resets
   (a sustained move does not re-alert every poll — R-D-01 dedup). Alert rows
   carry no news link unless one is verified; the empty link is shown as such. */
(function () {
  "use strict";
  var REST = "https://external-api.demo.kalshi.co/trade-api/v2";
  var WS_URL = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2";
  var POLL_MS = 15000;          // polite: ~14 requests per poll, one poll per 15 s
  var SWING = 0.10;             // official requirement: >= $0.10 either direction
  var MAX_LIVE_MARKETS = 12;    // highest-$ tracked markets on this page
  var TICK_KEEP = 240;          // ~60 min of ticks at 15 s
  var MARKET_URL = function (t) {
    return REST + "/markets/" + encodeURIComponent(t);
  };

  var mode = "snapshot";
  var caps = null;
  var lastRaws = [];            // for __deskLiveMerge (re-apply after snapshot loads)
  var refMid = {};              // swing baselines per ticker
  var lastMid = {};
  var ticks = {};               // ticker -> [{t, y}] session tick series
  var roiParams = { rev: 0.30, min: 0.02 };   // fallbacks mirror app.js defaults
  var lastPollAt = null;
  var pollTimer = null;

  function jget(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) return null;
      return r.json();
    }).catch(function () { return null; });
  }
  function nowSec() { return Date.now() / 1000; }
  function clock(t) {
    return new Date(t * 1000).toISOString().slice(11, 19) + "Z";
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* --------------------------------------------------- runtime self-check */
  function selfCheckRest() {
    // A failed cross-origin fetch is the definitive CORS verdict in a browser.
    return jget(REST + "/markets?limit=1").then(function (data) {
      return !!(data && (data.markets || data.market));
    });
  }

  /* ------------------------------------------------------------- badge */
  function setBadge(extra) {
    var d = window.__desk;
    if (!d) return;
    var t = lastPollAt ? clock(lastPollAt) : "";
    if (mode === "ws") {
      d.S.liveLabel = '<span class="badge ok">WS LIVE</span> anonymous ticker stream · ' +
        'verified protocol <a href="https://docs.kalshi.com/getting_started/quick_start_websockets" target="_blank" rel="noopener">docs ↗</a> · ' + esc(t);
    } else if (mode === "rest") {
      d.S.liveLabel = '<span class="badge ok">LIVE</span> direct demo API · ' +
        'poll ' + (POLL_MS / 1000) + 's · ' + esc(t) +
        (extra ? " · " + esc(extra) : "") +
        ' · <a href="data/capabilities.json" target="_blank" rel="noopener">probe</a>';
    } else {
      var g = (d.S.meta && (d.S.meta.finished_at || d.S.meta.generated_at)) || "";
      d.S.liveLabel = '<span class="badge unv">SNAPSHOT</span> published data' +
        (g ? " · " + esc(String(g).replace("T", " ").slice(0, 19)) + "Z" : "") +
        (extra ? " · " + esc(extra) : "") +
        ' · <a href="flagged.html">why?</a>';
    }
    d.render();
  }

  /* ----------------------------------------------- swing alerts + ticks */
  function midOf(raw) {
    var bid = parseFloat(raw.yes_bid_dollars), ask = parseFloat(raw.yes_ask_dollars);
    var last = parseFloat(raw.last_price_dollars);
    if (!isNaN(bid) && !isNaN(ask)) return (bid + ask) / 2;
    if (!isNaN(last)) return last;
    return null;
  }

  function observe(ticker, raw, topic, title) {
    var d = window.__desk;
    var mid = midOf(raw);
    if (mid == null) return;
    var t = nowSec();
    (ticks[ticker] = ticks[ticker] || []).push({ t: Math.floor(t), y: mid });
    while (ticks[ticker].length > TICK_KEEP) ticks[ticker].shift();
    d.S.liveTicks = ticks;

    if (refMid[ticker] == null) {
      refMid[ticker] = mid;
      lastMid[ticker] = mid;
      return;
    }
    var delta = Math.round((mid - refMid[ticker]) * 10000) / 10000;
    if (Math.abs(delta) >= SWING) {
      var ok = d.pushLiveAlert({
        t: Math.floor(t),
        t_iso: new Date(t * 1000).toISOString(),
        delta: delta,
        ticker: ticker,
        title: title || "",
        topic: topic || "",
        from: Math.round(refMid[ticker] * 10000) / 10000,
        to: Math.round(mid * 10000) / 10000,
        window: "live poll vs baseline (reset after alert)",
        headlines: [],           // no verified headline -> app.js shows the blank flag
        source_url: MARKET_URL(ticker),
        candle_source_url: REST + "/series/" + esc(ticker.split("-")[0]) +
          "/markets/" + encodeURIComponent(ticker) + "/candlesticks?period_interval=1",
        flags: [],
      });
      if (ok) refMid[ticker] = mid;   // reset baseline: no repeated alerts (R-D-01)
    }
    lastMid[ticker] = mid;
  }

  /* --------------------------------------------------------- REST poll */
  function pickTickers() {
    var d = window.__desk;
    var list = (d && d.S.markets) || [];
    return list.filter(function (m) { return m && m.ticker; })
      .slice().sort(function (a, b) {
        return (b.notional_usd || 0) - (a.notional_usd || 0);
      })
      .slice(0, MAX_LIVE_MARKETS);
  }

  function pollOnce() {
    var d = window.__desk;
    if (!d || mode !== "rest") return;
    var picks = pickTickers();
    if (!picks.length) return;
    var reqs = picks.map(function (m) {
      return jget(MARKET_URL(m.ticker)).then(function (data) {
        var raw = data && (data.market || data);
        return raw && raw.ticker ? { raw: raw, meta: m } : null;
      });
    });
    Promise.all(reqs).then(function (results) {
      var raws = [];
      results.forEach(function (r) {
        if (!r) return;
        raws.push(r.raw);
        observe(r.raw.ticker, r.raw, r.meta.topic, r.raw.title || r.meta.title);
      });
      lastRaws = raws;
      if (raws.length) {
        d.ingest({ markets: raws, books: {}, fetched_at: nowSec() });
      }
      // 1-minute candles for the charted market (official minimum period):
      var sel = document.querySelector("#pick-market");
      if (sel && sel.value) {
        var start = Math.floor(nowSec()) - 6 * 3600;
        jget(REST + "/series/" + sel.value.split("-")[0] + "/markets/" +
          encodeURIComponent(sel.value) +
          "/candlesticks?start_ts=" + start + "&period_interval=1").then(function (c) {
          if (!c || !c.candlesticks) return;
          var pts = c.candlesticks.map(function (k) {
            return { t: k.end_period_ts, close: k.close };
          }).filter(function (p) { return p.close != null; });
          if (pts.length > 1) {
            (d.S.candles[sel.value] = d.S.candles[sel.value] || {}).live_1min = {
              points: pts, interval: 1,
              source_url: REST + "/series/" + sel.value.split("-")[0] + "/markets/" +
                encodeURIComponent(sel.value) + "/candlesticks?period_interval=1",
            };
            d.redrawChart();
          }
        });
        // order book for the charted market every other poll (liquidity ladder)
        if ((lastPollAt == null || Date.now() - lastPollAt > POLL_MS * 2)) {
          jget(MARKET_URL(sel.value) + "/orderbook").then(function (ob) {
            if (!ob) return;
            ob.__ticker = sel.value;
            d.S.books[sel.value] = d.parseBook(ob);
            d.redrawChart();
          });
        }
      }
      lastPollAt = Date.now();
      setBadge(raws.length + "/" + picks.length + " markets");
      d.flashDot();
    });
  }

  /* ------------------------------------------------- optional WS stream */
  function startWs() {
    // Envelope exactly as the official quick start documents it.
    var ws;
    try { ws = new WebSocket(WS_URL); } catch (e) { return; }
    ws.onopen = function () {
      mode = "ws";
      setBadge();
      try {
        ws.send(JSON.stringify({
          id: 1, cmd: "subscribe",
          params: { channels: ["ticker"],
                    market_tickers: pickTickers().map(function (m) { return m.ticker; }) },
        }));
      } catch (e) { /* keep connection even if subscribe frame fails */ }
    };
    ws.onmessage = function (ev) {
      var d = window.__desk;
      if (!d) return;
      try {
        var msg = JSON.parse(ev.data);
        if (msg.type === "ticker" && msg.msg && msg.msg.market_ticker) {
          var raw = msg.msg;
          var meta = (d.S.markets || []).filter(function (m) {
            return m.ticker === raw.market_ticker; })[0] || {};
          observe(raw.market_ticker, raw, meta.topic, meta.title);
          lastRaws = [raw];
          d.ingest({ markets: [raw], books: {}, fetched_at: nowSec() });
          lastPollAt = Date.now();
          setBadge("ticker stream");
          d.flashDot();
        }
      } catch (e) { /* ignore partial frames, per docs */ }
    };
    ws.onerror = function () { /* onclose handles fallback */ };
    ws.onclose = function () {
      if (mode === "ws") {
        mode = "rest";              // degrade to REST, never to a false "live"
        setBadge("ws closed — REST fallback");
        if (!pollTimer) pollTimer = setInterval(pollOnce, POLL_MS);
      }
    };
  }

  /* -------------------------------------------------------- merge hook */
  window.__deskLiveMerge = function () {
    var d = window.__desk;
    if (d && lastRaws.length && (mode === "rest" || mode === "ws")) {
      d.ingest({ markets: lastRaws, books: {}, fetched_at: nowSec() });
    }
  };
  // Test / debug hook (tests/test_docs_live.mjs drives one poll directly).
  window.__deskLivePoll = function () { pollOnce(); };
  window.__deskLiveState = function () {
    return { mode: mode, lastPollAt: lastPollAt, refMid: refMid, lastMid: lastMid };
  };

  /* ------------------------------------------------------------- boot */
  function boot() {
    if (!window.__desk) { setTimeout(boot, 50); return; }
    var d = window.__desk;
    jget("data/portfolio.json").then(function (p) {
      if (p && p.parameters) {
        if (p.parameters.reversion_share != null) roiParams.rev = p.parameters.reversion_share;
        if (p.parameters.roi_min != null) roiParams.min = p.parameters.roi_min;
      }
      return jget("data/capabilities.json");
    }).then(function (c) {
      caps = c;
      var wsOk = !!(c && c.probes && c.probes.ws_anonymous_handshake &&
                    c.probes.ws_anonymous_handshake.anonymous_handshake_accepted);
      return selfCheckRest().then(function (restOk) {
        if (wsOk) {
          startWs();               // sets mode = "ws" on open
          mode = "rest";           // poll until the socket opens
          pollTimer = setInterval(pollOnce, POLL_MS);
          pollOnce();
          setBadge("ws probe: accepted");
        } else if (restOk) {
          mode = "rest";
          pollTimer = setInterval(pollOnce, POLL_MS);
          pollOnce();
          setBadge();
        } else {
          mode = "snapshot";
          var why = (c && c.probes && c.probes.rest_cors && !c.probes.rest_cors.browser_usable)
            ? "probe: CORS blocked for Pages origin"
            : "runtime check: demo API unreachable from this page";
          setBadge(why);
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
