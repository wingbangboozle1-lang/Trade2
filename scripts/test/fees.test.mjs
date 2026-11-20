// Line-by-line check of scripts/fees.mjs against the OFFICIAL Kalshi Fee Schedule
// (https://kalshi.com/docs/kalshi-fee-schedule.pdf, "General Trading Fees Table", effective July 7, 2026).
// Each row: [price_cents, fee_for_1_contract_cents, fee_for_100_contracts_cents]
// Values are transcribed from the PDF text (see SOURCES.md, source S2).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { takerFeeCents, makerFeeCents } from '../fees.mjs';

const OFFICIAL_GENERAL_TABLE = [
  [1, 1, 7], // PDF row: price $0.01 -> fee 1 contract $0.01 | price 100 contracts $1.00 -> fee $0.07
  [5, 1, 34],
  [10, 1, 63],
  [15, 1, 90],
  [20, 2, 112],
  [25, 2, 132],
  [30, 2, 147],
  [35, 2, 160],
  [40, 2, 168],
  [45, 2, 174],
  [50, 2, 175],
  [55, 2, 174],
  [60, 2, 168],
  [65, 2, 160],
  [70, 2, 147],
  [75, 2, 132],
  [80, 2, 112],
  [85, 1, 90],
  [90, 1, 63],
  [95, 1, 34],
  [99, 1, 7],
];

test('taker fee matches every row of the official General Trading Fees Table (1 and 100 contracts)', () => {
  for (const [p, one, hundred] of OFFICIAL_GENERAL_TABLE) {
    assert.equal(takerFeeCents(1, p), one, `1 contract @ ${p}c`);
    assert.equal(takerFeeCents(100, p), hundred, `100 contracts @ ${p}c`);
  }
});

test('official worked example: 1 contract at 50 cents, taker = $0.02 after rounding up', () => {
  assert.equal(takerFeeCents(1, 50), 2);
});

test('official worked example: 100 contracts at 50 cents = $1.75', () => {
  assert.equal(takerFeeCents(100, 50), 175);
});

test('series multiplier 0 gives zero taker fee (e.g. KXBTCY, KXETHY, KXELECTIRAN in the schedule)', () => {
  assert.equal(takerFeeCents(100, 50, 0), 0);
});

test('maker formula uses 0.0175 coefficient; default multiplier 0 means no maker fee', () => {
  assert.equal(makerFeeCents(100, 50), 0);
  // 0.0175 x 100 x 0.5 x 0.5 = 0.4375 dollars -> rounded up to 44 cents
  assert.equal(makerFeeCents(100, 50, 1), 44);
});

test('invalid inputs are rejected', () => {
  assert.throws(() => takerFeeCents(0, 50));
  assert.throws(() => takerFeeCents(1, 0));
  assert.throws(() => takerFeeCents(1, 100));
  assert.throws(() => takerFeeCents(1.5, 50));
});
