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
    side: "yes",        // which contract is charted; NO = 1 - YES, same book
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

  /* Third-party URLs (a news headline link comes from outside Kalshi) must not
   * reach an href as javascript: or data:. The generator applies the same rule
   * in site_build/format.py:safe_url, so both renderers agree. */
  function safeUrl(value) {
    var text = String(value === null || value === undefined ? "" : value).trim();
    return /^https?:\/\//i.test(text) ? esc(text) : "";
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
   * sync time, so a stale view is never mistaken for a live one.
   *
   * The age is rendered server-side into the #snapshotAge badge so it is
   * correct with JavaScript disabled; this only keeps it ticking. The
   * wording comes from AlertsView.ageLabel, the shared helper module, so
   * there is one implementation and one unit-tested format. */
  function tickAge() {
    var el = document.getElementById("updatedAt");
    if (el && state.lastSync) {
      el.textContent = "Updated " + new Date(state.lastSync).toLocaleTimeString();
      el.title = "Snapshot generated at " + state.lastSync + " (UTC)";
    }
    var badge = document.getElementById("snapshotAge");
    if (!badge) return;
    var ts = parseFloat(badge.getAttribute("data-generated-ts") || "");
    if (!isFinite(ts) || ts <= 0) {
      if (!state.lastSync) return;
      ts = new Date(state.lastSync).getTime() / 1000;
    }
    var seconds = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    var V = window.AlertsView;
    badge.textContent = V
      ? V.ageLabel(new Date(ts * 1000).toISOString())
      : (seconds < 90 ? seconds + "s old"
                      : Math.floor(seconds / 60) + "m old");
    badge.className = "snap-age" + (seconds < 900 ? " fresh" : "");
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
    tickAge();
    if (source === "poll" || source === "sse") banner("LIVE STREAM", "live");
    renderFeeds();
    renderDesk();
    fillMarketSelect();
    if (state.market) {
      renderChartNotes();
      refreshMarketNow(state.market);
    }
  }

  /* The API root the snapshot was collected from, so a per-row source link
   * points at the same demo environment the numbers came from. Falls back to
   * the documented demo host when the snapshot does not carry one. */
  var API_ROOT_FALLBACK = "https://external-api.demo.kalshi.co/trade-api/v2";
  function apiRoot() {
    var root = state.snapshot && state.snapshot.api_root;
    return (typeof root === "string" && root) ? root.replace(/\/+$/, "") : API_ROOT_FALLBACK;
  }

  /* ------------------------------------------------------------------ */
  /* chat feeds                                                          */
  /* ------------------------------------------------------------------ */

  /* Kalshi's public event page carries Kalshi's own live news feed for that
   * event, so it is the first place to look for something that may have
   * moved the price. The second link is a news search built from the event
   * title. Neither asserts a cause. */
  function eventUrl(a) {
    var series = a.series_ticker ||
      String(a.event_ticker || "").split("-")[0] || "";
    return "https://kalshi.com/markets/" + encodeURIComponent(series) + "/" +
      encodeURIComponent(a.event_ticker || "");
  }

  function newsUrl(a) {
    var label = String(a.topic || "").replace(/-/g, " ");
    var q = (a.title || a.ticker || "") + " " + label + " Kalshi";
    return "https://news.google.com/rss/search?q=" + encodeURIComponent(q) +
      "&hl=en-US&gl=US&ceid=US:en";
  }

  function alertRow(a, isModel) {
    var up = a.direction === "up";
    var when = (a.iso || "").slice(11, 19) || hhmmss(a.ts);
    var basis = a.basis || "mid";
    var badge = "";
    if (a.thin_book || (basis && basis !== "mid")) {
      var label = basis === "quote" ? "one-sided book" : "thin book";
      badge = '<span class="tag tag-warn" title="Move measured on ' + label +
        " basis — the midpoint of a wide spread is not an executable price. " +
        'See Methodology.">' + label + "</span>";
    }
    var q = encodeURIComponent(a.title || a.ticker || "");
    var context = '<a class="source-link" target="_blank" rel="noreferrer" ' +
      'href="https://news.google.com/search?q=' + q + '" title="Research link ' +
      '— possible context only; causality unverified">context ↗</a>';
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
    /* The collector stamps a verdict on every row it writes; a row without one
     * predates the rule and says so instead of being assumed executable. */
    if (a.quality === "executable") {
      badges += '<span class="tag tag-yes" title="Both sides quoted, and the YES ' +
        "spread is tighter than the $0.10 threshold, so the midpoint sits inside " +
        'a range a trader could transact in.">executable</span> ';
    } else if (a.quality === "indicative") {
      badges += '<span class="flag-badge" title="' + esc(a.quality_reason || "") +
        '">indicative · not executable</span> ';
    } else if (a.quality === undefined || a.quality === null) {
      badges += '<span class="tag tag-grey" title="Written before the collector ' +
        "stated a price basis per row; no executability claim is made either " +
        'way.">pre-rule row</span> ';
    }
    /* What the two subtracted numbers are, and whether anything was resting at
     * the level when the move printed. */
    var extra = a.reference_basis ? " · " + esc(a.reference_basis) : "";
    if (a.spread !== null && a.spread !== undefined) {
      extra += " · YES spread " + money(a.spread, 4) +
        (a.size_at_top !== null && a.size_at_top !== undefined
          ? " · " + num(a.size_at_top) + " contracts at the level"
          : " · no resting size at the level");
    }
    /* Headlines the collector found within six hours either side of the move:
     * candidates, never a claimed cause. */
    var heads = [], newsList = a.news || [];
    for (var hi = 0; hi < newsList.length && hi < 2; hi++) {
      var href = safeUrl(newsList[hi].url);
      var label = String(newsList[hi].title || "").trim();
      if (href && label) {
        heads.push('<a href="' + href + '" target="_blank" rel="noreferrer noopener">' +
          esc(label) + " ↗</a>");
      }
    }
    var newsWhy = String(a.news_status || "no news lookup recorded for this row");
    var newsHtml = heads.length
      ? '<span class="cause-links"><span class="cause-label">candidate headline, ' +
        'not confirmed:</span>' + heads.join(" ") + "</span>"
      : '<span class="cause-links"><span class="cause-none" title="' + esc(newsWhy) +
        '">no verified news link · ' + esc(newsWhy) + "</span></span>";
    row.innerHTML =
      "<time>" + esc(when) + "</time>" +
      '<span class="chat-delta ' + (up ? "pos" : "neg") + '">' +
      (up ? "▲ +" : "▼ −") + Math.abs(Number(a.abs_delta) || 0).toFixed(4) + "</span>" +
      '<span class="chat-body">' +
      '<a href="' + (safeUrl(a.market_url) || "#") + '" target="_blank" rel="noreferrer">' +
      esc(a.title || a.ticker) + "</a>" +
      "<small>" + money(a.previous) + " → " + money(a.current) +
      " · " + esc(a.topic) +
      (isModel ? " · net ROI " + pct(a.model_net_roi) : "") +
      extra + "</small>" +
      (badges ? '<span class="chat-badges">' + badges + "</span>" : "") +
      newsHtml +
      '<span class="cause-links">' +
      '<a href="' + esc(eventUrl(a)) + '" target="_blank" rel="noreferrer">Event page ↗</a>' +
      '<a href="' + esc(newsUrl(a)) + '" target="_blank" rel="noreferrer">News search ↗</a>' +
      "</span>" +
      "</span>" +
      '<button class="ghost-link" data-chart="' + esc(a.ticker) + '" ' +
      'data-series="' + esc(a.series_ticker || "") + '">chart</button>';
    return row;
  }

  /* A model signal rendered as a chat row. The shortlist shows these when no
   * >= $0.10 swing matches the signal: a swing usually leaves little modelled
   * edge behind it, so intersecting the two feeds made the shortlist
   * structurally empty. Mirrors the signal-picks fallback in
   * site_build.build_overview. */
  function signalRow(sig, seriesByTicker) {
    var row = document.createElement("div");
    row.className = "chat-row up";
    row.innerHTML =
      "<time>" + esc(hhmmss(sig.ts)) + "</time>" +
      '<span class="chat-delta pos">★ ' + pct(sig.net_roi) + "</span>" +
      '<span class="chat-body">' +
      '<a href="' + esc(sig.market_url || "#") + '" target="_blank" rel="noreferrer">' +
      esc(sig.title || sig.ticker) + "</a>" +
      "<small>" + esc(String(sig.side || "").toUpperCase()) + " at " +
      money(sig.executable_price) + " · " + esc(sig.topic) +
      " · no ≥ $0.10 swing yet</small></span>" +
      '<button class="ghost-link" data-chart="' + esc(sig.ticker) + '" ' +
      'data-series="' + esc((seriesByTicker || {})[sig.ticker] || "") +
      '">chart</button>';
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

  /* What an empty "All events" chat actually means.
   *
   * An empty chat is the honest answer only when it also says what was measured.
   * Before session arena-27de8294 it said nothing had been observed yet, which
   * a trader reads as "nothing happened" — even though 652 of the 750 tracked
   * markets had no candle reference in that snapshot and the previous-snapshot
   * fallback was silently dead (see tests/test_snapshot_fallback_27de.py).
   * The panel now states the measured row count, the candle-reference count and
   * how many earlier rows the comparison could use. Every number comes from the
   * snapshot; nothing is inferred.
   */
  function emptyAllFeedHtml(s) {
    var refusedN = (s.suppressed_alerts || []).length;
    var fb = s.snapshot_fallback || {};
    var measured = fb.measured_rows != null ? fb.measured_rows : s.observation_count;
    var candle = fb.candle_reference_rows;
    var prior = fb.previous_rows;
    var bits = [];
    if (measured != null) bits.push(num(measured) + " markets measured this snapshot");
    if (candle != null) bits.push(num(candle) + " had an official 1-minute candle reference");
    if (prior != null) {
      bits.push(prior
        ? num(prior) + " earlier rows available for the previous-snapshot fallback"
        : "no earlier rows yet, so the previous-snapshot fallback had nothing to compare");
    }
    var tail = refusedN
      ? refusedN + " midpoint move" + (refusedN === 1 ? "" : "s") +
        " cleared $0.10 but the quote rule refused " + (refusedN === 1 ? "it" : "them") +
        ' — each with its reason on <a href="review.html#refused">Flagged for review</a>.'
      : "No row cleared $0.10 on a two-sided book in this snapshot.";
    return '<div class="empty-state inline"><b>No alert row in this snapshot.</b> ' +
      tail + (bits.length ? " <span class=\"empty-basis\">Measured: " +
        bits.join(" · ") + ". Every row is quote mid to quote mid against one of two " +
        "bases — <code>candle_quote_mid</code> when Kalshi published a candle, " +
        "<code>previous_snapshot_mid</code> otherwise.</span>" : "") + "</div>";
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
    /* Order-book model side-car (picks + verdicts per alerted market). */
    var shortlist = s.shortlist || {};

    /* Model shortlist: the collector publishes it through one gate
     * (high_roi_alerts, >= MODEL_MIN_NET_ROI and executable), so the polled
     * view and the pre-rendered view cannot disagree about which rows belong
     * in it. The first fallback exists for snapshots written before that
     * field shipped and reads the published threshold rather than inventing
     * a second one; when no swing matches a signal at all — the common case,
     * since a swing usually leaves little modelled edge behind it — the
     * chat shows the model's current top signals, exactly like the
     * server-rendered chat in build_overview. */
    var model = s.high_roi_alerts;
    if (!Array.isArray(model) || !model.length) {
      var gate = (s.model_gate && s.model_gate.min_net_roi != null)
        ? Number(s.model_gate.min_net_roi) : 0.05;
      var scoreByTicker = {};
      (s.signals || []).forEach(function (sig) {
        if (sig && sig.net_roi !== null && sig.net_roi !== undefined &&
            Number(sig.net_roi) >= gate) scoreByTicker[sig.ticker] = sig;
      });
      var rawModel = raw
        .filter(function (a) { return !!scoreByTicker[a.ticker]; })
        .map(function (a) {
          var out = Object.assign({}, a);
          out.model_net_roi = scoreByTicker[a.ticker].net_roi;
          return out;
        });
      model = rawModel;
    }
    if (V) model = V.dedupeAlerts(model);
    var signalRows = model.length
      ? []
      : (s.signals || []).filter(Boolean).slice(0, 8);
    var seriesByTicker = {};
    (s.events || []).forEach(function (e) {
      if (e && e.ticker && e.series_ticker) seriesByTicker[e.ticker] = e.series_ticker;
    });

    var feedAll = document.getElementById("feedAll");
    var feedModel = document.getElementById("feedModel");
    if (feedAll) {
      feedAll.innerHTML = "";
      if (!all.length) {
        feedAll.innerHTML = emptyAllFeedHtml(s);
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
      /* Order-book model rows first (picks + a verdict for every alert), then
       * any high-ROI alert row on a market the book model did not price, so
       * the two model views never show the same ticker twice. When the model
       * priced nothing and no alert clears the high-ROI gate, the merged
       * fallback from the pre-shortlist contract still renders the current
       * top signals as chat rows (pinned by tests/test_chat_rows.py and
       * test/desk_render_dc732aa6.mjs). */
      var rows = modelRows(shortlist);
      var covered = {};
      (shortlist.picks || []).forEach(function (p) { covered[p.ticker] = 1; });
      (shortlist.verdicts || []).forEach(function (v) { covered[v.ticker] = 1; });
      var extra = (model || []).filter(function (a) { return !covered[a.ticker]; });
      if (rows.length || extra.length) {
        rows.forEach(function (row) { feedModel.appendChild(row); });
        extra.slice(0, 200).forEach(function (a) {
          feedModel.appendChild(alertRow(a, true));
        });
        modelCount = rows.length + extra.length;
      } else if (signalRows.length) {
        signalRows.slice(0, 200).forEach(function (sig) {
          feedModel.appendChild(signalRow(sig, seriesByTicker));
        });
        modelCount = signalRows.length;
      } else {
        feedModel.innerHTML = '<div class="empty-state inline">Nothing clears the ' +
          "model's gates right now. This is normal — an empty shortlist is an " +
          "honest answer, and the verdicts say why.</div>";
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
        '<td><a href="' + (safeUrl(e.market_url) || "#") + '" target="_blank" rel="noreferrer">' +
        esc(e.title) + '</a><small class="ticker">' + esc(e.ticker) + "</small></td>" +
        "<td>" + esc(e.topic) + "</td>" +
        "<td>" + money(e.yes_bid) + "</td>" +
        "<td>" + money(e.yes_ask) + "</td>" +
        "<td>" + money(liq.spread) + "</td>" +
        "<td>" + num(liq.yes_bid_contracts) + "</td>" +
        "<td>$" + num(e.open_interest_notional) + "</td>" +
        "<td>" + (sig ? '<span class="tag tag-yes">' + esc(sig.side.toUpperCase()) +
          "</span>" : "—") + "</td>" +
        "<td>" + (sig ? pct(sig.net_roi) : "—") + "</td>" +
        '<td><a class="source-link" target="_blank" rel="noreferrer" href="' +
        esc(apiRoot() + "/markets/" + e.ticker) + '">API &#8597;</a></td>';
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

    renderChartNotes();
    loadSeries(ticker, series || (found && found.series_ticker) || "").then(function () {
      drawChart();
    });
    pollBook(ticker);
  }

  /* Swing annotations under the chart: every >= $0.10 move observed on the
   * selected market, with the market link and a clearly labelled research
   * link. Cause is never asserted (R-D-01 / suggestions rows 1 and 4). */
  function renderChartNotes() {
    var el = document.getElementById("chartNotes");
    if (!el) return;
    var t = state.market;
    var V = window.AlertsView;
    var raw = (state.snapshot && state.snapshot.alerts) || [];
    var rows = (V ? V.dedupeAlerts(raw) : raw)
      .filter(function (a) { return a.ticker === t; });
    if (!rows.length) {
      el.innerHTML = '<span class="muted">No ≥ $0.10 swing recorded for this ' +
        "market in the snapshot. The chart still plots every observation.</span>";
      return;
    }
    el.innerHTML = '<b>Jump annotations</b> — swings ≥ $0.10 on this market' +
      rows.map(function (a) {
        var q = encodeURIComponent(a.title || a.ticker || "");
        return '<div class="chart-note-row"><time>' +
          esc((a.iso || "").slice(11, 19) || hhmmss(a.ts)) + "</time>" +
          '<span class="chat-delta ' + (a.direction === "up" ? "pos" : "neg") + '">' +
          (a.direction === "up" ? "▲ +" : "▼ −") +
          Math.abs(Number(a.abs_delta) || 0).toFixed(4) + "</span>" +
          '<a href="' + esc(a.market_url || "#") + '" target="_blank" ' +
          'rel="noreferrer">event ↗</a>' +
          '<a class="source-link" target="_blank" rel="noreferrer" href="https://news.google.com/search?q=' +
          q + '" title="Research link — possible context only; causality ' +
          'unverified">context ↗</a></div>';
      }).join("");
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

    /* The NO contract is the other side of the same binary market. Its price
     * is 1 - YES for any two-sided quote: buying NO at (1 - YES bid) and
     * selling NO at (1 - YES ask) is the identical order read from the other
     * side of the book, so no new data is invented — every NO value is derived
     * from a YES value Kalshi published, and the axis says so. */
    if (state.side === "no") points = points.map(function (p) {
      return { t: p.t, mid: 1 - p.mid, src: p.src };
    });

    var box = canvas.getBoundingClientRect();
    var w = Math.max(320, box.width || canvas.parentNode.clientWidth || 640);
    var h = Math.max(200, box.height || 260);
    canvas.width = w * dpr();
    canvas.height = h * dpr();
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    var ctx = canvas.getContext && canvas.getContext("2d");
    if (!ctx) {
      /* No 2D context (hardened browser, or canvas blocked by policy): the
       * numbers under the chart are still worth showing, and the chat feeds
       * must not go down with the picture. */
      chartMetrics(points);
      return;
    }
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
      chartMetrics([]);
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

    chartMetrics(points);
  }

  /* The numbers under the chart, rendered whether or not the picture could be
   * drawn: a browser without a 2D context still gets the price, the change and
   * the depth line. */
  function chartMetrics(points) {
    var priceEl = document.getElementById("chartPrice");
    var changeEl = document.getElementById("chartChange");
    if (!points || !points.length) {
      if (priceEl) priceEl.textContent = "—";
      if (changeEl) { changeEl.textContent = "—"; changeEl.className = ""; }
      return;
    }
    var last = points[points.length - 1];
    if (priceEl) priceEl.textContent = money(last.mid);
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
    /* Both ladders are BIDS (Kalshi's book endpoint returns bids only). The
     * implied YES ask is 1.00 - best NO bid, so a NO bid at 0.96 is a YES ask
     * at 0.04 — reading the NO ladder top-down is reading the YES ask side. */
    host.innerHTML = block("YES bid ladder", yes, "yes") +
      block("NO bid ladder (= YES asks as 1.00 − price)", no, "no");
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
    tickAge();
    fetchSnapshot().then(function (payload) {
      if (payload) applySnapshot(payload, "poll");
    });

    // Snapshot age: computed in the visitor's browser from the topbar
    // timestamp, so a stale snapshot is visible at a glance (R-D-01).
    function updateAge() {
      var el = document.getElementById("snapshotAge");
      var t = document.getElementById("updatedAt");
      if (!el || !t) return;
      var raw = (t.textContent || "").replace(/^Snapshot\s+/, "").trim();
      if (!raw) { el.textContent = ""; return; }
      var when = Date.parse(/(zZ|[+\-]\d\d:?\d\d)$/.test(raw) ? raw : raw + "Z");
      if (isNaN(when)) { el.textContent = ""; return; }
      var mins = Math.max(0, Math.round((Date.now() - when) / 60000));
      el.textContent = mins < 1 ? "· age < 1 min" : "· age " + mins + " min";
      el.className = "snapshot-age" + (mins >= 15 ? " stale" : "");
    }
    updateAge();
    setInterval(updateAge, 30000);

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

    /* YES / NO — the same market seen from either contract. */
    $all("#sideTabs button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        $all("#sideTabs button").forEach(function (b) { b.classList.remove("selected"); });
        btn.classList.add("selected");
        state.side = btn.getAttribute("data-side") || "yes";
        var legend = document.getElementById("sideLegend");
        var axis = document.getElementById("sideAxis");
        var name = state.side === "no" ? "NO" : "YES";
        if (legend) legend.textContent = name + " price";
        if (axis) axis.textContent = name;
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

    // Live pulse: measure the tracked books from this browser (see the block
    // above startLivePulse()). Off when the page has no pulse panel.
    startLivePulse();
  }

  /* ------------------------------------------------------------------ */
  /* live pulse — a rolling >= $0.10 detector measured in this browser   */
  /* ------------------------------------------------------------------ */

  /* Why: the published snapshot is rebuilt every 5-15 minutes by a scheduled
   * Actions run, so between runs nothing re-measures a price and both chats go
   * quiet even while a market moves. Kalshi's documented batch order-book
   * endpoint returns up to 100 books in ONE anonymous request, so a polite
   * per-refresh poll measures the whole tracked set without a credential and
   * without a WebSocket (the WS `ticker` channel needs KALSHI-ACCESS-*
   * handshake headers a browser cannot set — see review.html).
   *
   * The detector itself is assets/live-feed.js: pure, unit-tested, and it
   * mirrors the collector's quote-integrity rule instead of relaxing it. This
   * block is only I/O + rendering. */
  var pulse = {
    detector: null,
    timer: null,
    on: true,
    inflight: false,
    tickers: [],
    meta: {},
    refreshes: 0,
    error: "",
  };
  var PULSE_EVERY_MS = 45000;   // polite: one request per refresh
  var PULSE_CAP = 100;          // documented cap of GET /markets/orderbooks

  /* The cadence is a panel attribute so an operator can slow the desk down
   * without a code change; the default is one request every 45 s. */
  function pulseInterval() {
    var host = pulseEl("livePulse");
    var raw = host && host.getAttribute("data-pulse-interval-ms");
    var ms = raw ? Number(raw) : NaN;
    return (isFinite(ms) && ms >= 2000) ? ms : PULSE_EVERY_MS;
  }

  function pulseMeta() {
    var s = state.snapshot || {};
    var out = {};
    (s.events || []).forEach(function (e) {
      if (!e || !e.ticker) return;
      out[e.ticker] = {
        ticker: e.ticker,
        title: e.title || e.ticker,
        topic: e.topic || "",
        series_ticker: e.series_ticker || "",
        event_ticker: e.event_ticker || "",
        market_url: e.market_url || "",
      };
    });
    return out;
  }

  function pulseEl(id) { return document.getElementById(id); }

  function pulseBanner(text, kind) {
    var pill = pulseEl("pulseState");
    if (!pill) return;
    pill.className = "live-pill " + (kind || "");
    var span = pill.querySelector("span");
    if (span) span.textContent = text; else pill.textContent = text;
  }

  function pulseStats() {
    var el = pulseEl("pulseStats");
    if (!el || !pulse.detector) return;
    var ev = pulse.detector.events();
    var ex = ev.filter(function (a) { return a.quality === "executable"; }).length;
    el.textContent = pulse.refreshes + " refresh" + (pulse.refreshes === 1 ? "" : "es") +
      " · " + ev.length + " live swing" + (ev.length === 1 ? "" : "s") +
      " (" + ex + " executable, " + (ev.length - ex) + " indicative)";
    var src = pulseEl("pulseSource");
    if (src) {
      src.textContent = pulse.error
        ? "last error: " + pulse.error
        : "source: GET /markets/orderbooks (demo)";
    }
  }

  /* A live row is deliberately NOT the same object shape the collector
   * publishes, and it says so on its face: its reference_basis and news_status
   * differ, and it carries a LIVE tag. Reusing alertRow() would have implied
   * the collector produced it. */
  function liveRow(a) {
    var up = a.direction === "up";
    var row = document.createElement("div");
    row.className = "chat-row live " + (up ? "up" : "down");
    var badges = '<span class="tag tag-live" title="Measured by this browser ' +
      'between collector runs, not by the scheduled collector.">live</span> ';
    if (a.live_repeat) {
      badges += '<span class="tag tag-purple" title="The same market stepped ' +
        '&ge; $0.10 again in the same direction inside two minutes.">repeat step</span> ';
    }
    if (a.quality === "indicative") {
      badges += '<span class="flag-badge" title="' + esc(a.quality_reason || "") +
        '">indicative · not executable</span> ';
    } else {
      badges += '<span class="tag tag-yes" title="Two-sided book tighter than ' +
        'the $0.10 threshold with size resting at the level.">executable</span> ';
    }
    var q = encodeURIComponent(a.title || a.ticker || "");
    row.innerHTML =
      "<time>" + esc((a.iso || "").slice(11, 19)) + "</time>" +
      '<span class="chat-delta ' + (up ? "pos" : "neg") + '">' +
      (up ? "▲ +" : "▼ −") + Math.abs(Number(a.abs_delta) || 0).toFixed(4) + "</span>" +
      '<span class="chat-body">' +
      '<a href="' + (safeUrl(a.market_url) || "#") + '" target="_blank" rel="noreferrer">' +
      esc(a.title || a.ticker) + "</a>" +
      "<small>" + money(a.previous) + " → " + money(a.current) + " · " +
      esc(a.topic) + " · quote mid to quote mid (live polls)" +
      " · YES spread " + money(a.spread, 4) +
      (a.size_at_top === null || a.size_at_top === undefined
        ? " · no resting size at the level"
        : " · " + num(a.size_at_top) + " contracts at the level") +
      "</small>" +
      '<span class="chat-badges">' + badges + "</span>" +
      '<span class="cause-links"><span class="cause-none">no news link: a live ' +
      "row is not compared against a headline, and no cause is claimed</span></span>" +
      '<span class="cause-links">' +
      '<a href="' + esc(eventUrl(a)) + '" target="_blank" rel="noreferrer">Event page ↗</a>' +
      '<a href="' + esc(newsUrl(a)) + '" target="_blank" rel="noreferrer">News search ↗</a>' +
      "</span></span>" +
      '<button class="ghost-link" data-chart="' + esc(a.ticker) + '" ' +
      'data-series="' + esc(a.series_ticker || "") + '">chart</button>';
    return row;
  }

  function renderPulse(delta) {
    var feed = pulseEl("feedLive");
    if (!feed || !pulse.detector) return;
    var rows = pulse.detector.events();
    if (!rows.length) {
      if (!feed.querySelector(".empty-state")) {
        feed.innerHTML = '<div class="empty-state inline">No ≥ $0.10 move ' +
          "measured between two of this tab's readings yet. " +
          (pulse.refreshes < 2 ? "One reading so far — the second one is what " +
            "can produce a move." : "The books are quiet at this cadence. " +
            "Each row will show the two quotes it compared.") + "</div>";
      }
    } else {
      var empty = feed.querySelector(".empty-state");
      if (empty) empty.remove();
      var added = (delta && delta.fired) || [];
      added.slice().reverse().forEach(function (a) {
        feed.insertBefore(liveRow(a), feed.firstChild);
      });
      /* Bounded: the detector caps its own buffer, but the DOM must not grow
       * without bound in a tab left open for a day. */
      while (feed.children.length > 120) feed.removeChild(feed.lastChild);
    }
    var box = pulseEl("pulseRefusals");
    if (box) {
      var refused = pulse.detector.suppressed();
      box.hidden = !refused.length;
      if (refused.length) {
        box.innerHTML = '<div class="pulse-refusal-head"><b>' + refused.length +
          " move" + (refused.length === 1 ? "" : "s") + " refused by the quote " +
          'rule since this tab opened</b> <button class="ghost-link" id="pulseRefusalToggle">' +
          'show</button></div><ul id="pulseRefusalList" hidden>' +
          refused.slice(0, 40).map(function (r) {
            return "<li><code>" + esc(r.ticker) + "</code> " +
              (r.abs_delta !== undefined ? "$" + Number(r.abs_delta).toFixed(4) + " " +
                esc(r.direction) + " · " : "") + esc(r.reason) +
              " · " + esc((r.iso || "").slice(11, 19)) + "</li>";
          }).join("") + "</ul>";
        var toggle = pulseEl("pulseRefusalToggle");
        if (toggle) toggle.addEventListener("click", function () {
          var list = pulseEl("pulseRefusalList");
          if (!list) return;
          list.hidden = !list.hidden;
          toggle.textContent = list.hidden ? "show" : "hide";
        });
      }
    }
    pulseStats();
  }

  /* Where to read the books from.
   *
   * 1. The demo API directly — CORS for the Pages origin was verified by
   *    tools/live_probe.py (docs/data/capabilities.json), and this keeps the
   *    visitor's browser talking to one origin it already trusts.
   * 2. This site's own origin, when it is being served by server/app.py, which
   *    proxies the identical documented endpoint (/api/orderbooks). Used when
   *    the direct call fails, e.g. a network that blocks the exchange or a
   *    preview origin the exchange has never seen.
   * A failure of both is reported on the panel; the rows are never fabricated. */
  function pulseUrls() {
    /* `tickers` is a string[] query parameter, so each ticker is its own
     * `tickers=` occurrence. A comma-joined value is read by the exchange as
     * one ticker named "A,B" and comes back with an empty book — which
     * silently starves the pulse. LiveFeed.batchOrderbookUrl() builds the
     * documented form and is unit-tested (test/live-feed-url.test.mjs). */
    var urls = [];
    var direct = LiveFeed.batchOrderbookUrl(
      "https://external-api.demo.kalshi.co/trade-api/v2/markets/orderbooks",
      pulse.tickers);
    if (direct) urls.push(direct);
    if (/^https?:$/.test(location.protocol)) {
      var proxied = LiveFeed.batchOrderbookUrl(location.origin + "/api/orderbooks",
                                               pulse.tickers);
      if (proxied) urls.push(proxied);
    }
    return urls;
  }

  function tryUrls(urls, i) {
    if (i >= urls.length) return Promise.reject(new Error(pulse.error || "no route"));
    return fetch(urls[i], { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .catch(function (err) {
        if (i + 1 < urls.length) {
          pulse.error = String((err && err.message) || err);
          return tryUrls(urls, i + 1);
        }
        throw err;
      });
  }

  function pulseRefresh() {
    if (!pulse.on || pulse.inflight || !pulse.detector) return Promise.resolve(null);
    if (!pulse.tickers.length) return Promise.resolve(null);
    pulse.inflight = true;
    var started = Date.now();
    return tryUrls(pulseUrls(), 0)
      .then(function (data) {
        var books = {};
        ((data && data.orderbooks) || []).forEach(function (entry) {
          if (entry && entry.ticker) books[entry.ticker] = entry.orderbook_fp || {};
        });
        if (!Object.keys(books).length) throw new Error("empty response");
        var quotes = {};
        Object.keys(books).forEach(function (t) {
          if (!pulse.meta[t]) return;
          quotes[t] = { meta: pulse.meta[t], quote: LiveFeed.quoteFromBook(books[t]) };
        });
        /* If none of the returned books is one of the tracked tickers, the
         * request shape was wrong (e.g. a comma-joined `tickers` value is
         * read by the exchange as one ticker with commas in its name). Report
         * it instead of counting a healthy-looking refresh that measured
         * nothing. */
        if (!Object.keys(quotes).length) {
          throw new Error("no tracked ticker in response (" +
            Object.keys(books).length + " unmatched)");
        }
        var out = pulse.detector.ingest(quotes, started);
        pulse.refreshes += 1;
        pulse.error = "";
        pulseBanner("LIVE PULSE · " + pulse.refreshes + " reading" +
          (pulse.refreshes === 1 ? "" : "s"), "live");
        renderPulse(out);
        return out;
      })
      .catch(function (err) {
        pulse.error = String((err && err.message) || err);
        pulseBanner("PULSE OFFLINE", "");
        pulseStats();
        return null;
      })
      .then(function (out) { pulse.inflight = false; return out; });
  }

  function startLivePulse() {
    var host = pulseEl("livePulse");
    if (!host || host.getAttribute("data-pulse-started")) return;
    host.setAttribute("data-pulse-started", "1");
    if (!window.LiveFeed) {
      pulseBanner("PULSE UNAVAILABLE", "");
      return;
    }
    pulse.detector = LiveFeed.newDetector();
    pulse.meta = pulseMeta();
    pulse.tickers = Object.keys(pulse.meta).slice(0, PULSE_CAP);
    var toggle = pulseEl("pulseOn");
    if (toggle) {
      toggle.addEventListener("change", function () {
        pulse.on = !!toggle.checked;
        if (pulse.on) { pulseRefresh(); }
        else {
          pulseBanner("PULSE PAUSED", "");
        }
      });
    }
    if (!pulse.tickers.length) {
      pulseBanner("NO MARKETS", "");
      return;
    }
    pulseBanner("READING…", "");
    pulseRefresh();
    pulse.timer = setInterval(pulseRefresh, pulseInterval());
    state.timers.push(function () { clearInterval(pulse.timer); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
