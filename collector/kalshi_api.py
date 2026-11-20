"""Minimal, dependency-free Kalshi Trade API v2 client.

Verified against the official Kalshi documentation:

* Environments / base URLs — https://docs.kalshi.com/getting_started/api_environments.md
  Production REST: https://external-api.kalshi.com/trade-api/v2  (also api.elections.kalshi.com)
  Demo REST:       https://external-api.demo.kalshi.co/trade-api/v2 (also demo-api.kalshi.co)
  Demo WebSocket:  wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2 (also demo-api.kalshi.co)
* Request signing — https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md
  message = f"{timestamp_ms}{METHOD}{path_without_query}"
  RSA keys -> RSA-PSS / SHA-256 / salt = digest length; Ed25519 -> sign message directly.
  Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE (base64).
* Fixed point — https://docs.kalshi.com/getting_started/fixed_point_migration.md
  Money fields arrive as decimal *strings* in dollars (e.g. "0.4200"); counts as
  strings with 2 decimals (e.g. "13.00"). Never treat them as floats blindly.
* Orderbook shape — https://docs.kalshi.com/getting_started/orderbook_responses.md
  {"orderbook_fp": {"yes_dollars": [["0.4200","13.00"], ...], "no_dollars": [...]}}
  Arrays are ascending by price; best bid is the LAST element. Only bids are returned.
  Implied YES ask = 1.00 - best NO bid.

The module uses only the Python standard library. Authenticated calls additionally
need ``cryptography``; they raise ``AuthNotConfigured`` when no key material is
present instead of silently doing something else.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

PROD_REST = "https://external-api.kalshi.com/trade-api/v2"
PROD_REST_ALT = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_REST = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_REST_ALT = "https://demo-api.kalshi.co/trade-api/v2"

DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
DEMO_WS_ALT = "wss://demo-api.kalshi.co/trade-api/ws/v2"
PROD_WS = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
PROD_WS_ALT = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# The signed path is part of the API root, not the host (see docs above).
SIGNED_PREFIX = "/trade-api/v2"


class AuthNotConfigured(RuntimeError):
    """Raised when an authenticated endpoint is requested without credentials."""


class KalshiHTTPError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:400]}")
        self.status = status
        self.body = body
        self.url = url


@dataclass(frozen=True)
class Credentials:
    """Demo (or production) API key material.

    Loaded from the environment so no secret is ever written to the repo:

        KALSHI_API_KEY_ID       - the key id shown in Account & security -> API Keys
        KALSHI_PRIVATE_KEY_PATH - path to the downloaded PEM private key
        KALSHI_ENV              - "demo" (default) or "prod"
    """

    key_id: str
    private_key_path: str
    env: str = "demo"

    @classmethod
    def from_env(cls) -> "Credentials | None":
        key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
        path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()
        if not key_id or not path:
            return None
        return cls(key_id=key_id, private_key_path=path,
                   env=os.environ.get("KALSHI_ENV", "demo").strip().lower())


def _load_private_key(path: str):
    from cryptography.hazmat.primitives import serialization  # type: ignore

    with open(path, "rb") as fh:
        return serialization.load_pem_private_key(fh.read(), password=None)


def sign_message(private_key, timestamp_ms: str, method: str, signed_path: str) -> str:
    """Reproduce the documented signature exactly.

    ``signed_path`` must already exclude the query string.
    """
    from cryptography.hazmat.primitives import hashes  # type: ignore
    from cryptography.hazmat.primitives.asymmetric import padding  # type: ignore
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore
        Ed25519PrivateKey,
    )

    message = f"{timestamp_ms}{method}{signed_path}".encode("utf-8")
    if isinstance(private_key, Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    return base64.b64encode(signature).decode("utf-8")


class KalshiClient:
    """Thin REST wrapper. Public endpoints need no credentials."""

    def __init__(self, base_url: str = DEMO_REST, credentials: Credentials | None = None,
                 timeout: float = 20.0, user_agent: str = "trade2-kalshi-dashboard/1.0"):
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.timeout = timeout
        self.user_agent = user_agent
        self._key = None
        self.last_rate_limit: dict[str, str] = {}

    # -- plumbing ---------------------------------------------------------
    def _request(self, method: str, path: str, params: dict[str, Any] | None = None,
                 body: dict[str, Any] | None = None, authenticated: bool = False,
                 retries: int = 2) -> Any:
        query = ""
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                query = "?" + urllib.parse.urlencode(clean, doseq=True)
        url = f"{self.base_url}{path}{query}"

        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if authenticated:
            if not self.credentials:
                raise AuthNotConfigured(
                    "Authenticated endpoint requested but KALSHI_API_KEY_ID / "
                    "KALSHI_PRIVATE_KEY_PATH are not set."
                )
            if self._key is None:
                self._key = _load_private_key(self.credentials.private_key_path)
            ts = str(int(time.time() * 1000))
            # Sign path from the API root, query string excluded (docs above).
            signature = sign_message(self._key, ts, method, SIGNED_PREFIX + path)
            headers["KALSHI-ACCESS-KEY"] = self.credentials.key_id
            headers["KALSHI-ACCESS-TIMESTAMP"] = ts
            headers["KALSHI-ACCESS-SIGNATURE"] = signature

        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    self._capture_rate_limit(resp.headers)
                    raw = resp.read().decode("utf-8") or "{}"
                    return json.loads(raw)
            except urllib.error.HTTPError as exc:
                self._capture_rate_limit(exc.headers)
                payload = exc.read().decode("utf-8", "replace")
                if exc.code == 429 and attempt < retries:
                    time.sleep(1.5 * (2 ** attempt))
                    attempt += 1
                    continue
                raise KalshiHTTPError(exc.code, payload, url) from None
            except urllib.error.URLError as exc:
                if attempt < retries:
                    time.sleep(1.0 * (2 ** attempt))
                    attempt += 1
                    continue
                raise KalshiHTTPError(0, str(exc.reason), url) from None

    def _capture_rate_limit(self, headers) -> None:
        if headers is None:
            return
        keys = ("X-RateLimit-Limit", "X-RateLimit-Remaining",
                "X-RateLimit-Reset", "X-RateLimit-Cost")
        for k in keys:
            v = headers.get(k)
            if v is not None:
                self.last_rate_limit[k] = v

    # -- public market data ----------------------------------------------
    def exchange_status(self) -> dict[str, Any]:
        """GET /exchange/status — https://docs.kalshi.com/api-reference/exchange/get-exchange-status"""
        return self._request("GET", "/exchange/status")

    def series_list(self, category: str | None = None, tags: str | None = None,
                    include_volume: bool = True, max_pages: int = 4) -> list[dict[str, Any]]:
        """GET /series — https://docs.kalshi.com/api-reference/market/get-series-list

        Paged with a cursor. ``max_pages`` bounds the work: the Elections
        category alone returns thousands of series, and the collector only needs
        enough of them to identify in-scope markets within its time budget.
        """
        out: list[dict[str, Any]] = []
        cursor = None
        for _ in range(max_pages):  # hard stop; guard against a runaway loop
            page = self._request("GET", "/series", {
                "category": category, "tags": tags,
                "include_volume": "true" if include_volume else "false",
                "cursor": cursor,
            })
            out.extend(page.get("series") or [])
            cursor = page.get("cursor") or ""
            if not cursor:
                break
        return out

    def markets(self, max_pages: int = 50, **params: Any) -> list[dict[str, Any]]:
        """GET /markets — https://docs.kalshi.com/api-reference/market/get-markets

        Paged with cursor; every matching market is de-duplicated by ticker as
        the docs advise (a market whose close time moves can repeat).
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = None
        for _ in range(max_pages):
            page = self._request("GET", "/markets", {**params, "cursor": cursor})
            for market in page.get("markets") or []:
                ticker = market.get("ticker")
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    out.append(market)
            cursor = page.get("cursor") or ""
            if not cursor:
                break
        return out

    def events(self, **params: Any) -> list[dict[str, Any]]:
        """GET /events — https://docs.kalshi.com/api-reference/events/get-events"""
        out: list[dict[str, Any]] = []
        cursor = None
        for _ in range(100):
            page = self._request("GET", "/events", {**params, "cursor": cursor})
            out.extend(page.get("events") or [])
            cursor = page.get("cursor") or ""
            if not cursor:
                break
        return out

    def orderbook(self, ticker: str, depth: int | None = None) -> dict[str, Any]:
        """GET /markets/{ticker}/orderbook — orderbook_responses.md (bids only)."""
        params = {"depth": depth} if depth else None
        return self._request("GET", f"/markets/{urllib.parse.quote(ticker)}/orderbook",
                             params)

    def orderbooks(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """GET /markets/orderbooks — up to 100 tickers in one request.

        Documented at
        https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks.md
        Returns {ticker: orderbook_fp}. A ticker with no book (including an
        unknown one) comes back with empty arrays, never a 404, so an empty book
        and a bad ticker are indistinguishable here by design — check the market
        with GET /markets/{ticker} when that distinction matters.
        """
        out: dict[str, dict[str, Any]] = {}
        clean = [t for t in tickers if t][:100]
        if not clean:
            return out
        page = self._request("GET", "/markets/orderbooks", {"tickers": clean})
        for entry in page.get("orderbooks") or []:
            ticker = entry.get("ticker")
            if ticker:
                out[ticker] = entry.get("orderbook_fp") or {}
        return out

    def candlesticks(self, series_ticker: str, ticker: str, start_ts: int, end_ts: int,
                     period_interval: int = 1) -> dict[str, Any]:
        """GET /series/{s}/markets/{t}/candlesticks — period must be 1, 60 or 1440.

        Docs cap a single request at 5,000 periods.
        """
        if period_interval not in (1, 60, 1440):
            raise ValueError("period_interval must be 1, 60 or 1440")
        return self._request(
            "GET",
            f"/series/{urllib.parse.quote(series_ticker)}/markets/"
            f"{urllib.parse.quote(ticker)}/candlesticks",
            {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval},
        )

    def trades(self, **params: Any) -> list[dict[str, Any]]:
        """GET /markets/trades — https://docs.kalshi.com/api-reference/market/get-trades"""
        page = self._request("GET", "/markets/trades", params)
        return page.get("trades") or []

    # -- authenticated portfolio -----------------------------------------
    def balance(self) -> dict[str, Any]:
        """GET /portfolio/balance (authenticated; own rate-limit bucket)."""
        return self._request("GET", "/portfolio/balance", authenticated=True)

    def positions(self) -> dict[str, Any]:
        return self._request("GET", "/portfolio/positions", authenticated=True)

    def orders(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/portfolio/orders", params, authenticated=True)

    def fills(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/portfolio/fills", params, authenticated=True)

    def create_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """POST /portfolio/events/orders (see quick_start_create_order.md)."""
        return self._request("POST", "/portfolio/events/orders", body=order,
                             authenticated=True)


# -- validated helpers ---------------------------------------------------

def dollars(value: Any) -> float | None:
    """Parse a Kalshi fixed-point dollar string. Returns None when absent.

    Returns None (never 0.0) for '', None or unparsable values so that callers
    can distinguish "no quote" from "quoted at zero" — a real distinction on
    Kalshi, where 0.0000 is a legitimate bid.
    """
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def count(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def best_bid(levels: Iterable[list[str]] | None) -> tuple[float, float] | None:
    """Return (price, size) of the best bid.

    Documented shape: ascending arrays of [price_dollars, count_fp]; the best
    (highest) bid is the LAST element.
    """
    rows = list(levels or [])
    if not rows:
        return None
    last = rows[-1]
    if not isinstance(last, (list, tuple)) or len(last) < 2:
        return None
    price, size = dollars(last[0]), count(last[1])
    if price is None:
        return None
    return price, (size or 0.0)


def implied_yes_ask(no_bid: float | None) -> float | None:
    """YES ask implied by the best NO bid: 1.00 - NO bid (orderbook docs)."""
    if no_bid is None:
        return None
    return round(1.0 - no_bid, 4)


def mid_price(yes_bid: float | None, yes_ask: float | None) -> float | None:
    if yes_bid is None and yes_ask is None:
        return None
    if yes_bid is None:
        return yes_ask
    if yes_ask is None:
        return yes_bid
    return round((yes_bid + yes_ask) / 2.0, 4)


def kalshi_fee(price: float, contracts: float, multiplier: float = 1.0) -> float:
    """Kalshi's published taker trading fee, computed exactly.

    Source of the formula and the table used as the oracle:
    https://kalshi.com/docs/kalshi-fee-schedule.pdf
    (referenced by ``fee_type`` in
    https://docs.kalshi.com/api-reference/market/get-series-list.md)

        fees = round_up( M x 0.07 x C x P x (1 - P) )   to the cent

    Decimal arithmetic is used deliberately. Computing this in binary floats
    produces 1.7500000000000002 for P=0.50, C=100 and a naive ceiling then
    yields $1.76 where Kalshi's own table says $1.75. With Decimal every one of
    the 42 published rows reproduces exactly — see
    tests/test_engine.py::TestFees::test_all_published_fee_table_rows.

    The schedule also lists per-series multipliers (0 for fee-free series, 2 for
    uncorrelated combos); callers pass the series' own ``fee_multiplier``. A
    ``flat`` fee structure is not modelled here; pass multiplier=0.0 for it and
    label the assumption in the UI.
    """
    from decimal import Decimal, ROUND_CEILING

    p = Decimal(str(price))
    c = Decimal(str(contracts))
    m = Decimal(str(multiplier))
    if p <= 0 or p >= 1 or c <= 0 or m <= 0:
        return 0.0
    raw = m * Decimal("0.07") * c * p * (Decimal(1) - p)
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING))
