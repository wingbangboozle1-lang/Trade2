"""Discovery pass: resolve the in-scope series and open markets per topic."""
import json, sys, datetime
sys.path.insert(0, ".")
from collector.kalshi_api import KalshiClient, DEMO_REST
from collector import topics as T

def main():
    c = KalshiClient(DEMO_REST)
    out = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "api_root": DEMO_REST, "topics": {}}
    for t in T.TOPICS:
        series = T.resolve_series(c, t)
        out["topics"][t.slug] = {"label": t.label, "source_url": t.source_url,
                                 "series": series,
                                 "series_count": len(series)}
        print(f"{t.slug}: {len(series)} series", file=sys.stderr)
    with open("data/discovery.json", "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v["series_count"] for k, v in out["topics"].items()}, indent=1))

main()
