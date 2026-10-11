#!/usr/bin/env python3
"""
Backtest: "draw from a 1-goal lead at the 70th minute", split by who is leading.

Idea: at minute MIN_CUT (70') with a lead of exactly LEAD_MARGIN (1 goal), how often does the
match end as a DRAW / the leader HOLDS / the trailer COMES BACK, and how does that depend on
who is leading (favourite / even / underdog, proxied by final league position)?
The resulting conditional probabilities are then compared with a live Polymarket draw price
to estimate EV and variance (Monte Carlo).

Data source: API-Football (https://www.api-football.com/), fixtures + events + standings.
The key is read from the API_FOOTBALL_KEY environment variable (see .env.example).
Responses are cached on disk (default ./apifb_cache) so re-runs are free.

Usage:
    export API_FOOTBALL_KEY=...
    python draw_backtest.py                       # 5 top leagues, seasons 2021-2023
    python draw_backtest.py --seasons 2022 2023 --minute 75 --fav-gap 5

Standard library only.
"""
import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

HOST = "https://v3.football.api-sports.io"

# API-Football league ids. 88 = Eredivisie if you want to add it.
LEAGUES = {39: "EPL", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
RATE_SLEEP = 0.12  # polite pause after each uncached request


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2021, 2022, 2023], help="seasons to scan")
    ap.add_argument("--minute", type=int, default=70, help="cut-off minute (default 70)")
    ap.add_argument("--margin", type=int, default=1, help="goal lead at the cut-off (default 1)")
    ap.add_argument("--fav-gap", type=int, default=6,
                    help="final-table position gap that makes the leader a 'clear favourite' (default 6)")
    ap.add_argument("--cache-dir", default="apifb_cache", help="directory for cached API responses")
    return ap.parse_args()


def get_api_key():
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        sys.exit("API_FOOTBALL_KEY is not set (see .env.example)")
    return key


# ------------------------------------------------------------------ API + cache
class Client:
    def __init__(self, key, cache_dir):
        self.key = key
        self.cache = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def api(self, path):
        req = urllib.request.Request(HOST + path, headers={"x-apisports-key": self.key})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 499, 500, 502, 503):
                    time.sleep(2 + attempt * 2)
                    continue
                raise
            except Exception:
                time.sleep(1 + attempt)
                continue
        return {"response": []}

    def cached(self, name, producer):
        path = os.path.join(self.cache, name)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        data = producer()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        time.sleep(RATE_SLEEP)
        return data

    def fixtures(self, league_id, season):
        data = self.cached(f"fx_{league_id}_{season}.json",
                           lambda: self.api(f"/fixtures?league={league_id}&season={season}").get("response", []))
        return [f for f in data if f["fixture"]["status"]["short"] == "FT"]

    def events(self, fixture_id):
        return self.cached(f"ev_{fixture_id}.json",
                           lambda: self.api(f"/fixtures/events?fixture={fixture_id}").get("response", []))

    def ranks(self, league_id, season):
        """team id -> final league position."""
        data = self.cached(f"st_{league_id}_{season}.json",
                           lambda: self.api(f"/standings?league={league_id}&season={season}").get("response", []))
        rank = {}
        try:
            for row in data[0]["league"]["standings"][0]:
                rank[row["team"]["id"]] = row["rank"]
        except Exception:
            pass
        return rank


def score_at(events, home_id, away_id, minute):
    """Score after `minute` from the event list. Own goals are credited to the opponent."""
    h = a = 0
    for e in events:
        if e.get("type") != "Goal":
            continue
        if ((e.get("time") or {}).get("elapsed") or 0) > minute:
            continue
        team = (e.get("team") or {}).get("id")
        if "own" in (e.get("detail") or "").lower():
            team = away_id if team == home_id else home_id
        if team == home_id:
            h += 1
        elif team == away_id:
            a += 1
    return h, a


# ------------------------------------------------------------------ stats helpers
def pct(x, n):
    return 0.0 if not n else round(100 * x / n, 1)


def ci(x, n):
    """Half-width of the 95% normal-approximation confidence interval, in percentage points."""
    if not n:
        return 0.0
    p = x / n
    return round(100 * 1.96 * math.sqrt(p * (1 - p) / n), 1)


