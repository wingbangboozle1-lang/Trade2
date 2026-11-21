#!/usr/bin/env node
// Kalshi dashboard collector.
//
//   node scripts/collect.mjs --state ./state --out ./_site/data [--base https://external-api.demo.kalshi.co/trade-api/v2]
//
// Reads ONLY public Kalshi Trade API endpoints (no credentials). Writes JSON the static site renders.
// Persistent state (price history, alert memory, simulated trades) lives in --state (restored/saved by
// GitHub Actions cache; not committed to git).
//
// Official endpoints used (see SOURCES.md for links and verification):
//   GET /exchange/status                       exchange + trading status
//   GET /search/tags_by_categories             official category/tag taxonomy (recorded for review)
//   GET /series                                series list (titles, categories, fee_type, fee_multiplier, contract URLs)
//   GET /events?series_ticker&status=open&with_nested_markets=true   events + their markets
//   GET /markets?series_ticker&status=settled&min_settled_ts=…       settled-market scan (rotating, documented filters:
//     status values unopened|open|closed|settled and min_settled_ts "settled after this Unix timestamp" (seconds) —
//     https://docs.kalshi.com/api-reference/market/get-markets, verified against the demo API 2026-11-21)
//   GET /markets/{ticker}                      single market (used for resolution watch checks)
//   GET /markets/{ticker}/orderbook?depth=10   resting bids for YES and NO (liquidity ladder)

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { getPublic, DEMO_BASE, KalshiHttpError, configureBreaker, breakerTripped, breakerReason } from './kalshi.mjs';
import { dollarsToCents } from './fees.mjs';
import { openPositions, updatePositions, summarize, STRATEGIES } from './strategies.mjs';

const args = parseArgs(process.argv.slice(2));
const STATE_DIR = args.state || './state';
const OUT_DIR = args.out || './_site/data';
const BASE = args.base || process.env.KALSHI_BASE || DEMO_BASE;
const CONFIG_PATH = args.config || path.join(path.dirname(new URL(import.meta.url).pathname), '..', 'config', 'topics.json');

const log = (m) => console.error(m);

/** Enforce demo-only collection, even if a workflow variable or CLI arg is changed. */
export function assertDemoBase(base) {
  let url;
  try { url = new URL(base); } catch { throw new Error('Invalid Kalshi API base URL'); }
  const allowedHosts = new Set(['external-api.demo.kalshi.co', 'demo-api.kalshi.co']);
  if (url.protocol !== 'https:' || !allowedHosts.has(url.hostname) || url.port ||
      url.username || url.password || url.pathname.replace(/\/+$/, '') !== '/trade-api/v2' || url.search || url.hash) {
    throw new Error(`Demo-only guard rejected API base: ${base}`);
  }
  return base;
}

