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

from .kalshi_api import (DEMO_REST, best_bid, count, dollars, implied_yes_ask,
                         mid_price, kalshi_fee)

SWING_THRESHOLD = 0.10   # USD per contract, either direction (project brief)
MIN_EDGE = 0.02          # USD minimum modelled edge to call something "high ROI"
MAX_SPREAD = 0.20        # skip books wider than this: mid is not meaningful
# Swing alerts need a tight, two-sided quote. If the bid-ask spread is at least
# the swing threshold, the mid can move by $0.10 purely because the quotes moved,
# not because a trade happened. Design choice (not a Kalshi rule): require the
# spread to be strictly below the $0.10 threshold. Logged in VERIFICATION_856e184e.md.
ALERT_MAX_SPREAD = 0.10
# R-F3-1 corroboration tolerance: a reference bar's quote mid must agree with the
# same bar's trade price (``price.previous_dollars`` / ``price.close_dollars``)
# to within this. A stray quote (one un-arbitraged level, e.g. KXPRESNOMD-28-BOBA's
# 0.8820 ask against a 0.0050 trade) moves the quote mid without any trade behind
# it; refusing that at the source is the point of this guard. It is the same
# $0.10 swing threshold so the published reason lines up with the alert rule.
REFERENCE_TRADE_TOLERANCE = SWING_THRESHOLD
SHRINK = 0.50            # how strongly a wide spread pulls the fair value to 0.5
MIN_EXECUTABLE_PRICE = 0.01   # $0.01 is the lowest valid quote on Kalshi's grid
MIN_DEPTH_CONTRACTS = 10.0    # a market with no resting size is not tradable
MIN_TOP_LEVEL_CONTRACTS = 1.0  # the best level must actually hold size

# --- alert hygiene (session arena-dc732aa6, request R-D-01) ---------------
# The published snapshot of 2026-11-20T18:41Z buffered 29 alerts describing
# only 8 distinct moves: every run stamps a fresh id, and the merge only
# excluded exact id matches, so one sustained swing re-fired on every run.
#   * one row per (market, direction, reference bar); repeats fold into it
#   * a later bar earns its own row only when the move grows by ESCALATION_STEP
#   * every row states its price basis, and whether the move was executable at
#     the top of the book (a midpoint move with no size behind it is labelled
#     "indicative", and is reported as a suppression rather than hidden)
ESCALATION_STEP = SWING_THRESHOLD
MIN_ACTIONABLE_SIZE = 1.0     # contracts resting at the level you would trade
MODEL_MIN_NET_ROI = 0.05      # one gate for the shortlist: generator and browser


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
    no_bid_size: float | None = None   # contracts at the best NO bid = YES ask size
    notional: float | None = None      # notional_value_dollars per contract
    # Tick size: ``price_ranges[0].step``, documented on the market schema at
    # https://docs.kalshi.com/api-reference/market/get-market ("Price step/tick
    # size for this range in dollars"). Published next to the $0.10 threshold
    # so a reader can see how many ticks a swing represents. None = the market
    # object carried no price_ranges; the tick is then omitted, never guessed.
    tick_size: float | None = None
    # Reference prices from the official candlestick record of the bar being
    # measured against, when the collector has one (all documented fields of the
    # candlestick schema at
    # https://docs.kalshi.com/api-reference/market/get-market-candlesticks):
    #   ref_yes_bid / ref_yes_ask -> yes_bid.close_dollars / yes_ask.close_dollars
    #   ref_trade_close           -> price.close_dollars (last trade, never used
    #                                 as a swing basis - see 856e184e's quote rule)
    #   ref_previous_dollars      -> price.previous_dollars (trade price at the
    #                                 start of the reference bar; used only to
    #                                 corroborate the reference quote mid - see
    #                                 R-F3-1 in COORDINATION.md)
    ref_ts: float | None = None
    ref_yes_bid: float | None = None
    ref_yes_ask: float | None = None
    ref_trade_close: float | None = None
    ref_previous_dollars: float | None = None
    status: str = "active"
    result: str = ""
    series_ticker: str = ""
    close_time: str = ""
    # This series' own fee multiplier from ``GET /series`` (``fee_multiplier``,
    # documented at https://docs.kalshi.com/api-reference/series/get-series and
    # the multiplier M in the published schedule
    # https://kalshi.com/docs/kalshi-fee-schedule.pdf). ``None`` means the
    # series row was not available for this market — the schedule's own default
    # for a listed general market is M = 1, so callers fall back to 1.0 and the
    # fee is labelled "series default" rather than "series fee multiplier".
    fee_multiplier: float | None = None
    fee_type: str | None = None
    fee_basis: str = ""

    @property
    def market_url(self) -> str:
        return f"https://kalshi.com/markets/{self.series_ticker or self.event_ticker}/{self.ticker}"


