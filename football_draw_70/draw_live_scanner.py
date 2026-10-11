#!/usr/bin/env python3
"""
Live scanner for "draw from a 1-goal lead" setups (API-Football live endpoint).

Every --poll seconds it fetches /fixtures?live=all and looks, in the monitored leagues, for
matches where:
  - the minute is inside [--min-from, --min-to] (default 65-80'),
  - the lead is exactly 1 goal,
  - the leader is NOT a clear favourite (strength = points-per-game from the live table).
Each setup produces an alert: console + terminal bell + a line in the alert log.

Reading the alert (Polymarket quotes the draw in cents = implied probability):
  backing the draw is +EV only when the market price is BELOW the breakeven (= the true
  probability). The breakevens below come from the 2021-2023 backtest (draw_backtest.py):
     favourite leads ~13c (skip - the favourite almost always holds),
     even teams      ~22c,
     underdog leads  ~27c.
  NOTE: the follow-up backtest against real Polymarket prices (see README) found that the
  market already prices the draw at or above these breakevens, so this scanner is a research
  tool, not a signal generator.

Usage:
    export API_FOOTBALL_KEY=...
    python draw_live_scanner.py            # Ctrl+C to stop
    python draw_live_scanner.py --poll 30 --min-from 60 --min-to 82

Standard library only.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HOST = "https://v3.football.api-sports.io"

# ~12 major leagues (API-Football ids). Add freely.
MONITORED_LEAGUES = {
    39: "EPL", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1",
    88: "Eredivisie", 94: "Primeira Liga", 253: "MLS", 71: "Brazil Serie A",
    40: "Championship", 2: "Champions League", 1: "World Cup",
    # 203: "Turkey", 144: "Belgium", 307: "Saudi", 262: "Liga MX",
}

# breakeven price (cents) = empirical draw probability per bucket (2021-2023 backtest)
BREAKEVEN = {"EVEN": 22, "DOG": 27, "FAV": 13, "?": 20}
TAG = {"EVEN": "even teams", "DOG": "underdog leads", "FAV": "favourite leads", "?": "strength unknown"}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--poll", type=int, default=60, help="seconds between polls (default 60)")
    ap.add_argument("--min-from", type=int, default=65, help="start of the minute window (default 65)")
    ap.add_argument("--min-to", type=int, default=80, help="end of the minute window (default 80)")
    ap.add_argument("--gap-ppg", type=float, default=0.50,
                    help="points-per-game gap that makes the leader a clear favourite (default 0.50)")
    ap.add_argument("--no-unknown", action="store_true",
                    help="do not alert when team strength cannot be determined (cups, no table)")
    ap.add_argument("--log", default="alerts.log", help="alert log file (default alerts.log)")
    return ap.parse_args()


class Api:
    def __init__(self, key):
        self.key = key
        self._ppg_cache = {}

    def get(self, path):
        req = urllib.request.Request(HOST + path, headers={"x-apisports-key": self.key})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503):
                    time.sleep(2 + attempt * 2)
                    continue
                return {"response": []}
            except Exception:
                time.sleep(1 + attempt)
                continue
        return {"response": []}

    def ppg(self, league_id, season):
        """team id -> points per game (comparable across groups/conferences, accounts for games played)."""
        key = (league_id, season)
        now = time.time()
        hit = self._ppg_cache.get(key)
        if hit and now - hit[0] < 6 * 3600:
            return hit[1]
        data = self.get(f"/standings?league={league_id}&season={season}").get("response", [])
        ppg = {}
        try:
            for group in data[0]["league"]["standings"]:  # there may be several groups / conferences
                for row in group:
                    played = (row.get("all") or {}).get("played") or 0
                    pts = row.get("points")
                    if played and pts is not None:
                        ppg[row["team"]["id"]] = pts / played
        except Exception:
            pass
        self._ppg_cache[key] = (now, ppg)
        return ppg


def bucket_of(lead_id, trail_id, ppg, gap):
    if lead_id not in ppg or trail_id not in ppg:
        return "?"
    d = ppg[lead_id] - ppg[trail_id]  # > 0: the leader is the stronger side
    if d >= gap:
        return "FAV"
    if d <= -gap:
        return "DOG"
    return "EVEN"


def beep():
    try:
        import winsound  # Windows only
        for _ in range(2):
            winsound.Beep(880, 160)
            winsound.Beep(1175, 160)
    except Exception:
        print("\a", end="")


def alert(text, log):
    line = datetime.now().strftime("%H:%M:%S") + "  " + text
    print("\n[ALERT] " + line)
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    beep()


def main():
    args = parse_args()
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key:
        sys.exit("API_FOOTBALL_KEY is not set (see .env.example)")
    api = Api(key)

    print("Live draw-setup scanner started.")
    print(f"Leagues: {', '.join(MONITORED_LEAGUES.values())}")
    print(f"Window {args.min_from}-{args.min_to}', lead of 1 goal, leader is not a clear favourite. "
          f"Polling every {args.poll}s. (Ctrl+C to stop)")
    print("Reminder: back the draw only if its price is BELOW the breakeven (even <22c, underdog <27c).\n")

    alerted = set()
    while True:
        try:
            resp = api.get("/fixtures?live=all").get("response", [])
            live = 0
            for f in resp:
                try:
                    lid = f["league"]["id"]
                    if lid not in MONITORED_LEAGUES:
                        continue
                    status = f["fixture"]["status"]
                    mins = status.get("elapsed")
                    if status.get("short") not in ("1H", "2H", "ET") or mins is None:
                        continue
                    gh, ga = f["goals"]["home"], f["goals"]["away"]
                    if gh is None or ga is None:
                        continue
                    live += 1
                    if not (args.min_from <= mins <= args.min_to) or abs(gh - ga) != 1:
                        continue
                    fid = f["fixture"]["id"]
                    if fid in alerted:
                        continue
                    home_id, away_id = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
                    home, away = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
                    season = f["league"]["season"]
                    lead_id = home_id if gh > ga else away_id
                    trail_id = away_id if gh > ga else home_id
                    bk = bucket_of(lead_id, trail_id, api.ppg(lid, season), args.gap_ppg)
                    if bk == "FAV":
                        continue
                    if bk == "?" and args.no_unknown:
                        continue
                    alerted.add(fid)
                    be = BREAKEVEN.get(bk, 20)
                    leader = home if gh > ga else away
                    alert(f"{home} {gh}-{ga} {away} | {mins}' | {MONITORED_LEAGUES[lid]} | {leader} leads "
                          f"[{TAG[bk]}] -> draw ~{be}%. Back the draw only if Polymarket quotes it BELOW "
                          f"{be}c; at {be}c or above, skip.", args.log)
                except Exception:
                    continue
            print(f"  {datetime.now().strftime('%H:%M:%S')}  live matches in monitored leagues: {live}, "
                  f"alerts: {len(alerted)}   ", end="\r")
        except KeyboardInterrupt:
            print("\nstopped.")
            break
        except Exception as e:
            print("loop error:", e)
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