export async function main({ base = BASE, stateDir = STATE_DIR, outDir = OUT_DIR, configPath = CONFIG_PATH, getFn = getPublic, nowMs = Date.now(), deadlineMs = 12 * 60 * 1000, maxScanSeries = RESOLUTION_SCAN_MAX_SERIES } = {}) {
  assertDemoBase(base);
  const started = Date.now();
  configureBreaker({ limit: 6, deadlineMs: started + deadlineMs });
  const cfg = JSON.parse(await readFile(configPath, 'utf8'));
  const state = await loadState(stateDir);
  state.run = (state.run || 0) + 1;
  // Durable memory (F642-T1 / R-4f92-4): the published snapshot IS committed to git, so
  // merging it back makes resolution history survive eviction of the Actions state cache.
  const prior = await loadPriorPublished(outDir);
  for (const [t, r] of Object.entries(prior.resolved)) if (!state.resolved[t]) state.resolved[t] = r;
  for (const [t, p] of Object.entries(prior.pending)) if (!state.pending[t]) state.pending[t] = p;
  const errors = [];
  const get = (p, params, o) => getFn(base, p, params, o);

  log(`[collect] phase: exchange status (elapsed ${Math.round((Date.now() - started) / 1000)}s)`);
  // 1) exchange status
  let exchange = null;
  try {
    exchange = (await get('/exchange/status')).data;
  } catch (e) {
    errors.push(describeErr('exchange/status', e));
  }

  // 2) official category taxonomy (recorded so the mapping can be reviewed)
  let categories = null;
  try {
    categories = (await get('/search/tags_by_categories')).data.tags_by_categories;
  } catch (e) {
    errors.push(describeErr('search/tags_by_categories', e));
  }

  // 3) series list -> topic mapping
  let seriesList = [];
  try {
    seriesList = (await get('/series')).data.series || [];
  } catch (e) {
    errors.push(describeErr('series', e));
  }
  const seriesMap = capSeries(resolveTopicSeries(cfg, seriesList), cfg.max_series || 60);

  log(`[collect] phase: events (elapsed ${Math.round((Date.now() - started) / 1000)}s)`);
  // 4) events (with nested markets) for each mapped series
  const eventsBySeries = new Map();
  for (const [seriesTicker] of seriesMap) {
    try {
      const evs = await fetchAllEvents(get, seriesTicker, 2);
      eventsBySeries.set(seriesTicker, evs);
    } catch (e) {
      errors.push(describeErr(`events?series_ticker=${seriesTicker}`, e));
    }
  }

  // 5) flatten to market rows
  const rows = [];
  for (const [seriesTicker, evs] of eventsBySeries) {
    const meta = seriesMap.get(seriesTicker);
    const series = meta.series;
    for (const ev of evs) {
      for (const m of ev.markets || []) {
        if (m.status !== 'active') continue; // response enum: active = tradable (see REPO_REVIEW irregularity)
        const row = buildRow(m, ev, meta, series, base, nowMs);
        rows.push(row);
      }
    }
  }
  rows.sort((a, b) => (b.est_volume_24h_usd ?? 0) - (a.est_volume_24h_usd ?? 0));

  // 6) previous-run memory for price-move alerts
  const alerts = [];
  const threshold = cfg.alert_threshold_cents;
  for (const r of rows) {
    const prev = state.last[r.ticker];
    r.prev_last_cents = prev ? prev.cents : null;
    r.change_cents = null;
    if (r.last_cents !== null && prev && prev.cents !== null) {
      const gap = nowMs - prev.ms;
      const delta = r.last_cents - prev.cents;
      r.change_cents = delta;
      if (Math.abs(delta) >= threshold && gap <= 90 * 60 * 1000) {
        alerts.push(makeAlert(r, prev, delta, cfg, nowMs));
      }
    }
  }
  for (const r of rows) {
    if (r.last_cents !== null) state.last[r.ticker] = { cents: r.last_cents, ms: nowMs };
  }
  // forget markets not seen for 2h so the memory stays bounded
  for (const t of Object.keys(state.last)) {
    if (nowMs - state.last[t].ms > 2 * 3600e3) delete state.last[t];
  }

  log(`[collect] phase: order books (elapsed ${Math.round((Date.now() - started) / 1000)}s)`);
  // 7) order books for the top-N markets by estimated 24h dollar volume
  const topN = rows.slice(0, cfg.orderbook_top_n);
  const orderbooks = {};
  for (const r of topN) {
    try {
      const ob = (await get(`/markets/${r.ticker}/orderbook`, { depth: 10 })).data.orderbook_fp;
      orderbooks[r.ticker] = {
        yes_bids: ladder(ob.yes_dollars),
        no_bids: ladder(ob.no_dollars),
        fetched_at: new Date(nowMs).toISOString(),
        source_url: `${base}/markets/${r.ticker}/orderbook?depth=10`,
      };
    } catch (e) {
      errors.push(describeErr(`orderbook ${r.ticker}`, e));
    }
  }

  // 8) history for tracked markets (top-N by volume + any alerted market), retention-pruned
  const tracked = new Set([...rows.slice(0, cfg.tracked_max).map((r) => r.ticker), ...alerts.map((a) => a.ticker)]);
  const cutoff = nowMs - cfg.history_retention_hours * 3600e3;
  for (const r of rows) {
    if (!tracked.has(r.ticker) || r.last_cents === null) continue;
    const h = (state.history[r.ticker] ||= []);
    const last = h[h.length - 1];
    if (!last || nowMs - last[0] >= 60 * 1000) {
      h.push([nowMs, r.last_cents, dollarsToCents(r.yes_bid_dollars), dollarsToCents(r.yes_ask_dollars), r.volume_24h, r.open_interest]);
    }
    state.meta[r.ticker] = { topic: r.topic, event_title: r.event_title, outcome_label: r.outcome_label, series_ticker: r.series_ticker, event_ticker: r.event_ticker, source_url: r.source_url, volume_rank_run: state.run };
  }
  for (const t of Object.keys(state.history)) {
    state.history[t] = state.history[t].filter((p) => p[0] >= cutoff);
    if (state.history[t].length === 0) delete state.history[t];
  }

  log(`[collect] phase: resolution (elapsed ${Math.round((Date.now() - started) / 1000)}s)`);
  // 9) resolution tracking — durable, three layers (session arena-f642a30a / F642-T1, request R-4f92-4):
  //    a) rotating settled-market scan per topic via the documented GET /markets filters
  //       (status=settled, min_settled_ts = now − 30 days). Same pattern as the docs pipeline
  //       fix in collector/runner.py::collect_resolutions (session arena-3dcf3f13 / X1).
  //    b) watch check for tracked/pending markets that left the active set (fast path).
  //    c) the previously published resolved.json is merged back at startup (loadPriorPublished),
  //       so outcomes accumulate across runs even when the Actions state cache is evicted.
  //    A row records the first observed official `result` verbatim (yes|no|scalar — never
  //    inferred); open-position tickers are exempt from retention pruning so a position can
  //    always settle against its row.
  const activeTickers = new Set(rows.map((r) => r.ticker));

  // a) rotating settled scan (bounded requests; full series pass in ceil(series/perCap) runs)
  const scanTargets = rotateScanSeries(seriesMap, nowMs, maxScanSeries);
  let scannedSeries = 0;
  let scannedMarkets = 0;
  let scanRequests = 0;
  let scanPages = 0;
  let dupes = 0;
  let resolvedAdded = 0;
  const budget = { left: RESOLUTION_SCAN_MAX_REQUESTS };
  const seenInRun = new Set(); // the listing is allowed to repeat a market; state.resolved alone hides that
  for (const { ticker: st, topic } of scanTargets) {
    if (breakerTripped() || budget.left <= 0) break;
    // Documented filters, from https://docs.kalshi.com/api-reference/market/get-markets:
    //   status=settled ("Only one status filter may be supplied at a time"), min_settled_ts
    //   ("settled after this Unix timestamp", seconds), limit (default 100, max 1000),
    //   mve_filter=exclude (multi-event markets are not part of a topic series sweep here).
    // Paging: "pass the cursor exactly as returned, stop when it is empty" — so this walks the
    // cursor until it ends or the run's request budget is spent, instead of reading two pages.
    // key order here is the request order; the demo host accepted this exact ordering in the
    // live probes (VERIFICATION-8a8d4294.md §3 P1).
    const params = { status: 'settled', series_ticker: st, min_settled_ts: Math.floor(nowMs / 1000) - RESOLUTION_LOOKBACK_S, limit: 100, mve_filter: 'exclude' };
    let cursor;
    let firstError = null;
    try {
      for (;;) {
        if (budget.left <= 0) break;
        const url = `${base}/markets?${new URLSearchParams({ ...params, ...(cursor ? { cursor } : {}) })}`;
        const res = (await get('/markets', cursor ? { ...params, cursor } : params)).data;
        budget.left--; scanRequests++; scanPages++;
        const page = res.markets || [];
        scannedMarkets += page.length;
        for (const m of page) {
          if (!m || !m.ticker) continue;
          if (seenInRun.has(m.ticker)) { dupes++; continue; }
          seenInRun.add(m.ticker);
          if (noteResolved(state, m, { topic, seriesTicker: st, via: 'settled-scan', base, nowMs, requestUrl: url })) resolvedAdded++;
        }
        cursor = res.cursor || '';
        if (!cursor || !page.length) break;
      }
      scannedSeries++;
    } catch (e) {
      // A failed series must not blank what earlier runs accumulated: state.resolved is only
      // ever added to here, so the rows already published stay published.
      errors.push(describeErr(`markets?series_ticker=${st}&status=settled`, e));
      firstError = String((e && e.message) || e);
      if (breakerTripped()) break;
    } finally {
      if (firstError) log(`[collect] settled scan ${st}: stopped after ${scanPages} page(s): ${firstError}`);
    }
  }
  if (dupes) log(`[collect] settled scan: ${dupes} repeated ticker(s) in the listings, deduped`);

  // b) watch check: anything once tracked (or previously pending) that is no longer active
  const watch = [...new Set([...Object.keys(state.meta), ...Object.keys(state.pending)])]
    .filter((t) => !activeTickers.has(t) && !state.resolved[t]);
  let checked = 0;
  for (const t of watch.slice(0, 60)) {
    try {
      const m = (await get(`/markets/${t}`)).data.market;
      checked++;
      const meta = state.meta[t];
      const prevPending = state.pending[t];
      if (m && RESULT_VALUES.has(m.result)) {
        if (noteResolved(state, m, {
          topic: meta_topic(state, t) ?? prevPending?.topic ?? null,
          seriesTicker: meta?.series_ticker ?? prevPending?.series_ticker ?? null,
          eventTitle: meta?.event_title ?? prevPending?.event_title ?? null,
          outcomeLabel: meta?.outcome_label ?? null,
          via: 'watch', base, nowMs, requestUrl: `${base}/markets/${t}`,
        })) resolvedAdded++;
      } else if (m) {
        state.pending[t] = {
          ticker: t,
          topic: meta_topic(state, t) ?? prevPending?.topic ?? null,
          event_title: meta?.event_title ?? prevPending?.event_title ?? null,
          series_ticker: meta?.series_ticker ?? prevPending?.series_ticker ?? null,
          status: m.status,
          close_time: m.close_time ?? null,
          settlement_ts: m.settlement_ts ?? null,
          source_url: `${base}/markets/${t}`,
        };
      }
    } catch (e) {
      errors.push(describeErr(`markets/${t}`, e));
    }
  }

  // c) cleanups + retention (open positions protected so every position can settle)
  for (const t of Object.keys(state.resolved)) delete state.meta[t];
  for (const t of Object.keys(state.pending)) {
    if (state.resolved[t] || activeTickers.has(t)) delete state.pending[t];
  }
  const protectTickers = new Set(state.positions.filter((p) => p.status === 'open').map((p) => p.ticker));
  pruneResolved(state, RESOLUTION_KEEP_PER_TOPIC, protectTickers);
  // Markets resolved in this run stop being watched; still-active ones refresh their meta above.

  log(`[collect] phase: paper trades (elapsed ${Math.round((Date.now() - started) / 1000)}s)`);
  // 10) simulated trades (paper) — uses only official prices + official fee formula
  const marketsByTicker = new Map(rows.map((r) => [r.ticker, r]));
  const resolvedByTicker = new Map(Object.entries(state.resolved).map(([t, v]) => [t, v]));
  const opened = openPositions(state, alerts, marketsByTicker, cfg, nowMs);
  updatePositions(state, marketsByTicker, resolvedByTicker, nowMs);
  // keep positions bounded: all open + latest 2000 settled
  const open = state.positions.filter((p) => p.status === 'open');
  const settled = state.positions.filter((p) => p.status !== 'open').slice(-2000);
  state.positions = [...open, ...settled];
  const tradeSummary = summarize(state.positions);

  // 11) alert memory (chronological, bounded)
  state.alerts = [...state.alerts, ...alerts].slice(-1000);

  log(`[collect] phase: write output (elapsed ${Math.round((Date.now() - started) / 1000)}s)`);
  // 12) topic index for the site
  const topicIndex = {};
  for (const key of Object.keys(cfg.topics)) {
    const tr = rows.filter((r) => r.topic === key);
    const evMap = new Map();
    for (const r of tr) {
      if (!evMap.has(r.event_ticker)) evMap.set(r.event_ticker, { event_ticker: r.event_ticker, title: r.event_title, series_ticker: r.series_ticker, series_title: r.series_title, source_url: r.event_url, markets: [] });
      evMap.get(r.event_ticker).markets.push(r.ticker);
    }
    topicIndex[key] = {
      label: cfg.topics[key].label,
      market_count: tr.length,
      event_count: evMap.size,
      dollar_volume_24h_usd: round2(tr.reduce((s, r) => s + (r.est_volume_24h_usd ?? 0), 0)),
      events: [...evMap.values()],
    };
  }

  const runInfo = {
    run: state.run,
    generated_at: new Date(nowMs).toISOString(),
    duration_ms: Date.now() - started,
    previous_run_at: state.prev_run_ms ? new Date(state.prev_run_ms).toISOString() : null,
    errors_this_run: errors.length,
  };
  state.prev_run_ms = nowMs;

  const latest = {
    generated_at: runInfo.generated_at,
    run: runInfo,
    source: {
      base_url: base,
      environment: 'Kalshi demo — public read-only market data',
      endpoints: [
        `${base}/exchange/status`,
        `${base}/series`,
        `${base}/events?series_ticker={series}&status=open&with_nested_markets=true`,
        `${base}/markets/{ticker}/orderbook?depth=10`,
        `${base}/markets/{ticker}`,
      ],
      docs: ['https://docs.kalshi.com/getting_started/api_environments', 'https://docs.kalshi.com/api-reference/market/get-market-orderbook'],
    },
    exchange,
    categories_official: categories,
    series_mapping: [...seriesMap.values()].map((m) => ({ series_ticker: m.series.ticker, topic: m.topic, reason: m.reason, title: m.series.title, category: m.series.category, fee_type: m.series.fee_type, fee_multiplier: m.series.fee_multiplier, contract_url: m.series.contract_url, contract_terms_url: m.series.contract_terms_url, settlement_sources: m.series.settlement_sources || [], source_url: `${base}/series/${m.series.ticker}` })),
    topics: topicIndex,
    markets: rows,
    orderbooks,
    errors,
  };

  const alertsOut = { generated_at: runInfo.generated_at, alerts: state.alerts.slice().reverse() };
  const resolvedOut = {
    generated_at: runInfo.generated_at,
    resolved: Object.values(state.resolved).sort((a, b) => (b.detected_at > a.detected_at ? 1 : -1)),
    pending: Object.values(state.pending).sort((a, b) => String(b.close_time || '').localeCompare(String(a.close_time || ''))),
  };
  const tradesOut = {
    generated_at: runInfo.generated_at,
    method: 'Simulated (paper) trades only. Fill at reported ask; size ' + 10 + ' contracts; official taker fee; settlement at $1/$0 from official result; no settlement fee.',
    strategies: STRATEGIES,
    summary: tradeSummary,
    positions: state.positions.slice().reverse().slice(0, 1500),
    opened_this_run: opened.length,
  };
  const historyOut = {};
  for (const [t, pts] of Object.entries(state.history)) {
    historyOut[t] = { meta: state.meta[t] || null, points: pts, fields: ['t_ms', 'last_cents', 'yes_bid_cents', 'yes_ask_cents', 'volume_24h_contracts', 'open_interest_contracts'] };
  }
  const statusOut = { generated_at: runInfo.generated_at, run: state.run, base_url: base, counts: { series_mapped: seriesMap.size, markets_active: rows.length, alerts_this_run: alerts.length, alerts_total: state.alerts.length, orderbooks: Object.keys(orderbooks).length, resolved_total: Object.keys(state.resolved).length, resolved_added_this_run: resolvedAdded, settled_scan_series: scannedSeries, settled_scan_markets: scannedMarkets, settled_scan_requests: scanRequests, settled_scan_pages: scanPages, settled_scan_duplicates_deduped: dupes, settled_scan_budget: budget.left, pending_total: Object.keys(state.pending).length, resolution_checks_this_run: checked, positions: state.positions.length, positions_opened_this_run: opened.length, history_markets: Object.keys(historyOut).length }, errors };

  // Fail closed: if the API was unreachable for the whole run, do not publish a partial snapshot.
  if (breakerTripped()) {
    const last = errors.length ? errors[errors.length - 1] : null;
    throw new Error(`Collector stopped before publishing: ${breakerReason() || 'circuit breaker tripped'}${last ? ` · last error at ${last.where}: ${last.message}` : ''}. Previous snapshot kept; nothing written.`);
  }
  await mkdir(outDir, { recursive: true });
  await writeFile(path.join(outDir, 'latest.json'), JSON.stringify(latest));
  await writeFile(path.join(outDir, 'alerts.json'), JSON.stringify(alertsOut));
  await writeFile(path.join(outDir, 'resolved.json'), JSON.stringify(resolvedOut));
  await writeFile(path.join(outDir, 'trades.json'), JSON.stringify(tradesOut));
  await writeFile(path.join(outDir, 'history.json'), JSON.stringify(historyOut));
  await writeFile(path.join(outDir, 'status.json'), JSON.stringify(statusOut, null, 1));
  await saveState(stateDir, state);
  return { latest, statusOut };
}

