"""The "model shortlist" — the selective half of the two live chat feeds.

Why this module exists
----------------------
The desk publishes two scrolling chats. The first ("All events") is every
observed move of at least $0.10. The second ("Model shortlist") is the subset
the model likes, ranked by modelled net return after Kalshi's published taker
fee. Before this module the shortlist was derived from ``collector.alerts``
and was empty in practice: the collector's reference price for a swing is a
*candle close* (a traded price) while the "current" price is an *order-book
mid*, and the Kalshi demo feed prints alternating trades on a market whose
book never moves. Comparing the two is comparing different things, so the
edge that comes out of it is an artifact.

Evidence for that (official demo API, 2026-11-20):

  * ``GET /series/KXPRESNOMD/markets/KXPRESNOMD-28-AKLO/candlesticks``
    ``period_interval=1`` alternates ``price.close_dollars`` between 0.8030 and
    0.0030 every minute while ``yes_bid.close_dollars`` stays at 0.0020 and
    ``yes_ask.close_dollars`` stays at 0.0030 for the whole window.
  * ``GET /markets/KXPRESNOMD-28-AKLO/orderbook`` returns a book that is
    0.0020 x 83,333.33 on the bid side and a 0.9970 NO bid, i.e. the market
    has not moved at all.

So the model here is built on the **order book** only. Both ends of every
comparison are book mids, which is the only basis on which the demo feed is
self-consistent.

The model
---------
For a market whose book mid has moved from ``p_ref`` to ``p_now``:

    fair      = (p_ref + p_now) / 2          # half the move is an overreaction
    edge_YES  = fair - yes_ask               # buy YES  -> pay the ask
    edge_NO   = yes_bid - fair               # buy NO   -> pay 1 - yes_bid
    fee       = 0.07 * C * P * (1 - P)       # Kalshi published taker fee
    net_edge  = edge - fee
    net_roi   = net_edge / price

``fair`` is the midpoint between where the contract was and where it is now:
the model assumes half of a move is an overreaction that unwinds. ``fair`` is
never allowed to be a value the market itself is quoting, so the model can
only produce an edge when the price has actually left where it was.

Two references are used, both of them book mids:

``swing``  ``p_ref`` is the book mid recorded in the previous snapshot. The
           pick only qualifies if the book itself moved by at least $0.10,
           i.e. the move is confirmed by the book and not by a single trade
           print. This is the row that answers "the model likes this swing".
``level``  ``p_ref`` is the mean of the recent book-mid trail (up to
           ``TRAIL_LEN`` snapshots). This finds a contract that has drifted
           away from its own recent average without a single big print.

Every gate below is applied before a row is published:

1. The book must be quoted on both sides and the spread must be <= $0.20.
2. The side we would buy must have at least ``MIN_DEPTH_CONTRACTS`` resting.
3. The executable price must sit on Kalshi's $0.01-$0.99 grid.
4. The edge after the published taker fee must be >= ``MIN_EDGE`` ($0.02) and
   the net ROI must be positive.

A row that fails a gate is not published as a pick; the reason is recorded in
``data/shortlist.json`` so the site can explain what the model rejected and
why. Nothing here is a prediction or a claim of profitability: it is a
transparent, rule-based ranking of what the model would trade and what it
would pay, recomputable from the numbers shown on the page.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .kalshi_api import kalshi_fee

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LIVE_PATH = os.path.join(DATA_DIR, "live.json")
HISTORY_PATH = os.path.join(DATA_DIR, "mid_history.json")
OUT_PATH = os.path.join(DATA_DIR, "shortlist.json")

API = "https://external-api.demo.kalshi.co/trade-api/v2"

SWING_THRESHOLD = 0.10     # USD, the brief's alert size
MIN_EDGE = 0.02            # USD of edge after fees before a row qualifies
MAX_SPREAD = 0.20          # wider books are not meaningful
MIN_DEPTH_CONTRACTS = 10.0  # the side we would buy must have real size
MIN_PRICE = 0.01           # lowest tradable quote on Kalshi's grid
MAX_PRICE = 0.99
TRAIL_LEN = 12             # snapshots kept for the mean-reversion reference
MAX_PICKS = 40             # rows published in the shortlist chat
MIN_DRIFT = 0.01           # smallest drift a "level" pick may be based on
                           # (the $0.02 edge gate, not this number, is what
                           #  decides whether the model actually likes it)


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)


def _usd(amount: float, decimals: int = 4) -> str:
    """Dollar amount with the sign *outside* the currency symbol.

    A negative edge must read ``-$0.0340``, never ``$-0.0340`` — the site
    contract pins that form on every published page
    (tests/test_site_contract.py::TestNegativeMoney), and these reason strings
    are published verbatim in the model chat.
    """
    magnitude = f"{abs(amount):.{decimals}f}"
    return f"-${magnitude}" if amount < 0 else f"${magnitude}"


def book_of(event: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(yes bid, yes ask, mid) for one event row of the snapshot.

    The snapshot's ``liquidity`` block is the collector's own reading of
    ``GET /markets/{ticker}/orderbook``; when it is missing the market's own
    ``yes_bid``/``yes_ask`` quotes are used. Both are official API values.
    """
    liq = event.get("liquidity") or {}
    bid = liq.get("best_yes_bid")
    ask = liq.get("best_yes_ask")
    if bid is None:
        bid = event.get("yes_bid")
    if ask is None:
        ask = event.get("yes_ask")
    try:
        bid = None if bid is None else float(bid)
        ask = None if ask is None else float(ask)
    except (TypeError, ValueError):
        return None, None, None
    if bid is None or ask is None:
        return bid, ask, None
    return bid, ask, round((bid + ask) / 2.0, 4)


