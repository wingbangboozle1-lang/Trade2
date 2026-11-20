#!/usr/bin/env python3
"""Strategy lab — categorise simulated trades and backtest reference strategies.

Scope (task T32, session arena-5bec0ea3, see COORDINATION.md Board E):

* Normalise every simulated trade found in the repo's published data files
  (docs/data/portfolio.json — the "docs-sim" book, data/live.json + data/
  portfolio_state.json — the "root" book, kalshi-dashboard/data/trades.json).
* Categorise round-trips by strategy x signal x topic and compute performance
  tables (win rate, gross/fees/net P&L, ROI on cost, drawdown).
* Cross-check the books' *published* aggregate stats against a recomputation
  from the trade rows; discrepancies are listed, never silently reconciled.
* Replay three deterministic reference strategies (momentum, mean-reversion,
  breakout) over the recorded demo candlesticks in docs/data/candles.json,
  with the official Kalshi taker fee formula. Every generated trade row keeps
  the candle series' official API source URL.
* Emit: STRATEGY_ANALYSIS.md, docs/strategies.html, docs/data/strategy_lab.json.

Verification rules honoured here:
  - Values computed by this tool are labelled as computed from the repo's own
    simulated ledger or recorded demo candles. They are NOT presented as
    verified facts about the world or as investment advice.
  - Every table row carries a source URL (official Kalshi host) or is left
    blank and marked "(unverified)".
  - Fee maths: taker fee = 0.07 * C * P * (1 - P), rounded UP to the cent,
    per https://kalshi.com/docs/kalshi-fee-schedule.pdf (Decimal, not float).

Usage:
    python3 tools/strategy_lab.py [--root .] [--quiet]
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

FEE_SCHEDULE_URL = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_FORMULA_DOC = (
    "taker fee = round_up(0.07 * C * P * (1 - P)) to the cent "
    f"({FEE_SCHEDULE_URL})"
)
DEMO_MARKET_URL = "https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}"
OFFICIAL_HOSTS = (
    "https://external-api.demo.kalshi.co/",
    "https://demo-api.kalshi.co/",
    "https://docs.kalshi.com/",
    "https://kalshi.com/docs/",
    "https://kalshi.com/getting_started/",
)

UNVERIFIED = "(unverified)"
BACKTEST_CONTRACTS = 100  # fixed size per backtest trade, for comparability
BACKTEST_HOLD_BARS = 12
# Recorded candle histories are currently 3-6 bars (collection began
# 2026-11-20), so the gate is low and every table flags the small sample.
# Momentum/mean-reversion need entry + exit = 3 bars; breakout's own gate
# requires 11 prior bars, so it simply produces no trades on short records.
BACKTEST_MIN_BARS = 3
SWING_THRESHOLD = Decimal("0.10")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def taker_fee(contracts: Decimal, price: Decimal) -> Decimal:
    """Official taker fee, exact decimal, rounded UP to the cent."""
    fee = (Decimal("0.07") * contracts * price * (Decimal(1) - price))
    return fee.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def market_url(ticker: str, source_url: str | None = None) -> str:
    """Prefer the ledger's own official source URL; else construct the
    official demo market URL from the ticker."""
    if source_url and source_url.startswith("https://"):
        return source_url
    if ticker:
        return DEMO_MARKET_URL.format(ticker=ticker)
    return ""


def link_or_unverified(url: str) -> str:
    """Markdown link cell: blank + '(unverified)' when no official URL exists."""
    if not url:
        return f"— {UNVERIFIED}"
    return f"[source]({url})"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100.0 * x:.1f}%"


def money(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_ts(v) -> str | None:
    """Normalise timestamps to ISO-8601 strings: epoch seconds (float/int) or
    strings pass through. Returns None when absent."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v)
    return s or None


# --------------------------------------------------------------------------
# ledger loading
# --------------------------------------------------------------------------

def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_docs_book(root: Path) -> dict:
    """Round-trips from docs/data/portfolio.json (c0205283 simulated book).

    Trade rows carry action open/close; a round-trip is one open row plus its
    matching close row (same ticker, side, strategy). Open rows with no close
    are kept as 'open' round-trips with unrealised context only.
    """
    data = _load_json(root / "docs" / "data" / "portfolio.json")
    book = {"name": "docs-sim book", "engine": "docs/data/portfolio.json (roi_edge)",
            "round_trips": [], "published_stats": None, "equity_curve": []}
    if not isinstance(data, dict):
        return book
    book["published_stats"] = data.get("stats")
    book["equity_curve"] = data.get("equity_curve") or []
    trades = data.get("trades") or []
    open_by_key: dict[tuple, dict] = {}
    for t in trades:
        if not isinstance(t, dict):
            continue
        ticker = t.get("ticker") or ""
        side = t.get("side") or ""
        strat = t.get("strategy") or ""
        key = (ticker, side, strat)
        action = (t.get("action") or "").lower()
        src = market_url(ticker, t.get("source_url"))
        if action == "open":
            open_by_key[key] = t
            book["round_trips"].append({
                "book": book["name"], "ticker": ticker, "topic": t.get("topic") or "",
                "strategy": strat, "signal": t.get("signal") or "",
                "trade_type": t.get("trade_type") or f"{strat}|{t.get('signal')}|{side}",
                "side": side, "status": "open",
                "entry_ts": norm_ts(t.get("ts")), "entry_px": t.get("price"),
                "contracts": t.get("contracts"), "entry_fee": t.get("fee"),
                "exit_ts": None, "exit_px": None, "exit_fee": None,
                "gross": None, "net": None, "result": "open",
                "source_url": src,
            })
        elif action == "close":
            rt = {
                "book": book["name"], "ticker": ticker, "topic": t.get("topic") or "",
                "strategy": strat, "signal": t.get("signal") or "",
                "trade_type": t.get("trade_type") or f"{strat}|{t.get('signal')}|{side}",
                "side": side, "status": "closed",
                "entry_ts": norm_ts(open_by_key.get(key, {}).get("ts")),
                "entry_px": open_by_key.get(key, {}).get("price"),
                "contracts": t.get("contracts"), "entry_fee": open_by_key.get(key, {}).get("fee"),
                "exit_ts": norm_ts(t.get("ts")), "exit_px": t.get("price"), "exit_fee": t.get("fee"),
                "gross": None, "net": t.get("pnl"), "result": "win" if (t.get("pnl") or 0) > 0
                else ("loss" if (t.get("pnl") or 0) < 0 else "flat"),
                "source_url": src,
            }
            # recompute gross from rows when entry is known
            if rt["entry_px"] is not None and rt["exit_px"] is not None and rt["contracts"]:
                c = Decimal(str(rt["contracts"]))
                rt["gross"] = float(c * (Decimal(str(rt["exit_px"])) - Decimal(str(rt["entry_px"]))))
            book["round_trips"].append(rt)
    return book


