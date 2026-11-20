"""Topic registry for the five tracked subjects — shared by both pipelines.

Two consumers share this module (see COORDINATION.md, PR #11 integration log):

* **session arena-c0205283** (`collector.runner`, `trading.engine`, the
  `docs/` site): ``Topic.matches()``, ``TOPICS``, ``TOPIC_BY_KEY``,
  ``topic_for_series()``, ``classify_market()``.
* **session arena-f5837994** (`collector.collector`, `collector.discover`):
  ``Topic.queries`` / ``Topic.matchers``, ``resolve_series()``,
  ``cached_series()``, ``all_series()``, ``TOPIC_BY_SLUG``.

Nothing here is guessed. Everything is derived from fields the official Trade
API actually returns (`category`, `categories`, `tags`, `title`, `ticker`) —
see `docs/verification/` and `VERIFICATION.md`.

Why matchers and not a hard-coded list of tickers: Kalshi rolls event series
over constantly (a golf tournament ends, the next one opens). A hard-coded list
would go stale within a day; a matcher keyed on the official metadata stays
correct. Every matcher is written so a reviewer can read the rule and check it
by hand against `GET /series?category=...`
(https://docs.kalshi.com/api-reference/market/get-series-list).

Matching rules used by ``Topic.matches()`` (conservative by design):
  * `categories_strict`  -> the category alone is enough (it is topic-specific).
  * `categories_broad`   -> the category only counts when a tag/title/ticker
                            filter also matches (e.g. Economics alone is NOT
                            gas prices; it also needs a "gas" word).
  * A series whose categories match neither set never belongs to the topic.

The ``queries``/``matchers`` pair (session f5837994) narrows with an official
category+tags query first, then applies keyword matchers to that candidate
set; both systems are kept verbatim and are covered by their own test suites.

Scope (per the project brief): gas prices, elections, culture, crypto, golf.
Anything outside those five is deliberately excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

API_ROOT = "https://external-api.demo.kalshi.co/trade-api/v2"


@dataclass(frozen=True)
class Topic:
    # --- shared identity (both pipelines use the same value for either name) ---
    key: str
    label: str

    # --- session arena-c0205283 matcher fields (Topic.matches) ---
    blurb: str = ""
    categories_strict: Tuple[str, ...] = ()
    categories_broad: Tuple[str, ...] = ()
    tags_any: Tuple[str, ...] = ()
    title_regex: Optional[str] = None
    ticker_regex: Optional[str] = None

    # --- session arena-f5837994 discovery fields (resolve_series) ---
    queries: Tuple[Tuple[str, Optional[str]], ...] = ()
    matchers: Tuple[Callable[[str, str], bool], ...] = ()
    include_tickers: Tuple[str, ...] = ()
    exclude_tickers: Tuple[str, ...] = ()
    notes: str = ""
    series_pages: int = 4          # pages of ~100 series to walk per query
    event_series_scan: int = 40    # series to ask /events about per run
    _cache: Dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def slug(self) -> str:
        """Alias used by session arena-f5837994 (same value as ``key``)."""
        return self.key

    @property
    def source_url(self) -> str:
        """Official URL a human can open to confirm this topic's query."""
        if self.queries:
            first = self.queries[0]
            if first[1]:
                return f"{API_ROOT}/series?category={first[0]}&tags={first[1]}"
            return f"{API_ROOT}/series?category={first[0]}"
        cats = self.categories_strict or self.categories_broad
        if cats:
            return f"{API_ROOT}/series?category={cats[0]}"
        return f"{API_ROOT}/series"

    def matches(self, series: Dict) -> bool:
        cats = {str(c).strip().lower() for c in (series.get("categories") or []) if c}
        cat = str(series.get("category") or "").strip().lower()
        if cat:
            cats.add(cat)

        strict = {c.lower() for c in self.categories_strict}
        broad = {c.lower() for c in self.categories_broad}
        if cats & strict:
            return True
        if cats & broad:
            return self._secondary_match(series)
        return False

    def _secondary_match(self, series: Dict) -> bool:
        tags = {str(t).strip().lower() for t in (series.get("tags") or []) if t}
        title = str(series.get("title") or "")
        ticker = str(series.get("ticker") or "")
        if self.tags_any and (tags & {t.lower() for t in self.tags_any}):
            return True
        if self.title_regex and re.search(self.title_regex, title, re.I):
            return True
        if self.ticker_regex and re.search(self.ticker_regex, ticker, re.I):
            return True
        return False


