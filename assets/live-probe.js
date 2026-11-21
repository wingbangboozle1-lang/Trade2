/* Browser-side live probe for the Kalshi demo monitoring desk.
 *
 * WHY THIS EXISTS
 * ---------------
 * The published site is static: GitHub Actions rewrites assets/live.json on a
 * schedule, and the previous alert engine could only compare two of those
 * snapshots. That left two gaps a trader actually notices:
 *
 *   1. An alert could appear at most once per CI run, and only if the same
 *      market happened to be sampled in both runs. On 2026-11-21 the public
 *      site showed `Swings >= $0.10: 0` for this reason.
 *   2. In a demo account almost nothing trades, so both snapshots are usually
 *      byte-identical and the buffer stays empty.
 *
 * The demo REST API, however, sends `access-control-allow-origin` back for any
 * Origin, so the visitor's browser can read it directly (evidence:
 * data/_cors.txt and data/capabilities.json, both captured by CI). This module
 * does that: it polls the public, unauthenticated endpoints and runs the SAME
 * >= $0.10 swing rule in the tab, so the two chat feeds update while the page
 * is open instead of only when CI happens to run.
 *
 * RULES (all taken from official Kalshi documentation, linked in the page)
 * -----------------------------------------------------------------------
 *   * Swing = |quote mid now - quote mid when first seen| >= $0.10, and the
 *     move must be at least $0.10 from the *last alerted* mid in that
 *     direction (so a market that drifts 10 cents alerts once, not every tick).
 *   * The mid is the order-book mid: (best YES bid + implied YES ask) / 2,
 *     where implied YES ask = 1 - best NO bid.
 *     https://docs.kalshi.com/getting_started/orderbook_responses
 *   * A move only counts when BOTH sides of the book are quoted and the spread
 *     is under $0.10. A one-sided or wide book is not a price a trader could
 *     act on, so the row is reported separately as `indicative` instead of
 *     being presented as a tradable swing. (This is the defect that produced
 *     the phantom $0.877 "move" in docs/data/alerts.json: yes_bid 0.0010 vs
 *     yes_ask 0.8860 on KXPRESNOMD-28-BOBA.)
 *   * The model feed applies the desk's published net-ROI gate
 *     (model_gate.min_net_roi, default 0.05) using the official taker fee
 *     schedule  fees = ceil_to_cent( M * 0.07 * C * P * (1 - P) )
 *     https://kalshi.com/docs/kalshi-fee-schedule.pdf
 *     and refuses any row whose quoted spread is wider than the $0.10 swing it
 *     is supposed to represent.
 *
 * WHAT IT DOES NOT DO
 * -------------------
 *   * It never sends an order. There are no credentials in the browser and
 *     none are needed; POST /portfolio/... is never called. Simulated trades
 *     stay in the CI engine, which is the only writer of the paper ledger.
 *   * It never invents news attribution. A headline link is only shown when
 *     the CI collector fetched one and published it next to the alert; rows
 *     detected in the browser carry an explicit "context search" link that
 *     says it is not evidence of cause.
 *   * It never overwrites the served snapshot the user is looking at. Browser
 *     rows are kept in a separate list and merged at render time, labelled
 *     LIVE, so a page that is stale is still visibly stale.
 *
 * The module is dependency-free and is shared by the desk (assets/desk.js) and
 * by the tests (tests/test_live_probe.py runs it under node). Keep it that way.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;            // node: tests
  }
  if (root) {
    root.KalshiLive = api;           // browser: window.KalshiLive
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var REST = "https://external-api.demo.kalshi.co/trade-api/v2";

  /* Documented endpoints only. `tickers` is the one filter that returns every
   * matching market in a single response with no paging, which makes it the
   * cheapest way to poll a fixed watchlist:
   * https://docs.kalshi.com/api-reference/market/get-markets */
  var ENDPOINTS = {
    markets: REST + "/markets",
    orderbooks: REST + "/markets/orderbooks",
    exchange: REST + "/exchange/status",
    candlesticks: REST + "/series/{series}/markets/{ticker}/candlesticks"
  };

  var SWING = 0.10;        // the brief's threshold, $ per contract
  var MAX_SPREAD = 0.10;   // wider than this = no executable price
  var FEE_RATE = 0.07;     // fee schedule: M * 0.07 * C * P * (1 - P)
  var MAX_BOOKS = 100;     // documented ceiling for GET /markets/orderbooks
  var MODEL_GATE = 0.05;   // desk default, overridable from the snapshot

  function num(v) {
    if (v === null || v === undefined || v === "") return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }

  /* Best bid is the LAST element: the arrays are sorted ascending by price.
   * https://docs.kalshi.com/getting_started/orderbook_responses */
  function bestBid(levels) {
    if (!levels || !levels.length) return null;
    for (var i = levels.length - 1; i >= 0; i--) {
      var row = levels[i];
      if (!row || row.length < 2) continue;
      var price = num(row[0]);
      var count = num(row[1]);
      if (price === null) continue;
      return { price: price, contracts: count === null ? 0 : count };
    }
    return null;
  }

  function bookTop(book) {
    if (!book) return null;
    var yb = bestBid(book.yes_dollars);
    var nb = bestBid(book.no_dollars);
    var yesBid = yb ? yb.price : null;
    var yesAsk = nb ? round4(1 - nb.price) : null;
    var twoSided = yesBid !== null && yesAsk !== null;
    var spread = twoSided ? round4(yesAsk - yesBid) : null;
    var mid = null;
    if (twoSided) mid = round4((yesBid + yesAsk) / 2);
    else if (yesBid !== null) mid = yesBid;
    else if (yesAsk !== null) mid = yesAsk;
    return {
      yes_bid: yesBid,
      yes_ask: yesAsk,
      mid: mid,
      spread: spread,
      two_sided: twoSided,
      yes_bid_contracts: yb ? yb.contracts : 0,
      no_bid_contracts: nb ? nb.contracts : 0,
      executable: twoSided && spread !== null && spread >= 0 && spread < MAX_SPREAD
    };
  }

  function round4(v) {
    var n = Number(v);
    if (!isFinite(n)) return null;
    return Math.round(n * 10000) / 10000;
  }

  /* fees = ceil_to_cent( M * 0.07 * C * P * (1 - P) ), in dollars.
   * Mirrors collector/kalshi_api.py:kalshi_fee, which reproduces all 42 rows
   * of the published fee table in the Python test suite. Integer arithmetic on
   * cents keeps the browser version from rounding differently. */
  function fee(price, contracts, multiplier) {
    var p = num(price);
    var c = num(contracts);
    var m = num(multiplier);
    if (m === null) m = 1;
    if (p === null || c === null || p <= 0 || p >= 1 || c <= 0 || m <= 0) return 0;
    var cents = Math.ceil(m * FEE_RATE * c * p * (1 - p) * 100 - 1e-9);
    return cents / 100;
  }

  /* ------------------------------------------------------------------ */
  /* swing detection                                                     */
  /* ------------------------------------------------------------------ */

  /* A tracker holds, per ticker, the mid each direction was last alerted from.
   * `baseline` is the first mid seen in this tab; it is what makes a move
   * measurable even when the served snapshot is hours old. */
  function createTracker(opts) {
    opts = opts || {};
    var threshold = num(opts.threshold);
    if (threshold === null) threshold = SWING;
    var state = {};
    return {
      threshold: threshold,
      baseline: function (ticker, mid) {
        if (!ticker || mid === null || mid === undefined) return null;
        /* Every stored price is rounded to the 4-decimal quote grid first.
         * Without that, 0.4999 + 0.10 != 0.6 in binary floating point and an
         * exact 10-cent move can measure as 9.999999999999998 cents. */
        var p = round4(mid);
        if (p === null) return null;
        var row = state[ticker];
        if (!row) {
          /* `ref` is the turning point a swing is measured from: the price
           * when the tab started, then the price at each alert. `first` is kept
           * separately so the indicative-move audit can say "moved this far
           * since first seen" without being reset by an alert. */
          state[ticker] = { first: p, ref: p, last: p, n: 0, alerts: 0 };
          return null;
        }
        row.last = p;
        row.n += 1;
        return row;
      },
      peek: function (ticker) { return state[ticker] || null; }
    };
  }

  /* Feed one observation. Returns an alert object when a >= threshold move is
   * measured, otherwise null. The alert is deliberately shaped like the CI
   * collector's rows so both renderers and both feeds agree field for field. */
  function observe(tracker, obs, nowMs) {
    if (!tracker || !obs || !obs.ticker) return null;
    var top = obs.top || {};
    var mid = top.mid;
    var row = tracker.baseline(obs.ticker, mid);
    if (!row || mid === null || mid === undefined) return null;
    if (!top.two_sided || !top.executable) {
      /* One-sided or wide: not a price anyone could trade. Still count a move
       * for the audit trail, but never as a tradable swing. */
      return null;
    }
    var price = round4(mid);
    var up = round4(price - row.ref);
    var down = round4(row.ref - price);
    var direction = null;
    var ref = row.ref;
    var delta = null;
    /* A swing is measured from the last turning point, not from a fixed
     * baseline: 0.50 -> 0.65 is +$0.15, and a fall back to 0.52 is then
     * -$0.13 and legitimately a second alert. Without moving `ref` to the
     * price at each alert, a market that walked up 15 cents and gave it all
     * back would report only the first half of the round trip. */
    if (up >= tracker.threshold) {
      direction = "up"; delta = up;
    } else if (down >= tracker.threshold) {
      direction = "down"; delta = down;
    }
    if (!direction) return null;
    row.ref = price;
    row.alerts += 1;
    var ts = Math.floor((nowMs || Date.now()) / 1000);
    return {
      id: "live:" + obs.ticker + ":" + direction + ":" + ts,
      ticker: obs.ticker,
      series_ticker: obs.series_ticker || null,
      event_ticker: obs.event_ticker || null,
      topic: obs.topic || null,
      title: obs.title || obs.ticker,
      direction: direction,
      from: ref,
      to: price,
      delta: round4(direction === "up" ? delta : -delta),
      abs_delta: round4(Math.abs(delta)),
      current: price,
      yes_bid: top.yes_bid,
      yes_ask: top.yes_ask,
      spread: top.spread,
      size_at_top: top.yes_bid_contracts,
      ts: ts,
      t_iso: new Date(ts * 1000).toISOString().replace(".000Z", "Z"),
      threshold: tracker.threshold,
      basis: "browser order-book mid",
      basis_url: "https://docs.kalshi.com/getting_started/orderbook_responses",
      market_url: obs.market_url || ("https://kalshi.com/markets/" +
        encodeURIComponent(obs.series_ticker || obs.event_ticker || obs.ticker) +
        "/" + encodeURIComponent(obs.ticker)),
      source_url: REST + "/markets/" + encodeURIComponent(obs.ticker) + "/orderbook",
      origin: "live",
      quality: "executable",
      news_status: "not-checked-in-browser",
      headlines: [],
      model: scoreSwing(obs, top, direction)
    };
  }

  /* The model feed. Same shape and same idea as collector/alerts.py: buy the
   * side that just got cheaper if the reversion edge still clears the official
   * taker fee plus the published net-ROI gate. `model_fair` is the previous
   * mid: the model's only claim is that the quoted price overshot, which is a
   * statement about the book, not a prediction about the underlying event. */
  function scoreSwing(obs, top, direction, gate) {
    var minNet = num(gate);
    if (minNet === null) minNet = MODEL_GATE;
    if (!top || !top.executable) return null;
    var side, price;
    if (direction === "down") {
      /* Price fell: buy YES at the ask. */
      side = "yes"; price = top.yes_ask;
    } else {
      /* Price rose: buy NO at 1 - yes bid. */
      side = "no"; price = top.yes_bid === null ? null : round4(1 - top.yes_bid);
    }
    if (price === null || price === undefined) return null;
    if (price < 0.01 || price > 0.99) return null;
    var fair = direction === "down" ? obs.prevMid : round4(1 - (obs.prevMid === null ? 0 : obs.prevMid));
    if (fair === null || fair === undefined) return null;
    var edge = round4(fair - price);
    var feeUsd = fee(price, 1, obs.fee_multiplier);
    var netRoi = price > 0 ? (edge - feeUsd) / price : 0;
    if (!isFinite(netRoi) || netRoi < minNet) return null;
    /* Spread guard: if the quoted spread already eats the modelled edge, the
     * "trade" cannot be executed at the price that produced it. */
    if (top.spread !== null && top.spread > Math.max(edge, MAX_SPREAD)) return null;
    return {
      side: side,
      executable_price: price,
      model_fair: fair,
      edge: edge,
      fee: feeUsd,
      net_roi: round4(netRoi),
      gate: minNet,
      fee_basis: "M x 0.07 x C x P x (1-P), ceil to the cent",
      fee_url: "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
    };
  }

  /* ------------------------------------------------------------------ */
  /* snapshot parsing                                                    */
  /* ------------------------------------------------------------------ */

  /* Turn the CI snapshot's `events` array into probe observations, so the very
   * first poll only has to fetch books and can already measure a move against
   * the served price instead of waiting for two polls. Only markets whose
   * served quote is two-sided and tight are eligible, for the same reason the
   * order-book path is: a one-sided record is not a price. */
  function observationsFromSnapshot(snapshot) {
    var out = [];
    var events = (snapshot && snapshot.events) || [];
    for (var i = 0; i < events.length; i++) {
      var e = events[i];
      if (!e || !e.ticker) continue;
      var bid = num(e.yes_bid);
      var ask = num(e.yes_ask);
      if (bid === null || ask === null) continue;
      var spread = round4(ask - bid);
      if (!(spread >= 0 && spread < MAX_SPREAD)) continue;
      out.push({
        ticker: e.ticker,
        series_ticker: e.series_ticker || null,
        event_ticker: e.event_ticker || null,
        topic: e.topic || null,
        title: e.title || e.ticker,
        market_url: e.market_url || null,
        prevMid: round4((bid + ask) / 2),
        fee_multiplier: e.fee_multiplier === undefined ? null : e.fee_multiplier,
        top: {
          yes_bid: bid, yes_ask: ask, mid: round4((bid + ask) / 2),
          spread: spread, two_sided: true,
          executable: spread < MAX_SPREAD,
          yes_bid_contracts: num(e.yes_bid_size) || 0,
          no_bid_contracts: 0
        }
      });
    }
    return out;
  }

  /* Pair GET /markets records with GET /markets/orderbooks entries. Both are
   * documented public endpoints; neither needs authentication. */
  function joinBooks(markets, books, topicFor) {
    var out = [];
    var byTicker = {};
    (books || []).forEach(function (row) {
      if (row && row.ticker) byTicker[row.ticker] = row.orderbook || row.orderbook_fp || null;
    });
    (markets || []).forEach(function (m) {
      if (!m || !m.ticker) return;
      var book = byTicker[m.ticker];
      var top = bookTop(book);
      if (!top || top.mid === null) return;
      /* The market record supplies the identity and the fee multiplier input;
       * the book supplies the price. Never mix: a record's last trade or a
       * stale previous_yes_ask is not a current quote. */
      out.push({
        ticker: m.ticker,
        series_ticker: m.series_ticker || (topicFor && topicFor(m)) || null,
        event_ticker: m.event_ticker || null,
        topic: m.topic || (topicFor ? topicFor(m) : null),
        title: m.yes_sub_title || m.title || m.ticker,
        market_url: "https://kalshi.com/markets/" +
          encodeURIComponent(m.event_ticker || m.ticker) + "/" +
          encodeURIComponent(m.ticker),
        fee_multiplier: m.fee_multiplier === undefined ? null : m.fee_multiplier,
        prevMid: top.mid,
        top: top
      });
    });
    return out;
  }

  function chunk(list, size) {
    var out = [];
    for (var i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
    return out;
  }

  /* The two batch endpoints do NOT share a `tickers` serialisation, and the
   * documentation does not say so — this was measured against the live demo
   * host by .github/workflows/probe-live.yml on 2026-11-21:
   *
   *   GET /markets?tickers=A,B            200, 2 records
   *   GET /markets?tickers=A&tickers=B    400 "multiple values for single value
   *                                           parameter 'tickers'"
   *   GET /markets/orderbooks?tickers=A,B            200, 1 entry
   *   GET /markets/orderbooks?tickers=A&tickers=B    200, 2 entries, request order
   *
   * So the listing takes a comma-joined single value and the order-book batch
   * takes repeated parameters. Getting either one wrong fails *silently* as an
   * empty result, which would have looked exactly like "no swings" in the chat.
   * https://docs.kalshi.com/api-reference/market/get-markets
   * https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks */
  function tickersQuery(tickers, style) {
    var list = tickers || [];
    if (style === "comma") {
      return "tickers=" + encodeURIComponent(list.join(","));
    }
    return list.map(function (t) {
      return "tickers=" + encodeURIComponent(t);
    }).join("&");
  }

  /* ------------------------------------------------------------------ */
  /* the poller                                                          */
  /* ------------------------------------------------------------------ */

  /* Build a poller. Nothing happens until start() is called, and every network
   * call is injectable, so the tests exercise real logic with fake I/O.
   *
   *   fetchJson(url)      -> Promise<parsed body>  (rejects on non-2xx)
   *   onAlert(alert)      -> called once per new swing
   *   onStatus(status)    -> {state: ..., detail: ...} for the UI pill
   *   onPoll(summary)     -> bookkeeping for the UI (counts, latency)
   */
  function createPoller(cfg) {
    cfg = cfg || {};
    var fetchJson = cfg.fetchJson;
    if (typeof fetchJson !== "function") throw new Error("fetchJson required");
    var intervalMs = num(cfg.intervalMs) || 5000;
    var timeoutMs = num(cfg.timeoutMs) || 12000;
    var watchlistSize = num(cfg.watchlistSize) || 60;
    var gate = num(cfg.modelGate);
    var tracker = createTracker({ threshold: cfg.threshold });
    var timer = null;
    var inFlight = false;
    var stopped = true;
    var consecutiveErrors = 0;
    var backoff = 1;
    var stats = {
      polls: 0, alerts: 0, indicative: 0, modelHits: 0, markets: 0,
      lastPollMs: null, lastError: null, startedAt: null
    };
    var watch = [];
    var seenIndicative = {};

    function status(state, detail) {
      if (typeof cfg.onStatus === "function") cfg.onStatus({ state: state, detail: detail || null });
    }

    function setWatchlist(list) {
      watch = (list || []).slice(0, watchlistSize);
      return watch.length;
    }

    function withTimeout(promise) {
      return new Promise(function (resolve, reject) {
        var t = setTimeout(function () { reject(new Error("timeout after " + timeoutMs + "ms")); }, timeoutMs);
        promise.then(function (v) { clearTimeout(t); resolve(v); },
                     function (e) { clearTimeout(t); reject(e); });
      });
    }

    /* Fetch every chunk that documents `key`, tolerating a partial failure but
     * never tolerating a total one: if no chunk answered, the poll must surface
     * an error rather than present itself as a healthy poll with 0 markets.
     * (Bug caught by tests: all-fail used to look like "live, 0 books".) */
    function fetchAll(tickers, baseUrl, key, style) {
      var groups = chunk(tickers, MAX_BOOKS);
      var errors = [];
      return Promise.all(groups.map(function (group) {
        var url = baseUrl + "?" + tickersQuery(group, style);
        return withTimeout(fetchJson(url)).then(function (body) {
          if (!body || !Array.isArray(body[key])) {
            errors.push("no " + key + " in response");
            return [];
          }
          return body[key];
        }, function (err) {
          errors.push(String(err && err.message ? err.message : err));
          return [];
        });
      })).then(function (pages) {
        if (groups.length && errors.length === groups.length) {
          throw new Error(errors[0] || "all requests failed");
        }
        var rows = [];
        pages.forEach(function (page) { rows = rows.concat(page); });
        return rows;
      });
    }

    function fetchBooks(tickers) {
      return fetchAll(tickers, ENDPOINTS.orderbooks, "orderbooks", "repeated");
    }

    function fetchMarkets(tickers) {
      /* The listing endpoint takes the comma-joined form; see tickersQuery. */
      return fetchAll(tickers, ENDPOINTS.markets, "markets", "comma");
    }

    function pollOnce() {
      if (inFlight) return Promise.resolve(null);
      if (!watch.length) return Promise.resolve(null);
      inFlight = true;
      var started = Date.now();
      var tickers = watch.map(function (w) { return w.ticker; });
      return Promise.all([fetchMarkets(tickers), fetchBooks(tickers)])
        .then(function (res) {
          var joined = joinBooks(res[0], res[1], function (m) {
            for (var i = 0; i < watch.length; i++) {
              if (watch[i].ticker === m.ticker) return watch[i].topic;
            }
            return null;
          });
          var found = [];
          joined.forEach(function (obs) {
            var alert = observe(tracker, obs, Date.now());
            if (!alert) return;
            if (alert.model) stats.modelHits += 1;
            stats.alerts += 1;
            found.push(alert);
            if (typeof cfg.onAlert === "function") cfg.onAlert(alert);
          });
          /* Indicative moves: a >= $0.10 change on a one-sided or wide book.
           * Reported to the UI once per market+direction so the audit trail is
           * honest without flooding the chat with untradable noise. */
          joined.forEach(function (obs) {
            var row = tracker.peek(obs.ticker);
            if (!row || !obs.top || obs.top.mid === null) return;
            if (obs.top.executable) return;
            var key = obs.ticker + ":" + (obs.top.mid > row.first ? "up" : "down");
            if (seenIndicative[key]) return;
            if (Math.abs(obs.top.mid - row.first) < SWING) return;
            seenIndicative[key] = true;
            stats.indicative += 1;
            if (typeof cfg.onIndicative === "function") {
              cfg.onIndicative({
                ticker: obs.ticker, title: obs.title, topic: obs.topic,
                mid: obs.top.mid, from: row.first,
                yes_bid: obs.top.yes_bid, yes_ask: obs.top.yes_ask,
                spread: obs.top.spread, two_sided: obs.top.two_sided,
                reason: obs.top.two_sided
                  ? "quoted spread " + obs.top.spread.toFixed(4) +
                    " is wider than the $0.10 threshold"
                  : "order book is one-sided",
                ts: Math.floor(Date.now() / 1000),
                market_url: obs.market_url
              });
            }
          });
          stats.polls += 1;
          stats.markets = joined.length;
          stats.lastPollMs = Date.now() - started;
          stats.lastError = null;
          consecutiveErrors = 0;
          backoff = 1;
          status("live", joined.length + " books");
          if (typeof cfg.onPoll === "function") {
            cfg.onPoll({ at: Date.now(), markets: joined.length, alerts: found.length, stats: stats });
          }
          return found;
        })
        .catch(function (err) {
          stats.lastError = String(err && err.message ? err.message : err);
          consecutiveErrors += 1;
          /* Documented behaviour: back off on failures rather than hammering a
           * public endpoint. 5s, 10s, 20s, capped at 60s. */
          backoff = Math.min(12, Math.pow(2, Math.min(consecutiveErrors - 1, 3)));
          status("error", stats.lastError);
          return [];
        })
        .then(function (out) {
          inFlight = false;
          return out;
        });
    }

    function schedule() {
      if (stopped) return;
      var wait = intervalMs * backoff;
      timer = setTimeout(function () {
        pollOnce().then(function () {
          schedule();
        });
      }, wait);
    }

    return {
      tracker: tracker,
      stats: stats,
      endpoints: ENDPOINTS,
      setWatchlist: setWatchlist,
      watchlist: function () { return watch.slice(); },
      pollOnce: pollOnce,
      start: function () {
        if (!stopped) return;
        stopped = false;
        stats.startedAt = Date.now();
        status("connecting", null);
        pollOnce().then(function () { schedule(); });
      },
      stop: function () {
        stopped = true;
        if (timer) clearTimeout(timer);
        timer = null;
      },
      isRunning: function () { return !stopped; },
      fee: fee,
      bookTop: bookTop,
      tickersQuery: tickersQuery,
      observationsFromSnapshot: observationsFromSnapshot,
      joinBooks: joinBooks,
      createTracker: createTracker,
      observe: observe,
      scoreSwing: scoreSwing,
      SWING: SWING,
      MAX_SPREAD: MAX_SPREAD,
      MODEL_GATE: MODEL_GATE,
      REST: REST
    };
  }

  return {
    createPoller: createPoller,
    createTracker: createTracker,
    observe: observe,
    scoreSwing: scoreSwing,
    bookTop: bookTop,
    bestBid: bestBid,
    joinBooks: joinBooks,
    observationsFromSnapshot: observationsFromSnapshot,
    tickersQuery: tickersQuery,
    fee: fee,
    round4: round4,
    ENDPOINTS: ENDPOINTS,
    REST: REST,
    SWING: SWING,
    MAX_SPREAD: MAX_SPREAD,
    MODEL_GATE: MODEL_GATE
  };
});
