"""Swing detection and the "high ROI" model.

Definitions, stated explicitly so nothing is implied:

Swing
    A change of at least $0.10 in either direction in the same measured price
    of the same market. The price is the YES mid, computed from the order book
    exactly as the official docs define it
    (https://docs.kalshi.com/getting_started/orderbook_responses):
        best YES bid = last element of orderbook_fp.yes_dollars
        best YES ask = 1.00 - (best NO bid, i.e. last of orderbook_fp.no_dollars)
        mid = (bid + ask) / 2
    Both legs are required. A one-sided book has no mid — it has a bid and no
    offer — so it is never given a synthetic price and never alerts. The rule
    used to fall back to the market record's `last_price_dollars` for the
    reference, which meant a last *trade* (Hunter Biden: $0.811 on a book
    quoted 0.0020 / 0.8110) was subtracted from an order-book *mid* ($0.4065)
    and published as a 40-cent "swing". That is a comparison of two different
    quantities and is no longer made: the reference and the current value now
    come from the same source, and `detect_swing` rejects any alert whose
    reference is not a two-sided mid.

Threshold
    SWING_THRESHOLD = 0.10 USD, applied literally and reported in the UI, so a
    row can always be checked against the requirement that produced it. What is
    gated is dealability, not magnitude: both quotes must be two-sided and the
    spread must be strictly below $0.10 (ALERT_MAX_SPREAD). A book wider than
    the threshold cannot have its mid moved by $0.10 of trading; the mid only
    moves because one side was pulled, which is a quote artefact and not a price
    move a trader can act on. The gate is a documented design choice, and it is
    stated on the Methodology page rather than hidden in code.

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
# the swing threshold, the mid can move by $0.10 purely because one side of the
# book was pulled, not because a trade happened. Design choice (not a Kalshi
# rule): require the spread to be strictly below the $0.10 threshold.
# Logged in VERIFICATION_856e184e.md and stated on the Methodology page.
ALERT_MAX_SPREAD = 0.10
SHRINK = 0.50            # how strongly a wide spread pulls the fair value to 0.5
MIN_EXECUTABLE_PRICE = 0.01   # $0.01 is the lowest valid quote on Kalshi's grid
MIN_DEPTH_CONTRACTS = 10.0    # a market with no resting size is not tradable
MIN_TOP_LEVEL_CONTRACTS = 1.0  # the best level must actually hold size

# De-duplication: one alert per market per reference bar per direction. The id
# is built from these parts, so a re-run inside the same bar cannot append the
# same move twice to the chat buffer.
ALERT_DEDUP_SECONDS = 300


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
    no_bid_size: float | None = None   # contracts resting at the best NO bid
    quote_source: str = ""             # "book" (two-sided) or "unquoted"
    spread: float | None = None

    @property
    def market_url(self) -> str:
        return f"https://kalshi.com/markets/{self.series_ticker or self.event_ticker}/{self.ticker}"

    @property
    def alertable(self) -> bool:
        """True only when this observation supports a measured price move.

        Requires a mid built from two resting bids (see ``observe``) and a
        spread narrow enough that the mid is a price rather than the midpoint of
        an empty range.
        """
        return (self.quote_source == "book" and self.mid is not None
                and self.spread is not None
                and swing_quotes_ok(self.yes_bid, self.yes_ask))


def observe(market: dict[str, Any], orderbook: dict[str, Any] | None,
            topic: str, ts: float | None = None) -> Observation:
    """Build an Observation from GET /markets plus GET /markets/{t}/orderbook.

    Only the order book produces a price. Both bid sides must be present:

        YES bid  = last of orderbook_fp.yes_dollars
        NO  bid  = last of orderbook_fp.no_dollars
        YES ask  = 1.00 - NO bid          (documented reciprocal, see module docstring)

    A book that is missing either side is recorded as ``quote_source="unquoted"``
    with ``mid=None``. The market record's own ``yes_bid_dollars`` /
    ``yes_ask_dollars`` are *not* used to manufacture one: on Kalshi a market
    quoting 0.0020 / 0.8110 reports a "mid" of 0.4065 that no order ever
    touched, and that artefact is what produced the phantom 40-cent alerts on
    KXPRESNOMD-28-HBID (verified against
    https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-HBID/orderbook
    on 2026-11-20, whose yes side is 0.0010/0.0020 and no side is 0.1850-0.1890).
    """
    ob = (orderbook or {}).get("orderbook_fp") or {}
    yes_levels = ob.get("yes_dollars") or []
    no_levels = ob.get("no_dollars") or []

    yb = best_bid(yes_levels)
    nb = best_bid(no_levels)
    yes_bid = yb[0] if yb else None
    yes_bid_size = yb[1] if yb else None
    no_bid = nb[0] if nb else None
    no_bid_size = nb[1] if nb else None
    yes_ask = implied_yes_ask(no_bid)

    quote_source = "book"
    if yes_bid is None or yes_ask is None:
        quote_source = "unquoted"
        # For DISPLAY only: the market record carries official yes_bid_dollars /
        # yes_ask_dollars even when no book was fetched. Those numbers are
        # published on the tables (they are Kalshi's own fields), but they never
        # produce a mid, a mark or an alert, because a quote without depth is
        # not a tradeable price.
        if yes_bid is None:
            yes_bid = dollars(market.get("yes_bid_dollars"))
            yes_bid_size = count(market.get("yes_bid_size_fp"))
        if yes_ask is None:
            yes_ask = dollars(market.get("yes_ask_dollars"))
        # A 0.0000 / 1.0000 pair is the "no quote" placeholder, not a quote.
        if (yes_bid is not None and yes_ask is not None
                and yes_bid <= 0.0 and yes_ask >= 1.0):
            yes_bid, yes_ask = None, None

    spread = None
    if quote_source == "book" and yes_bid is not None and yes_ask is not None:
        spread = round(yes_ask - yes_bid, 4)

    return Observation(
        ts=ts if ts is not None else time.time(),
        ticker=market.get("ticker", ""),
        event_ticker=market.get("event_ticker", ""),
        topic=topic,
        title=(market.get("yes_sub_title") or market.get("title") or "").strip(),
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        mid=mid_price(yes_bid, yes_ask) if quote_source == "book" else None,
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
        no_bid_size=no_bid_size,
        quote_source=quote_source,
        spread=spread,
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


VERIFIABLE_BASES = ("candle_quote_mid", "previous_snapshot_mid")


def alert_record_valid(alert: dict[str, Any]) -> bool:
    """Re-check a stored alert before publishing it again.

    Two checks, both mechanical:

    1. the *current* quote must be two-sided and tighter than
       ``ALERT_MAX_SPREAD`` (``swing_quotes_ok``);
    2. the row must record the basis its reference was measured from, and that
       basis must be one of the two the code can produce
       (``VERIFIABLE_BASES``). A row with no basis was written before the rule
       existed, and a row whose basis names a trade price is not a price move.

    Why the basis and not the numbers: a genuine 10-cent move is, by definition,
    further than 5 cents from the *new* book, so "does the old value sit inside
    the current quote" would reject every real alert. The basis is the only
    field that distinguishes a quote reference from a trade reference, so it is
    the field that is required.

    This is what removes the row `KXPRESNOMD-28-AKLO:1795200068` (0.803 ->
    0.0025, current quote 0.0020/0.0030, no basis): its current quote is tight
    enough to pass check 1, and only check 2 catches it. Its 0.803 was the
    hourly trade print, which is exactly the comparison the fix forbids.
    """
    if not swing_quotes_ok(alert.get("yes_bid"), alert.get("yes_ask")):
        return False
    return alert.get("reference_basis") in VERIFIABLE_BASES


def detect_swing(previous: Observation | None, current: Observation,
                 threshold: float = SWING_THRESHOLD,
                 reference: float | None = None,
                 reference_ts: float | None = None,
                 reference_spread: float | None = None) -> dict[str, Any] | None:
    """Return an alert dict when the measured price moved by >= ``threshold``.

    Price basis
        Both ends of the comparison are YES *mid* prices built from two-sided
        quotes. The reference is the mid of the reference bar's candle quote
        closes (``yes_bid`` / ``yes_ask``), with ``reference_spread`` its
        ask-minus-bid width; the current value is ``current.mid``, which is
        built from the order book. A last *trade* price is never compared with a
        quote mid: doing exactly that produced the phantom "0.811 -> 0.4065"
        alert on KXPRESNOMD-28-HBID, where 0.8110 was the last trade and 0.4065
        was the midpoint of a 0.0020 / 0.8110 book (both verified against the
        live API on 2026-11-20 and against the candle history for that bar).

    Dealability
        The requirement is "any swing >= $0.10 either way", so ``threshold`` is
        applied literally and the spread is *not* used to raise it. What is
        required is that both quotes can actually be dealt on: two resting bids
        and a spread strictly below the threshold. A book whose spread is at
        least $0.10 cannot move its mid by $0.10 through trading — the mid only
        moves because one side was pulled — so such rows are not price moves.
        Both gates live in ``swing_quotes_ok``.

    Reference
        The collector samples every ~5 minutes while a market moves
        continuously. Comparing only against the immediately previous snapshot
        makes every alert fire once and reset, so a market drifting 20 cents in
        4-cent steps never alerts. The caller therefore passes the quote mid at
        the start of the current bar, taken from Kalshi's own published candle
        (a measured value, never an interpolation). The previous snapshot is the
        fallback only when no candle exists, and it is subject to the same gate.

    De-duplication
        The id is ``<ticker>:<bar start>:<direction>``. A re-run inside the same
        bar recomputes the same id, so the row is not appended twice (the same
        Hunter Biden row appeared 7 times in the 18:41Z snapshot, with
        ``observed_gap_seconds`` as low as -3.8).
    """
    if previous is None and reference is None:
        return None
    if not current.alertable:
        return None
    if not swing_quotes_ok(current.yes_bid, current.yes_ask):
        return None
    basis = "candle_quote_mid"
    if reference is not None:
        if reference_spread is None or not (0.0 <= reference_spread < ALERT_MAX_SPREAD):
            return None
        base = reference
        prev_ts = reference_ts
    elif previous is not None:
        if not swing_quotes_ok(previous.yes_bid, previous.yes_ask):
            return None
        base = previous.mid
        prev_ts = previous.ts
        basis = "previous_snapshot_mid"
    else:
        return None
    if base is None or current.mid is None:
        return None
    delta = round(current.mid - base, 4)
    if abs(delta) + 1e-9 < threshold:
        return None
    direction = "up" if delta > 0 else "down"
    bar = int((current.ts // ALERT_DEDUP_SECONDS) * ALERT_DEDUP_SECONDS)
    return {
        "id": f"{current.ticker}:{bar}:{direction}",
        "ts": current.ts,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current.ts)),
        "ticker": current.ticker,
        "event_ticker": current.event_ticker,
        "series_ticker": current.series_ticker,
        "topic": current.topic,
        "title": current.title,
        "previous": base,
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
        "price_source": "order-book mid (two-sided)",
        "reference_basis": basis,
        "spread": quoted_spread(current.yes_bid, current.yes_ask),
        "observed_gap_seconds": round(
            current.ts - (prev_ts if prev_ts is not None else current.ts), 1),
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
    if spread is None:
        # No book for this market: a quote without depth is not a price. The
        # old code defaulted the spread to 2 cents here, which let an empty
        # book with a stale 1-cent quote score as a high-ROI signal.
        return None
    if spread > max_spread:
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
    width = spread
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


# ---------------------------------------------------------------------------
# Model shortlist ("the events our model likes"), one definition, used by both
# the collector and the tests, so the second chat can never silently go empty
# because two different filters disagreed.
# ---------------------------------------------------------------------------

MODEL_SIGNAL_MIN_NET_ROI = 0.05   # modelled net ROI after the taker fee


def model_shortlist(alerts_rows: list[dict[str, Any]],
                    signals: list[dict[str, Any]],
                    min_net_roi: float = MODEL_SIGNAL_MIN_NET_ROI) -> list[dict[str, Any]]:
    """Rows for the model chat: tradeable swings first, then scored signals.

    The model chat used to be built by intersecting alerts with signals on the
    same ticker. That intersection is nearly always empty: an alert needs a
    >= $0.10 move, a signal needs a tight book with depth, and the markets that
    move 10 cents in one bar are usually the ones whose book is a 0.0020/0.8110
    quote. The feed therefore showed "nothing clears the gate" while the model
    had real candidates. This function instead publishes:

    * every alert whose own book is tradeable (``alertable``, spread gate) —
      these are the *swings* the model can act on, tagged ``kind="swing"``;
    * every scored signal at or above ``min_net_roi``, tagged ``kind="signal"``
      and carrying the model's own numbers (``net_roi``, ``side``,
      ``executable_price``).

    Each row states which of the two it is, so nothing is presented as a "high
    ROI alert" when it is only a move, or vice versa.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    by_ticker = {s.get("ticker"): s for s in signals if s.get("ticker")}

    for row in alerts_rows:
        spread = row.get("spread")
        if spread is None or not (0.0 <= spread < ALERT_MAX_SPREAD):
            continue
        sig = by_ticker.get(row.get("ticker"))
        item = dict(row)
        item["kind"] = "swing"
        if sig and sig.get("net_roi") is not None and sig["net_roi"] >= min_net_roi:
            item["kind"] = "swing+signal"
            item["model_net_roi"] = sig.get("net_roi")
            item["model_side"] = sig.get("side")
        key = (str(item.get("ticker")), str(item.get("kind")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)

    for sig in signals:
        if sig.get("net_roi") is None or sig["net_roi"] < min_net_roi:
            continue
        item = {
            "kind": "signal",
            "id": f"signal:{sig.get('ticker')}:{int(float(sig.get('ts') or 0))}",
            "ts": sig.get("ts"),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                 time.gmtime(float(sig.get("ts") or 0))),
            "ticker": sig.get("ticker"),
            "event_ticker": sig.get("event_ticker"),
            "series_ticker": "",
            "topic": sig.get("topic"),
            "title": sig.get("title"),
            "direction": "up" if (sig.get("side") == "yes") else "down",
            "previous": sig.get("executable_price"),
            "current": sig.get("model_fair"),
            "abs_delta": sig.get("edge"),
            "model_net_roi": sig.get("net_roi"),
            "model_side": sig.get("side"),
            "executable_price": sig.get("executable_price"),
            "market_url": sig.get("market_url"),
            "reason": sig.get("reason"),
        }
        key = (str(item.get("ticker")), "signal")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)

    out.sort(key=lambda r: float(r.get("ts") or 0), reverse=True)
    return out


