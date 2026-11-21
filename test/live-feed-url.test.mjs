/* Regression tests for the batch order-book URL builder.
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * `GET /markets/orderbooks` declares `tickers` as a **string[]** query
 * parameter ("Required array length: 1 - 100 elements",
 * https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks).
 * The exchange reads ONE value per occurrence of the parameter. A
 * comma-joined value is therefore read as a single ticker whose name
 * contains the commas, and the answer is one EMPTY book for it.
 *
 * The live pulse (assets/desk.js) shipped with a comma-joined
 * `?tickers=A,B,C`, so every refresh returned one empty book, no tracked
 * ticker matched, and the panel reported a healthy "LIVE PULSE - N
 * readings" while measuring nothing. This test pins the documented form.
 *
 * Live evidence against the demo exchange, 2026-11-21 ~07:20Z:
 *   ?tickers=KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70
 *     -> one entry, ticker "KXPRESNOMD-28-RW,KXAAAGASM-26NOV30-4.70",
 *        orderbook_fp {"yes_dollars": [], "no_dollars": []}
 *   ?tickers=KXPRESNOMD-28-RW&tickers=KXAAAGASM-26NOV30-4.70
 *     -> two entries, each with its real book.
 *
 * Run: node --test test/live-feed-url.test.mjs
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const LiveFeed = require("../assets/live-feed.js");

const BASE = "https://external-api.demo.kalshi.co/trade-api/v2/markets/orderbooks";

test("each ticker is its own `tickers=` occurrence, never a comma-joined value", () => {
  const url = LiveFeed.batchOrderbookUrl(BASE, ["KXPRESNOMD-28-RW", "KXAAAGASM-26NOV30-4.70"]);
  assert.equal(
    url,
    BASE + "?tickers=KXPRESNOMD-28-RW&tickers=KXAAAGASM-26NOV30-4.70"
  );
  assert.ok(!url.includes("%2C"), "no comma may survive into the query value");
  assert.equal(url.split("tickers=").length - 1, 2, "one occurrence per ticker");
});

test("a single ticker still produces a valid documented query", () => {
  const url = LiveFeed.batchOrderbookUrl(BASE, ["KXPRESNOMD-28-RW"]);
  assert.equal(url, BASE + "?tickers=KXPRESNOMD-28-RW");
});

test("ticker values are percent-encoded", () => {
  const url = LiveFeed.batchOrderbookUrl(BASE, ["KX A&B", "X?Y"]);
  assert.equal(url, BASE + "?tickers=KX%20A%26B&tickers=X%3FY");
});

test("blank and null tickers are dropped, not sent as empty values", () => {
  const url = LiveFeed.batchOrderbookUrl(BASE, ["A", "", "   ", null, undefined, "B"]);
  assert.equal(url, BASE + "?tickers=A&tickers=B");
});

test("no usable ticker yields no URL at all (the caller must not fetch)", () => {
  assert.equal(LiveFeed.batchOrderbookUrl(BASE, []), null);
  assert.equal(LiveFeed.batchOrderbookUrl(BASE, ["", "  "]), null);
  assert.equal(LiveFeed.batchOrderbookUrl(BASE, null), null);
});

test("a base URL that already has a query keeps it", () => {
  const url = LiveFeed.batchOrderbookUrl(BASE + "?depth=10", ["A", "B"]);
  assert.equal(url, BASE + "?depth=10&tickers=A&tickers=B");
});

test("the count of `tickers=` occurrences equals the count of requested tickers", () => {
  const tickers = Array.from({ length: 100 }, (_, i) => `KXTEST-${i}`);
  const url = LiveFeed.batchOrderbookUrl(BASE, tickers);
  assert.equal(url.split("tickers=").length - 1, 100);
});
