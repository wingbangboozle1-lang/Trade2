// Kalshi trading-fee formulas, implemented exactly as written in the official
// Kalshi Fee Schedule (effective July 7, 2026):
//   https://kalshi.com/docs/kalshi-fee-schedule.pdf
//
//   Taker:  fees = round up( M × 0.07 × C × P × (1 − P) )      M default 1
//   Maker:  fees = round up( M × 0.0175 × C × P × (1 − P) )    M default 0 (series-specific)
//
// P = price in dollars (50 cents = 0.5), C = contracts, M = series multiplier.
// All money here is computed in integer cents to avoid floating-point drift.
// "round up" is applied to the whole-cent amount (matches the PDF's General Trading
// Fees Table; see scripts/test/fees.test.mjs for line-by-line checks).

/**
 * Taker fee in whole cents.
 * @param {number} contracts  C, integer >= 1
 * @param {number} priceCents p in cents, integer 1..99
 * @param {number} [multiplier=1] M (series multiplier, default 1)
 */
export function takerFeeCents(contracts, priceCents, multiplier = 1) {
  assertArgs(contracts, priceCents, multiplier);
  // fee$ = M × 0.07 × C × p(100−p)/10000  ->  cents = M × 7 × C × p(100−p) / 10000
  return ceilDiv(multiplier * 7 * contracts * priceCents * (100 - priceCents), 10000);
}

/**
 * Maker fee in whole cents (only for series whose fee schedule lists a maker multiplier).
 * cents = M × 175 × C × p(100−p) / 1,000,000   (0.0175 = 175/10000)
 */
export function makerFeeCents(contracts, priceCents, multiplier = 0) {
  assertArgs(contracts, priceCents, multiplier);
  if (multiplier === 0) return 0;
  return ceilDiv(multiplier * 175 * contracts * priceCents * (100 - priceCents), 1000000);
}

function ceilDiv(numerator, denominator) {
  // numerator and denominator are non-negative integers below 2^53
  return Math.floor((numerator + denominator - 1) / denominator);
}

function assertArgs(contracts, priceCents, multiplier) {
  if (!Number.isInteger(contracts) || contracts < 1) throw new RangeError(`contracts must be integer >= 1, got ${contracts}`);
  if (!Number.isInteger(priceCents) || priceCents < 1 || priceCents > 99) throw new RangeError(`priceCents must be integer 1..99, got ${priceCents}`);
  if (!Number.isFinite(multiplier) || multiplier < 0) throw new RangeError(`multiplier must be >= 0, got ${multiplier}`);
}

/** Parse a Kalshi fixed-point dollar string (e.g. "0.5600") into integer cents, or null if unusable. */
export function dollarsToCents(s) {
  if (s === null || s === undefined || s === '') return null;
  const v = Number(s);
  if (!Number.isFinite(v)) return null;
  return Math.round(v * 100);
}
