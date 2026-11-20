"""Topic registry + discovery for the five in-scope topics.

Verification policy for this file
---------------------------------
Nothing here is guessed. Each topic declares:

* the Kalshi ``category`` / ``tags`` values used to query ``GET /series``
  (official endpoint: https://docs.kalshi.com/api-reference/market/get-series-list)
* explicit keyword/allow-list rules applied to the returned series metadata
* the ``source_url`` that a human can open to confirm the same result

``resolve_series()`` re-derives the series list live from the API on every run,
so the registry can never drift from Kalshi without the snapshot showing it.

Scope (per the project brief): gas prices, elections, culture, crypto, golf.
Anything outside those five is deliberately excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

API_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"


@dataclass(frozen=True)
class Topic:
    slug: str
    label: str
    # (category, tags) pairs passed straight to GET /series
    queries: tuple[tuple[str, str | None], ...]
    # series is in scope when any matcher returns True for (ticker, title)
    matchers: tuple[Callable[[str, str], bool], ...]
    include_tickers: tuple[str, ...] = ()
    exclude_tickers: tuple[str, ...] = ()
    notes: str = ""
    series_pages: int = 4          # pages of 100-ish series to walk per query
    _cache: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def source_url(self) -> str:
        first = self.queries[0]
        if first[1]:
            return f"{API_ROOT}/series?category={first[0]}&tags={first[1]}"
        return f"{API_ROOT}/series?category={first[0]}"


def _kw(*words: str) -> Callable[[str, str], bool]:
    """Substring matcher over ticker + title, case-insensitive, word-boundary safe."""
    pats = [re.compile(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", re.I)
            for w in words]
    def _match(ticker: str, title: str) -> bool:
        hay = f"{ticker} {title}"
        return any(p.search(hay) for p in pats)
    return _match


def _ticker_prefix(*prefixes: str) -> Callable[[str, str], bool]:
    def _match(ticker: str, title: str) -> bool:
        return any(ticker.upper().startswith(p) for p in prefixes)
    return _match


# --- Gas prices ---------------------------------------------------------
# Verified: GET /series/KXAAAGASD returns category "Economics" with
# settlement_sources [{"name": "AAA", "url": "https://gasprices.aaa.com/"}].
# GET /series?category=Commodities lists statewide AAA gasoline series such as
# KXAAAGASDCT (Connecticut) and KXAAAGASCDWA (Washington).
GAS = Topic(
    slug="gas-prices",
    label="Gas Prices",
    queries=(("Economics", None), ("Commodities", None)),
    matchers=(_kw("gas", "gasoline", "AAA", "pump"), _ticker_prefix("KXAAAGAS")),
    notes="US and state average retail gasoline prices, settled against AAA "
          "(https://gasprices.aaa.com/).",
)

# --- Elections ----------------------------------------------------------
ELECTIONS = Topic(
    slug="elections",
    label="Elections",
    queries=(("Elections", None),),
    series_pages=8,   # Elections is by far the largest category (~1,450 series)
    matchers=(_kw("election", "electoral", "vote", "ballot", "primary",
                  "nominee", "nomination", "mayor", "governor", "senate",
                  "congress", "president", "parliament"),),
    notes="Electoral outcomes, nominations and control-of-chamber markets.",
)

# --- Culture ------------------------------------------------------------
# Verified against the live demo API: GET /events?status=open shows Culture
# content published mostly under the "Entertainment" category (413 open events)
# and "Culture" itself (2 series). Both are queried so the topic is complete.
CULTURE = Topic(
    slug="culture",
    label="Culture",
    queries=(("Culture", None), ("Entertainment", None)),
    matchers=(_kw("culture", "celebrity", "emmy", "oscar", "grammy", "award",
                  "album", "movie", "film", "box office", "song", "series",
                  "tv", "netflix", "billboard", "time person", "nobel",
                  "ballon d'or", "viral", "tweet", "x post", "banned"),),
    notes="Entertainment, celebrity and internet-culture markets. Kalshi files "
          "most of these under the Entertainment category; the Culture category "
          "is queried as well.",
)

# --- Crypto -------------------------------------------------------------
CRYPTO = Topic(
    slug="crypto",
    label="Crypto",
    queries=(("Crypto", None),),
    matchers=(_kw("bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp",
                  "doge", "crypto", "satoshi", "stablecoin", "altcoin"),),
    notes="Digital-asset price and event markets, settled against CF Benchmarks "
          "(https://www.cfbenchmarks.com/).",
)

# --- Golf ---------------------------------------------------------------
GOLF = Topic(
    slug="golf",
    label="Golf",
    queries=(("Sports", "Golf"),),
    matchers=(_kw("golf", "PGA", "LPGA", "DP World", "Ryder Cup", "Masters",
                  "Open Championship", "birdie", "eagle", "hole", "clubhouse"),
              _ticker_prefix("KXPG", "KXGOLF", "KXDPWORLD", "KXRYDER")),
    notes="Professional golf markets; settlement sources per series are ESPN, "
          "Fox Sports and pgatour.com.",
)

TOPICS: tuple[Topic, ...] = (GAS, ELECTIONS, CULTURE, CRYPTO, GOLF)
TOPIC_BY_SLUG = {t.slug: t for t in TOPICS}


def resolve_series(client, topic: Topic) -> list[dict[str, Any]]:
    """Return the in-scope series for ``topic``, straight from GET /series."""
    seen: dict[str, dict[str, Any]] = {}
    for category, tags in topic.queries:
        for series in client.series_list(category=category, tags=tags,
                                         max_pages=topic.series_pages):
            ticker = series.get("ticker")
            if not ticker or ticker in seen:
                continue
            title = series.get("title") or ""
            in_scope = ticker in topic.include_tickers
            if not in_scope:
                in_scope = any(m(ticker, title) for m in topic.matchers)
            if ticker in topic.exclude_tickers:
                in_scope = False
            if in_scope:
                seen[ticker] = {
                    "ticker": ticker,
                    "title": title,
                    "category": series.get("category"),
                    "categories": series.get("categories") or [],
                    "tags": series.get("tags") or [],
                    "frequency": series.get("frequency"),
                    "fee_type": series.get("fee_type"),
                    "fee_multiplier": series.get("fee_multiplier"),
                    "settlement_sources": series.get("settlement_sources") or [],
                    "contract_terms_url": series.get("contract_terms_url"),
                    "contract_url": series.get("contract_url"),
                    "exchange_index": series.get("exchange_index"),
                    "volume_fp": series.get("volume_fp"),
                    "topic": topic.slug,
                    "source_url": f"{API_ROOT}/series/{ticker}",
                }
    return sorted(seen.values(), key=lambda s: s["ticker"])


def all_series(client) -> dict[str, list[dict[str, Any]]]:
    return {t.slug: resolve_series(client, t) for t in TOPICS}
