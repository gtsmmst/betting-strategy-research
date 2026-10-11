#!/usr/bin/env python3
"""
Build the "draw at 70' vs Polymarket price" dataset for one season (data collection script).

Stage A (API-Football): top-5 leagues, the given season -> every match with a lead of exactly
          1 goal at the 70th minute, bucketed FAV / EVEN / DOG by final-table position gap
          (gap >= 6 places). Cached in --cache-dir.
Stage B (Polymarket, public APIs, no key): Gamma events by league tag_slug (closed=true,
          paginated by 100); for each event the draw market (slug "...-draw" or question
          "end in a draw"); clobTokenIds -> the Yes token; CLOB /prices-history with
          fidelity=1; the price point closest to kickoff + 87 min (window +78..+95 min of
          wall-clock time, which is roughly the 70th minute of play), plus the pre-match price.

Output: <out-dir>/draw_poly_dataset_<season>.json  (and draw_poly_setups_<season>.json after stage A).
Analyse it offline with draw_poly_analyze.py.

Usage:
    export API_FOOTBALL_KEY=...
    python draw_poly_backtest.py --season 2025
    python draw_poly_backtest.py --season 2024 --cache-dir apifb_cache --out-dir data/raw

Standard library only. Safe to re-run: everything is cached.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

AFB = "https://v3.football.api-sports.io"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# API-Football league id -> (name, Polymarket tag_slug)
LEAGUES = {39: ("EPL", "epl"), 140: ("La Liga", "la-liga"), 135: ("Serie A", "serie-a"),
           78: ("Bundesliga", "bundesliga"), 61: ("Ligue 1", "ligue-1")}
MIN_CUT, LEAD_MARGIN, FAV_GAP = 70, 1, 6
KO_OFFSET_MIN, WIN_LO, WIN_HI = 87, 78, 95  # wall-clock minutes after kickoff

UA = {"User-Agent": "Mozilla/5.0 (compatible; betting-strategy-research/1.0)",
      "Accept": "application/json"}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=2025, help="API-Football season (start year), default 2025")
    ap.add_argument("--cache-dir", default="apifb_cache", help="cache directory for API responses")
    ap.add_argument("--out-dir", default=".", help="where to write the dataset files")
    ap.add_argument("--skip-stage-b", action="store_true", help="only build the API-Football setups")
    return ap.parse_args()


def http_json(url, headers=None, tries=6):
    for attempt in range(tries):
        try:
            h = dict(UA)
            h.update(headers or {})
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(1.5 + attempt * 1.5)
    return None


class Cache:
    def __init__(self, directory):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)

    def get(self, name, producer):
        path = os.path.join(self.dir, name)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    v = json.load(f)
                if v not in (None, [], {}):  # an empty cache entry counts as a miss
                    return v
            except Exception:
                pass
        v = producer()
        if v not in (None, [], {}):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(v, f, ensure_ascii=False)
        return v


def norm_team(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower())
    drop = {"fc", "cf", "afc", "ac", "as", "ssc", "rc", "sc", "club", "de", "le", "the", "1", "us", "cd"}
    return set(t for t in s.split() if len(t) >= 3 and t not in drop)


def teams_match(a, b):
    A, B = norm_team(a), norm_team(b)
    return bool(A and B and (A & B))


# ---------------------------------------------------------------- Stage A
def stage_a(season, cache, out_dir, api_key):
    def afb(path):
        return http_json(AFB + path, {"x-apisports-key": api_key})

    print("=== Stage A: API-Football, season", season, "===")
    setups = []
    for lid, (lname, tag) in LEAGUES.items():
        fx = cache.get(f"fx_{season}_{lid}.json", lambda: afb(f"/fixtures?league={lid}&season={season}"))
        rows = (fx or {}).get("response") or []
        rows = [r for r in rows if (r.get("fixture") or {}).get("status", {}).get("short") in ("FT", "AET", "PEN")]
        st = cache.get(f"st_{season}_{lid}.json", lambda: afb(f"/standings?league={lid}&season={season}"))
        rank = {}
        try:
            for t in st["response"][0]["league"]["standings"][0]:
                rank[t["team"]["id"]] = t["rank"]
        except Exception:
            pass
        n_setup = 0
        for i, r in enumerate(rows):
            f = r["fixture"]
            fid = f["id"]
            home, away = r["teams"]["home"], r["teams"]["away"]
            ev = cache.get(f"ev_{fid}.json", lambda: (time.sleep(0.12), afb(f"/fixtures/events?fixture={fid}"))[1])
            goals = []
            for e in (ev or {}).get("response") or []:
                if e.get("type") == "Goal" and e.get("detail") != "Missed Penalty":
                    el = (e.get("time") or {}).get("elapsed")
                    if el is None:
                        continue
                    goals.append((el, e["team"]["id"]))
            h70 = sum(1 for el, t in goals if el <= MIN_CUT and t == home["id"])
            a70 = sum(1 for el, t in goals if el <= MIN_CUT and t == away["id"])
            if abs(h70 - a70) != LEAD_MARGIN:
                continue
            leader = home if h70 > a70 else away
            trailer = away if h70 > a70 else home
            rl, rt = rank.get(leader["id"]), rank.get(trailer["id"])
            bucket = "EVEN"
            if rl is not None and rt is not None:
                if rt - rl >= FAV_GAP:
                    bucket = "FAV"
                elif rl - rt >= FAV_GAP:
                    bucket = "DOG"
            gh, ga = (r.get("goals") or {}).get("home"), (r.get("goals") or {}).get("away")
            # a goal between 70' and the price window start makes the 70' price stale ("grey" row)
            grey = any(MIN_CUT < el <= WIN_LO for el, _ in goals)
            setups.append({
                "fixture": fid, "league": lname, "tag": tag, "kickoff": f.get("timestamp"),
                "date": (f.get("date") or "")[:10],
                "home": home["name"], "away": away["name"],
                "score70": f"{h70}-{a70}", "leader": leader["name"], "bucket": bucket,
                "final": f"{gh}-{ga}", "draw": gh == ga,
                "goals_70_78": grey,
            })
            n_setup += 1
            if (i + 1) % 50 == 0:
                print(f"  {lname}: {i + 1}/{len(rows)} matches, setups {n_setup}")
        print(f"  {lname}: matches {len(rows)}, setups {n_setup}")
    out = os.path.join(out_dir, f"draw_poly_setups_{season}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(setups, f, ensure_ascii=False, indent=1)
    print(f"Stage A done: {len(setups)} setups -> {out}")
    return setups


# ---------------------------------------------------------------- Stage B
def gamma_events_for_tag(tag, cache):
    def fetch():
        out, off = [], 0
        while True:
            u = f"{GAMMA}/events?tag_slug={tag}&closed=true&related_tags=true&limit=100&offset={off}"
            js = http_json(u)
            if not js:
                break
            out += js
            if len(js) < 100:
                break
            off += 100
            time.sleep(0.2)
        return out
    return cache.get(f"gamma_{tag}.json", fetch) or []


def find_draw_market(ev):
    for m in ev.get("markets") or []:
        slug = (m.get("slug") or "").lower()
        q = (m.get("question") or "").lower()
        if slug.endswith("-draw") or "end in a draw" in q:
            try:
                toks = json.loads(m.get("clobTokenIds") or "[]")  # this field is a JSON string
                if toks:
                    return m, toks[0]
            except Exception:
                pass
    return None, None


def price_points(token, kickoff):
    u = f"{CLOB}/prices-history?market={token}&fidelity=1&startTs={kickoff - 7200}&endTs={kickoff + 10800}"
    js = http_json(u)
    return (js or {}).get("history") or []


def stage_b(setups, season, cache, out_dir):
    print("=== Stage B: Polymarket (Gamma + CLOB prices-history) ===")
    out = os.path.join(out_dir, f"draw_poly_dataset_{season}.json")
    idx = {}  # tag -> list of (date, title, event)
    for tag in set(s["tag"] for s in setups):
        evs = gamma_events_for_tag(tag, cache)
        lst = []
        for e in evs:
            slug = e.get("slug") or ""
            m = re.search(r"(\d{4}-\d{2}-\d{2})$", slug)
            d = m.group(1) if m else (e.get("startDate") or "")[:10]
            lst.append((d, e.get("title") or "", e))
        idx[tag] = lst
        print(f"  gamma {tag}: {len(evs)} closed events")
    dataset, miss_ev, miss_px = [], 0, 0

    def save():
        with open(out, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=1)

    for i, s in enumerate(setups):
        cand = None
        for d, title, e in idx.get(s["tag"], []):
            if d != s["date"]:
                continue
            if teams_match(s["home"], title) and teams_match(s["away"], title):
                cand = e
                break
        row = dict(s)
        if not cand:
            miss_ev += 1
            row.update({"poly": None})
            dataset.append(row)
            continue
        m, token = find_draw_market(cand)
        if not token:
            miss_ev += 1
            row.update({"poly": None})
            dataset.append(row)
            continue
        ko = s.get("kickoff") or 0
        pts = price_points(token, ko)
        time.sleep(0.15)
        target = ko + KO_OFFSET_MIN * 60
        lo, hi = ko + WIN_LO * 60, ko + WIN_HI * 60
        inwin = [p for p in pts if lo <= p.get("t", 0) <= hi]
        p70 = min(inwin, key=lambda p: abs(p["t"] - target)) if inwin else None
        pre = [p for p in pts if p.get("t", 0) <= ko]
        ppre = pre[-1] if pre else None
        if not p70:
            miss_px += 1
        row.update({
            "poly": cand.get("slug"), "draw_mkt": (m.get("slug") if m else None), "token": token,
            "price_70": round(p70["p"], 4) if p70 else None,
            "price_70_off_min": round((p70["t"] - ko) / 60, 1) if p70 else None,
            "price_pre": round(ppre["p"], 4) if ppre else None,
        })
        dataset.append(row)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(setups)} setups processed (no event: {miss_ev}, no price: {miss_px})")
            save()
    save()
    ok = [r for r in dataset if r.get("price_70") is not None]
    print(f"Stage B done: {len(dataset)} rows, with a Polymarket price at ~70': {len(ok)}, "
          f"no event: {miss_ev}, no price in window: {miss_px}")
    print(f"-> {out}\nRun: python draw_poly_analyze.py --data {out}")


def main():
    args = parse_args()
    api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        sys.exit("API_FOOTBALL_KEY is not set (see .env.example)")
    os.makedirs(args.out_dir, exist_ok=True)
    cache = Cache(args.cache_dir)
    setups = stage_a(args.season, cache, args.out_dir, api_key)
    if not args.skip_stage_b:
        stage_b(setups, args.season, cache, args.out_dir)


if __name__ == "__main__":
    main()
