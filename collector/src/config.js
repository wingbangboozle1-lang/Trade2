/**
 * Central configuration for the Kalshi demo collector.
 *
 * Every value here traces back to an official Kalshi source; see `SOURCES` and
 * the `docs/methodology.html` page for the links.
 */

/** Recommended demo REST root (official demo environment docs). */
export const REST_BASE = process.env.KALSHI_API_BASE || 'https://external-api.demo.kalshi.co/trade-api/v2';

/** Recommended demo WebSocket root (official WebSocket quick start). */
export const WS_BASE = process.env.KALSHI_WS_BASE || 'wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2';

/** Public Kalshi market page for an event/series (used for human review links). */
export const KALSHI_SITE = 'https://kalshi.co';

/** Alert threshold: a price move of at least $0.10 in either direction. */
export const SWING_THRESHOLD = 0.10;

/** Minimum $ move that the ROI model calls "high ROI" (filters the 2nd chat pane). */
export const ROI_CHAT_THRESHOLD = 60;

/** Simulated (paper) portfolio starting cash in USD. */
export const PAPER_START_CASH = 10000;

/** Maximum number of markets tracked per topic. */
export const PER_TOPIC_LIMIT = 12;

/** Candle period used for the in-page charts (minutes). Kalshi allows 1 | 60 | 1440. */
export const CANDLE_PERIOD_MINUTES = 1;

/** How many hours of 1-minute candles to pull per market (max 5000 periods per request). */
export const CANDLE_HISTORY_HOURS = 36;

/** Orderbook depth requested per side (1-100 allowed by the API). */
export const ORDERBOOK_DEPTH = 10;

/** Maximum pages pulled per discovery query. */
export const MAX_PAGES_PER_QUERY = 6;

/** Page size for `/markets` (API maximum is 1000). */
export const PAGE_LIMIT = 1000;

/** Maximum number of orderbook/candle requests per collection run (rate-limit politeness). */
export const MAX_DETAIL_REQUESTS = 180;

/** Keep at most this many swing alerts in the published alert log. */
export const MAX_ALERTS = 400;

/** Keep at most this many price points per market in the published price history. */
export const MAX_PRICE_POINTS = 2000;

/** Keep at most this many simulated trades in the published trade log. */
export const MAX_TRADES = 500;

/** Request timeout (ms). */
export const REQUEST_TIMEOUT_MS = 30000;

/** Minimum delay between API calls (ms) — keeps the collector inside Kalshi rate limits. */
export const REQUEST_DELAY_MS = 60;

/** Retry attempts for transient failures (5xx / network). */
export const MAX_RETRIES = 3;

/**
 * The five topics this project tracks. `keywords` are matched (case-insensitively)
 * against the Kalshi series title, event title and market title. `categories` are
 * the Kalshi `category` values that the Kalshi API reports for series/events.
 */
