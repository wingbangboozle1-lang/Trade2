/* Unit tests for assets/live-feed.js (the browser live detector).
 *
 * Every expected value here is derived from the OFFICIAL documented rules:
 *   - order book semantics (best bid is the LAST element; implied YES ask =
 *     1 - best NO bid; bids only):
 *     https://docs.kalshi.com/getting_started/orderbook_responses
 *   - the project's own $0.10 threshold and quote-integrity rule, which this
 *     module must mirror exactly (collector/alerts.py).
 *
 * Run: node --test test/live-feed.test.mjs
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const LiveFeed = require("../assets/live-feed.js");

/* A book shaped exactly like GET /markets/orderbooks returns:
 * orderbook_fp.{yes_dollars,no_dollars}, ascending, [price, contracts]. */
function book(yesLevels, noLevels) {
  return { orderbook_fp: { yes_dollars: yesLevels, no_dollars: noLevels } };
}

const CENTS = (n) => n.toFixed(4);

test("best bid is the LAST level, per the documented ordering", () => {
  const b = book([["0.0100", "5"], ["0.0300", "7"], ["0.0500", "9"]], []);
  const q = LiveFeed.quoteFromBook(b);
  assert.equal(q.yes_bid, 0.05);
});

test("implied YES ask is 1.00 - best NO bid", () => {
  const b = book([["0.0300", "7"]], [["0.9400", "11"]]);
  const q = LiveFeed.quoteFromBook(b);
  assert.equal(q.no_bid, 0.94);
  assert.equal(q.yes_ask, 0.06);
  assert.equal(q.mid, 0.045); // (0.03 + 0.06) / 2
  assert.equal(q.spread, 0.03);
});

test("One documented market, verified live 2026-11-21 06:44Z", () => {
  /* GET /trade-api/v2/markets/KXPRESNOMD-28-RW/orderbook?depth=10 returned
   * yes_dollars last = ["0.0380","13869.69"] and no_dollars last =
   * ["0.9610","423.25"]; the market record said yes_bid 0.0380 / yes_ask
   * 0.0390. Both endpoints must agree through this function. */
  const b = book(
    [["0.0010", "100.00"], ["0.0100", "32.10"], ["0.0370", "18018.00"], ["0.0380", "13869.69"]],
    [["0.1960", "321.57"], ["0.9600", "20833.30"], ["0.9610", "423.25"]]
  );
  const q = LiveFeed.quoteFromBook(b);
  assert.equal(q.yes_bid, 0.038);
  assert.equal(q.no_bid, 0.961);
  assert.equal(q.yes_ask, 0.039); // published yes_ask_dollars
  assert.equal(q.mid, 0.0385);
  assert.equal(q.spread, 0.001); // published spread 0.001
});

test("an empty book is not a price (never the phantom 0.50)", () => {
  const q = LiveFeed.quoteFromBook(book([], []));
  assert.equal(q.yes_bid, null);
  assert.equal(q.yes_ask, null);
  assert.equal(q.mid, null);
  assert.equal(q.spread, null);
});

test("a 0.0000 / 1.0000 record pair is not a price", () => {
  /* Same guard as collector/alerts.py:observe(); KXAAAGASM-26NOV30-4.70 and
   * KXAAAGASM-26NOV30-4.50 publish exactly this pair with no book at all. */
  const q = LiveFeed.quoteFromBook(
    book([["0.0000", "0"]], [["0.0000", "0"]])
  );
  assert.equal(q.mid, null);
});

test("one-sided quotes are refused by quotesOk", () => {
  assert.equal(LiveFeed.quotesOk({ yes_bid: 0.02, yes_ask: null, spread: null }), false);
  assert.equal(LiveFeed.quotesOk({ yes_bid: null, yes_ask: 0.9, spread: null }), false);
});

test("quotesOk is STRICT below $0.10, matching the collector", () => {
  assert.equal(LiveFeed.quotesOk({ yes_bid: 0.0, yes_ask: 0.0999, spread: 0.0999 }), true);
  assert.equal(LiveFeed.quotesOk({ yes_bid: 0.0, yes_ask: 0.1, spread: 0.1 }), false);
  assert.equal(LiveFeed.quotesOk({ yes_bid: 0.0, yes_ask: 0.2, spread: 0.2 }), false);
});

