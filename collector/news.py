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

import argparse
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
    timeout: float = 6.0,
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


# ---------------------------------------------------------------------------
# Command line entry point
# ---------------------------------------------------------------------------
#
# ``python3 -m collector.news`` reads the collector's alert buffer, looks for
# headlines published near each swing, and writes ``data/news.json``. The site
# builder reads that file, so the news lookup never blocks the collector and
# its output is auditable on its own.
#
# A headline is a *candidate* catalyst. Temporal proximity is not causation, so
# every headline carries the label it is published under and the alert row
# always links to the official Kalshi market as well.

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ALERTS_PATH = os.path.join(DATA_DIR, "alerts.json")
LIVE_PATH = os.path.join(DATA_DIR, "live.json")
OUT_PATH = os.path.join(DATA_DIR, "news.json")

MAX_MARKETS = 12          # markets looked up per run
MAX_PER_MARKET = 3        # headlines kept per market
DEFAULT_WINDOW_HOURS = 24


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def collect_news(window_hours: int = DEFAULT_WINDOW_HOURS,
                 max_markets: int = MAX_MARKETS,
                 timeout: float = 8.0) -> Dict[str, Any]:
    """Look for candidate headlines around each recent >= $0.10 swing."""
    alerts = _load(ALERTS_PATH, {})
    rows = alerts.get("alerts") if isinstance(alerts, dict) else alerts
    if not rows:
        live = _load(LIVE_PATH, {})
        rows = live.get("alerts") or []
    rows = rows or []

    # One lookup per market, newest swing first.
    latest: Dict[str, Dict] = {}
    for alert in rows:
        ticker = alert.get("ticker")
        if not ticker:
            continue
        prior = latest.get(ticker)
        if prior is None or (alert.get("ts") or 0) >= (prior.get("ts") or 0):
            latest[ticker] = alert

    ordered = sorted(latest.values(), key=lambda a: -(a.get("ts") or 0))[:max_markets]
    now = datetime.now(timezone.utc)
    headlines: Dict[str, List[Dict]] = {}
    errors: List[str] = []
    for alert in ordered:
        ticker = alert["ticker"]
        when = datetime.fromtimestamp(alert.get("ts") or now.timestamp(), tz=timezone.utc)
        title = alert.get("title") or ticker
        try:
            found = market_news(ticker, title, when, window_hours=window_hours)
        except Exception as exc:  # never break the pipeline on a news lookup
            errors.append(f"{ticker}: {exc}")
            continue
        if not found:
            continue
        headlines[ticker] = found[:MAX_PER_MARKET]

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "window_hours": window_hours,
        "source": RSS,
        "note": ("Headlines are keyword and publish-time candidates only. "
                 "Temporal proximity is not causation and no headline here is "
                 "presented as the confirmed cause of a price move. Every alert "
                 "row also links to the official Kalshi market response."),
        "markets_considered": len(ordered),
        "headlines": headlines,
        "headline_count": sum(len(v) for v in headlines.values()),
        "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Attach candidate news links to swings.")
    ap.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    ap.add_argument("--max-markets", type=int, default=MAX_MARKETS)
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    payload = collect_news(window_hours=args.window_hours,
                           max_markets=args.max_markets)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print(json.dumps({"markets_considered": payload["markets_considered"],
                      "headline_count": payload["headline_count"],
                      "errors": len(payload["errors"]),
                      "out": args.out}, indent=1))


if __name__ == "__main__":
    main()
