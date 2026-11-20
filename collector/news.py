"""Best-effort headline lookup for >= $0.10 price swings.

Uses Google News RSS (public, no API key) to find headlines published near a swing.
IMPORTANT: a headline is only a *candidate* catalyst — temporal proximity is not
causation, and nothing here is presented as a confirmed cause. If the lookup fails
(for example in an offline environment) the link fields stay blank and the item is
flagged as unverified, per the project verification rule.

Sandbox note: this runner executes on GitHub Actions runners, which have full
network egress; the dev sandbox cannot reach news.google.com, so the code degrades
to empty results rather than raising.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

USER_AGENT = "Trade2-collector/1.0 (+https://github.com/wingbangboozle1-lang/Trade2)"
RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


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


def headlines_near(
    query: str,
    when: datetime,
    window_hours: int = 6,
    max_items: int = 5,
    timeout: float = 12.0,
) -> List[Dict]:
    """Return RSS headlines for `query` published within +/- window_hours of `when`."""
    if not query:
        return []
    url = RSS.format(q=urllib.parse.quote(query))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except Exception:
        return []  # network blocked -> caller leaves links blank + flags unverified

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
                "status": "verified-fetch" if published else "unverified-time",
            }
        )
        if len(out) >= max_items:
            break
    return out


def market_news(ticker: str, title: str, when: datetime, window_hours: int = 6) -> List[Dict]:
    """Headlines for a market, using a short query built only from public title words."""
    words = [w for w in re.split(r"[^A-Za-z0-9$]+", title or "") if len(w) > 2]
    query = " ".join(words[:6]) if words else ticker
    return headlines_near(query, when, window_hours=window_hours)
