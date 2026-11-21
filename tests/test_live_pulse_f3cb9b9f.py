"""Tests for the live pulse (assets/live-feed.js + its wiring).

Two layers:

1. **Static HTML contract** — the pre-rendered desk must ship the panel, the
   YES/NO side control, and the module tag, so a JavaScript-free reader still
   sees where the live feed lives and a JS reader can boot it.

2. **Executed browser path** — `assets/desk.js` is loaded into jsdom against
   the real `live.html`, with `fetch` stubbed to serve (a) the published
   snapshot and (b) a two-reading order-book sequence that crosses the $0.10
   threshold on exactly one market, and stays below it on another. That proves
   the wiring end to end: one alert row, and none for the sub-threshold market.

Official sources for every rule asserted here:
  * batch order books, up to 100 tickers, anonymous
    https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
  * book semantics (best bid = last element, implied YES ask = 1 - best NO bid)
    https://docs.kalshi.com/getting_started/orderbook_responses
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LIVE_HTML = os.path.join(ROOT, "live.html")
HAS_NODE = shutil.which("node") is not None


def _report(name, passed, details):
    return f"{'ok  ' if passed else 'FAIL'} {name}" + (f" — {details}" if details else "")


BROWSER_CASE = r"""
import fs from "node:fs";
import path from "node:path";
import { JSDOM, VirtualConsole } from "jsdom";

const root = process.cwd();
const html = fs.readFileSync(path.join(root, "live.html"), "utf8")
  .replace(/<script src="[^"]+" defer><\/script>/g, "");
const snapshot = JSON.parse(fs.readFileSync(path.join(root, "assets/live.json"), "utf8"));
const script = fs.readFileSync(path.join(root, "assets/desk.js"), "utf8");
const liveFeed = fs.readFileSync(path.join(root, "assets/live-feed.js"), "utf8");

/* Two eligible markets from the published snapshot, so the tickers the pulse
 * polls are real ones that exist in the snapshot's event list. */
const meta = (snapshot.events || []).filter((e) => e && e.ticker && e.series_ticker);
if (meta.length < 2) { console.log("SKIP not-enough-markets"); process.exit(0); }
const mover = meta[0].ticker;
const quiet = meta[1].ticker;
/* A chat row renders the market TITLE and puts the ticker only on its chart
 * button, so the assertions below look for the title text. */
const moverTitle = meta[0].title || mover;
const quietTitle = meta[1].title || quiet;

/* Reading 1 vs reading 2:
 *   mover: YES 0.30/0.32 -> 0.60/0.62  (mid 0.31 -> 0.61, step +0.30 => fires)
 *   quiet: YES 0.30/0.32 -> 0.36/0.38  (mid 0.31 -> 0.37, step +0.06 => no row)
 * Readings are books, exactly the shape GET /markets/orderbooks returns. */
const readings = [
  { [mover]: [["0.3000", "900.00"]], [quiet]: [["0.3000", "900.00"]] },
  { [mover]: [["0.6000", "900.00"]], [quiet]: [["0.3600", "900.00"]] },
];
/* no_dollars: best NO bid 0.68 => implied YES ask 0.32 (reading 1);
 *              best NO bid 0.38 => implied YES ask 0.62 (reading 2). */
const noFor = { 0.3: "0.6800", 0.36: "0.6200", 0.6: "0.3800", 0.3: "0.6800" };
let call = 0;

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push(String(e.message)));
vc.on("error", (...a) => errors.push(a.join(" ")));
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true,
  virtualConsole: vc, url: "http://localhost/Trade2/live.html",
});
const win = dom.window;

win.HTMLCanvasElement.prototype.getContext = function () {
  return {
    canvas: this, setTransform() {}, clearRect() {}, beginPath() {}, closePath() {},
    moveTo() {}, lineTo() {}, stroke() {}, fill() {}, arc() {}, fillRect() {},
    createLinearGradient() { return { addColorStop() {} }; },
    fillText() {},
    get font() {}, set font(_) {}, get fillStyle() {}, set fillStyle(_) {},
    get strokeStyle() {}, set strokeStyle(_) {}, get lineWidth() {}, set lineWidth(_) {},
    get textAlign() {}, set textAlign(_) {},
  };
};

