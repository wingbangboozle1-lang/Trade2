"""Ask the live demo API which tickers serialisation it accepts. Diagnostic only."""
import json, urllib.error, urllib.parse, urllib.request

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
T = ["KXAAAGASM-26NOV30-4.70", "KXRESNOMD-28-RW"]
T = ["KXAAAGASM-26NOV30-4.70", "KXPRESNOMD-28-RW"]

def get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                              "User-Agent": "Trade2-fmt/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace")
        return e.code, body
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

cases = {
  "orderbooks repeated": BASE + "/markets/orderbooks?" + "&".join("tickers=" + urllib.parse.quote(t) for t in T),
  "orderbooks comma":    BASE + "/markets/orderbooks?tickers=" + urllib.parse.quote(",".join(T)),
  "orderbooks brackets": BASE + "/markets/orderbooks?tickers[]=" + "&tickers[]=".join(urllib.parse.quote(t) for t in T),
  "markets repeated":    BASE + "/markets?" + "&".join("tickers=" + urllib.parse.quote(t) for t in T),
  "markets comma":       BASE + "/markets?tickers=" + urllib.parse.quote(",".join(T)),
  "markets single":      BASE + "/markets?tickers=" + urllib.parse.quote(T[0]),
}
out = {}
for name, url in cases.items():
    status, body = get(url)
    if isinstance(body, dict):
        rows = body.get("orderbooks") or body.get("markets") or []
        got = [r.get("ticker") for r in rows]
        out[name] = {"status": status, "n": len(rows), "tickers": got[:5]}
    else:
        out[name] = {"status": status, "error": str(body)[:200]}
    print(name, "->", json.dumps(out[name]))
msg = json.dumps(out).replace("%", "%25").replace("\n", "%0A")
print("::notice title=Tickers formats::" + msg[:6000])