// ---------- helpers ----------

// Resolution tracking (F642-T1 / R-4f92-4). Official facts used here, all verified against
// the live demo API and the official docs on 2026-11-21 (see VERIFICATION-f642a30a.md):
//   * GET /markets accepts `status=settled` and `min_settled_ts` (Unix seconds —
//     "Filter items that settled after this Unix timestamp",
//     https://docs.kalshi.com/api-reference/market/get-markets).
//   * A settled market object carries `result` "yes"|"no" (binary), `settlement_ts`,
//     `settlement_value_dollars`, and object `status` "finalized" (the docs' filter value
//     is `settled`; the code keys on `result` and copies `status` verbatim).
//   * YES/NO payouts: https://docs.kalshi.com/getting_started/market_settlement.
export const RESULT_VALUES = new Set(['yes', 'no', 'scalar']);
export const RESOLUTION_LOOKBACK_S = 30 * 86400;
export const RESOLUTION_WINDOW_S = 900; // rotate the scan slice every 15 minutes (matches the docs pipeline, X1)
export const RESOLUTION_KEEP_PER_TOPIC = 100;
export const RESOLUTION_SCAN_MAX_SERIES = 15; // bound the request count; full series pass in ceil(series/perCap) runs
// A second, harder bound, because a series with many settlements is paginated: one run never
// spends more than this many listing requests on the settled scan. The budget is spent in series
// order, so a truncated series simply resumes on the next rotation window (rate limits for public
// endpoints are not published numerically, F-06, hence a conservative number).
export const RESOLUTION_SCAN_MAX_REQUESTS = 30;

