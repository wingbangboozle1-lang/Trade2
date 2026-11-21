#!/usr/bin/env node
/* Tests for assets/live-probe.js — the browser-side swing detector.
 *
 * Runs with no dependencies:  node test/live-probe.test.mjs
 * Exits non-zero on the first failure, so `python3 -m unittest` can shell out
 * to it (tests/test_live_probe.py) and CI can run it on its own.
 *
 * Every assertion below is about a rule that is checkable against official
 * Kalshi documentation; the doc URL is quoted next to each group.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const L = require(path.join(ROOT, "assets", "live-probe.js"));

let passed = 0;
const failures = [];
function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (err) {
    failures.push({ name, err });
  }
}
async function testAsync(name, fn) {
  try {
    await fn();
    passed += 1;
  } catch (err) {
    failures.push({ name, err });
  }
}

/* ------------------------------------------------------------------ */
/* order book conventions                                              */
/* docs.kalshi.com/getting_started/orderbook_responses                 */
/*   "Arrays are sorted by price in ascending order. The highest bid   */
/*    (best bid) is the last element in each array."                   */
/* ------------------------------------------------------------------ */

test("bestBid takes the LAST element, not the first", () => {
  const b = L.bestBid([["0.0100", "200.00"], ["0.1500", "100.00"], ["0.4200", "13.00"]]);
  assert.equal(b.price, 0.42);
  assert.equal(b.contracts, 13);
});

test("bestBid survives an empty book", () => {
  assert.equal(L.bestBid([]), null);
  assert.equal(L.bestBid(null), null);
});

test("bookTop derives the implied YES ask from the best NO bid", () => {
  /* Doc example: YES bids up to 0.42, NO bids up to 0.56 ->
   * best YES bid 0.42, implied YES ask 1 - 0.56 = 0.44, spread 0.02. */
  const top = L.bookTop({
    yes_dollars: [["0.0100", "200.00"], ["0.4200", "13.00"]],
    no_dollars: [["0.0100", "100.00"], ["0.5600", "17.00"]]
  });
  assert.equal(top.yes_bid, 0.42);
  assert.equal(top.yes_ask, 0.44);
  assert.equal(top.spread, 0.02);
  assert.equal(top.mid, 0.43);
  assert.equal(top.two_sided, true);
  assert.equal(top.executable, true);
});

test("bookTop marks a one-sided book as not executable", () => {
  const top = L.bookTop({ yes_dollars: [], no_dollars: [["0.5600", "17.00"]] });
  assert.equal(top.two_sided, false);
  assert.equal(top.executable, false);
});

test("bookTop refuses an 88-cent spread (the BOBA phantom)", () => {
  /* The published record for KXPRESNOMD-28-BOBA on 2026-11-21 was
   * yes_bid 0.0010 / yes_ask 0.8860. No two-sided market; must not alert. */
  const top = L.bookTop({
    yes_dollars: [["0.0010", "20.00"]],
    no_dollars: [["0.1140", "10.00"]]
  });
  assert.equal(top.yes_bid, 0.001);
  assert.equal(top.yes_ask, 0.886);
  assert.equal(top.spread, 0.885);
  assert.equal(top.executable, false);
});

/* ------------------------------------------------------------------ */
/* swing threshold                                                     */
/* ------------------------------------------------------------------ */

test("a move of exactly $0.10 fires (>=, not >)", () => {
  const t = L.createTracker({ threshold: 0.1 });
  const obs = (mid) => ({ mid: Math.fround(mid),
    ticker: "T", top: { mid, two_sided: true, executable: true, spread: 0.01,
                        yes_bid: mid - 0.005, yes_ask: mid + 0.005 }
  });
  assert.equal(L.observe(t, obs(0.40), 1000), null);
  const a = L.observe(t, obs(0.50), 2000);
  assert.ok(a, "expected an alert at exactly 10 cents");
  assert.equal(a.direction, "up");
  assert.equal(a.abs_delta, 0.1);
  assert.equal(a.from, 0.4);
  assert.equal(a.to, 0.5);
});

test("a move of $0.0999 does not fire", () => {
  const t = L.createTracker({ threshold: 0.1 });
  const obs = (mid) => ({ mid: Math.fround(mid),
    ticker: "T", top: { mid, two_sided: true, executable: true, spread: 0.01 }
  });
  L.observe(t, obs(0.4), 1000);
  assert.equal(L.observe(t, obs(0.4999), 2000), null);
});

