"""Minimal, dependency-free client for the Kalshi Trade API v2 (demo environment).

Only public market-data endpoints are used here; no API key is required for those.
Every request is logged with its exact URL so a reviewer can replay it manually.

Verified against:
  - https://docs.kalshi.com/getting_started/demo_env   (recommended demo base URL)
  - https://docs.kalshi.com/getting_started/api_environments
  - https://docs.kalshi.com/getting_started/rate_limits (429 handling)
  - https://docs.kalshi.com/getting_started/orderbook_responses (book shape)
  - https://docs.kalshi.com/api-reference/market/get-market-candlesticks
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
PROD_BASE = "https://external-api.kalshi.com/trade-api/v2"

USER_AGENT = "Trade2-collector/1.0 (+https://github.com/wingbangboozle1-lang/Trade2)"


class KalshiError(RuntimeError):
    def __init__(self, url: str, status: int, body: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.url = url
        self.status = status
        self.body = body


class KalshiClient:
    """Tiny GET-only client with retry/backoff and an auditable request log."""

    def __init__(
        self,
        base: str = DEMO_BASE,
        timeout: float = 12.0,
        max_retries: int = 3,
        min_interval: float = 0.5,
        budget: Optional[int] = None,
        logger=None,
    ) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval      # floor for the adaptive pace
        self._interval = min_interval         # current pacing (grows on 429, decays on success)
        self._last_call = 0.0
        self.budget = budget                  # hard cap on HTTP attempts (None = unlimited)
        self.requests: List[Dict[str, Any]] = []
        self.log = logger or (lambda *a, **k: None)

    # ------------------------------------------------------------------ http
    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self._interval:
            time.sleep(self._interval - gap)
        self._last_call = time.monotonic()

    def get(self, path: str, **params: Any) -> Dict[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            if self.budget is not None and self.budget <= 0:
                # degrade gracefully: caller records the error and the run still publishes
                raise KalshiError(url, 0, "request budget exhausted (partial run)")
            if self.budget is not None:
                self.budget -= 1
            self._throttle()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    self.requests.append({"url": url, "status": resp.status, "ts": int(time.time())})
                    # success -> gently speed back up toward the floor interval
                    self._interval = max(self.min_interval, self._interval * 0.95)
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:  # 429 / 5xx -> backoff
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:
                    pass
                self.requests.append({"url": url, "status": exc.code, "ts": int(time.time()), "error": body[:200]})
                if exc.code in (429, 500, 502, 503, 504):
                    last_err = KalshiError(url, exc.code, body)
                    if exc.code == 429:
                        # back off AND slow the whole run down, not just this request
                        self._interval = min(4.0, max(self._interval * 1.4, 1.2))
                        self.log(f"warn: 429 rate limited; pacing now {self._interval:.1f}s/req url={url}")
                    time.sleep(min(30.0, 1.5 * (2**attempt)))
                    continue
                raise KalshiError(url, exc.code, body)
            except Exception as exc:  # network/timeout -> backoff
                last_err = exc
                self.log(f"warn: request failed ({exc.__class__.__name__}: {exc}) attempt={attempt + 1} url={url}")
                time.sleep(min(30.0, 1.5 * (2**attempt)))
        raise KalshiError(url, 0, f"exhausted retries: {last_err}")

    # ------------------------------------------------------------- endpoints
    def exchange_status(self) -> Dict[str, Any]:
        return self.get("/exchange/status")

    def series(self, category: Optional[str] = None, tags: Optional[str] = None, limit: int = 0) -> List[Dict[str, Any]]:
        # NOTE: the API returns an unpaginated list; `limit` is only a client-side cap.
        data = self.get("/series/", category=category, tags=tags, include_product_metadata="false")
        items = data.get("series") or []
        return items[:limit] if limit else items

    def markets(
        self,
        status: Optional[str] = None,
        series_ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
        limit: int = 1000,
        max_pages: int = 12,
        mve_filter: str = "exclude",
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            data = self.get(
                "/markets",
                status=status,
                series_ticker=series_ticker,
                event_ticker=event_ticker,
                limit=limit,
                cursor=cursor,
                mve_filter=mve_filter,
            )
            out.extend(data.get("markets") or [])
            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out

    def orderbook(self, ticker: str, depth: int = 20) -> Dict[str, Any]:
        return self.get(f"/markets/{ticker}/orderbook", depth=depth)

    def candlesticks(self, series_ticker: str, ticker: str, start_ts: int, end_ts: int, interval: int = 1) -> List[Dict[str, Any]]:
        data = self.get(
            f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            start_ts=int(start_ts),
            end_ts=int(end_ts),
            period_interval=int(interval),
        )
        return data.get("candlesticks") or []

    def trades(self, ticker: str, limit: int = 200) -> List[Dict[str, Any]]:
        data = self.get("/markets/trades", ticker=ticker, limit=limit)
        return data.get("trades") or []


# --------------------------------------------------------------------- helpers
def fnum(value: Any) -> Optional[float]:
    """Parse Kalshi fixed-point strings ('0.4500', '35.00') into floats.

    Returns None for missing/blank values so callers can leave a cell blank
    instead of inventing a zero.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def best_bid(levels: Iterable[List[str]]) -> Optional[float]:
    prices = [fnum(l[0]) for l in levels or [] if len(l) >= 1]
    prices = [p for p in prices if p is not None]
    return max(prices) if prices else None


def depth_usd(levels: Iterable[List[str]], upto: Optional[float] = None) -> Tuple[float, float]:
    """Return (contracts, dollars) resting on a side of the book."""
    contracts = 0.0
    dollars = 0.0
    for level in levels or []:
        if len(level) < 2:
            continue
        price, count = fnum(level[0]), fnum(level[1])
        if price is None or count is None:
            continue
        contracts += count
        dollars += price * count
    return round(contracts, 2), round(dollars, 2)


def contracts_available(levels: Iterable[List[str]], min_price: float, max_price: float, side: str = "yes") -> float:
    """How many contracts can be bought within [min_price, max_price] on one side."""
    total = 0.0
    for level in levels or []:
        if len(level) < 2:
            continue
        price, count = fnum(level[0]), fnum(level[1])
        if price is None or count is None:
            continue
        if min_price <= price <= max_price:
            total += count
    return round(total, 2)


def iter_pages(items: List[Dict[str, Any]], size: int = 100) -> Iterator[List[Dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
