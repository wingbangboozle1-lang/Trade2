#!/usr/bin/env node
/**
 * Kalshi demo collector — main entry point.
 *
 * Pipeline (no credentials required):
 *   1. Discover live markets in the five tracked topics (gas, elections,
 *      culture, crypto, golf) using the public Kalshi REST API.
 *   2. Rank them by notional dollar amount (open interest x price).
 *   3. Capture orderbooks (liquidity) and 1-minute candles (charts).
 *   4. Detect price swings of >= $0.10 and publish them as alerts.
 *   5. Run the simulated (paper) trading engine: backtest + forward paper trades,
 *      with positions tracked until the market resolves.
 *   6. Write the JSON snapshots that the GitHub Pages site renders.
 *
 * Run:  node collector/src/collect.js
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  REST_BASE, WS_BASE, TOPICS, PER_TOPIC_LIMIT, SWING_THRESHOLD, ROI_CHAT_THRESHOLD,
  PAPER_START_CASH, CANDLE_PERIOD_MINUTES, CANDLE_HISTORY_HOURS, ORDERBOOK_DEPTH,
  MAX_PAGES_PER_QUERY, MAX_DETAIL_REQUESTS, MAX_ALERTS, MAX_PRICE_POINTS, MAX_TRADES, BACKTEST_HISTORY_HOURS,
  SOURCES,
} from './config.js';
import { KalshiClient, fp } from './kalshi.js';
import { classify, kalshiSeriesUrl } from './topics.js';
import { summarizeOrderbook } from './liquidity.js';
import { scoreMarket } from './roi.js';
import { detectSwings, detectTradeSwings, mergeAlerts, SWING_LOOKBACK_MINUTES } from './alerts.js';
import { backtestMarket, stepMarket, buildPortfolio, STRATEGIES, strategyConfigHash } from './paper.js';
import { createLiveClient, readAccountPortfolio } from './live-trade.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
const DATA_DIR = path.join(ROOT, 'docs', 'data');
const STATE_FILE = path.join(DATA_DIR, 'state.json');

const now = () => Math.floor(Date.now() / 1000);
const iso = (ts) => new Date(ts * 1000).toISOString();

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJson(file, fallback) {
  try {
    if (!fs.existsSync(file)) return fallback;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    console.warn(`[collector] could not read ${file}: ${error.message}`);
    return fallback;
  }
}

function writeJson(file, data) {
  ensureDir(path.dirname(file));
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`);
}

const log = (...args) => console.log(`[collector ${new Date().toISOString()}]`, ...args);

/** Normalize a raw Kalshi market into the shape the site consumes. */
function normalizeMarket(raw, topics, category) {
  const last = fp.dollars(raw.last_price_dollars);
  const yesBid = fp.dollars(raw.yes_bid_dollars);
  const yesAsk = fp.dollars(raw.yes_ask_dollars);
  const noBid = fp.dollars(raw.no_bid_dollars);
  const noAsk = fp.dollars(raw.no_ask_dollars);
  const openInterest = fp.num(raw.open_interest_fp);
  const volume = fp.num(raw.volume_fp);
  const volume24h = fp.num(raw.volume_24h_fp);
  const price = last || yesAsk || yesBid;
  const seriesTicker = String(raw.ticker || '').split('-')[0] || null;

  return {
    ticker: raw.ticker,
    event_ticker: raw.event_ticker,
    series_ticker: seriesTicker,
    title: raw.title || raw.yes_sub_title || raw.ticker,
    yes_sub_title: raw.yes_sub_title || '',
    no_sub_title: raw.no_sub_title || '',
    topic: topics[0] || null,
    topics,
    category: category || null,
    status: raw.status,
    close_time: raw.close_time,
    open_time: raw.open_time,
    updated_time: raw.updated_time,
    last_price: Number(price.toFixed(4)),
    previous_price: Number(fp.dollars(raw.previous_price_dollars).toFixed(4)),
    yes_bid: Number(yesBid.toFixed(4)),
    yes_ask: Number(yesAsk.toFixed(4)),
    no_bid: Number(noBid.toFixed(4)),
    no_ask: Number(noAsk.toFixed(4)),
    spread: Number((yesAsk - yesBid).toFixed(4)),
    volume,
    volume_24h: volume24h,
    open_interest: openInterest,
    // "highest dollar amount": contracts outstanding valued at the current price
    dollar_amount: Number((openInterest * price).toFixed(2)),
    // traded notional
    dollar_volume: Number((volume * price).toFixed(2)),
    dollar_volume_24h: Number((volume24h * price).toFixed(2)),
    result: raw.result || '',
    rules_primary: raw.rules_primary || '',
    rules_secondary: raw.rules_secondary || '',
    kalshi_url: kalshiSeriesUrl(seriesTicker),
    market_url: `https://kalshi.co/markets/${String(seriesTicker || '').toLowerCase()}`,
    settlement_sources: [],
  };
}