export const TOPICS = {
  gas: {
    id: 'gas',
    label: 'Gas Prices',
    blurb: 'Retail fuel and crude price levels — daily and threshold style contracts.',
    keywords: [
      'gas price', 'gasoline', 'gas prices', 'diesel', 'fuel price', 'price of gas',
      'regular gas', 'premium gas', 'national average gas', 'retail gas', 'pump price',
      'crude oil', 'wti', 'brent', 'opec', 'oil price',
    ],
    categories: ['Economics', 'Financial', 'Climate and Weather'],
  },
  elections: {
    id: 'elections',
    label: 'Elections',
    blurb: 'Election, nomination, appointment and ballot markets — political outcomes.',
    keywords: [
      'election', 'elections', 'president', 'presidential', 'senate', 'house of representatives',
      'congress', 'primary', 'general election', 'ballot', 'referendum', 'governor',
      'mayor', 'nominee', 'nominated', 'win the', 'electoral college', 'midterm',
      'republican', 'democrat', 'parliament', 'prime minister', 'impeach', 'cabinet',
      'secretary general', 'supreme court', 'trump', 'biden', 'harris', 'vance',
    ],
    categories: ['Politics', 'World', 'Elections'],
  },
  culture: {
    id: 'culture',
    label: 'Culture',
    blurb: 'Film, music, awards, publishing and celebrity culture markets.',
    keywords: [
      'oscar', 'oscars', 'academy award', 'grammy', 'grammys', 'emmy', 'emmys', 'tony award',
      'billboard', 'album', 'box office', 'movie', 'film', 'tv show', 'series finale',
      'netflix', 'spotify', 'celebrity', 'youtube', 'bestseller', 'book', 'novel',
      'spotify', 'chART', 'c-chart', 'taylor swift', 'jay-z', 'drake', 'stranger things',
      'video game', 'album of the year', 'song of the year',
    ],
    categories: ['Culture', 'Awards', 'Movies', 'Music', 'Mentions'],
  },
  crypto: {
    id: 'crypto',
    label: 'Crypto',
    blurb: 'Digital asset price, milestone and regulatory markets.',
    keywords: [
      'bitcoin', 'btc', 'ethereum', 'eth ', 'eth-', 'solana', 'sol ', 'dogecoin', 'doge',
      'xrp', 'ripple', 'cardano', 'polkadot', 'litecoin', 'crypto', 'cryptocurrency',
      'stablecoin', 'usdc', 'usdt', 'coinbase', 'binance', 'blockchain', 'token',
      'nft', 'microstrategy', 'strategy inc', 'sec ', 'bitcoin etf', 'ether etf',
    ],
    categories: ['Crypto', 'Economics', 'Financial'],
  },
  golf: {
    id: 'golf',
    label: 'Golf',
    blurb: 'Tour events, majors, match play and player props.',
    keywords: [
      'golf', 'pga', 'masters', 'ryder cup', 'us open', 'u.s. open', 'open championship',
      'the open', 'lpga', ' Augusta', 'augusta', 'caddie', 'birdie', 'eagle', 'bogey',
      'cut line', 'win the pga', 'tour championship', 'wmphi', 'wmphc', 'fedex',
    ],
    categories: ['Sports'],
  },
};

/** Official sources used by the collector / site (for the methodology table). */
export const SOURCES = {
  demoEnv: 'https://docs.kalshi.com/getting_started/demo_env',
  apiEnvironments: 'https://docs.kalshi.com/getting_started/api_environments',
  marketData: 'https://docs.kalshi.com/getting_started/quick_start_market_data',
  websockets: 'https://docs.kalshi.com/getting_started/quick_start_websockets',
  apiKeys: 'https://docs.kalshi.com/getting_started/api_keys',
  getMarkets: 'https://docs.kalshi.com/api-reference/market/get-markets',
  getMarket: 'https://docs.kalshi.com/api-reference/market/get-market',
  getSeriesList: 'https://docs.kalshi.com/api-reference/market/get-series-list',
  getEvents: 'https://docs.kalshi.com/api-reference/events/get-events',
  getEvent: 'https://docs.kalshi.com/api-reference/events/get-event',
  getOrderbook: 'https://docs.kalshi.com/api-reference/market/get-market-orderbook',
  getOrderbooks: 'https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks',
  getCandlesticks: 'https://docs.kalshi.com/api-reference/market/get-market-candlesticks',
  batchCandlesticks: 'https://docs.kalshi.com/api-reference/market/batch-get-market-candlesticks',
  createOrderV2: 'https://docs.kalshi.com/api-reference/orders/create-order-v2',
  getOrders: 'https://docs.kalshi.com/api-reference/orders/get-orders',
  portfolioBalance: 'https://docs.kalshi.com/api-reference/portfolio/get-portfolio-balance',
  portfolioPositions: 'https://docs.kalshi.com/api-reference/portfolio/get-portfolio-positions',
  portfolioFills: 'https://docs.kalshi.com/api-reference/portfolio/get-portfolio-fills',
  portfolioSettlements: 'https://docs.kalshi.com/api-reference/portfolio/get-portfolio-settlements',
  orderbookResponses: 'https://docs.kalshi.com/getting_started/orderbook_responses',
  marketLifecycle: 'https://docs.kalshi.com/getting_started/market_lifecycle',
  marketSettlement: 'https://docs.kalshi.com/getting_started/market_settlement',
  fixedPoint: 'https://docs.kalshi.com/getting_started/fixed_point_migration',
  rateLimits: 'https://docs.kalshi.com/getting_started/rate_limits',
  exchangeStatus: 'https://docs.kalshi.com/api-reference/exchange/get-exchange-status',
  demoAccount: 'https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account',
  sdk: 'https://www.npmjs.com/package/kalshi-typescript',
};