test("the threshold is exactly $0.10 and fires at, not below, it", () => {
  assert.equal(LiveFeed.SWING, 0.1);
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "golf", title: "Test", market_url: "https://kalshi.com/markets/KXPGATOUR/T" };
  d.ingest({ T: { meta, quote: { yes_bid: 0.1, yes_ask: 0.12, mid: 0.11, spread: 0.02, no_bid_size: 10, yes_bid_size: 10 } } }, t0);
  // +0.09 -> no alert
  let r = d.ingest({ T: { meta, quote: { yes_bid: 0.19, yes_ask: 0.21, mid: 0.2, spread: 0.02, no_bid_size: 10, yes_bid_size: 10 } } }, t0 + 60_000);
  assert.equal(r.fired.length, 0);
  // +0.01 more (total 0.10 from 0.19 baseline? no: baseline advanced) -> use exact 0.10
  r = d.ingest({ T: { meta, quote: { yes_bid: 0.29, yes_ask: 0.31, mid: 0.3, spread: 0.02, no_bid_size: 10, yes_bid_size: 10 } } }, t0 + 120_000);
  assert.equal(r.fired.length, 1, "a further $0.10 from the advanced baseline must fire");
  assert.ok(Math.abs(r.fired[0].abs_delta - 0.1) < 1e-9);
});

test("first sighting is a baseline, never an alert", () => {
  const d = LiveFeed.newDetector();
  const r = d.ingest(
    { T: { meta: { topic: "crypto" }, quote: { yes_bid: 0.4, yes_ask: 0.42, mid: 0.41, spread: 0.02 } } },
    Date.now()
  );
  assert.equal(r.fired.length, 0);
  assert.equal(d.last().T.mid, 0.41);
});