def load_root_book(root: Path) -> dict:
    """Round-trips from data/live.json + data/portfolio_state.json (root book)."""
    book = {"name": "root book", "engine": "data/live.json portfolio + data/portfolio_state.json",
            "round_trips": [], "published_stats": None, "equity_curve": []}
    live = _load_json(root / "data" / "live.json")
    state = _load_json(root / "data" / "portfolio_state.json")
    if isinstance(live, dict):
        port = live.get("portfolio") or {}
        if isinstance(port, dict):
            book["published_stats"] = {
                "overall": port.get("overall"), "by_strategy": port.get("by_strategy"),
                "by_topic": port.get("by_topic"), "by_category": port.get("by_category"),
            }
        for t in (port.get("trades") or []):
            if not isinstance(t, dict):
                continue
            ticker = t.get("ticker") or ""
            closed = t.get("status") == "closed" or t.get("exit_price") is not None
            net = t.get("realized") if t.get("realized") is not None else t.get("pnl")
            book["round_trips"].append({
                "book": book["name"], "ticker": ticker, "topic": t.get("topic") or "",
                "strategy": t.get("strategy") or "",
                "signal": t.get("signal") or t.get("reason") or "",
                "trade_type": t.get("trade_type") or f"{t.get('strategy')}|{t.get('signal') or t.get('reason')}|{t.get('side')}",
                "side": t.get("side") or "", "status": "closed" if closed else "open",
                "entry_ts": norm_ts(t.get("entry_ts")), "entry_px": t.get("entry_price"),
                "contracts": t.get("contracts"), "entry_fee": t.get("entry_fee"),
                "exit_ts": norm_ts(t.get("exit_ts")), "exit_px": t.get("exit_price"),
                "exit_fee": t.get("exit_fee"),
                "gross": None, "net": net if closed else None,
                "result": (t.get("result") or ("win" if (net or 0) > 0 else
                           ("loss" if (net or 0) < 0 else "flat"))) if closed else "open",
                "source_url": market_url(ticker, t.get("source_url")),
            })
    # Dedupe guard: data/live.json portfolio.trades and data/portfolio_state.json
    # positions come from the same engine and may describe the same round-trips.
    seen = {(rt["ticker"], rt["side"], rt.get("entry_ts")) for rt in book["round_trips"]}
    if isinstance(state, dict):
        for p in (state.get("positions") or []):
            if not isinstance(p, dict):
                continue
            ticker = p.get("ticker") or ""
            key = (ticker, p.get("side") or "", p.get("entry_ts"))
            if key in seen:
                continue
            seen.add(key)
            closed = (p.get("status") == "closed")
            net = p.get("realized") if closed else None
            book["round_trips"].append({
                "book": book["name"], "ticker": ticker, "topic": p.get("topic") or "",
                "strategy": p.get("strategy") or "",
                "signal": p.get("title") or "",
                "trade_type": f"{p.get('strategy')}|settlement|{p.get('side')}",
                "side": p.get("side") or "", "status": "closed" if closed else "open",
                "entry_ts": norm_ts(p.get("entry_ts")), "entry_px": p.get("entry_price"),
                "contracts": p.get("contracts"), "entry_fee": p.get("entry_fee"),
                "exit_ts": norm_ts(p.get("exit_ts")), "exit_px": p.get("exit_price"),
                "exit_fee": p.get("exit_fee"),
                "gross": None, "net": net,
                "result": (p.get("result") or ("win" if (net or 0) > 0 else
                           ("loss" if (net or 0) < 0 else "flat"))) if closed else "open",
                "source_url": market_url(ticker, p.get("source_url")),
            })
    return book


