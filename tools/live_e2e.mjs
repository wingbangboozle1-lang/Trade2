/* End-to-end check of the shipped browser detector against the LIVE demo API.
 *
 * assets/live-probe.js is written for a browser, so the unit tests stub the
 * network. This script does not: it loads the real module, seeds the watchlist
 * from the committed snapshot exactly as the page does, and runs two real polls
 * with the module's own fetch path. It answers the one question a stub cannot:
 * does the page, as shipped, actually get order books back from Kalshi?
 *
 * Read-only, exactly two unauthenticated GETs per poll, no credentials.
 *
 *   node tools/live_e2e.mjs [--json out.json]
 * Exit 0 only when both endpoints answer one record per ticker, in order, and
 * at least one book carries levels.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const jsonArg = process.argv.indexOf("--json");

function annotate(level, title, message) {
  if (process.env.GITHUB_ACTIONS !== "true") return;
  const clean = String(message).replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
  console.log(`::${level} title=${title}::${clean}`);
}

const { default: L } = await import(join(ROOT, "assets", "live-probe.js"));
const live = JSON.parse(readFileSync(join(ROOT, "data", "live.json"), "utf8"));

const watch = live.events
  .filter((e) => e.ticker && e.yes_bid != null && e.yes_ask != null)
  .sort((a, b) => (b.open_interest_notional || 0) - (a.open_interest_notional || 0))
  .slice(0, 6)
  .map((e) => ({ ticker: e.ticker, topic: e.topic }));

const report = { requested: watch.map((w) => w.ticker), polls: 0, errors: [] };
const bodies = {};

const poller = L.createPoller({
  intervalMs: 1,
  onStatus: (s) => {
    if (s.state === "error") report.errors.push(String(s.detail || "error"));
  },
  fetchJson: async (url) => {
    report.marketsUrl = report.marketsUrl || (url.includes("/markets?") ? url : undefined);
    report.booksUrl = report.booksUrl || (url.includes("/orderbooks") ? url : undefined);
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) {
      const text = (await res.text()).slice(0, 200);
      throw new Error(`HTTP ${res.status} ${text}`);
    }
    const body = await res.json();
    bodies[url.includes("/orderbooks") ? "books" : "markets"] = body;
    return body;
  },
});

const size = poller.setWatchlist(watch);
if (size !== watch.length) report.errors.push(`watchlist truncated to ${size}`);

try {
  await poller.pollOnce(); // baseline — first sight of a market never alerts
  report.polls += 1;
  const alerts = await poller.pollOnce(); // comparable read
  report.polls += 1;
  report.alerts = alerts.length;
} catch (err) {
  report.errors.push(String(err && err.message ? err.message : err));
}

const markets = (bodies.markets && bodies.markets.markets) || [];
const books = (bodies.books && bodies.books.orderbooks) || [];
const withLevels = books.filter((entry) => {
  const b = entry.orderbook_fp || {};
  return (b.yes_dollars && b.yes_dollars.length) || (b.no_dollars && b.no_dollars.length);
});

report.markets = markets.length;
report.books = books.length;
report.booksWithLevels = withLevels.length;
report.orderPreserved =
  JSON.stringify(books.map((e) => e.ticker)) === JSON.stringify(report.requested);

const problems = [...report.errors];
if (markets.length !== watch.length) problems.push(`/markets returned ${markets.length} of ${watch.length} records`);
if (books.length !== watch.length) problems.push(`/orderbooks returned ${books.length} of ${watch.length} entries`);
if (!report.orderPreserved) problems.push("order-book entries were not returned in request order");
if (!withLevels.length) problems.push("no order book carried any levels");

report.problems = problems;

console.log(JSON.stringify(report, null, 1));
if (jsonArg > 0 && process.argv[jsonArg + 1]) writeFileSync(process.argv[jsonArg + 1], JSON.stringify(report, null, 1));

if (problems.length) {
  for (const p of problems) annotate("error", "live e2e", p);
  console.error("\nLIVE E2E FAILED");
  process.exit(1);
}
console.log("\nLIVE E2E OK — the shipped page gets real order books, one per ticker, in order");
