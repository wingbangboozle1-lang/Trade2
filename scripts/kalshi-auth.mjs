// Request signing for the Kalshi Trade API, per the official docs:
//   https://docs.kalshi.com/getting_started/api_keys   (headers, pre-sign text, Ed25519 and RSA-PSS)
//   https://docs.kalshi.com/getting_started/api_environments  (sign the path WITHOUT the query string)
//
// Headers:  KALSHI-ACCESS-KEY (key id), KALSHI-ACCESS-TIMESTAMP (ms since epoch), KALSHI-ACCESS-SIGNATURE (base64)
// Pre-sign text = timestamp + HTTP method (upper case) + path without query, e.g. "/trade-api/v2/portfolio/balance".
// Ed25519 signs the text directly; RSA keys use RSA-PSS with SHA-256, MGF1-SHA-256, salt length = digest length.
// Timestamps must be within 30 seconds of Kalshi's clock (docs).

import crypto from 'node:crypto';

export function loadPrivateKey(pem) {
  return crypto.createPrivateKey(pem); // accepts PKCS#8 (Ed25519 / RSA) and PKCS#1 RSA PEM
}

export function preSignText(timestampMs, method, fullUrl) {
  const u = new URL(fullUrl);
  return `${timestampMs}${method.toUpperCase()}${u.pathname}`;
}

export function signHeaders({ keyId, privateKey, method, fullUrl, nowMs = Date.now() }) {
  const text = Buffer.from(preSignText(nowMs, method, fullUrl), 'utf8');
  let sig;
  if (privateKey.asymmetricKeyType === 'ed25519') {
    sig = crypto.sign(null, text, privateKey);
  } else if (privateKey.asymmetricKeyType === 'rsa') {
    sig = crypto.sign('sha256', text, {
      key: privateKey,
      padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
      saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
    });
  } else {
    throw new Error(`Unsupported key type: ${privateKey.asymmetricKeyType}`);
  }
  return {
    'KALSHI-ACCESS-KEY': keyId,
    'KALSHI-ACCESS-TIMESTAMP': String(nowMs),
    'KALSHI-ACCESS-SIGNATURE': sig.toString('base64'),
  };
}

/** Verify a signature produced by signHeaders (used by tests; mirrors what the server checks). */
export function verifyHeaders({ publicKey, method, fullUrl, headers }) {
  const text = Buffer.from(preSignText(headers['KALSHI-ACCESS-TIMESTAMP'], method, fullUrl), 'utf8');
  const sig = Buffer.from(headers['KALSHI-ACCESS-SIGNATURE'], 'base64');
  if (publicKey.asymmetricKeyType === 'ed25519') return crypto.verify(null, text, publicKey, sig);
  return crypto.verify('sha256', text, { key: publicKey, padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST }, sig);
}
