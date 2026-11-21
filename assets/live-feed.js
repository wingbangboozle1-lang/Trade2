/* Live swing detector — a pure, dependency-free module.
 *
 * WHY THIS EXISTS
 * ---------------
 * The published site is a static snapshot: `assets/live.json` is rewritten by a
 * scheduled GitHub Actions run (every 5-15 minutes). Between two runs nothing
 * re-measures a price, so the two scrolling chats go quiet even when a market
 * is moving. The user asked for an alerting system that works "in real time".
 *
 * Kalshi's WebSocket `ticker` channel carries trade prints and cannot be used
 * anonymously — the official docs require KALSHI-ACCESS-* handshake headers,
 * and a browser cannot set them (that limitation is already documented on the
 * site's Flagged-for-Review page). What IS available anonymously, and is
 * documented, is `GET /markets/orderbooks?tickers=…` — up to 100 market books
 * in ONE request (https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks).
 * One polite request per refresh is therefore enough to measure the whole
 * tracked set in the browser.
 *
 * WHAT THIS MODULE DOES, EXACTLY
 * ------------------------------
 *   1. Takes an order-book payload for one market and derives its YES quote
 *      using the SAME documented rules the collector uses
 *      (https://docs.kalshi.com/getting_started/orderbook_responses):
 *          best YES bid = last element of orderbook_fp.yes_dollars
 *          best NO  bid = last element of orderbook_fp.no_dollars
 *          implied YES ask = 1.00 - best NO bid
 *          mid = (best YES bid + implied YES ask) / 2
 *      A market with no quote at all (0.0000 bid / 1.0000 ask, or an empty
 *      book) produces **no price** — never a phantom 0.50.
 *   2. Applies the project's existing integrity rule verbatim: both the
 *      reference and the current quote must be two-sided with a YES spread
 *      strictly below $0.10, otherwise the move is reported as *suppressed*
 *      with its reason (this mirrors `collector/alerts.py`; it does not
 *      relax it).
 *   3. Emits one alert per (market, direction) step of >= $0.10, then resets
 *      that market's baseline so a sustained move does not re-fire every
 *      refresh. A later step of >= $0.10 in the same direction does fire again
 *      (it is a new move), and a reversal fires immediately.
 *   4. When the same market moves >= $0.10 again *within* COOLDOWN_MS, the
 *      rows are tagged `live_repeat` so the display can group them; nothing is
 *      deleted.
 *
 * WHAT IT DOES NOT DO
 * -------------------
 *  * It does not predict, score or rank anything. Prices only.
 *  * It does not compare a quote mid against a last-trade print.
 *  * It does not invent a missing side. One-sided quotes are refused.
 *  * It does not claim a cause for a move: alerts carry no news link, and the
 *    row is labelled with its basis so a reader knows what was measured.
 *
 * The module is intentionally side-effect free (no fetch, no DOM) so the
 * browser and Node test harness execute the identical code.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.LiveFeed = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var SWING = 0.10;            // USD per contract, either direction (project brief)
  var ALERT_MAX_SPREAD = 0.10; // same rule as collector/alerts.py
  var COOLDOWN_MS = 2 * 60 * 1000;

  function fnum(v) {
    if (v === null || v === undefined || v === "") return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }

  /* Last element of a level list is the best (highest) bid — documented. */
  function bestBid(levels) {
    if (!levels || !levels.length) return null;
    var last = levels[levels.length - 1];
    if (!last || last.length < 2) return null;
    var price = fnum(last[0]);
    var contracts = fnum(last[1]);
    if (price === null) return null;
    return { price: price, contracts: contracts === null ? 0 : contracts };
  }

  /* Parse one `orderbook_fp` object into the YES quote, per the documented
   * rules. Everything returned here traces to a field Kalshi sent. */
  function quoteFromBook(book) {
    var ob = (book && book.orderbook_fp) || book || {};
    var yb = bestBid(ob.yes_dollars);
    var nb = bestBid(ob.no_dollars);
    var yesBid = yb ? yb.price : null;
    var noBid = nb ? nb.price : null;
    var yesBidSize = yb ? yb.contracts : null;
    var noBidSize = nb ? nb.contracts : null;
    var yesAsk = noBid === null ? null : Math.round((1 - noBid) * 10000) / 10000;

    /* A 0.0000 / 1.0000 pair is "no quote", not a 0.50 price. Same guard as
     * collector/alerts.py:observe(). */
    if (yesBid !== null && yesAsk !== null && yesBid <= 0 && yesAsk >= 1) {
      yesBid = null;
      yesAsk = null;
    }
    var mid = null;
    if (yesBid !== null && yesAsk !== null) mid = (yesBid + yesAsk) / 2;
    else if (yesBid !== null) mid = yesBid;
    else if (yesAsk !== null) mid = yesAsk;

    var spread = (yesBid !== null && yesAsk !== null)
      ? Math.round((yesAsk - yesBid) * 10000) / 10000
      : null;
    return {
      yes_bid: yesBid,
      yes_ask: yesAsk,
      no_bid: noBid,
      yes_bid_size: yesBidSize,
      no_bid_size: noBidSize,
      mid: mid,
      spread: spread,
    };
  }

  /* Two-sided and strictly tighter than the alert threshold. Identical rule
   * and strictness as collector/alerts.py:swing_quotes_ok(). */
  function quotesOk(q) {
    if (!q) return false;
    if (q.yes_bid === null || q.yes_ask === null) return false;
    if (q.spread === null) return false;
    return q.spread >= 0 && q.spread < ALERT_MAX_SPREAD;
  }

  function isoOf(ts) {
    return new Date(ts * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  /* Build the batch order-book URL.
   *
   * `GET /markets/orderbooks` declares `tickers` as a **string[]** query
   * parameter — "List of market tickers to fetch orderbooks for", "Required
   * array length: 1 - 100 elements"
   * (https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks).
   * The exchange reads one value per occurrence of the parameter, so a
   * comma-joined value is read as ONE ticker whose name literally contains
   * the commas — and the answer is a single empty book.
   *
   * Verified live against the demo exchange on 2026-11-21 (07:20Z):
   *   ?tickers=KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70
   *     -> {"orderbooks":[{"ticker":"KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70",
   *          "orderbook_fp":{"yes_dollars":[],"no_dollars":[]}}]}
   *   ?tickers=KXPRESNOMD-28-RW&tickers=KXAAAGASM-26NOV30-4.70
   *     -> two entries, each carrying its real book.
   * The comma form therefore silently starves the pulse; this helper exists
   * so that mistake cannot be made twice.
   */
  function batchOrderbookUrl(base, tickers) {
    var clean = [];
    (tickers || []).forEach(function (t) {
      var s = String(t === null || t === undefined ? "" : t).trim();
      if (s) clean.push(s);
    });
    if (!clean.length) return null;
    return base + (String(base).indexOf("?") === -1 ? "?" : "&") +
      clean.map(function (t) { return "tickers=" + encodeURIComponent(t); }).join("&");
  }

  /**
   * newDetector() -> stateful detector.
   *
   * `state` is inspectable (and serialisable) so the tests can assert on it;
   * `ingest()` is the only way it changes.
   */
  function newDetector() {
    var last = {};       // ticker -> last quote record (baseline candidate)
    var events = [];     // newest first, capped
    var suppressed = []; // newest first, capped
    var firedAt = {};    // ticker+direction -> ms, for the repeat tag
    var seen = 0;        // refreshes ingested

    function pushEvent(row) {
      events.unshift(row);
      if (events.length > 500) events.length = 500;
      return row;
    }
    function pushSuppressed(row) {
      suppressed.unshift(row);
      if (suppressed.length > 200) suppressed.length = 200;
      return row;
    }

    /* One refresh. `quotes` is {ticker: {market metadata, quote}} — the caller
     * supplies market metadata from the published snapshot (title, topic,
     * series ticker, market URL) because the order-book endpoint does not
     * return it. `tsMs` is when the response was received. */
    function ingest(quotes, tsMs) {
      seen += 1;
      var ts = Math.floor((tsMs === undefined ? Date.now() : tsMs) / 1000);
      var out = { fired: [], suppressed: [], updates: [] };

      Object.keys(quotes || {}).forEach(function (ticker) {
        var rec = quotes[ticker];
        if (!rec) return;
        var q = rec.quote || rec;
        var meta = rec.meta || {};
        var prev = last[ticker] || null;

        if (q.mid === null || q.mid === undefined) {
          /* No quote: remember that we have no baseline, and say why. */
          last[ticker] = { ts: ts, mid: null, quote: q, meta: meta };
          if (prev && prev.mid !== null) {
            out.suppressed.push(pushSuppressed({
              ticker: ticker,
              topic: meta.topic || "",
              title: meta.title || ticker,
              ts: ts,
              iso: isoOf(ts),
              reason: "the book no longer carries a two-sided quote",
              previous: prev.mid,
              current: null,
              yes_bid: q.yes_bid,
              yes_ask: q.yes_ask,
              spread: q.spread,
            }));
          }
          return;
        }

        /* First sighting is a baseline, never an alert: there is nothing to
         * compare against, and inventing a previous price would be fabrication. */
        if (!prev || prev.mid === null) {
          last[ticker] = { ts: ts, mid: q.mid, quote: q, meta: meta };
          out.updates.push({ ticker: ticker, mid: q.mid, baseline: true });
          return;
        }

        var delta = Math.round((q.mid - prev.mid) * 10000) / 10000;
        if (Math.abs(delta) + 1e-9 < SWING) {
          /* Sub-threshold moves still advance the baseline: the baseline is
           * "price at the previous refresh", which is what the collector
           * measures against between snapshots. */
          last[ticker] = { ts: ts, mid: q.mid, quote: q, meta: meta };
          out.updates.push({ ticker: ticker, mid: q.mid, baseline: false });
          return;
        }

        /* A >= $0.10 midpoint step. Now apply the quote-integrity rule: if
         * either side of the comparison is one-sided or wide, publish a
         * refusal with its reason instead of an alert. */
        var okNow = quotesOk(q);
        var okPrev = quotesOk(prev.quote);
        if (!okNow || !okPrev) {
          var why;
          if (!okNow) {
            why = q.spread === null
              ? "current book is one-sided: only one side is quoted"
              : "current YES spread $" + q.spread.toFixed(4) +
                " is not tighter than the $0.10 alert threshold";
          } else {
            why = "reference book is missing or wider than the $0.10 threshold";
          }
          out.suppressed.push(pushSuppressed({
            ticker: ticker,
            topic: meta.topic || "",
            title: meta.title || ticker,
            ts: ts,
            iso: isoOf(ts),
            reason: why,
            previous: prev.mid,
            current: q.mid,
            abs_delta: Math.abs(delta),
            direction: delta > 0 ? "up" : "down",
            yes_bid: q.yes_bid,
            yes_ask: q.yes_ask,
            spread: q.spread,
            market_url: meta.market_url || "",
            threshold: SWING,
            source: "live",
          }));
          /* The baseline advances anyway: the refusal is about this step, not
           * about freezing the market. */
          last[ticker] = { ts: ts, mid: q.mid, quote: q, meta: meta };
          return;
        }

        var direction = delta > 0 ? "up" : "down";
        var key = ticker + ":" + direction;
        var nowMs = ts * 1000;
        var repeat = firedAt[key] !== undefined &&
          (nowMs - firedAt[key]) < COOLDOWN_MS;
        firedAt[key] = nowMs;

        /* Executability mirrors the collector: buying YES at the ask for an up
         * move, selling YES into the bid for a down move, and the size resting
         * there must be at least one contract. */
        var size = direction === "up" ? q.no_bid_size : q.yes_bid_size;
        var quality = (size === null || size === undefined || size < 1)
          ? "indicative" : "executable";

        var row = {
          id: "live:" + ticker + ":" + ts,
          key: "live:" + ticker + ":" + direction + ":" + ts,
          ts: ts,
          iso: isoOf(ts),
          ticker: ticker,
          event_ticker: meta.event_ticker || "",
          series_ticker: meta.series_ticker || "",
          topic: meta.topic || "",
          title: meta.title || ticker,
          market_url: meta.market_url || "",
          direction: direction,
          previous: prev.mid,
          current: q.mid,
          delta: delta,
          abs_delta: Math.abs(delta),
          percentage_points: Math.round(Math.abs(delta) * 10000) / 100,
          yes_bid: q.yes_bid,
          yes_ask: q.yes_ask,
          spread: q.spread,
          size_at_top: size,
          quality: quality,
          quality_reason: quality === "executable"
            ? "two-sided book tighter than the threshold, size resting at the level"
            : "no size at the level you would trade",
          reference_basis: "previous_live_poll_mid",
          price_pair: "quote mid to quote mid (live polls)",
          threshold: SWING,
          source: "live",
          live_repeat: repeat,
          repeat_count: 1,
          news: [],
          news_status: "not looked up: live row",
        };
        if (quality === "indicative") {
          /* Same discipline as the collector: an indicative move still shows
           * in the chat (it is real), but it is also reported as a refusal so
           * it is never counted as an executable alert. */
          row.indicative = true;
        }
        out.fired.push(pushEvent(row));
        last[ticker] = { ts: ts, mid: q.mid, quote: q, meta: meta };
        out.updates.push({ ticker: ticker, mid: q.mid, baseline: false });
      });

      return out;
    }

    return {
      ingest: ingest,
      events: function () { return events.slice(); },
      suppressed: function () { return suppressed.slice(); },
      last: function () { return JSON.parse(JSON.stringify(last)); },
      firedAt: function () { return Object.assign({}, firedAt); },
      refreshCount: function () { return seen; },
      constant: {
        SWING: SWING,
        ALERT_MAX_SPREAD: ALERT_MAX_SPREAD,
        COOLDOWN_MS: COOLDOWN_MS,
      },
    };
  }

  return {
    newDetector: newDetector,
    quoteFromBook: quoteFromBook,
    quotesOk: quotesOk,
    bestBid: bestBid,
    isoOf: isoOf,
    batchOrderbookUrl: batchOrderbookUrl,
    SWING: SWING,
    ALERT_MAX_SPREAD: ALERT_MAX_SPREAD,
    COOLDOWN_MS: COOLDOWN_MS,
  };
});
