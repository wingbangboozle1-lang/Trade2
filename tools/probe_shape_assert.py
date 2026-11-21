#!/usr/bin/env python3
"""Re-assert the live-shape invariants on ``tools/probe_live_check.py``'s report.

The report is produced by asking the real demo API; this layer is pure and is
unit-tested, so a check that silently stops checking cannot pass.

The contract it enforces was measured on the live host, not assumed:

    GET /markets?tickers=A,B            200, one record per ticker
    GET /markets?tickers=A&tickers=B    400 "multiple values for single value
                                            parameter 'tickers'"
    GET /markets/orderbooks?tickers=A,B            200, one empty entry
    GET /markets/orderbooks?tickers=A&tickers=B    200, one entry per ticker,
                                                   in request order

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
    probe = report.get("probe") or {}
    forms = report.get("forms") or {}

    if not tickers:
        problems.append("the report lists no tickers, so it proves nothing")

    # 1. /markets must come back complete from the probe's own URL.
    markets = (probe.get("markets") or {}).get("returned") or []
    if sorted(markets) != sorted(tickers):
        problems.append(
            f"markets response did not cover every ticker: {markets} != {tickers}")

    # 2. /markets/orderbooks must come back for every ticker, in request order.
    if (probe.get("orderbooks") or {}).get("returned") != tickers:
        problems.append(
            "orderbooks not returned in request order: "
            f"{(probe.get('orderbooks') or {}).get('returned')} != {tickers}")

    # 3. The measured contract itself must still hold: if the host ever flips
    #    which serialisation it accepts, the probe is wrong and this must fail.
    def accepted(path_label: str, label: str, expect_n: int) -> bool:
        row = forms.get(f"{path_label}:{label}") or {}
        return row.get("status") == 200 and row.get("n") == expect_n

    if tickers and not accepted("markets", "comma", len(set(tickers))):
        problems.append(
            "GET /markets no longer accepts the comma-joined form "
            f"({(forms.get('markets:comma') or {})}); re-measure and update the probe")
    if tickers and not accepted("orderbooks-plural", "repeated", len(set(tickers))):
        problems.append(
            "GET /markets/orderbooks no longer accepts repeated parameters "
            f"({(forms.get('orderbooks-plural:repeated') or {})}); re-measure")

    # 4. The documentation's `+0.877` trap: a comma-joined order-book request
    #    must NOT be silently equivalent, or nobody would know which is right.
    comma_books = forms.get("orderbooks-plural:comma") or {}
    if comma_books.get("status") == 200 and comma_books.get("n") == len(set(tickers)) \
            and comma_books.get("returned") == tickers:
        problems.append(
            "comma-joined order-book request now behaves like the repeated one; "
            "the probe's per-endpoint serialisation is no longer justified by "
            "measurement and must be re-verified")

    if problems:
        for p in problems:
            print(" - " + p, file=sys.stderr)
        return 1
    print("shape invariants hold: comma for /markets, repeated for /orderbooks, "
          "full coverage, request order")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
