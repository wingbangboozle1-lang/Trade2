/* Runtime check for every page: the JS layer must boot without throwing, and
 * the generated HTML must not leak `undefined`, `NaN` or `[object Object]`.
 * Uses jsdom; run with:  node tools/rendercheck.mjs
 * (CI installs jsdom; locally `npm i jsdom` in a temp dir also works.)
 */
import { JSDOM, VirtualConsole } from "jsdom";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const pages = [
  "index.html", "live.html", "review.html", "methodology.html", "summary.html",
  "categories/gas-prices.html", "categories/elections.html",
  "categories/culture.html", "categories/crypto.html", "categories/golf.html",
];

let failures = 0;
for (const page of pages) {
  const file = path.join(root, page);
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
  w.HTMLCanvasElement.prototype.getContext = () =>
    new Proxy({}, { get: (t, k) => (k === "canvas" ? {} : () => {}), set: () => true });
  w.HTMLCanvasElement.prototype.getBoundingClientRect = () =>
    ({ width: 800, height: 260, top: 0, left: 0 });
  if (fs.existsSync(path.join(root, "assets/desk.js"))) {
    try {
      w.eval(fs.readFileSync(path.join(root, "assets/desk.js"), "utf8"));
    } catch (e) {
      errors.push("eval threw: " + e.message);
    }
  }
  await new Promise((r) => setTimeout(r, 400));
  const bad = [...new Set(w.document.body.textContent.match(/\bundefined\b|\bNaN\b|\[object Object\]/g) || [])];
  const ok = errors.length === 0 && bad.length === 0;
  if (!ok) failures++;
  console.log(`${ok ? "ok  " : "FAIL"} ${page.padEnd(30)} rows=${w.document.querySelectorAll("tr").length} ` +
    `externalLinks=${w.document.querySelectorAll('a[target="_blank"]').length}`);
  errors.slice(0, 3).forEach((e) => console.log("     !", e));
  if (bad.length) console.log("     ! bad tokens:", bad.join(","));
  w.close();
}
process.exit(failures ? 1 : 0);