def monte_carlo(p, price, frac=0.01, nbets=300, runs=4000, seed=11):
    """Flat fractional staking: `frac` of bankroll per bet at `price`, true hit rate `p`."""
    random.seed(seed)
    payoff = 1 / price - 1
    finals, drawdowns, streaks = [], [], []
    for _ in range(runs):
        bank = peak = 1.0
        dd = 0.0
        streak = max_streak = 0
        for _ in range(nbets):
            stake = bank * frac
            if random.random() < p:
                bank += stake * payoff
                streak = 0
            else:
                bank -= stake
                streak += 1
                max_streak = max(max_streak, streak)
            peak = max(peak, bank)
            dd = max(dd, (peak - bank) / peak)
        finals.append(bank)
        drawdowns.append(dd)
        streaks.append(max_streak)
    finals.sort(); drawdowns.sort(); streaks.sort()
    q = lambda arr, t: arr[min(len(arr) - 1, int(len(arr) * t))]
    return (f"EV/bet {(p * payoff - (1 - p)) * 100:+.0f}%  median x{q(finals, .5):.2f}  "
            f"5th pct x{q(finals, .05):.2f}  max drawdown (median/p95) "
            f"{100 * q(drawdowns, .5):.0f}%/{100 * q(drawdowns, .95):.0f}%  "
            f"losing streak (p95) {q(streaks, .95)}")


# ------------------------------------------------------------------ main
def main():
    args = parse_args()
    client = Client(get_api_key(), args.cache_dir)
    min_cut, margin, fav_gap = args.minute, args.margin, args.fav_gap

    buckets = defaultdict(lambda: {"q": 0, "draw": 0, "hold": 0, "comeback": 0})
    print(f"Collecting: minute {min_cut}, lead {margin}. Leagues {list(LEAGUES.values())}, seasons {args.seasons}\n")
    for season in args.seasons:
        for lid, lname in LEAGUES.items():
            ranks = client.ranks(lid, season)
            fixtures = client.fixtures(lid, season)
            print(f"  {lname} {season}: {len(fixtures)} matches")
            for f in fixtures:
                home_id, away_id = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
                h, a = score_at(client.events(f["fixture"]["id"]), home_id, away_id, min_cut)
                if abs(h - a) != margin:
                    continue
                fh, fa = f["goals"]["home"], f["goals"]["away"]
                if fh is None or fa is None:
                    continue
                if fh == fa:
                    res = "draw"
                else:
                    lead = "h" if h > a else "a"
                    win = "h" if fh > fa else "a"
                    res = "hold" if lead == win else "comeback"
                scoreline = f"{max(h, a)}-{min(h, a)}"
                lead_id = home_id if h > a else away_id
                trail_id = away_id if h > a else home_id
                keys = ["ALL", "L:" + lname, "S:" + scoreline]
                if lead_id in ranks and trail_id in ranks:
                    gap = ranks[trail_id] - ranks[lead_id]  # > 0: the leader finished higher (favourite leads)
                    keys.append("FAV leads" if gap >= fav_gap else ("DOG leads" if gap <= -fav_gap else "EVEN"))
                for k in keys:
                    buckets[k]["q"] += 1
                    buckets[k][res] += 1

    def show(keys, title):
        print(f"\n===== {title} =====")
        for k in keys:
            b = buckets.get(k)
            if not b or b["q"] == 0:
                continue
            n = b["q"]
            print(f"{k:14} n={n:5}  draw {pct(b['draw'], n):>5}% (+/-{ci(b['draw'], n)})  "
                  f"hold {pct(b['hold'], n):>5}%  comeback {pct(b['comeback'], n):>5}%")

    show(["ALL"], "Total")
    show(["FAV leads", "EVEN", "DOG leads"], "SPLIT BY FAVOURITE (the main result)")
    show(["L:" + v for v in LEAGUES.values()], "By league")
    show(sorted(k for k in buckets if k.startswith("S:")), "By scoreline at the cut-off")

    print("\n===== EV of backing the draw (Polymarket price in cents) by bucket =====")
    print(f"{'bucket':12} P(draw)  breakeven   EV@15c   EV@18c   EV@20c   EV@25c")
    for k in ["ALL", "FAV leads", "EVEN", "DOG leads"]:
        b = buckets.get(k)
        if not b or not b["q"]:
            continue
        p = b["draw"] / b["q"]
        row = "".join(f"  {((p / (c / 100)) - 1) * 100:+6.0f}%" for c in (15, 18, 20, 25))
        print(f"{k:12} {p * 100:6.1f}%   {p * 100:6.1f}c{row}")
    print("  (backing the draw is +EV only where the breakeven (= P in cents) is ABOVE the market price)")

    print("\n===== Monte Carlo (1% of bankroll per bet, 300 bets, 4000 runs) =====")
    for k, price in [("DOG leads", 0.18), ("EVEN", 0.17), ("EVEN", 0.20), ("ALL", 0.18)]:
        b = buckets.get(k)
        if b and b["q"]:
            print(f"  {k} @ {int(price * 100)}c:  " + monte_carlo(b["draw"] / b["q"], price))

    print("\nDone. Tune --seasons/--minute/--margin/--fav-gap; the cache is reused between runs.")


if __name__ == "__main__":
    main()
