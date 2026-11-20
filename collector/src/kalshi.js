/**
 * Minimal, dependency-free Kalshi REST client.
 *
 * Public market-data endpoints need no authentication. Authenticated endpoints
 * (order placement, portfolio reads) require an API key id + private key and
 * are signed exactly as documented by Kalshi:
 *
 *   pre-sign text = <timestamp in ms> + <HTTP METHOD> + <path without query string>
 *   Ed25519 keys  -> Ed25519 signature over the pre-sign text
 *   RSA keys      -> RSA-PSS with SHA-256 (MGF1-SHA256, salt length = digest length)
 *   headers       -> KALSHI-ACCESS-KEY / KALSHI-ACCESS-SIGNATURE / KALSHI-ACCESS-TIMESTAMP
 *
 * References (official):
 *   https://docs.kalshi.com/getting_started/api_keys
 *   https://www.npmjs.com/package/kalshi-typescript  (official SDK, `KalshiAuth`)
 */
import crypto from 'node:crypto';
import {
  REST_BASE, REQUEST_TIMEOUT_MS, REQUEST_DELAY_MS, MAX_RETRIES, PAGE_LIMIT,
} from './config.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Fixed-point helpers — Kalshi returns strings for prices/counts (see fixed-point migration docs). */
export const fp = {
  num(value, fallback = 0) {
    if (value === null || value === undefined || value === '') return fallback;
    const n = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(n) ? n : fallback;
  },
  dollars(value) {
    return fp.num(value, 0);
  },
};

export class KalshiError extends Error {
  constructor(message, { status, code, body } = {}) {
    super(message);
    this.name = 'KalshiError';
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

export class KalshiClient {
  /**
   * @param {object} [options]
   * @param {string} [options.baseUrl] REST root, e.g. https://external-api.demo.kalshi.co/trade-api/v2
   * @param {string} [options.apiKeyId] KALSHI-ACCESS-KEY value (optional — public data needs none)
   * @param {string} [options.privateKeyPem] Private key PEM (optional)
   * @param {boolean} [options.verbose] Log requests
   */
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || REST_BASE).replace(/\/+$/, '');
    this.apiKeyId = options.apiKeyId || null;
    this.privateKeyPem = options.privateKeyPem || null;
    this.verbose = Boolean(options.verbose);
    this.requestCount = 0;
    this.errorCount = 0;
    this.lastError = null;
    this.lastRequestAt = 0;
    this._privateKey = null;
  }

  get hasCredentials() {
    return Boolean(this.apiKeyId && this.privateKeyPem);
  }

  /** Lazily parse the private key; detects Ed25519 vs RSA exactly like the official SDK. */
  _key() {
    if (!this._privateKey) {
      this._privateKey = crypto.createPrivateKey(this.privateKeyPem);
      const type = this._privateKey.asymmetricKeyType;
      if (type !== 'rsa' && type !== 'ed25519') {
        throw new Error(`Unsupported private key type "${type}": Kalshi API keys are RSA or Ed25519`);
      }
    }
    return this._privateKey;
  }

  /** Sign the pre-sign text. Returns base64 signature. */
  signText(text) {
    const key = this._key();
    if (key.asymmetricKeyType === 'ed25519') {
      return crypto.sign(null, Buffer.from(text, 'utf8'), key).toString('base64');
    }
    const signer = crypto.createSign('RSA-SHA256');
    signer.update(text);
    signer.end();
    return signer.sign({
      key,
      padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
      saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
    }).toString('base64');
  }

  /** Build the three auth headers for a request. */
  authHeaders(method, path) {
    if (!this.hasCredentials) {
      throw new Error('Kalshi API credentials are not configured (apiKeyId + privateKeyPem required).');
    }
    const timestamp = Date.now().toString();
    const signature = this.signText(timestamp + method.toUpperCase() + path);
    return {
      'KALSHI-ACCESS-KEY': this.apiKeyId,
      'KALSHI-ACCESS-SIGNATURE': signature,
      'KALSHI-ACCESS-TIMESTAMP': timestamp,
    };
  }

