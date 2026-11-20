/* jsdom smoke test: loads each dashboard page with fixture data and asserts the
 * key UI regions actually rendered, and that no uncaught JS errors occurred.
 *
 *   node test/site_smoke.mjs <fixture-data-dir>
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DOCS = path.join(ROOT, "docs");
const FIX = process.argv[2];
if (!FIX || !fs.existsSync(FIX)) {
  console.error("usage: node test/site_smoke.mjs <fixture-data-dir>");
  process.exit(2);
}

function fixtureJSON(rel) {
  const clean = rel.split("?")[0].replace(/^data\//, "");
  const p = path.join(FIX, clean);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

async function loadPage(file, { topic } = {}) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", e => errors.push("jsdomError: " + e.message));
  vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

  let html = fs.readFileSync(path.join(DOCS, file), "utf8");
  // jsdom does not load external scripts unless a resource loader is configured;
  // inline app.js so the real front-end code executes in the test DOM.
  const appJs = fs.readFileSync(path.join(DOCS, "assets", "app.js"), "utf8");
  // NB: must use a function replacement — a string replacement would interpret
  // $$, $', $& sequences that occur throughout app.js and corrupt the source.
  html = html.replace(
    '<script src="assets/app.js"></script>',
    () => "<script>\n" + appJs + "\n</script>"
  );
  const dom = new JSDOM(html, {
    url: "https://example.test/Trade2/" + file,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.devicePixelRatio = 1;
      // jsdom has no canvas backend and logs "Not implemented" for getContext();
      // provide a no-op 2D context so the drawing code paths actually execute.
      const makeCtx = () =>
        new Proxy({}, {
          get(t, p) {
            if (p in t) return t[p];
            return () => undefined;
          },
          set(t, p, v) { t[p] = v; return true; },
        });
      window.HTMLCanvasElement.prototype.getContext = function () { return makeCtx(); };
      // serve fixture JSON for any relative data/ fetch
      window.fetch = async url => {
        const data = fixtureJSON(String(url));
        if (!data) return { ok: false, status: 404, json: async () => null };
        return { ok: true, status: 200, json: async () => data };
      };
      if (topic) window.__TOPIC = topic;
    },
  });
  // allow async refresh() to finish
  await new Promise(r => setTimeout(r, 250));
  return { dom, errors };
}

const checks = [];
function ok(name, cond, detail) {
  checks.push({ name, pass: !!cond, detail });
}

// ---- index ----
{
  const { dom, errors } = await loadPage("index.html");
  const d = dom.window.document;
  ok("index: no JS errors", errors.length === 0, errors.join(" | "));
  ok("index: stat cards rendered", d.querySelectorAll("#stats .stat").length === 4,
     d.querySelectorAll("#stats .stat").length);
  ok("index: 5 topic cards", d.querySelectorAll("#topic-cards .topic-card").length === 5);
  ok("index: top-markets table rows", d.querySelectorAll("#top-markets tbody tr").length > 0,
     d.querySelectorAll("#top-markets tbody tr").length);
  ok("index: all-event chat rendered", /msg|empty/.test(d.querySelector("#feed-all").innerHTML));
  ok("index: roi chat rendered", /msg|empty/.test(d.querySelector("#feed-roi").innerHTML));
  ok("index: freshness shows data", /data:/.test(d.querySelector("#freshness").textContent));
  const rows = Array.from(d.querySelectorAll("#top-markets tbody tr"));
  ok("index: every market row has an official source link",
     rows.length > 0 && rows.every(r => r.querySelector('a[href*="external-api.demo.kalshi.co"]')),
     rows.length + " rows");
  dom.window.close();
}

// ---- topic page (golf) ----
{
  const { dom, errors } = await loadPage("golf.html");
  const d = dom.window.document;
  ok("golf: no JS errors", errors.length === 0, errors.join(" | "));
  ok("golf: markets table rows", d.querySelectorAll("#markets tbody tr").length > 0,
     d.querySelectorAll("#markets tbody tr").length);
  ok("golf: market picker populated", d.querySelectorAll("#pick-market option").length > 0);
  ok("golf: alerts section rendered", d.querySelector("#topic-alerts").innerHTML.length > 20);
  ok("golf: resolutions section rendered", d.querySelector("#topic-resolutions").innerHTML.length > 10);
  ok("golf: window toggle present", d.querySelectorAll(".seg button[data-win]").length === 3);
  dom.window.close();
}

// ---- portfolio ----
{
  const { dom, errors } = await loadPage("portfolio.html");
  const d = dom.window.document;
  ok("portfolio: no JS errors", errors.length === 0, errors.join(" | "));
  ok("portfolio: stat cards", d.querySelectorAll("#pf-stats .stat").length === 4,
     d.querySelectorAll("#pf-stats .stat").length);
  ok("portfolio: strategy stats table", d.querySelectorAll("#stats-by-strategy tbody tr").length > 0,
     d.querySelectorAll("#stats-by-strategy tbody tr").length);
  ok("portfolio: trade type stats table", d.querySelectorAll("#stats-by-type tbody tr").length > 0);
  ok("portfolio: trade log table", !!d.querySelector("#trade-log tbody tr") ||
     /No trades/.test(d.querySelector("#trade-log").innerHTML));
  ok("portfolio: fee source linked",
     d.querySelector("#pf-note").innerHTML.includes("kalshi.com/docs/kalshi-fee-schedule.pdf"));
  dom.window.close();
}

// ---- flagged ----
{
  const { dom, errors } = await loadPage("flagged.html");
  const d = dom.window.document;
  ok("flagged: no JS errors", errors.length === 0, errors.join(" | "));
  ok("flagged: curated table >= 9 rows", d.querySelectorAll("table.data tbody tr").length >= 9,
     d.querySelectorAll("table.data tbody tr").length);
  ok("flagged: dynamic flags section rendered", d.querySelector("#dynamic-flags").innerHTML.length > 20);
  ok("flagged: count populated", /\d/.test(d.querySelector("#flag-count").textContent));
  dom.window.close();
}

// ---- summary (static content) ----
{
  const { dom, errors } = await loadPage("summary.html");
  const d = dom.window.document;
  ok("summary: no JS errors", errors.length === 0, errors.join(" | "));
  ok("summary: fact table has official links", d.querySelectorAll('a[href*="docs.kalshi.com"]').length >= 4);
  ok("summary: fee pdf linked", d.body.innerHTML.includes("kalshi.com/docs/kalshi-fee-schedule.pdf"));
  dom.window.close();
}

let failed = 0;
for (const c of checks) {
  console.log(`${c.pass ? "OK " : "FAIL"} ${c.name}${c.detail ? "  [" + c.detail + "]" : ""}`);
  if (!c.pass) failed++;
}
console.log(failed ? `${failed} FAILED` : "ALL SITE SMOKE CHECKS PASSED");
process.exit(failed ? 1 : 0);
