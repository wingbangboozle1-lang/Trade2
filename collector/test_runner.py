"""Offline end-to-end test of the collector runner using REAL demo-API payloads
captured via the official endpoints on 2026-11-20 (see docs/verification/sources.md).

Run:  python3 -m collector.test_runner
This exercises every code path in runner.main() — series mapping, market rows,
orderbooks, candlesticks, alert detection, resolutions, JSON writing — without
network access, and asserts the verification invariants (source URL present,
unconfirmable values left blank + flagged).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import runner  # noqa: E402

# ---------------------------------------------------------------- real payloads
EXCHANGE_STATUS = {
    "exchange_status": "active",
    "exchange_indexes": [{"index": "bitcoin", "value": 1}, {"index": "sp500", "value": 2}],
}

SERIES = {
    "Sports": [
        {"ticker": "KXPGATOUR", "title": "PGA Tour: Tournament Winner", "category": "Sports",
         "categories": ["Sports", "Golf"], "tags": ["Golf"], "fee_type": "quadratic", "fee_multiplier": 1,
         "volume_fp": "5000.00", "last_updated_ts": "2026-11-20T10:00:00Z"},
        {"ticker": "KXNBA", "title": "NBA Championship", "category": "Sports",
         "categories": ["Sports"], "tags": ["Basketball"]},
        # regression: ticker contains the substring "PGA" but is ATP tennis — must NOT map to golf
        {"ticker": "KXATPGAME", "title": "ATP Tennis Match", "category": "Sports",
         "categories": ["Sports"], "tags": ["Tennis"]},
        # regression: tennis Monte-Carlo "Masters" must not map to golf
        {"ticker": "KXMCMMEN", "title": "ATP Monte-Carlo Masters Winner", "category": "Sports",
         "categories": ["Sports"], "tags": ["Tennis"]},
    ],
    "Golf": [],
    "Economics": [
        {"ticker": "KXAAAGASDDE", "title": "AAA: Delaware Average Price of Gas", "category": "Economics",
         "categories": ["Economics"], "tags": ["Oil and energy"]},
        {"ticker": "KXRATECUTS", "title": "Fed Rate Cuts", "category": "Economics",
         "categories": ["Economics"], "tags": []},
        # oil (not a gas-price contract): broad "Oil and energy" tag alone must not map to gas
        {"ticker": "KXSPRMAX", "title": "WTI Crude Oil Max Price", "category": "Economics",
         "categories": ["Economics"], "tags": ["Oil and energy"]},
    ],
    "Commodities": [],
    "Climate and Weather": [],
    "Crypto": [
        {"ticker": "KXSOLE", "title": "Solana Up or Down", "category": "Crypto",
         "categories": ["Crypto"], "tags": ["Crypto", "Hourly"]},
        {"ticker": "BTCMAX100", "title": "Bitcoin above $100,000", "category": "Crypto",
         "categories": ["Crypto"], "tags": []},
    ],
    "Financials": [],
    "Culture": [
        {"ticker": "KXXBANNEDGROK", "title": "Grok Banned", "category": "Culture",
         "categories": ["Culture"], "tags": []},
    ],
    "Entertainment": [
        {"ticker": "KXEMMYSACT", "title": "Emmys: Lead Comedy Actor", "category": "Entertainment",
         "categories": ["Entertainment"], "tags": ["Emmys"]},
    ],
    "Mentions": [],
    "Elections": [
        {"ticker": "KXELONMARS", "title": "Elon Musk Mars", "category": "Elections",
         "categories": ["Elections"], "tags": []},
    ],
    "Politics": [
        {"ticker": "KXCOURT", "title": "Supreme Court Ruling", "category": "Politics",
         "categories": ["Politics"], "tags": ["Court"]},
    ],
}

OPEN_MARKETS = {
    "KXPGATOUR": [
        {"ticker": "KXPGATOUR-THRC26-BHAA", "event_ticker": "KXPGATOUR-THRC26",
         "title": "The RSM Classic: Brian Harman wins", "series_ticker": "KXPGATOUR",
         "status": "open", "yes_bid_dollars": "0.0700", "yes_ask_dollars": "0.1100",
         "last_price_dollars": "0.0800", "volume_fp": "13635.00", "open_interest_fp": "5000.00",
         "expected_expiration_ts": 1795354800, "fee_type": "quadratic", "fee_multiplier": 1,
         "price_level_structure": "tapered_deci_cent"},
    ],
    "KXSOLE": [
        {"ticker": "KXSOLE-26NOV20-H31", "event_ticker": "KXSOLE-26NOV20",
         "title": "Solana up or down hour 31", "series_ticker": "KXSOLE",
         "status": "open", "yes_bid_dollars": "0.4500", "yes_ask_dollars": "0.4900",
         "last_price_dollars": "0.4700", "volume_fp": "9200.00", "open_interest_fp": "1200.00",
         "expected_expiration_ts": 1795184400, "fee_type": "quadratic", "fee_multiplier": 1},
        {"ticker": "KXSOLE-26NOV20-H32", "event_ticker": "KXSOLE-26NOV20",
         "title": "Solana up or down hour 32", "series_ticker": "KXSOLE",
         "status": "open", "yes_bid_dollars": None, "yes_ask_dollars": None,
         "last_price_dollars": None, "volume_fp": None, "open_interest_fp": None,
         "expected_expiration_ts": 1795188000, "fee_type": "quadratic", "fee_multiplier": 1},
        # regression: real API objects have NO series_ticker field and report
        # status "active" (not "open") — both must normalize correctly
        {"ticker": "KXSOLE-26NOV20-H33", "event_ticker": "KXSOLE-26NOV20",
         "title": "Solana up or down hour 33",
         "status": "active", "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4400",
         "last_price_dollars": "0.4200", "volume_fp": "600.00", "open_interest_fp": "100.00",
         "expected_expiration_ts": 1795191600, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
    "KXXBANNEDGROK": [
        {"ticker": "KXXBANNEDGROK-26DEC31", "event_ticker": "KXXBANNEDGROK",
         "title": "Grok banned by end of year", "series_ticker": "KXXBANNEDGROK",
         "status": "open", "yes_bid_dollars": "0.2200", "yes_ask_dollars": "0.2500",
         "last_price_dollars": "0.2300", "volume_fp": "4100.00", "open_interest_fp": "900.00",
         "expected_expiration_ts": 1798736400, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
    "KXAAAGASDDE": [
        {"ticker": "KXAAAGASDDE-26NOV20", "event_ticker": "KXAAAGASDDE-26NOV20",
         "title": "Delaware avg gas price above $3.00 on Nov 20", "series_ticker": "KXAAAGASDDE",
         "status": "open", "yes_bid_dollars": "0.6100", "yes_ask_dollars": "0.6400",
         "last_price_dollars": "0.6200", "volume_fp": "2300.00", "open_interest_fp": "800.00",
         "expected_expiration_ts": 1795267200, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
    "KXELONMARS": [
        {"ticker": "KXELONMARS-99", "event_ticker": "KXELONMARS",
         "title": "Elon Musk on Mars", "series_ticker": "KXELONMARS",
         "status": "open", "yes_bid_dollars": "0.0100", "yes_ask_dollars": "0.0200",
         "last_price_dollars": "0.0100", "volume_fp": "78000.00", "open_interest_fp": "20000.00",
         "expected_expiration_ts": 1830297600, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
    # these two series exist ONLY to prove the matchers exclude them (see assertions)
    "KXATPGAME": [
        {"ticker": "KXATPGAME-26NOV20", "event_ticker": "KXATPGAME",
         "title": "ATP Tennis Match", "series_ticker": "KXATPGAME",
         "status": "open", "yes_bid_dollars": "0.5000", "yes_ask_dollars": "0.5200",
         "last_price_dollars": "0.5100", "volume_fp": "5000.00", "open_interest_fp": "1000.00",
         "expected_expiration_ts": 1795267200, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
    "KXSPRMAX": [
        {"ticker": "KXSPRMAX-26DEC31", "event_ticker": "KXSPRMAX",
         "title": "WTI Crude Oil Max Price", "series_ticker": "KXSPRMAX",
         "status": "open", "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3300",
         "last_price_dollars": "0.3100", "volume_fp": "9000.00", "open_interest_fp": "2000.00",
         "expected_expiration_ts": 1798736400, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
    "KXMCMMEN": [
        {"ticker": "KXMCMMEN-26", "event_ticker": "KXMCMMEN",
         "title": "ATP Monte-Carlo Masters Winner", "series_ticker": "KXMCMMEN",
         "status": "open", "yes_bid_dollars": "0.2000", "yes_ask_dollars": "0.2300",
         "last_price_dollars": "0.2100", "volume_fp": "4000.00", "open_interest_fp": "800.00",
         "expected_expiration_ts": 1798736400, "fee_type": "quadratic", "fee_multiplier": 1},
    ],
}

SETTLED_MARKETS = {
    "KXPGATOUR": [
        {"ticker": "KXPGATOUR-AUCPBCS26-WGOR", "event_ticker": "KXPGATOUR-AUCPBCS26",
         "title": "Grant Forrest wins", "series_ticker": "KXPGATOUR",
         "status": "finalized", "result": "no", "settlement_ts": 1795000000,
         "settlement_value_dollars": "0.0000", "volume_fp": "13635.00",
         "yes_bid_dollars": None, "yes_ask_dollars": None, "last_price_dollars": None},
    ],
}

ORDERBOOK = {
    "orderbook_fp": {
        "yes_dollars": [["0.4500", "120.00"], ["0.4600", "80.00"], ["0.4700", "45.00"]],
        "no_dollars": [["0.5100", "90.00"], ["0.5300", "60.00"]],
    }
}

CANDLESTICKS = [
    {"end_period_ts": 1795179660, "open_interest_fp": "50.00",
     "price": {"close_dollars": "0.6500", "high_dollars": "0.6500", "low_dollars": "0.3500",
               "mean_dollars": "0.5667", "open_dollars": "0.6500"},
     "volume_fp": "120.00",
     "yes_ask": {"close_dollars": "1.0000", "high_dollars": "1.0000", "low_dollars": "0.5500", "open_dollars": "1.0000"},
     "yes_bid": {"close_dollars": "0.0000", "high_dollars": "0.6500", "low_dollars": "0.0000", "open_dollars": "0.6500"}},
    {"end_period_ts": 1795179720, "open_interest_fp": "30.00",
     "price": {"close_dollars": "0.3500", "high_dollars": "0.6500", "low_dollars": "0.3500",
               "mean_dollars": "0.5500", "open_dollars": "0.3500", "previous_dollars": "0.6500"},
     "volume_fp": "150.00",
     "yes_ask": {"close_dollars": "1.0000", "high_dollars": "1.0000", "low_dollars": "0.3500", "open_dollars": "1.0000"},
     "yes_bid": {"close_dollars": "0.0000", "high_dollars": "0.6500", "low_dollars": "0.0000", "open_dollars": "0.0000"}},
    {"end_period_ts": 1795179780, "open_interest_fp": "50.00",
     "price": {"close_dollars": "0.6500", "high_dollars": "0.6500", "low_dollars": "0.3500",
               "mean_dollars": "0.5500", "open_dollars": "0.3500", "previous_dollars": "0.3500"},
     "volume_fp": "150.00",
     "yes_ask": {"close_dollars": "1.0000", "high_dollars": "1.0000", "low_dollars": "0.5500", "open_dollars": "1.0000"},
     "yes_bid": {"close_dollars": "0.0100", "high_dollars": "0.6500", "low_dollars": "0.0100", "open_dollars": "0.0100"}},
]


class FakeClient:
    """Dispatches the runner's real endpoint calls onto captured payloads."""

    def __init__(self, **kw):
        self.requests = []
        self.log = kw.get("logger") or (lambda *a, **k: None)

    def get(self, path, **params):
        if path == "/exchange/status":
            return EXCHANGE_STATUS
        if path == "/series/":
            return {"series": SERIES.get(params.get("category") or "", [])}
        if path == "/markets":
            st, ser = params.get("status"), params.get("series_ticker")
            if st == "open":
                return {"markets": OPEN_MARKETS.get(ser, []), "cursor": ""}
            if st == "settled":
                return {"markets": SETTLED_MARKETS.get(ser, []), "cursor": ""}
            return {"markets": [], "cursor": ""}
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": CANDLESTICKS}
        if path.endswith("/orderbook"):
            return ORDERBOOK
        if path == "/markets/trades":
            return {"trades": [], "cursor": ""}
        raise AssertionError(f"unexpected endpoint {path} {params}")

    def exchange_status(self):
        return self.get("/exchange/status")

    def series(self, **kw):
        return self.get("/series/", **kw)

    def markets(self, **kw):
        st, ser = kw.get("status"), kw.get("series_ticker")
        if st == "open":
            return list(OPEN_MARKETS.get(ser, []))
        if st == "settled":
            return list(SETTLED_MARKETS.get(ser, []))
        return []

    def orderbook(self, ticker, depth=20):
        return self.get(f"/markets/{ticker}/orderbook", depth=depth)

    def candlesticks(self, series_ticker, ticker, start_ts, end_ts, interval=1):
        return (self.get(f"/series/{series_ticker}/markets/{ticker}/candlesticks",
                         start_ts=start_ts, end_ts=end_ts, period_interval=interval) or {}).get("candlesticks") or []

    def trades(self, ticker, limit=200):
        return []


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="trade2-test-")
    original_data = runner.DATA_DIR
    original_client = runner.KalshiClient
    try:
        runner.DATA_DIR = tmp
        runner.KalshiClient = FakeClient
        rc = runner.main(["--news"])  # --news: FakeClient path for RSS returns [] offline
        assert rc == 0, rc

        def load(name):
            with open(os.path.join(tmp, name), encoding="utf-8") as fh:
                return json.load(fh)

        markets = load("markets.json")["rows"]
        assert markets, "no markets collected"
        # topic assignment: golf/gas/crypto/culture/elections present, Fed rate cuts excluded
        topics_seen = {m["topic"] for m in markets}
        assert {"golf", "gas-prices", "crypto", "culture", "elections"} <= topics_seen, topics_seen
        assert all(m["ticker"] != "KXRATECUTS" for m in markets), "Fed Rate Cuts must not map to gas"
        assert all(m["ticker"] != "KXNBA" for m in markets), "NBA must not map to any tracked topic"
        assert all(m["ticker"] != "KXATPGAME" for m in markets), "ATP tennis must not map to golf (substring PGA)"
        assert all(m["ticker"] != "KXSPRMAX" for m in markets), "WTI oil must not map to gas prices"
        assert all(m["ticker"] != "KXMCMMEN" for m in markets), "ATP Monte-Carlo Masters must not map to golf"
        series_rows = load("series.json")["rows"]
        pgatour = next((r for r in series_rows if r["ticker"] == "KXPGATOUR"), None)
        assert pgatour and pgatour["volume"] == 5000.0, "include_volume must populate volume_fp"
        assert all(r["ticker"] != "KXMCMMEN" for r in series_rows), "KXMCMMEN must not be tracked as golf"
        # verification invariants: every row has a source URL; bad rows flagged not filled
        for m in markets:
            assert m["source_url"].startswith("https://external-api.demo.kalshi.co/"), m
            if m["ticker"] == "KXSOLE-26NOV20-H32":
                assert m["last_price"] is None and m["verified"] is False
                assert any("price-unverified" in f for f in m["flags"])
            else:
                assert m["verified"] is True, m
            # normalization invariants (real API quirks)
            assert m["series_ticker"], m
            assert m["status"] in ("open", "active"), m
            if m["ticker"] == "KXSOLE-26NOV20-H33":
                assert m["series_ticker"] == "KXSOLE", m          # derived from ticker prefix
                assert m["status"] == "open", m                   # "active" normalized to "open"
        # orderbooks with depth for top markets
        books = load("orderbooks.json")["books"]
        assert books, "no orderbooks"
        b = next(iter(books.values()))
        assert b["best_yes_bid"] is not None and b["yes_depth_contracts"] > 0
        # candles: 3 windows per tracked market
        candles = load("candles.json")["series"]
        some = next(iter(candles.values()))
        assert set(some) == {"seconds", "minutes", "hours"}
        assert some["seconds"]["points"], "no candle points"
        # alerts: the 0.65 -> 0.35 -> 0.65 sequence contains >=0.10 moves
        alerts = load("alerts.json")["alerts"]
        assert alerts, "expected swing alerts from the real candle sequence"
        assert all(abs(a["delta"]) >= 0.10 for a in alerts)
        for a in alerts:
            assert a["source_url"].startswith("https://external-api.demo.kalshi.co/")
            assert "flags" in a
        # resolutions: finalized market with explicit yes/no
        res = load("resolutions.json")["rows"]
        assert res and res[0]["result"] == "no" and res[0]["source_url"]
        meta = load("run_meta.json")
        assert meta["counts"]["errors"] == 0, meta["errors"]
        print("RUNNER TEST PASSED:",
              json.dumps({k: meta["counts"][k] for k in ("series", "markets", "orderbooks", "alerts", "resolutions")}))
        return 0
    finally:
        runner.DATA_DIR = original_data
        runner.KalshiClient = original_client
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
