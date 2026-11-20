/* Render check for the ROOT site (index, live desk, topic pages and the
 * research pages).
 *
 * `tools/rendercheck.mjs` covers the same ground, but that file is owned by
 * another session that is repairing its jsdom setup, so this one is scoped to
 * the root pages only and stubs the network as an offline miss. That is the
 * point of the test: the site must render completely from the snapshot that
 * is embedded in the page, with no network at all.
 *
 *   node test/root_render.mjs
 *
 * Exits non-zero on the first page that throws or leaks an undefined value.
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const PAGES = [
  "index.html",
  "live.html",
  "resolutions.html",
  "trades.html",
  "suggestions.html",
  "review.html",
  "methodology.html",
  "summary.html",
  "categories/gas-prices.html",
  "categories/elections.html",
  "categories/culture.html",
  "categories/crypto.html",
  "categories/golf.html",
];

// Every page must offer a way to reach the other pages, so a reader is
// never stranded. These are the links the navigation is expected to carry.
const REQUIRED_LINKS = [
  "index.html",
  "live.html",
  "resolutions.html",
  "trades.html",
  "suggestions.html",
  "methodology.html",
  "review.html",
];

let failures = 0;

function offlineFetch() {
  // Every fetch fails, exactly like a browser with no connection. The page
  // must still be complete and correct because it was pre-rendered.
  return Promise.reject(new Error("offline"));
}

for (const page of PAGES) {
  const file = path.join(ROOT, page);
  if (!fs.existsSync(file)) {
    console.log(`FAIL ${page} (missing)`);
    failures++;
    continue;
  }
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(e.message));
  const dom = new JSDOM(fs.readFileSync(file, "utf8"), {
    url: `http://127.0.0.1:8137/${page}`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const w = dom.window;
  w.fetch = offlineFetch;
  w.HTMLCanvasElement.prototype.getContext = () =>
    new Proxy({}, { get: (t, k) => (k === "canvas" ? {} : () => {}), set: () => true });
  w.HTMLCanvasElement.prototype.getBoundingClientRect = () =>
    ({ width: 800, height: 260, top: 0, left: 0 });

  for (const script of ["assets/alerts-view.js", "assets/nav.js", "assets/desk.js"]) {
    const scriptPath = path.join(ROOT, script);
    if (!fs.existsSync(scriptPath)) continue;
    try {
      w.eval(fs.readFileSync(scriptPath, "utf8"));
    } catch (e) {
      errors.push(`${script} eval threw: ${e.message}`);
    }
  }
  await new Promise((r) => setTimeout(r, 400));

  const body = w.document.body.textContent;
  const bad = [
    ...new Set(body.match(/\bundefined\b|\bNaN\b|\[object Object\]/g) || []),
  ];

  // Navigation completeness, checked on the landing page only.
  const navMissing = [];
  if (page === "index.html") {
    const html = w.document.documentElement.innerHTML;
    for (const href of REQUIRED_LINKS) {
      if (!html.includes(`"${href}"`)) navMissing.push(href);
    }
  }

  // Every table row that carries a market or resolution must carry a source
  // link, so a reviewer can check it against the official API in one click.
  let rowsWithoutSource = 0;
  for (const row of w.document.querySelectorAll("table tr")) {
    const text = row.textContent || "";
    if (!/API|↗/.test(text)) continue;
    if (!row.querySelector("a[href]")) rowsWithoutSource++;
  }

  const ok =
    errors.length === 0 && bad.length === 0 && navMissing.length === 0 &&
    rowsWithoutSource === 0;
  if (!ok) failures++;
  console.log(
    `${ok ? "ok  " : "FAIL"} ${page.padEnd(28)} rows=${w.document.querySelectorAll("tr").length} ` +
      `links=${w.document.querySelectorAll("a[href]").length}`,
  );
  errors.slice(0, 3).forEach((e) => console.log("     !", e));
  if (bad.length) console.log("     ! bad tokens:", bad.join(","));
  if (navMissing.length) console.log("     ! nav missing:", navMissing.join(","));
  if (rowsWithoutSource) {
    console.log("     ! rows with a source marker but no link:", rowsWithoutSource);
  }
  w.close();
}

console.log(failures ? `RENDER CHECK FAILED (${failures})` : "RENDER CHECK PASSED");
process.exit(failures ? 1 : 0);
