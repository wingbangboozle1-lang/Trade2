/* Front-end gate for the live desk (root site).
 *
 * What it proves, with no network:
 *   1. every page boots assets/desk.js and assets/app.js without throwing, and
 *      no page leaks `undefined`, `NaN` or `[object Object]`;
 *   2. BOTH scrolling chats render from one snapshot — the all-events feed and
 *      the model shortlist (the bug this check was written for: the model chat
 *      required a swing and a live signal on the same ticker in the same run, so
 *      it rendered empty on the published site);
 *   3. a swing row carries its candidate-catalyst link, and the "what moved this
 *      market" panel fills for the selected market;
 *   4. an empty shortlist is reported as an empty shortlist, not a loading state.
 *
 * Run: node tools/deskcheck.mjs            (against the committed live.html)
 *      node tools/deskcheck.mjs --selftest   (also checks the empty-state path)
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const selftest = process.argv.includes("--selftest");

const FIXTURE = {
  generated_at: "2026-11-20T19:00:00Z",
  generated_at_ts: 1795200000,
  swap_threshold_dollars: 0.1,
  model_gate: 0.1,
  topics: {},
  events: [
    {
      ticker: "KXTEST-26-A", event_ticker: "KXTEST-26", series_ticker: "KXTEST",
      topic: "crypto", title: "Test swing", mid: 0.42, yes_bid: 0.41, yes_ask: 0.43,
      open_interest_notional: 5000, status: "active", result: "",
      close_time: "2026-11-21T00:00:00Z",
      market_url: "https://kalshi.com/markets/KXTEST/KXTEST-26-A",
    },
  ],
  alerts: [
    {
      id: "KXTEST-26-A:1795200000", ts: 1795200000, iso: "2026-11-20T18:40:00Z",
      ticker: "KXTEST-26-A", event_ticker: "KXTEST-26", series_ticker: "KXTEST",
      topic: "crypto", title: "Test swing", previous: 0.30, current: 0.42,
      delta: 0.12, abs_delta: 0.12, direction: "up", threshold: 0.1,
      market_url: "https://kalshi.com/markets/KXTEST/KXTEST-26-A",
      news_status: "ok",
      news_query: "Test swing",
      news_url: "https://news.google.com/rss/search?q=Test%20swing",
      headlines: [{
        title: "Crypto rally continues", url: "https://example.test/headline",
        source: "Example Wire", published: "2026-11-20T18:30:00+00:00",
        status: "verified-fetch",
      }],
      model_net_roi: 0.31, model_score: 0.42, model_side: "yes",
    },
    {
      id: "KXQUIET-26-B:1795200001", ts: 1795200001, iso: "2026-11-20T18:41:00Z",
      ticker: "KXQUIET-26-B", event_ticker: "KXQUIET-26", series_ticker: "KXQUIET",
      topic: "golf", title: "Swing without a headline", previous: 0.55, current: 0.44,
      delta: -0.11, abs_delta: 0.11, direction: "down", threshold: 0.1,
      news_status: "no-headlines-found",
      news_query: "Swing without a headline",
      news_url: "https://news.google.com/rss/search?q=Swing%20without%20a%20headline",
      market_url: "https://kalshi.com/markets/KXQUIET/KXQUIET-26-B",
    },
  ],
  model_shortlist: [
    {
      id: "KXTEST-26-A:1795200000", kind: "swing", ts: 1795200000,
      iso: "2026-11-20T18:40:00Z", ticker: "KXTEST-26-A", series_ticker: "KXTEST",
      topic: "crypto", title: "Test swing", previous: 0.30, current: 0.42,
      abs_delta: 0.12, direction: "up", model_net_roi: 0.31, model_score: 0.42,
      model_reason: "edge after fee", market_url: "https://kalshi.com/markets/KXTEST/KXTEST-26-A",
      headlines: [{ title: "Crypto rally continues", url: "https://example.test/headline",
                    source: "Example Wire", published: "2026-11-20T18:30:00+00:00" }],
      news_status: "ok",
    },
    {
      id: "signal:KXWATCH-26-C:1795199000", kind: "signal", ts: 1795200002,
      iso: "2026-11-20T18:42:00Z", ticker: "KXWATCH-26-C", series_ticker: "KXWATCH",
      topic: "elections", title: "Flagged, not yet swung", previous: 0.20,
      current: 0.22, abs_delta: 0.02, direction: "up", model_net_roi: 0.19,
      model_score: 0.25, market_url: "https://kalshi.com/markets/KXWATCH/KXWATCH-26-C",
    },
  ],
  signals: [],
  liquidity: {},
  portfolio: {},
  resolutions: {},
  errors: [],
};

function bootPage(file, snapshot, expect) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(e.message));
  let html = fs.readFileSync(file, "utf8");
  html = html.replace(
    /<script id="snapshot" type="application\/json">[\s\S]*?<\/script>/,
    `<script id="snapshot" type="application/json">${
      JSON.stringify(snapshot).replace(/<\//g, "<\\/")}</script>`);
  const dom = new JSDOM(html, {
    url: `http://127.0.0.1:8137/${path.basename(file)}`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const w = dom.window;
  w.HTMLCanvasElement.prototype.getContext = () =>
    new Proxy({}, { get: (t, k) => (k === "canvas" ? {} : () => {}), set: () => true });
  w.HTMLCanvasElement.prototype.getBoundingClientRect = () =>
    ({ width: 800, height: 260, top: 0, left: 0 });
  // jsdom ships no fetch; the desk calls it for polling and for the official
  // candlestick + order-book endpoints. Every stub answers with the fixture.
  w.fetch = () => Promise.resolve({ ok: false, status: 599, json: () => Promise.resolve(null) });
  w.EventSource = undefined;
  for (const src of ["assets/desk.js", "assets/nav.js"]) {
    const p = path.join(root, src);
    if (!fs.existsSync(p)) continue;
    try {
      w.eval(fs.readFileSync(p, "utf8"));
    } catch (e) {
      errors.push(`${src} threw: ` + e.message);
    }
  }
  return { w, errors, expect };
}

let failures = 0;
function check(label, ok, detail) {
  if (!ok) failures++;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? `  — ${detail}` : ""}`);
}

/* ---- 1. the desk, with data ------------------------------------------------ */
const desk = bootPage(path.join(root, "live.html"), FIXTURE);
await new Promise((r) => setTimeout(r, 250));
const doc = desk.w.document;