async function main() {
  const startedAt = Date.now();
  ensureDir(DATA_DIR);
  const state = readJson(STATE_FILE, {
    prices: {}, trades: [], alerts: [], runs: 0, lastRunAt: null, backtested: [], errorLog: [],
  });
  const client = new KalshiClient({ verbose: false });
  const errors = [];
  const calls = { markets: 0, series: 0, orderbooks: 0, candles: 0, events: 0, trades: 0 };

  const exchangeStatus = await client.getExchangeStatus().catch((error) => {
    errors.push({ where: 'exchange/status', error: error.message });
    return null;
  });

  // ---------------------------------------------------------------- 1. discovery
  log('discovering series…');
  const series = await client.getSeries({}).catch((error) => {
    errors.push({ where: 'series', error: error.message });
    return [];
  });
  calls.series += 1;

  const seriesByTopic = {};
  for (const id of Object.keys(TOPICS)) seriesByTopic[id] = [];
  for (const s of series) {
    const topics = classify({ title: s.title, ticker: s.ticker, category: s.category });
    if (!topics.length) continue;
    for (const t of topics) {
      seriesByTopic[t].push({
        ticker: s.ticker,
        title: s.title,
        category: s.category || null,
        volume: fp.num(s.volume_fp ?? s.volume),
      });
    }
  }
  for (const id of Object.keys(seriesByTopic)) {
    seriesByTopic[id].sort((a, b) => b.volume - a.volume);
    seriesByTopic[id] = seriesByTopic[id].slice(0, 8);
  }
  log(`series matched: ${Object.entries(seriesByTopic).map(([k, v]) => `${k}:${v.length}`).join(' ')}`);

  // Live markets for the matched series.
  const rawMarkets = new Map();
  for (const [topic, list] of Object.entries(seriesByTopic)) {
    for (const s of list) {
      if (calls.markets > 120) break;
      try {
        const markets = await client.getMarkets({ series_ticker: s.ticker, status: 'open', limit: 200 }, { maxPages: 2 });
        calls.markets += 1;
        for (const m of markets) {
          if (!rawMarkets.has(m.ticker)) rawMarkets.set(m.ticker, { raw: m, seriesCategory: s.category });
        }
      } catch (error) {
        errors.push({ where: `markets?series_ticker=${s.ticker}`, error: error.message });
      }
    }
  }

  // General sweep of newly created open markets (catches markets whose series is
  // not discoverable through /series).
  try {
    const sweep = await client.getMarkets({ status: 'open', limit: 1000, mve_filter: 'exclude' }, { maxPages: MAX_PAGES_PER_QUERY });
    calls.markets += MAX_PAGES_PER_QUERY;
    for (const m of sweep) {
      if (!rawMarkets.has(m.ticker)) rawMarkets.set(m.ticker, { raw: m, seriesCategory: null });
    }
  } catch (error) {
    errors.push({ where: 'markets sweep', error: error.message });
  }
  log(`candidate markets: ${rawMarkets.size}`);

  // ------------------------------------------------------------- 2. normalise
  const normalized = [];
  for (const { raw, seriesCategory } of rawMarkets.values()) {
    const topics = classify({
      title: raw.title,
      subtitle: raw.yes_sub_title,
      ticker: raw.ticker,
      series_ticker: String(raw.ticker || '').split('-')[0],
      category: seriesCategory,
    });
    if (!topics.length) continue;
    normalized.push(normalizeMarket(raw, topics, seriesCategory));
  }

  // Markets that already carry a simulated position must keep being tracked even
  // if they drop out of the topic ranking.
  const trackedTickers = new Set(state.trades.filter((t) => t.status === 'open').map((t) => t.ticker));
  if (trackedTickers.size) {
    const missing = [...trackedTickers].filter((t) => !rawMarkets.has(t));
    if (missing.length) {
      try {
        const extra = await client.getMarketsByTickers(missing);
        calls.markets += 1;
        for (const raw of extra) {
          const topics = classify({ title: raw.title, subtitle: raw.yes_sub_title, ticker: raw.ticker });
          normalized.push(normalizeMarket(raw, topics, null));
        }
      } catch (error) {
        errors.push({ where: 'markets?tickers (tracked)', error: error.message });
      }
    }
  }

  // --------------------------------------------------------------- 3. select
  const byTopic = {};
  for (const id of Object.keys(TOPICS)) byTopic[id] = [];
  for (const market of normalized) {
    for (const t of market.topics) byTopic[t].push(market);
  }
  const selected = new Map();
  for (const id of Object.keys(byTopic)) {
    byTopic[id].sort((a, b) => (b.dollar_amount + b.dollar_volume) - (a.dollar_amount + a.dollar_volume));
    for (const market of byTopic[id].slice(0, PER_TOPIC_LIMIT)) selected.set(market.ticker, market);
  }
  for (const market of normalized) {
    if (trackedTickers.has(market.ticker)) selected.set(market.ticker, market);
  }
  const markets = [...selected.values()];
  log(`selected ${markets.length} markets across ${Object.keys(byTopic).filter((k) => byTopic[k].length).length} topics`);

  // ---------------------------------------------------- 4. orderbooks + candles
  const tickers = markets.map((m) => m.ticker);
  const books = {};
  for (const market of markets) {
    if (calls.orderbooks >= MAX_DETAIL_REQUESTS) break;
    try {
      const book = await client.getOrderbook(market.ticker, ORDERBOOK_DEPTH);
      calls.orderbooks += 1;
      if (book) books[market.ticker] = book;
    } catch (error) {
      errors.push({ where: `orderbook ${market.ticker}`, error: error.message });
    }
  }

  // Recent fills for every market: this is the live price feed (second resolution).
  let tradeFeed = {};
  try {
    const rawTrades = await client.getTradesPaged({ limit: 1000, maxPages: 4 });
    calls.trades += 1;
    const tracked = new Set(tickers);
    for (const trade of rawTrades) {
      if (!tracked.has(trade.ticker)) continue;
      const ts = Math.floor(Date.parse(trade.created_time) / 1000);
      if (!Number.isFinite(ts)) continue;
      if (!tradeFeed[trade.ticker]) tradeFeed[trade.ticker] = [];
      tradeFeed[trade.ticker].push({
        ts,
        price: fp.dollars(trade.yes_price_dollars),
        count: fp.num(trade.count_fp),
      });
    }
    for (const key of Object.keys(tradeFeed)) {
      tradeFeed[key].sort((a, b) => a.ts - b.ts);
      tradeFeed[key] = tradeFeed[key].slice(-600);
    }
  } catch (error) {
    errors.push({ where: 'markets/trades', error: error.message });
  }
  log(`trade feed: ${Object.keys(tradeFeed).length} markets with fills`);

  const endTs = now();
  const startTs = endTs - CANDLE_HISTORY_HOURS * 3600;
  const candleSets = {};
  // Intraday candles (1 minute) are only useful where the market actually trades.
  const withTrades = markets.filter((m) => (tradeFeed[m.ticker] || []).length > 0);
  for (const market of withTrades) {
    if (calls.candles >= MAX_DETAIL_REQUESTS) break;
    try {
      const series = market.series_ticker || String(market.ticker).split('-')[0];
      const candles = await client.getCandles(series, market.ticker, {
        startTs, endTs, periodInterval: CANDLE_PERIOD_MINUTES,
      });
      calls.candles += 1;
      candleSets[market.ticker] = candles;
    } catch (error) {
      errors.push({ where: `candlesticks ${market.ticker}`, error: error.message });
    }
  }

  // Hourly candles over a longer window give the backtest a usable series even
  // where the market only prints occasionally.
  const hourlySets = {};
  const hourlyStart = endTs - BACKTEST_HISTORY_HOURS * 3600;
  for (const market of markets) {
    if (calls.candles >= MAX_DETAIL_REQUESTS) break;
    try {
      const series = market.series_ticker || String(market.ticker).split('-')[0];
      const candles = await client.getCandles(series, market.ticker, {
        startTs: hourlyStart, endTs, periodInterval: 60,
      });
      calls.candles += 1;
      if (candles && candles.length) hourlySets[market.ticker] = candles;
    } catch (error) {
      errors.push({ where: `hourly candlesticks ${market.ticker}`, error: error.message });
    }
  }

  // ------------------------------------------------------------- 5. event data
  const eventTickers = [...new Set(markets.map((m) => m.event_ticker))].slice(0, 70);
  const events = {};
  for (const eventTicker of eventTickers) {
    if (calls.events >= MAX_DETAIL_REQUESTS) break;
    try {
      const event = await client.getEvent(eventTicker);
      calls.events += 1;
      if (event) events[eventTicker] = event;
    } catch (error) {
      errors.push({ where: `events/${eventTicker}`, error: error.message });
    }
  }

  // ------------------------------------------- 6. normalise books / candles
  const orderbooks = {};
  const candles = {};
  const hourly = {};
  for (const market of markets) {
    const summary = summarizeOrderbook(books[market.ticker], market);
    orderbooks[market.ticker] = summary;

    const raw = candleSets[market.ticker] || [];
    const list = raw
      .map((c) => ({
        ts: Number(c.end_period_ts),
        open: fp.dollars(c.price?.open_dollars),
        high: fp.dollars(c.price?.high_dollars),
        low: fp.dollars(c.price?.low_dollars),
        close: fp.dollars(c.price?.close_dollars),
        bid: fp.dollars(c.yes_bid?.close_dollars),
        ask: fp.dollars(c.yes_ask?.close_dollars),
        volume: fp.num(c.volume_fp),
        open_interest: fp.num(c.open_interest_fp),
      }))
      .filter((c) => Number.isFinite(c.ts) && Number.isFinite(c.close) && c.close > 0)
      .sort((a, b) => a.ts - b.ts);
    candles[market.ticker] = list.slice(-360);

    const hourlyRaw = hourlySets[market.ticker] || [];
    hourly[market.ticker] = hourlyRaw
      .map((c) => ({
        ts: Number(c.end_period_ts),
        open: fp.dollars(c.price?.open_dollars),
        high: fp.dollars(c.price?.high_dollars),
        low: fp.dollars(c.price?.low_dollars),
        close: fp.dollars(c.price?.close_dollars),
        bid: fp.dollars(c.yes_bid?.close_dollars),
        ask: fp.dollars(c.yes_ask?.close_dollars),
        volume: fp.num(c.volume_fp),
        open_interest: fp.num(c.open_interest_fp),
      }))
      .filter((c) => Number.isFinite(c.ts) && Number.isFinite(c.close) && c.close > 0)
      .sort((a, b) => a.ts - b.ts)
      .slice(-720);
  }

  // ------------------------------------------------------ 7. history + scores
  const history = state.prices || {};
  const timestamp = now();
  for (const market of markets) {
    const list = history[market.ticker] || [];
    const lastPoint = list[list.length - 1];
    if (!lastPoint || lastPoint[0] !== timestamp) {
      list.push([timestamp, market.last_price]);
      history[market.ticker] = list.slice(-MAX_PRICE_POINTS);
    }
  }

  for (const market of markets) {
    const score = scoreMarket({
      market,
      book: orderbooks[market.ticker],
      points: [
        ...(history[market.ticker] || []).map(([ts, price]) => ({ ts, price })),
        ...(tradeFeed[market.ticker] || []).map((t) => ({ ts: t.ts, price: t.price })),
      ].sort((a, b) => a.ts - b.ts),
      now: timestamp,
    });
    market.roi_score = score.score;
    market.roi_components = score.components;
    market.roi_reasons = score.reasons;
    market.roi_fair_yes = score.fair_yes;
    market.roi_ev_yes = score.ev_yes;
    market.roi_ev_no = score.ev_no;
    market.roi_pct = score.roi_pct;
    market.hours_to_close = score.hours_to_close;
    const event = events[market.event_ticker];
    if (event) {
      market.category = event.category || market.category;
      market.settlement_sources = (event.settlement_sources || []).map((s) => ({ name: s.name, url: s.url }));
      market.event_title = event.title || '';
      market.event_strike_period = event.strike_period || '';
      market.mutually_exclusive = Boolean(event.mutually_exclusive);
    }
  }

  // --------------------------------------------------------------- 8. swings
  // Two independent references:
  //   - consecutive trade prints (live, second resolution)
  //   - Kalshi's own previous_price_dollars vs the current price
  const priceSwings = detectSwings({ markets, history, now: timestamp });
  const tradeSwings = detectTradeSwings({ tradeFeed, markets });
  const swings = [...tradeSwings, ...priceSwings]
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  const alerts = mergeAlerts(state.alerts || [], swings, { max: MAX_ALERTS });
  for (const alert of alerts) {
    const market = markets.find((m) => m.ticker === alert.ticker);
    if (market) {
      alert.roi_score = market.roi_score ?? null;
      alert.settlement_sources = market.settlement_sources || [];
      alert.kalshi_url = market.kalshi_url;
    }
  }
  log(`swings this run: ${swings.length} (log size ${alerts.length})`);

  // ------------------------------------------------------- 9. paper trading
  const configHash = strategyConfigHash();
  const resetTrades = state.strategy_config_hash && state.strategy_config_hash !== configHash;
  if (resetTrades) {
    log('strategy parameters changed — clearing the stored trade log and re-running the backtest');
  }
  const trades = resetTrades ? [] : [...(state.trades || [])];
  const backtested = resetTrades ? new Set() : new Set(state.backtested || []);

  // 9a. backtest newly tracked markets over their candle history.
  for (const market of markets) {
    if (backtested.has(market.ticker)) continue;
    const hourlySeries = (hourly[market.ticker] || []).map((c) => ({
      ts: c.ts, price: c.close, bid: c.bid, ask: c.ask, spread: (c.ask > 0 && c.bid > 0) ? c.ask - c.bid : null,
    }));
    const intradaySeries = (candles[market.ticker] || []).map((c) => ({
      ts: c.ts, price: c.close, bid: c.bid, ask: c.ask, spread: (c.ask > 0 && c.bid > 0) ? c.ask - c.bid : null,
    }));
    const series = hourlySeries.length >= 30 ? hourlySeries : intradaySeries;
    if (series.length < 10) continue;
    const produced = backtestMarket({ market, series });
    for (const trade of produced) {
      const key = `${trade.ticker}|${trade.strategy}|${trade.entry_ts}`;
      if (trades.some((t) => `${t.ticker}|${t.strategy}|${t.entry_ts}` === key)) continue;
      trades.push(trade);
    }
    backtested.add(market.ticker);
  }

  // 9b. forward paper trading on the live book.
  const openByTicker = new Map();
  for (const trade of trades) {
    if (trade.status !== 'open') continue;
    if (!openByTicker.has(trade.ticker)) openByTicker.set(trade.ticker, []);
    openByTicker.get(trade.ticker).push(trade);
  }

  const closedNow = [];
  const openedNow = [];
  for (const market of markets) {
    const openPositions = openByTicker.get(market.ticker) || [];
    if (!openPositions.length) continue;
    const series = [
      ...(history[market.ticker] || []).map(([ts, price]) => ({ ts, price, bid: price, ask: price, spread: null })),
      ...(tradeFeed[market.ticker] || []).map((t) => ({ ts: t.ts, price: t.price, bid: t.price, ask: t.price, spread: null })),
    ].sort((a, b) => a.ts - b.ts).slice(-400);
    const { closed, opened } = stepMarket({
      openPositions,
      market,
      book: orderbooks[market.ticker],
      series,
      now: timestamp,
    });
    closedNow.push(...closed);
    openedNow.push(...opened);
  }
  for (const trade of closedNow) {
    const idx = trades.findIndex((t) => t.id === trade.id);
    if (idx >= 0) trades[idx] = trade;
    else trades.push(trade);
  }
  for (const trade of openedNow) {
    trades.push({ ...trade, id: `${trade.ticker}|${trade.strategy}|${trade.entry_ts}` });
  }

  // 9c. mark open positions to market and detect resolutions.
  for (const trade of trades) {
    if (trade.status !== 'open') continue;
    const market = markets.find((m) => m.ticker === trade.ticker);
    if (!market) continue;
    const book = orderbooks[market.ticker];
    const yesBid = book?.best_yes_bid ?? market.yes_bid;
    const mark = trade.side === 'YES' ? yesBid : 1 - (book?.best_yes_ask ?? market.yes_ask);
    trade.mark_price = Number(mark.toFixed(4));
    trade.mark_value = Number((mark * trade.count).toFixed(2));
    trade.unrealized_pnl = Number((trade.mark_value - trade.cost).toFixed(2));
    trade.marked_at = iso(timestamp);
    trade.close_time = market.close_time;
    trade.topic = market.topic;
  }

  const trimmedTrades = trades
    .sort((a, b) => (b.entry_ts || 0) - (a.entry_ts || 0))
    .slice(0, MAX_TRADES);
  const portfolio = buildPortfolio(trimmedTrades, PAPER_START_CASH);

  // --------------------------------------------------------- 10. live account
  const live = createLiveClient();
  let account = { available: false, reason: live.reason, source: live.source || null, portfolio: null };
  if (live.available && live.client) {
    try {
      account = {
        available: true,
        reason: null,
        portfolio: await readAccountPortfolio(live.client),
        source: 'https://docs.kalshi.com/api-reference/portfolio/get-portfolio-balance',
      };
    } catch (error) {
      account = { available: false, reason: `Kalshi API call failed: ${error.message}`, portfolio: null };
    }
  }

  // ------------------------------------------------------------ 11. publish
  const manifest = {
    generated_at: new Date().toISOString(),
    generator: 'collector/src/collect.js',
    source: {
      rest_base: REST_BASE,
      ws_base: WS_BASE,
      docs: SOURCES.demoEnv,
    },
    threshold: { swing_usd: SWING_THRESHOLD, roi_chat_score: ROI_CHAT_THRESHOLD },
    counts: {
      series_seen: series.length,
      candidate_markets: rawMarkets.size,
      topic_markets: markets.length,
      events: Object.keys(events).length,
      orderbooks: Object.keys(orderbooks).length,
      candles_series: Object.keys(candles).length,
      alerts_total: alerts.length,
      alerts_this_run: swings.length,
      trade_feed_markets: Object.keys(tradeFeed).length,
      trade_prints: Object.values(tradeFeed).reduce((n, list) => n + list.length, 0),
      trades_total: trimmedTrades.length,
      trades_open: portfolio.open_positions,
      trades_closed: portfolio.closed_trades,
    },
    exchange_status: exchangeStatus,
    account,
  };

  const health = {
    last_run_at: new Date().toISOString(),
    duration_ms: Date.now() - startedAt,
    api_calls: client.requestCount,
    api_errors: client.errorCount,
    errors: errors.slice(0, 25),
    calls,
    exchange_active: exchangeStatus?.exchange_active ?? null,
    trading_active: exchangeStatus?.trading_active ?? null,
    runs: (state.runs || 0) + 1,
    rest_base: REST_BASE,
    ws_base: WS_BASE,
    notes: [
      'All market data is read from the public Kalshi demo REST API (no credentials).',
      'Orderbook and candle counts reflect the per-run request budget in collector/src/config.js.',
    ],
  };

  writeJson(path.join(DATA_DIR, 'markets.json'), markets);
  writeJson(path.join(DATA_DIR, 'events.json'), events);
  writeJson(path.join(DATA_DIR, 'orderbooks.json'), orderbooks);
  writeJson(path.join(DATA_DIR, 'candles.json'), candles);
  writeJson(path.join(DATA_DIR, 'candles_hourly.json'), hourly);
  writeJson(path.join(DATA_DIR, 'market_trades.json'), tradeFeed);
  writeJson(path.join(DATA_DIR, 'alerts.json'), alerts);
  writeJson(path.join(DATA_DIR, 'prices.json'), history);
  writeJson(path.join(DATA_DIR, 'trades.json'), trimmedTrades);
  writeJson(path.join(DATA_DIR, 'portfolio.json'), portfolio);
  writeJson(path.join(DATA_DIR, 'manifest.json'), manifest);
  writeJson(path.join(DATA_DIR, 'collector-health.json'), health);

  state.prices = history;
  state.trade_feed = tradeFeed;
  state.trades = trimmedTrades;
  state.alerts = alerts;
  state.backtested = [...backtested].slice(-500);
  state.strategy_config_hash = configHash;
  state.runs = (state.runs || 0) + 1;
  state.lastRunAt = new Date().toISOString();
  writeJson(STATE_FILE, state);

  log(`done in ${Date.now() - startedAt}ms — ${markets.length} markets, ${alerts.length} alerts, ${trimmedTrades.length} trades, equity $${portfolio.equity}`);
  if (errors.length) log(`errors: ${errors.length} (first: ${errors[0].where} ${errors[0].error})`);
}

main().catch((error) => {
  console.error('[collector] fatal error:', error);
  // Persist the failure so the scheduled run leaves a diagnosable artefact.
  try {
    const file = path.join(DATA_DIR, 'collector-health.json');
    const previous = readJson(file, {});
    writeJson(file, {
      ...previous,
      last_run_at: new Date().toISOString(),
      status: 'failed',
      error: { message: String(error?.message || error), stack: String(error?.stack || '').split('\n').slice(0, 12) },
    });
  } catch { /* never mask the original failure */ }
  process.exitCode = 1;
});