test("a sustained move does not re-fire on the next refresh", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "crypto", title: "BTC" };
  d.ingest({ B: { meta, quote: { yes_bid: 0.4, yes_ask: 0.42, mid: 0.41, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0);
  const r1 = d.ingest({ B: { meta, quote: { yes_bid: 0.55, yes_ask: 0.57, mid: 0.56, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0 + 15_000);
  assert.equal(r1.fired.length, 1);
  const r2 = d.ingest({ B: { meta, quote: { yes_bid: 0.55, yes_ask: 0.57, mid: 0.56, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0 + 30_000);
  assert.equal(r2.fired.length, 0, "same price must not alert twice");
});

test("a reversal fires immediately", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "elections", title: "X" };
  const q = (b) => ({ yes_bid: b, yes_ask: b + 0.02, mid: b + 0.01, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 });
  d.ingest({ E: { meta, quote: q(0.1) } }, t0);
  assert.equal(d.ingest({ E: { meta, quote: q(0.3) } }, t0 + 15_000).fired.length, 1);
  assert.equal(d.ingest({ E: { meta, quote: q(0.5) } }, t0 + 30_000).fired.length, 1, "a second +0.20 up step");
  const down = d.ingest({ E: { meta, quote: q(0.3) } }, t0 + 45_000);
  assert.equal(down.fired.length, 1);
  assert.equal(down.fired[0].direction, "down");
});

test("a wide-spread step is reported as suppressed, not as an alert", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "culture", title: "Y" };
  d.ingest({ C: { meta, quote: { yes_bid: 0.4, yes_ask: 0.42, mid: 0.41, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0);
  /* Current spread 0.30 (>= threshold) with a >= $0.10 mid move: refused. */
  const r = d.ingest({ C: { meta, quote: { yes_bid: 0.1, yes_ask: 0.4, mid: 0.25, spread: 0.3, no_bid_size: 5, yes_bid_size: 5 } } }, t0 + 15_000);
  assert.equal(r.fired.length, 0);
  assert.equal(r.suppressed.length, 1);
  assert.match(r.suppressed[0].reason, /not tighter than the \$0\.10 alert threshold/);
});

test("a move whose reference was one-sided is suppressed with that reason", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "gas-prices", title: "Z" };
  d.ingest({ G: { meta, quote: { yes_bid: 0.02, yes_ask: null, mid: 0.02, spread: null, no_bid_size: null, yes_bid_size: 5 } } }, t0);
  const r = d.ingest({ G: { meta, quote: { yes_bid: 0.2, yes_ask: 0.22, mid: 0.21, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0 + 15_000);
  assert.equal(r.fired.length, 0);
  assert.equal(r.suppressed.length, 1);
  assert.match(r.suppressed[0].reason, /reference book is missing or wider/);
});

test("no size at the level makes the row indicative, and it is also reported", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "golf", title: "W" };
  d.ingest({ T: { meta, quote: { yes_bid: 0.1, yes_ask: 0.12, mid: 0.11, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0);
  const r = d.ingest({ T: { meta, quote: { yes_bid: 0.3, yes_ask: 0.32, mid: 0.31, spread: 0.02, no_bid_size: 0, yes_bid_size: 5 } } }, t0 + 15_000);
  assert.equal(r.fired.length, 1);
  assert.equal(r.fired[0].quality, "indicative");
  assert.equal(r.fired[0].indicative, true);
});

test("a repeat inside the cooldown is tagged, never dropped", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = { topic: "crypto", title: "R" };
  const q = (b) => ({ yes_bid: b, yes_ask: b + 0.02, mid: b + 0.01, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 });
  d.ingest({ T: { meta, quote: q(0.1) } }, t0);
  const r1 = d.ingest({ T: { meta, quote: q(0.3) } }, t0 + 10_000);
  const r2 = d.ingest({ T: { meta, quote: q(0.5) } }, t0 + 20_000);
  assert.equal(r1.fired[0].live_repeat, false);
  assert.equal(r2.fired[0].live_repeat, true);
  assert.equal(d.events().length, 2, "nothing is deleted");
});

test("a book that loses its quote is reported, not silently dropped", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  d.ingest({ T: { meta: { topic: "elections" }, quote: { yes_bid: 0.3, yes_ask: 0.32, mid: 0.31, spread: 0.02 } } }, t0);
  const r = d.ingest({ T: { meta: { topic: "elections" }, quote: LiveFeed.quoteFromBook(book([], [])) } }, t0 + 15_000);
  assert.equal(r.suppressed.length, 1);
  assert.match(r.suppressed[0].reason, /no longer carries a two-sided quote/);
});

test("every emitted alert carries the fields the chat renderer reads", () => {
  const d = LiveFeed.newDetector();
  const t0 = 1_795_000_000_000;
  const meta = {
    topic: "golf", title: "T", series_ticker: "KXPGATOUR",
    event_ticker: "KXPGATOUR-X", market_url: "https://kalshi.com/markets/KXPGATOUR/T",
  };
  d.ingest({ T: { meta, quote: { yes_bid: 0.1, yes_ask: 0.12, mid: 0.11, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0);
  const row = d.ingest({ T: { meta, quote: { yes_bid: 0.4, yes_ask: 0.42, mid: 0.41, spread: 0.02, no_bid_size: 5, yes_bid_size: 5 } } }, t0 + 15_000).fired[0];
  for (const k of ["ticker", "title", "topic", "iso", "ts", "direction", "previous",
    "current", "abs_delta", "yes_bid", "yes_ask", "spread", "quality",
    "reference_basis", "market_url", "series_ticker", "event_ticker"]) {
    assert.ok(row[k] !== undefined, `missing ${k}`);
  }
  assert.equal(row.source, "live");
  assert.deepEqual(row.news, []);
});

test("the detector never mutates the market metadata it is given", () => {
  const d = LiveFeed.newDetector();
  const meta = Object.freeze({ topic: "crypto", title: "F" });
  d.ingest({ T: { meta, quote: { yes_bid: 0.1, yes_ask: 0.12, mid: 0.11, spread: 0.02 } } }, 1_795_000_000_000);
  d.ingest({ T: { meta, quote: { yes_bid: 0.3, yes_ask: 0.32, mid: 0.31, spread: 0.02 } } }, 1_795_000_015_000);
});