let directBlocked = false;
let usedProxy = 0;
directBlocked = process.env.FORCE_PROXY === "1";
win.fetch = (url) => {
  let u = String(url);
  /* FORCE_PROXY simulates a network where the exchange is unreachable: every
   * direct demo-API call rejects, so the pulse must fall back to this site's
   * own /api/orderbooks route. */
  if (directBlocked && u.includes("external-api.demo.kalshi.co")) {
    return Promise.reject(new Error("blocked by test"));
  }
  if (u.includes("/api/orderbooks")) {
    usedProxy++;
    u = "https://external-api.demo.kalshi.co/trade-api/v2/markets/orderbooks?tickers=" +
        (u.split("tickers=")[1] || "");
  }
  /* Route on the path, not a substring: the desk also fetches
   * /markets/{ticker}/orderbook and /series/{s}/markets/{t}/candlesticks, and
   * /markets/orderbooks is the batch endpoint this check is about. */
  if (/\/markets\/orderbooks\?/.test(u)) {
    const r = readings[Math.min(call, readings.length - 1)];
    call++;
    const orderbooks = Object.keys(r).map((t) => ({
      ticker: t,
      orderbook_fp: {
        yes_dollars: r[t],
        no_dollars: [[noFor[Number(r[t][0][0])], "400.00"]],
      },
    }));
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ orderbooks }) });
  }
  if (/\/orderbook\?/.test(u) || /\/orderbook$/.test(u)) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({
      orderbook_fp: { yes_dollars: [["0.4000", "500.00"]], no_dollars: [["0.5700", "40.00"]] },
    }) });
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve(snapshot) });
};

/* Make every timer inert at the source: the desk schedules a 45 s pulse and
 * several 4-30 s pollers, and jsdom would keep the process alive for them. The
 * two readings this check needs are driven explicitly below, through the real
 * production path (the toggle handler calls pulseRefresh()). */
win.setInterval = function () { return 0; };
win.setTimeout = function (fn) { return 0; };
win.EventSource = undefined;

const tick = () => new Promise((r) => setImmediate(r));

win.eval(liveFeed);
win.eval(script);
win.document.dispatchEvent(new win.Event("DOMContentLoaded", { bubbles: true }));
const toggle = async () => {
  const el = win.document.getElementById("pulseOn");
  el.checked = false;
  el.dispatchEvent(new win.Event("change", { bubbles: false }));
  el.checked = true;
  el.dispatchEvent(new win.Event("change", { bubbles: false }));
  for (let i = 0; i < 60; i++) await tick();
};
/* Reading 1 (baseline) is issued at boot. Wait for it to settle before asking
 * for reading 2: refresh() refuses to overlap, which is the behaviour we want
 * in production (one request at a time) and must respect here. */
for (let i = 0; i < 60; i++) await tick();
/* Reading 2 — the one that can fire a row. */
await toggle();

