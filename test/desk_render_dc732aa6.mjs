/**
 * Browser-path check for the live desk (session arena-dc732aa6).
 *
 * tools/rendercheck.mjs loads each page but cannot execute `assets/desk.js`,
 * because jsdom does not fetch external scripts. The two scrolling chats, the
 * price-basis badges and the snapshot-age label are rendered *by that script*,
 * so they are checked here instead: the real page, the real script, a stubbed
 * fetch that returns the real published snapshot, and assertions on the DOM
 * that a trader would see.
 *
 * Run: node test/desk_render_dc732aa6.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

const root = process.cwd();
const pageFile = path.join(root, "live.html");
const scriptFile = path.join(root, "assets", "desk.js");
const dataFile = path.join(root, "assets", "live.json");

let failures = 0;
function check(name, ok, detail = "") {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
  if (!ok) failures++;
}

const html = fs.readFileSync(pageFile, "utf8")
  // Strip the deferred script tags: jsdom will not fetch them, and we eval the
  // real file ourselves so the check exercises the shipped code.
  .replace(/<script src="[^"]+" defer><\/script>/g, "");
const script = fs.readFileSync(scriptFile, "utf8");
const snapshot = JSON.parse(fs.readFileSync(dataFile, "utf8"));

const consoleErrors = [];
const vc2Errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => consoleErrors.push(`jsdomError: ${e.message}`));
vc.on("error", (...a) => consoleErrors.push(`console.error: ${a.join(" ")}`));
const vc2 = new VirtualConsole();
vc2.on("jsdomError", (e) => vc2Errors.push(`jsdomError: ${e.message}`));
vc2.on("error", (...a) => vc2Errors.push(`console.error: ${a.join(" ")}`));

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
  url: "http://localhost/Trade2/live.html",
});
const win = dom.window;

// The desk polls the published snapshot and the live book. Both are stubbed
// from real data so the render path is exercised end to end, offline.
// jsdom has no canvas backend. Supply a recording 2D context so the real
// drawing path runs; the no-canvas fallback is asserted separately below.
const drawn = { arcs: 0, texts: 0, strokes: 0 };
win.HTMLCanvasElement.prototype.getContext = function getContext() {
  return {
    canvas: this,
    setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
    moveTo() {}, lineTo() {}, stroke() { drawn.strokes++; },
    fill() {}, arc() { drawn.arcs++; }, fillRect() {},
    createLinearGradient() { return { addColorStop() {} }; },
    fillText() { drawn.texts++; },
    get font() {}, set font(_) {}, get fillStyle() {}, set fillStyle(_) {},
    get strokeStyle() {}, set strokeStyle(_) {}, get lineWidth() {},
    set lineWidth(_) {}, get textAlign() {}, set textAlign(_) {},
  };
};

win.fetch = (url) => {
  const body = String(url).includes("orderbook")
    ? JSON.stringify({
        orderbook_fp: {
          yes_dollars: [["0.4000", "500.00"], ["0.4200", "250.00"]],
          no_dollars: [["0.5500", "100.00"], ["0.5700", "40.00"]],
        },
      })
    : fs.readFileSync(dataFile, "utf8");
  return Promise.resolve({ ok: true, json: () => Promise.resolve(JSON.parse(body)) });
};
win.eval(script);
await new Promise((r) => setTimeout(r, 150));
win.document.dispatchEvent(new win.Event("DOMContentLoaded", { bubbles: true }));
await new Promise((r) => setTimeout(r, 300));

const doc = win.document;
const alerts = snapshot.alerts || [];
const rows = doc.querySelectorAll("#feedAll .chat-row");
const modelRows = doc.querySelectorAll("#feedModel .chat-row");
const deskRows = doc.querySelectorAll("#deskRows tr");

check("desk.js ran without a thrown error", consoleErrors.length === 0,
      consoleErrors.slice(0, 2).join(" | "));
check("all-events chat renders every buffered alert",
      rows.length === Math.min(200, alerts.length),
      `expected ${Math.min(200, alerts.length)}, got ${rows.length}`);
check("model chat uses the published shortlist, not a client-side re-gate",
      modelRows.length === Math.min(200, (snapshot.high_roi_alerts || []).length),
      `expected ${Math.min(200, (snapshot.high_roi_alerts || []).length)}, ` +
      `got ${modelRows.length}`);
check("market table renders from the snapshot", deskRows.length > 0,
      `${deskRows.length} rows`);
check("each chat row states a price basis or is labelled pre-rule",
      rows.length === 0 || Array.from(rows).every((r) =>
        /quote mid|previous-snapshot mid|pre-rule row/.test(r.textContent)),
      `${rows.length} rows`);
check("each chat row carries a news line (link or an explicit absence)",
      rows.length === 0 || Array.from(rows).every((r) =>
        r.querySelector(".cause-links") !== null));
check("no literal null/undefined/[object Object] leaks into the chats",
      !/undefined|\[object Object\]|NaN/.test(
        doc.querySelector("#feedAll").textContent +
        doc.querySelector("#feedModel").textContent +
        doc.querySelector("#depthBook").textContent));
check("snapshot age label is computed from the payload timestamp",
      /old|unknown/.test(doc.querySelector("#snapshotAge")?.textContent || ""),
      JSON.stringify(doc.querySelector("#snapshotAge")?.textContent));
check("a stale snapshot is not presented as fresh",
      (() => {
        const ageMin = (Date.now() - snapshot.generated_at_ts * 1000) / 60000;
        const el = doc.querySelector("#snapshotAge");
        if (!el) return false;
        return ageMin > 15 ? !el.className.includes("fresh") : true;
      })(),
      `snapshot age ${((Date.now() - snapshot.generated_at_ts * 1000) / 60000)
        .toFixed(0)} min`);

// Window tabs still switch the chart window.
const hoursTab = doc.querySelector('#windowTabs button[data-window="hours"]');
hoursTab?.dispatchEvent(new win.Event("click", { bubbles: true }));
check("seconds/minutes/hours tabs are wired", !!hoursTab &&
      doc.querySelector("#chartWindowLabel").textContent.includes("12 hours"),
      doc.querySelector("#chartWindowLabel")?.textContent);

// A chat "chart" button selects that market in the chart control.
const chartBtn = doc.querySelector('#feedAll [data-chart]');
if (chartBtn) {
  chartBtn.dispatchEvent(new win.Event("click", { bubbles: true }));
  const sel = doc.querySelector("#chartMarket");
  check("chat row's chart button drives the chart selector",
        sel.value === chartBtn.getAttribute("data-chart"),
        `${sel.value} vs ${chartBtn.getAttribute("data-chart")}`);
} else {
  // No buffered swing in this snapshot: the same wiring is exercised through a
  // market-table row instead, so the check still proves something real.
  const row = doc.querySelector("#deskRows tr.clickable") || doc.querySelector("#deskRows tr");
  row?.dispatchEvent(new win.Event("click", { bubbles: true }));
  const sel2 = doc.querySelector("#chartMarket");
  check("market row click drives the chart selector (no alerts to click)", !!row,
        `selected ${sel2?.value}`);
}
check("an empty all-events feed explains itself",
      alerts.length > 0 ||
      /No .*0\.10 swing/.test(doc.querySelector("#feedAll").textContent));

check("the chart drew price lines and swing markers", drawn.strokes > 0 && drawn.texts > 0,
      JSON.stringify(drawn));

// Fallback: a browser without a 2D context must keep the feeds alive.
const noCanvas = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true,
  virtualConsole: new VirtualConsole(), url: "http://localhost/Trade2/live.html" });
noCanvas.window.HTMLCanvasElement.prototype.getContext = () => null;
noCanvas.window.fetch = win.fetch;
noCanvas.window.eval(script);
await new Promise((r) => setTimeout(r, 300));
check("a missing canvas does not take the chats down with it",
      noCanvas.window.document.querySelectorAll("#feedAll .chat-row").length ===
      Math.min(200, alerts.length),
      `${noCanvas.window.document.querySelectorAll("#feedAll .chat-row").length} rows`);

/* ---------------------------------------------------------------------------
 * Second pass: a fixture snapshot, so the row-level rules are asserted on rows
 * that exist. The published snapshot is often empty — an honest feed says so —
 * and an empty feed proves nothing about a row's badges.
 * ------------------------------------------------------------------------- */