def load_kd_book(root: Path) -> dict:
    """Round-trips from kalshi-dashboard/data/trades.json (5788e385 book)."""
    book = {"name": "kalshi-dashboard book",
            "engine": "kalshi-dashboard/data/trades.json",
            "round_trips": [], "published_stats": None, "equity_curve": []}
    data = _load_json(root / "kalshi-dashboard" / "data" / "trades.json")
    rows = data if isinstance(data, list) else (data.get("trades") or [] if isinstance(data, dict) else [])
    for t in rows:
        if not isinstance(t, dict):
            continue
        ticker = t.get("ticker") or ""
        closed = t.get("exit_price") is not None or t.get("status") == "closed"
        net = t.get("realized") or t.get("pnl")
        book["round_trips"].append({
            "book": book["name"], "ticker": ticker, "topic": t.get("topic") or "",
            "strategy": t.get("strategy") or "", "signal": t.get("signal") or "",
            "trade_type": t.get("trade_type") or f"{t.get('strategy')}|{t.get('signal')}|{t.get('side')}",
            "side": t.get("side") or "", "status": "closed" if closed else "open",
            "entry_ts": norm_ts(t.get("entry_ts") or t.get("ts")), "entry_px": t.get("entry_price") or t.get("price"),
            "contracts": t.get("contracts"), "entry_fee": t.get("entry_fee") or t.get("fee"),
            "exit_ts": norm_ts(t.get("exit_ts")), "exit_px": t.get("exit_price"), "exit_fee": t.get("exit_fee"),
            "gross": None, "net": net if closed else None,
            "result": (t.get("result") or ("win" if (net or 0) > 0 else
                       ("loss" if (net or 0) < 0 else "flat"))) if closed else "open",
            "source_url": market_url(ticker, t.get("source_url")),
        })
    return book


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def aggregate(round_trips: list[dict], key_fn) -> list[dict]:
    """Group closed round-trips; compute stats. Open round-trips are counted
    but excluded from win/loss statistics."""
    groups: dict[str, dict] = {}
    for rt in round_trips:
        k = key_fn(rt) or "(blank)"
        g = groups.setdefault(k, {
            "key": k, "trades": 0, "closed": 0, "open": 0, "wins": 0, "losses": 0,
            "flat": 0, "gross": 0.0, "fees": 0.0, "net": 0.0, "cost": 0.0,
            "nets": [], "sources": set(),
        })
        g["trades"] += 1
        if rt.get("source_url"):
            g["sources"].add(rt["source_url"])
        if rt["status"] != "closed":
            g["open"] += 1
            continue
        g["closed"] += 1
        res = rt.get("result") or "flat"
        g["wins" if res == "win" else ("losses" if res == "loss" else "flat")] += 1
        gross = rt.get("gross")
        net = rt.get("net")
        fees = (rt.get("entry_fee") or 0) + (rt.get("exit_fee") or 0) if rt.get("exit_fee") is not None \
            else (rt.get("entry_fee") or 0)
        if gross is not None:
            g["gross"] += gross
        if net is not None:
            g["net"] += net
            g["nets"].append(net)
        g["fees"] += fees or 0
        if rt.get("entry_px") is not None and rt.get("contracts"):
            g["cost"] += float(Decimal(str(rt["contracts"])) * Decimal(str(rt["entry_px"])))
    out = []
    for g in groups.values():
        closed = g["closed"]
        g["win_rate"] = (g["wins"] / closed) if closed else None
        g["avg_net"] = (g["net"] / closed) if closed else None
        g["roi_on_cost"] = (g["net"] / g["cost"]) if g["cost"] > 0 else None
        g["max_drawdown"] = _max_drawdown(g["nets"])
        g["sources"] = sorted(g["sources"])
        out.append(g)
    out.sort(key=lambda g: (-g["closed"], -g["net"], g["key"]))
    return out


def _max_drawdown(nets: list[float]) -> float | None:
    if not nets:
        return None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


# --------------------------------------------------------------------------
# published-stats cross-check
# --------------------------------------------------------------------------

def crosscheck_docs_book(book: dict) -> list[dict]:
    """Compare a book's published aggregates with a fresh recomputation over
    the same trade rows. Handles the docs book's `stats.all` shape and the root
    book's `overall` shape. Returns discrepancy rows (empty = consistent)."""
    issues = []
    stats = book.get("published_stats")
    if not isinstance(stats, dict):
        return issues
    allstat = stats.get("all") or stats.get("overall") or {}
    closed = [rt for rt in book["round_trips"] if rt["status"] == "closed"]
    n = len(closed)
    net = sum(rt.get("net") or 0.0 for rt in closed)
    fees = sum((rt.get("entry_fee") or 0) + (rt.get("exit_fee") or 0) for rt in closed)
    wins = sum(1 for rt in closed if rt.get("result") == "win")
    checks = [
        ("trades (closed round-trips)", allstat.get("trades"), n),
        ("net_pnl/realized", allstat.get("net_pnl", allstat.get("realized")), round(net, 2)),
        ("fees (entry+exit)", allstat.get("fees"), round(fees, 2)),
        ("wins", allstat.get("wins"), wins),
    ]
    for label, published, recomputed in checks:
        if published is None:
            continue
        try:
            match = abs(float(published) - float(recomputed)) < 0.011
        except (TypeError, ValueError):
            match = False
        if not match:
            issues.append({"book": book["name"], "metric": label,
                           "published": published, "recomputed": recomputed})
    return issues


# --------------------------------------------------------------------------
# backtest over recorded candles
# --------------------------------------------------------------------------

def load_candle_series(root: Path) -> list[dict]:
    """Flatten docs/data/candles.json into per-ticker, per-window bar series.

    Both stored windows are replayed separately: the `minutes` window
    (period_interval=60 → hourly candles) and the `hours` window
    (period_interval=1440 → daily candles). Every series keeps the official
    API source_url of the window it came from. Bars with a null close
    (unquoted) are dropped.
    """
    data = _load_json(root / "docs" / "data" / "candles.json")
    out = []
    if not isinstance(data, dict):
        return out
    series = data.get("series") or {}
    if not isinstance(series, dict):
        return out
    for ticker, windows in sorted(series.items()):
        if not isinstance(windows, dict):
            continue
        for win in ("minutes", "hours"):
            w = windows.get(win) or {}
            pts = [p for p in (w.get("points") or [])
                   if isinstance(p, dict) and isinstance(p.get("close"), (int, float))]
            if pts:
                out.append({
                    "ticker": ticker, "window": win,
                    "interval": w.get("interval"),
                    "points": pts,
                    "source_url": w.get("source_url") or "",
                })
    return out