# --- keyword / ticker-prefix helpers (session arena-f5837994, verbatim) ---

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


# --- The five topics (both matcher systems carried on each instance) --------

TOPICS: List[Topic] = [
    Topic(
        key="gas-prices",
        label="Gas prices",
        blurb="Retail gasoline, CPI-gas and energy-price contracts. Settlement sources are AAA and the "
        "U.S. Energy Information Administration. Official rules: assets.kalshi.com/contract_terms/AAAGAS*.pdf",
        categories_broad=("Economics", "Commodities", "Climate and Weather"),
        # only gas-specific tags: the broad "Oil and energy" tag pulls in power/oil
        # series (e.g. ERCOT peak power) that are not gas prices
        tags_any=("gas",),
        title_regex=r"\bgas(oline)?\b|pump price|fuel price|petrol",
        ticker_regex=r"GAS",
        # discovery query set (f5837994): category+tags GET /series, then keywords
        queries=(("Economics", None), ("Commodities", None)),
        matchers=(_kw("gas", "gasoline", "AAA", "pump"), _ticker_prefix("KXAAAGAS")),
        notes="US and state average retail gasoline prices, settled against AAA "
        "(https://gasprices.aaa.com/).",
    ),
    Topic(
        key="elections",
        label="Elections",
        blurb="Federal, state and international election contracts. Settlement sources are the responsible "
        "election authority named in each series (e.g. a state secretary of state or foreign electoral body).",
        categories_strict=("Elections",),
        categories_broad=("Politics",),
        tags_any=("Election", "Elections", "International elections", "US elections"),
        title_regex=r"\belection\b|\bprimary\b|\bcaucus\b|mayoral|ballot",
        ticker_regex=r"MAYOR|GOVERNOR",
        queries=(("Elections", None),),
        matchers=(_kw("election", "electoral", "vote", "ballot", "primary",
                      "nominee", "nomination", "mayor", "governor", "senate",
                      "congress", "president", "parliament"),),
        series_pages=8,
        event_series_scan=30,   # Elections is by far the largest category
        notes="Electoral outcomes, nominations and control-of-chamber markets.",
    ),
    Topic(
        key="culture",
        label="Culture",
        blurb="Entertainment, celebrity and internet-culture contracts. Settlement sources are the outlets "
        "named per series (e.g. Spotify for streaming counts, major wires for news-driven markets).",
        categories_strict=("Culture", "Entertainment", "Mentions"),
        queries=(("Culture", None), ("Entertainment", None)),
        # Deliberately strict. Kalshi files awards shows, streaming and celebrity
        # content under "Entertainment", but that category also carries ordinary
        # TV/sports programming; a loose matcher pulled in 963 unrelated series in
        # testing (f5837994). Only these marker words qualify a series.
        matchers=(_kw("culture", "celebrity", "emmy", "oscars", "academy award",
                      "grammy", "golden globe", "billboard", "box office",
                      "time person of the year", "nobel", "ballon d'or",
                      "netflix", "album", "movie", "film", "song", "banned from x",
                      "tweet", "viral", "best actor", "best actress",
                      "song of the year", "record of the year"),),
        notes="Entertainment, celebrity and internet-culture markets. Kalshi files "
        "most of these under the Entertainment category; the Culture category "
        "is queried as well.",
    ),
    Topic(
        key="crypto",
        label="Crypto",
        blurb="Bitcoin, Ethereum, Solana and other digital-asset price contracts. Settlement source is "
        "CF Benchmarks (BRTI and related indices) per the series metadata.",
        categories_strict=("Crypto",),
        categories_broad=("Financials",),
        tags_any=("Crypto", "Bitcoin", "BTC", "Solana", "Ethereum"),
        title_regex=r"\bbitcoin\b|\bbtc\b|\beth(ereum)?\b|\bsol(ana)?\b|\bcrypto\b|\bxrp\b|\bdogecoin\b",
        ticker_regex=r"BTC|ETH|SOL|XRP|DOGE|CRYPTO|HYPE",
        queries=(("Crypto", None),),
        matchers=(_kw("bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp",
                      "doge", "crypto", "satoshi", "stablecoin", "altcoin"),),
        notes="Digital-asset price and event markets, settled against CF Benchmarks "
        "(https://www.cfbenchmarks.com/).",
    ),
    Topic(
        key="golf",
        label="Golf",
        blurb="PGA/LPGA and DP World Tour contracts. Settlement sources are the governing league (pgatour.com) "
        "and ESPN/Fox Sports per the series metadata. Official rules: assets.kalshi.com/contract_terms/GOLF*.pdf",
        categories_strict=("Golf",),
        categories_broad=("Sports",),
        tags_any=("Golf",),
        # NB (c0205283): no bare "masters" — it matches tennis (ATP Monte-Carlo
        # Masters); plain "PGA" would match inside "KXATPGAME" — anchor it.
        title_regex=r"\bgolf\b|\bpga\b|\blpga\b|ryder cup|presidents cup|open championship",
        ticker_regex=r"GOLF|LPGA|PGATOUR|KXPGA|MASTERS",
        # discovery query narrows to the official Golf tag first (f5837994), so
        # its broader keyword list only ever sees Golf-tagged candidates
        queries=(("Sports", "Golf"),),
        matchers=(_kw("golf", "PGA", "LPGA", "DP World", "Ryder Cup", "Masters",
                      "Open Championship", "birdie", "eagle", "hole", "clubhouse"),
                  _ticker_prefix("KXPG", "KXGOLF", "KXDPWORLD", "KXRYDER")),
        notes="Professional golf markets; settlement sources per series are ESPN, "
        "Fox Sports and pgatour.com.",
    ),
]

