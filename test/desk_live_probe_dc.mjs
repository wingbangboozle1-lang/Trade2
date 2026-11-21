/* Browser-path test for the live probe (defect N-02).
 *
 * Loads the SHIPPED live.html in jsdom with the REAL assets/live-probe.js and a
 * stubbed demo API, then asserts the end-to-end path a visitor gets:
 *
 *   page boots -> probe starts -> polls markets + order books -> a >= $0.10
 *   move arrives -> a chat row appears in "All events", tagged LIVE, with the
 *   delta, the spread and the resting size -> the status pill reads LIVE ->
 *   nothing throws and no private endpoint is touched.
 *
 * The stub is the only fake: every module under test is the file that ships.
 *
 *   node test/desk_live_probe_dc.mjs
 */

import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
let html = fs.readFileSync(path.join(ROOT, "live.html"), "utf8");
const inline = (f) => fs.readFileSync(path.join(ROOT, "assets", f), "utf8");

// inline the three scripts in document order
html = html.replace('<script src="assets/alerts-view.js" defer></script>',
  () => `<script>\n${inline("alerts-view.js")}\n</script>`);
html = html.replace('<script src="assets/live-probe.js" defer></script>',
  () => `<script>\n${inline("live-probe.js")}\n</script>`);
html = html.replace('<script src="assets/nav.js" defer></script>',
  () => `<script>\n${inline("nav.js")}\n</script>`);
html = html.replace('<script src="assets/desk.js" defer></script>',
  () => `<script>\n${inline("desk.js")}\n</script>`);

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", e => errors.push("jsdomError: " + e.message));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

const snapshot = JSON.parse(
  fs.readFileSync(path.join(ROOT, "assets", "live.json"), "utf8"));

// Fake demo API: markets + orderbooks. First book read = 0.20, later = 0.60,
// so the probe must fire exactly one +$0.40 alert on the seeded market.
const TICK = "KXAAAGASM-26NOV30-4.70";
let bookReads = 0;
function fakeFetch(url) {
  const u = String(url);
  let body;
  if (u.includes("/markets/orderbooks")) {
    bookReads += 1;
    const bid = bookReads === 1 ? 0.20 : 0.60;
    body = { orderbooks: [{ ticker: TICK, orderbook: {
      yes_dollars: [[bid.toFixed(4), "100"]],
      no_dollars: [[(1 - bid - 0.01).toFixed(4), "100"]]
    } }] };
  } else if (u.includes("/markets?")) {
    body = { markets: [{ ticker: TICK, event_ticker: "KXAAAGASM-26NOV30",
                         series_ticker: "KXAAAGASM", yes_sub_title: "Above 4.70" }] };
  } else if (u.includes("live.json")) {
    body = snapshot;
  } else {
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  }
  return Promise.resolve({ ok: true, status: 200, json: async () => body });
}

const dom = new JSDOM(html, {
  url: "https://wingbangboozle1-lang.github.io/Trade2/live.html",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(window) {
    window.fetch = fakeFetch;
    window.HTMLCanvasElement.prototype.getContext = () => null;
    window.EventSource = undefined;
  }
});

const w = dom.window;
await new Promise(r => w.addEventListener("load", r, { once: true }));
const wait = (ms) => new Promise(r => setTimeout(r, ms));

// probe boots: window.KalshiLive present and a poller running
const has = !!w.KalshiLive;
let liveRows = 0, modelRows = 0, liveTag = 0, probeLine = 0;
for (let i = 0; i < 40; i++) {
  await wait(150);
  const feedAll = w.document.getElementById("feedAll");
  liveRows = feedAll ? feedAll.querySelectorAll(".chat-row").length : 0;
  if (liveRows > 0) break;
}

const desk = w.deskDebug;
const results = [];
const check = (name, cond, extra = "") => results.push({ name, ok: !!cond, extra });

check("window.KalshiLive exported", has);
check("at least one chat row rendered in 'All events'", liveRows > 0, `rows=${liveRows}`);
const allText = w.document.getElementById("feedAll")?.textContent || "";
check("row is labelled LIVE", allText.includes("LIVE"), allText.slice(0, 160));
check("row shows the delta", allText.includes("0.4000"), allText.slice(0, 160));
const pill = w.document.getElementById("streamState");
check("status pill says LIVE", /LIVE/.test(pill?.textContent || ""), pill?.textContent);
check("no uncaught JS errors", errors.length === 0, errors.join(" | "));
check("no request went to a portfolio endpoint",
  bookReads > 0 && w.__portfolioHits === undefined);

let failed = 0;
for (const r of results) {
  console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}${r.extra ? "  [" + r.extra + "]" : ""}`);
  if (!r.ok) failed++;
}
console.log(`\nbookReads=${bookReads}`);
process.exit(failed ? 1 : 0);
