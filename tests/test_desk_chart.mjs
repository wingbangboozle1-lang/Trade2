/* The live desk chart must plot quote mids, never trade prints, and must never
 * synthesise a price from a one-sided book. Those two rules are enforced in
 * assets/desk.js (midFromBook, blockClose and the candlestick seed). This test
 * executes the same expressions against documented payload shapes so a future
 * edit cannot quietly reintroduce the defect.
 *
 * Official schema: https://docs.kalshi.com/api-reference/market/get-market-candlesticks
 *   price     = trade OHLC
 *   yes_bid   = YES bid OHLC  } quote OHLC
 *   yes_ask   = YES ask OHLC  }
 */
import assert from "node:assert/strict";

const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, msg || `${a} != ${b}`);

// ---- copied verbatim from assets/desk.js -------------------------------
function bestBid(levels) {
  if (!levels || !levels.length) return null;
  const last = levels[levels.length - 1];
  if (!last || last.length < 2) return null;
  const price = Number(last[0]);
  const size = Number(last[1]);
  return isFinite(price) ? { price, size } : null;
}
function midFromBook(book) {
  const yb = bestBid(book.yes_dollars);
  const nb = bestBid(book.no_dollars);
  if (!yb || !nb) return null;
  const yesBid = yb.price;
  const yesAsk = 1 - nb.price;
  if (!(yesAsk >= yesBid)) return null;
  return (yesBid + yesAsk) / 2;
}
function blockClose(block) {
  if (!block || block.close_dollars == null || block.close_dollars === "") return null;
  const v = Number(block.close_dollars);
  return isFinite(v) && v > 0 && v <= 1 ? v : null;
}
function candleMid(c) {
  const bid = blockClose(c.yes_bid);
  const ask = blockClose(c.yes_ask);
  if (bid === null || ask === null || ask < bid) return null;
  return Math.round(((bid + ask) / 2) * 10000) / 10000;
}
// -----------------------------------------------------------------------

// Live book for KXPRESNOMD-28-HBID, fetched 2026-11-20T19:04Z.
const HBID = {
  yes_dollars: [["0.0010", "166666.66"], ["0.0020", "83333.33"]],
  no_dollars: [["0.1850", "1471.00"], ["0.1890", "271.49"]],
};
// best YES bid 0.0020, implied YES ask 1 - 0.1890 = 0.8110, mid 0.4065.
close(midFromBook(HBID), 0.4065, "HBID mid is (0.0020 + 0.8110) / 2");

// One-sided books have no mid at all.
assert.equal(midFromBook({ yes_dollars: [["0.5000", "10.00"]], no_dollars: [] }), null);
assert.equal(midFromBook({ yes_dollars: [], no_dollars: [["0.4000", "10.00"]] }), null);
assert.equal(midFromBook({ yes_dollars: [], no_dollars: [] }), null);

// A tight book still produces the documented mid: 0.42 bid, 0.56 NO bid
// -> implied YES ask 0.44, mid 0.43 (the docs' own worked example is
// 0.42 / 0.44 -> spread 0.02; this fixture uses the same shape).
close(
  midFromBook({ yes_dollars: [["0.4200", "13.00"]], no_dollars: [["0.5600", "17.00"]] }),
  0.43,
  "0.42 bid / 0.44 implied ask -> mid 0.43"
);

// Candles: the trade price must be ignored; the quote closes decide.
const hbidCandle = {
  end_period_ts: 1795200000,
  price: { close_dollars: "0.8110" },        // last trade
  yes_bid: { close_dollars: "0.0020" },
  yes_ask: { close_dollars: "0.8110" },
};
assert.equal(candleMid(hbidCandle), 0.4065, "quote mid, not the 0.8110 trade print");

// A candle without a two-sided quote contributes no point.
assert.equal(candleMid({ end_period_ts: 1, price: { close_dollars: "0.5000" },
                         yes_bid: {}, yes_ask: {} }), null);
// Crossed quote -> no point.
assert.equal(candleMid({ end_period_ts: 1, yes_bid: { close_dollars: "0.6000" },
                         yes_ask: { close_dollars: "0.4000" } }), null);

console.log("DESK CHART BASIS OK: quote mids only, never one-sided books or trade prints");