TOPIC_BY_KEY: Dict[str, Topic] = {t.key: t for t in TOPICS}
TOPIC_BY_SLUG: Dict[str, Topic] = {t.slug: t for t in TOPICS}


# --- session arena-c0205283 helpers (verbatim) ------------------------------

def topic_for_series(series: Dict) -> Optional[str]:
    for topic in TOPICS:
        if topic.matches(series):
            return topic.key
    return None


def classify_market(market: Dict, series_topic: Dict[str, str]) -> Optional[str]:
    """Markets inherit the topic of their series; demo BTC markets fall back to crypto."""
    series_ticker = str(market.get("series_ticker") or "")
    if series_ticker and series_ticker in series_topic:
        return series_topic[series_ticker]
    ticker = str(market.get("ticker") or "")
    base = ticker.split("-")[0]
    if base in series_topic:
        return series_topic[base]
    # last resort: the market's own ticker/title, using the same public matchers
    for topic in TOPICS:
        if topic.ticker_regex and re.search(topic.ticker_regex, ticker, re.I):
            return topic.key
        if topic.title_regex and re.search(topic.title_regex, str(market.get("title") or ""), re.I):
            return topic.key
    return None


# --- session arena-f5837994 discovery functions (verbatim) -----------------

def resolve_series(client, topic: Topic) -> List[Dict[str, Any]]:
    """Return the in-scope series for ``topic``, straight from GET /series."""
    seen: Dict[str, Dict[str, Any]] = {}
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


def cached_series(client, topic: "Topic", cache: Dict[str, Any],
                  max_age_seconds: float = 6 * 3600) -> List[Dict[str, Any]]:
    """resolve_series() with an on-disk cache.

    Series metadata (title, category, settlement sources, fee type) changes on
    the order of days, so walking every page on every 5-minute run is wasted
    time that starves the alerting work. The cache is keyed by topic and
    re-resolved when older than ``max_age_seconds``. The snapshot records
    whether the series list came from cache or a fresh walk, so nothing is
    passed off as freshly verified when it is not.
    """
    import time as _time

    entry = cache.get(topic.slug) or {}
    fresh = (_time.time() - float(entry.get("resolved_at") or 0)) < max_age_seconds
    if fresh and entry.get("series"):
        rows = entry["series"]
        for row in rows:
            row.setdefault("topic", topic.slug)
            row.setdefault("source_url", f"{API_ROOT}/series/{row.get('ticker')}")
        return rows
    rows = resolve_series(client, topic)
    cache[topic.slug] = {"resolved_at": _time.time(), "series": rows}
    return rows


def all_series(client) -> Dict[str, List[Dict[str, Any]]]:
    return {t.slug: resolve_series(client, t) for t in TOPICS}