/** Build one resolved row from a raw market object. `result` is copied verbatim (never inferred). */
export function resolutionRow(m, { topic = null, seriesTicker = null, eventTitle = null, outcomeLabel = null, via, base, nowMs, requestUrl = null } = {}) {
  return {
    ticker: m.ticker,
    topic,
    // Only a title the collector actually saw on an EVENT object may be called an event title.
    // The settled listing documents a market-level `title`, which is published as `market_title`
    // instead of being renamed (the two are different objects, and a reader must be able to tell
    // which one a line of text came from).
    event_title: eventTitle ?? null,
    market_title: m.title ?? null,
    // Provenance: `via` is this pipeline's name, `detected_by` the root/docs name, so a reviewer
    // can read one field on any of the three sites. `request_url` is the exact listing that
    // returned the row, so the claim is re-checkable with one click.
    detected_by: via,
    outcome_label: outcomeLabel ?? m.yes_sub_title ?? m.subtitle ?? '',
    event_ticker: m.event_ticker ?? null,
    series_ticker: seriesTicker ?? (m.ticker ? String(m.ticker).split('-')[0] : null),
    result: m.result,
    status: m.status ?? null,
    close_time: m.close_time ?? null,
    settlement_ts: m.settlement_ts ?? null,
    settlement_value_dollars: m.settlement_value_dollars ?? null,
    detected_at: new Date(nowMs).toISOString(),
    via,
    source_url: `${base}/markets/${m.ticker}`,
    request_url: requestUrl || null,
    docs_url: 'https://docs.kalshi.com/getting_started/market_settlement',
  };
}

