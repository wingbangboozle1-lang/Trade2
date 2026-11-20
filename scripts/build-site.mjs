#!/usr/bin/env node
// Builds the static site into _site/ and checks it before deploy.
//   node scripts/build-site.mjs [--out _site]
// 1) wraps each fragment in site/pages/*.html with the shared header/nav/footer (one template, so nav never drifts)
// 2) copies site/assets/ and config JSON (sources, flags, topics) into _site/data/
// 3) checks every internal link and asset reference resolves, and every source/flag entry has a link
// Exits non-zero on any failure, so a broken site is never deployed.

import { readFile, writeFile, mkdir, readdir, cp, copyFile } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const outIdx = argv.indexOf('--out');
const OUT = path.resolve(ROOT, outIdx >= 0 ? argv[outIdx + 1] : '_site');

const NAV = [
  ['index.html', 'Home'],
  ['gas.html', 'Gas prices'],
  ['elections.html', 'Elections'],
  ['culture.html', 'Culture'],
  ['crypto.html', 'Crypto'],
  ['golf.html', 'Golf'],
  ['alerts.html', 'Live alerts'],
  ['trades.html', 'Trades & analysis'],
  ['resolved.html', 'Resolved'],
  ['summary.html', 'Executive summary'],
  ['suggestions.html', 'Suggestions'],
  ['sources.html', 'Sources'],
  ['flagged.html', '⚠ Flagged for review'],
];

const errors = [];

async function main() {
  await mkdir(OUT, { recursive: true });
  const frag = path.join(ROOT, 'site', 'pages');
  const files = (await readdir(frag)).filter((f) => f.endsWith('.html')).sort();
  const built = [];
  for (const f of files) {
    const raw = await readFile(path.join(frag, f), 'utf8');
    const m = raw.match(/^<!--meta:\s*(\{.*?\})\s*-->\n?/);
    if (!m) {
      errors.push(`${f}: missing <!--meta: {...}--> first line`);
      continue;
    }
    const meta = JSON.parse(m[1]);
    const body = raw.slice(m[0].length);
    const html = template({ ...meta, body });
    await writeFile(path.join(OUT, meta.out), html);
    built.push(meta.out);
  }
  for (const [href] of NAV) if (!built.includes(href)) errors.push(`nav target not built: ${href}`);

  await cp(path.join(ROOT, 'site', 'assets'), path.join(OUT, 'assets'), { recursive: true });
  await mkdir(path.join(OUT, 'data'), { recursive: true });
  for (const f of ['sources.json', 'flags.json', 'topics.json']) {
    await copyFile(path.join(ROOT, 'config', f), path.join(OUT, 'data', f));
  }
  await writeFile(path.join(OUT, '.nojekyll'), '');

  checkConfig();
  await checkLinks(OUT);

  if (errors.length) {
    console.error('BUILD FAILED:\n- ' + errors.join('\n- '));
    process.exit(1);
  }
  console.log(`built ${built.length} pages into ${path.relative(ROOT, OUT) || '.'} · links and config OK`);
}

function template({ out, page, topic, title, body }) {
  const pageTitle = title || 'Kalshi topic dashboard';
  const nav = NAV.map(([href, label]) => `<a href="${href}">${label}</a>`).join('');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${pageTitle}</title>
<meta name="description" content="Live Kalshi prices, liquidity, price-move alerts, resolved outcomes and simulated trades for gas prices, elections, culture, crypto and golf. Read-only public data.">
<link rel="stylesheet" href="assets/style.css">
</head>
<body data-page="${page}"${topic ? ` data-topic="${topic}"` : ''}>
<header class="top"><div class="row"><a class="brand" href="index.html">Kalshi topic dashboard</a><nav>${nav}</nav></div></header>
<main>
${body}
</main>
<footer>
<p>Data: Kalshi public Trade API (read-only), fetched by a scheduled GitHub Actions job. Not financial advice. Simulated trades are paper trades. Every value links to its official source; unverified items are on <a href="flagged.html">Flagged for review</a>. Fee formulas: <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener">Kalshi Fee Schedule (PDF)</a>.</p>
</footer>
<script src="assets/app.js"></script>
</body>
</html>
`;
}

function checkConfig() {
  const src = JSON.parse(readFileSyncSafe(path.join(ROOT, 'config', 'sources.json')));
  for (const s of src.sources) {
    if (!/^https:\/\//.test(s.url)) errors.push(`source ${s.id}: url must be https`);
    if (!s.verification) errors.push(`source ${s.id}: missing verification note`);
  }
  const flags = JSON.parse(readFileSyncSafe(path.join(ROOT, 'config', 'flags.json')));
  const ids = new Set();
  for (const f of flags.flags) {
    if (ids.has(f.id)) errors.push(`flag ${f.id}: duplicate id`);
    ids.add(f.id);
    if (!['irregularity', 'unverified', 'decision', 'blocker'].includes(f.type)) errors.push(`flag ${f.id}: bad type ${f.type}`);
    for (const l of f.links || []) if (!/^https:\/\//.test(l.url)) errors.push(`flag ${f.id}: link must be https: ${l.url}`);
  }
}

function readFileSyncSafe(p) {
  return readFileSync(p, 'utf8');
}

async function checkLinks(dir) {
  const htmlFiles = (await readdir(dir)).filter((f) => f.endsWith('.html'));
  for (const f of htmlFiles) {
    const html = await readFile(path.join(dir, f), 'utf8');
    const refs = [...html.matchAll(/(?:href|src)="([^"]+)"/g)].map((m) => m[1]);
    for (const r of refs) {
      if (/^(https?:|mailto:|#|data:)/.test(r)) continue;
      const clean = r.split('#')[0].split('?')[0];
      if (!clean) continue;
      const target = path.join(dir, clean);
      if (!existsSync(target)) errors.push(`${f}: broken internal link → ${r}`);
    }
    // every page must include the nav (so users can always move between sections)
    if (!html.includes('class="top"')) errors.push(`${f}: missing header`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
