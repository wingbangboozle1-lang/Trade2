"""Topic definitions for the five tracked subjects.

Everything here is derived from fields that the official Trade API actually returns
(`category`, `categories`, `tags`, `title`, `ticker`) — see `docs/verification/`.

Why matchers and not a hard-coded list of tickers: Kalshi rolls event series over
constantly (a golf tournament ends, the next one opens). A hard-coded list would go
stale within a day; a matcher keyed on the official metadata stays correct. Every
matcher is written so a reviewer can read the rule and check it by hand against
`/series?category=...`.

Matching rules (conservative by design, to avoid pulling in unrelated markets):
  * `categories_strict`  -> the category alone is enough (it is topic-specific).
  * `categories_broad`   -> the category only counts when a tag/title/ticker filter
                            also matches (e.g. Economics alone is NOT gas prices;
                            it also needs an energy tag or a "gas" word).
  * A series whose categories match neither set never belongs to the topic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    blurb: str
    categories_strict: Tuple[str, ...] = ()
    categories_broad: Tuple[str, ...] = ()
    tags_any: Tuple[str, ...] = ()
    title_regex: Optional[str] = None
    ticker_regex: Optional[str] = None

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
    ),
    Topic(
        key="culture",
        label="Culture",
        blurb="Entertainment, celebrity and internet-culture contracts. Settlement sources are the outlets "
        "named per series (e.g. Spotify for streaming counts, major wires for news-driven markets).",
        categories_strict=("Culture", "Entertainment", "Mentions"),
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
    ),
    Topic(
        key="golf",
        label="Golf",
        blurb="PGA/LPGA and DP World Tour contracts. Settlement sources are the governing league (pgatour.com) "
        "and ESPN/Fox Sports per the series metadata. Official rules: assets.kalshi.com/contract_terms/GOLF*.pdf",
        categories_strict=("Golf",),
        categories_broad=("Sports",),
        tags_any=("Golf",),
        title_regex=r"\bgolf\b|\bpga\b|\blpga\b|ryder cup|open championship|masters",
        # NB: plain "PGA" would match inside e.g. "KXATPGAME" (ATP tennis) — anchor it
        ticker_regex=r"GOLF|LPGA|PGATOUR|KXPGA",
    ),
]

TOPIC_BY_KEY: Dict[str, Topic] = {t.key: t for t in TOPICS}


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