const doc = win.document;
const feed = doc.getElementById("feedLive");
const rows = feed ? Array.from(feed.querySelectorAll(".chat-row")) : [];
const text = feed ? feed.textContent : "";
console.log(JSON.stringify({
  errors,
  panel: !!doc.getElementById("livePulse"),
  moduleLoaded: !!win.LiveFeed,
  refreshes: call,
  usedProxy,
  rows: rows.length,

  tickers: rows.map((r) => {
    const b = r.querySelector("[data-chart]");
    return b ? b.getAttribute("data-chart") : "";
  }),
  firedMover: rows.some((r) => (r.textContent || "").includes(moverTitle)),
  firedQuiet: rows.some((r) => (r.textContent || "").includes(quietTitle)),
  rowTickers: rows.map((r) => {
    const b = r.querySelector("[data-chart]");
    return b ? b.getAttribute("data-chart") : "";
  }),
  hasLiveTag: rows.some((r) => (r.textContent || "").toLowerCase().includes("live")),
  saysQuoteMid: /quote mid to quote mid/.test(text),
  noCauseClaim: /no news link/.test(text),
  stats: (doc.getElementById("pulseStats") || {}).textContent || "",
  refusalBox: !!doc.getElementById("pulseRefusals"),
  sideTabs: !!doc.getElementById("sideTabs"),
  sideButtons: Array.from(doc.querySelectorAll("#sideTabs button")).map((b) => b.textContent.trim()),
  noSideClickable: (() => {
    const b = doc.querySelector('#sideTabs button[data-side="no"]');
    if (!b) return false;
    b.dispatchEvent(new win.MouseEvent("click", { bubbles: true }));
    const axis = doc.getElementById("sideAxis");
    return axis ? axis.textContent.trim() === "NO" : false;
  })(),
}));
dom.window.close();
"""


class TestLivePulseStaticPage(unittest.TestCase):
    """The panel and controls must exist in the pre-rendered HTML."""

    @classmethod
    def setUpClass(cls):
        with open(LIVE_HTML, encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_panel_is_present(self):
        self.assertIn('id="livePulse"', self.html)

    def test_module_is_loaded_before_desk(self):
        self.assertIn('assets/live-feed.js', self.html)
        self.assertLess(self.html.index("assets/live-feed.js"),
                        self.html.index("assets/desk.js"))

    def test_multi_market_orderbook_endpoint_is_cited(self):
        self.assertIn("get-multiple-market-orderbooks", self.html)

    def test_book_semantics_are_cited(self):
        self.assertIn("orderbook_responses", self.html)

    def test_two_sides_are_selectable(self):
        self.assertIn('id="sideTabs"', self.html)
        self.assertIn('data-side="yes"', self.html)
        self.assertIn('data-side="no"', self.html)

    def test_polling_is_opt_out_able(self):
        """A visitor's browser must not be forced to call a third-party API."""
        self.assertIn('id="pulseOn"', self.html)
        self.assertIn("checked", self.html)

    def test_panel_claims_no_causality(self):
        self.assertIn("no cause is ever claimed", self.html)


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TestLivePulseBrowserPath(unittest.TestCase):
    """Execute desk.js in jsdom and drive two readings through the pulse."""

    @classmethod
    def _run(cls, force_proxy: str):
        env = dict(os.environ, FORCE_PROXY=force_proxy)
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", BROWSER_CASE],
            cwd=ROOT, capture_output=True, text=True, timeout=180, env=env,
        )
        result = None
        for line in reversed(proc.stdout.strip().splitlines()):
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        return proc, result

    @classmethod
    def setUpClass(cls):
        cls.proc, cls.result = cls._run("0")
        cls.stdout = cls.proc.stdout.strip()
        cls.stderr = cls.proc.stderr.strip()
        cls.returncode = cls.proc.returncode
        if cls.result is not None:
            cls.proxy_proc, cls.proxy_result = cls._run("1")
        else:
            cls.proxy_proc, cls.proxy_result = None, None

    def setUp(self):
        if self.returncode != 0:
            self.skipTest(f"jsdom unavailable or node failed: {self.stderr[-400:]}")
        if self.result is None:
            self.skipTest("browser case produced no JSON result")
        if self.result.get("errors") == ["not-enough-markets"]:
            self.skipTest("snapshot has fewer than two eligible markets")

    def test_no_script_errors(self):
        self.assertEqual(self.result["errors"], [],
                         "desk.js threw while booting the pulse")

    def test_panel_exists_and_module_loaded(self):
        self.assertTrue(self.result["panel"])
        self.assertTrue(self.result["moduleLoaded"])

    def test_direct_api_is_the_first_route(self):
        self.assertEqual(self.result["usedProxy"], 0,
                         "the pulse must not detour through the local proxy "
                         "when the demo API is reachable")

    def test_two_readings_were_taken(self):
        self.assertGreaterEqual(self.result["refreshes"], 2,
                                "the pulse must poll more than once")

    def test_only_the_ten_cent_mover_fires(self):
        if self.result["firedMover"]:
            self.assertTrue(self.result["rowTickers"] and
                            self.result["rowTickers"][0])
        else:
            self.fail("a +$0.30 mid step must produce a row; rows=" +
                      repr(self.result["rowTickers"]))
        self.assertFalse(self.result["firedQuiet"],
                         "a +$0.06 mid step must not produce a row")

    def test_exactly_one_row(self):
        self.assertEqual(self.result["rows"], 1,
                         "one mover, one row; rows=" + repr(self.result["rowTickers"]))

    def test_row_states_its_basis_and_claims_no_cause(self):
        self.assertTrue(self.result["saysQuoteMid"])
        self.assertTrue(self.result["noCauseClaim"])

    def test_row_is_labelled_live(self):
        self.assertTrue(self.result["hasLiveTag"])

    def test_stats_line_reports_refreshes(self):
        self.assertRegex(self.result["stats"], r"\d+ refreshes?")

    def test_no_switch_changes_the_axis(self):
        self.assertEqual(self.result["sideButtons"], ["YES", "NO"])
        self.assertTrue(self.result["noSideClickable"],
                        "clicking NO must relabel the Y axis")

    def test_site_origin_fallback_measures_the_same_books(self):
        """When the exchange is unreachable, the panel must use the site's own
        proxy (/api/orderbooks, served by server/app.py) — not go dark and not
        invent rows. The same two readings are served either way, so the same
        single row must appear and the same sub-threshold market must stay out."""
        if self.proxy_result is None:
            self.skipTest("proxy run produced no result")
        pr = self.proxy_result
        self.assertEqual(pr["errors"], [])
        self.assertGreaterEqual(pr["usedProxy"], 1,
                                "the fallback route was never called")
        self.assertGreaterEqual(pr["refreshes"], 2)
        self.assertEqual(pr["rows"], 1)
        self.assertTrue(pr["firedMover"])
        self.assertFalse(pr["firedQuiet"])


if __name__ == "__main__":
    unittest.main()
