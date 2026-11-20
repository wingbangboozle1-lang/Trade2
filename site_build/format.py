"""Shared formatters and link builders for the root site.

Kept in its own module so ``build.py`` and ``extras.py`` can both use it
without importing each other.

Two rules are enforced here, because every table on the site depends on them:

1. A value that could not be read from the official API is never guessed.
   It renders as a blank cell with an ``UNVERIFIED`` badge, so a reviewer can
   see at a glance which numbers still need checking.
2. A whole number renders without a decimal tail. Open-interest *contracts*
   and *volume* keep their decimals (``189,529,515.91``) because the API
   publishes fractional contract counts, but a count of markets or trades
   renders as ``750``, never ``750.00``.
"""

from __future__ import annotations

import html
import urllib.parse
from decimal import Decimal, InvalidOperation
from typing import Any

API = "https://external-api.demo.kalshi.co/trade-api/v2"

#: Kalshi's own event page carries a live news feed for the event, so it is
#: the honest place to look for something that may have moved the price.
#: https://kalshi.com/markets/<series>/<ticker> redirects to it.
KALSHI_SITE = "https://kalshi.com"


def esc(value: Any) -> str:
    """Escape a value, or mark it unverified when it is missing."""
    if value is None or value == "":
        return '<span class="flag-badge">UNVERIFIED</span>'
    return html.escape(str(value))


def money(value: Any, places: int = 2) -> str:
    if value is None or value == "":
        return '<span class="flag-badge">UNVERIFIED</span>'
    try:
        return f"${float(value):,.{places}f}"
    except (TypeError, ValueError):
        return esc(value)


def cents(value: Any) -> str:
    """A contract price in dollars, to the cent."""
    if value is None or value == "":
        return '<span class="flag-badge">UNVERIFIED</span>'
    try:
        return f"${float(value):.4f}"
    except (TypeError, ValueError):
        return esc(value)


def num(value: Any) -> str:
    """A quantity that may legitimately carry decimals (contracts, volume).

    A missing value is flagged, never left blank: rule 1 of this module promises
    an ``UNVERIFIED`` badge, and an empty cell in a price table is
    indistinguishable from a legitimate zero.
    """
    if value is None or value == "":
        return esc(value)
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return esc(value)


def count(value: Any) -> str:
    """Format counts exactly without rounding away unexpected fractions.

    Integral values render with thousands separators and no decimal tail.
    Non-integral values retain the existing two-decimal formatting. Contract
    quantities, prices, and money continue to use their separate formatters.
    """
    if value is None or value == "":
        # Blank, on purpose — unlike num(). A missing *count* is a KPI tile with
        # nothing to report yet (observation_count, open_positions,
        # resolutions_count), pinned by tests/test_site_build.py as merged in
        # PR #25; a missing *quantity* is an API read that failed and must show
        # the badge. If these should agree, change the test and this line together.
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return esc(value)
    if not number.is_finite():
        return esc(value)
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return num(value)


def pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return esc(value)


def result_chip(result: Any) -> str:
    """YES/NO chip for an official settlement result."""
    r = (result or "").strip().lower()
    if r == "yes":
        return '<span class="tag tag-yes">YES</span>'
    if r == "no":
        return '<span class="tag tag-no">NO</span>'
    return '<span class="flag-badge">UNVERIFIED</span>'


def series_prefix(ticker: Any) -> str:
    """The series ticker that prefixes every market ticker.

    Kalshi market tickers are ``<SERIES>-<...>`` (for example
    ``KXPRESNOMD-28-RW`` belongs to series ``KXPRESNOMD``). The market
    objects returned by ``GET /markets`` carry no ``series_ticker`` field, so
    the prefix is the documented way to recover the series. Used only as a
    fallback when the API does supply ``series_ticker`` directly.
    """
    text = str(ticker or "")
    return text.split("-")[0] if "-" in text else text


def kalshi_market_url(ticker: Any, series_ticker: Any = None,
                      event_ticker: Any = None) -> str:
    """Public Kalshi page for a market.

    ``https://kalshi.com/markets/<series>/<ticker>`` redirects to the event
    page, which carries the live order ticket and Kalshi's own news feed for
    that event.
    """
    series = series_ticker or series_prefix(ticker)
    return f"{KALSHI_SITE}/markets/{series}/{ticker}"


def kalshi_event_url(event_ticker: Any, series_ticker: Any = None) -> str:
    """Public Kalshi page for an event (the whole ticket, with its news feed)."""
    series = series_ticker or series_prefix(event_ticker)
    return f"{KALSHI_SITE}/markets/{series}/{event_ticker}"


def safe_url(value: Any) -> str:
    """Return an http(s) URL, or "" for anything else.

    Every external href on the site is either built by us from a ticker or read
    out of a payload the collector wrote — and one field of that payload (a news
    headline link) is supplied by a third party. A renderer that trusts it can be
    handed ``javascript:`` or ``data:`` and turn a headline into a click handler,
    so the scheme is checked here, once, for both renderers to share.
    """
    text = str(value or "").strip()
    if text.lower().startswith(("https://", "http://")):
        return html.escape(text, quote=True)
    return ""


def news_search_url(text: Any, topic_label: Any = "") -> str:
    """A news search for an event — a place to look for a possible cause.

    This is a *search*, deliberately: the dashboard never asserts that any
    article caused a move. The link points at Google News' RSS search, the
    same source the repo's other collector already uses
    (``collector/news.py``).
    """
    query = " ".join(str(x) for x in (text, topic_label) if x)
    query = query.strip() or "Kalshi"
    return ("https://news.google.com/rss/search?q="
            + urllib.parse.quote(query)
            + "&hl=en-US&gl=US&ceid=US:en")


def api_market_url(ticker: Any) -> str:
    """The exact REST response a market row came from."""
    return f"{API}/markets/{ticker}"


def api_event_url(event_ticker: Any) -> str:
    return f"{API}/events/{event_ticker}"


def api_series_url(ticker: Any) -> str:
    return f"{API}/series/{ticker}"