/** Record a market's official result once (first observation wins); returns true when stored. */
export function noteResolved(state, m, opts) {
  if (!m || !m.ticker || !RESULT_VALUES.has(m.result)) return false;
  if (state.resolved[m.ticker]) return false;
  state.resolved[m.ticker] = resolutionRow(m, opts);
  return true;
}

/**
 * Rotating per-topic slice of series for the settled scan: run N (window = now/15min) scans
 * `perCap = floor(maxSeries/topics)` series per topic starting at (window * perCap) mod n,
 * so every mapped series is visited within ceil(series/perCap) windows. Mirrors the docs
 * pipeline's fix (collector/runner.py::collect_resolutions, session arena-3dcf3f13).
 */
export function rotateScanSeries(seriesMap, nowMs, maxSeries = RESOLUTION_SCAN_MAX_SERIES, windowS = RESOLUTION_WINDOW_S) {
  const perTopic = new Map();
  for (const [ticker, meta] of seriesMap) {
    const list = perTopic.get(meta.topic) || [];
    list.push(ticker);
    perTopic.set(meta.topic, list);
  }
  const topics = [...perTopic.keys()].sort();
  if (!topics.length) return [];
  const perCap = Math.max(1, Math.floor(maxSeries / topics.length));
  const window = Math.floor(nowMs / 1000 / windowS);
  const out = [];
  for (const topic of topics) {
    const list = [...perTopic.get(topic)].sort();
    const n = list.length;
    const start = (window * perCap) % n;
    for (let i = 0; i < Math.min(perCap, n); i++) out.push({ ticker: list[(start + i) % n], topic });
  }
  return out;
}

