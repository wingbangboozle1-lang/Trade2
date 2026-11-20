#!/usr/bin/env node
/**
 * Render smoke test.
 *
 * Executes the page modules against a minimal DOM + fetch shim so that runtime
 * errors (undefined properties, wrong shapes, broken templates) fail loudly
 * without needing a browser.
 *
 * Usage: node tools/smoke-render.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const DOCS = path.join(ROOT, 'docs');

/* ------------------------------------------------------------ DOM shim */
class El {
  constructor(tag = 'div') {
    this.tag = tag;
    this.innerHTML = '';
    this.textContent = '';
    this.className = '';
    this.value = '';
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.parentElement = null;
    this.clientWidth = 800;
    this.clientHeight = 320;
    this.width = 800;
    this.height = 320;
  }

  addEventListener() {}

  removeEventListener() {}

  querySelector() { return new El(); }

  querySelectorAll() { return []; }

  getContext() { return ctx2d; }
}

const ctx2d = new Proxy({}, {
  get(target, prop) {
    if (prop === 'createLinearGradient') return () => ({ addColorStop() {} });
    if (prop === 'measureText') return () => ({ width: 10 });
    if (prop in target) return target[prop];
    return () => {};
  },
  set(target, prop, value) {
    target[prop] = value;
    return true;
  },
});

const elements = new Map();
const document = {
  body: new El('body'),
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, new El('div'));
    return elements.get(id);
  },
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, new El('div'));
    return elements.get(selector);
  },
  querySelectorAll() { return []; },
  createElement(tag) { return new El(tag); },
  addEventListener() {},
};

globalThis.document = document;
globalThis.window = { addEventListener() {}, devicePixelRatio: 1, innerWidth: 1280 };
globalThis.location = { pathname: '/dashboard.html', href: 'http://localhost/dashboard.html' };
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.setTimeout = (fn) => { fn(); return 0; };
globalThis.requestAnimationFrame = (fn) => { fn(); return 0; };

globalThis.fetch = async (url) => {
  const file = path.join(DOCS, String(url).replace(/^\.\//, ''));
  if (!fs.existsSync(file)) {
    return { ok: false, status: 404, json: async () => ({}) };
  }
  const text = fs.readFileSync(file, 'utf8');
  return { ok: true, status: 200, json: async () => JSON.parse(text), text: async () => text };
};

/* --------------------------------------------------------------- runner */
const failures = [];

async function run(label, modulePath, pathname) {
  globalThis.location.pathname = pathname;
  elements.clear();
  try {
    await import(`${modulePath}?t=${Date.now()}${Math.random()}`);
    await new Promise((resolve) => setImmediate(resolve));
    console.log(`  ok  ${label}`);
  } catch (error) {
    failures.push(`${label}: ${error.stack || error}`);
    console.log(`  FAIL ${label}: ${error.message}`);
  }
}

console.log('render smoke test');
await run('home page', path.join(DOCS, 'assets/js/home.js'), '/index.html');
await run('dashboard page', path.join(DOCS, 'assets/js/dashboard.js'), '/dashboard.html');
await run('trading page', path.join(DOCS, 'assets/js/trading.js'), '/trading.html');
await run('topic page (gas)', path.join(DOCS, 'assets/js/topic.js'), '/topics/gas.html');

if (failures.length) {
  console.error(`\n${failures.length} failure(s)`);
  for (const failure of failures) console.error(failure);
  process.exitCode = 1;
} else {
  console.log('\nall page modules rendered without error');
}