def fee_params(series: dict[str, Any] | None) -> tuple[float, str]:
    """Return ``(multiplier, basis)`` for one series' official fee parameters.

    Source of truth is the series object itself: ``fee_multiplier`` ("a floating
    point multiplier applied to the fee calculations") and ``fee_type`` are both
    *required* fields of ``Series`` in the official schema
    (https://docs.kalshi.com/api-reference/market/get-series-list.md), and
    ``fee_type`` names which table of https://kalshi.com/docs/kalshi-fee-schedule.pdf
    applies ('quadratic' = the General Trading Fees Table, 'flat' = the Specific
    Trading Fees Table, which this model does not implement).

    Rules, in order:
      * no series row at all            -> M = 1.0, basis says it is the schedule
        default, not an observation.
      * fee_type is not quadratic-family -> M = 0.0 with a labelled basis, because
        charging the quadratic formula for a flat schedule would invent a number;
        the schedule's own note for a non-modelled structure is the same
        (see kalshi_api.kalshi_fee).
      * otherwise                        -> M = the series' own fee_multiplier
        (0.0 means the series is fee-free), basis quotes the field.
    """
    if not series:
        return 1.0, "series default M=1 (no GET /series row for this market)"
    fee_type = series.get("fee_type")
    mult = series.get("fee_multiplier")
    if fee_type and not str(fee_type).startswith("quadratic"):
        return 0.0, f"fee_type '{fee_type}' is not the quadratic schedule — no fee modelled (labelled)"
    if mult is None:
        return 1.0, "series default M=1 (fee_multiplier absent from GET /series)"
    try:
        m = float(mult)
    except (TypeError, ValueError):
        return 1.0, f"series default M=1 (unreadable fee_multiplier {mult!r})"
    return m, f"GET /series fee_multiplier={m:g}, fee_type={fee_type or 'unknown'}"