def _rejection(reason: str) -> dict[str, Any]:
    return {"accepted": False, "reason": reason}


def evaluate(event: dict[str, Any], p_ref: float, p_now: float,
             kind: str, alert: dict[str, Any] | None = None) -> dict[str, Any]:
    """Price one market with the model and apply every gate.

    ``p_ref`` and ``p_now`` must both be order-book mids (YES axis). Returns a
    dict with ``accepted`` and, when accepted, the full set of numbers the
    page needs to show the calculation.
    """
    liq = event.get("liquidity") or {}
    bid, ask, mid = book_of(event)
    if bid is None or ask is None:
        return _rejection("the book is not quoted on both sides")
    spread = round(ask - bid, 4)
    if spread <= 0:
        return _rejection("the book is crossed (ask at or below bid)")
    if spread > MAX_SPREAD:
        return _rejection(f"the spread is {_usd(spread, 2)}, wider than "
                          f"{_usd(MAX_SPREAD, 2)}, so the mid is not meaningful")
    if p_now is None or p_ref is None:
        return _rejection("no book reference to compare against")
    if not (0.0 < p_now < 1.0) or not (0.0 < p_ref < 1.0):
        return _rejection("the reference price is outside the $0.01-$0.99 grid")

    fair = round((p_ref + p_now) / 2.0, 4)

    yes_depth = float(liq.get("yes_bid_contracts") or 0.0)
    no_depth = float(liq.get("no_bid_contracts") or 0.0)

    candidates = []
    # Buy YES: pay the implied YES ask, which is 1 - best NO bid.
    if MIN_PRICE <= ask <= MAX_PRICE:
        candidates.append(("yes", ask, fair, yes_depth))
    # Buy NO: pay 1 - best YES bid.
    no_price = round(1.0 - bid, 4)
    if MIN_PRICE <= no_price <= MAX_PRICE:
        candidates.append(("no", no_price, round(1.0 - fair, 4), no_depth))

    if not candidates:
        return _rejection("neither side can be bought inside the $0.01-$0.99 grid")

    best: dict[str, Any] | None = None
    reasons: list[str] = []
    for side, price, fair_side, depth in candidates:
        edge = round(fair_side - price, 4)
        if edge < MIN_EDGE:
            reasons.append(f"{side.upper()} at {price:.4f} leaves only "
                           f"{_usd(edge)} of edge before fees")
            continue
        if depth < MIN_DEPTH_CONTRACTS:
            reasons.append(f"{side.upper()} has only {depth:.0f} contracts resting")
            continue
        fee = kalshi_fee(price, 1.0)
        net = round(edge - fee, 4)
        if net < MIN_EDGE:
            reasons.append(f"{side.upper()} leaves {_usd(net)} after the "
                           f"{_usd(fee)} taker fee")
            continue
        if price <= 0:
            continue
        net_roi = round(net / price, 4)
        if net_roi <= 0:
            reasons.append(f"{side.upper()} has a non-positive modelled return")
            continue
        row = {
            "accepted": True,
            "kind": kind,
            "ticker": event.get("ticker"),
            "event_ticker": event.get("event_ticker"),
            "series_ticker": event.get("series_ticker"),
            "topic": event.get("topic"),
            "title": event.get("title"),
            "side": side,
            "executable_price": price,
            "model_fair": fair_side,
            "reference_price": p_ref,
            "current_price": p_now,
            "edge": edge,
            "fee": fee,
            "net_edge": net,
            "net_roi": net_roi,
            "spread": spread,
            "depth_contracts": depth,
            "yes_bid": bid,
            "yes_ask": ask,
            "market_url": event.get("market_url"),
            "source_url": f"{API}/markets/{event.get('ticker')}",
            "book_source_url": f"{API}/markets/{event.get('ticker')}/orderbook",
            "reason": (f"book mid moved {p_ref:.4f} -> {p_now:.4f}; fair value "
                       f"{fair:.4f} is the midpoint of the two, so {side.upper()} "
                       f"at {price:.4f} leaves {_usd(edge)} of edge and "
                       f"{_usd(net)} after the {_usd(fee)} taker fee"),
            "ts": time.time(),
        }
        if alert:
            row["alert"] = {
                "id": alert.get("id"),
                "iso": alert.get("iso"),
                "delta": alert.get("delta"),
                "direction": alert.get("direction"),
            }
        if best is None or row["net_roi"] > best["net_roi"]:
            best = row

    if best is None:
        return _rejection("; ".join(reasons) or "no side passed the model's gates")
    return best