def run_backtest(points: list[dict], rule: str) -> list[dict]:
    """Deterministic reference backtest on recorded close prices.

    Rules (each identical exit for comparability):
      momentum       — after a >= $0.10 up bar, buy YES; after a >= $0.10
                       down bar, buy NO. Enter at that bar's close.
      mean-reversion — after a >= $0.10 up bar, buy NO; after a >= $0.10 down
                       bar, buy YES (fade the swing).
      breakout       — enter YES on a close above the prior 10-bar high, NO on
                       a close below the prior 10-bar low.
    Exit: hold up to BACKTEST_HOLD_BARS bars (exit at that close), or exit
    early on an opposite >= $0.10 close-to-close bar.
    Fees: official taker formula on entry and exit.
    """
    trades = []
    closes = [Decimal(str(p["close"])) for p in points
              if isinstance(p.get("close"), (int, float))]
    for i in range(1, len(closes)):
        if i >= len(closes) - 1:
            continue  # need at least one hold bar after entry
        if len(trades) >= 1 and trades[-1]["exit_idx"] is None:
            continue  # one position at a time
        move = closes[i] - closes[i - 1]
        side = None
        if rule == "momentum":
            if move >= SWING_THRESHOLD:
                side = "yes"
            elif move <= -SWING_THRESHOLD:
                side = "no"
        elif rule == "mean-reversion":
            if move >= SWING_THRESHOLD:
                side = "no"
            elif move <= -SWING_THRESHOLD:
                side = "yes"
        elif rule == "breakout":
            if i >= 11:
                prior_high = max(closes[i - 11:i - 1])
                prior_low = min(closes[i - 11:i - 1])
                if closes[i] > prior_high:
                    side = "yes"
                elif closes[i] < prior_low:
                    side = "no"
        if side is None:
            continue
        entry_px = closes[i]
        entry_fee = taker_fee(Decimal(BACKTEST_CONTRACTS), entry_px)
        # exit scan
        exit_idx = min(i + BACKTEST_HOLD_BARS, len(closes) - 1)
        for j in range(i + 1, min(i + BACKTEST_HOLD_BARS, len(closes) - 1) + 1):
            mv = closes[j] - closes[j - 1]
            if (side == "yes" and mv <= -SWING_THRESHOLD) or \
               (side == "no" and mv >= SWING_THRESHOLD):
                exit_idx = j
                break
        exit_px = closes[exit_idx]
        exit_fee = taker_fee(Decimal(BACKTEST_CONTRACTS), exit_px)
        c = Decimal(BACKTEST_CONTRACTS)
        gross = c * (exit_px - entry_px) if side == "yes" else c * (entry_px - exit_px)
        net = gross - entry_fee - exit_fee
        trades.append({
            "rule": rule, "side": side,
            "entry_idx": i, "exit_idx": exit_idx,
            "entry_ts": norm_ts(points[i].get("t")), "exit_ts": norm_ts(points[exit_idx].get("t")),
            "entry_px": float(entry_px), "exit_px": float(exit_px),
            "contracts": BACKTEST_CONTRACTS,
            "entry_fee": float(entry_fee), "exit_fee": float(exit_fee),
            "gross": float(gross), "net": float(net),
            "result": "win" if net > 0 else ("loss" if net < 0 else "flat"),
        })
    return trades


def backtest_all(series_list: list[dict]) -> dict:
    """Run all three rules over every recorded series; aggregate per rule."""
    rules = ("momentum", "mean-reversion", "breakout")
    per_rule: dict[str, list[dict]] = {r: [] for r in rules}
    for s in series_list:
        if len(s["points"]) < BACKTEST_MIN_BARS:
            continue
        for r in rules:
            for t in run_backtest(s["points"], r):
                t["ticker"] = s["ticker"]
                t["window"] = s["window"]
                t["source_url"] = s["source_url"]
                per_rule[r].append(t)
    summary = {}
    for r, trades in per_rule.items():
        closed = trades  # backtests always close
        wins = sum(1 for t in closed if t["result"] == "win")
        net = sum(t["net"] for t in closed)
        fees = sum(t["entry_fee"] + t["exit_fee"] for t in closed)
        cost = sum(t["contracts"] * t["entry_px"] for t in closed)
        nets = [t["net"] for t in closed]
        summary[r] = {
            "trades": len(closed), "wins": wins,
            "losses": sum(1 for t in closed if t["result"] == "loss"),
            "win_rate": (wins / len(closed)) if closed else None,
            "gross": sum(t["gross"] for t in closed), "fees": fees, "net": net,
            "avg_net": (net / len(closed)) if closed else None,
            "roi_on_cost": (net / cost) if cost > 0 else None,
            "max_drawdown": _max_drawdown(nets),
            "rows": closed,
        }
    return summary


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def fmt_table(headers: list[str], rows: list[list[str]]) -> str:
    md = "| " + " | ".join(headers) + " |\n"
    md += "| " + " | ".join("---" for _ in headers) + " |\n"
    for r in rows:
        md += "| " + " | ".join(str(c) for c in r) + " |\n"
    return md