def observe(market: dict[str, Any], orderbook: dict[str, Any] | None,
            topic: str, ts: float | None = None,
            reference: dict[str, Any] | None = None,
            series: dict[str, Any] | None = None) -> Observation:
    """``reference`` is the optional bar-open record from the candlestick
    endpoint; attaching it lets the swing test and the UI state exactly which
    Kalshi-published numbers the comparison used.

    ``series`` is the market's own row from ``GET /series`` (the collector has
    it from the topic registry; it is not on the market object). It carries
    ``fee_multiplier`` / ``fee_type``, the only per-series fee facts Kalshi
    publishes machine-readably, so the alert and model ROI can charge the fee
    this series actually pays instead of assuming the general one.
    """
    """Build an Observation from GET /markets plus GET /markets/{t}/orderbook."""
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

    # Fall back to the market record's own quotes when the book is empty...
    if yes_ask is None:
        yes_ask = dollars(market.get("yes_ask_dollars"))
    if yes_bid is None:
        yes_bid = dollars(market.get("yes_bid_dollars"))
    if yes_bid is None and yes_bid_size is None:
        yes_bid_size = count(market.get("yes_bid_size_fp"))
    if no_bid_size is None:
        # The ask side of the market record, when the book did not give one.
        no_bid_size = count(market.get("yes_ask_size_fp"))

    # ...but a market with no quotes at all reports 0.0000 bid / 1.0000 ask.
    # Averaging that pair produces a phantom 0.50 mid, which is how a golf
    # outlier with no book would appear to "jump" to exactly $0.50 and back.
    # A full 0-to-1 spread is not a price: treat it as no quote.
    if (yes_bid is not None and yes_ask is not None
            and yes_bid <= 0.0 and yes_ask >= 1.0):
        yes_bid, yes_ask = None, None

    ref = reference or {}
    price_ranges = market.get("price_ranges") or []
    tick = None
    if price_ranges:
        tick = dollars((price_ranges[0] or {}).get("step"))
    return Observation(
        ts=ts if ts is not None else time.time(),
        ref_ts=ref.get("ts"),
        ref_yes_bid=ref.get("yes_bid"),
        ref_yes_ask=ref.get("yes_ask"),
        ref_trade_close=ref.get("trade_close"),
        ref_previous_dollars=ref.get("previous_dollars"),
        no_bid_size=no_bid_size,
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
        tick_size=tick,
        status=market.get("status", "active"),
        result=market.get("result", "") or "",
        series_ticker=market.get("series_ticker", "") or "",
        close_time=market.get("close_time", "") or "",
        fee_multiplier=fee_params(series)[0] if series is not None else None,
        fee_type=(series or {}).get("fee_type"),
        fee_basis=fee_params(series)[1],
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


def threshold_in_ticks(threshold: float,
                       tick_size: float | None) -> float | None:
    """How many of this market's ticks the $ threshold represents.

    ``tick_size`` is the documented ``price_ranges[0].step``. None when the
    tick is unknown or not positive — the UI then omits the ticks note rather
    than inventing one.
    """
    if tick_size is None or tick_size <= 0:
        return None
    return round(threshold / tick_size, 1)


def mark_reverted(alerts_list: list[dict[str, Any]],
                  references: dict[str, dict[str, Any]],
                  threshold: float = SWING_THRESHOLD) -> int:
    """Annotate alerts that reverted within one candle (request R-3DCF-3).

    ``references[ticker]["candles"]`` carries the completed 1-minute candles
    bar_reference fetched for that market (each with its documented trade
    close). For an alert, the first candle whose ``end_period_ts`` is strictly
    after the alert's reference bar (``previous_ts`` for candle-basis rows, the
    observation time otherwise) is "the next candle". When that candle's trade
    close is back within ``threshold`` of the alert's previous level, the alert
    gains ``reverted_within_candle = {candle_end_ts, trade_close,
    previous_level}``. Rows keep a once-set annotation: a measured revert is a
    fact that happened, not a state to clear when the candle ages out of the
    fetch window. Returns the number of rows annotated this run.
    """
    annotated = 0
    for alert in alerts_list:
        if alert.get("reverted_within_candle"):
            continue
        ref = references.get(alert.get("ticker") or "") or {}
        candles = [c for c in (ref.get("candles") or []) if c.get("ts")]
        if not candles:
            continue
        after = alert.get("previous_ts")
        if after is None:
            after = alert.get("ts")
        if after is None:
            continue
        nxt = min((c for c in candles if c["ts"] > after),
                  key=lambda c: c["ts"], default=None)
        if not nxt:
            continue
        close = nxt.get("trade_close")
        prev_level = alert.get("previous")
        if close is None or prev_level is None:
            continue
        if abs(close - prev_level) + 1e-9 < threshold:
            alert["reverted_within_candle"] = {
                "candle_end_ts": nxt["ts"],
                "trade_close": close,
                "previous_level": prev_level,
                "check_basis": "official 1-minute candlestick trade close",
            }
            annotated += 1
    return annotated


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


def _mid_and_spread(mid: float | None, spread: float | None
                    ) -> tuple[float | None, float | None]:
    """Recover (bid, ask) from a reference mid and its quoted spread."""
    if mid is None or spread is None:
        return None, None
    return round(mid - spread / 2.0, 4), round(mid + spread / 2.0, 4)


def _swing(previous: Observation | None, current: Observation,
           threshold: float, reference: float | None,
           reference_ts: float | None, reference_spread: float | None,
           bar_seconds: int) -> tuple[dict[str, Any] | None,
                                      dict[str, Any] | None]:
    """Single implementation of the swing test. Returns (alert, suppression).

    ``alert`` is the row the chat shows, or None when the move is not measured
    or does not clear the threshold. ``suppression`` is a record of a *midpoint*
    move that would have cleared the threshold but was refused by the quote rule
    — published so nothing disappears silently (R-D-01).
    """
    # A reference attached to the observation (from the candlestick endpoint)
    # fills in for callers that did not pass one, and gives us both sides of
    # the reference quote rather than only its midpoint.
    if reference is None and current.ref_yes_bid is not None \
            and current.ref_yes_ask is not None:
        reference = round((current.ref_yes_bid + current.ref_yes_ask) / 2.0, 4)
        reference_ts = current.ref_ts if reference_ts is None else reference_ts
        reference_spread = quoted_spread(current.ref_yes_bid, current.ref_yes_ask)

    def naive_delta() -> float | None:
        base = reference if reference is not None else (
            previous.mid if previous is not None else None)
        if base is None or current.mid is None:
            return None
        return round(current.mid - base, 4)

    def suppress(reason: str) -> tuple[None, dict[str, Any] | None]:
        d = naive_delta()
        if d is None or abs(d) + 1e-9 < threshold:
            return None, None
        return None, {
            "id": f"suppressed:{current.ticker}:{int(current.ts)}",
            "ticker": current.ticker,
            "event_ticker": current.event_ticker,
            "series_ticker": current.series_ticker,
            "topic": current.topic,
            "title": current.title,
            "abs_delta": abs(d),
            "direction": "up" if d > 0 else "down",
            "yes_bid": current.yes_bid,
            "yes_ask": current.yes_ask,
            "spread": quoted_spread(current.yes_bid, current.yes_ask),
            "reason": reason,
            "market_url": current.market_url,
            "ts": current.ts,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(current.ts)),
            "threshold": threshold,
        }

    if previous is None and reference is None:
        return None, None
    # The current observation must itself be a tight, two-sided quote.
    if not swing_quotes_ok(current.yes_bid, current.yes_ask):
        spread = quoted_spread(current.yes_bid, current.yes_ask)
        if spread is None:
            return suppress("one-sided book: only one side is quoted")
        return suppress(f"YES spread {spread:.4f} is not tighter than the "
                        f"${ALERT_MAX_SPREAD:.2f} alert threshold, so the "
                        "midpoint can move without a trade")
    basis = "candle_quote_mid"
    if reference is not None:
        if reference_spread is None or not (0.0 <= reference_spread < ALERT_MAX_SPREAD):
            return suppress("reference quote is missing or wider than the "
                            f"${ALERT_MAX_SPREAD:.2f} threshold")
        base = reference
    elif previous is not None:
        if not swing_quotes_ok(previous.yes_bid, previous.yes_ask):
            return suppress("previous snapshot is one-sided or too wide to be "
                            "a valid reference")
        base = previous.mid
        basis = "previous_snapshot_mid"
    else:
        base = None
    if base is None or current.mid is None:
        return None, None
    prev_ts = reference_ts if reference is not None else (
        previous.ts if previous is not None else None)
    delta = round(current.mid - base, 4)
    if abs(delta) + 1e-9 < threshold:
        return None, None
    direction = "up" if delta > 0 else "down"
    spread = quoted_spread(current.yes_bid, current.yes_ask)

    # --- trade-price corroboration (R-F3-1, COORDINATION.md board L) -------
    # The reference is a *quote* mid. A quote mid can move on a single stray,
    # un-arbitraged level with no trade behind it (observed on
    # KXPRESNOMD-28-BOBA: quote ask close 0.8820 against a trade price of
    # 0.0050). The candle also publishes the bar's trade price, so compare the
    # reference quote mid against it. If they disagree by at least the swing
    # threshold, the reference quote is not corroborated by trades and the
    # candidate swing is a quote artefact: refuse it here, at the source, and
    # publish the refusal (never hide it) the same way the quote rule does.
    # Only the candle basis has a trade price to compare against; the
    # previous-snapshot fallback never carries one and is left untouched.
    trade_ref = current.ref_previous_dollars
    trade_basis = "price.previous_dollars"
    if trade_ref is None:
        trade_ref = current.ref_trade_close
        trade_basis = "price.close_dollars"
    if basis == "candle_quote_mid" and trade_ref is not None:
        ref_trade_gap = round(base - trade_ref, 4)
        if abs(ref_trade_gap) + 1e-9 >= REFERENCE_TRADE_TOLERANCE:
            sup = suppress(
                f"reference quote mid {base:.4f} is not corroborated by the "
                f"candle trade price {trade_basis} {trade_ref:.4f} "
                f"(gap {abs(ref_trade_gap):.4f} >= ${REFERENCE_TRADE_TOLERANCE:.2f}), "
                "so the move is a stray quote, not a trade")
            if sup[1] is not None:
                sup[1]["trade_price"] = trade_ref
                sup[1]["trade_price_basis"] = trade_basis
                sup[1]["trade_price_gap"] = ref_trade_gap
                sup[1]["corroboration"] = "uncorroborated"
            return sup
    corroboration = None
    corroboration_gap = None
    if trade_ref is not None:
        corroboration_gap = round(base - trade_ref, 4)
        corroboration = ("corroborated"
                         if abs(corroboration_gap) + 1e-9
                         < REFERENCE_TRADE_TOLERANCE else "uncorroborated")

    # --- executability ---------------------------------------------------
    # Buy YES at the ask (implied by the best NO bid); sell YES into the YES bid.
    ref_bid, ref_ask = _mid_and_spread(base, reference_spread)
    if current.ref_yes_bid is not None and current.ref_yes_ask is not None:
        ref_bid, ref_ask = current.ref_yes_bid, current.ref_yes_ask
    if direction == "up":
        cur_exec, ref_exec = current.yes_ask, ref_ask
        size, size_name = current.no_bid_size, "contracts offered at the implied YES ask"
    else:
        cur_exec, ref_exec = current.yes_bid, ref_bid
        size, size_name = current.yes_bid_size, "contracts bid at the top YES bid"
    exec_delta = (round(cur_exec - ref_exec, 4)
                  if cur_exec is not None and ref_exec is not None else None)
    quality, reasons = "executable", []
    if size is not None and size < MIN_ACTIONABLE_SIZE:
        quality = "indicative"
        reasons.append("no size at the level you would trade")
    if exec_delta is not None and abs(exec_delta) + 1e-9 < threshold:
        quality = "indicative"
        reasons.append(f"the executable side moved only {exec_delta:+.4f} while "
                       f"the midpoint moved {delta:+.4f}")
    bar_start = int(current.ts // bar_seconds * bar_seconds)
    alert = {
        "id": f"{current.ticker}:{int(current.ts)}",
        # Stable identity for the rolling buffer: one row per market, per
        # direction, per reference bar. Repeated runs fold into it.
        "key": f"{current.ticker}:{direction}:{bar_start}",
        "bar_start": bar_start,
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
        "observed_gap_seconds": round(
            current.ts - (prev_ts if prev_ts is not None else current.ts), 1),
        "reference_basis": basis,
        "basis": basis,                       # alias used by the site templates
        "price_pair": "quote mid to quote mid",
        "spread": spread,
        "trade_price": trade_ref,
        "trade_price_basis": trade_basis if trade_ref is not None else None,
        "trade_price_gap": corroboration_gap,
        "corroboration": corroboration,
        "size_at_top": size,
        "size_name": size_name,
        "executable": {
            "side": ("buy YES at the ask" if direction == "up"
                     else "sell YES into the YES bid"),
            "reference_price": ref_exec,
            "current_price": cur_exec,
            "delta": exec_delta,
            "clears_threshold": (exec_delta is not None
                                 and abs(exec_delta) + 1e-9 >= threshold),
        },
        "quality": quality,
        "quality_reason": "; ".join(reasons) if reasons else (
            "two-sided book tighter than the threshold, move present on the "
            "executable side"),
        "first_seen_ts": current.ts,
        "last_seen_ts": current.ts,
        "repeat_count": 0,
        # Tick size from the documented price_ranges[0].step (R-F3-2), so the
        # row can state how many ticks the $0.10 threshold represents.
        "tick_size": current.tick_size,
        "threshold_ticks": threshold_in_ticks(threshold, current.tick_size),
    }
    return alert, None


def detect_swing(previous: Observation | None, current: Observation,
                 threshold: float = SWING_THRESHOLD,
                 reference: float | None = None,
                 reference_ts: float | None = None,
                 reference_spread: float | None = None,
                 bar_seconds: int = 300) -> dict[str, Any] | None:
    """Return an alert dict when the reference price moved by >= threshold.

    Price basis: both sides of the comparison are YES *mid* prices built from
    quotes (bid and ask). ``reference`` must therefore be the mid of the
    reference bar's quote closes, with ``reference_spread`` its ask-bid width.
    A last-trade price must never be compared with a quote mid. Both the current
    and the reference quotes must be two-sided and narrower than
    ALERT_MAX_SPREAD, otherwise no alert is raised (that suppression is
    published by ``swing_rejection`` instead of being dropped).

    How the reference works, and why it is not simply "the previous snapshot":

    The collector samples roughly every 5-15 minutes while a market can move
    continuously. Comparing only against the immediately previous sample makes
    every alert fire once and then reset, so a market that drifts 20 cents over
    an hour in 4-cent steps never alerts. The caller therefore passes the price
    at the start of the current 5-minute bar, taken from Kalshi's own published
    candle quote closes (yes_bid / yes_ask), not the last-trade close. That
    reference is still a measured price, never an interpolation, and it is used
    whenever available; the previous snapshot is the fallback for markets
    without candle history.
    """
    return _swing(previous, current, threshold, reference, reference_ts,
                  reference_spread, bar_seconds)[0]


def swing_rejection(previous: Observation | None, current: Observation,
                    threshold: float = SWING_THRESHOLD,
                    reference: float | None = None,
                    reference_ts: float | None = None,
                    reference_spread: float | None = None,
                    bar_seconds: int = 300) -> dict[str, Any] | None:
    """Why a >= $0.10 *midpoint* move did not become an alert, if that happened.

    Kept deliberately separate from ``detect_swing`` so the alert rule stays
    strict while the reviewer still sees what the rule refused.
    """
    return _swing(previous, current, threshold, reference, reference_ts,
                  reference_spread, bar_seconds)[1]


def book_record_divergence(market: dict[str, Any], orderbook: dict[str, Any] | None,
                           threshold: float = SWING_THRESHOLD) -> dict[str, Any] | None:
    """Report a market whose order book and market record disagree by >= threshold.

    Both numbers come from Kalshi, from two documented endpoints, and they can
    disagree in the demo environment. Observed on 2026-11-20T19:1xZ for
    KXPRESNOMD-28-HBID:

        GET /markets/KXPRESNOMD-28-HBID
            yes_bid_dollars 0.0020   yes_ask_dollars 0.0030   -> mid 0.0025
        GET /markets/KXPRESNOMD-28-HBID/orderbook
            best YES bid 0.0020, best NO bid 0.1890
            -> implied YES ask 1.00 - 0.1890 = 0.8110         -> mid 0.4065

    A $0.8080 gap on the same market, at the same moment. Whichever is stale, a
    dashboard must not present either as "the price" without saying so, because
    the alert engine and the chart read the book while the market table reads
    the record. This function exists to make that visible instead of picking a
    winner.
    """
    ob = (orderbook or {}).get("orderbook_fp") or {}
    yb = best_bid(ob.get("yes_dollars") or [])
    nb = best_bid(ob.get("no_dollars") or [])
    book_bid = yb[0] if yb else None
    book_ask = implied_yes_ask(nb[0] if nb else None)
    rec_bid = dollars(market.get("yes_bid_dollars"))
    rec_ask = dollars(market.get("yes_ask_dollars"))
    if book_bid is None and book_ask is None:
        return None
    if rec_bid is None and rec_ask is None:
        return None
    book_mid = mid_price(book_bid, book_ask)
    rec_mid = mid_price(rec_bid, rec_ask)
    if book_mid is None or rec_mid is None:
        return None
    gap = round(book_mid - rec_mid, 4)
    if abs(gap) + 1e-9 < threshold:
        return None
    return {
        "ticker": market.get("ticker", ""),
        "event_ticker": market.get("event_ticker", ""),
        "title": (market.get("yes_sub_title") or market.get("title") or "").strip(),
        "book_mid": book_mid, "record_mid": rec_mid, "gap": gap,
        "abs_gap": abs(gap),
        "book_yes_bid": book_bid, "book_yes_ask": book_ask,
        "record_yes_bid": rec_bid, "record_yes_ask": rec_ask,
        "threshold": threshold,
        "source_book": (f"{DEMO_REST}/markets/{market.get('ticker')}/orderbook"),
        "source_record": f"{DEMO_REST}/markets/{market.get('ticker')}",
    }


def fold_alerts(new_alerts: list[dict[str, Any]], existing: list[dict[str, Any]],
                max_alerts: int = 400,
                escalation: float = ESCALATION_STEP) -> dict[str, Any]:
    """Merge this run's alerts into the rolling chat buffer without duplicates.

    * same ``key`` (market + direction + reference bar) -> update that row and
      keep the largest move, counting the repeat;
    * later bar, same market + direction -> a new row only when the move has
      grown by at least ``escalation``; smaller repeats fold into it;
    * the opposite direction is always its own row.

    Returns ``{"alerts": [...], "added": n, "escalated": n, "folded": n}``.
    """
    merged = [dict(a) for a in existing]
    stats = {"folded": 0, "added": 0, "escalated": 0}

    def index_of(row: dict[str, Any]) -> dict[Any, int]:
        return {a.get("key"): i for i, a in enumerate(merged) if a.get("key")}

    by_key = index_of({})
    for fresh in new_alerts:
        row = dict(fresh)
        idx = by_key.get(row.get("key"))
        if idx is not None:
            cur = merged[idx]
            if (row.get("abs_delta") or 0) > (cur.get("abs_delta") or 0):
                row["first_seen_ts"] = cur.get("first_seen_ts", row["first_seen_ts"])
                row["repeat_count"] = (cur.get("repeat_count") or 0) + 1
                if cur.get("news") and not row.get("news"):
                    row["news"] = cur["news"]
                merged[idx] = row
            else:
                cur["last_seen_ts"] = row["ts"]
                cur["iso"] = row["iso"]
                cur["repeat_count"] = (cur.get("repeat_count") or 0) + 1
            stats["folded"] += 1
            continue
        newest = None
        for i, cur in enumerate(merged):
            if (cur.get("ticker") == row.get("ticker")
                    and cur.get("direction") == row.get("direction")):
                if newest is None or ((cur.get("ts") or 0)
                                       > (merged[newest].get("ts") or 0)):
                    newest = i
        if newest is not None:
            cur = merged[newest]
            grows = ((row.get("abs_delta") or 0)
                     >= ((cur.get("abs_delta") or 0) + escalation - 1e-9))
            if not grows:
                cur["last_seen_ts"] = row["ts"]
                cur["iso"] = row["iso"]
                cur["repeat_count"] = (cur.get("repeat_count") or 0) + 1
                for field in ("current", "yes_bid", "yes_ask", "spread",
                              "size_at_top", "quality", "quality_reason",
                              "volume", "open_interest", "executable", "news"):
                    if row.get(field) is not None:
                        cur[field] = row[field]
                stats["folded"] += 1
                continue
            row["escalated_from"] = cur.get("key")
            stats["escalated"] += 1
        merged.insert(0, row)
        by_key = index_of({})
        stats["added"] += 1

    merged.sort(key=lambda a: (a.get("last_seen_ts") or a.get("ts") or 0,
                               a.get("abs_delta") or 0), reverse=True)
    return {"alerts": merged[:max_alerts], **stats}


def clears_model_gate(signal: dict[str, Any] | None,
                      min_net_roi: float = MODEL_MIN_NET_ROI) -> bool:
    """One definition of "the model likes this", shared by the generator, the
    JSON payload and the browser. The server used to gate the shortlist on
    ``score >= 0.10`` while the page gated it on ``net_roi >= 0.05``, so the two
    views of the same feed disagreed."""
    if not signal:
        return False
    roi = signal.get("net_roi")
    if roi is None:
        return False
    try:
        return float(roi) >= min_net_roi
    except (TypeError, ValueError):
        return False


def high_roi_alerts(alerts_: Iterable[dict[str, Any]],
                    signals: Iterable[dict[str, Any]],
                    min_net_roi: float = MODEL_MIN_NET_ROI,
                    require_executable: bool = True) -> list[dict[str, Any]]:
    """Alerts the model also likes: a >= $0.10 swing *and* a live high-ROI signal.

    Rows whose move is only indicative are left out on purpose — the shortlist
    is the feed a trader would act on, so it must be executable.
    """
    liked: dict[str, dict[str, Any]] = {}
    for sig in signals:
        if clears_model_gate(sig, min_net_roi):
            liked[sig.get("ticker")] = sig
    out = []
    for alert in alerts_:
        if require_executable and alert.get("quality") == "indicative":
            continue
        sig = liked.get(alert.get("ticker"))
        if not sig:
            continue
        row = dict(alert)
        row["model_net_roi"] = sig.get("net_roi")
        row["model_side"] = sig.get("side")
        row["model_executable_price"] = sig.get("executable_price")
        out.append(row)
    return out


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
    # Which official fee parameters the fee above used, so a reader can audit
    # the number instead of trusting it (see fee_params).
    fee_multiplier: float = 1.0
    fee_basis: str = "series default M=1 (no GET /series row for this market)"

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
    # Charge this series' own fee, not an assumed one: the schedule's multiplier
    # M is a required per-series field (GET /series), and a fee-free series must
    # not be screened out by a fee it never pays. ``obs`` already carries the
    # resolved pair (see fee_params); 1.0 only when no series row was available.
    fee_mult = 1.0 if obs.fee_multiplier is None else obs.fee_multiplier
    fee_basis = obs.fee_basis or fee_params(None)[1]
    for side, price, fair_side in candidates:
        edge = round(fair_side - price, 4)
        if edge < min_edge:
            continue
        fee = kalshi_fee(price, 1.0, fee_mult)
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
            score=score, fee_multiplier=fee_mult, fee_basis=fee_basis,
            reason=(f"mid {mid:.2f} shrunk to fair {fair:.2f} on a {width:.2f} "
                    f"spread; buying {side.upper()} at {price:.2f} leaves "
                    f"{edge:.2f} of modelled edge after the "
                    f"${fee:.4f} taker fee ({fee_basis})"),
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
            "tick_size": obs.tick_size,
            "status": obs.status,
            "result": obs.result,
            "close_time": obs.close_time,
            "market_url": obs.market_url,
        })
    return sorted(rows, key=lambda r: r["dollar_activity"], reverse=True)
