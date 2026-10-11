#!/usr/bin/env python3
"""
Polymarket resolution-yield monitor (public Gamma + CLOB APIs, no key needed).

What it does:
  Scans ACTIVE markets across all categories and looks for the side priced near $1 (an
  almost-certain outcome). For each candidate it computes the yield, the ANNUALISED yield
  (important for slow markets), the order-book depth (how much can really be filled) and
  alerts. Not only live sport: slow markets (politics / macro / elections) show up with
  "when" in days or weeks and a much lower annualised figure.

Price bands:
  sport + esports      -> 97-99c (safer: less upset risk, closer to the end)
  politics / macro etc -> 95-99c (slow resolution, usually fee-free)

Not a latency race: the 99.9c bot zone is cut off at the top (--hi 0.99). The 95-99c band is
where price and capital decide, not milliseconds.

NOTE: the 12-month backtest in ../polymarket_yield found roughly ZERO yield before fees for
this pattern (one upset at 97c wipes ~32 winners). Treat the output as a candidate list for
further research, not as a signal.

Usage:
    python resolution_monitor.py            # Ctrl+C to stop
    python resolution_monitor.py --poll 120 --min-fill 1000 --once

Standard library only.
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

FAST = 0.97  # sport + esports
SLOW = 0.95  # politics / macro / everything slow
TAGS = {
    # --- sport + esports: 97-99c ---
    "sports": FAST, "soccer": FAST, "football": FAST, "basketball": FAST, "nba": FAST,
    "mlb": FAST, "baseball": FAST, "nhl": FAST, "hockey": FAST, "tennis": FAST,
    "cricket": FAST, "ufc": FAST, "mma": FAST, "golf": FAST,
    "esports": FAST, "counter-strike-2": FAST, "dota-2": FAST,
    "league-of-legends": FAST, "valorant": FAST,
    # --- slow: 95-99c ---
    "politics": SLOW, "elections": SLOW, "geopolitics": SLOW, "iran": SLOW,
    "middle-east": SLOW, "finance": SLOW, "economy": SLOW, "economics": SLOW,
    "crypto": SLOW, "tech": SLOW, "pop-culture": SLOW, "culture": SLOW,
    "weather": SLOW, "world": SLOW,
}
GROUP = {FAST: "sport/esp", SLOW: "slow"}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--poll", type=int, default=60, help="seconds between scans (default 60)")
    ap.add_argument("--hi", type=float, default=0.99, help="upper price bound, cuts off the bot zone (default 0.99)")
    ap.add_argument("--max-fill-price", type=float, default=0.992,
                    help="count book depth only up to this ask price (default 0.992)")
    ap.add_argument("--min-fill", type=float, default=300, help="hide candidates with less fillable $ than this (default 300)")
    ap.add_argument("--events-per-tag", type=int, default=80, help="events to pull per tag (default 80)")
    ap.add_argument("--log", default="resolution_alerts.log", help="alert log file")
    ap.add_argument("--once", action="store_true", help="run a single scan and exit")
    return ap.parse_args()


def http(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(1 + attempt)
                continue
            return None
        except Exception:
            time.sleep(1 + attempt)
            continue
    return None


def arr(x):
    if isinstance(x, list):
        return x
    try:
        return json.loads(x)
    except Exception:
        return []


def fl(x):
    try:
        return float(x)
    except Exception:
        return None


def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(s):
    if not s:
        return None
    try:
        s = s.strip().replace(" ", "T", 1)
        s = re.sub(r"([+-]\d{2})$", r"\1:00", s)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def book_depth(token_id, max_price):
    """Shares and $ that can be BOUGHT from asks priced <= max_price."""
    b = http(f"{CLOB}/book?token_id={token_id}", timeout=6)
    if not b or "asks" not in b:
        return 0.0, 0.0, None
    shares = cost = 0.0
    best = None
    for lvl in b["asks"]:
        p = fl(lvl.get("price"))
        s = fl(lvl.get("size"))
        if p is None or s is None:
            continue
        if best is None or p < best:
            best = p
        if p <= max_price:
            shares += s
            cost += p * s
    return shares, cost, best


def scan(args):
    seen_events = set()
    cands = []
    for tag, lo in TAGS.items():
        evs = http(f"{GAMMA}/events?closed=false&active=true&related_tags=true"
                   f"&limit={args.events_per_tag}&tag_slug={tag}")
        if not isinstance(evs, list):
            continue
        for e in evs:
            eid = e.get("id")
            if eid in seen_events:
                continue
            seen_events.add(eid)
            for m in (e.get("markets") or []):
                if m.get("closed") or m.get("umaResolutionStatus") == "resolved":
                    continue
                prices = [fl(x) for x in arr(m.get("outcomePrices"))]
                outs = arr(m.get("outcomes"))
                toks = arr(m.get("clobTokenIds"))
                if len(prices) < 2 or len(outs) < 2 or len(toks) < 2:
                    continue
                idx = 0 if (prices[0] or 0) >= (prices[1] or 0) else 1  # the near-$1 side
                p = prices[idx]
                if p is None or not (lo <= p <= args.hi):
                    continue
                shares, cost, best = book_depth(toks[idx], args.max_fill_price)
                liq = fl(m.get("liquidityClob")) or fl(m.get("liquidityNum")) or 0
                if cost >= args.min_fill:        # exact depth from the book
                    avg = cost / shares
                    fill_usd = cost
                    src = "book"
                elif liq >= args.min_fill:       # book unavailable -> estimate from liquidity
                    avg = p
                    fill_usd = liq
                    src = "~liq"
                else:
                    continue
                yld = (1 / avg - 1) if avg else 0
                profit = fill_usd * yld
                end = parse_ts(m.get("endDate"))
                gst = parse_ts(m.get("gameStartTime"))
                live = gst is not None and gst <= now_utc()
                hrs = ((end - now_utc()).total_seconds() / 3600) if end else None
                ann = (yld / (hrs / 24 / 365)) if (hrs and hrs > 0) else None
                fee = ((m.get("feeSchedule") or {}).get("rate")) or 0
                cands.append({
                    "title": (e.get("title") or "")[:42], "side": str(outs[idx])[:14],
                    "price": round(avg, 4), "yldPct": round(yld * 100, 2),
                    "annPct": round(ann * 100) if ann else None,
                    "fillUSD": round(fill_usd), "profitUSD": round(profit), "src": src,
                    "grp": GROUP[lo], "live": live,
                    "hrs": round(hrs, 1) if hrs is not None else None,
                    "fee": fee, "slug": e.get("slug"),
                })
    cands.sort(key=lambda c: c["yldPct"] * c["fillUSD"], reverse=True)
    return cands


def when(c):
    if c["live"]:
        return "LIVE"
    if c["hrs"] is None:
        return "?"
    h = c["hrs"]
    return f"{h:.0f}h" if h < 48 else f"{h / 24:.0f}d"


def beep():
    try:
        import winsound  # Windows only
        winsound.Beep(1000, 160)
        winsound.Beep(1300, 160)
    except Exception:
        print("\a", end="")


def main():
    args = parse_args()
    print(f"Resolution monitor. Bands: sport/esports {FAST * 100:.0f}-{args.hi * 100:.0f}c, "
          f"slow (politics/macro/...) {SLOW * 100:.0f}-{args.hi * 100:.0f}c.")
    print(f"Min fill ${args.min_fill:g}. Bot zone above {args.hi} cut off. Poll {args.poll}s. (Ctrl+C to stop)")
    print("Sizing reminder: one upset at 97c wipes ~32 winners; one match in several sub-markets = ONE risk.\n")
    alerted = set()
    while True:
        try:
            cands = scan(args)
            ts = datetime.now().strftime("%H:%M:%S")
            if cands:
                print(f"\n[{ts}] near-certain candidates (top by yield x depth):")
                print(f"  {'price':>5} {'yld%':>5} {'annual':>7} {'fill$':>8} {'when':>6} {'fee':>4} {'group':>9} {'src':>4}  event / side")
                for c in cands[:20]:
                    ann = f"{c['annPct']}%" if c['annPct'] is not None else "-"
                    print(f"  {c['price'] * 100:5.1f} {c['yldPct']:5.2f} {ann:>7} {c['fillUSD']:8} {when(c):>6} "
                          f"{c['fee'] * 100:3.0f}% {c['grp']:>9} {c['src']:>4}  {c['title']} / {c['side']}")
                    key = c["slug"] + "|" + c["side"]
                    if key not in alerted and c["yldPct"] >= 1.0:
                        alerted.add(key)
                        line = (f"{ts}  {c['title']} / {c['side']} @ {c['price'] * 100:.1f}c, yield {c['yldPct']}%, "
                                f"annual {c['annPct']}%, fill ${c['fillUSD']}, {when(c)}, "
                                f"polymarket.com/event/{c['slug']}")
                        try:
                            with open(args.log, "a", encoding="utf-8") as f:
                                f.write(line + "\n")
                        except Exception:
                            pass
                        beep()
            else:
                print(f"[{ts}] no near-certain candidates with depth found.", end="\r")
        except KeyboardInterrupt:
            print("\nstopped.")
            break
        except Exception as ex:
            print("loop error:", ex)
        if args.once:
            break
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
