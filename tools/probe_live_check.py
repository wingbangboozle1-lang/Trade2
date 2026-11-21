#!/usr/bin/env python3
"""Verify the browser live probe's request shapes against the REAL demo API.

The sandbox that wrote ``assets/live-probe.js`` has no route to Kalshi, so the
only thing it could not check locally was whether the URLs the browser builds
are accepted and interpreted the way the code assumes. This script closes that
gap in CI, where egress is unrestricted.

It deliberately tests *every* plausible serialisation of the ``tickers`` filter
and reports which ones the live API actually honours, then asserts the one the
probe uses is correct. That is how the first bug here was found:
``?tickers=A,B`` and ``?tickers=A&tickers=B`` both looked right on paper; only
the live host can say which it accepts.

    python3 tools/probe_live_check.py [--json out.json]
Exit 0 when the probe's own serialisation is confirmed working, 1 otherwise.
Never writes to the repository and never sends an order.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "data", "live.json")
BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
UA = "Trade2-probe-check/1.0 (+github.com/wingbangboozle1-lang/Trade2)"


def fetch(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp), None
    except urllib.error.HTTPError as exc:
        body = exc.read()[:400].decode("utf-8", "replace")
        return exc.code, None, body
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return None, None, f"{type(exc).__name__}: {exc}"


def top_tickers(limit: int = 2) -> list[str]:
    with open(LIVE, encoding="utf-8") as fh:
        live = json.load(fh)
    rows = [e for e in (live.get("events") or [])
            if e.get("ticker") and e.get("yes_bid") is not None
            and e.get("yes_ask") is not None]
    rows.sort(key=lambda e: e.get("open_interest_notional") or 0, reverse=True)
    seen, out = set(), []
    for row in rows:
        if row["ticker"] in seen:
            continue
        seen.add(row["ticker"])
        out.append(row["ticker"])
        if len(out) >= limit:
            break
    return out


def probe_urls(tickers: list[str]) -> dict[str, str]:
    """Build the URLs with the probe's own serialiser (not by hand)."""
    node = shutil.which("node")
    if not node:
        raise SystemExit("node is required to build the probe's URLs")
    script = r"""
const path = require("path");
const L = require(path.join(process.argv[1], "assets", "live-probe.js"));
const tickers = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify({
  query: L.tickersQuery(tickers),
  markets: L.ENDPOINTS.markets + "?" + L.tickersQuery(tickers),
  orderbooks: L.ENDPOINTS.orderbooks + "?" + L.tickersQuery(tickers)
}));
"""
    out = subprocess.run([node, "-e", script, ROOT, json.dumps(tickers)],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit("could not run the probe module under node:\n" + out.stderr)
    return json.loads(out.stdout)


def result_shape(body):
    if not isinstance(body, dict):
        return None
    rows = body.get("orderbooks") or body.get("markets") or []
    return [r.get("ticker") for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    problems: list[str] = []
    report: dict = {"base": BASE}

    tickers = top_tickers()
    if len(tickers) < 2:
        print("not enough quoted markets in data/live.json to check")
        return 1
    report["tickers"] = tickers

    urls = probe_urls(tickers)
    report["probe_urls"] = urls
    report["probe_query"] = urls["query"]

    # -- what the probe actually sends, per endpoint -----------------------
    report["probe"] = {}
    for name, key in (("markets", "markets"), ("orderbooks", "orderbooks")):
        status, body, err = fetch(urls[key])
        got = result_shape(body)
        report["probe"][name] = {"status": status, "returned": got, "error": err}
        if status != 200:
            problems.append(f"probe {name} URL returned {status}: {err}")
        elif name == "markets":
            missing = [t for t in tickers if t not in (got or [])]
            if missing:
                problems.append(f"markets response missing {missing} (got {got})")
        else:
            if got != tickers:
                problems.append(
                    f"orderbooks not in request order: {got} != {tickers}")

    # -- which serialisations does the host honour? ------------------------
    def q_repeated(ts):
        return "&".join("tickers=" + urllib.parse.quote(t) for t in ts)

    def q_comma(ts):
        return "tickers=" + urllib.parse.quote(",".join(ts))

    def q_brackets(ts):
        return "&".join("tickers[]=" + urllib.parse.quote(t) for t in ts)

    forms = {
        "repeated": q_repeated(tickers),
        "comma": q_comma(tickers),
        "brackets": q_brackets(tickers),
        "single": "tickers=" + urllib.parse.quote(tickers[0]),
    }
    report["forms"] = {}
    for label, qs in forms.items():
        for endpoint in ("markets", "orderbooks"):
            status, body, err = fetch(f"{BASE}/{endpoint}?{qs}")
            got = result_shape(body)
            report["forms"][f"{endpoint}:{label}"] = {
                "status": status,
                "n": None if got is None else len(got),
                "returned": got,
                "error": err,
            }

    # -- assert the probe's choice against what the host honours -----------
    ok_forms = [label for label in forms
                if (report["forms"].get(f"orderbooks:{label}", {}).get("returned")
                    == tickers)]
    report["orderbooks_forms_returning_both"] = ok_forms
    if ok_forms and "repeated" not in ok_forms:
        problems.append(
            "orderbooks accepts " + ", ".join(ok_forms) +
            " but not repeated parameters; the probe must change")

    text = json.dumps(report, indent=1)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)

    if problems:
        print("\nPROBE LIVE CHECK FAILED", file=sys.stderr)
        for p in problems:
            print(" - " + p, file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # Annotations are the only channel guaranteed to survive a
            # restricted client, so the whole verdict rides along with them.
            summary = json.dumps({
                "forms": {k: {"status": v.get("status"), "n": v.get("n")}
                          for k, v in (report.get("forms") or {}).items()},
                "orderbooks_forms_returning_both":
                    report.get("orderbooks_forms_returning_both"),
            })
            for chunk in [problems[0]]:
                msg = chunk.replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
                print(f"::error title=Probe live check::{msg}")
            smsg = summary.replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
            print(f"::notice title=Tickers forms tested::{smsg[:6000]}")
        return 1
    print("\nprobe live check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
