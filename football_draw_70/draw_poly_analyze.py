#!/usr/bin/env python3
"""
Offline analysis of the "draw at 70' vs Polymarket price" dataset(s) built by draw_poly_backtest.py.

For every bucket (FAV / EVEN / DOG / ALL) it prints:
  n, P(draw) with a 95% CI, the average Polymarket draw price at ~70', and two EV estimates
  for buying the draw at that price:
    EV(avg)  = P(draw) / avg_price - 1          (bucket-level, what the original notes quoted)
    EV/row   = mean of per-row P&L of a $1 ticket (+(1/price - 1) on a draw, -1 otherwise), with CI
By default rows with a goal between 70' and the start of the price window (goals_70_78) are
dropped, because the ~70' price is then stale; --keep-grey keeps them.

Usage:
    python draw_poly_analyze.py                                  # shipped 20-row sample
    python draw_poly_analyze.py --data data/raw/draw_poly_dataset_2024.json data/raw/draw_poly_dataset_2025.json
    python draw_poly_analyze.py --keep-grey --by league

Standard library only.
"""
import argparse
import json
import math
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(HERE, "data", "samples", "draw_poly_dataset_sample.json")
BUCKETS = ("FAV", "EVEN", "DOG", "ALL")


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="+", default=[DEFAULT_DATA],
                    help="one or more dataset JSON files (default: the shipped sample)")
    ap.add_argument("--keep-grey", action="store_true",
                    help="keep rows with a goal between 70' and the price window (default: drop)")
    ap.add_argument("--by", choices=["bucket", "league", "score"], default="bucket",
                    help="grouping for the main table (default: bucket)")
    ap.add_argument("--max-price", type=float, default=None,
                    help="only rows where the 70' draw price is below this (e.g. 0.22 = the old breakeven rule)")
    return ap.parse_args()


def ci95(p, n):
    return 1.96 * math.sqrt(p * (1 - p) / n) if n else 0.0


def load(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            rows += json.load(f)
    return rows


def summarise(rows, label):
    n = len(rows)
    if not n:
        return None
    p_draw = sum(1 for r in rows if r["draw"]) / n
    avg_px = sum(r["price_70"] for r in rows) / n
    ev_avg = p_draw / avg_px - 1
    pnl = [((1 / r["price_70"] - 1) if r["draw"] else -1.0) for r in rows]
    ev_row = sum(pnl) / n
    ev_row_ci = 1.96 * statistics.pstdev(pnl) / math.sqrt(n)
    return (f"{label:12} n={n:4d}  P(draw)={p_draw * 100:5.1f}% +/-{ci95(p_draw, n) * 100:4.1f}  "
            f"avg price={avg_px * 100:5.1f}c  EV(avg)={ev_avg * 100:+6.1f}%  "
            f"EV/row={ev_row * 100:+6.1f}% +/-{ev_row_ci * 100:4.1f}")


def main():
    args = parse_args()
    rows = load(args.data)
    priced = [r for r in rows if r.get("price_70") is not None]
    print(f"rows: {len(rows)}  with a Polymarket price at ~70': {len(priced)}  "
          f"(no Polymarket event: {sum(1 for r in rows if r.get('poly') is None)})")
    if not args.keep_grey:
        priced = [r for r in priced if not r.get("goals_70_78")]
        print(f"after dropping rows with a goal in 70'-78' (stale price): {len(priced)}")
    if args.max_price is not None:
        priced = [r for r in priced if r["price_70"] < args.max_price]
        print(f"after keeping only price_70 < {args.max_price}: {len(priced)}")
    if not priced:
        print("nothing to analyse")
        return

    print(f"\n===== EV of buying the draw at the ~70' Polymarket price, by {args.by} =====")
    if args.by == "bucket":
        groups = [(b, [r for r in priced if b == "ALL" or r["bucket"] == b]) for b in BUCKETS]
    elif args.by == "league":
        leagues = sorted(set(r["league"] for r in priced))
        groups = [(L, [r for r in priced if r["league"] == L]) for L in leagues] + [("ALL", priced)]
    else:
        scores = sorted(set(max(r["score70"], r["score70"][::-1]) for r in priced))
        groups = [(s, [r for r in priced if r["score70"] in (s, s[::-1])]) for s in scores] + [("ALL", priced)]
    for label, rs in groups:
        line = summarise(rs, label)
        if line:
            print(line)

    print("\nEV(avg) = P(draw)/avg_price - 1.  EV/row = mean P&L of a $1 ticket per row (95% CI).")
    print("Backing the draw is only +EV where P(draw) is ABOVE the market price with a CI that excludes zero.")


if __name__ == "__main__":
    main()
