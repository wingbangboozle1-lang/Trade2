/* Unit tests for assets/alerts-view.js (coordination T-997-A / R-D-01).
 *
 * Run: node --test test/alerts-view.test.mjs
 *
 * The fixture rows mirror the structure the collector publishes in
 * data/live.json -> alerts[] (fields: ticker, direction, previous, current,
 * iso, ts, yes_bid, yes_ask). The final test block also runs the module over
 * the repository's current committed snapshot and asserts only invariants
 * (never specific counts, because the snapshot updates on every collector
 * run).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import AlertsView from "../assets/alerts-view.js";

const { dedupeAlerts, spreadOf, wideSpread, ageLabel, ALERT_THRESHOLD } = AlertsView;

function row(over) {
  return Object.assign(
    {
      ticker: "KXTEST-1",
      direction: "up",
      previous: 0.3,
      current: 0.45,
      iso: "2026-11-20T18:00:00Z",
      ts: 1763644800,
      yes_bid: 0.44,
      yes_ask: 0.46,
    },
    over
  );
}

test("ALERT_THRESHOLD matches the brief's $0.10 swing definition", () => {
  assert.equal(ALERT_THRESHOLD, 0.1);
});

test("exact repeated rows collapse into one row with a repeat count", () => {
  const raw = [row(), row(), row()];
  const out = dedupeAlerts(raw);
  assert.equal(out.length, 1);
  assert.equal(out[0].repeat_count, 3);
  /* Most recent occurrence wins for last_iso. */
  assert.equal(out[0].last_iso, "2026-11-20T18:00:00Z");
});

test("repeat groups keep first-appearance order and latest timestamps", () => {
  const raw = [
    row({ ticker: "A", iso: "2026-11-20T18:00:00Z" }),
    row({ ticker: "B", iso: "2026-11-20T18:01:00Z" }),
    row({ ticker: "A", iso: "2026-11-20T18:02:00Z" }),
  ];
  const out = dedupeAlerts(raw);
  assert.deepEqual(out.map((r) => r.ticker), ["A", "B"]);
  assert.equal(out[0].repeat_count, 2);
  assert.equal(out[0].last_iso, "2026-11-20T18:02:00Z");
});

test("distinct price steps, directions and markets stay separate rows", () => {
  const raw = [
    row(),
    row({ previous: 0.45, current: 0.6 }), // next step of the same move
    row({ direction: "down", previous: 0.6, current: 0.45 }),
    row({ ticker: "KXTEST-2" }),
  ];
  const out = dedupeAlerts(raw);
  assert.equal(out.length, 4);
  out.forEach((r) => assert.equal(r.repeat_count, 1));
});

test("wide spread detection: >= $0.10 spread marks the midpoint non-executable", () => {
  assert.equal(wideSpread(row({ yes_bid: 0.002, yes_ask: 0.811 })), true);
  assert.equal(wideSpread(row({ yes_bid: 0.01, yes_ask: 0.944 })), true);
  assert.equal(wideSpread(row({ yes_bid: 0.44, yes_ask: 0.46 })), false);
  assert.equal(wideSpread(row({ yes_bid: 0.002, yes_ask: 0.003 })), false);
});

test("spreadOf returns null when either side is missing or non-numeric", () => {
  assert.equal(spreadOf(row({ yes_bid: undefined })), null);
  assert.equal(spreadOf(row({ yes_ask: "n/a" })), null);
  assert.equal(spreadOf({}), null);
  assert.ok(Math.abs(spreadOf(row({ yes_bid: 0.1, yes_ask: 0.3 })) - 0.2) < 1e-9);
});

test("deduped rows carry spread fields from the newest occurrence", () => {
  const raw = [
    row({ yes_bid: 0.002, yes_ask: 0.811, iso: "2026-11-20T18:00:00Z" }),
    row({ yes_bid: 0.44, yes_ask: 0.46, iso: "2026-11-20T18:05:00Z" }),
  ];
  const out = dedupeAlerts(raw);
  assert.equal(out.length, 1);
  assert.equal(out[0].wide_spread, false); // newest quotes are tight
  assert.ok(Math.abs(out[0].spread - 0.02) < 1e-9);
  assert.equal(out[0].last_iso, "2026-11-20T18:05:00Z");
});

test("malformed input is skipped, not crashed on", () => {
  assert.deepEqual(dedupeAlerts(null), []);
  assert.deepEqual(dedupeAlerts(undefined), []);
  assert.deepEqual(dedupeAlerts("nope"), []);
  assert.deepEqual(dedupeAlerts([null, 42, row()]), [dedupeAlerts([row()])[0]]);
});

test("ageLabel humanizes seconds, minutes, hours and days; junk stays a dash", () => {
  const now = new Date("2026-11-20T18:30:00Z").getTime();
  assert.equal(ageLabel("2026-11-20T18:29:55Z", now), "5s old");
  assert.equal(ageLabel("2026-11-20T18:27:00Z", now), "3m old");
  assert.equal(ageLabel("2026-11-20T16:25:00Z", now), "2h 5m old");
  assert.equal(ageLabel("2026-11-18T12:30:00Z", now), "2d 6h old");
  assert.equal(ageLabel("", now), "—");
  assert.equal(ageLabel("not-a-date", now), "—");
  assert.equal(ageLabel(undefined, now), "—");
});

test("invariants hold on the repository's current committed snapshot", async () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  let raw;
  try {
    raw = JSON.parse(await readFile(path.join(root, "data", "live.json"), "utf8")).alerts || [];
  } catch {
    return; // no snapshot in this checkout — nothing to assert
  }
  const out = dedupeAlerts(raw);
  assert.ok(out.length <= raw.length, "dedupe never grows the feed");
  assert.equal(
    out.reduce((acc, r) => acc + r.repeat_count, 0),
    raw.length,
    "repeat counts sum to the raw row count"
  );
  out.forEach((r) => {
    if (r.wide_spread) {
      assert.ok(r.spread >= ALERT_THRESHOLD, "flagged rows really have a wide spread");
    }
  });
});