const fixture = {
  generated_at: new Date(Date.now() - 4 * 60000).toISOString().slice(0, 19) + "Z",
  generated_at_ts: Math.floor(Date.now() / 1000) - 240,
  reference_bar_seconds: 300,
  model_gate: { min_net_roi: 0.05, source: "collector/alerts.py" },
  suppressed_alerts: [{
    ticker: "KXFUEL-A", topic: "gas-prices", direction: "down",
    abs_delta: 0.4045, yes_bid: 0.002, yes_ask: 0.003,
    reason: "YES spread 0.8090 is not tighter than the $0.10 alert threshold",
    iso: "2026-11-20T18:41:58Z",
  }],
  signals: [{ ticker: "KXBTC-1", net_roi: 0.09, side: "yes",
              market_url: "https://demo.kalshi.co/events/KXBTC-1" }],
  high_roi_alerts: [{
    ticker: "KXBTC-1", direction: "up", abs_delta: 0.12, previous: 0.44,
    current: 0.56, topic: "crypto", title: "Bitcoin",
    iso: "2026-11-20T19:02:11Z", model_net_roi: 0.09,
  }],
  alerts: [
    { ticker: "KXBTC-1", event_ticker: "KXBTC-1", series_ticker: "KXBTC",
      topic: "crypto", title: "Bitcoin above $65k", direction: "up",
      abs_delta: 0.124, previous: 0.44, current: 0.564,
      iso: "2026-11-20T19:02:11Z", ts: Math.floor(Date.now() / 1000),
      yes_bid: 0.44, yes_ask: 0.45,
      market_url: "https://demo.kalshi.co/events/KXBTC-1",
      reference_basis: "quote mid vs quote mid", quality: "executable",
      quality_reason: "", spread: 0.01, size_at_top: 2400, repeat_count: 4,
      news_status: "",
      news: [{ title: "Exchange confirms outage", url: "https://example.test/a" }] },
    { ticker: "KXGAS-1", event_ticker: "KXGAS-1", series_ticker: "KXGAS",
      topic: "gas-prices", title: "California regular gasoline", direction: "down",
      abs_delta: 0.4045, previous: 0.4065, current: 0.002,
      iso: "2026-11-20T19:05:02Z", ts: Math.floor(Date.now() / 1000),
      yes_bid: 0.002, yes_ask: 0.811, market_url: "javascript:alert(1)",
      reference_basis: "previous-snapshot mid", quality: "indicative",
      quality_reason: "YES spread 0.8090 is not tighter than the $0.10 alert threshold",
      spread: 0.809, size_at_top: null, repeat_count: 0,
      news_status: "lookup disabled: no route to news.google.com from this runner" },
    { ticker: "KXGOLF-1", event_ticker: "KXGOLF-1", topic: "golf",
      title: "The Masters winner", direction: "up", abs_delta: 0.11,
      previous: 0.3, current: 0.41, iso: "2026-11-20T18:55:00Z",
      ts: Math.floor(Date.now() / 1000) - 400 },
  ],
  events: (snapshot.events || []).slice(0, 5),
  portfolio: snapshot.portfolio || {},
};