/** Retention: newest keepPerTopic rows per topic; tickers in `protect` are never pruned. */
export function pruneResolved(state, keepPerTopic = RESOLUTION_KEEP_PER_TOPIC, protect = new Set()) {
  const byTopic = new Map();
  for (const [t, r] of Object.entries(state.resolved)) {
    const key = r.topic ?? '';
    const list = byTopic.get(key) || [];
    list.push([t, r]);
    byTopic.set(key, list);
  }
  for (const list of byTopic.values()) {
    list.sort((a, b) => String(b[1].settlement_ts || b[1].detected_at || '').localeCompare(String(a[1].settlement_ts || a[1].detected_at || '')));
    for (const [t] of list.slice(keepPerTopic)) {
      if (!protect.has(t)) delete state.resolved[t];
    }
  }
}

/** Read the previously published snapshot so history survives state-cache eviction. */
export async function loadPriorPublished(outDir) {
  const out = { resolved: {}, pending: {} };
  try {
    const raw = JSON.parse(await readFile(path.join(outDir, 'resolved.json'), 'utf8'));
    for (const r of raw.resolved || []) {
      if (r && r.ticker && RESULT_VALUES.has(r.result)) out.resolved[r.ticker] = r;
    }
    for (const p of raw.pending || []) {
      if (p && p.ticker) out.pending[p.ticker] = p;
    }
  } catch {
    // no prior published snapshot (first run, clean checkout, or unreadable file) — start empty
  }
  return out;
}

