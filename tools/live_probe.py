#!/usr/bin/env python3
"""Live-layer capability probe (task T31, session arena-5bec0ea3).

Runs on a GitHub Actions runner (unrestricted egress — this sandbox cannot
reach Kalshi hosts directly) and records, as verified facts with raw evidence:

  A. REST CORS: can a browser page hosted on GitHub Pages call the demo REST
     API directly? (Origin + preflight headers, exact response headers kept.)
  B. WebSocket: is an *anonymous* browser-style handshake accepted by
     wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2? (Browsers cannot set
     KALSHI-ACCESS-* headers; the official docs say the handshake requires
     authentication:
     https://docs.kalshi.com/getting_started/quick_start_websockets .)
  C. REST reachability: one market GET, field names observed.

Output: docs/data/capabilities.json — consumed by docs/assets/live.js to pick
the honest live mode (direct REST / WS / snapshot fallback) and shown on the
Flagged page. Nothing here is inferred: each probe records its exact request
and the raw response head.

Usage: python3 tools/live_probe.py [--root .] [--timeout 20]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

REST_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
WS_URL = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
PAGE_ORIGIN = "https://wingbangboozle1-lang.github.io"
PROBE_MARKET = "KXPRESNOMD-28-RW"  # documented live demo market (see AUDIT_ADDENDUM)
DOC_WS = "https://docs.kalshi.com/getting_started/quick_start_websockets"
DOC_CORS_NOTE = ("Browsers enforce CORS for fetch(); WebSocket connections are "
                 "not CORS-restricted but cannot carry custom auth headers.")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_probe(url: str, method: str = "GET", extra_headers: dict | None = None,
               timeout: int = 20) -> dict:
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", "Trade2-live-probe/1.0")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    out = {"request": {"method": method, "url": url,
                       "headers": extra_headers or {}},
           "probed_at": now()}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(2000)
            out["status"] = r.status
            out["response_headers"] = {k.lower(): v for k, v in r.headers.items()}
            try:
                out["body_sample"] = json.loads(body.decode("utf-8", "replace"))
            except ValueError:
                out["body_sample"] = body.decode("utf-8", "replace")[:400]
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        out["response_headers"] = {k.lower(): v for k, v in (e.headers or {}).items()}
        try:
            out["body_sample"] = e.read(600).decode("utf-8", "replace")
        except Exception:
            pass
    except Exception as e:  # network-level failure is itself a recorded fact
        out["status"] = None
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def probe_rest_cors(timeout: int) -> dict:
    """A. CORS as seen by a GitHub Pages origin."""
    get = http_probe(f"{REST_BASE}/markets?limit=1", "GET",
                     {"Origin": PAGE_ORIGIN}, timeout)
    pre = http_probe(f"{REST_BASE}/markets?limit=1", "OPTIONS",
                     {"Origin": PAGE_ORIGIN,
                      "Access-Control-Request-Method": "GET",
                      "Access-Control-Request-Headers": "content-type"}, timeout)
    acao_get = (get.get("response_headers") or {}).get("access-control-allow-origin")
    acao_pre = (pre.get("response_headers") or {}).get("access-control-allow-origin")
    browser_usable = bool(
        (acao_get == "*" or acao_get == PAGE_ORIGIN) or
        (acao_pre == "*" or acao_pre == PAGE_ORIGIN))
    return {
        "browser_usable": browser_usable,
        "access_control_allow_origin_get": acao_get,
        "access_control_allow_origin_preflight": acao_pre,
        "get": get, "preflight": pre,
        "docs": "https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS",
        "note": DOC_CORS_NOTE,
    }


def probe_ws_anonymous(timeout: int) -> dict:
    """B. Browser-equivalent WebSocket handshake: TLS + HTTP Upgrade, no
    KALSHI-ACCESS-* headers (browsers cannot send them)."""
    host = "external-api-ws.demo.kalshi.co"
    path = "/trade-api/ws/v2"
    out = {"request": {"url": WS_URL, "headers_sent": [
        "Host", "Upgrade", "Connection", "Sec-WebSocket-Key",
        "Sec-WebSocket-Version", f"Origin: {PAGE_ORIGIN}"],
        "auth_headers_sent": []},
        "probed_at": now(), "docs": DOC_WS}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                key = base64.b64encode(os.urandom(16)).decode()
                req = (f"GET {path} HTTP/1.1\r\n"
                       f"Host: {host}\r\n"
                       f"Upgrade: websocket\r\n"
                       f"Connection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\n"
                       f"Sec-WebSocket-Version: 13\r\n"
                       f"Origin: {PAGE_ORIGIN}\r\n"
                       f"\r\n")
                s.sendall(req.encode())
                s.settimeout(timeout)
                resp = b""
                while b"\r\n\r\n" not in resp and len(resp) < 8192:
                    chunk = s.recv(1024)
                    if not chunk:
                        break
                    resp += chunk
                head = resp.decode("utf-8", "replace")
                out["response_head"] = head[:1200]
                status_line = head.split("\r\n", 1)[0]
                out["status_line"] = status_line
                out["upgraded"] = " 101 " in status_line
                out["anonymous_handshake_accepted"] = out["upgraded"]
    except Exception as e:
        out["status_line"] = None
        out["upgraded"] = False
        out["anonymous_handshake_accepted"] = False
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args(argv)

    caps = {
        "generated_at": now(),
        "runner": os.environ.get("GITHUB_RUN_ID") or "local",
        "probes": {
            "rest_cors": probe_rest_cors(args.timeout),
            "ws_anonymous_handshake": probe_ws_anonymous(args.timeout),
            "rest_reachable": http_probe(
                f"{REST_BASE}/markets/{PROBE_MARKET}", "GET", None, args.timeout),
        },
        "interpretation": {
            "live_rest_mode": "browser can poll the demo REST API directly "
                              "only if rest_cors.browser_usable is true",
            "live_ws_mode": "browser WebSocket can stream only if "
                            "ws_anonymous_handshake.anonymous_handshake_accepted "
                            "is true (official docs require auth headers, which "
                            "browsers cannot send)",
            "snapshot_mode": "otherwise the site falls back to the published "
                             "docs/data/*.json snapshot and says so",
        },
        "official_sources": {
            "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
            "api_environments": "https://docs.kalshi.com/getting_started/api_environments",
            "websockets": DOC_WS,
            "get_markets": "https://docs.kalshi.com/api-reference/market/get-markets",
        },
    }
    out_path = os.path.join(args.root, "docs", "data", "capabilities.json")
    with open(out_path, "w") as f:
        json.dump(caps, f, indent=1)
    cors = caps["probes"]["rest_cors"]["browser_usable"]
    ws = caps["probes"]["ws_anonymous_handshake"]["anonymous_handshake_accepted"]
    print(f"live_probe: wrote {out_path}")
    print(f"  REST CORS for {PAGE_ORIGIN}: {cors}")
    print(f"  anonymous WS handshake accepted: {ws}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