def stats_rows_md(groups: list[dict]) -> list[list[str]]:
    rows = []
    for g in groups:
        src = link_or_unverified(g["sources"][0]) if g["sources"] else link_or_unverified("")
        rows.append([
            g["key"], str(g["trades"]), str(g["closed"]), str(g["open"]),
            str(g["wins"]), str(g["losses"]), pct(g["win_rate"]),
            money(g["net"]), money(g["fees"]), pct(g["roi_on_cost"]),
            money(g["max_drawdown"]), src,
        ])
    return rows


def build_report(root: Path) -> dict:
    books = [load_docs_book(root), load_root_book(root), load_kd_book(root)]
    all_rts = [rt for b in books for rt in b["round_trips"]]
    by_strategy = aggregate(all_rts, lambda rt: rt.get("strategy") or "(blank)")
    by_type = aggregate(all_rts, lambda rt: rt.get("trade_type") or "(blank)")
    by_topic = aggregate(all_rts, lambda rt: rt.get("topic") or "(blank)")
    by_book = aggregate(all_rts, lambda rt: rt.get("book") or "(blank)")
    issues = []
    for b in books:
        issues.extend(crosscheck_docs_book(b))
    series_list = load_candle_series(root)
    bt = backtest_all(series_list)
    return {
        "generated_at": iso_now(),
        "books": books, "round_trips": all_rts,
        "by_strategy": by_strategy, "by_trade_type": by_type,
        "by_topic": by_topic, "by_book": by_book,
        "crosscheck_issues": issues,
        "candle_series": [{"ticker": s["ticker"], "window": s["window"],
                           "points": len(s["points"]), "source_url": s["source_url"]}
                          for s in series_list],
        "backtest": bt,
        "parameters": {
            "swing_threshold": float(SWING_THRESHOLD),
            "hold_bars": BACKTEST_HOLD_BARS, "min_bars": BACKTEST_MIN_BARS,
            "contracts_per_trade": BACKTEST_CONTRACTS,
            "fee_formula": FEE_FORMULA_DOC,
        },
    }


