#!/usr/bin/env python3
"""
Polymarket daily-opportunity scanner (Gamma API, no key needed).

Looks for three low-risk / delta-neutral patterns inside Polymarket itself:

  1) NEG-RISK ARB - on multi-outcome markets (exactly one of N mutually exclusive outcomes wins)
     the sum of the best asks across all outcomes < $1  ->  buy every outcome, exactly one pays
     $1  ->  locked-in profit of (1 - sum).
     Polymarket has an automatic neg-risk converter, so large gaps get taken quickly; what is
     left is small and must be checked against the fee (feeSchedule.rate).

  2) RESOLUTION YIELD - an outcome trading at 94-99.5c that is close to its endDate:
     yield = 1/price - 1, annualised = yield / days * 365. These are "almost decided" markets;
     whether the outcome really is decided (UMA can delay or dispute) is a manual judgement.

  3) MM REWARDS - markets with a liquidity-rewards programme (rewardsMinSize / rewardsMaxSpread)
     where quoting inside the spread earns a rebate.

Usage:
    python poly_arb_scanner.py
    python poly_arb_scanner.py --limit 300 --neg-edge 0.01 --res-days 10 --tag soccer

This is a candidate list, not a signal: check the order book, liquidity and fees by hand.
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
    ap.add_argument("--limit", type=int, default=500, help="how many top events (by volume) to pull (default 500)")
    ap.add_argument("--neg-edge", type=float, default=0.02, help="neg-risk threshold: sum of asks < 1 - edge (default 0.02)")
    ap.add_argument("--res-min", type=float, default=0.94, help="resolution-yield price band, lower bound (default 0.94)")
    ap.add_argument("--res-max", type=float, default=0.999, help="resolution-yield price band, upper bound (default 0.999)")
    ap.add_argument("--res-days", type=float, default=21, help="near-resolved: at most this many days to endDate (default 21)")
    ap.add_argument("--tag", default=None, help="restrict to a Gamma tag_slug (e.g. soccer, politics)")
    return ap.parse_args()


def http(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def events(limit, tag):
    params = {"closed": "false", "active": "true", "order": "volume", "ascending": "false", "limit": limit}
    if tag:
        params["tag_slug"] = tag
    return http(f"{GAMMA}/events?{urllib.parse.urlencode(params)}")


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


def ask_yes(m):
    """Best price to BUY the 'Yes' outcome (as a probability)."""
    a = fl(m.get("bestAsk"))
    if a is not None and 0 < a < 1:
        return a
    p = arr(m.get("outcomePrices"))
    return fl(p[0]) if p else None


def main():
    args = parse_args()
    print("Fetching top Polymarket events...")
    try:
        evs = events(args.limit, args.tag)
    except Exception as e:
        raise SystemExit(f"could not reach the Gamma API: {e}")
    print(f"events received: {len(evs)}\n")

    negrisk, resyield, mm = [], [], []
    for e in evs:
        mkts = [m for m in (e.get("markets") or []) if not m.get("closed")]
        title = (e.get("title") or e.get("slug") or "")[:60]
        # --- 1) neg-risk arb ---
        is_neg = e.get("negRisk") or e.get("enableNegRisk")
        if is_neg and len(mkts) >= 3:
            asks = [ask_yes(m) for m in mkts]
            if all(a is not None for a in asks) and len(asks) >= 3:
                s = sum(asks)
                if s < 1 - args.neg_edge:
                    fee = (((mkts[0].get("feeSchedule") or {}).get("rate")) or 0)
                    negrisk.append((round(1 - s, 4), round(s, 3), len(asks), fee, title, e.get("slug")))
        # --- 2) resolution yield + 3) MM rewards ---
        for m in mkts:
            a = fl(m.get("bestAsk"))
            d = days_to(m.get("endDate"))
            if a is not None and args.res_min <= a <= args.res_max and d is not None and 0 < d <= args.res_days:
                yld = (1 / a - 1)
                ann = yld / d * 365
                resyield.append((round(ann * 100, 1), round(yld * 100, 2), round(d, 1), round(a, 3),
                                 (m.get("groupItemTitle") or m.get("question") or "")[:48], e.get("slug")))
            rmin = fl(m.get("rewardsMinSize"))
            rspr = fl(m.get("rewardsMaxSpread"))
            liq = fl(m.get("liquidityClob")) or fl(m.get("liquidityNum")) or 0
            if rmin and rspr and liq and liq > 5000:
                mm.append((round(liq), rspr, rmin, (m.get("groupItemTitle") or m.get("question") or "")[:48], e.get("slug")))

    line = lambda: print("-" * 92)

    print("=" * 92)
    print("1) NEG-RISK ARB  (buy every outcome; sum of asks < $1 -> locked-in profit)")
    line()
    if not negrisk:
        print("  no candidates (or the neg-risk converter has already taken them).")
    else:
        print(f"  {'profit':>7} {'sum$':>7} {'outs':>4} {'fee':>6}  event")
        for prof, s, n, fee, title, slug in sorted(negrisk, reverse=True)[:25]:
            flag = "  [fee > profit]" if fee and fee >= prof else ""
            print(f"  {prof * 100:6.1f}% {s:7.3f} {n:4}  {fee * 100:5.1f}%  {title}{flag}")
            print(f"            polymarket.com/event/{slug}")

    print("\n" + "=" * 92)
    print(f"2) RESOLUTION YIELD  (outcome at {args.res_min * 100:.0f}-{args.res_max * 100:.1f}c, "
          f"<= {args.res_days:g} days to resolution)")
    line()
    if not resyield:
        print("  no candidates.")
    else:
        print(f"  {'annual':>8} {'yield':>6} {'days':>5} {'price':>6}  outcome")
        for ann, yld, d, a, name, slug in sorted(resyield, reverse=True)[:25]:
            print(f"  {ann:7.0f}% {yld:5.2f}% {d:5.1f} {a:6.3f}  {name}")
            print(f"            polymarket.com/event/{slug}")
        print("  (these are 'almost decided' markets: confirm the outcome really is decided; UMA can delay/dispute)")

    print("\n" + "=" * 92)
    print("3) MM REWARDS  (markets with a liquidity-rewards programme; quote both sides inside the spread)")
    line()
    if not mm:
        print("  no candidates.")
    else:
        print(f"  {'liq$':>9} {'maxSpread':>10} {'minSize':>9}  market")
        for liq, spr, rmin, name, slug in sorted(mm, reverse=True)[:20]:
            print(f"  {liq:9} {spr:10} {rmin:9}  {name}")

    print("\nDone. These are candidates: check the order book, liquidity and fee before trading.")


if __name__ == "__main__":
    main()
