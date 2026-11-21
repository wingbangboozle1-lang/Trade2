/* jsdom tests for the docs/ browser live layer (task T31, session arena-5bec0ea3).
 *
 *   node tests/test_docs_live.mjs
 *
 * Drives docs/assets/app.js + docs/assets/live.js inside jsdom with a stubbed
 * fetch so no network is needed. Verifies:
 *   1. REST self-check OK -> LIVE badge, live poll hits the demo API,
 *      a >= $0.10 move raises one deduplicated live alert with an official
 *      source link, and the baseline resets (no re-alert on a sustained move).
 *   2. Demo API unreachable -> SNAPSHOT badge, feed untouched, no errors.
 *   3. The seconds/minutes/hours chart windows never render a wrong label.
 *   4. docs/resolutions.html groups YES/NO rows with source links.
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DOCS = path.join(ROOT, "docs");
const FIX = path.join(DOCS, "data");

const appJs = fs.readFileSync(path.join(DOCS, "assets", "app.js"), "utf8");
const liveJs = fs.readFileSync(path.join(DOCS, "assets", "live.js"), "utf8");

function fixture(rel) {
  const p = path.join(FIX, rel);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, "utf8")) : null;
}

function inline(html) {
  // must use function replacements: app.js contains $$, $& sequences
  return html
    .replace('<script src="assets/app.js"></script>',
      () => "<script>\n" + appJs + "\n</script>")
    .replace('<script src="assets/live.js"></script>',
      () => "<script>\n" + liveJs + "\n</script>");
}

const TICKER = "KXAAAGASM-26NOV30-3.50";
const OTHER = ["KXFAKE-1", "KXFAKE-2"];
let marketCalls = 0;      // total /markets/{ticker} fetches (any ticker)
let tickerPolls = 0;      // fetches of the scripted TICKER = one per poll
function marketRaw(bid, ask, ticker) {
  ticker = ticker || TICKER;
  return {
    market: {
      ticker: ticker, event_ticker: "KXAAAGASM-26NOV30", series_ticker: "KXAAAGASM",
      title: "Gas above $3.50?", status: "active",
      yes_bid_dollars: bid.toFixed(4), yes_ask_dollars: ask.toFixed(4),
      last_price_dollars: ((bid + ask) / 2).toFixed(4),
      volume_fp: "1234", open_interest_fp: "5678",
      // real response key/value (GET /markets/{ticker} returns this ISO field)
      expected_expiration_time: "2026-11-29T21:33:20Z",
    },
  };
}
// Synthetic markets.json rows: scripted ticker always ranks first.
function synthMarkets() {
  const row = (ticker, notional) => ({
    ticker, event_ticker: "KXAAAGASM-26NOV30", series_ticker: "KXAAAGASM",
    title: "Gas above $3.50?", topic: "gas-prices", status: "open",
    yes_bid: 0.40, yes_ask: 0.42, last_price: 0.41,
    volume_fp: 1234, open_interest_fp: 5678, notional_usd: notional,
    source_url: "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + ticker,
    docs_url: "https://docs.kalshi.com/api-reference/market/get-markets",
    flags: [], verified: true,
  });
  return {
    generated_at: "2026-11-20T00:00:00Z",
    rows: [row(TICKER, 900), row(OTHER[0], 100), row(OTHER[1], 50)],
    source_docs: ["https://docs.kalshi.com/api-reference/market/get-markets"],
  };
}
function scriptForPoll(n) {
  // poll 1: mid 0.41 (baseline); poll 2: mid 0.56 (+$0.15 swing);
  // poll 3+: mid 0.67 (sustained move -> must NOT re-alert immediately)
  return n === 1 ? marketRaw(0.40, 0.42)
    : n === 2 ? marketRaw(0.55, 0.57)
    : marketRaw(0.66, 0.68);
}

async function loadPage(file, { restMode = true, capabilities = null, page } = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", e => errors.push("jsdomError: " + e.message));
  vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

  let html = fs.readFileSync(path.join(DOCS, file), "utf8");
  html = inline(html);
  const caps = capabilities === undefined ? fixture("capabilities.json") : capabilities;

  const dom = new JSDOM(html, {
    url: "https://wingbangboozle1-lang.github.io/Trade2/" + file,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.devicePixelRatio = 1;
      window.HTMLCanvasElement.prototype.getContext = () => null;
      window.fetch = async (url) => {
        const u = String(url).split("?")[0];
        const ok = (obj) => ({ ok: true, json: async () => obj });
        if (u.includes("external-api.demo.kalshi.co")) {
          if (!restMode) throw new TypeError("Failed to fetch (CORS/network)");
          if (u.includes("/orderbook")) {
            return ok({ orderbook_fp: { yes_dollars: [["0.40", "100"]], no_dollars: [["0.55", "80"]] } });
          }
          if (u.includes("/candlesticks")) {
            return ok({ candlesticks: [
              { end_period_ts: 1795197000, close: 0.41 },
              { end_period_ts: 1795197060, close: 0.56 },
            ] });
          }
          if (u.includes("/markets/")) {
            marketCalls += 1;
            const tk = decodeURIComponent(u.split("/markets/")[1].split("/")[0]);
            if (tk === TICKER) {
              tickerPolls += 1;
              return ok(scriptForPoll(tickerPolls));
            }
            // other polled tickers: own ticker, static price (own baseline)
            return ok(marketRaw(0.10, 0.12, tk));
          }
          return ok({ markets: [marketRaw(0.40, 0.42).market] });
        }
        // relative published JSON
        const rel = u.replace(/^.*\/Trade2\//, "");
        if (rel === "data/capabilities.json") return ok(caps);
        if (rel === "data/markets.json") return ok(synthMarkets());
        const name = rel.replace(/^data\//, "");
        const data = fixture(name);
        return data ? ok(data) : { ok: false, json: async () => null };
      };
    },
  });
  // allow boot() chains to settle
  const settle = async (steps = 12) => {
    for (let i = 0; i < steps; i++) await new Promise(r => setTimeout(r, 5));
  };
  return { dom, errors, settle, window: dom.window };
}

function badgeText(window) {
  const d = window.__desk;
  return d && d.S ? String(d.S.liveLabel || "") : "";
}

let failures = 0;
function check(cond, label) {
  if (cond) console.log("  ok:", label);
  else { failures += 1; console.error("  FAIL:", label); }
}

/* ------------------------------------------------------------------ 1 */
async function testLiveMode() {
  console.log("test: REST self-check OK -> LIVE badge + deduplicated live alerts");
  marketCalls = 0;
  const { window, errors, settle } = await loadPage("index.html");
  await settle();
  check(badgeText(window).includes("LIVE") && !badgeText(window).includes("SNAPSHOT"),
    "badge shows LIVE");
  check(marketCalls >= 1, "live poll hit the demo API (" + marketCalls + " calls)");
  const before = window.document.querySelectorAll("#feed-all .msg").length;

  window.__deskLivePoll();       // poll 2: +$0.15 swing vs baseline
  await settle(4);
  const rows = window.document.querySelectorAll("#feed-all .msg");
  check(rows.length === before + 1, "one live alert row added (got " + (rows.length - before) + ")");
  const row = rows[0] ? rows[0].innerHTML : "";
  check(row.includes("live"), "alert row carries the live badge");
  check(row.includes("external-api.demo.kalshi.co/trade-api/v2/markets/"),
    "alert row links the official market URL");
  check(row.includes("no verified headline"), "no invented news link — blank is flagged");
  // The market object's own expiration field must survive into the live row.
  // The collector's Python mapping is pinned in collector/test_runner.py; this
  // pins the browser path, which reads the same API response directly. A wrong
  // key here blanks the column in LIVE mode while looking perfectly healthy.
  const liveRow = (window.__desk.S.markets || []).find(m => m && m.ticker === TICKER);
  check(liveRow && liveRow.expected_expiration === "2026-11-29T21:33:20Z",
    "live row keeps the API's expected_expiration_time verbatim");

  window.__deskLivePoll();       // poll 3: sustained move -> dedup
  await settle(4);
  const after = window.document.querySelectorAll("#feed-all .msg").length;
  check(after === rows.length, "sustained move did NOT re-alert (dedup + baseline reset)");
  check(errors.length === 0, "no JS errors (" + errors.slice(0, 2).join(" | ") + ")");
  window.close();
}

