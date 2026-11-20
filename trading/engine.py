"""Simulated (paper) trading engine on Kalshi demo market data.

What this is
------------
No API credentials exist in this environment (see FL-01 in COORDINATION.md), so the
engine never sends orders. It consumes the collector's JSON (real demo order books,
prices, alerts, resolutions), simulates taker fills against the *real* resting
liquidity, applies the *official* fee formula, and grades every trade against real
settlement outcomes when markets resolve.

Fees — official source: https://kalshi.com/docs/kalshi-fee-schedule.pdf (eff. 2026-07-07)
    taker: fee = ceil_cent(C*P + M*0.07*C*P*(1-P)) - C*P      (M defaults to 1)
    maker: fee = ceil_cent(C*P + M*0.0175*C*P*(1-P)) - C*P     (M defaults to 0)
    "round up such that the fee + positionCost is rounded to a centicent"
    There is no settlement fee and no membership fee (same PDF).
    The implementation below reproduces the PDF's General Trading Fees Table exactly
    (see test_engine.py).

Strategies — all simulated, parameters explicit, results measured not promised:
    swing_reversal  after a >= $0.10 down-swing, buy YES expecting partial reversion
                    (and the mirror after an up-swing); exit on +$0.05, -$0.05 stop,
                    or 40 candle periods.
    swing_momentum  follow a >= $0.10 move in its direction; exit when the move
                    stalls (two flat periods) or reverses by >= $0.05.
    roi_edge        "high ROI" filter: only trades whose opportunity score
                    score = reversion_share * swing - fee_per_contract - spread
                    (expected net dollars per contract after friction) clears ROI_MIN.
                    The reversion share is an explicit assumption (REVERSION_SHARE),
                    not a forecast.

State persists in docs/data/portfolio.json between runs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")

START_CASH = 10000.00          # simulated starting balance (not an API value)
MAX_OPEN = 8                   # concurrent positions
PER_POSITION_USD = 200.00      # max cost per position
DAILY_LOSS_CAP = 150.00        # stop trading for the day after this much loss
EXIT_TARGET = 0.05             # take-profit in dollars per contract
EXIT_STOP = 0.05               # stop-loss in dollars per contract
MOMENTUM_STALLS = 2            # flat periods before a momentum exit
MAX_HOLD_PERIODS = 40          # force-exit after this many candle periods
REVERSION_SHARE = 0.30         # assumed fraction of a swing that reverts (assumption!)
ROI_MIN = 0.02                 # min expected net $/contract after fee+spread
SPREAD_MAX = 0.06              # skip markets wider than this

FEE_SCHEDULE_URL = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_SCHEDULE_PAGE = "https://kalshi.com/fee-schedule"


# --------------------------------------------------------------------- fees
def _ceil_cent(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def fee_taker(contracts: float, price: float, multiplier: float = 1.0) -> float:
    """Official taker fee: ceil to the cent of M*0.07*C*P*(1-P).

    This reproduces every row of the PDF's General Trading Fees Table exactly
    (test_fee_table below). The PDF's prose also describes rounding fee+positionCost
    to a centicent; on the published table both readings agree after the fee is
    rounded to cents for charge display, so we follow the table.
    """
    c, p, m = Decimal(str(contracts)), Decimal(str(price)), Decimal(str(multiplier))
    if c <= 0 or p <= 0:
        return 0.0
    raw = m * Decimal("0.07") * c * p * (Decimal(1) - p)
    return float(max(_ceil_cent(raw), Decimal(0)))


def fee_maker(contracts: float, price: float, multiplier: float = 0.0) -> float:
    c, p, m = Decimal(str(contracts)), Decimal(str(price)), Decimal(str(multiplier))
    if c <= 0 or p <= 0 or m == 0:
        return 0.0
    raw = m * Decimal("0.0175") * c * p * (Decimal(1) - p)
    return float(max(_ceil_cent(raw), Decimal(0)))


# ------------------------------------------------------------------ helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(name: str, default: Any = None) -> Any:
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(name: str, payload: Any) -> None:
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def implied_prices(book: Dict) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """(best_yes_bid, implied_yes_ask, spread) from the bids-only book."""
    yb = book.get("best_yes_bid")
    nb = book.get("best_no_bid")
    ask = round(1.0 - nb, 4) if nb is not None else None
    spread = round(ask - yb, 4) if (ask is not None and yb is not None) else None
    return yb, ask, spread


def book_edge(book: Dict) -> Optional[float]:
    """Depth-imbalance estimate of fair YES probability: yes_usd / (yes_usd + no_usd)."""
    y, n = book.get("yes_depth_usd") or 0.0, book.get("no_depth_usd") or 0.0
    if y + n <= 0:
        return None
    return round(y / (y + n), 4)


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, state: Optional[Dict] = None) -> None:
        state = state or {}
        self.cash: float = float(state.get("cash", START_CASH))
        raw_pos = state.get("positions", {})
        if isinstance(raw_pos, list):  # JSON round-trip stores positions as a list
            self.positions = {p["ticker"]: p for p in raw_pos if isinstance(p, dict) and p.get("ticker")}
        else:
            self.positions = dict(raw_pos)
        self.trades: List[Dict] = list(state.get("trades", []))
        self.equity_curve: List[Dict] = list(state.get("equity_curve", []))
        self.fees_paid: float = float(state.get("fees_paid", 0.0))
        self.realized_pnl: float = float(state.get("realized_pnl", 0.0))
        self.day_key: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.day_start_equity: float = float(state.get("day_start_equity", self.equity()))
        self.day_realized: float = 0.0
        self.blocked_today = False

    # ------------------------------------------------------------ valuation
    def equity(self, marks: Optional[Dict[str, float]] = None) -> float:
        pos_val = 0.0
        for t, p in self.positions.items():
            mark = (marks or {}).get(t)
            if mark is None:
                mark = p["avg_price"]
            pos_val += p["contracts"] * mark
        return round(self.cash + pos_val, 2)

    def mark_prices(self, books: Dict[str, Dict]) -> Dict[str, float]:
        out = {}
        for t, p in self.positions.items():
            book = books.get(t) or {}
            yb, ask, _ = implied_prices(book)
            if p["side"] == "yes":
                out[t] = yb if yb is not None else (ask if ask is not None else p["avg_price"])
            else:  # mark NO at best NO bid = 1 - best YES bid
                out[t] = (round(1.0 - yb, 4) if yb is not None else (ask if ask is not None else p["avg_price"]))
        return out

    # ------------------------------------------------------------ execution
    def open_position(
        self,
        ticker: str,
        side: str,
        price: float,
        strategy: str,
        signal: str,
        topic: Optional[str],
        fee_mult: float = 1.0,
        reason: str = "",
    ) -> Optional[Dict]:
        if ticker in self.positions or len(self.positions) >= MAX_OPEN:
            return None
        if self.blocked_today:
            return None
        budget = min(PER_POSITION_USD, self.cash)
        contracts = math.floor(budget / price) if price > 0 else 0
        if contracts < 1:
            return None
        cost = round(contracts * price, 2)
        fee = round(fee_taker(contracts, price, fee_mult), 2)
        if cost + fee > self.cash:
            contracts -= 1
            cost = round(contracts * price, 2)
            fee = round(fee_taker(contracts, price, fee_mult), 2)
        if contracts < 1 or cost + fee > self.cash:
            return None
        self.cash = round(self.cash - cost - fee, 2)
        self.fees_paid = round(self.fees_paid + fee, 2)
        pos = {
            "ticker": ticker,
            "side": side,
            "contracts": contracts,
            "avg_price": price,
            "strategy": strategy,
            "signal": signal,
            "topic": topic,
            "opened_at": now_iso(),
            "open_periods": 0,
            "entry_fee": fee,
            "entry_cost": cost,
            "reason": reason,
            "status": "open",
        }
        self.positions[ticker] = pos
        self._log_trade(pos, "open", price, 0.0, fee)
        return pos

    def close_position(self, ticker: str, price: float, why: str, settlement: Optional[str] = None) -> Optional[Dict]:
        pos = self.positions.pop(ticker, None)
        if not pos:
            return None
        contracts, avg = pos["contracts"], pos["avg_price"]
        if settlement is not None:
            # settlement payout: $1 per contract if this side won, else $0
            win = (settlement == pos["side"])
            proceeds = float(contracts) * (1.0 if win else 0.0)
            exit_price = 1.0 if win else 0.0
            fee = 0.0  # no settlement fee (official schedule)
            gross = proceeds - contracts * avg
        else:
            exit_price = price
            proceeds = round(contracts * price, 2)
            fee = round(fee_taker(contracts, price), 2)  # closing crosses the book -> taker
            gross = round(proceeds - contracts * avg - fee, 2)
        net = round(gross if settlement is not None else gross, 2)
        self.cash = round(self.cash + proceeds - fee, 2)
        self.fees_paid = round(self.fees_paid + fee, 2)
        self.realized_pnl = round(self.realized_pnl + net, 2)
        self.day_realized = round(self.day_realized + net, 2)
        pos.update(
            {
                "status": "closed",
                "closed_at": now_iso(),
                "exit_price": exit_price,
                "exit_fee": fee,
                "pnl": net,
                "exit_reason": why,
                "settlement": settlement,
            }
        )
        self._log_trade(pos, "close", exit_price, net, fee)
        if self.day_realized <= -DAILY_LOSS_CAP:
            self.blocked_today = True
        return pos

    def _log_trade(self, pos: Dict, action: str, price: float, pnl: float, fee: float) -> None:
        self.trades.append(
            {
                "ts": now_iso(),
                "action": action,
                "ticker": pos["ticker"],
                "topic": pos.get("topic"),
                "side": pos["side"],
                "contracts": pos["contracts"],
                "price": price,
                "fee": fee,
                "pnl": pnl,
                "strategy": pos.get("strategy"),
                "signal": pos.get("signal"),
                "trade_type": f"{pos.get('strategy')}|{pos.get('signal')}|{pos['side']}",
                "reason": pos.get("reason", ""),
                "exit_reason": pos.get("exit_reason") if action == "close" else None,
                "settlement": pos.get("settlement") if action == "close" else None,
                "source_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{pos['ticker']}",
                "fee_schedule_url": FEE_SCHEDULE_URL,
            }
        )
        if len(self.trades) > 4000:
            self.trades = self.trades[-4000:]

    # -------------------------------------------------------------- signals
    def signals(self, markets: List[Dict], books: Dict[str, Dict], alerts: List[Dict]) -> List[Dict]:
        """Produce candidate entries from alerts + book state. Pure, no side effects."""
        out: List[Dict] = []
        by_ticker = {m.get("ticker"): m for m in markets}
        recent = {a.get("ticker"): a for a in alerts[:40]}

        for ticker, alert in recent.items():
            m = by_ticker.get(ticker)
            if not m or m.get("status") != "open":
                continue
            book = books.get(ticker) or {}
            yb, ask, spread = implied_prices(book)
            if ask is None or yb is None or spread is None or spread > SPREAD_MAX:
                continue
            delta = float(alert.get("delta") or 0.0)
            if abs(delta) < 0.10:
                continue
            topic = m.get("topic")
            fee_mult = float(m.get("fee_multiplier") or 1.0)
            up = delta > 0
            swing = abs(delta)

            # momentum: continue with the move
            out.append(
                {
                    "ticker": ticker,
                    "topic": topic,
                    "strategy": "swing_momentum",
                    "signal": "swing-up" if up else "swing-down",
                    "side": "yes" if up else "no",
                    "price": ask if up else round(1.0 - yb, 4),
                    "fee_mult": fee_mult,
                    "reason": f"momentum: {alert.get('window')} move {delta:+.2f} (>=0.10 rule)",
                    "score": None,
                }
            )
            # reversal: fade the move
            rev_price = round(1.0 - yb, 4) if up else ask
            out.append(
                {
                    "ticker": ticker,
                    "topic": topic,
                    "strategy": "swing_reversal",
                    "signal": "fade-up" if up else "fade-down",
                    "side": "no" if up else "yes",
                    "price": rev_price,
                    "fee_mult": fee_mult,
                    "reason": f"reversal: fade {delta:+.2f} swing, assumed revert {REVERSION_SHARE:.0%}",
                    "score": None,
                }
            )
            # high-ROI model: only clear, fee-aware opportunities
            fee_c = fee_taker(1, rev_price if not up else ask, fee_mult)
            score = round(REVERSION_SHARE * swing - fee_c - spread, 4)
            if score >= ROI_MIN and spread <= SPREAD_MAX:
                out.append(
                    {
                        "ticker": ticker,
                        "topic": topic,
                        "strategy": "roi_edge",
                        "signal": "high-roi-fade",
                        "side": "no" if up else "yes",
                        "price": rev_price,
                        "fee_mult": fee_mult,
                        "reason": f"high-ROI: net edge {score:+.3f} >= {ROI_MIN} (revert {REVERSION_SHARE:.0%}x{swing:.2f} - fee {fee_c:.3f} - spread {spread:.3f})",
                        "score": score,
                    }
                )

        # book-imbalance entries on fresh books (opportunistic, no swing needed)
        for ticker, book in books.items():
            if ticker in self.positions or len(out) >= 40:
                continue
            m = by_ticker.get(ticker)
            if not m or m.get("status") != "open":
                continue
            edge = book_edge(book)
            yb, ask, spread = implied_prices(book)
            if edge is None or ask is None or yb is None or spread is None or spread > SPREAD_MAX:
                continue
            if ask >= 0.95 or yb <= 0.05:
                continue  # skip near-resolved contracts, room to move is gone
            # fair vs ask: buy YES when ask is below depth-implied fair, else buy NO
            if edge - ask >= 0.05:
                side, price, sig = "yes", ask, "book-undervalued-yes"
            elif (1 - edge) - (1 - yb) >= 0.05:
                side, price, sig = "no", round(1.0 - yb, 4), "book-undervalued-no"
            else:
                continue
            fee_c = fee_taker(1, price)
            score = round(abs(edge - price) - fee_c - spread, 4)
            if score < ROI_MIN:
                continue
            out.append(
                {
                    "ticker": ticker,
                    "topic": m.get("topic"),
                    "strategy": "roi_edge",
                    "signal": sig,
                    "side": side,
                    "price": price,
                    "fee_mult": float(m.get("fee_multiplier") or 1.0),
                    "reason": f"book edge fair={edge:.3f} vs price={price:.3f} spread={spread:.3f} net={score:+.3f}",
                    "score": score,
                }
            )
        out.sort(key=lambda s: (s.get("score") is not None, s.get("score") or 0), reverse=True)
        return out

    def step(
        self,
        markets: List[Dict],
        books: Dict[str, Dict],
        alerts: List[Dict],
        resolutions: List[Dict],
    ) -> Dict[str, Any]:
        # 1) settle anything that resolved
        res_by_ticker = {r.get("ticker"): r for r in resolutions}
        for ticker in list(self.positions):
            r = res_by_ticker.get(ticker)
            if r and r.get("result") in ("yes", "no"):
                self.close_position(ticker, price=0.0, why="settlement", settlement=r["result"])

        # 2) manage open positions against current marks
        marks = self.mark_prices(books)
        for ticker in list(self.positions):
            pos = self.positions[ticker]
            mark = marks.get(ticker)
            if mark is None:
                continue
            pos["open_periods"] += 1
            drift = round(mark - pos["avg_price"], 4) * (1 if pos["side"] == "yes" else -1)
            if pos["strategy"] == "swing_momentum":
                if drift <= -EXIT_STOP:
                    self.close_position(ticker, mark, "momentum-stop")
                elif pos["open_periods"] >= MOMENTUM_STALLS and drift < 0.01:
                    self.close_position(ticker, mark, "momentum-stall")
                elif drift >= EXIT_TARGET:
                    self.close_position(ticker, mark, "momentum-target")
                elif pos["open_periods"] >= MAX_HOLD_PERIODS:
                    self.close_position(ticker, mark, "max-hold")
            else:  # reversal / roi_edge
                if drift >= EXIT_TARGET:
                    self.close_position(ticker, mark, "target")
                elif drift <= -EXIT_STOP:
                    self.close_position(ticker, mark, "stop")
                elif pos["open_periods"] >= MAX_HOLD_PERIODS:
                    self.close_position(ticker, mark, "max-hold")

        # 3) take new signals
        opened = []
        for sig in self.signals(markets, books, alerts):
            pos = self.open_position(
                sig["ticker"], sig["side"], sig["price"], sig["strategy"], sig["signal"],
                sig["topic"], sig["fee_mult"], sig["reason"],
            )
            if pos:
                opened.append({"ticker": pos["ticker"], "strategy": pos["strategy"], "signal": pos["signal"]})
            if len(self.positions) >= MAX_OPEN:
                break

        equity = self.equity(marks)
        self.equity_curve.append({"ts": now_iso(), "equity": equity, "cash": self.cash})
        self.equity_curve = self.equity_curve[-900:]
        return {"opened": opened, "equity": equity, "marks": marks}


def stats(trades: List[Dict]) -> Dict[str, Any]:
    """Aggregate closed trades by strategy and by trade type (the 'categorize' ask)."""
    closes = [t for t in trades if t.get("action") == "close"]

    def agg(rows: List[Dict]) -> Dict[str, Any]:
        wins = [r for r in rows if (r.get("pnl") or 0) > 0]
        losses = [r for r in rows if (r.get("pnl") or 0) < 0]
        fees = sum(float(r.get("fee") or 0) for r in rows)
        pnl = sum(float(r.get("pnl") or 0) for r in rows)
        return {
            "trades": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(rows), 3) if rows else None,
            "net_pnl": round(pnl, 2),
            "avg_pnl": round(pnl / len(rows), 2) if rows else None,
            "fees": round(fees, 2),
        }

    by_strategy: Dict[str, List[Dict]] = {}
    by_type: Dict[str, List[Dict]] = {}
    for r in closes:
        by_strategy.setdefault(str(r.get("strategy")), []).append(r)
        by_type.setdefault(str(r.get("trade_type")), []).append(r)
    return {
        "by_strategy": {k: agg(v) for k, v in sorted(by_strategy.items())},
        "by_trade_type": {k: agg(v) for k, v in sorted(by_type.items())},
        "all": agg(closes),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Simulated trading engine (paper only)")
    ap.add_argument("--reset", action="store_true", help="start a fresh simulated account")
    args = ap.parse_args(argv)

    markets = (load("markets.json") or {}).get("rows") or []
    books = (load("orderbooks.json") or {}).get("books") or {}
    alerts = (load("alerts.json") or {}).get("alerts") or []
    resolutions = (load("resolutions.json") or {}).get("rows") or []

    state = None if args.reset else load("portfolio.json")
    eng = Engine(state)
    result = eng.step(markets, books, alerts, resolutions)

    payload = {
        "generated_at": now_iso(),
        "mode": "simulated-paper",
        "credentials": "none — no orders are sent (FL-01); all fills are simulated against real demo order books",
        "account": {
            "starting_cash": START_CASH,
            "cash": eng.cash,
            "equity": result["equity"],
            "realized_pnl": eng.realized_pnl,
            "fees_paid": eng.fees_paid,
            "open_positions": len(eng.positions),
            "daily_loss_cap": DAILY_LOSS_CAP,
            "blocked_today": eng.blocked_today,
        },
        "parameters": {
            "max_open": MAX_OPEN,
            "per_position_usd": PER_POSITION_USD,
            "exit_target": EXIT_TARGET,
            "exit_stop": EXIT_STOP,
            "reversion_share": REVERSION_SHARE,
            "roi_min": ROI_MIN,
            "spread_max": SPREAD_MAX,
            "fee_formula": "round_up(C*P + M*0.07*C*P*(1-P)) - C*P (taker)",
            "fee_schedule_url": FEE_SCHEDULE_URL,
        },
        "positions": list(eng.positions.values()),
        "trades": eng.trades[-300:],
        "stats": stats(eng.trades),
        "equity_curve": eng.equity_curve,
        "this_run": result,
        "source_urls": {
            "orderbooks": "https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}/orderbook",
            "markets": "https://external-api.demo.kalshi.co/trade-api/v2/markets",
            "fees": FEE_SCHEDULE_URL,
        },
    }
    save("portfolio.json", payload)
    print(json.dumps({"equity": result["equity"], "cash": eng.cash, "open": len(eng.positions),
                      "opened": len(result["opened"]), "closed_total": payload["stats"]["all"]["trades"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