def resolution_topic(series_ticker: str | None, event_ticker: str | None,
                     series_to_topic: dict[str, str],
                     event_to_topic: dict[str, str]) -> str | None:
    """Attribute a settlement to one of the five topics, or None.

    Uses only identifiers Kalshi itself returns, in the order the official
    glossary recommends ("do not parse ticker strings to infer relationships",
    https://docs.kalshi.com/getting_started/terms#ticker-conventions):

    1. the market's own ``series_ticker``, looked up in the registry of series
       that the topic-scoped series queries returned;
    2. the market's own ``event_ticker``, looked up in the registry of events
       that this collector actually discovered for a topic.

    Anything else returns ``None``. The row is then published as "topic not
    attributable" on the Flagged for Review page — never guessed from a title
    or from the shape of a ticker string.

    Why this exists: settlements were mapped only by ``series_ticker``, and
    Kalshi's settled-market records routinely carry ``series_ticker: null``
    (verified on KXQUICKSETTLE-20NOV26H1310-3, fetched 2026-11-20T19:07Z). Every
    row was therefore dropped and the "resolved" tables stayed empty while
    2,000 settlements sat in the store.
    """
    if series_ticker and series_ticker in series_to_topic:
        return series_to_topic[series_ticker]
    if event_ticker and event_ticker in event_to_topic:
        return event_to_topic[event_ticker]
    return None
