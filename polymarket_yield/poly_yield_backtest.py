#!/usr/bin/env python3
"""
Polymarket "resolution yield" backtest: buy a near-certain outcome (0.90-0.995) N hours before
resolution and hold it to the end. Evaluated on closed Polymarket markets from the last 12 months.

Data collection (--fetch, public APIs, no key):
  categories -> Gamma tag_slugs (related_tags=true, closed=true, paginated by 100, order=endDate desc):
    soccer, esports, tennis, politics (see CATS).
  Market filters: volumeNum >= 2000, market resolved (some outcome's final price > 0.99).
  For EVERY outcome of the market: price N hours before endDate (CLOB /prices-history,
  fidelity=60, window +/-3h, closest point). If that entry is inside the band -> a virtual $1 buy.
  won = final price of that outcome > 0.99.
  Cache in --cache-dir (market lists per category + done-set, checkpoint every 50 markets);
  re-running resumes. A full run takes 30-60 minutes.

Summary (default, offline): reads the dataset and prints, per category, n, average entry,
hit rate, tail rate and the yield per $1 (fees ignored).

Usage:
    python poly_yield_backtest.py                              # summary of the shipped dataset
    python poly_yield_backtest.py --data path/to/dataset.json
    python poly_yield_backtest.py --fetch --hours 72           # rebuild (slow, network)
    python poly_yield_backtest.py --fetch --hours 168 --outrights   # 7 days before, outright markets, band 0.80+

Standard library only.
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import time
import urllib.error
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(HERE, "data", "poly_yield_dataset.json")

CATS = {
    "soccer": ["epl", "la-liga", "serie-a", "bundesliga", "ligue-1", "champions-league", "world-cup"],
    "esports": ["cs2", "lol", "league-of-legends", "dota-2", "valorant"],
    "tennis": ["tennis", "atp", "wta"],
    "politics": ["politics", "geopolitics", "elections"],
}
MIN_VOL = 2000
MAX_MKT_PER_CAT = 2500
OUTRIGHT_RX = re.compile(r"reach the (grand )?final|win the|winner|champion|to reach", re.I)

UA = {"User-Agent": "Mozilla/5.0 (compatible; betting-strategy-research/1.0)", "Accept": "application/json"}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DEFAULT_DATA, help="dataset JSON to summarise / write (default: shipped file)")
    ap.add_argument("--fetch", action="store_true", help="(re)build the dataset from Polymarket APIs (slow)")
    ap.add_argument("--hours", type=int, default=72, help="entry N hours before resolution (default 72)")
    ap.add_argument("--outrights", action="store_true",
                    help="restrict to outright markets (winner / reach the final) and widen the band to 0.80+")
    ap.add_argument("--cache-dir", default="poly_cache", help="cache directory for --fetch")
    return ap.parse_args()


# ------------------------------------------------------------------ helpers
def http_json(url, tries=6):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 + attempt * 2)
                continue
            return None
        except Exception:
            time.sleep(1 + attempt)
    return None


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def save_json(path, value):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)


def iso_ts(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


# ------------------------------------------------------------------ fetch
def collect_markets(cat, tags, cache_dir, cutoff):
    """All resolved markets of a category (cached as a whole)."""
    path = os.path.join(cache_dir, f"mkts_{cat}.json")
    got = load_json(path, None)
    if got is not None:
        return got
    seen, out = set(), []
    for tag in tags:
        off = 0
        while True:
            u = (f"{GAMMA}/events?tag_slug={tag}&closed=true&related_tags=true"
                 f"&limit=100&offset={off}&order=endDate&ascending=false")
            js = http_json(u)
            if not js:
                break
            stop = False
            for ev in js:
                ets = iso_ts(ev.get("endDate"))
                if ets and ets < cutoff:
                    stop = True
                    continue
                for m in ev.get("markets") or []:
                    mid = m.get("id") or m.get("slug")
                    if not mid or mid in seen:
                        continue
                    try:
                        vol = float(m.get("volumeNum") or 0)
                    except Exception:
                        vol = 0
                    if vol < MIN_VOL:
                        continue
                    try:
                        prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
                    except Exception:
                        continue
                    if not prices or max(prices) <= 0.99:  # not resolved
                        continue
                    try:
                        toks = json.loads(m.get("clobTokenIds") or "[]")
                    except Exception:
                        toks = []
                    try:
                        outs = json.loads(m.get("outcomes") or "[]")
                    except Exception:
                        outs = []
                    if not toks or len(toks) != len(prices):
                        continue
                    mts = iso_ts(m.get("endDate")) or ets
                    if not mts or mts < cutoff:
                        continue
                    seen.add(mid)
                    out.append({"id": str(mid), "cat": cat, "slug": m.get("slug"),
                                "q": (m.get("question") or "")[:100], "outs": outs,
                                "final": prices, "toks": toks, "end": mts,
                                "vol": vol, "neg": bool(m.get("negRisk")),
                                "title": (ev.get("title") or "")[:80]})
                if len(out) >= MAX_MKT_PER_CAT:
                    stop = True
                    break
            off += 100
            time.sleep(0.25)
            if stop or len(js) < 100 or len(out) >= MAX_MKT_PER_CAT:
                break
        print(f"  {cat}/{tag}: markets so far {len(out)}")
        if len(out) >= MAX_MKT_PER_CAT:
            break
    save_json(path, out)
    return out


def entry_price(token, end_ts, hours_before, win_h):
    target = end_ts - hours_before * 3600
    u = (f"{CLOB}/prices-history?market={token}&fidelity=60"
         f"&startTs={int(target - win_h * 3600)}&endTs={int(target + win_h * 3600)}")
    js = http_json(u)
    pts = (js or {}).get("history") or []
    if not pts:
        return None
    best = min(pts, key=lambda p: abs(p.get("t", 0) - target))
    return best.get("p")


def fetch(args):
    band_lo, band_hi = (0.80 if args.outrights else 0.90), 0.995
    win_h = 6 if args.hours >= 168 else 3
    suffix = f"_h{args.hours}" + ("_out" if args.outrights else "")
    cutoff = time.time() - 365 * 86400
    os.makedirs(args.cache_dir, exist_ok=True)
    done_path = os.path.join(args.cache_dir, f"done{suffix}.json")
    print(f"Config: entry {args.hours}h before resolution, band {band_lo}-{band_hi}, "
          f"outrights={args.outrights} -> {args.data}")
    dataset = load_json(args.data, [])
    done = set(load_json(done_path, []))
    print(f"Resuming: rows {len(dataset)}, markets processed {len(done)}")
    for cat, tags in CATS.items():
        mkts = collect_markets(cat, tags, args.cache_dir, cutoff)
        print(f"== {cat}: {len(mkts)} markets ==")
        n_proc = 0
        for m in mkts:
            if m["id"] in done:
                continue
            if args.outrights and not (OUTRIGHT_RX.search(m.get("q") or "") or OUTRIGHT_RX.search(m.get("title") or "")):
                done.add(m["id"])
                continue
            for i, tok in enumerate(m["toks"]):
                ep = entry_price(tok, m["end"], args.hours, win_h)
                time.sleep(0.25)
                if ep is None or not (band_lo <= ep <= band_hi):
                    continue
                won = m["final"][i] > 0.99
                dataset.append({"cat": cat, "slug": m["slug"], "q": m["q"],
                                "outcome": (m["outs"][i] if i < len(m["outs"]) else i),
                                "entry": round(ep, 4), "won": won, "end": int(m["end"]),
                                "vol": m["vol"], "neg": m["neg"], "title": m["title"]})
            done.add(m["id"])
            n_proc += 1
            if n_proc % 50 == 0:
                save_json(args.data, dataset)
                save_json(done_path, sorted(done))
                print(f"  {cat}: {n_proc} markets, rows in dataset {len(dataset)}")
        save_json(args.data, dataset)
        save_json(done_path, sorted(done))
    return dataset


# ------------------------------------------------------------------ summary
def summary(dataset, hours):
    def block(title, groups):
        print(f"\n===== {title} =====")
        print(f"{'group':12s} {'n':>5s} {'avg entry':>9s} {'won':>7s} {'tails':>7s} {'yield/$1':>9s} {'95% CI':>8s}")
        for label, rows in groups:
            if not rows:
                continue
            n = len(rows)
            avg = sum(r["entry"] for r in rows) / n
            wins = sum(1 for r in rows if r["won"])
            pnl = [((1 / r["entry"] - 1) if r["won"] else -1.0) for r in rows]
            yld = sum(pnl) / n
            ci = 1.96 * statistics.pstdev(pnl) / math.sqrt(n)
            print(f"{label:12s} {n:5d} {avg * 100:8.1f}c {wins / n * 100:6.1f}% {(n - wins) / n * 100:6.2f}% "
                  f"{yld * 100:+8.2f}% {ci * 100:7.2f}")

    cats = sorted(set(r["cat"] for r in dataset), key=lambda c: list(CATS).index(c) if c in CATS else 99)
    block(f"Buying 90-99.5c outcomes {hours}h before resolution, by category",
          [(c, [r for r in dataset if r["cat"] == c]) for c in cats] + [("ALL", dataset)])
    block("By entry price band",
          [(f"{lo:.2f}-{hi:.3f}", [r for r in dataset if lo <= r["entry"] < hi])
           for lo, hi in ((0.80, 0.90), (0.90, 0.95), (0.95, 0.98), (0.98, 0.995))])
    block("By market type",
          [("negRisk", [r for r in dataset if r["neg"]]), ("binary", [r for r in dataset if not r["neg"]])])
    print("\nyield/$1 = mean P&L of a $1 ticket: +(1/entry - 1) if the outcome resolved Yes, -1 otherwise. "
          "Fees and slippage are NOT included.")


def main():
    args = parse_args()
    if args.fetch:
        dataset = fetch(args)
    else:
        dataset = load_json(args.data, None)
        if dataset is None:
            raise SystemExit(f"dataset not found: {args.data} (use --fetch to build it)")
    print(f"dataset: {args.data}  rows: {len(dataset)}")
    summary(dataset, args.hours)


if __name__ == "__main__":
    main()
