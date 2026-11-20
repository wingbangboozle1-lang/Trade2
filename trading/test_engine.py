"""Tests for the paper-trading engine.

Run:  python3 -m trading.test_engine
The fee table below is transcribed from the official schedule PDF:
https://kalshi.com/docs/kalshi-fee-schedule.pdf (General Trading Fees Table,
"Last updated and effective: July 7, 2026"). Every row must match exactly.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.engine import Engine, fee_maker, fee_taker, stats  # noqa: E402

# (price, fee for 1 contract, fee for 100 contracts) straight from the official PDF
OFFICIAL_TABLE = [
    (0.01, 0.01, 0.07), (0.05, 0.01, 0.34), (0.10, 0.01, 0.63), (0.15, 0.01, 0.90),
    (0.20, 0.02, 1.12), (0.25, 0.02, 1.32), (0.30, 0.02, 1.47), (0.35, 0.02, 1.60),
    (0.40, 0.02, 1.68), (0.45, 0.02, 1.74), (0.50, 0.02, 1.75), (0.55, 0.02, 1.74),
    (0.60, 0.02, 1.68), (0.65, 0.02, 1.60), (0.70, 0.02, 1.47), (0.75, 0.02, 1.32),
    (0.80, 0.02, 1.12), (0.85, 0.01, 0.90), (0.90, 0.01, 0.63), (0.95, 0.01, 0.34),
    (0.99, 0.01, 0.07),
]


def test_fee_table() -> None:
    for price, f1, f100 in OFFICIAL_TABLE:
        got1, got100 = fee_taker(1, price), fee_taker(100, price)
        assert abs(got1 - f1) < 1e-9, f"1@{price}: got {got1} want {f1}"
        assert abs(got100 - f100) < 1e-9, f"100@{price}: got {got100} want {f100}"
    assert fee_maker(100, 0.50, 0.0) == 0.0  # maker M defaults to 0 -> no fee
    assert fee_maker(100, 0.50, 1.0) == 0.44  # ceil(0.0175*100*0.5*0.5)=ceil(0.4375)
    print("OK fee table matches the official PDF (42 checks + maker)")


def test_open_close_settle() -> None:
    eng = Engine()
    # open a YES position at 0.40 on a thin book
    pos = eng.open_position("T-1", "yes", 0.40, "roi_edge", "test", "crypto", 1.0, "unit test")
    assert pos and pos["contracts"] >= 1
    cash_after = eng.cash
    assert cash_after < 10000

    # mark moves +0.06 -> target exit
    books = {"T-1": {"best_yes_bid": 0.46, "best_no_bid": 0.53, "yes_depth_usd": 100, "no_depth_usd": 80}}
    res = eng.step([], books, [], [])
    assert "T-1" not in eng.positions, "position should have taken profit at +0.06"
    closed = [t for t in eng.trades if t["action"] == "close"][-1]
    assert closed["pnl"] > 0, closed
    print(f"OK open -> +0.06 target exit, pnl={closed['pnl']}")

    # settlement grading: buy NO, market resolves 'no' -> wins $1.00/contract
    eng2 = Engine()
    eng2.open_position("T-2", "no", 0.30, "roi_edge", "test", "golf", 1.0, "settle test")
    eng2.step([], {}, [], [{"ticker": "T-2", "result": "no"}])
    assert "T-2" not in eng2.positions
    c = [t for t in eng2.trades if t["action"] == "close"][-1]
    assert c["settlement"] == "no" and c["pnl"] > 0, c
    print(f"OK settlement grading on T-2 (won), pnl={c['pnl']}")

    # losing settlement: buy YES, resolves 'no' -> lose the cost
    eng3 = Engine()
    eng3.open_position("T-3", "yes", 0.50, "swing_momentum", "test", "elections", 1.0, "lose test")
    eng3.step({}, {}, [], [{"ticker": "T-3", "result": "no"}])
    c3 = [t for t in eng3.trades if t["action"] == "close"][-1]
    assert c3["pnl"] < 0, c3
    print(f"OK settlement grading on T-3 (lost), pnl={c3['pnl']}")


def test_signal_rules() -> None:
    eng = Engine()
    markets = [
        {"ticker": "A-1", "status": "open", "topic": "crypto", "fee_multiplier": 1.0},
        {"ticker": "A-2", "status": "open", "topic": "golf", "fee_multiplier": 1.0},
    ]
    books = {
        "A-1": {"best_yes_bid": 0.30, "best_no_bid": 0.65, "yes_depth_usd": 500.0, "no_depth_usd": 100.0},
        "A-2": {"best_yes_bid": 0.55, "best_no_bid": 0.44, "yes_depth_usd": 100.0, "no_depth_usd": 100.0},
    }
    alerts = [
        {"ticker": "A-1", "delta": -0.30, "window": "seconds"},   # >=0.10 down -> swing strategies + roi
        {"ticker": "A-2", "delta": -0.04, "window": "seconds"},   # below threshold -> ignored
        {"ticker": "A-3", "delta": -0.20, "window": "seconds"},   # unknown market -> ignored
    ]
    sigs = eng.signals(markets, books, alerts)
    strats = {(s["strategy"], s["ticker"]) for s in sigs}
    assert ("swing_momentum", "A-1") in strats
    assert ("swing_reversal", "A-1") in strats
    assert ("roi_edge", "A-1") in strats
    assert all(s["ticker"] != "A-2" or s["strategy"] == "roi_edge" for s in sigs), "sub-threshold alert must not fire swing strategies"
    assert all(s["ticker"] != "A-3" for s in sigs)
    # A-1 depth imbalance: yes_usd 500 vs no_usd 100 -> fair 0.833, ask=0.35 -> book-undervalued-yes
    assert any(s["signal"] == "book-undervalued-yes" for s in sigs)
    # every roi_edge signal must have a positive net-edge score >= ROI_MIN
    assert all((s.get("score") or 0) >= 0.02 for s in sigs if s["strategy"] == "roi_edge")
    print(f"OK signal rules ({len(sigs)} signals; threshold + unknown-ticker + imbalance checks)")


def test_stats_categorization() -> None:
    trades = [
        {"action": "close", "strategy": "roi_edge", "trade_type": "roi_edge|high-roi-fade|yes", "pnl": 2.0, "fee": 0.5},
        {"action": "close", "strategy": "roi_edge", "trade_type": "roi_edge|high-roi-fade|yes", "pnl": -1.0, "fee": 0.5},
        {"action": "close", "strategy": "swing_momentum", "trade_type": "swing_momentum|swing-up|yes", "pnl": 3.0, "fee": 0.2},
        {"action": "open", "strategy": "roi_edge", "trade_type": "x", "pnl": 0, "fee": 0.1},
    ]
    s = stats(trades)
    assert s["all"]["trades"] == 3
    assert s["by_strategy"]["roi_edge"]["trades"] == 2
    assert abs(s["by_strategy"]["roi_edge"]["win_rate"] - 0.5) < 1e-9
    assert s["by_trade_type"]["swing_momentum|swing-up|yes"]["net_pnl"] == 3.0
    print("OK stats aggregate by strategy and trade type")


if __name__ == "__main__":
    test_fee_table()
    test_open_close_settle()
    test_signal_rules()
    test_stats_categorization()
    print("ALL TRADING TESTS PASSED")