test("downward moves fire too, and are labelled down", () => {
  const t = L.createTracker({ threshold: 0.1 });
  const obs = (mid) => ({ mid: Math.fround(mid),
    ticker: "T", top: { mid, two_sided: true, executable: true, spread: 0.01 }
  });
  L.observe(t, obs(0.6), 1000);
  const a = L.observe(t, obs(0.45), 2000);
  assert.equal(a.direction, "down");
  assert.equal(a.abs_delta, 0.15);
});

test("a slow drift alerts once, not on every tick", () => {
  const t = L.createTracker({ threshold: 0.1 });
  const obs = (mid) => ({ mid: Math.fround(mid),
    ticker: "T", top: { mid, two_sided: true, executable: true, spread: 0.01 }
  });
  L.observe(t, obs(0.50), 1000);
  const fired = [0.55, 0.60, 0.61, 0.62, 0.70, 0.75]
    .map((m, i) => L.observe(t, obs(m), 2000 + i))
    .filter(Boolean);
  assert.equal(fired.length, 2, "0.50->0.60 and 0.60->0.70 only");
  assert.deepEqual(fired.map((f) => f.to), [0.6, 0.7]);
});

test("a retracement in the other direction is its own row", () => {
  const t = L.createTracker({ threshold: 0.1 });
  const obs = (mid) => ({ mid: Math.fround(mid),
    ticker: "T", top: { mid, two_sided: true, executable: true, spread: 0.01 }
  });
  L.observe(t, obs(0.50), 1000);
  assert.equal(L.observe(t, obs(0.65), 2000).direction, "up");
  assert.equal(L.observe(t, obs(0.52), 3000).direction, "down");
});

test("a one-sided book never produces a tradable alert", () => {
  const t = L.createTracker({ threshold: 0.1 });
  L.observe(t, { ticker: "T", top: { mid: 0.2, two_sided: true, executable: true, spread: 0.01 } }, 1000);
  assert.equal(L.observe(t, { ticker: "T", top: { mid: 0.9, two_sided: false, executable: false } }, 2000), null);
});

