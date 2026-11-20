/**
 * Topic classification.
 *
 * The Kalshi API's own `category` filter on `GET /events` is not applied by the
 * service (verified live: `?category=Crypto` returned `category:"World"` events),
 * so topics are derived locally from the titles/tickers/categories that Kalshi
 * actually reports. Nothing is inferred beyond string matching.
 */
import { TOPICS } from './config.js';

const STOP_WORDS = new Set(['will', 'the', 'a', 'an', 'of', 'to', 'in', 'on', 'at', 'be', 'is', 'by', 'for']);

/** Build a matcher for one keyword (word-boundary for short/ambiguous tokens). */
function matcher(keyword) {
  const phrase = keyword.trim().toLowerCase();
  if (!phrase) return null;
  if (phrase.includes(' ')) {
    return (text) => text.includes(phrase);
  }
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return (text) => new RegExp(`\\b${escaped}\\b`).test(text);
}

const MATCHERS = Object.fromEntries(
  Object.entries(TOPICS).map(([id, topic]) => [id, topic.keywords.map(matcher).filter(Boolean)]),
);

const CATEGORY_HINTS = Object.fromEntries(
  Object.entries(TOPICS).map(([id, topic]) => [id, new Set(topic.categories.map((c) => c.toLowerCase()))]),
);

/**
 * Classify a record (series, event or market) into zero or more topics.
 * @param {{title?:string, subtitle?:string, ticker?:string, series_ticker?:string, category?:string}} record
 * @returns {string[]} topic ids (ordered by the TOPICS definition order)
 */
export function classify(record = {}) {
  const title = String(record.title || '').toLowerCase();
  const subtitle = String(record.subtitle || record.sub_title || '').toLowerCase();
  const ticker = String(record.ticker || record.series_ticker || record.event_ticker || '').toLowerCase();
  const category = String(record.category || '').toLowerCase();
  const haystack = `${title} ${subtitle}`;

  const hits = [];
  for (const [id, matchers] of Object.entries(MATCHERS)) {
    let matched = false;
    for (const test of matchers) {
      if (test(haystack)) { matched = true; break; }
    }
    if (!matched) continue;

    // Ticker evidence: Kalshi series tickers are stable identifiers
    // (e.g. KXPRES*, KXGAS*, KXCRYPTO*). Used as a supporting signal only.
    if (!matched && ticker) {
      // placeholder – ticker check happens below per topic
    }
    hits.push(id);
  }

  // Supporting ticker evidence for short, ambiguous keywords.
  if (!hits.includes('gas') && /\b(kx)?gas|gasoil|kxgasoilprice/.test(ticker)) hits.push('gas');
  if (!hits.includes('elections') && /kx(pres|senate|house|gov|primary|mayor|elect|vote|republican|democrat|nominate|poll)/.test(ticker)) hits.push('elections');
  if (!hits.includes('culture') && /kx(grammy|emmy|oscar|boxoffice|album|spotify|billboard|movie|film|celeb|netflix)/.test(ticker)) hits.push('culture');
  if (!hits.includes('crypto') && /kx(btc|bitcoin|eth|ethereum|solana|crypto|doge|xrp|coinbase|binance|nft)/.test(ticker)) hits.push('crypto');
  if (!hits.includes('golf') && /(golf|pga|lyt|masters|ryder|wimbledon)/.test(ticker)) hits.push('golf');

  // Kalshi-reported category is a supporting signal for the weaker topics.
  if (category) {
    for (const [id, cats] of Object.entries(CATEGORY_HINTS)) {
      if (cats.has(category) && !hits.includes(id)) {
        // Only accept the category hint when the title also shows topical evidence.
        const weak = /gas|oil|fuel|election|vote|president|senate|house|primary|governor|mayor|nominate|crypto|bitcoin|ethereum|solana|golf|pga|masters|oscar|grammy|emmy|album|movie|film|box office/.test(haystack);
        if (weak) hits.push(id);
      }
    }
  }

  const order = Object.keys(TOPICS);
  return hits.sort((a, b) => order.indexOf(a) - order.indexOf(b));
}

/** Words that are too generic to classify on their own. */
export function isTooGeneric(text) {
  const words = String(text).toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  const meaningful = words.filter((w) => !STOP_WORDS.has(w) && w.length > 3);
  return meaningful.length === 0;
}

/** Public Kalshi page for a series / event, used for human review links. */
export function kalshiSeriesUrl(seriesTicker) {
  if (!seriesTicker) return null;
  return `https://kalshi.co/markets/${encodeURIComponent(seriesTicker.toLowerCase())}`;
}
