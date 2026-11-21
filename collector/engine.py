"""Simulated trading engine: strategies, portfolio, and performance analytics.

This is a PAPER-TRADING simulator. It matches modelled intent against real
observed Kalshi demo prices and records what would have happened. It never
claims a fill happened on the exchange.

Why simulated rather than live:
  the repository has no Kalshi demo API credentials configured
  (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH). Authenticated order entry
  cannot be exercised without them. ``LiveDemoBroker`` below is a complete,
  documented adapter that activates automatically when those variables exist,
  and is exercised in tests against a local mock. See VERIFICATION.md.

Fee model: Kalshi's published taker fee, quadratic 0.07 * M * C * P * (1-P),
rounded up to the cent, from https://kalshi.com/docs/kalshi-fee-schedule.pdf
(as referenced by fee_type in https://docs.kalshi.com/api-reference/market/get-series-list.md).
``M`` is not assumed here: it is read from the market's own series row
(``fee_multiplier`` / ``fee_type``, both required fields of ``Series``) through
``alerts.fee_params``, so a fee-free series is charged 0 and a combo series is
charged its own multiplier. The schedule and the live demo API disagree for
some series — the PDF lists KXBTCY at maker 0 / taker 0 while
``GET https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY`` returns
``fee_multiplier: 1`` (checked 2026-11-20; the PDF is "last updated and
effective: July 7, 2026" and defers to https://kalshi.com/fee-schedule for later
changes). This ledger follows the API field, because it is the value Kalshi's
own matching engine reports for the environment being simulated, and publishes
the basis on every row. Positions opened before the field existed stay charged
at M=1, which is what they were actually charged — no historical P&L is
restated.
Settlement: YES pays $1 per contract if result == "yes", NO pays $1 if
"no", per https://docs.kalshi.com/getting_started/market_settlement.md, and the
schedule charges no settlement fee, so ``settle()`` charges none either.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any

from .alerts import Signal
from .kalshi_api import Credentials, KalshiClient, kalshi_fee

STARTING_BANKROLL = 10_000.00
MAX_POSITION_PCT = 0.02        # never risk >2% of bankroll on one idea
MAX_POSITIONS = 40
MIN_CONFIDENCE = 0.55          # strategy gate, see STRATEGIES below

# Exit rules applied to open positions on every run.
#  - take profit: a swing of >= this much in our favour is banked rather than
#    held to expiry, because the brief asks for strategies that react to swings.
#  - stop: a swing of >= this much against us liquidates the idea.
TAKE_PROFIT_SWING = 0.10
STOP_SWING = 0.10

STRATEGIES: dict[str, dict[str, Any]] = {
    "momentum": {
        "label": "Momentum follow",
        "description": ("Enter in the direction of a >= $0.10 swing when the "
                        "post-swing price still leaves >= 2 cents of modelled "
                        "edge after fees. Holds to settlement."),
        "category": "swing",
    },
    "mean-reversion": {
        "label": "Mean reversion",
        "description": ("Take the opposite side of a swing when the model's "
                        "shrunk fair value crosses back through 0.50."),
        "category": "swing",
    },
    "value": {
        "label": "Quiet value",
        "description": ("No swing needed. Buy the side with the largest "
                        "modelled edge after fees whenever the spread is tight "
                        "and there is real book depth."),
        "category": "edge",
    },
    "resolution-hold": {
        "label": "Resolution hold",
        "description": ("Buy the side already trading above 0.85 with a tight "
                        "spread, betting on a clean yes/no resolution. Small "
                        "payout, frequent wins, occasional total loss."),
        "category": "carry",
    },
}


@dataclass
class Position:
    position_id: str
    ticker: str
    event_ticker: str
    topic: str
    title: str
    strategy: str
    side: str
    contracts: float
    entry_price: float
    entry_ts: float
    entry_fee: float
    current_price: float = 0.0
    unrealized: float = 0.0
    status: str = "open"          # open | settled | stopped
    exit_price: float | None = None
    exit_ts: float | None = None
    exit_fee: float = 0.0
    realized: float = 0.0
    result: str = ""
    reason: str = ""
    market_url: str = ""
    bankroll_at_entry: float = 0.0
    # The fee parameters this position was charged under, carried from the signal
    # so an exit (possibly in a later run) uses the same official multiplier as
    # the entry instead of an assumed one. 1.0 is also the default for positions
    # written before this field existed, which is correct: every one of them was
    # charged M=1, so no historical P&L is restated by this field appearing.
    fee_multiplier: float = 1.0
    fee_basis: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Trade:
    trade_id: str
    ts: float
    ticker: str
    strategy: str
    side: str
    contracts: float
    price: float
    fee: float
    action: str                   # open | close | settle
    realized: float = 0.0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Portfolio:
    """Ledger with mark-to-market, settlement handling and analytics."""

    def __init__(self, state: dict[str, Any] | None = None):
        state = state or {}
        self.bankroll = float(state.get("bankroll", STARTING_BANKROLL))
        self.starting_bankroll = float(state.get("starting_bankroll", STARTING_BANKROLL))
        self.positions: dict[str, Position] = {
            p["position_id"]: Position(**p) for p in state.get("positions", [])
        }
        self.trades: list[Trade] = [Trade(**t) for t in state.get("trades", [])]
        self.equity_curve: list[dict[str, float]] = state.get("equity_curve", [])
        self.started_at = float(state.get("started_at", time.time()))
        self.open_tickers: set[str] = {p.ticker for p in self.positions.values()
                                       if p.status == "open"}

    # -- persistence ------------------------------------------------------
    def to_state(self) -> dict[str, Any]:
        return {
            "bankroll": round(self.bankroll, 2),
            "starting_bankroll": round(self.starting_bankroll, 2),
            "positions": [p.as_dict() for p in self.positions.values()],
            "trades": [t.as_dict() for t in self.trades][-5000:],
            "equity_curve": self.equity_curve[-5000:],
            "started_at": self.started_at,
        }

    # -- accounting -------------------------------------------------------
    @property
    def realized_pnl(self) -> float:
        return round(sum(p.realized for p in self.positions.values()
                         if p.status in ("settled", "stopped")), 2)

    @property
    def fees_paid(self) -> float:
        return round(sum(p.entry_fee + p.exit_fee for p in self.positions.values()), 2)

    @property
    def open_exposure(self) -> float:
        return round(sum(p.contracts * p.entry_price for p in self.positions.values()
                         if p.status == "open"), 2)

    @property
    def unrealized_pnl(self) -> float:
        return round(sum(p.unrealized for p in self.positions.values()
                         if p.status == "open"), 2)

    @property
    def equity(self) -> float:
        open_value = sum(p.contracts * p.current_price
                         for p in self.positions.values() if p.status == "open")
        return round(self.bankroll + open_value, 2)

    def size_for(self, price: float) -> float:
        budget = min(self.bankroll * MAX_POSITION_PCT, self.bankroll * 0.5)
        if price <= 0:
            return 0.0
        return round(max(0.0, budget / price), 2)

    # -- trading ----------------------------------------------------------
    def can_open(self, ticker: str, price: float) -> bool:
        if ticker in self.open_tickers:
            return False
        if len([p for p in self.positions.values() if p.status == "open"]) >= MAX_POSITIONS:
            return False
        return self.bankroll > 5.0 and 0.01 <= price <= 0.99

    def open(self, signal: Signal, strategy: str, reason: str = "") -> Position | None:
        if not self.can_open(signal.ticker, signal.executable_price):
            return None
        contracts = self.size_for(signal.executable_price)
        if contracts < 1:
            return None
        cost = round(contracts * signal.executable_price, 4)
        # Same official multiplier the signal was screened with (GET /series
        # fee_multiplier / fee_type — see alerts.fee_params). Falls back to the
        # schedule's default M=1 for a signal that carries no fee basis, which
        # is exactly what every earlier trade in this ledger used.
        fee_mult = getattr(signal, "fee_multiplier", None)
        fee_mult = 1.0 if fee_mult is None else float(fee_mult)
        fee = kalshi_fee(signal.executable_price, contracts, fee_mult)
        if cost + fee > self.bankroll:
            return None
        self.bankroll = round(self.bankroll - cost - fee, 4)
        pos = Position(
            position_id=f"pos-{uuid.uuid4().hex[:10]}",
            ticker=signal.ticker, event_ticker=signal.event_ticker,
            topic=signal.topic, title=signal.title, strategy=strategy,
            side=signal.side, contracts=contracts,
            entry_price=signal.executable_price, entry_ts=signal.ts,
            entry_fee=fee, current_price=signal.executable_price,
            reason=reason or signal.reason, market_url=signal.market_url,
            bankroll_at_entry=self.bankroll,
            fee_multiplier=fee_mult,
            fee_basis=getattr(signal, "fee_basis", "") or "",
        )
        self.positions[pos.position_id] = pos
        self.open_tickers.add(pos.ticker)
        self.trades.append(Trade(
            trade_id=f"tr-{uuid.uuid4().hex[:10]}", ts=signal.ts,
            ticker=signal.ticker, strategy=strategy, side=signal.side,
            contracts=contracts, price=signal.executable_price, fee=fee,
            action="open", note=pos.reason[:300],
        ))
        return pos

    def mark(self, ticker: str, price: float | None) -> None:
        """Mark an open position to market.

        ``price`` is the YES mid. ``current_price`` always stores the value of
        the side we actually hold (YES mid for a YES position, ``1 - YES mid``
        for a NO position) so that ``equity`` and ``unrealized`` agree.
        """
        if price is None:
            return
        for pos in self.positions.values():
            if pos.status == "open" and pos.ticker == ticker:
                # Value of one contract of the held side.
                held = price if pos.side == "yes" else round(1.0 - price, 4)
                pos.current_price = held
                pos.unrealized = round((held - pos.entry_price) * pos.contracts, 4)

    def close(self, ticker: str, side_price: float, ts: float | None = None,
              reason: str = "") -> Position | None:
        """Exit a position at an observed price (selling the held side).

        ``side_price`` is the price of the *held side*: for a YES position that
        is the YES bid (what a seller actually receives), for a NO position it
        is 1 - YES ask. Fees follow the same published taker formula.
        """
        for pos in self.positions.values():
            if pos.status == "open" and pos.ticker == ticker:
                if not (0.0 < side_price < 1.0):
                    return None
                proceeds = round(pos.contracts * side_price, 4)
                pos_mult = getattr(pos, "fee_multiplier", None)
                fee = kalshi_fee(side_price, pos.contracts,
                                 1.0 if pos_mult is None else float(pos_mult))
                self.bankroll = round(self.bankroll + proceeds - fee, 4)
                pos.exit_price = side_price
                pos.exit_ts = ts or time.time()
                pos.exit_fee = fee
                pos.realized = round(proceeds - fee
                                     - pos.contracts * pos.entry_price
                                     - pos.entry_fee, 4)
                pos.status = "stopped"
                pos.current_price = side_price
                pos.unrealized = 0.0
                self.open_tickers.discard(pos.ticker)
                self.trades.append(Trade(
                    trade_id=f"tr-{uuid.uuid4().hex[:10]}", ts=pos.exit_ts,
                    ticker=pos.ticker, strategy=pos.strategy, side=pos.side,
                    contracts=pos.contracts, price=side_price, fee=fee,
                    action="close", realized=pos.realized,
                    note=reason or "exit on swing",
                ))
                return pos
        return None

    def settle(self, ticker: str, result: str, ts: float | None = None) -> Position | None:
        """Resolve a position using the market's official ``result`` field.

        result is "yes" or "no" from GET /markets (see
        https://docs.kalshi.com/getting_started/market_settlement.md).
        """
        if result not in ("yes", "no"):
            return None
        for pos in self.positions.values():
            if pos.status == "open" and pos.ticker == ticker:
                payout_per = 1.0 if pos.side == result else 0.0
                payout = round(pos.contracts * payout_per, 4)
                self.bankroll = round(self.bankroll + payout, 4)
                pos.exit_price = payout_per
                pos.exit_ts = ts or time.time()
                pos.realized = round(payout - pos.contracts * pos.entry_price
                                     - pos.entry_fee, 4)
                pos.status = "settled"
                pos.result = result
                pos.current_price = payout_per
                pos.unrealized = 0.0
                self.open_tickers.discard(pos.ticker)
                self.trades.append(Trade(
                    trade_id=f"tr-{uuid.uuid4().hex[:10]}", ts=pos.exit_ts,
                    ticker=pos.ticker, strategy=pos.strategy, side=pos.side,
                    contracts=pos.contracts, price=payout_per, fee=0.0,
                    action="settle", realized=pos.realized,
                    note=f"official result: {result}",
                ))
                return pos
        return None

    def snapshot_equity(self, ts: float | None = None) -> None:
        self.equity_curve.append({"ts": ts or time.time(), "equity": self.equity,
                                  "realized": self.realized_pnl,
                                  "open": self.open_exposure})

    # -- analytics --------------------------------------------------------
    def analytics(self) -> dict[str, Any]:
        # "settled" here means any position with a final outcome, whether it
        # resolved at expiry (status "settled") or was exited early ("stopped").
        settled = [p for p in self.positions.values() if p.status in ("settled", "stopped")]
        wins = [p for p in settled if p.realized > 0]
        losses = [p for p in settled if p.realized <= 0]

        def block(rows: list[Position]) -> dict[str, Any]:
            if not rows:
                return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None,
                        "realized": 0.0, "avg_win": None, "avg_loss": None,
                        "expectancy": None, "roi_on_cost": None, "fees": 0.0}
            cost = sum(r.contracts * r.entry_price for r in rows)
            realized = sum(r.realized for r in rows)
            w = [r.realized for r in rows if r.realized > 0]
            l = [r.realized for r in rows if r.realized <= 0]
            return {
                "trades": len(rows),
                "wins": len(w),
                "losses": len(l),
                "win_rate": round(len(w) / len(rows), 4),
                "realized": round(realized, 2),
                "avg_win": round(sum(w) / len(w), 2) if w else None,
                "avg_loss": round(sum(l) / len(l), 2) if l else None,
                "expectancy": round(realized / len(rows), 2),
                "roi_on_cost": round(realized / cost, 4) if cost else None,
                "fees": round(sum(r.entry_fee + r.exit_fee for r in rows), 2),
            }

        by_strategy = {s: block([p for p in settled if p.strategy == s])
                       for s in STRATEGIES}
        by_topic = {t: block([p for p in settled if p.topic == t])
                    for t in sorted({p.topic for p in settled})}
        by_category = {}
        for cat in sorted({STRATEGIES.get(s, {}).get("category", "other")
                           for s in STRATEGIES}):
            by_category[cat] = block([
                p for p in settled
                if STRATEGIES.get(p.strategy, {}).get("category", "other") == cat
            ])

        overall = block(settled)
        peak = 0.0
        max_dd = 0.0
        for point in self.equity_curve:
            eq = point.get("equity", self.starting_bankroll)
            peak = max(peak, eq)
            if peak:
                max_dd = max(max_dd, (peak - eq) / peak)

        return {
            "starting_bankroll": self.starting_bankroll,
            "equity": self.equity,
            "cash": round(self.bankroll, 2),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "fees_paid": self.fees_paid,
            "open_positions": len([p for p in self.positions.values()
                                   if p.status == "open"]),
            "open_exposure": self.open_exposure,
            "total_return": round((self.equity - self.starting_bankroll)
                                  / self.starting_bankroll, 4),
            "max_drawdown": round(max_dd, 4),
            "overall": overall,
            "by_strategy": by_strategy,
            "by_topic": by_topic,
            "by_category": by_category,
            "strategies": STRATEGIES,
            "settled_positions": [p.as_dict() for p in
                                  sorted(settled, key=lambda p: -(p.exit_ts or 0))[:200]],
            "open_positions_detail": [p.as_dict() for p in self.positions.values()
                                      if p.status == "open"],
            "trades": [t.as_dict() for t in self.trades[-200:]][::-1],
            "positions_count": len(self.positions),
            "wins": len(wins),
            "losses": len(losses),
            "mode": "simulated",
        }


# ---------------------------------------------------------------------------
# Strategy gate: which signals each strategy is allowed to trade.
# ---------------------------------------------------------------------------

def select_trades(signals: list[Signal], swings: list[dict[str, Any]],
                  portfolio: Portfolio) -> list[tuple[Signal, str, str]]:
    """Map scored signals + swing alerts onto strategy entries.

    Returns (signal, strategy, reason) triples. Every rule is readable in the
    code below and mirrored on the Methodology page.
    """
    if not signals:
        return []
    by_ticker = {s.ticker: s for s in signals}
    swing_dir = {}
    for alert in swings:
        swing_dir[alert["ticker"]] = alert["direction"]

    picks: list[tuple[Signal, str, str]] = []
    used: set[str] = set()

    ranked = sorted(signals, key=lambda s: s.score, reverse=True)

    # 1. Momentum: swing up and we can still buy YES with edge.
    for alert in sorted(swings, key=lambda a: -a["abs_delta"]):
        sig = by_ticker.get(alert["ticker"])
        if not sig or sig.ticker in used:
            continue
        if alert["direction"] == "up" and sig.side == "yes" and sig.net_roi >= 0.05:
            picks.append((sig, "momentum",
                          f"swing +${alert['abs_delta']:.2f} and modelled net ROI "
                          f"{sig.net_roi:.0%}"))
            used.add(sig.ticker)

    # 2. Mean reversion: swing down but the shrunk fair value is still above 0.5.
    for alert in sorted(swings, key=lambda a: -a["abs_delta"]):
        sig = by_ticker.get(alert["ticker"])
        if not sig or sig.ticker in used:
            continue
        if (alert["direction"] == "down" and sig.side == "yes"
                and sig.model_fair >= 0.50 and sig.net_roi >= 0.05):
            picks.append((sig, "mean-reversion",
                          f"swing -${alert['abs_delta']:.2f} while fair value "
                          f"({sig.model_fair:.2f}) stayed above 0.50"))
            used.add(sig.ticker)

    # 3. Quiet value: best net ROI regardless of a swing, tight spread required.
    for sig in ranked:
        if sig.ticker in used:
            continue
        if sig.net_roi >= 0.12 and (sig.spread is None or sig.spread <= 0.05):
            picks.append((sig, "value",
                          f"net ROI {sig.net_roi:.0%} on a "
                          f"{(sig.spread or 0):.2f} spread"))
            used.add(sig.ticker)
            break

    # 4. Resolution hold: near-certain side, small but frequent carry.
    for sig in ranked:
        if sig.ticker in used:
            continue
        favourable = (sig.side == "yes" and sig.executable_price >= 0.85) or \
                     (sig.side == "no" and sig.executable_price >= 0.85)
        if favourable and (sig.spread is None or sig.spread <= 0.04) and sig.liquidity >= 50:
            picks.append((sig, "resolution-hold",
                          f"{sig.side.upper()} at {sig.executable_price:.2f} with "
                          f"{sig.liquidity:.0f} contracts resting"))
            used.add(sig.ticker)
            break

    return picks


def exit_signals(portfolio: Portfolio, observations: dict[str, Any]) -> list[tuple[Position, float, str]]:
    """Decide which open positions to close on a >= $0.10 swing.

    ``observations`` maps ticker -> Observation for the current run. Only prices
    the trader could actually transact at are used: the YES bid to sell YES, and
    1 - YES ask to sell NO.
    """
    decisions: list[tuple[Position, float, str]] = []
    for pos in portfolio.positions.values():
        if pos.status != "open":
            continue
        obs = observations.get(pos.ticker)
        if obs is None or obs.mid is None:
            continue
        # Move of the held side since entry. ``obs.mid`` is the YES mid, so a NO
        # position's value is ``1 - mid``; comparing a NO entry price to the YES
        # mid directly would read a losing NO trade as a large favourable swing
        # and force it out at a loss.
        held_value = obs.mid if pos.side == "yes" else round(1.0 - obs.mid, 4)
        change = held_value - pos.entry_price
        # Price we would receive for the side we hold.
        if pos.side == "yes":
            exit_price = obs.yes_bid
        else:
            exit_price = (round(1.0 - obs.yes_ask, 4)
                          if obs.yes_ask is not None else None)
        if exit_price is None or not (0.0 < exit_price < 1.0):
            continue
        if change >= TAKE_PROFIT_SWING:
            decisions.append((pos, exit_price,
                              f"+${change:.2f} favourable swing — take profit"))
        elif change <= -STOP_SWING:
            decisions.append((pos, exit_price,
                              f"-${abs(change):.2f} adverse swing — stop out"))
    return decisions


# ---------------------------------------------------------------------------
# Live demo broker (used only when credentials exist)
# ---------------------------------------------------------------------------

class LiveDemoBroker:
    """Order entry against the Kalshi DEMO environment.

    Endpoint and payload shape are taken from
    https://docs.kalshi.com/getting_started/quick_start_create_order.md
    (POST /portfolio/events/orders with ticker, side, count, price,
    time_in_force, self_trade_prevention_type, client_order_id).

    It is inert unless credentials are configured; ``available`` reports that.
    """

    def __init__(self, client: KalshiClient | None = None):
        creds = Credentials.from_env()
        self.enabled = creds is not None
        self.client = client or KalshiClient(credentials=creds)

    def place(self, ticker: str, side: str, count: int, price: float,
              client_order_id: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError(
                "Live demo trading is not configured: set KALSHI_API_KEY_ID and "
                "KALSHI_PRIVATE_KEY_PATH. The simulator is running instead."
            )
        return self.client.create_order({
            "ticker": ticker,
            "side": "bid",
            "count": str(count),
            "price": f"{price:.4f}",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": client_order_id or str(uuid.uuid4()),
        })
