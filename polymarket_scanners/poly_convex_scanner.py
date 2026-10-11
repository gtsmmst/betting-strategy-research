#!/usr/bin/env python3
"""
Polymarket convex / long-shot scanner (Gamma API, no key needed).

Why: the large documented wins on Polymarket mostly came from CONVEXITY (cheap outcomes that
resolved Yes), not from yield. Those are SLOW markets where research and patience matter more
than latency - bots do not freeze capital for weeks for a 3c long shot.

What it does:
  (1) CHEAP TAILS: outcomes priced 1-20c in slow markets (resolution not today) with enough
      liquidity to actually enter. Shows the multiple (1/price), implied probability, days to
      resolution and category.
  (2) CHEAP FIELDS: multi-outcome (negRisk) events with many cheap contenders - the
      "buy the undervalued field" pattern. Shows the 5 cheapest outcomes of the event.

This is the candidate universe. Cheap is not the same as undervalued; most tails expire
worthless. The edge, if any, is finding where the market underestimates a tail and taking MANY
small uncorrelated tickets.

Usage:
    python poly_convex_scanner.py
    python poly_convex_scanner.py --lo 0.001 --hi 0.01 --min-days 7     # the 0.1-1c tail lottery
    python poly_convex_scanner.py --limit 300 --min-liq 1000 --top 20

Standard library only.
"""
import argparse
import datetime
import json
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=600, help="how many top events (by volume) to pull (default 600)")
    ap.add_argument("--lo", type=float, default=0.01, help="lower bound of the cheap-tail price band (default 0.01)")
    ap.add_argument("--hi", type=float, default=0.20, help="upper bound of the cheap-tail price band (default 0.20)")
    ap.add_argument("--min-days", type=float, default=2, help="slow markets only: at least this many days to endDate (default 2)")
    ap.add_argument("--min-liq", type=float, default=500, help="minimum liquidity in $ to list a tail (default 500)")
    ap.add_argument("--top", type=int, default=35, help="how many tails to print (default 35)")
    return ap.parse_args()


def http(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


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


def days_to(iso):
    if not iso:
        return None
    try:
        d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (d - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 86400
    except Exception:
        return None


def main():
    args = parse_args()
    print(f"Fetching top-{args.limit} Polymarket events by volume...")
    try:
        qs = urllib.parse.urlencode({"closed": "false", "active": "true",
                                     "order": "volume", "ascending": "false", "limit": args.limit})
        evs = http(f"{GAMMA}/events?{qs}")
    except Exception as e:
        raise SystemExit(f"could not reach the Gamma API: {e}")
    print(f"events received: {len(evs)}. Looking for cheap tails in slow markets...\n")

    tails, fields = [], []
    for e in evs:
        title = (e.get("title") or e.get("slug") or "")[:44]
        cats = ",".join((t.get("slug") or "") for t in (e.get("tags") or [])[:2])[:22]
        mkts = [m for m in (e.get("markets") or []) if not m.get("closed")]
        # slow market? days to the event's / first market's endDate; skip today's live matches
        d = days_to(e.get("endDate")) or (days_to(mkts[0].get("endDate")) if mkts else None)
        if d is None or d < args.min_days:
            continue
        is_neg = e.get("negRisk") or e.get("enableNegRisk")
        cheap_here = []
        for m in mkts:
            outs = arr(m.get("outcomes"))
            prices = [fl(x) for x in arr(m.get("outcomePrices"))]
            liq = fl(m.get("liquidityClob")) or fl(m.get("liquidityNum")) or 0
            if len(outs) != len(prices):
                continue
            for nm, p in zip(outs, prices):
                if p is None or not (args.lo <= p <= args.hi):
                    continue
                name = (m.get("groupItemTitle") or str(nm))[:30]
                rec = {"title": title, "cats": cats, "name": name, "p": p,
                       "mult": round(1 / p, 1), "liq": round(liq), "days": round(d), "slug": e.get("slug")}
                if liq >= args.min_liq:
                    tails.append(rec)
                cheap_here.append((p, name, round(liq)))
        # cheap field: a negRisk event with >= 4 cheap contenders
        if is_neg and len(cheap_here) >= 4:
            cheap_here.sort()
            fields.append({"title": title, "cats": cats, "days": round(d),
                           "n": len(cheap_here), "cheap": cheap_here[:5], "slug": e.get("slug")})

    # sort: liquidity x multiple (can enter AND large upside)
    tails.sort(key=lambda r: r["liq"] * r["mult"], reverse=True)
    fields.sort(key=lambda f: f["n"], reverse=True)

    print("=" * 100)
    print(f"1) CHEAP TAILS ({args.lo * 100:g}-{args.hi * 100:g}c, resolution >= {args.min_days:g} days, "
          f"liquidity >= ${args.min_liq:g}) - sorted by liquidity x multiple")
    print("=" * 100)
    if not tails:
        print("  none found.")
    else:
        print(f"  {'price':>5} {'x':>5} {'prob%':>5} {'liq$':>9} {'days':>5} {'category':>22}  event / outcome")
        for r in tails[:args.top]:
            print(f"  {r['p'] * 100:5.1f} {r['mult']:5} {r['p'] * 100:5.1f} {r['liq']:9} {r['days']:5} "
                  f"{r['cats']:>22}  {r['title']} / {r['name']}")
            print(f"            polymarket.com/event/{r['slug']}")

    print("\n" + "=" * 100)
    print("2) CHEAP FIELDS (negRisk multi-outcome events with >= 4 cheap contenders)")
    print("=" * 100)
    if not fields:
        print("  none found.")
    else:
        for f in fields[:12]:
            cheap = " | ".join(f"{nm} {p * 100:.1f}c (${liq})" for p, nm, liq in f["cheap"])
            print(f"  {f['title']}  [{f['cats']}, {f['days']}d, outcomes {f['n']}]")
            print(f"     cheapest: {cheap}")
            print(f"     polymarket.com/event/{f['slug']}")

    print("\n" + "=" * 100)
    print("HOW TO USE:")
    print("  - This is a candidate list, not a buy signal. Cheap != undervalued.")
    print("  - For each one decide whether the TRUE probability is above the price (news, form, structure).")
    print("  - Many small UNcorrelated tickets, tiny size: most expire worthless, a few pay the multiple.")
    print("  - Slow resolution is the point: time to research, and bots do not compete here.")
    print("  - politics/geopolitics/economy/elections categories are often fee-free.")


if __name__ == "__main__":
    main()