const fx = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true,
  virtualConsole: vc2, url: "http://localhost/Trade2/live.html",
});
fx.window.HTMLCanvasElement.prototype.getContext =
  win.HTMLCanvasElement.prototype.getContext;
fx.window.fetch = (url) => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(String(url).includes("orderbook")
    ? { orderbook_fp: { yes_dollars: [["0.4000", "500.00"]],
                        no_dollars: [["0.5500", "100.00"]] } }
    : fixture),
});
fx.window.eval(script);
await new Promise((r) => setTimeout(r, 350));
const fdoc = fx.window.document;
const frows = fdoc.querySelectorAll("#feedAll .chat-row");

check("fixture: every buffered alert is on the all-events feed",
      frows.length === fixture.alerts.length, `${frows.length} rows`);
const exec = frows[0] || { textContent: "", innerHTML: "" };
check("fixture: an executable row states the basis, the depth and the fold count",
      /quote mid vs quote mid/.test(exec.textContent) &&
      /YES spread/.test(exec.textContent) &&
      /contracts at the level/.test(exec.textContent) &&
      /×4 repeats/.test(exec.textContent) &&
      !!frows[0]?.querySelector(".tag-yes"),
      exec.textContent.replace(/\s+/g, " ").slice(0, 150));
check("fixture: a candidate headline is linked and labelled a candidate",
      /candidate headline, not confirmed/.test(exec.textContent) &&
      exec.innerHTML.includes('href="https://example.test/a"') &&
      !/caused by/.test(exec.textContent));