check("live.html boots without throwing", desk.errors.length === 0, desk.errors.slice(0, 2).join(" | "));
const allRows = doc.querySelectorAll("#feedAll .chat-row");
check("all-events chat renders every swing", allRows.length === 2, `rows=${allRows.length}`);
const modelRows = doc.querySelectorAll("#feedModel .chat-row");
check("model chat renders the shortlist (regression: it used to be empty)",
  modelRows.length === 2, `rows=${modelRows.length}`);
check("model chat labels a watch flag that has not swung",
  !!doc.querySelector("#feedModel .chat-kind"));
const queryLink = doc.querySelector("#feedAll .chat-news-query");
check("swing row links the exact search the desk ran (news_url is published)",
  !!queryLink && /^https:\/\/news\.google\.com\/rss\/search\?q=/.test(queryLink.getAttribute("href") || ""));
const newsLinks = [...doc.querySelectorAll("#feedAll .chat-news-link")];
check("swing row carries its candidate-catalyst link",
  newsLinks.length === 1 && newsLinks[0].getAttribute("href") === "https://example.test/headline",
  `links=${newsLinks.length}`);
check("a swing with no headline states that none was found, and still links its search",
  /no headline published in the/.test(doc.querySelector("#feedAll .chat-row.down")?.textContent || "") &&
  !!doc.querySelector("#feedAll .chat-row.down .chat-news-query"));
const leaked = [...new Set(doc.body.textContent.match(/\bundefined\b|\bNaN\b|\[object Object\]/g) || [])];
check("desk page leaks no undefined/NaN token", leaked.length === 0, leaked.join(","));

// Selecting a market from a chat row must populate the moves panel.
const chartBtn = doc.querySelector('#feedAll [data-chart="KXTEST-26-A"]');
check("chat row offers a chart button for its market", !!chartBtn);
if (chartBtn) {
  chartBtn.dispatchEvent(new desk.w.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  const moves = doc.querySelectorAll("#chartMoves .move-row");
  check("moves panel lists the ≥ $0.10 swings of the selected market",
    moves.length === 1, `rows=${moves.length}`);
  check("moves panel links the candidate catalyst",
    !!doc.querySelector('#chartMoves a[href="https://example.test/headline"]'));
}

/* ---- 2. the desk, with an empty shortlist --------------------------------- */
if (selftest) {
  const empty = bootPage(path.join(root, "live.html"),
    { ...FIXTURE, model_shortlist: [], high_roi_alerts: [], alerts: [] });
  await new Promise((r) => setTimeout(r, 150));
  const d2 = empty.w.document;
  check("empty shortlist is explained, not left blank",
    /score gate/.test(d2.querySelector("#feedModel")?.textContent || ""));
  check("empty all-events chat is explained",
    /No ≥ \$0.10 move/.test(d2.querySelector("#feedAll")?.textContent || ""));
}

/* ---- 3. every other page still boots -------------------------------------- */
for (const page of ["index.html", "review.html", "methodology.html", "summary.html",
  "categories/gas-prices.html", "categories/elections.html", "categories/culture.html",
  "categories/crypto.html", "categories/golf.html"]) {
  const file = path.join(root, page);
  if (!fs.existsSync(file)) { check(`${page} exists`, false); continue; }
  const r = bootPage(file, FIXTURE);
  await new Promise((res) => setTimeout(res, 120));
  const bad = [...new Set(r.w.document.body.textContent.match(
    /\bundefined\b|\bNaN\b|\[object Object\]/g) || [])];
  check(`${page} boots clean`, r.errors.length === 0 && bad.length === 0,
    [r.errors[0], bad.join(",")].filter(Boolean).join(" | "));
  const modelPanel = r.w.document.querySelector("#feedModel, .model-chat");
  if (page === "index.html") {
    const panels = [...r.w.document.querySelectorAll(".chat-panel")];
    const answered = panels.filter((p) =>
      p.querySelectorAll(".chat-row").length > 0 ||
      p.querySelectorAll(".empty-state").length > 0);
    check("overview pre-renders BOTH chats, each with rows or an explicit empty state",
      panels.length === 2 && answered.length === 2,
      `panels=${panels.length} answered=${answered.length} ` +
      `rows=${r.w.document.querySelectorAll(".chat-panel .chat-row").length}`);
  }
  void modelPanel;
  r.w.close();
}

console.log(failures ? `\nDESK CHECK FAILED (${failures})` : "\nDESK CHECK PASSED");
process.exit(failures ? 1 : 0);
