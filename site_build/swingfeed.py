"""Fold the candlestick swing feed into the all-events chat.

Why this module exists
----------------------
The root snapshot (``data/live.json``) measures a swing between two *order-book
midpoints*: the book now and the completed 1-minute candle's quote close. That is
the strictest basis available — it is the only one where a trader could actually
have transacted — and its guard deliberately discards an empty
``0.0000 bid / 1.0000 ask`` book so a phantom $0.50 mid can never fire an alert.

The cost of that guard is visible on a quiet demo book: ``data/live.json``
published ``alert_stats.fired_this_run: 0`` for the 2026-11-21T06:28:00Z run
while the ``docs/`` collector, which measures the swing between the *official
candlestick closes* Kalshi publishes for the same market, published 6 moves of
≥ $0.10 in the same half hour. A reader of the landing page therefore saw
"Swings ≥ $0.10: 0" next to a populated, sourced alert history — two views of
one exchange disagreeing, which is worse for a trader than either alone.

This module merges them, honestly:

* every merged row keeps the basis it was measured on and is labelled
  ``quality = "candle-close"`` — Kalshi's own published close-to-close step, not
  a transactable mid;
* merged rows are added to the **all-events** feed only. The model / high-ROI
  chat keeps its executability gate untouched, because a historical close says
  nothing about the price you could trade now;
* nothing is invented: each row carries the market URL it came from and the
  candlestick URL that produced its two numbers, and rows older than
  ``max_age_hours`` are dropped rather than shown as "live".

Data sources (official):
  * https://docs.kalshi.com/api-reference/market/get-market-candlesticks
  * https://docs.kalshi.com/api-reference/market/get-market
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: The brief's alert threshold, in dollars.
THRESHOLD_DOLLARS = 0.10

#: A candle row older than this is stale, not live; it is dropped and counted.
DEFAULT_MAX_AGE_HOURS = 24.0

#: Basis label used on the chat row and understood by ``alert_chat_row``.
CANDLE_QUALITY = "candle-close"


def _iso_to_ts(value: Any) -> float | None:
    """Epoch seconds from an ISO-8601 stamp, or None when it is absent."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def _close(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _headline(item: Any) -> dict[str, Any] | None:
    """Normalise one docs-pipeline headline into the chat row's ``news`` shape.

    ``collector/news.py`` only ever attaches a headline it actually fetched, so
    a URL here means "this article was published in the window", never "this
    article caused the move". The chat row prints that caveat itself.
    """
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    if not url or not title:
        return None
    return {
        "url": url,
        "title": title,
        "source": str(item.get("source") or "").strip(),
        "published": str(item.get("published") or "").strip(),
        "status": str(item.get("status") or "").strip(),
    }


