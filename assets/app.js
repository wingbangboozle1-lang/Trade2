(() => {
  "use strict";
  const REST = "https://external-api.demo.kalshi.co/trade-api/v2";
  const DOCS = {
    events: "https://docs.kalshi.com/api-reference/events/get-events",
    markets: "https://docs.kalshi.com/api-reference/market/get-markets",
    orderbook:
      "https://docs.kalshi.com/api-reference/market/get-market-orderbook",
    demo: "https://docs.kalshi.com/getting_started/demo_env",
    ws: "https://docs.kalshi.com/getting_started/quick_start_websockets",
    order: "https://docs.kalshi.com/getting_started/quick_start_create_order",
  };
  const TOPICS = {
    gas: {
      label: "Gas prices",
      terms: /\b(gasoline|gas prices?|natural gas|fuel prices?|petrol)\b/i,
    },
    elections: {
      label: "Elections",
      terms:
        /\b(election|president|presidential|senate|governor|congress|primary|nominee|vote|ballot|democrat|republican)\b/i,
    },
    culture: {
      label: "Culture",
      terms:
        /\b(celebrity|entertainment|movie|film|music|album|artist|actor|actress|award|grammy|oscar|box office|tv show|television|culture|tiktok|youtube)\b/i,
    },
    crypto: {
      label: "Crypto",
      terms:
        /\b(bitcoin|btc|ethereum|ether|crypto|solana|dogecoin|doge|xrp|blockchain)\b/i,
    },
    golf: {
      label: "Golf",
      terms:
        /\b(golf|pga|masters tournament|ryder cup|lpga|the open championship|us open golf)\b/i,
    },
  };
  const $ = (q, root = document) => root.querySelector(q);
  const $$ = (q, root = document) => [...root.querySelectorAll(q)];
  const store = {
    read(key, fallback) {
      try {
        const v = localStorage.getItem("marketdesk." + key);
        return v ? JSON.parse(v) : fallback;
      } catch {
        return fallback;
      }
    },
    write(key, value) {
      try {
        localStorage.setItem("marketdesk." + key, JSON.stringify(value));
      } catch {
        toast("Browser storage is unavailable; session data will not persist.");
      }
    },
  };
  let markets = [],
    settledMarkets = [],
    lastSettledFetch = 0,
    lastSettlementCheck = 0,
    alerts = store.read("alerts", []),
    trades = store.read("trades", []),
    history = store.read("history", {}),
    autoTrade = store.read("autoTrade", true),
    selectedTopic = "all",
    feed = "all",
    selectedTicker = "",
    busy = false,
    lastError = "",
    settledLoadError = "";
  let settlementOffset = 0;
  const pageTopic = document.body.dataset.topic || "all";
  const RANGE_MS = {
    seconds: 60 * 1000,
    minutes: 15 * 60 * 1000,
    hours: 6 * 60 * 60 * 1000,
  };
  const MAX_ALERTS = 180;
  const MAX_HISTORY_MARKETS = 300;
  const MAX_HISTORY_POINTS = 240;
  const value = (obj, ...keys) => {
    for (const k of keys) {
      if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== "")
        return obj[k];
    }
    return null;
  };
  const num = (v) => {
    if (v === null || v === undefined || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const esc = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const fmtPrice = (v) => (num(v) === null ? "—" : `$${Number(v).toFixed(2)}`);
  const fmtQty = (v) =>
    num(v) === null
      ? "—"
      : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const fmtDollar = (v) =>
    num(v) === null
      ? "—"
      : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const timeOf = (v) => {
    const d = new Date(v);
    return Number.isNaN(d.valueOf())
      ? "—"
      : d.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });
  };
  const pct = (v) =>
    v === null ? "—" : `${v >= 0 ? "+" : ""}$${Math.abs(v).toFixed(2)}`;
  function toast(text) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = text;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2600);
  }
  function classify(event, market) {
    const text = [
      event.title,
      event.sub_title,
      event.category,
      event.series_ticker,
      event.event_ticker,
      market.title,
      market.subtitle,
      market.ticker,
    ]
      .filter(Boolean)
      .join(" ");
    for (const [id, t] of Object.entries(TOPICS))
      if (t.terms.test(text)) return id;
    return "";
  }
  function yesBid(m) {
    return num(value(m, "yes_bid_dollars", "yes_bid"));
  }
  function marketLink(m) {
    return `${REST}/markets/${encodeURIComponent(m.ticker)}`;
  }
  function topicHref(id) {
    return (
      {
        gas: "categories/gas-prices.html",
        elections: "categories/elections.html",
        culture: "categories/culture.html",
        crypto: "categories/crypto.html",
        golf: "categories/golf.html",
      }[id] || "#"
    );
  }
  function normalize(data, includeSettled = false) {
    const output = [];
    for (const event of data.events || []) {
      for (const m of event.markets || []) {
        const status = String(
          value(m, "status") || event.status || "",
        ).toLowerCase();
        if (
          status &&
          !["open", "active"].includes(status) &&
          !(includeSettled && status === "settled")
        )
          continue;
        const topic = classify(event, m);
        if (!topic) continue;
        const bid = yesBid(m);
        const volume = num(value(m, "volume_24h_fp", "volume_24h"));
        const contractValue = num(value(m, "notional_value_dollars"));
        const openInterest = num(value(m, "open_interest_fp"));
        const openInterestValue =
          contractValue !== null && openInterest !== null
            ? contractValue * openInterest
            : null;
        output.push({
          ...m,
          event_title: event.title || m.title || m.ticker,
          event_ticker: event.event_ticker || m.event_ticker,
          topic,
          bid,
          volume24: volume,
          contractValue,
          openInterest,
          openInterestValue,
          topSize: num(value(m, "yes_bid_size_fp", "yes_bid_size")),
          resolution: String(value(m, "result") || "").toLowerCase(),
          source: marketLink(m),
        });
      }
    }
    return output;
  }
  async function getJson(path) {
    const r = await fetch(`${REST}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!r.ok)
      throw new Error(
        `Kalshi demo API returned HTTP ${r.status} for ${path.split("?")[0]}`,
      );
    return r.json();
  }
  async function fetchEvents() {
    let cursor = "",
      collected = [],
      page = 0;
    // Each events response contains nested market quotes; cap the scan at four documented 200-event pages per refresh.
    while (page < 4) {
      const params = new URLSearchParams({
        status: "open",
        with_nested_markets: "true",
        limit: "200",
      });
      if (cursor) params.set("cursor", cursor);
      const data = await getJson(`/events?${params.toString()}`);
      collected.push(...(data.events || []));
      page++;
      cursor = data.cursor || "";
      if (!cursor) break;
    }
    return normalize({ events: collected });
  }
  async function fetchSettled() {
    const data = await getJson(
      "/events?status=settled&with_nested_markets=true&limit=200",
    );
    return normalize(data, true).filter(
      (m) => m.resolution === "yes" || m.resolution === "no",
    );
  }
  function histPoint(m, now) {
    if (m.bid === null) return;
    const points = history[m.ticker] || [];
    const previous = points.length ? points[points.length - 1] : null;
    // Do not manufacture an alert from the first observation; compare quotes only when both are present.
    if (previous && now - previous.t < 20 * 60 * 1000) {
      const delta = +(m.bid - previous.p).toFixed(4);
      if (Math.abs(delta) >= 0.1) recordAlert(m, delta, now);
    }
    points.push({ t: now, p: m.bid });
    history[m.ticker] = points
      .filter((p) => now - p.t <= 24 * 60 * 60 * 1000)
      .slice(-MAX_HISTORY_POINTS);
  }
  function persistHistory() {
    const compact = Object.entries(history)
      .sort((a, b) => {
        if (a[0] === selectedTicker) return -1;
        if (b[0] === selectedTicker) return 1;
        return (b[1].at(-1)?.t || 0) - (a[1].at(-1)?.t || 0);
      })
      .slice(0, MAX_HISTORY_MARKETS)
      .map(([ticker, points]) => [ticker, points.slice(-MAX_HISTORY_POINTS)]);
    store.write("history", Object.fromEntries(compact));
  }
  function modelCandidate(alert) {
    // Transparent screening heuristic, not an expected-return or profit model.
    return num(alert.openInterestValue) > 0 && Math.abs(alert.delta) >= 0.1;
  }
  function recordAlert(m, delta, now) {
    const a = {
      id: `${m.ticker}-${now}`,
      ticker: m.ticker,
      title: m.event_title,
      topic: m.topic,
      delta,
      bid: m.bid,
      openInterestValue: m.openInterestValue,
      volume24: m.volume24,
      topSize: m.topSize,
      time: now,
      source: m.source,
    };
    a.shortlisted = modelCandidate(a);
    alerts.unshift(a);
    alerts = alerts.slice(0, MAX_ALERTS);
    store.write("alerts", alerts);
    if (autoTrade && delta >= 0.1) paperEntry(m, now);
  }
  function paperEntry(m, now) {
    const same = trades.some(
      (t) => t.ticker === m.ticker && now - t.time < 60 * 60 * 1000,
    );
    if (same || m.bid === null || m.bid <= 0 || m.bid >= 1) return;
    const count = Number($("#contractCount")?.value || 1);
    trades.unshift({
      id: `paper-${m.ticker}-${now}`,
      ticker: m.ticker,
      title: m.event_title,
      topic: m.topic,
      side: "YES",
      entry: m.bid,
      count,
      time: now,
      result: "",
      pnl: null,
      tradeType: "positive momentum",
      source: m.source,
    });
    trades = trades.slice(0, 250);
    store.write("trades", trades);
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    const refreshEls = [$("#refreshButton"), $("#refreshMain")].filter(Boolean);
    refreshEls.forEach((b) => (b.disabled = true));
    try {
      const fresh = await fetchEvents();
      const now = Date.now();
      for (const m of fresh) histPoint(m, now);
      markets = fresh;
      lastError = "";
      persistHistory();
      const checkSettlements = now - lastSettlementCheck >= 60000;
      await updateSettlements(fresh, checkSettlements);
      if (checkSettlements) lastSettlementCheck = now;
      if ($("#resolvedRows") && now - lastSettledFetch >= 60000) {
        try {
          settledMarkets = await fetchSettled();
          lastSettledFetch = now;
          settledLoadError = "";
        } catch (e) {
          settledLoadError = e.message;
        }
      }
      render();
    } catch (e) {
      lastError = e.message;
      renderError(e.message);
    } finally {
      busy = false;
      refreshEls.forEach((b) => (b.disabled = false));
      const t = $("#updatedAt");
      if (t)
        t.textContent = `${lastError ? "Checked" : "Updated"} ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    }
  }
  async function updateSettlements(fresh, checkPending = false) {
    const active = new Set(fresh.map((m) => m.ticker));
    const pendingAll = checkPending
      ? [
          ...new Set(
            trades
              .filter((t) => !t.result && !active.has(t.ticker))
              .map((t) => t.ticker),
          ),
        ]
      : [];
    const pending = pendingAll.length
      ? Array.from(
          { length: Math.min(12, pendingAll.length) },
          (_, i) => pendingAll[(settlementOffset + i) % pendingAll.length],
        )
      : [];
    if (pendingAll.length)
      settlementOffset =
        (settlementOffset + pending.length) % pendingAll.length;
    for (const ticker of pending) {
      try {
        const data = await getJson(`/markets/${encodeURIComponent(ticker)}`);
        const m = data.market || data;
        const result = String(value(m, "result") || "").toLowerCase();
        if (result === "yes" || result === "no") {
          for (const t of trades)
            if (t.ticker === ticker && !t.result) {
              t.result = result;
              t.pnl = +(
                result === "yes" ? (1 - t.entry) * t.count : -t.entry * t.count
              ).toFixed(4);
            }
        }
      } catch {
        /* Pending market may not be available in this demo response; leave outcome blank. */
      }
    }
    for (const m of fresh) {
      if (m.resolution === "yes" || m.resolution === "no") {
        for (const t of trades)
          if (t.ticker === m.ticker && !t.result) {
            t.result = m.resolution;
            t.pnl = +(
              m.resolution === "yes"
                ? (1 - t.entry) * t.count
                : -t.entry * t.count
            ).toFixed(4);
          }
      }
    }
    store.write("trades", trades);
  }
  function renderError(message) {
    const notice = $("#apiNotice");
    if (notice) {
      notice.className = "notice notice-error";
      notice.innerHTML = `<span>!</span><div><b>Live demo data unavailable</b><p>${esc(message)}. Displayed rows are from the last successful poll, if any, and may be stale. Check the official API status or retry.</p></div>`;
    }
    if (!markets.length) {
      const rows = $("#marketRows");
      if (rows)
        rows.innerHTML = `<tr><td colspan="9" class="empty-state">No verified live values to display. <a href="${DOCS.events}" target="_blank" rel="noreferrer">Review the official events API ↗</a></td></tr>`;
    }
    render();
  }
  function renderedMarkets() {
    let list = [...markets];
    if (pageTopic !== "all") list = list.filter((m) => m.topic === pageTopic);
    if (selectedTopic !== "all")
      list = list.filter((m) => m.topic === selectedTopic);
    const q = ($("#searchInput")?.value || "").toLowerCase().trim();
    if (q)
      list = list.filter((m) =>
        `${m.event_title} ${m.ticker} ${m.event_ticker}`
          .toLowerCase()
          .includes(q),
      );
    return list.sort(
      (a, b) => (b.openInterestValue ?? -1) - (a.openInterestValue ?? -1),
    );
  }
  function render() {
    renderNotice();
    renderStats();
    renderMarkets();
    renderCategoryRows();
    renderResolved();
    renderSelector();
    renderAlerts();
    renderTrades();
    renderChart();
    renderDepth();
  }
  function renderNotice() {
    const n = $("#apiNotice");
    if (!n) return;
    if (lastError) {
      n.className = "notice notice-error";
      n.innerHTML = `<span>!</span><div><b>Live demo data unavailable</b><p>${esc(lastError)}. Displayed rows are from the last successful poll, if any, and may be stale. Check the official API status or retry.</p></div>`;
      return;
    }
    n.className = "notice notice-info";
    n.innerHTML = `<span>ⓘ</span><div><b>Demo feed · public market data</b><p>REST polling every 15 seconds. Demo pricing can differ from real markets. <a href="${DOCS.demo}" target="_blank" rel="noreferrer">Official demo notes ↗</a></p></div>`;
  }
  function renderStats() {
    const s = $("#statMarkets");
    if (s)
      s.textContent = String(
        pageTopic === "all"
          ? markets.length
          : markets.filter((m) => m.topic === pageTopic).length,
      );
    const a = $("#statAlerts");
    if (a) a.textContent = String(alerts.length);
    const p = $("#statPositions");
    if (p) p.textContent = String(trades.filter((t) => !t.result).length);
    const pnl = trades
      .filter((t) => Number.isFinite(t.pnl))
      .reduce((sum, t) => sum + t.pnl, 0);
    const pnlEl = $("#statPnl");
    if (pnlEl) {
      pnlEl.textContent = fmtDollar(pnl);
      pnlEl.className = pnl >= 0 ? "positive" : "negative";
    }
  }
  function renderMarkets() {
    const body = $("#marketRows");
    if (!body) return;
    const list = renderedMarkets();
    const count = $("#tableCount");
    if (count)
      count.textContent = `Showing ${Math.min(list.length, 150)} of ${list.length} open markets · sorted by calculated open-interest value · up to 800 events scanned`;
    if (!list.length) {
      body.innerHTML = `<tr><td colspan="9" class="empty-state">${lastError ? "No live API data available." : "No open markets matched this topic in the scanned event pages."}</td></tr>`;
      return;
    }
    body.innerHTML = list
      .slice(0, 150)
      .map((m) => {
        const hs = history[m.ticker] || [];
        const change =
          hs.length > 1
            ? +(hs[hs.length - 1].p - hs[hs.length - 2].p).toFixed(2)
            : null;
        const deltaCls =
          change === null
            ? "quiet"
            : change > 0
              ? "positive"
              : change < 0
                ? "negative"
                : "quiet";
        const topic = TOPICS[m.topic]?.label || m.topic;
        return `<tr data-ticker="${esc(m.ticker)}"><td><div class="event-name" title="${esc(m.event_title)}">${esc(m.event_title || m.title || m.ticker)}</div><div class="ticker">${esc(m.ticker)}</div></td><td><a class="topic-chip" href="${topicHref(m.topic)}">${esc(topic)}</a></td><td class="price-cell">${m.bid === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtPrice(m.bid)}</td><td class="${deltaCls}">${change === null ? "" : pct(change)}</td><td>${m.topSize === null ? '<span class="flag-badge">UNVERIFIED</span>' : `${fmtQty(m.topSize)} <span class="quiet">at best bid</span>`}</td><td>${m.volume24 === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtQty(m.volume24)}</td><td>${m.openInterestValue === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtDollar(m.openInterestValue)}</td><td><span class="status-chip ${lastError ? "status-settled" : ""}">${lastError ? "STALE" : "Open"}</span></td><td><a class="external-link" href="${m.source}" target="_blank" rel="noreferrer" title="Official Kalshi market API source">↗</a></td></tr>`;
      })
      .join("");
    $$("tbody tr[data-ticker]", body).forEach((row) =>
      row.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;
        selectMarket(row.dataset.ticker);
      }),
    );
  }
  function renderResolved() {
    const body = $("#resolvedRows");
    if (!body) return;
    if (settledLoadError && !settledMarkets.length) {
      body.innerHTML = `<tr><td colspan="5" class="empty-state">Settled event snapshot unavailable. <a href="${DOCS.events}" target="_blank" rel="noreferrer">Official source ↗</a></td></tr>`;
      return;
    }
    const topicFilter = pageTopic === "all" ? selectedTopic : pageTopic;
    const list =
      topicFilter === "all"
        ? settledMarkets
        : settledMarkets.filter((m) => m.topic === topicFilter);
    if (!list.length) {
      body.innerHTML =
        '<tr><td colspan="5" class="empty-state">No YES/NO resolutions returned in the latest official settled-event page.</td></tr>';
      return;
    }
    body.innerHTML = list
      .slice(0, 50)
      .map(
        (m) =>
          `<tr><td><div class="event-name">${esc(m.event_title || m.title || m.ticker)}</div><div class="ticker">${esc(m.ticker)}</div></td><td>${esc(TOPICS[m.topic]?.label || m.topic)}</td><td><span class="status-chip ${m.resolution === "yes" ? "" : "status-settled"}">${esc(m.resolution.toUpperCase())}</span></td><td>${value(m, "settlement_ts", "close_time") ? esc(value(m, "settlement_ts", "close_time")) : '<span class="flag-badge">UNVERIFIED</span>'}</td><td><a class="source-link" href="${m.source}" target="_blank" rel="noreferrer">Kalshi API source ↗</a></td></tr>`,
      )
      .join("");
  }
  function renderCategoryRows() {
    const body = $("#categoryRows");
    if (!body) return;
    const list = renderedMarkets();
    if (!list.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty-state">${lastError ? "No verified live values are currently available." : "No open markets matched this category in the scanned event pages."}</td></tr>`;
      return;
    }
    body.innerHTML = list
      .map(
        (m) =>
          `<tr><td><div class="event-name">${esc(m.event_title || m.title || m.ticker)}</div><div class="ticker">${esc(m.ticker)}</div></td><td>${m.bid === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtPrice(m.bid)}</td><td>${m.topSize === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtQty(m.topSize)}</td><td>${m.volume24 === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtQty(m.volume24)}</td><td>${m.openInterestValue === null ? '<span class="flag-badge">UNVERIFIED</span>' : fmtDollar(m.openInterestValue)}</td><td>${value(m, "close_time") ? esc(value(m, "close_time")) : '<span class="flag-badge">UNVERIFIED</span>'}</td><td><a class="source-link" href="${m.source}" target="_blank" rel="noreferrer">Kalshi API source ↗</a></td></tr>`,
      )
      .join("");
  }
  function renderSelector() {
    const select = $("#chartMarket");
    if (!select) return;
    const previous = selectedTicker;
    const list = markets
      .filter((m) => m.bid !== null)
      .slice()
      .sort(
        (a, b) => (b.openInterestValue ?? -1) - (a.openInterestValue ?? -1),
      );
    select.innerHTML =
      '<option value="">Choose a market</option>' +
      list
        .map(
          (m) =>
            `<option value="${esc(m.ticker)}">${esc(m.event_title || m.ticker).slice(0, 70)}</option>`,
        )
        .join("");
    if (previous && list.some((m) => m.ticker === previous)) {
      select.value = previous;
    } else if (list.length) {
      select.value = list[0].ticker;
      selectedTicker = list[0].ticker;
    }
  }
  function selectMarket(ticker) {
    selectedTicker = ticker;
    const s = $("#chartMarket");
    if (s) s.value = ticker;
    renderChart();
    renderDepth();
  }
  function renderAlerts() {
    const feedEl = $("#alertFeed");
    if (!feedEl) return;
    const list =
      feed === "model" ? alerts.filter((a) => a.shortlisted) : alerts;
    const badge = $("#alertCount");
    if (badge) badge.textContent = String(list.length);
    if (!list.length) {
      feedEl.innerHTML = `<div class="empty-state inline">${alerts.length ? "No events meet the transparent shortlist rule yet." : "Waiting for observed price changes…"}</div>`;
      return;
    }
    feedEl.innerHTML = list
      .slice(0, 60)
      .map(
        (a) =>
          `<div class="alert-item"><span class="alert-avatar">${a.delta >= 0 ? "↗" : "↘"}</span><div><b title="${esc(a.title)}">${esc(a.title)}</b><p><span class="${a.delta >= 0 ? "positive" : "negative"}">${a.delta >= 0 ? "up" : "down"} ${fmtDollar(Math.abs(a.delta))}</span> · YES bid ${fmtPrice(a.bid)} · ${esc(TOPICS[a.topic]?.label || a.topic)}</p><div class="alert-time">${timeOf(a.time)} · <a href="${a.source}" target="_blank" rel="noreferrer">official market data ↗</a>${a.shortlisted ? " · model watch" : ""}</div></div></div>`,
      )
      .join("");
  }
  function renderTrades() {
    const body = $("#tradeRows");
    if (!body) return;
    if (!trades.length) {
      body.innerHTML =
        '<tr><td colspan="7" class="empty-state">No paper trades yet. Enable Auto to simulate future positive threshold alerts.</td></tr>';
      return;
    }
    body.innerHTML = trades
      .slice(0, 30)
      .map(
        (t) =>
          `<tr><td><div class="event-name">${esc(t.title)}</div><div class="ticker"><a href="${t.source}" target="_blank" rel="noreferrer">${esc(t.ticker)} · official source ↗</a> · ${timeOf(t.time)}</div></td><td>${esc(t.side)}</td><td>${fmtPrice(t.entry)}</td><td>${fmtQty(t.count)}</td><td>${t.result ? `<b>${esc(t.result.toUpperCase())}</b>` : '<span class="quiet">Open</span>'}</td><td class="${t.pnl === null ? "quiet" : t.pnl >= 0 ? "positive" : "negative"}">${t.pnl === null ? "—" : fmtDollar(t.pnl)}</td><td><span class="topic-chip">${esc(t.tradeType)}</span></td></tr>`,
      )
      .join("");
  }
  function renderChart() {
    const canvas = $("#priceChart");
    if (!canvas) return;
    const m = markets.find((x) => x.ticker === selectedTicker);
    const range = $("#timeRange")?.value || "minutes";
    const duration = RANGE_MS[range] || RANGE_MS.minutes;
    const points = (history[selectedTicker] || []).filter(
      (p) => Date.now() - p.t <= duration,
    );
    const price = $("#chartPrice");
    const change = $("#chartChange");
    const sub = $("#chartSubtitle");
    const win = $("#chartWindow");
    if (price) price.textContent = m ? fmtPrice(m.bid) : "—";
    if (sub)
      sub.textContent = m
        ? `${m.event_title} · ${m.ticker}`
        : "Select a market to view observed price history";
    if (win)
      win.textContent =
        range === "seconds"
          ? "Last 60 seconds"
          : range === "hours"
            ? "Last 6 hours"
            : "Last 15 minutes";
    const d =
      points.length > 1 ? +(points.at(-1).p - points[0].p).toFixed(2) : null;
    if (change) {
      change.textContent = d === null ? "—" : pct(d);
      change.className = d === null ? "" : d >= 0 ? "positive" : "negative";
    }
    const ctx = canvas.getContext("2d");
    const box = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(box.width * ratio));
    canvas.height = Math.max(1, Math.floor(box.height * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const w = box.width,
      h = box.height;
    ctx.clearRect(0, 0, w, h);
    const pad = { l: 38, r: 8, t: 10, b: 20 };
    const cw = w - pad.l - pad.r,
      ch = h - pad.t - pad.b;
    ctx.font = "9px DM Sans, sans-serif";
    ctx.fillStyle = "#98a49f";
    ctx.strokeStyle = "#edf1ef";
    ctx.lineWidth = 1;
    if (points.length < 2) {
      for (let i = 0; i < 4; i++) {
        const y = pad.t + (ch * i) / 3;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();
      }
      ctx.fillText(
        points.length
          ? "Collecting next observation…"
          : "Price history appears after first observation",
        pad.l + 4,
        h / 2,
      );
      return;
    }
    let min = Math.min(...points.map((p) => p.p)),
      max = Math.max(...points.map((p) => p.p));
    const spread = max - min || 0.02;
    min = Math.max(0, min - spread * 0.15);
    max = Math.min(1, max + spread * 0.15);
    if (max - min < 0.01) {
      max = Math.min(1, max + 0.02);
      min = Math.max(0, min - 0.02);
    }
    const yAt = (p) => pad.t + (max - p) * (ch / (max - min));
    for (let i = 0; i < 4; i++) {
      const y = pad.t + (ch * i) / 3;
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(w - pad.r, y);
      ctx.stroke();
      const val = max - ((max - min) * i) / 3;
      ctx.fillStyle = "#98a49f";
      ctx.fillText(`$${val.toFixed(2)}`, 2, y + 3);
    }
    const first = points[0].t,
      last = points.at(-1).t;
    for (let i = 0; i < 3; i++) {
      const x = pad.l + (cw * i) / 2;
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, pad.t + ch);
      ctx.stroke();
      const dtime = new Date(first + ((last - first) * i) / 2);
      ctx.fillStyle = "#98a49f";
      ctx.fillText(
        dtime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        Math.max(pad.l, x - 20),
        h - 4,
      );
    }
    const gradient = ctx.createLinearGradient(0, pad.t, 0, pad.t + ch);
    gradient.addColorStop(0, "rgba(25,169,123,.17)");
    gradient.addColorStop(1, "rgba(25,169,123,0)");
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = pad.l + ((p.t - first) / (last - first || 1)) * cw;
      const y = yAt(p.p);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.lineTo(pad.l + cw, pad.t + ch);
    ctx.lineTo(pad.l, pad.t + ch);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = pad.l + ((p.t - first) / (last - first || 1)) * cw;
      const y = yAt(p.p);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.strokeStyle = "#16a67a";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  async function renderDepth() {
    const el = $("#depthLevels");
    if (!el) return;
    const m = markets.find((x) => x.ticker === selectedTicker);
    if (!m) {
      el.innerHTML = '<span class="quiet">No market selected</span>';
      return;
    }
    el.innerHTML = '<span class="quiet">Loading book…</span>';
    const stamp = $("#depthStamp");
    try {
      const data = await getJson(
        `/markets/${encodeURIComponent(m.ticker)}/orderbook?depth=5`,
      );
      const book = data.orderbook_fp || data.orderbook || {};
      const yes = book.yes_dollars || [],
        no = book.no_dollars || [];
      if (stamp) stamp.textContent = `${m.ticker} · official snapshot`;
      const rows = [
        ...yes
          .slice()
          .reverse()
          .map((x) => ({ side: "YES bid", price: x[0], qty: x[1] })),
        ...no
          .slice()
          .reverse()
          .map((x) => ({ side: "NO bid", price: x[0], qty: x[1] })),
      ];
      el.innerHTML = rows.length
        ? rows
            .map(
              (r) =>
                `<div class="depth-level"><span>${esc(r.side)}</span><b>${fmtPrice(r.price)}</b><span>${fmtQty(r.qty)} contracts</span></div>`,
            )
            .join("")
        : '<span class="quiet">No bid levels returned by official API.</span>';
    } catch (e) {
      if (stamp) stamp.textContent = "Unavailable";
      el.innerHTML = `<span class="quiet">Orderbook unavailable. <a href="${m.source}" target="_blank" rel="noreferrer">Market source ↗</a></span>`;
    }
  }
  function init() {
    const search = $("#searchInput");
    if (search) search.addEventListener("input", renderMarkets);
    const time = $("#timeRange");
    if (time) time.addEventListener("change", renderChart);
    const selector = $("#chartMarket");
    if (selector)
      selector.addEventListener("change", () => selectMarket(selector.value));
    const toggle = $("#strategyToggle");
    if (toggle) {
      toggle.checked = autoTrade;
      toggle.addEventListener("change", () => {
        autoTrade = toggle.checked;
        store.write("autoTrade", autoTrade);
        toast(
          autoTrade
            ? "Momentum simulation enabled"
            : "Momentum simulation paused",
        );
      });
    }
    const refreshButton = $("#refreshButton"),
      refreshMain = $("#refreshMain");
    if (refreshButton) refreshButton.onclick = refresh;
    if (refreshMain) refreshMain.onclick = refresh;
    $$("#topicTabs button").forEach((b) =>
      b.addEventListener("click", () => {
        $$("#topicTabs button").forEach((x) => x.classList.remove("selected"));
        b.classList.add("selected");
        selectedTopic = b.dataset.topic;
        renderMarkets();
      }),
    );
    $$(".chat-switch button").forEach((b) =>
      b.addEventListener("click", () => {
        $$(".chat-switch button").forEach((x) =>
          x.classList.remove("selected"),
        );
        b.classList.add("selected");
        feed = b.dataset.feed;
        renderAlerts();
      }),
    );
    const exportButton = $("#exportTrades");
    if (exportButton)
      exportButton.onclick = () => {
        const csv = [
          "ticker,title,side,entry,contracts,result,paper_pnl,trade_type,time",
          ...trades.map((t) =>
            [
              t.ticker,
              `"${String(t.title).replaceAll('"', '""')}"`,
              t.side,
              t.entry,
              t.count,
              t.result,
              t.pnl ?? "",
              t.tradeType,
              new Date(t.time).toISOString(),
            ].join(","),
          ),
        ].join("\n");
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
        a.download = "kalshi-paper-trades.csv";
        a.click();
        URL.revokeObjectURL(a.href);
      };
    const reset = $("#resetPaper");
    if (reset)
      reset.onclick = () => {
        if (
          confirm(
            "Clear all locally stored simulated trades and alerts? This does not affect any Kalshi account.",
          )
        ) {
          trades = [];
          alerts = [];
          store.write("trades", trades);
          store.write("alerts", alerts);
          render();
          toast("Paper ledger cleared");
        }
      };
    const mobile = $(".mobile-menu");
    if (mobile)
      mobile.addEventListener("click", () =>
        $(".sidebar")?.classList.toggle("open"),
      );
    render();
    refresh();
    setInterval(refresh, 15000);
    window.addEventListener("resize", () => requestAnimationFrame(renderChart));
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