  _url(path, params) {
    const url = new URL(this.baseUrl + path);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null || value === '') continue;
        url.searchParams.set(key, String(value));
      }
    }
    return url;
  }

  async _request(method, path, { params, body, signed = false } = {}) {
    const url = this._url(path, params);
    const headers = { accept: 'application/json' };
    if (body !== undefined) headers['content-type'] = 'application/json';
    if (signed) {
      if (!this.hasCredentials) {
        throw new Error(`Signed request to ${path} requires Kalshi API credentials.`);
      }
      // Sign the path *without* the query string (official api_keys docs).
      Object.assign(headers, this.authHeaders(method, url.pathname));
    }

    let lastError = null;
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
      const sinceLast = Date.now() - this.lastRequestAt;
      if (sinceLast < REQUEST_DELAY_MS) await sleep(REQUEST_DELAY_MS - sinceLast);

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      try {
        this.requestCount += 1;
        this.lastRequestAt = Date.now();
        const response = await fetch(url, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        });
        const text = await response.text();
        let parsed = null;
        if (text) {
          try { parsed = JSON.parse(text); } catch { parsed = { raw: text }; }
        }
        if (!response.ok) {
          const message = parsed?.message || parsed?.error || `HTTP ${response.status}`;
          const code = parsed?.code || null;
          // 4xx (other than 429) are not retryable.
          if (response.status < 500 && response.status !== 429) {
            this.errorCount += 1;
            this.lastError = { path, status: response.status, code, message };
            throw new KalshiError(`${message} (${path})`, { status: response.status, code, body: parsed });
          }
          lastError = new KalshiError(`${message} (${path})`, { status: response.status, code, body: parsed });
        } else {
          return { data: parsed, status: response.status, headers: response.headers };
        }
      } catch (error) {
        if (error instanceof KalshiError && error.status < 500 && error.status !== 429) throw error;
        lastError = error;
      } finally {
        clearTimeout(timer);
      }
      if (attempt < MAX_RETRIES) {
        await sleep(500 * (attempt + 1));
      }
    }
    this.errorCount += 1;
    this.lastError = { path, message: String(lastError?.message || lastError) };
    throw lastError || new Error(`Request failed: ${method} ${path}`);
  }

  async get(path, params) {
    const res = await this._request('GET', path, { params });
    return res.data;
  }

  async post(path, body, { signed = true } = {}) {
    const res = await this._request('POST', path, { body, signed });
    return res.data;
  }

  // ---------------------------------------------------------------- public data

  /**
   * Page through `GET /markets`.
   * @param {object} params see https://docs.kalshi.com/api-reference/market/get-markets
   */
  async getMarkets(params = {}, { maxPages = 6 } = {}) {
    const markets = [];
    let cursor = '';
    for (let page = 0; page < maxPages; page += 1) {
      const query = { limit: PAGE_LIMIT, ...params };
      if (cursor) query.cursor = cursor;
      const data = await this.get('/markets', query);
      const list = data?.markets || [];
      markets.push(...list);
      cursor = data?.cursor || '';
      if (!cursor || list.length === 0) break;
    }
    return markets;
  }

  async getMarket(ticker) {
    const data = await this.get(`/markets/${encodeURIComponent(ticker)}`);
    return data?.market || null;
  }

  /** Batch fetch markets by ticker (comma separated). */
  async getMarketsByTickers(tickers) {
    if (!tickers.length) return [];
    const data = await this.get('/markets', { tickers: tickers.join(',') });
    return data?.markets || [];
  }

  /** Batch orderbooks: `GET /markets/orderbooks?tickers=a,b,c`. */
  async getOrderbooks(tickers) {
    if (!tickers.length) return {};
    const data = await this.get('/markets/orderbooks', { tickers: tickers.join(',') });
    return data?.orderbooks || {};
  }

  /** Single orderbook with depth: `GET /markets/{ticker}/orderbook?depth=`. */
  async getOrderbook(ticker, depth = 10) {
    const data = await this.get(`/markets/${encodeURIComponent(ticker)}/orderbook`, { depth });
    return data?.orderbook_fp || null;
  }

  /**
   * Candles for one market.
   * The documented route is `GET /series/{series_ticker}/markets/{ticker}/candlesticks`;
   * the batch route `GET /markets/candlesticks?market_tickers=...` is used as fallback.
   */
  async getCandles(seriesTicker, ticker, { startTs, endTs, periodInterval = 1 } = {}) {
    try {
      const data = await this.get(
        `/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks`,
        { start_ts: startTs, end_ts: endTs, period_interval: periodInterval },
      );
      return data?.candlesticks || [];
    } catch (error) {
      const data = await this.get('/markets/candlesticks', {
        market_tickers: ticker,
        start_ts: startTs,
        end_ts: endTs,
        period_interval: periodInterval,
      });
      return data?.candlesticks || [];
    }
  }

  /** Batch candles for up to 100 tickers. */
  async getCandlesBatch(tickers, { startTs, endTs, periodInterval = 1 } = {}) {
    if (!tickers.length) return {};
    const data = await this.get('/markets/candlesticks', {
      market_tickers: tickers.join(','),
      start_ts: startTs,
      end_ts: endTs,
      period_interval: periodInterval,
    });
    return data?.candlesticks || {};
  }

  async getEvent(eventTicker) {
    const data = await this.get(`/events/${encodeURIComponent(eventTicker)}`);
    return data?.event || null;
  }

  /** Series discovery: `GET /series?category=...&include_volume=true`. */
  async getSeries(params = {}) {
    const data = await this.get('/series', { include_volume: 'true', ...params });
    return data?.series || [];
  }

  async getExchangeStatus() {
    return this.get('/exchange/status');
  }

  // ------------------------------------------------------------ authenticated

  /**
   * Create an order using the V2 request shape.
   * `POST /portfolio/events/orders` (legacy /portfolio/orders writes are gone — 410).
   * https://docs.kalshi.com/api-reference/orders/create-order-v2
   */
  async createOrder(order) {
    return this.post('/portfolio/events/orders', {
      ticker: order.ticker,
      client_order_id: order.clientOrderId,
      side: order.side,                       // 'bid' | 'ask' (single book)
      count: order.count,                     // fixed-point string, e.g. "10.00"
      price: order.price,                     // fixed-point dollar string, e.g. "0.5600"
      time_in_force: order.timeInForce || 'fill_or_kill',
      self_trade_prevention_type: order.selfTradePreventionType || 'taker_at_cross',
      post_only: Boolean(order.postOnly),
      cancel_order_on_pause: Boolean(order.cancelOrderOnPause),
      reduce_only: Boolean(order.reduceOnly),
      subaccount: order.subaccount,
      exchange_index: order.exchangeIndex,
      expiration_time: order.expirationTime,
    });
  }

  async getBalance() {
    return this.get('/portfolio/balance');
  }

  async getPositions(params = {}) {
    return this.get('/portfolio/positions', params);
  }

  async getFills(params = {}) {
    return this.get('/portfolio/fills', params);
  }

  async getSettlements(params = {}) {
    return this.get('/portfolio/settlements', params);
  }

  async getOrders(params = {}) {
    return this.get('/portfolio/orders', params);
  }
}