test("alerts carry the fields the renderers and the ledger expect", () => {
  const t = L.createTracker({ threshold: 0.1 });
  L.observe(t, { ticker: "KXAAAGASM-26NOV30-4.70", series_ticker: "KXAAAGASM",
                 event_ticker: "KXAAAGASM-26NOV30", topic: "gas-prices",
                 title: "Above 4.70",
                 top: { mid: 0.2, two_sided: true, executable: true, spread: 0.01,
                        yes_bid: 0.195, yes_ask: 0.205, yes_bid_contracts: 100 } }, 1000);
  const a = L.observe(t, { ticker: "KXAAAGASM-26NOV30-4.70", series_ticker: "KXAAAGASM",
                            event_ticker: "KXAAAGASM-26NOV30", topic: "gas-prices",
                            title: "Above 4.70",
                            top: { mid: 0.35, two_sided: true, executable: true, spread: 0.01,
                                   yes_bid: 0.345, yes_ask: 0.355, yes_bid_contracts: 100 } }, 2000);
  for (const key of ["id", "ticker", "topic", "title", "direction", "from", "to",
                     "delta", "abs_delta", "ts", "t_iso", "threshold", "basis",
                     "market_url", "source_url", "origin", "quality"]) {
    assert.ok(key in a, "missing " + key);
  }
  assert.equal(a.origin, "live");
  assert.equal(a.quality, "executable");
  assert.match(a.source_url, /^https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets\//);
  assert.match(a.t_iso, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
});

/* ------------------------------------------------------------------ */
/* published fee schedule                                              */
/* kalshi.com/docs/kalshi-fee-schedule.pdf                             */
/*   fees = M x 0.07 x C x P x (1 - P), rounded up to the next cent    */
/* ------------------------------------------------------------------ */

test("fee reproduces the published table rows", () => {
  /* Rows quoted in the fee schedule for M=1, C=100: */
  assert.equal(L.fee(0.5, 100, 1), 1.75);
  assert.equal(L.fee(0.1, 100, 1), 0.63);
  assert.equal(L.fee(0.9, 100, 1), 0.63);
  assert.equal(L.fee(0.01, 100, 1), 0.07);
  assert.equal(L.fee(0.99, 100, 1), 0.07);
});

test("tickersQuery repeats the parameter, never comma-joins", () => {
  assert.equal(L.tickersQuery(["A", "B"]), "tickers=A&tickers=B");
  assert.equal(L.tickersQuery(["KX-ONE"]), "tickers=KX-ONE");
  assert.equal(L.tickersQuery(["A B"]), "tickers=A%20B");
});

test("fee is zero for a zero multiplier and for off-grid prices", () => {
  assert.equal(L.fee(0.5, 1, 0), 0);
  assert.equal(L.fee(0, 1, 1), 0);
  assert.equal(L.fee(1, 1, 1), 0);
  assert.equal(L.fee(0.5, 0, 1), 0);
});

/* ------------------------------------------------------------------ */
/* model gate                                                          */
/* ------------------------------------------------------------------ */

test("a down move can qualify as a YES reversal", () => {
  const obs = {
    ticker: "T", fee_multiplier: 1, prevMid: 0.60,
    top: { yes_bid: 0.44, yes_ask: 0.45, mid: 0.445, spread: 0.01,
           two_sided: true, executable: true }
  };
  const m = L.scoreSwing(obs, obs.top, "down", 0.05);
  assert.ok(m, "expected a model pick");
  assert.equal(m.side, "yes");
  assert.equal(m.executable_price, 0.45);
  assert.equal(m.model_fair, 0.6);
  assert.ok(m.net_roi >= 0.05);
});

test("an up move can qualify as a NO reversal", () => {
  const obs = {
    ticker: "T", fee_multiplier: 1, prevMid: 0.40,
    top: { yes_bid: 0.54, yes_ask: 0.55, mid: 0.545, spread: 0.01,
           two_sided: true, executable: true }
  };
  const m = L.scoreSwing(obs, obs.top, "up", 0.05);
  assert.ok(m);
  assert.equal(m.side, "no");
  assert.equal(m.executable_price, 0.46); // 1 - 0.54
});

test("the model refuses trades whose spread eats the edge", () => {
  const obs = {
    ticker: "T", fee_multiplier: 1, prevMid: 0.55,
    top: { yes_bid: 0.44, yes_ask: 0.46, mid: 0.45, spread: 0.02,
           two_sided: true, executable: true }
  };
  assert.equal(L.scoreSwing(obs, obs.top, "down", 0.30), null);
});

test("the model refuses an unexecutable book outright", () => {
  const obs = {
    ticker: "T", fee_multiplier: 1, prevMid: 0.9,
    top: { yes_bid: 0.001, yes_ask: 0.886, spread: 0.885,
           two_sided: true, executable: false }
  };
  assert.equal(L.scoreSwing(obs, obs.top, "down", 0.0), null);
});

/* ------------------------------------------------------------------ */
/* snapshot -> observations                                            */
/* ------------------------------------------------------------------ */

test("observationsFromSnapshot keeps only two-sided tight quotes", () => {
  const obs = L.observationsFromSnapshot({
    events: [
      { ticker: "OK", yes_bid: 0.4, yes_ask: 0.42, title: "ok", topic: "crypto" },
      { ticker: "WIDE", yes_bid: 0.001, yes_ask: 0.886 },
      { ticker: "ONE", yes_bid: 0.3, yes_ask: null },
      { ticker: "BLANK" }
    ]
  });
  assert.deepEqual(obs.map((o) => o.ticker), ["OK"]);
  assert.equal(obs[0].prevMid, 0.41);
});

test("joinBooks uses the book for price and the record for identity", () => {
  const joined = L.joinBooks(
    [{ ticker: "T1", event_ticker: "E1", yes_sub_title: "Title 1" }],
    [{ ticker: "T1", orderbook: { yes_dollars: [["0.30", "10"]], no_dollars: [["0.68", "5"]] } }],
    () => "golf"
  );
  assert.equal(joined.length, 1);
  assert.equal(joined[0].top.yes_bid, 0.3);
  assert.equal(joined[0].top.yes_ask, 0.32);
  assert.equal(joined[0].topic, "golf");
});

test("joinBooks keeps markets whose book is missing out of the list", () => {
  const joined = L.joinBooks([{ ticker: "T1" }], [], () => null);
  assert.equal(joined.length, 0);
});

/* ------------------------------------------------------------------ */
/* the poller, with injected I/O                                       */
/* ------------------------------------------------------------------ */

await testAsync("the poller polls once, fires an alert and reports live", async () => {
  const alerts = [];
  const polls = [];
  let call = 0;
  const booksFor = (bid, askBid) => ({
    orderbooks: [{ ticker: "T1", orderbook: {
      yes_dollars: [[String(bid.toFixed(4)), "100"]],
      no_dollars: [[String(askBid.toFixed(4)), "100"]]
    } }]
  });
  const poller = L.createPoller({
    fetchJson: async (url) => {
      if (url.includes("/markets/orderbooks")) {
        call += 1;
        return call === 1 ? booksFor(0.20, 0.79) : booksFor(0.60, 0.39);
      }
      if (url.includes("/markets?")) {
        return { markets: [{ ticker: "T1", event_ticker: "E1", yes_sub_title: "Test" }] };
      }
      throw new Error("unexpected url " + url);
    },
    intervalMs: 1,
    onAlert: (a) => alerts.push(a),
    onPoll: (p) => polls.push(p)
  });
  poller.setWatchlist([{ ticker: "T1", topic: "crypto" }]);
  await poller.pollOnce();
  const got = await poller.pollOnce();
  assert.equal(alerts.length, 1, "expected one swing");
  assert.equal(got.length, 1);
  assert.equal(alerts[0].ticker, "T1");
  assert.equal(alerts[0].abs_delta, 0.4);
  assert.equal(poller.stats.polls, 2);
  assert.equal(polls.length, 2);
});

await testAsync("the poller backs off and reports an error instead of throwing", async () => {
  const states = [];
  let n = 0;
  const poller = L.createPoller({
    fetchJson: async () => { n += 1; throw new Error("429 Too Many Requests"); },
    intervalMs: 1,
    onStatus: (s) => states.push(s)
  });
  poller.setWatchlist([{ ticker: "T1" }]);
  const out = await poller.pollOnce();
  assert.deepEqual(out, []);
  assert.equal(poller.stats.lastError, "429 Too Many Requests");
  assert.ok(states.some((s) => s.state === "error"));
});

await testAsync("the poller sends only unauthenticated GET URLs", async () => {
  const urls = [];
  const poller = L.createPoller({
    fetchJson: async (url) => {
      urls.push(url);
      return url.includes("orderbooks") ? { orderbooks: [] } : { markets: [] };
    },
    intervalMs: 1
  });
  poller.setWatchlist([{ ticker: "A" }, { ticker: "B" }]);
  await poller.pollOnce();
  assert.equal(urls.length, 2);
  for (const u of urls) {
    assert.match(u, /^https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets/);
    assert.ok(!u.includes("/portfolio/"), "must never touch a portfolio endpoint");
  }
  /* `tickers` is a repeated parameter (form/explode), so the URL must carry it
   * once per ticker. A comma-joined value would be read as a single unknown
   * ticker and come back as an empty book. */
  assert.match(urls[0], /tickers=A&tickers=B/);
  assert.ok(!/tickers=[^&]*,/.test(urls[0]), "must not comma-join tickers");
});

await testAsync("the poller accepts nothing from a snapshot other than tight quotes", async () => {
  const seen = [];
  const poller = L.createPoller({
    fetchJson: async (url) => url.includes("orderbooks")
      ? { orderbooks: [{ ticker: "OK", orderbook: { yes_dollars: [["0.30", "1"]], no_dollars: [["0.68", "1"]] } }] }
      : { markets: [{ ticker: "OK" }] },
    intervalMs: 1,
    onAlert: (a) => seen.push(a)
  });
  const obs = poller.observationsFromSnapshot({
    events: [
      { ticker: "OK", yes_bid: 0.4, yes_ask: 0.42 },
      { ticker: "WIDE", yes_bid: 0.01, yes_ask: 0.90 }
    ]
  });
  assert.deepEqual(obs.map((o) => o.ticker), ["OK"]);
});

/* ------------------------------------------------------------------ */
/* report                                                              */
/* ------------------------------------------------------------------ */

if (failures.length) {
  for (const f of failures) {
    console.error("FAIL " + f.name);
    console.error("     " + (f.err && f.err.message ? f.err.message : f.err));
  }
  console.error(`\n${passed} passed, ${failures.length} failed`);
  process.exit(1);
}
console.log(`live-probe: ${passed} checks passed`);
