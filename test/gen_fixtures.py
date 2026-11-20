"""Generates fixture site data (REAL captured API payload shapes, no network) into a
target directory, for the jsdom site smoke test only.

  python3 test/gen_fixtures.py /tmp/trade2-fixture-data

Never commit its output as live data: the live files come from GitHub Actions.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

from collector import runner  # noqa: E402
from collector.test_runner import FakeClient  # noqa: E402
from trading import engine  # noqa: E402


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/trade2-fixture-data"
    os.makedirs(out, exist_ok=True)

    orig_data, orig_client = runner.DATA_DIR, runner.KalshiClient
    try:
        runner.DATA_DIR = out
        runner.KalshiClient = FakeClient
        rc = runner.main([])  # no --news: offline
        assert rc == 0, rc
    finally:
        runner.DATA_DIR, runner.KalshiClient = orig_data, orig_client

    # run the paper engine against the fixture data just written; several cycles so
    # entries open AND close (stats tables need closed trades to populate)
    import json

    orig_engine_data = engine.DATA
    try:
        engine.DATA = out
        rc = engine.main(["--reset"])
        assert rc == 0, rc

        # settle two open positions (one win, one loss) the way a real run would:
        # resolutions.json gains their tickers, then the engine grades them.
        res_path = os.path.join(out, "resolutions.json")
        pf_path = os.path.join(out, "portfolio.json")
        with open(res_path, encoding="utf-8") as fh:
            res = json.load(fh)
        with open(pf_path, encoding="utf-8") as fh:
            pf = json.load(fh)
        open_tickers = [p["ticker"] for p in pf.get("positions", [])]
        for ticker, result in zip(open_tickers[:2], ("yes", "no")):
            res["rows"].append({"ticker": ticker, "event_ticker": ticker, "title": "fixture settlement",
                                "topic": "crypto", "result": result, "settlement_value": 1.0 if result == "yes" else 0.0,
                                "settlement_ts": 1795180000, "volume_fp": 100.0,
                                "source_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}",
                                "docs_url": "https://docs.kalshi.com/getting_started/market_settlement",
                                "verified": True})
        with open(res_path, "w", encoding="utf-8") as fh:
            json.dump(res, fh)

        for _ in range(3):
            rc = engine.main([])
            assert rc == 0, rc
    finally:
        engine.DATA = orig_engine_data

    print("fixtures written to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
