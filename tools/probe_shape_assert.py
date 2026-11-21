#!/usr/bin/env python3
"""Re-assert the documented shape invariants on ``tools/probe_live_check.py``'s
report, so a check that silently stops checking cannot pass.

    python3 tools/probe_shape_assert.py probe-live.json
Exit 0 when every invariant holds; 1 otherwise, printing each violation.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: probe_shape_assert.py <report.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        report = json.load(fh)

    problems = list(report.get("problems") or [])
    tickers = report.get("tickers") or []

    if not tickers:
        problems.append("the report lists no tickers, so it proves nothing")

    returned = (report.get("orderbooks") or {}).get("returned")
    if returned != tickers:
        problems.append(
            f"orderbooks not returned in request order: {returned} != {tickers}")

    markets = (report.get("markets") or {}).get("returned") or []
    if sorted(markets) != sorted(tickers):
        problems.append(
            f"markets response did not cover every ticker: {markets} != {tickers}")

    # The serialiser under test must have repeated the parameter.
    query = (report.get("urls") or {}).get("query") or ""
    if query.count("tickers=") != len(tickers):
        problems.append(
            f"query {query!r} does not repeat tickers once per ticker")
    if "," in query:
        problems.append(f"query {query!r} comma-joins tickers")

    if problems:
        for p in problems:
            print(" - " + p, file=sys.stderr)
        return 1
    print("shape invariants hold: repeated tickers, request order, full coverage")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
