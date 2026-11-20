#!/usr/bin/env node
/**
 * Site integrity check.
 *
 * 1. Every internal link and asset reference in the published HTML must resolve
 *    to a file that exists in the published tree.
 * 2. Every external link must point at an official Kalshi / GitHub host.
 * 3. Every JSON file the site fetches must exist and parse.
 * 4. The JavaScript modules must parse as ES modules.
 *
 * Usage: node tools/check-site.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const DOCS = path.join(ROOT, 'docs');

const ALLOWED_HOSTS = [
  'kalshi.com', 'www.kalshi.com', 'docs.kalshi.com', 'help.kalshi.com',
  'github.com', 'www.github.com', 'docs.github.com', 'gist.github.com',
  'raw.githubusercontent.com', 'pages.github.com', 'developer.mozilla.org',
  // Official Kalshi API hosts and the official SDK package page.
  'external-api.demo.kalshi.co', 'demo-api.kalshi.co', 'external-api-ws.demo.kalshi.co',
  'demo-api.kalshi.co', 'external-api.kalshi.com', 'api.elections.kalshi.com',
  'www.npmjs.com',
];

const problems = [];
const notes = [];

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

function resolveInternal(fromFile, href) {
  const clean = href.split('#')[0].split('?')[0];
  if (!clean) return null;
  const target = path.resolve(path.dirname(fromFile), clean);
  if (fs.existsSync(target)) {
    if (fs.statSync(target).isDirectory()) {
      const index = path.join(target, 'index.html');
      return fs.existsSync(index) ? index : null;
    }
    return target;
  }
  // directory-style URLs (e.g. topics/gas.html -> topics/gas/index.html)
  const index = path.join(target, 'index.html');
  if (fs.existsSync(index)) return index;
  return null;
}

const htmlFiles = walk(DOCS).filter((f) => f.endsWith('.html'));
let internalLinks = 0;
let externalLinks = 0;

for (const file of htmlFiles) {
  const html = fs.readFileSync(file, 'utf8');
  const refs = [...html.matchAll(/(?:href|src)\s*=\s*"([^"]+)"/g)].map((m) => m[1]);
  for (const ref of refs) {
    if (ref.startsWith('http://') || ref.startsWith('https://')) {
      externalLinks += 1;
      let host = '';
      try { host = new URL(ref).hostname; } catch { host = ''; }
      if (!ALLOWED_HOSTS.includes(host)) {
        problems.push(`${path.relative(ROOT, file)}: external link to non-allowlisted host "${host}" — ${ref}`);
      }
      continue;
    }
    if (ref.startsWith('data:') || ref.startsWith('mailto:') || ref.startsWith('#')) continue;
    internalLinks += 1;
    if (!resolveInternal(file, ref)) {
      problems.push(`${path.relative(ROOT, file)}: broken internal link — ${ref}`);
    }
  }
}

// data files the site fetches
const REQUIRED_DATA = [
  'manifest.json', 'markets.json', 'events.json', 'orderbooks.json', 'candles.json',
  'candles_hourly.json', 'market_trades.json', 'prices.json', 'alerts.json',
  'trades.json', 'portfolio.json', 'collector-health.json',
];
for (const name of REQUIRED_DATA) {
  const file = path.join(DOCS, 'data', name);
  if (!fs.existsSync(file)) {
    problems.push(`docs/data/${name}: missing`);
    continue;
  }
  try {
    JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    problems.push(`docs/data/${name}: invalid JSON — ${error.message}`);
  }
}

// ES module syntax check for the browser scripts
const jsFiles = walk(path.join(DOCS, 'assets', 'js')).filter((f) => f.endsWith('.js'));
const tmp = path.join(ROOT, 'node_modules', '.cache', 'syntax-check');
fs.mkdirSync(tmp, { recursive: true });
for (const file of jsFiles) {
  const copy = path.join(tmp, path.basename(file).replace(/\.js$/, '.mjs'));
  fs.copyFileSync(file, copy);
  const { spawnSync } = await import('node:child_process');
  const result = spawnSync(process.execPath, ['--check', copy], { encoding: 'utf8' });
  if (result.status !== 0) {
    problems.push(`${path.relative(ROOT, file)}: ES module syntax error — ${(result.stderr || '').split('\n').slice(0, 3).join(' ')}`);
  }
}

// every table row that shows a market must be able to link to its Kalshi page
const markets = JSON.parse(fs.readFileSync(path.join(DOCS, 'data', 'markets.json'), 'utf8'));
let missingUrls = 0;
for (const market of markets) {
  if (!market.kalshi_url) missingUrls += 1;
}
if (missingUrls) notes.push(`${missingUrls} of ${markets.length} markets have no Kalshi URL (ticker could not be mapped to a series).`);

console.log(`checked ${htmlFiles.length} html files, ${internalLinks} internal links, ${externalLinks} external links, ${jsFiles.length} scripts`);
if (notes.length) {
  console.log('\nnotes:');
  for (const note of notes) console.log(`  - ${note}`);
}
if (problems.length) {
  console.error(`\n${problems.length} problem(s):`);
  for (const problem of problems) console.error(`  ✗ ${problem}`);
  process.exitCode = 1;
} else {
  console.log('\nno problems found');
}