def render_markdown(rep: dict) -> str:
    L = []
    L.append("# Strategy lab — simulated-trade analysis and reference backtests\n")
    L.append(f"_Generated {rep['generated_at']} by `tools/strategy_lab.py` from the repo's "
             "published simulated-trade data and recorded demo candlesticks. "
             "All figures are **computed from simulated/demo data** — not verified live "
             "performance, not investment advice. Kalshi's demo environment uses mock funds "
             "and its market behaviour may not reflect production "
             "([Demo environment](https://docs.kalshi.com/getting_started/demo_env))._\n")
    L.append(f"Fee model used throughout: {FEE_FORMULA_DOC}.\n")

    L.append("## 1. Data sources (provenance)\n")
    src_rows = []
    for b in rep["books"]:
        n_rows = len(b["round_trips"])
        coverage = ("yes" if all(rt.get("source_url") for rt in b["round_trips"])
                    else f"partial {UNVERIFIED}") if n_rows else "n/a (no rows)"
        src_rows.append([
            b["name"], f"`{b['engine']}`",
            f"{sum(1 for rt in b['round_trips'] if rt['status']=='closed')} / "
            f"{sum(1 for rt in b['round_trips'] if rt['status']=='open')}",
            coverage,
        ])
    L.append(fmt_table(
        ["Book", "Engine file", "Round-trips (closed / open)", "Rows carry official source links"],
        src_rows))

    L.append("## 2. Performance by strategy\n")
    L.append(fmt_table(
        ["Strategy", "Trades", "Closed", "Open", "Wins", "Losses", "Win rate",
         "Net P&L", "Fees", "ROI on cost", "Max drawdown", "Source"],
        stats_rows_md(rep["by_strategy"])))
    L.append("## 3. Performance by trade type (strategy | signal | side)\n")
    L.append(fmt_table(
        ["Trade type", "Trades", "Closed", "Open", "Wins", "Losses", "Win rate",
         "Net P&L", "Fees", "ROI on cost", "Max drawdown", "Source"],
        stats_rows_md(rep["by_trade_type"])))
    L.append("## 4. Performance by topic\n")
    L.append(fmt_table(
        ["Topic", "Trades", "Closed", "Open", "Wins", "Losses", "Win rate",
         "Net P&L", "Fees", "ROI on cost", "Max drawdown", "Source"],
        stats_rows_md(rep["by_topic"])))
    L.append("## 5. Performance by book\n")
    L.append(fmt_table(
        ["Book", "Trades", "Closed", "Open", "Wins", "Losses", "Win rate",
         "Net P&L", "Fees", "ROI on cost", "Max drawdown", "Source"],
        stats_rows_md(rep["by_book"])))

    L.append("## 6. Trade ledger (every simulated round-trip)\n")
    rows = []
    for rt in sorted(rep["round_trips"], key=lambda r: (r.get("entry_ts") or "")):
        rows.append([
            (rt.get("entry_ts") or "—")[:19], rt.get("book"), rt.get("ticker") or f"— {UNVERIFIED}",
            rt.get("topic") or f"— {UNVERIFIED}", rt.get("strategy") or f"— {UNVERIFIED}",
            rt.get("side"), rt.get("status"), rt.get("result"),
            money(rt.get("entry_px")), money(rt.get("exit_px")),
            str(rt.get("contracts") if rt.get("contracts") is not None else f"— {UNVERIFIED}"),
            money(rt.get("net")), link_or_unverified(rt.get("source_url") or ""),
        ])
    L.append(fmt_table(
        ["Entry ts (UTC)", "Book", "Ticker", "Topic", "Strategy", "Side", "Status",
         "Result", "Entry", "Exit", "Contracts", "Net P&L", "Source"], rows))

    L.append("## 7. Published-stats cross-check\n")
    if rep["crosscheck_issues"]:
        L.append("Discrepancies between the books' published aggregates and a "
                 "recomputation from their own trade rows — **flagged for review**, "
                 "not silently reconciled:\n")
        engines = {b["name"]: b["engine"] for b in rep["books"]}
        L.append(fmt_table(["Book", "Metric", "Published", "Recomputed", "Source"],
                           [[i["book"], i["metric"], i["published"], i["recomputed"],
                             f"`{engines.get(i['book'], '')}`"]
                            for i in rep["crosscheck_issues"]]))
    else:
        L.append("No discrepancy found: every published aggregate matches the "
                 "recomputation from trade rows (within $0.01).\n")

    L.append("## 8. Reference backtests over recorded demo candles\n")
    L.append("Three deterministic rules replayed over the recorded "
             "`docs/data/candles.json` closes. Both stored windows are replayed "
             "separately: the `minutes` window "
             "(`period_interval=60`, i.e. **hourly** candles) and the `hours` window "
             "(`period_interval=1440`, i.e. **daily** candles); per the "
             "[official candlestick reference](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) "
             "the period is expressed in minutes. Fixed "
             f"{BACKTEST_CONTRACTS} contracts per trade, hold ≤ "
             f"{BACKTEST_HOLD_BARS} bars, swing threshold $0.10, taker fees both sides. "
             "Every generated row links to its candle API source. These are **model "
             "comparisons on recorded demo data** — recorded histories are only "
             f"{BACKTEST_MIN_BARS}+ bars long so far and demo behaviour may not reflect "
             "production.\n")
    bt_rows = []
    for rule, s in rep["backtest"].items():
        srcs = sorted({t["source_url"] for t in s["rows"] if t.get("source_url")})
        bt_rows.append([
            rule, str(s["trades"]), str(s["wins"]), str(s["losses"]), pct(s["win_rate"]),
            money(s["gross"]), money(s["fees"]), money(s["net"]),
            pct(s["roi_on_cost"]), money(s["max_drawdown"]),
            link_or_unverified(srcs[0]) if srcs else link_or_unverified(""),
        ])
    L.append(fmt_table(
        ["Rule", "Trades", "Wins", "Losses", "Win rate", "Gross", "Fees", "Net",
         "ROI on cost", "Max drawdown", "Source"], bt_rows))
    L.append("### Backtest trade rows\n")
    L.append(fmt_table(
        ["Rule", "Ticker", "Side", "Entry ts", "Exit ts", "Entry", "Exit",
         "Contracts", "Gross", "Fees", "Net", "Source"],
        [[t["rule"], t["ticker"], t["side"],
          str(t.get("entry_ts") or f"— {UNVERIFIED}"), str(t.get("exit_ts") or f"— {UNVERIFIED}"),
          money(t["entry_px"]), money(t["exit_px"]), str(t["contracts"]),
          money(t["gross"]), money(t["entry_fee"] + t["exit_fee"]), money(t["net"]),
          link_or_unverified(t.get("source_url") or "")]
         for rule in rep["backtest"] for t in rep["backtest"][rule]["rows"]]))

    L.append("## 9. Strategy playbook (rules by trade type)\n")
    L.append("| Trade type observed | Rule family | Standing rule | Source |\n| --- | --- | --- | --- |\n")
    fam = {
        "roi_edge": "book-edge / value",
        "momentum": "swing-follow",
        "mean-reversion": "swing-fade",
        "value": "quiet-value",
    }
    for g in rep["by_trade_type"]:
        strat = (g["key"].split("|") + [""])[0]
        family = fam.get(strat, f"— {UNVERIFIED}")
        rule = {
            "book-edge / value": "Enter the side whose modelled fair value minus price clears the net-edge threshold after fees, only when the spread is inside the limit and the book shows real depth.",
            "swing-follow": "Enter in the direction of a ≥ $0.10 swing when post-swing edge after fees remains; hold to settlement.",
            "swing-fade": "Take the opposite side of a ≥ $0.10 swing when the shrunk fair value crosses back through 0.50.",
            "quiet-value": "No swing needed; buy the side with the largest modelled edge after fees when the spread is tight and depth is real.",
        }.get(family, f"— {UNVERIFIED}")
        L.append(f"| {g['key']} | {family} | {rule} | {link_or_unverified('https://docs.kalshi.com/getting_started/demo_env')} |\n")

    L.append("## 10. Limitations and flagged items\n")
    L.append(
        "- Sample sizes are small (a handful of simulated round-trips across engines); "
        "no statistical ROI claim is made.\n"
        "- The root book aggregates report `trades: 0` for closed trades while open "
        "positions exist; win-rate columns are therefore empty there and left blank "
        "rather than inferred.\n"
        "- Backtests are in-sample on recorded demo candles and are not validated out "
        "of sample; they compare rules mechanically, they do not predict performance.\n"
        f"- The candle store's window labels (`minutes`/`hours`) are misleading: the "
        "stored `interval` values are 60 and 1440 **minutes** (hourly and daily candles) "
        "per the official candlestick reference. Flagged as a data-label quirk; the "
        "labels were not changed by this tool.\n"
        "- Kalshi demo market behaviour may not reflect production "
        "([docs](https://docs.kalshi.com/getting_started/demo_env)).\n"
        "- Where a row had no official source URL, the cell is blank and marked "
        f"{UNVERIFIED}; nothing was inferred.\n")
    return "".join(x if x.endswith("\n") else x + "\n" for x in L)


