"""Best-effort headline lookup for >= $0.10 price swings.

Uses Google News RSS (public, no API key) to find headlines published near a swing.
IMPORTANT: a headline is only a *candidate* catalyst — temporal proximity is not
causation, and nothing here is presented as a confirmed cause. If the lookup fails
(for example in an offline environment) the link fields stay blank and the item is
flagged as unverified, per the project verification rule.

Sandbox note: this runner executes on GitHub Actions runners, which have full
network egress; the dev sandbox cannot reach news.google.com, so the code degrades
to empty results rather than raising.

Why three states, not two
-------------------------
"we looked and found nothing" and "we could not look" are different facts, and
publishing a blank for both would silently misrepresent the first as the second.
``lookup()`` therefore returns an explicit ``status``:

    ok                  items were parsed from the feed
    no-headlines-found  the feed answered, nothing was published in the window
    unavailable         the request or the parse failed (offline sandbox, 429, …)

The caller records the status on the alert row and the site renders the difference.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

USER_AGENT = "Trade2-collector/1.0 (+https://github.com/wingbangboozle1-lang/Trade2)"
RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

Fetcher = Callable[[str, float], bytes]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _download(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# Words that appear in every Kalshi market title ("Will average gas prices be
# above $4.2000?") and carry nothing a news search can use. Only function words
# are listed: nouns and verbs that could be an entity ("gas", "price", "turnout",
# "above") are left alone, so the query never loses the subject of the market.
_STOPWORDS = {
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "be", "been", "being", "is", "are", "was", "were", "am", "do", "does", "did",
    "have", "has", "had", "the", "a", "an", "and", "or", "of", "to", "in", "on",
    "for", "with", "at", "by", "from", "as", "it", "its", "this", "that", "these",
    "those", "than", "then", "there", "here", "what", "when", "where", "which",
    "who", "whom", "why", "how", "if", "not", "any", "all", "each", "per",
}


def query_for(title: str, ticker: str = "", max_words: int = 6) -> str:
    """A search query built only from words the market's own title contains.

    Kalshi market titles are template text, so markdown, pure numerals and
    function words are dropped. No entity is ever named that the title does not
    name; if nothing is left, the caller falls back to the ticker itself.
    """
    if title and re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Za-z0-9.$]+)+", title.strip()):
        return title.strip()          # the title *is* a ticker: search it verbatim
    words = [w for w in re.split(r"[^A-Za-z0-9$]+", _strip_html(title or ""))
             if len(w) > 2 and not re.fullmatch(r"[\d$.,]+", w)
             and w.lower() not in _STOPWORDS]
    return " ".join(words[:max_words]) if words else (ticker or "")



def parse_feed(payload: bytes, when: datetime, window_hours: int = 6,
               max_items: int = 5) -> List[Dict]:
    """Parse RSS bytes into headline rows inside the window. Pure, testable."""
    try:
        root = ET.fromstring(payload)
    except Exception:
        return []
    lo = when - timedelta(hours=window_hours)
    hi = when + timedelta(hours=window_hours)
    out: List[Dict] = []
    for item in root.iter("item"):
        title = _strip_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        source = _strip_html(item.findtext("source") or "")
        published = _parse_date(item.findtext("pubDate") or "")
        if not title or not link:
            continue
        if published is not None and not (lo <= published <= hi):
            continue
        out.append(
            {
                "title": title,
                "url": link,
                "source": source or None,
                "published": published.isoformat() if published else None,
                # A row with a pubDate inside the window is time-verified against
                # the feed itself; anything else stays explicitly unverified.
                "status": "verified-fetch" if published else "unverified-time",
            }
        )
        if len(out) >= max_items:
            break
    return out


def lookup(
    title: str,
    when: datetime,
    window_hours: int = 6,
    max_items: int = 5,
    timeout: float = 6.0,
    fetcher: Optional[Fetcher] = None,
    ticker: str = "",
) -> Dict:
    """Candidate headlines near `when`, with an explicit outcome state.

    ``fetcher`` exists so tests can feed in a canned RSS document; production
    callers pass nothing and get the network path.
    """
    query = query_for(title, ticker)
    if not query:
        return {"query": "", "items": [], "status": "no-query",
                "error": "market title carries no searchable words"}
    url = RSS.format(q=urllib.parse.quote(query))
    try:
        payload = (fetcher or _download)(url, timeout)
    except Exception as exc:  # network blocked -> blank links + flagged, never a guess
        return {"query": query, "url": url, "items": [], "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}"}
    items = parse_feed(payload, when, window_hours=window_hours, max_items=max_items)
    return {"query": query, "url": url, "items": items,
            "status": "ok" if items else "no-headlines-found", "error": None}


def headlines_near(
    query: str,
    when: datetime,
    window_hours: int = 6,
    max_items: int = 5,
    timeout: float = 6.0,
) -> List[Dict]:
    """Return RSS headlines for `query` published within +/- window_hours of `when`.

    Kept for existing callers (``collector/runner.py``): the list-only shape, with
    an empty list whenever the lookup could not be completed.
    """
    if not query:
        return []
    url = RSS.format(q=urllib.parse.quote(query))
    try:
        payload = _download(url, timeout)
    except Exception:
        return []  # network blocked -> caller leaves links blank + flags unverified
    return parse_feed(payload, when, window_hours=window_hours, max_items=max_items)


def market_news(ticker: str, title: str, when: datetime, window_hours: int = 6) -> List[Dict]:
    """Headlines for a market, using a short query built only from public title words."""
    return headlines_near(query_for(title, ticker), when, window_hours=window_hours)
