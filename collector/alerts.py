"""Swing detection and the "high ROI" model.

Definitions, stated explicitly so nothing is implied:

Swing
    A change of at least $0.10 in either direction between two consecutive
    observations of the same market's reference price. The reference price is
    the YES mid, computed from the order book per the official docs
    (https://docs.kalshi.com/getting_started/orderbook_responses.md):
        best YES bid = last element of orderbook_fp.yes_dollars
        best YES ask = 1.00 - (last element of orderbook_fp.no_dollars)
        mid = (bid + ask) / 2
    When only one side is quoted the quote is used on its own; when neither is
    quoted the observation is skipped, never treated as zero.

Threshold
    SWING_THRESHOLD = 0.10 USD, configurable, and reported in the UI.

ROI model ("what our model likes")
    This is a transparent, rule-based scorer — not a prediction and not a
    claim of profitability. For a candidate trade it estimates:

        edge      = model_fair - executable_price
        roi       = edge / executable_price
        fee       = Kalshi's published taker fee, quadratic 0.07 * C * P * (1-P)
        net_roi   = (edge - fee_per_contract) / executable_price

    ``model_fair`` is the reference mid, shrunk toward 0.5 by the observed
    spread: a wide spread means the mid is unreliable, so the model trusts it
    less. Everything is published on the Methodology page, and outcomes are
    scored honestly after the fact on the Portfolio page (win rate, realized
    ROI, fees paid), including losses.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from .kalshi_api import (best_bid, count, dollars, implied_yes_ask, mid_price,
                         kalshi_fee)

SWING_THRESHOLD = 0.10   # USD per contract, either direction (project brief)
MIN_EDGE = 0.02          # USD minimum modelled edge to call something "high ROI"
MAX_SPREAD = 0.20        # skip books wider than this: mid is not meaningful
SHRINK = 0.50            # how strongly a wide spread pulls the fair value to 0.5


@dataclass
class Observation:
    ts: float
    ticker: str
    event_ticker: str
    topic: str
    title: str
    yes_bid: float | None
    yes_ask: float | None
    mid: float | None
    last_price: float | None
    volume: float | None
    open_interest: float | None
    yes_bid_size: float | None = None
    no_bid: float | None = None
    status: str = "active"
    result: str = ""
    series_ticker: str = ""
    close_time: str = ""

    @property
    def market_url(self) -> str:
        return f"https://kalshi.com/markets/{self.series_ticker or self.event_ticker}/{self.ticker}"


def observe(market: dict[str, Any], orderbook: dict[str, Any] | None,
            topic: str, ts: float | None = None) -> Observation:
    """Build an Observation from GET /markets plus GET /markets/{t}/orderbook."""
    ob = (orderbook or {}).get("orderbook_fp") or {}
    yes_levels = ob.get("yes_dollars") or []
    no_levels = ob.get("no_dollars") or []

    yb = best_bid(yes_levels)
    nb = best_bid(no_levels)
    yes_bid = yb[0] if yb else None
    yes_bid_size = yb[1] if yb else None
    no_bid = nb[0] if nb else None
    yes_ask = implied_yes_ask(no_bid)

    # Fall back to the market record's own quotes when the book is empty.
    if yes_ask is None:
        yes_ask = dollars(market.get("yes_ask_dollars"))
    if yes_bid is None:
        yes_bid = dollars(market.get("yes_bid_dollars"))
    if yes_bid is None and yes_bid_size is None:
        yes_bid_size = count(market.get("yes_bid_size_fp"))

    return Observation(
        ts=ts if ts is not None else time.time(),
        ticker=market.get("ticker", ""),
        event_ticker=market.get("event_ticker", ""),
        topic=topic,
        title=(market.get("yes_sub_title") or market.get("title") or "").strip(),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        mid=mid_price(yes_bid, yes_ask),
        last_price=dollars(market.get("last_price_dollars")),
        volume=count(market.get("volume_fp")),
        open_interest=count(market.get("open_interest_fp")),
        yes_bid_size=yes_bid_size,
        no_bid=no_bid,
        status=market.get("status", "active"),
        result=market.get("result", "") or "",
        series_ticker=market.get("series_ticker", "") or "",
        close_time=market.get("close_time", "") or "",
    )


def detect_swing(previous: Observation | None, current: Observation,
                 threshold: float = SWING_THRESHOLD) -> dict[str, Any] | None:
    """Return an alert dict when the reference price moved by >= threshold."""
    if previous is None or previous.mid is None or current.mid is None:
        return None
    delta = round(current.mid - previous.mid, 4)
    if abs(delta) + 1e-9 < threshold:
        return None
    direction = "up" if delta > 0 else "down"
    return {
        "id": f"{current.ticker}:{int(current.ts)}",
        "ts": current.ts,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current.ts)),
        "ticker": current.ticker,
        "event_ticker": current.event_ticker,
        "series_ticker": current.series_ticker,
        "topic": current.topic,
        "title": current.title,
        "previous": previous.mid,
        "current": current.mid,
        "delta": delta,
        "abs_delta": abs(delta),
        "direction": direction,
        "pct_of_dollar": round(abs(delta) * 100, 2),  # cents of contract value
        "yes_bid": current.yes_bid,
        "yes_ask": current.yes_ask,
        "volume": current.volume,
        "open_interest": current.open_interest,
        "market_url": current.market_url,
        "threshold": threshold,
        "observed_gap_seconds": round(current.ts - previous.ts, 1),
    }


def _all_levels(rows: list[Any]) -> list[dict[str, float]]:
    """Every bid level, best price first (used for aggregate depth figures)."""
    out = []
    for row in list(rows)[::-1]:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price, size = dollars(row[0]), count(row[1])
        if price is None or size is None:
            continue
        out.append({"price": price, "contracts": size,
                    "dollars": round(price * size, 2)})
    return out


def analyse_liquidity(orderbook: dict[str, Any], levels: int = 8) -> dict[str, Any]:
    """Depth view: how many contracts rest at each price, and the cost to fill.

    Only bids are returned by Kalshi, so we report bid-side depth for YES and NO
    and derive the implied asks from the reciprocal relationship documented at
    https://docs.kalshi.com/getting_started/orderbook_responses.md
    """
    ob = (orderbook or {}).get("orderbook_fp") or {}
    yes_levels = list(ob.get("yes_dollars") or [])
    no_levels = list(ob.get("no_dollars") or [])

    def normalise(rows: list[Any]) -> list[dict[str, float]]:
        # ``levels`` caps how many price levels of *each* side we report, but the
        # aggregate depth figures below are computed from the complete book so
        # that "contracts available" is never understated.
        out = []
        for row in rows[-levels:][::-1]:  # best first
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price, size = dollars(row[0]), count(row[1])
            if price is None or size is None:
                continue
            out.append({"price": price, "contracts": size,
                        "dollars": round(price * size, 2)})
        return out

    yes_bids = normalise(yes_levels)
    no_bids = normalise(no_levels)
    all_yes = normalise(yes_levels) if len(yes_levels) <= levels else _all_levels(yes_levels)
    all_no = normalise(no_levels) if len(no_levels) <= levels else _all_levels(no_levels)
    best_yes = yes_bids[0]["price"] if yes_bids else None
    best_no = no_bids[0]["price"] if no_bids else None
    yes_ask = implied_yes_ask(best_no)
    spread = (round(yes_ask - best_yes, 4)
              if yes_ask is not None and best_yes is not None else None)

    def cumulative(side: list[dict[str, float]]) -> list[dict[str, float]]:
        total = 0.0
        out = []
        for row in side:
            total += row["contracts"]
            out.append({**row, "cum_contracts": round(total, 2)})
        return out

    return {
        "yes_bids": cumulative(yes_bids),
        "no_bids": cumulative(no_bids),
        "best_yes_bid": best_yes,
        "best_yes_ask": yes_ask,
        "best_no_bid": best_no,
        "best_no_ask": (round(1.0 - best_yes, 4) if best_yes is not None else None),
        "spread": spread,
        "yes_bid_contracts": round(sum(r["contracts"] for r in all_yes), 2),
        "no_bid_contracts": round(sum(r["contracts"] for r in all_no), 2),
        "yes_bid_dollars": round(sum(r["dollars"] for r in all_yes), 2),
        "no_bid_dollars": round(sum(r["dollars"] for r in all_no), 2),
        "levels_reported": levels,
    }


@dataclass
class Signal:
    ticker: str
    event_ticker: str
    topic: str
    title: str
    side: str                  # "yes" or "no"
    executable_price: float    # price actually paid if we cross the spread now
    model_fair: float
    edge: float
    gross_roi: float
    fee: float
    net_roi: float
    spread: float | None
    liquidity: float
    score: float
    reason: str
    market_url: str
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_market(obs: Observation, liquidity: dict[str, Any],
                 min_edge: float = MIN_EDGE,
                 max_spread: float = MAX_SPREAD) -> Signal | None:
    """Score one side of a binary market on modelled edge after fees.

    Long-shot bias is handled by the shrink term: the further the mid is from
    0.5 and the wider the spread, the closer the fair value is pulled back to
    0.5. This deliberately makes the model conservative on cheap contracts,
    which is where raw ROI numbers look most spectacular and are least real.
    """
    if obs.yes_bid is None and obs.yes_ask is None:
        return None
    spread = liquidity.get("spread")
    if spread is not None and spread > max_spread:
        return None

    mid = obs.mid
    if mid is None:
        return None
    width = spread if spread is not None else 0.02
    prior = 0.5
    weight = SHRINK * min(1.0, width / max_spread)
    fair = round(mid * (1 - weight) + prior * weight, 4)

    # Buy YES at the ask, or buy NO at (1 - yes bid).
    candidates = []
    if obs.yes_ask is not None and 0.0 < obs.yes_ask < 1.0:
        candidates.append(("yes", obs.yes_ask, fair))
    if obs.yes_bid is not None and 0.0 < obs.yes_bid < 1.0:
        candidates.append(("no", round(1.0 - obs.yes_bid, 4),
                           round(1.0 - fair, 4)))

    best: Signal | None = None
    for side, price, fair_side in candidates:
        edge = round(fair_side - price, 4)
        if edge < min_edge:
            continue
        fee = kalshi_fee(price, 1.0)
        gross = edge / price if price > 0 else 0.0
        net = (edge - fee) / price if price > 0 else 0.0
        if net <= 0:
            continue
        depth = (liquidity.get("yes_bid_contracts" if side == "yes" else "no_bid_contracts")
                 or 0.0)
        # Score: net ROI scaled by how much size the book can absorb.
        size_factor = min(1.0, math.log10(1 + depth) / 3.0)
        score = round(net * (0.5 + 0.5 * size_factor), 4)
        signal = Signal(
            ticker=obs.ticker, event_ticker=obs.event_ticker, topic=obs.topic,
            title=obs.title, side=side, executable_price=price,
            model_fair=fair_side, edge=edge, gross_roi=round(gross, 4), fee=fee,
            net_roi=round(net, 4), spread=spread, liquidity=depth,
            score=score,
            reason=(f"mid {mid:.2f} shrunk to fair {fair:.2f} on a {width:.2f} "
                    f"spread; buying {side.upper()} at {price:.2f} leaves "
                    f"{edge:.2f} of modelled edge after the "
                    f"${fee:.4f} taker fee"),
            market_url=obs.market_url,
        )
        if best is None or signal.score > best.score:
            best = signal
    return best


def rank_events(observations: Iterable[Observation]) -> list[dict[str, Any]]:
    """Order events by the dollar value actually trading on them.

    "Highest dollar amount" is measured as open interest notional
    (open_interest * $1 notional per contract, which is the documented
    ``notional_value_dollars``) plus traded volume notional. Both fields come
    straight from GET /markets; nothing is estimated.
    """
    rows = []
    for obs in observations:
        oi = obs.open_interest or 0.0
        vol = obs.volume or 0.0
        rows.append({
            "ticker": obs.ticker,
            "event_ticker": obs.event_ticker,
            "series_ticker": obs.series_ticker,
            "topic": obs.topic,
            "title": obs.title,
            "mid": obs.mid,
            "yes_bid": obs.yes_bid,
            "yes_ask": obs.yes_ask,
            "volume_contracts": vol,
            "open_interest_contracts": oi,
            "open_interest_notional": round(oi * 1.0, 2),
            "volume_notional": round(vol * 1.0, 2),
            "dollar_activity": round(vol + oi, 2),
            "status": obs.status,
            "result": obs.result,
            "close_time": obs.close_time,
            "market_url": obs.market_url,
        })
    return sorted(rows, key=lambda r: r["dollar_activity"], reverse=True)
