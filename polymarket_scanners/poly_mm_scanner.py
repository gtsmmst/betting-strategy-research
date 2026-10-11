#!/usr/bin/env python3
"""
Polymarket market-making (liquidity-rewards) scanner (Gamma API, no key needed).

Idea: Polymarket pays makers for liquidity. Quoting both sides (bid + ask) near the mid,
with size >= rewardsMinSize and inside rewardsMaxSpread, earns a share of the market's daily
reward pool every day. You do not pick the winner -> the position is roughly delta-neutral
if the inventory is kept balanced.

What the scanner computes, for every active market with rewards enabled:
    - daily reward pool ($/day),
    - rewardsMinSize and rewardsMaxSpread (where to quote),
    - current liquidity = competition from other makers,
    - a ROUGH estimate of your share of the pool and the annualised return (APR) on the
      capital tied up, and sorts by APR.
This is reconnaissance - the top markets of the day where rewards per dollar look best.

Risk: maker P&L = rewards + spread - adverse selection (being filled right before a move) - fees.
On quiet / slow markets it is close to pure yield; on volatile news markets adverse selection
eats the spread and rewards only partly compensate. Quote wider on news markets, tighter on
quiet ones, keep bid ~ ask inventory, rebalance.

Execution: orders go through the Polymarket CLOB API (signed with your own key). This script
never touches keys or places orders - it only says WHERE and with what size to quote.

Usage:
    python poly_mm_scanner.py
    python poly_mm_scanner.py --limit 300 --min-pool 5 --top 15

Cross-check with polymarket.com/rewards - that page is the official picture.
Standard library only.
"""
import argparse
import json
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=500, help="how many top events (by volume) to pull (default 500)")
    ap.add_argument("--min-pool", type=float, default=1.0, help="hide markets with a daily pool below this $ (default 1)")
    ap.add_argument("--top", type=int, default=30, help="how many rows to print (default 30)")
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


def daily_pool(m):
    """Daily reward pool of a market ($). Gamma has exposed this under several field names."""
    for r in arr(m.get("clobRewards")):
        v = fl(r.get("rewardsDailyRate")) or fl(r.get("dailyRate")) or fl(r.get("rewardsAmount"))
        if v:
            return v
    v = fl(m.get("rewardsDailyRate")) or fl(m.get("dailyRewardsRate"))
    if v:
        return v
    return 0.0


def mid_price(m):
    bb, ba = fl(m.get("bestBid")), fl(m.get("bestAsk"))
    if bb is not None and ba is not None and 0 < bb < ba < 1:
        return (bb + ba) / 2
    p = arr(m.get("outcomePrices"))
    return fl(p[0]) if p else None


def main():
    args = parse_args()
    print(f"Fetching top-{args.limit} Polymarket events by volume...")
    try:
        qs = urllib.parse.urlencode({"closed": "false", "active": "true",
                                     "order": "volume", "ascending": "false", "limit": args.limit})
        evs = http(f"{GAMMA}/events?{qs}")
    except Exception as e:
        raise SystemExit(f"could not reach the Gamma API: {e}")
    print(f"events received: {len(evs)}. Looking for markets with rewards enabled...\n")

    rows = []
    for e in evs:
        title = (e.get("title") or e.get("slug") or "")[:46]
        cats = ",".join((t.get("slug") or "") for t in (e.get("tags") or [])[:3])
        for m in (e.get("markets") or []):
            if m.get("closed"):
                continue
            minsz = fl(m.get("rewardsMinSize"))
            maxspr = fl(m.get("rewardsMaxSpread"))
            if not minsz or not maxspr or minsz <= 0 or maxspr <= 0:
                continue  # rewards not enabled
            pool = daily_pool(m)
            if pool < args.min_pool:
                continue
            mid = mid_price(m) or 0.5
            liq = fl(m.get("liquidityClob")) or fl(m.get("liquidityNum")) or 0.0
            # --- rough estimates (Polymarket's formula is more complex; this is a ranking, not a guarantee) ---
            cap = round(minsz)                        # ~$ tied up by a two-sided quote of minSize shares
            liq_shares = (liq / mid) if mid else liq  # liquidity in shares (= competition)
            my_share = minsz / (liq_shares + minsz) if (liq_shares + minsz) else 0
            est_day = pool * my_share                 # your estimated daily reward, $
            apr = (est_day * 365 / cap * 100) if cap else 0
            fee = ((m.get("feeSchedule") or {}).get("rate")) or 0
            rows.append({
                "title": title, "q": (m.get("groupItemTitle") or m.get("question") or "")[:34],
                "cats": cats, "mid": round(mid, 3), "spr": round(maxspr * 100, 1),
                "minsz": round(minsz), "pool": round(pool), "liq": round(liq),
                "estday": round(est_day, 1), "apr": round(apr), "fee": fee, "slug": e.get("slug"),
            })

    rows.sort(key=lambda r: r["apr"], reverse=True)

    if not rows:
        print("No markets with rewards enabled found among the top-volume events.")
        print("Check polymarket.com/rewards - the programme or the API fields may have changed.")
        return

    print("=" * 108)
    print("MM-REWARDS CANDIDATES (sorted by estimated APR on capital). Quote BOTH sides near the mid, size >= minSize.")
    print("=" * 108)
    print(f"  {'APR~':>5} {'$/day~':>7} {'pool$/d':>7} {'minSize':>8} {'spread':>6} {'mid':>6} {'liq$':>9} {'fee':>4}  market")
    print("-" * 108)
    for r in rows[:args.top]:
        print(f"  {r['apr']:4}% {r['estday']:7} {r['pool']:7} {r['minsz']:8} {r['spr']:6} {r['mid']:6} "
              f"{r['liq']:9} {r['fee'] * 100:3.0f}%  {r['title']} / {r['q']}")
        print(f"            polymarket.com/event/{r['slug']}")

    print("\n" + "=" * 108)
    print("HOW TO READ:")
    print("  - APR~ and $/day~ are ROUGH estimates of your share (Polymarket weights distance to mid and size")
    print("    quadratically). It is a ranking of 'where rewards per $ look best', not a guarantee.")
    print("  - spread = rewardsMaxSpread in cents: quotes further from the mid than this earn nothing.")
    print("  - liq$ = how much competition already stands there (more -> smaller share of the pool).")
    print("  - Target: high pool, LOW competition, quiet (not news-driven) market, fee = 0.")
    print("  - Start with 1-2 markets at small size, measure the real rewards for a day, then scale.")


if __name__ == "__main__":
    main()
