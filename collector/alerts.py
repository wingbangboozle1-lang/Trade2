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
# Swing alerts need a tight, two-sided quote. If the bid-ask spread is at least
# the swing threshold, the mid can move by $0.10 purely because the quotes moved,
# not because a trade happened. Design choice (not a Kalshi rule): require the
# spread to be strictly below the $0.10 threshold. Logged in VERIFICATION_856e184e.md.
ALERT_MAX_SPREAD = 0.10
SHRINK = 0.50            # how strongly a wide spread pulls the fair value to 0.5
MIN_EXECUTABLE_PRICE = 0.01   # $0.01 is the lowest valid quote on Kalshi's grid
MIN_DEPTH_CONTRACTS = 10.0    # a market with no resting size is not tradable
MIN_TOP_LEVEL_CONTRACTS = 1.0  # the best level must actually hold size


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
    notional: float | None = None      # notional_value_dollars per contract
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

    # Fall back to the market record's own quotes when the book is empty...
    if yes_ask is None:
        yes_ask = dollars(market.get("yes_ask_dollars"))
    if yes_bid is None:
        yes_bid = dollars(market.get("yes_bid_dollars"))
    if yes_bid is None and yes_bid_size is None:
        yes_bid_size = count(market.get("yes_bid_size_fp"))

    # ...but a market with no quotes at all reports 0.0000 bid / 1.0000 ask.
    # Averaging that pair produces a phantom 0.50 mid, which is how a golf
    # outlier with no book would appear to "jump" to exactly $0.50 and back.
    # A full 0-to-1 spread is not a price: treat it as no quote.
    if (yes_bid is not None and yes_ask is not None
            and yes_bid <= 0.0 and yes_ask >= 1.0):
        yes_bid, yes_ask = None, None

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
        notional=dollars(market.get("notional_value_dollars")),
        status=market.get("status", "active"),
        result=market.get("result", "") or "",
        series_ticker=market.get("series_ticker", "") or "",
        close_time=market.get("close_time", "") or "",
    )


def quoted_spread(yes_bid: float | None, yes_ask: float | None) -> float | None:
    """YES ask minus YES bid, or None when either side is not quoted."""
    if yes_bid is None or yes_ask is None:
        return None
    return round(yes_ask - yes_bid, 4)


def swing_quotes_ok(yes_bid: float | None, yes_ask: float | None) -> bool:
    """True only for a two-sided quote tighter than ALERT_MAX_SPREAD."""
    spread = quoted_spread(yes_bid, yes_ask)
    return spread is not None and 0.0 <= spread < ALERT_MAX_SPREAD


QUOTE_BASES = ("candle_quote_mid", "previous_snapshot_mid")


def alert_record_valid(alert: dict[str, Any]) -> bool:
    """Re-check a stored alert against the current quote rule.

    Used to purge alerts written before the quote rule existed. Such records
    have no ``reference_basis`` field, so their reference cannot be shown to be a
    quote mid, and they are dropped even when their current quote looks tight.
    Example: the 0.803 -> 0.0025 AKLO alert, whose reference was a trade print.
    """
    if alert.get("reference_basis") not in QUOTE_BASES:
        return False
    return swing_quotes_ok(alert.get("yes_bid"), alert.get("yes_ask"))