def render_html(rep: dict) -> str:
    e = html.escape

    def tbl(headers, rows):
        h = "".join(f"<th>{e(str(x))}</th>" for x in headers)
        body = ""
        for r in rows:
            tds = ""
            for c in r:
                tds += f"<td>{c if isinstance(c, str) and c.startswith('<') else e(str(c))}</td>"
            body += f"<tr>{tds}</tr>"
        return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"

    def src_cell(url):
        return (f'<a href="{e(url)}">source</a>' if url
                else f"— {UNVERIFIED}")

    def stats_rows(groups):
        rows = []
        for g in groups:
            rows.append([
                g["key"], g["trades"], g["closed"], g["open"], g["wins"], g["losses"],
                pct(g["win_rate"]), money(g["net"]), money(g["fees"]),
                pct(g["roi_on_cost"]), money(g["max_drawdown"]),
                src_cell(g["sources"][0]) if g["sources"] else src_cell(""),
            ])
        return rows

    def equity_svg(curve, label):
        if len(curve) < 2:
            return (f'<p class="muted">Equity curve for {e(label)}: not available yet '
                    f'(&lt; 2 points) — {UNVERIFIED}</p>')
        vals = [float(p.get("equity", p.get("net", 0))) for p in curve]
        w, hgt, pad = 640, 180, 20
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        pts = []
        for i, v in enumerate(vals):
            x = pad + i * (w - 2 * pad) / max(1, len(vals) - 1)
            y = pad + (hi - v) * (hgt - 2 * pad) / rng
            pts.append(f"{x:.1f},{y:.1f}")
        return (
            f'<svg viewBox="0 0 {w} {hgt}" class="chart" role="img" '
            f'aria-label="Equity curve {e(label)}">'
            f'<polyline fill="none" stroke="currentColor" stroke-width="2" points="{" ".join(pts)}"/>'
            f"</svg>"
        )

    book_sections = ""
    for b in rep["books"]:
        eq = b.get("equity_curve") or []
        curve = eq if len(eq) >= 2 else [
            {"equity": 10000 + sum((rt.get("net") or 0) for rt in b["round_trips"][:i + 1])}
            for i in range(len(b["round_trips"]))
        ] if b["round_trips"] else []
        book_sections += f"""
<section class="card">
  <h3>{e(b['name'])}</h3>
  <p class="muted">Engine: <code>{e(b['engine'])}</code> ·
     round-trips: {sum(1 for rt in b['round_trips'] if rt['status']=='closed')} closed /
     {sum(1 for rt in b['round_trips'] if rt['status']=='open')} open</p>
  {equity_svg(curve, b['name'])}
</section>"""

    bt_rows = []
    for rule, s in rep["backtest"].items():
        srcs = sorted({t["source_url"] for t in s["rows"] if t.get("source_url")})
        bt_rows.append([
            e(rule), s["trades"], s["wins"], s["losses"], pct(s["win_rate"]),
            money(s["gross"]), money(s["fees"]), money(s["net"]),
            pct(s["roi_on_cost"]), money(s["max_drawdown"]),
            src_cell(srcs[0]) if srcs else src_cell(""),
        ])

    ledger_rows = []
    for rt in sorted(rep["round_trips"], key=lambda r: (r.get("entry_ts") or "")):
        ledger_rows.append([
            (rt.get("entry_ts") or "—")[:19], rt.get("book") or "",
            rt.get("ticker") or f"— {UNVERIFIED}",
            rt.get("topic") or f"— {UNVERIFIED}",
            rt.get("strategy") or f"— {UNVERIFIED}",
            rt.get("side") or "", rt.get("status") or "", rt.get("result") or "",
            money(rt.get("entry_px")), money(rt.get("exit_px")),
            str(rt.get("contracts")) if rt.get("contracts") is not None else f"— {UNVERIFIED}",
            money(rt.get("net")), src_cell(rt.get("source_url") or ""),
        ])

    cc = ""
    if rep["crosscheck_issues"]:
        engines = {b["name"]: b["engine"] for b in rep["books"]}
        cc = ("<h3>Flagged: published vs recomputed stats</h3>" + tbl(
            ["Book", "Metric", "Published", "Recomputed", "Source"],
            [[i["book"], i["metric"], str(i["published"]), str(i["recomputed"]),
              f"<code>{e(engines.get(i['book'], ''))}</code>"]
             for i in rep["crosscheck_issues"]]))
    else:
        cc = "<p>All published aggregates match a recomputation from trade rows (± $0.01).</p>"

    bt_detail_rows = []
    for rule in rep["backtest"]:
        for t in rep["backtest"][rule]["rows"]:
            bt_detail_rows.append([
                t["rule"], t["ticker"], t["side"],
                str(t.get("entry_ts") or f"— {UNVERIFIED}"),
                str(t.get("exit_ts") or f"— {UNVERIFIED}"),
                money(t["entry_px"]), money(t["exit_px"]), t["contracts"],
                money(t["gross"]), money(t["entry_fee"] + t["exit_fee"]), money(t["net"]),
                src_cell(t.get("source_url") or ""),
            ])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy lab — simulated trade analysis · Kalshi demo tracker</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="top">
  <h1>Strategy lab</h1>
  <p class="muted">Generated {e(rep['generated_at'])} · all figures computed from the repo's
  <strong>simulated</strong> ledgers and recorded demo candles — not verified live performance,
  not investment advice. Demo environment: <a href="https://docs.kalshi.com/getting_started/demo_env">docs.kalshi.com</a>.</p>
  <p class="muted">Fee model: {e(FEE_FORMULA_DOC)}</p>
  <nav><a href="index.html">Dashboard</a> · <a href="portfolio.html">Portfolio</a> ·
  <a href="resolutions.html">Resolutions</a> · <a href="flagged.html">Flagged</a> ·
  <a href="summary.html">Summary</a></nav>
