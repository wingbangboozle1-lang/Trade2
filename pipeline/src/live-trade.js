/**
 * Credential-gated live trading + on-account portfolio reads.
 *
 * This module is INERT unless Kalshi API credentials are present in the
 * environment:
 *   KALSHI_API_KEY_ID        — the key id (KALSHI-ACCESS-KEY)
 *   KALSHI_PRIVATE_KEY_PATH  — path to the PEM private key
 *   (or KALSHI_PRIVATE_KEY_PEM — the PEM itself)
 *
 * Signing follows the official docs:
 *   https://docs.kalshi.com/getting_started/api_keys
 *   https://docs.kalshi.com/api-reference/orders/create-order-v2
 *
 * Order placement uses the V2 single-book shape on `POST /portfolio/events/orders`
 * (the legacy `/portfolio/orders` write endpoints were removed and return 410).
 */
import fs from 'node:fs';
import { KalshiClient } from './kalshi.js';

export function loadCredentials(env = process.env) {
  const apiKeyId = env.KALSHI_API_KEY_ID || null;
  const privateKeyPem = env.KALSHI_PRIVATE_KEY_PEM
    || (env.KALSHI_PRIVATE_KEY_PATH && fs.existsSync(env.KALSHI_PRIVATE_KEY_PATH)
      ? fs.readFileSync(env.KALSHI_PRIVATE_KEY_PATH, 'utf8')
      : null);
  return { apiKeyId, privateKeyPem };
}

export function createLiveClient(env = process.env) {
  const creds = loadCredentials(env);
  if (!creds.apiKeyId || !creds.privateKeyPem) {
    return {
      client: null,
      available: false,
      reason: 'No Kalshi API credentials found (KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH). '
        + 'Demo account signup requires an email inbox that can receive a verification message, '
        + 'so no account could be provisioned in this environment. '
        + 'See https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account',
      source: 'https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account',
    };
  }
  return { client: new KalshiClient({ apiKeyId: creds.apiKeyId, privateKeyPem: creds.privateKeyPem }), available: true, reason: null };
}

/**
 * Place one order using the V2 request shape.
 * side: 'bid' (buy YES) | 'ask' (sell YES). Kalshi is a single book, so buying NO
 * is expressed as asking/bidding on the opposite side of the YES book.
 */
export async function placeOrder(client, {
  ticker, side, count, price, timeInForce = 'fill_or_kill', clientOrderId, exchangeIndex,
}) {
  return client.createOrder({
    ticker,
    side,
    count: String(count),
    price: Number(price).toFixed(4),
    timeInForce,
    clientOrderId,
    exchangeIndex,
  });
}

/** Read the real Kalshi account portfolio (balance, positions, fills, settlements). */
export async function readAccountPortfolio(client) {
  const [balance, positions, fills, settlements] = await Promise.all([
    client.getBalance(),
    client.getPositions({ limit: 200 }),
    client.getFills({ limit: 200 }),
    client.getSettlements({ limit: 200 }),
  ]);
  return { balance, positions, fills, settlements };
}