def detect_swing(previous: Observation | None, current: Observation,
                 threshold: float = SWING_THRESHOLD,
                 reference: float | None = None,
                 reference_ts: float | None = None,
                 reference_spread: float | None = None) -> dict[str, Any] | None:
    """Return an alert dict when the reference price moved by >= threshold.

    Price basis: both sides of the comparison are YES *mid* prices built from
    quotes (bid and ask). ``reference`` must therefore be the mid of the
    reference bar's quote closes, with ``reference_spread`` its ask-bid width.
    A last-trade price must never be compared with a quote mid. Both the current
    and the reference quotes must be two-sided and narrower than
    ALERT_MAX_SPREAD, otherwise no alert is raised.

    How the reference works, and why it is not simply "the previous snapshot":

    The collector samples roughly every 5-15 minutes while a market can move
    continuously. Comparing only against the immediately previous sample makes
    every alert fire once and then reset, so a market that drifts 20 cents over
    an hour in 4-cent steps never alerts. The caller therefore passes the price
    at the start of the current 5-minute bar, taken from Kalshi's own published
    candle quote closes (yes_bid / yes_ask), not the last-trade close. That reference is still a measured price, never an
    interpolation, and it is used whenever available; the previous snapshot is
    the fallback for markets without candle history.
    """
    if previous is None and reference is None:
        return None
    # The current observation must itself be a tight, two-sided quote.
    if not swing_quotes_ok(current.yes_bid, current.yes_ask):
        return None
    # Prefer the bar-opening reference: it spans the whole bar rather than a
    # single inter-snapshot hop, so a gradual move is measurable. Fall back to
    # the previous snapshot when no bar is available.
    basis = "candle_quote_mid"
    if reference is not None:
        if reference_spread is None or not (0.0 <= reference_spread < ALERT_MAX_SPREAD):
            return None
        base = reference
    elif previous is not None:
        if not swing_quotes_ok(previous.yes_bid, previous.yes_ask):
            return None
        base = previous.mid
        basis = "previous_snapshot_mid"
    else:
        base = None
    if base is None or current.mid is None:
        return None
    prev_ts = reference_ts if reference is not None else (
        previous.ts if previous is not None else None)
    delta = round(current.mid - base, 4)
    if abs(delta) + 1e-9 < threshold:
        return None
    direction = "up" if delta > 0 else "down"
    prev_mid = base
    return {
        "id": f"{current.ticker}:{int(current.ts)}",
        "ts": current.ts,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current.ts)),
        "ticker": current.ticker,
        "event_ticker": current.event_ticker,
        "series_ticker": current.series_ticker,
        "topic": current.topic,
        "title": current.title,
        "previous": prev_mid,
        "previous_ts": prev_ts,
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
        "observed_gap_seconds": round(
            current.ts - (prev_ts if prev_ts is not None else current.ts), 1),
        "reference_basis": basis,
        "spread": quoted_spread(current.yes_bid, current.yes_ask),
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

    # Tradability gates. Without resting size on both sides a quoted price is
    # an artifact: several Kalshi markets carry a 1-2 cent stale bid on
    # millions of open-interest contracts, which would otherwise look like an
    # infinite-ROI trade. These three checks keep such markets out of the model.
    depth_yes = liquidity.get("yes_bid_contracts") or 0.0
    depth_no = liquidity.get("no_bid_contracts") or 0.0
    if depth_yes + depth_no < MIN_DEPTH_CONTRACTS:
        return None
    top_yes = (liquidity.get("yes_bids") or [{}])[0].get("contracts") if liquidity.get("yes_bids") else 0.0
    top_no = (liquidity.get("no_bids") or [{}])[0].get("contracts") if liquidity.get("no_bids") else 0.0
    if max(top_yes or 0.0, top_no or 0.0) < MIN_TOP_LEVEL_CONTRACTS:
        return None

    mid = obs.mid
    if mid is None:
        return None
    width = spread if spread is not None else 0.02
    prior = 0.5
    weight = SHRINK * min(1.0, width / max_spread)
    fair = round(mid * (1 - weight) + prior * weight, 4)

    # Buy YES at the ask, or buy NO at (1 - yes bid). A crossed or zero quote
    # can never be filled, so anything off the tradable grid is dropped.
    candidates = []
    if obs.yes_ask is not None and MIN_EXECUTABLE_PRICE <= obs.yes_ask <= 1.0 - MIN_EXECUTABLE_PRICE:
        candidates.append(("yes", obs.yes_ask, fair))
    if obs.yes_bid is not None and MIN_EXECUTABLE_PRICE <= obs.yes_bid <= 1.0 - MIN_EXECUTABLE_PRICE:
        no_price = round(1.0 - obs.yes_bid, 4)
        if MIN_EXECUTABLE_PRICE <= no_price <= 1.0 - MIN_EXECUTABLE_PRICE:
            candidates.append(("no", no_price, round(1.0 - fair, 4)))

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
    """Order events by the dollar amount actually at stake.

    Primary measure: open-interest value = ``open_interest_fp`` x
    ``notional_value_dollars``. Both are documented GET /markets fields
    (https://docs.kalshi.com/api-reference/market/get-markets): notional value
    is "the total value of a single contract at settlement in dollars".
    Traded volume is reported separately in contracts and never multiplied by a
    price we invented, because the API does not publish a traded-dollar figure.
    """
    rows = []
    for obs in observations:
        oi = obs.open_interest or 0.0
        vol = obs.volume or 0.0
        notional = obs.notional if obs.notional is not None else 1.0
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
            "notional_per_contract": notional,
            "open_interest_notional": round(oi * notional, 2),
            "dollar_activity": round(oi * notional, 2),
            "status": obs.status,
            "result": obs.result,
            "close_time": obs.close_time,
            "market_url": obs.market_url,
        })
    return sorted(rows, key=lambda r: r["dollar_activity"], reverse=True)