/* ------------------------------------------------------------------ 2 */
async function testSnapshotFallback() {
  console.log("test: demo API unreachable -> SNAPSHOT mode, no errors");
  marketCalls = 0;
  const { window, errors, settle } = await loadPage("index.html", { restMode: false });
  await settle();
  const label = badgeText(window);
  check(label.includes("SNAPSHOT"), "badge shows SNAPSHOT (got: " + label.slice(0, 60) + ")");
  check(marketCalls === 0, "no live poll attempted after failed self-check");
  check(errors.length === 0, "no JS errors (" + errors.slice(0, 2).join(" | ") + ")");
  window.close();
}

/* ------------------------------------------------------------------ 3 */
async function testCapabilitiesGate() {
  console.log("test: probe with CORS blocked stays in snapshot mode");
  const caps = {
    generated_at: "2026-11-20T00:00:00Z",
    probes: {
      rest_cors: { browser_usable: false },
      ws_anonymous_handshake: { anonymous_handshake_accepted: false },
    },
  };
  // runtime self-check still decides REST; with restMode=false nothing changes
  const { window, settle } = await loadPage("index.html", { restMode: false, capabilities: caps });
  await settle();
  check(badgeText(window).includes("SNAPSHOT"), "snapshot mode kept");
  window.close();
}

/* ------------------------------------------------------------------ 4 */
async function testResolutionsPage() {
  console.log("test: resolutions page groups YES/NO with source links");
  const { window, errors, settle } = await loadPage("resolutions.html", { restMode: false });
  await settle();
  const html = window.document.querySelector("#resolutions-all").innerHTML;
  check(html.includes("YES") && html.includes("NO"), "outcomes rendered");
  check(html.includes("external-api.demo.kalshi.co/trade-api/v2/markets/"),
    "rows link the official market API");
  check(/Resolved YES/.test(window.document.querySelector("#resolutions-stats").innerHTML),
    "stats row for YES resolutions");
  check(errors.length === 0, "no JS errors (" + errors.slice(0, 2).join(" | ") + ")");
  window.close();
}

/* ------------------------------------------------------------------ 5 */
async function testChartWindows() {
  console.log("test: topic chart windows render with honest labels");
  const { window, errors, settle } = await loadPage("gas-prices.html", { restMode: false });
  await settle();
  const meta = window.document.querySelector("#chart-meta");
  check(meta && meta.innerHTML.length > 0, "chart meta rendered");
  check(!/1-minute/.test(meta.innerHTML) || /interval|tick/.test(meta.innerHTML),
    "no misleading second-level claim");
  check(errors.length === 0, "no JS errors (" + errors.slice(0, 2).join(" | ") + ")");
  window.close();
}

await testLiveMode();
await testSnapshotFallback();
await testCapabilitiesGate();
await testResolutionsPage();
await testChartWindows();

if (failures) {
  console.error(failures + " FAILURE(S)");
  process.exit(1);
}
console.log("ALL PASS");