// Keep curated series first, then the highest-volume keyword matches, up to `max`.
// Without a cap, keyword discovery over the full live series list made the run exceed its deadline.
export function capSeries(map, max) {
  if (map.size <= max) return map;
  const entries = [...map.entries()];
  const curated = entries.filter(([, v]) => String(v.reason).startsWith('curated'));
  const rest = entries.filter(([, v]) => !String(v.reason).startsWith('curated'))
    .sort((a, b) => Number(b[1].series.volume_fp || 0) - Number(a[1].series.volume_fp || 0));
  return new Map([...curated, ...rest].slice(0, max));
}

export function resolveTopicSeries(cfg, seriesList) {
  const out = new Map();
  const byTicker = new Map(seriesList.map((s) => [s.ticker, s]));
  for (const [topic, tcfg] of Object.entries(cfg.topics)) {
    for (const c of tcfg.series) {
      const s = byTicker.get(c.ticker);
      if (!s) continue; // curated ticker not in live list -> not mapped (reported in status)
      if (!out.has(s.ticker)) out.set(s.ticker, { topic, series: s, reason: `curated: official fee schedule row "${c.title_in_fee_schedule}"` });
    }
  }
  for (const s of seriesList) {
    if (out.has(s.ticker)) continue;
    const hay = { title: s.title || '', tags: (s.tags || []).join(' | '), category: [s.category, ...(s.categories || [])].filter(Boolean).join(' | ') };
    for (const [topic, tcfg] of Object.entries(cfg.topics)) {
      const hit = tcfg.keywords.find((kw) => {
        const re = new RegExp(`(^|[^a-z0-9])${escapeRe(kw.toLowerCase())}([^a-z0-9]|$)`, 'i');
        return re.test(hay.title) || re.test(hay.tags) || re.test(hay.category);
      });
      if (hit) {
        out.set(s.ticker, { topic, series: s, reason: `keyword "${hit}" in live series title/tags/category` });
        break;
      }
    }
  }
  return out;
}

async function fetchAllEvents(get, seriesTicker, maxPages) {
  const evs = [];
  let cursor = '';
  for (let i = 0; i < maxPages; i++) {
    const r = (await get('/events', { series_ticker: seriesTicker, status: 'open', with_nested_markets: true, limit: 200, cursor })).data;
    evs.push(...(r.events || []));
    if (!r.cursor) break;
    cursor = r.cursor;
  }
  return evs;
}