def candle_alerts(payload: Any, *, threshold: float = THRESHOLD_DOLLARS,
                  max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
                  now_ts: float | None = None,
                  tickers: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project ``docs/data/alerts.json`` into chat rows.

    Returns ``(rows, stats)``. ``rows`` use the same field names as the live
    snapshot's alerts (``abs_delta``, ``previous``, ``current``, ``iso``,
    ``quality``) so ``alert_chat_row`` renders both kinds from one function.
    A row that fails any check is counted in ``stats`` and dropped — never
    silently repaired.
    """
    stats = {"read": 0, "kept": 0, "below-threshold": 0, "too-old": 0,
             "unknown-ticker": 0, "malformed": 0}
    if not isinstance(payload, dict):
        return [], stats
    items = payload.get("alerts")
    if not isinstance(items, list):
        return [], stats

    limit = max(0.0, float(max_age_hours)) * 3600.0
    now = float(now_ts) if now_ts is not None else datetime.now(timezone.utc).timestamp()
    rows: list[dict[str, Any]] = []

    for item in items:
        stats["read"] += 1
        if not isinstance(item, dict):
            stats["malformed"] += 1
            continue
        ticker = str(item.get("ticker") or "").strip()
        delta = _close(item.get("delta"))
        frm = _close(item.get("from"))
        to = _close(item.get("to"))
        if not ticker or delta is None or frm is None or to is None:
            stats["malformed"] += 1
            continue
        if tickers is not None and ticker not in tickers:
            # Not a market this site tracks — dropping it keeps the feed scoped
            # to the five topics in the brief instead of widening it silently.
            stats["unknown-ticker"] += 1
            continue
        if abs(delta) + 1e-9 < float(threshold):
            stats["below-threshold"] += 1
            continue
        when = item.get("t") if isinstance(item.get("t"), (int, float)) else _iso_to_ts(item.get("t_iso"))
        if when is None:
            stats["malformed"] += 1
            continue
        if now - float(when) > limit:
            stats["too-old"] += 1
            continue

        headlines = [h for h in (_headline(x) for x in (item.get("headlines") or [])) if h]
        rows.append({
            "ticker": ticker,
            "event_ticker": str(item.get("event_ticker") or ""),
            "series_ticker": str(item.get("series_ticker") or ""),
            "topic": item.get("topic"),
            "title": item.get("title") or ticker,
            "abs_delta": round(abs(delta), 4),
            "signed_delta": round(delta, 4),
            "direction": "up" if delta > 0 else "down",
            "previous": frm,
            "current": to,
            "ts": float(when),
            "iso": item.get("t_iso") or datetime.fromtimestamp(float(when), tz=timezone.utc).isoformat(),
            "threshold": float(threshold),
            "quality": CANDLE_QUALITY,
            "quality_reason": (
                "measured between two consecutive closes of the official Kalshi "
                "candlestick series for this market (chart window: "
                f"{item.get('window') or 'unspecified'}), not between two live "
                "order-book mids — the linked candlestick URL holds both numbers"
            ),
            "reference_basis": "candlestick close → candlestick close",
            "basis": CANDLE_QUALITY,
            "window": item.get("window"),
            "spread": None,
            "size_at_top": None,
            "news": headlines,
            "news_status": item.get("news_status") or "no news lookup recorded for this row",
            # The two URLs this row rests on: the market record, and the
            # candlestick series the two numbers were read from.
            "source_url": item.get("source_url"),
            "candle_source_url": item.get("candle_source_url"),
            "docs_url": item.get("docs_url"),
        })
        stats["kept"] += 1

    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows, stats


def _is_duplicate(row: dict[str, Any], live_alerts: list[dict[str, Any]]) -> bool:
    """True when the live feed already carries this exact observed step.

    "Exact" means same ticker, same direction, and ``abs_delta`` within one
    cent. Anything else is a different measurement of the same market and is
    shown as its own row, labelled with its basis — the two bases answer
    different questions and folding them would hide that.
    """
    for a in live_alerts:
        if a.get("ticker") != row["ticker"]:
            continue
        if str(a.get("direction") or "") != row["direction"]:
            continue
        a_delta = _close(a.get("abs_delta"))
        if a_delta is not None and abs(a_delta - row["abs_delta"]) <= 0.01:
            return True
    return False


def attach(live: dict[str, Any], docs_payload: Any, *,
            threshold: float = THRESHOLD_DOLLARS,
            max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
            now_ts: float | None = None) -> dict[str, Any]:
    """Annotate the live snapshot with the candle-close feed, in place.

    ``live["candle_alerts"]`` is what the all-events chat adds; the model /
    high-ROI chat is left alone on purpose. ``live["candle_feed_stats"]`` says
    where the rows came from and what was dropped, so the site can print the
    provenance instead of asserting the two feeds agree.
    """
    tracked = {str(e.get("ticker")) for e in (live.get("events") or [])
               if isinstance(e, dict) and e.get("ticker")}
    rows, stats = candle_alerts(docs_payload, threshold=threshold,
                                max_age_hours=max_age_hours, now_ts=now_ts,
                                tickers=tracked or None)
    kept = [r for r in rows if not _is_duplicate(r, live.get("alerts") or [])]
    stats["duplicates_dropped"] = len(rows) - len(kept)
    stats["added"] = len(kept)
    stats["threshold"] = float(threshold)
    if isinstance(docs_payload, dict):
        stats["source_generated_at"] = docs_payload.get("generated_at")
        stats["source_path"] = "docs/data/alerts.json"
    live["candle_alerts"] = kept
    live["candle_feed_stats"] = stats
    return stats