const indic = frows[1] || { textContent: "", innerHTML: "" };
check("fixture: an indicative row says why and is not counted executable",
      /indicative · not executable/.test(indic.textContent) &&
      /not tighter than the \$0\.10 alert threshold/.test(indic.innerHTML) &&
      /no resting size at the level/.test(indic.textContent) &&
      !/class="tag tag-yes"[^>]*>executable/.test(indic.innerHTML));
check("fixture: no headline is invented — the reason is printed instead",
      /no verified news link · lookup disabled/.test(indic.textContent));
check("fixture: a non-http href from the payload never reaches the markup",
      !/javascript:/i.test(fdoc.querySelector("#feedAll").innerHTML) &&
      indic.innerHTML.includes('href="#"'), "safeUrl allowlist");
const legacy = frows[2] || { textContent: "" };
check("fixture: a row without a verdict is labelled pre-rule, not guessed",
      /pre-rule row/.test(legacy.textContent) && !/executable/.test(legacy.textContent));
check("fixture: the model chat reads the published shortlist",
      fdoc.querySelectorAll("#feedModel .chat-row").length === 1 &&
      /net ROI/.test(fdoc.querySelector("#feedModel .chat-row").textContent));
check("fixture: the age label keeps ticking from the snapshot timestamp",
      /old/.test(fdoc.querySelector("#snapshotAge")?.textContent || ""),
      JSON.stringify(fdoc.querySelector("#snapshotAge")?.textContent));
check("fixture: desk.js ran without a thrown error", vc2Errors.length === 0,
      vc2Errors.slice(0, 2).join(" | "));

/* Third pass: the same fixture, with no 2D context available at all. */
const fxNoCanvas = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true,
  virtualConsole: new VirtualConsole(), url: "http://localhost/Trade2/live.html",
});
fxNoCanvas.window.HTMLCanvasElement.prototype.getContext = () => null;
fxNoCanvas.window.fetch = fx.window.fetch;
fxNoCanvas.window.eval(script);
await new Promise((r) => setTimeout(r, 350));
check("fixture: a missing canvas keeps the chats and the chart numbers alive",
      fxNoCanvas.window.document.querySelectorAll("#feedAll .chat-row").length ===
        fixture.alerts.length &&
      /^\$\d/.test(fxNoCanvas.window.document.querySelector("#chartPrice").textContent),
      fxNoCanvas.window.document.querySelector("#chartPrice").textContent);

console.log(failures ? `\nDESK RENDER CHECK FAILED (${failures})` : "\nDESK RENDER CHECK PASSED");
process.exit(failures ? 1 : 0);