function buildRow(m, ev, meta, series, base, nowMs) {
  const notional = Number(m.notional_value_dollars) || 1;
  const v24 = Number(m.volume_24h_fp) || 0;
  const oi = Number(m.open_interest_fp) || 0;
  const last = dollarsToCents(m.last_price_dollars);
  const yb = dollarsToCents(m.yes_bid_dollars);
  const ya = dollarsToCents(m.yes_ask_dollars);
  const nb = dollarsToCents(m.no_bid_dollars);
  const na = dollarsToCents(m.no_ask_dollars);
  return {
    topic: meta.topic,
    topic_reason: meta.reason,
    series_ticker: ev.series_ticker,
    series_title: series.title,
    series_category: series.category,
    fee_type: series.fee_type,
    fee_multiplier: series.fee_multiplier,
    event_ticker: ev.event_ticker,
    event_title: ev.title,
    event_url: `${base}/events/${ev.event_ticker}`,
    ticker: m.ticker,
    outcome_label: m.yes_sub_title || m.subtitle || '',
    market_type: m.market_type,
    status: m.status,
    open_time: m.open_time,
    close_time: m.close_time,
    expected_expiration_time: m.expected_expiration_time ?? null,
    yes_bid_dollars: m.yes_bid_dollars,
    yes_ask_dollars: m.yes_ask_dollars,
    no_bid_dollars: m.no_bid_dollars,
    no_ask_dollars: m.no_ask_dollars,
    last_price_dollars: m.last_price_dollars,
    last_cents: last && last > 0 ? last : null,
    yes_bid_cents: yb,
    yes_ask_cents: ya,
    no_bid_cents: nb,
    no_ask_cents: na,
    spread_cents: ya !== null && yb !== null ? ya - yb : null,
    volume_24h: v24,
    volume_total: Number(m.volume_fp) || 0,
    open_interest: oi,
    notional_value_dollars: m.notional_value_dollars,
    est_volume_24h_usd: round2(v24 * notional),
    est_open_interest_usd: round2(oi * notional),
    rules_primary: m.rules_primary || '',
    series_contract_url: series.contract_url || null,
    series_terms_url: series.contract_terms_url || null,
    settlement_sources: series.settlement_sources || [],
    source_url: `${base}/markets/${m.ticker}`,
    fetched_at: new Date(nowMs).toISOString(),
  };
}

function makeAlert(r, prev, delta, cfg, nowMs) {
  const direction = delta > 0 ? 'up' : 'down';
  const sideEntry = direction === 'up' ? r.yes_ask_cents : r.no_ask_cents;
  const spread = r.spread_cents;
  const high_roi = sideEntry !== null && sideEntry <= cfg.high_roi_rule.max_entry_price_cents && spread !== null && spread <= cfg.high_roi_rule.max_spread_cents && r.volume_24h >= cfg.high_roi_rule.min_volume_24h_contracts;
  return {
    id: `${r.ticker}-${nowMs}`,
    t_ms: nowMs,
    at: new Date(nowMs).toISOString(),
    topic: r.topic,
    series_ticker: r.series_ticker,
    event_ticker: r.event_ticker,
    event_title: r.event_title,
    ticker: r.ticker,
    outcome_label: r.outcome_label,
    direction,
    from_cents: prev.cents,
    to_cents: r.last_cents,
    delta_cents: delta,
    previous_snapshot_at: new Date(prev.ms).toISOString(),
    high_roi,
    high_roi_entry_cents: sideEntry,
    volume_24h: r.volume_24h,
    source_url: r.source_url,
    event_url: r.event_url,
    rules_url: r.series_terms_url || r.series_contract_url,
    settlement_sources: r.settlement_sources,
    // Causal link to news/website is NOT determined automatically; see site "Flagged for Review".
    cause_link: null,
  };
}

function ladder(levels) {
  return (levels || [])
    .map(([p, c]) => ({ price_cents: dollarsToCents(p), contracts: Number(c) }))
    .filter((l) => l.price_cents !== null && l.contracts > 0)
    .sort((a, b) => b.price_cents - a.price_cents)
    .slice(0, 10);
}

function meta_topic(state, t) {
  return state.meta[t]?.topic ?? null;
}

async function loadState(dir) {
  const file = path.join(dir, 'state.json');
  const blank = { run: 0, last: {}, history: {}, meta: {}, resolved: {}, pending: {}, positions: [], alerts: [], prev_run_ms: null };
  if (!existsSync(file)) return blank;
  try {
    return { ...blank, ...JSON.parse(await readFile(file, 'utf8')) };
  } catch {
    return blank;
  }
}

async function saveState(dir, state) {
  await mkdir(dir, { recursive: true });
  await writeFile(path.join(dir, 'state.json'), JSON.stringify(state));
}

function describeErr(where, e) {
  if (e instanceof KalshiHttpError) return { where, status: e.status, message: e.message.slice(0, 200) };
  return { where, message: String(e?.message || e).slice(0, 200) };
}

function round2(x) {
  return Math.round(x * 100) / 100;
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function parseArgs(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      o[argv[i].slice(2)] = argv[i + 1];
      i++;
    }
  }
  return o;
}

// Run when executed directly (not when imported by tests).
if (process.argv[1] && import.meta.url === new URL(`file://${path.resolve(process.argv[1])}`).href) {
  main().then(
    ({ statusOut }) => {
      console.log(JSON.stringify(statusOut.counts));
      if (statusOut.errors.length) console.log('errors:', JSON.stringify(statusOut.errors.slice(0, 10)));
    },
    (e) => {
      console.error(e);
      process.exit(1);
    },
  );
}