def build(live: dict[str, Any] | None = None,
          history: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute the shortlist and the new book-mid history."""
    live = live if live is not None else _load(LIVE_PATH, {})
    history = history if history is not None else _load(HISTORY_PATH, {})
    previous_points: dict[str, Any] = history.get("points") or {}
    trails: dict[str, list[float]] = history.get("trail") or {}

    events = live.get("events") or []
    by_ticker = {e.get("ticker"): e for e in events if e.get("ticker")}
    alerts = live.get("alerts") or []
    latest_alert: dict[str, dict[str, Any]] = {}
    for alert in alerts:
        ticker = alert.get("ticker")
        if not ticker:
            continue
        prior = latest_alert.get(ticker)
        if prior is None or (alert.get("ts") or 0) >= (prior.get("ts") or 0):
            latest_alert[ticker] = alert

    picks: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    new_points: dict[str, Any] = {}
    new_trails: dict[str, list[float]] = {}

    for ticker, event in by_ticker.items():
        bid, ask, mid = book_of(event)
        if mid is None or bid is None or ask is None:
            continue
        new_points[ticker] = {"ts": live.get("generated_at_ts") or time.time(),
                              "bid": bid, "ask": ask, "mid": mid}
        trail = list(trails.get(ticker) or [])
        trail.append(mid)
        new_trails[ticker] = trail[-TRAIL_LEN:]

    # --- swing picks: the book itself moved by at least $0.10 -----------
    for ticker, event in by_ticker.items():
        point = new_points.get(ticker)
        prior = previous_points.get(ticker)
        if not point or not prior:
            continue
        p_ref = prior.get("mid")
        p_now = point.get("mid")
        if p_ref is None or p_now is None:
            continue
        move = round(p_now - p_ref, 4)
        if abs(move) + 1e-9 < SWING_THRESHOLD:
            continue
        alert = latest_alert.get(ticker)
        outcome = evaluate(event, p_ref, p_now, "swing", alert)
        if outcome.get("accepted"):
            outcome["book_move"] = move
            picks.append(outcome)
        else:
            rejected.append({"ticker": ticker, "topic": event.get("topic"),
                             "kind": "swing", "book_move": move,
                             "reason": outcome.get("reason")})

    # --- level picks: price has drifted from its own recent average ------
    for ticker, event in by_ticker.items():
        point = new_points.get(ticker)
        trail = new_trails.get(ticker) or []
        if not point or len(trail) < 2:
            continue
        p_now = point["mid"]
        history_mids = trail[:-1]
        if not history_mids:
            continue
        p_ref = round(sum(history_mids) / len(history_mids), 4)
        if abs(p_now - p_ref) + 1e-9 < MIN_DRIFT:
            # A drift smaller than a cent is noise. Whether the model likes
            # the market is decided by the edge gate below, not by this
            # number.
            continue
        outcome = evaluate(event, p_ref, p_now, "level")
        if outcome.get("accepted"):
            outcome["book_move"] = round(p_now - p_ref, 4)
            picks.append(outcome)
        else:
            rejected.append({"ticker": ticker, "topic": event.get("topic"),
                             "kind": "level",
                             "book_move": round(p_now - p_ref, 4),
                             "reason": outcome.get("reason")})

    # --- the model's verdict on every market in the alert stream --------
    # The shortlist chat shows the picks first and then, so the trader can
    # see the model working, the verdict the model reached on each alert and
    # the reason it reached it. An empty chat would say nothing.
    for ticker, alert in latest_alert.items():
        event = by_ticker.get(ticker)
        if not event:
            continue
        point = new_points.get(ticker)
        prior = previous_points.get(ticker)
        p_now = point.get("mid") if point else None
        p_ref = prior.get("mid") if prior else None
        book_move = (round(p_now - p_ref, 4)
                     if p_now is not None and p_ref is not None else None)
        picked = next((p for p in picks if p.get("ticker") == ticker), None)
        if picked:
            verdict = {
                "verdict": "picked", "ticker": ticker,
                "topic": alert.get("topic"), "title": alert.get("title"),
                "side": picked["side"], "net_roi": picked["net_roi"],
                "executable_price": picked["executable_price"],
                "model_fair": picked["model_fair"], "edge": picked["edge"],
                "net_edge": picked["net_edge"], "fee": picked["fee"],
                "reason": picked.get("reason") or "passed every model gate",
                "kind": picked.get("kind"),
                "book_move": picked.get("book_move"),
            }
        else:
            if p_now is None or p_ref is None:
                reason = ("no order book on both sides in this snapshot, so the "
                          "model has nothing to price")
            elif abs(book_move) + 1e-9 < SWING_THRESHOLD:
                reason = (f"the book has not moved since the previous snapshot "
                          f"(mid {_usd(p_ref)} -> {_usd(p_now)}), so this move is a "
                          f"single trade print rather than a change in the market")
            else:
                match = next((r for r in rejected if r["ticker"] == ticker), None)
                reason = (match or {}).get("reason") or \
                    "no side passed the model's gates"
            verdict = {
                "verdict": "rejected", "ticker": ticker,
                "topic": alert.get("topic"), "title": alert.get("title"),
                "reason": reason, "book_move": book_move,
                "alert_delta": alert.get("delta"),
                "alert_direction": alert.get("direction"),
                "market_url": event.get("market_url"),
                "source_url": f"{API}/markets/{ticker}",
            }
        verdicts.append(verdict)
    verdicts.sort(key=lambda v: (0 if v["verdict"] == "picked" else 1,
                                  -(v.get("book_move") or 0)))

    # Swing picks come first, then the strongest level picks. A market can
    # qualify under both references (the trail mean and the previous point
    # can be the same number), so each market appears once.
    picks.sort(key=lambda r: (0 if r.get("kind") == "swing" else 1, -r["net_roi"]))
    seen_tickers: set[str] = set()
    unique_picks: list[dict[str, Any]] = []
    for pick in picks:
        ticker = pick.get("ticker")
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        unique_picks.append(pick)
    picks = unique_picks[:MAX_PICKS]

    summary: dict[str, int] = {}
    for row in rejected:
        key = row["reason"].split(" has only")[0].split(" leaves only")[0]
        key = key.split(" in this snapshot")[0].strip()
        summary[key] = summary.get(key, 0) + 1

    now = time.time()
    payload = {
        "generated_at": live.get("generated_at"),
        "generated_at_ts": now,
        "api_root": API,
        "threshold_dollars": SWING_THRESHOLD,
        "min_edge_dollars": MIN_EDGE,
        "max_spread_dollars": MAX_SPREAD,
        "min_depth_contracts": MIN_DEPTH_CONTRACTS,
        "trail_length": TRAIL_LEN,
        "model": ("fair = (book mid before the move + book mid now) / 2; the "
                  "model assumes half of a move is an overreaction. Edge is "
                  "measured against the executable price (YES ask, or 1 - YES "
                  "bid for NO) and Kalshi's published taker fee "
                  "0.07 * C * P * (1 - P) with the schedule's default "
                  "multiplier M = 1: this module works offline from the "
                  "snapshot, which carries no per-series fee_multiplier field "
                  "(the trading engine and the paper ledger read it from "
                  "GET /series; see the Flagged for Review page for the "
                  "PDF-vs-API disagreement this follows)."),
        "model_inputs": {
            "fair_value": "(previous book mid + current book mid) / 2",
            "yes_edge": "fair - implied YES ask",
            "no_edge": "YES bid - fair",
            "fee": "0.07 * C * P * (1 - P), Kalshi published taker fee",
            "reference": ("the order book only; both ends of every comparison "
                          "are book mids so a traded price is never compared "
                          "with a book quote"),
        },
        "picks": picks,
        "picks_count": len(picks),
        "swing_picks_count": sum(1 for p in picks if p.get("kind") == "swing"),
        "level_picks_count": sum(1 for p in picks if p.get("kind") == "level"),
        "verdicts": verdicts,
        "verdicts_count": len(verdicts),
        "rejected_count": len(rejected),
        "rejection_summary": sorted(
            ({"reason": k, "count": v} for k, v in summary.items()),
            key=lambda r: -r["count"]),
        "rejected_sample": sorted(
            rejected, key=lambda r: -abs(r.get("book_move") or 0))[:40],
        "alerts_seen": len(alerts),
        "markets_seen": len(by_ticker),
        "sources": {
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets",
            "orderbook": "https://docs.kalshi.com/getting_started/orderbook_responses",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
            "fees": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
        },
    }
    new_history = {
        "generated_at": live.get("generated_at"),
        "generated_at_ts": now,
        "points": new_points,
        "trail": new_trails,
    }
    return {"shortlist": payload, "history": new_history}


def main() -> None:
    result = build()
    _save(OUT_PATH, result["shortlist"])
    _save(HISTORY_PATH, result["history"])
    print(json.dumps({
        "picks": result["shortlist"]["picks_count"],
        "swing_picks": result["shortlist"]["swing_picks_count"],
        "rejected": result["shortlist"]["rejected_count"],
        "markets": result["shortlist"]["markets_seen"],
        "out": OUT_PATH,
    }, indent=1))


if __name__ == "__main__":
    main()