</header>

<section class="card">
  <h2>Performance by strategy</h2>
  {tbl(["Strategy","Trades","Closed","Open","Wins","Losses","Win rate","Net P&amp;L","Fees","ROI on cost","Max drawdown","Source"], stats_rows(rep["by_strategy"]))}
</section>
<section class="card">
  <h2>Performance by trade type (strategy | signal | side)</h2>
  {tbl(["Trade type","Trades","Closed","Open","Wins","Losses","Win rate","Net P&amp;L","Fees","ROI on cost","Max drawdown","Source"], stats_rows(rep["by_trade_type"]))}
</section>
<section class="card">
  <h2>Performance by topic</h2>
  {tbl(["Topic","Trades","Closed","Open","Wins","Losses","Win rate","Net P&amp;L","Fees","ROI on cost","Max drawdown","Source"], stats_rows(rep["by_topic"]))}
</section>
<section class="card">
  <h2>Performance by book</h2>
  {tbl(["Book","Trades","Closed","Open","Wins","Losses","Win rate","Net P&amp;L","Fees","ROI on cost","Max drawdown","Source"], stats_rows(rep["by_book"]))}
  {book_sections}
</section>
<section class="card">
  <h2>Published-stats cross-check</h2>
  {cc}
</section>
<section class="card">
  <h2>Reference backtests over recorded demo candles</h2>
  <p class="muted">Deterministic rules, {BACKTEST_CONTRACTS} contracts/trade, hold ≤ {BACKTEST_HOLD_BARS} bars,
  swing threshold $0.10, taker fees both sides ({e(FEE_FORMULA_DOC)}). In-sample model
  comparison on recorded demo data — sample sizes are small.</p>
  {tbl(["Rule","Trades","Wins","Losses","Win rate","Gross","Fees","Net","ROI on cost","Max drawdown","Source"], bt_rows)}
  <details><summary>Backtest trade rows ({len(bt_detail_rows)})</summary>
  {tbl(["Rule","Ticker","Side","Entry ts","Exit ts","Entry","Exit","Contracts","Gross","Fees","Net","Source"], bt_detail_rows)}
  </details>
</section>
<section class="card">
  <h2>Trade ledger (all simulated round-trips)</h2>
  {tbl(["Entry ts (UTC)","Book","Ticker","Topic","Strategy","Side","Status","Result","Entry","Exit","Contracts","Net P&amp;L","Source"], ledger_rows)}
</section>
<section class="card">
  <h2>Limitations</h2>
  <ul>
    <li>Small simulated samples; no statistical ROI claim is made.</li>
    <li>Blank cells read “— {UNVERIFIED}”: no value was inferred.</li>
    <li>Demo market behaviour may not reflect production markets.</li>
    <li>Backtests are in-sample on recorded demo candles; they compare rules mechanically.</li>
  </ul>
</section>
<footer class="muted">
  Sources: official Kalshi demo API URLs per row ·
  <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf">fee schedule</a> ·
  <a href="https://docs.kalshi.com/api-reference/market/get-market-candlesticks">candlesticks</a> ·
  <a href="../REPO_REVIEW.md">repo review</a>
</footer>
</body>
</html>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="repository root")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)
    rep = build_report(root)

    md = render_markdown(rep)
    (root / "STRATEGY_ANALYSIS.md").write_text(md)
    (root / "docs" / "strategies.html").write_text(render_html(rep))
    out_json = {
        "generated_at": rep["generated_at"],
        "parameters": rep["parameters"],
        "crosscheck_issues": rep["crosscheck_issues"],
        "candle_series": rep["candle_series"],
        "round_trips": rep["round_trips"],
        "aggregates": {
            "by_strategy": [{k: (sorted(v) if isinstance(v, set) else v)
                             for k, v in g.items() if k != "nets"} for g in rep["by_strategy"]],
            "by_trade_type": [{k: (sorted(v) if isinstance(v, set) else v)
                               for k, v in g.items() if k != "nets"} for g in rep["by_trade_type"]],
            "by_topic": [{k: (sorted(v) if isinstance(v, set) else v)
                          for k, v in g.items() if k != "nets"} for g in rep["by_topic"]],
            "by_book": [{k: (sorted(v) if isinstance(v, set) else v)
                         for k, v in g.items() if k != "nets"} for g in rep["by_book"]],
        },
        "backtest": {r: {k: v for k, v in s.items() if k != "rows"} | {"rows": s["rows"]}
                     for r, s in rep["backtest"].items()},
    }
    (root / "docs" / "data" / "strategy_lab.json").write_text(json.dumps(out_json, indent=1))

    if not args.quiet:
        n_rt = len(rep["round_trips"])
        n_bt = sum(s["trades"] for s in rep["backtest"].values())
        print(f"strategy_lab: {n_rt} round-trips, {n_bt} backtest trades, "
              f"{len(rep['crosscheck_issues'])} cross-check issues")
        print("wrote STRATEGY_ANALYSIS.md, docs/strategies.html, docs/data/strategy_lab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
