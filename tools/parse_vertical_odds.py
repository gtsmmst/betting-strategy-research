#!/usr/bin/env python3
"""
Parser for the "vertical" odds text layout that several sportsbook sites produce when you
select-all + copy a match page: a market header, then one line per outcome / line / price.

Returns rows of the form {market, team, line, odds}, which is the common shape used by the
cross-book comparison scripts. Markets handled: 1x2 / Match Winner, Double Chance,
Draw No Bet, Handicap (incl. Asian), Totals, Both Teams To Score. Headers of markets that
are not modelled (correct score, goalscorers, corners, cards, ...) switch the parser to
"skip" mode until the next recognised header.

Usage:
    python parse_vertical_odds.py            # runs the built-in self-test
    python parse_vertical_odds.py page.txt   # parses a copied page and prints the rows
"""
import re
import sys

ODDS = re.compile(r'^\d{1,4}(?:\.\d+)?$')
LINEV = re.compile(r'^[+-]?\d+(?:\.\d+)?$')

SKIP_HEADERS = ["to qualify", "correct score", "goalscorer", "winning method", "overtime",
                "(2up)", "(1up)", "same-game", "same game", "half", "corner", "card", "player",
                "penalty", "1st goal", "anytime", "scoreboard", "live stream", "top markets",
                "show all", "select", "popular", "stats", "1st pistol", "pistol round",
                "winner & total", "map 1", "map 2", "map 3", "first map", "second map", "odds:"]

MARKET_NAME = {"ML": "1x2", "DC": "Double Chance", "DNB": "Draw No Bet",
               "HCAP": "Handicap", "TOT": "Total", "BTTS": "Both Teams To Score"}


def _header_type(line):
    """Classify a line as a market header. None = not a header."""
    l = line.lower().strip()
    if l in ("1x2", "winner", "match winner", "moneyline"):
        return "ML"
    if "both teams to score" in l:
        return "BTTS"
    if l == "double chance":
        return "DC"
    if l in ("draw no bet",):
        return "DNB"
    if l in ("handicap", "map handicap", "asian handicap"):
        return "HCAP"
    if l in ("total", "totals", "total maps", "total goals"):
        return "TOT"
    if any(k in l for k in SKIP_HEADERS):
        return "SKIP"
    return None


def _f(s):
    try:
        return float(s)
    except Exception:
        return None


def parse_vertical(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    rows = []
    mode = None
    side = None
    i, n = 0, len(lines)
    while i < n:
        ht = _header_type(lines[i])
        if ht is not None:
            mode = None if ht == "SKIP" else ht
            side = None
            i += 1
            continue
        tok = lines[i]
        nxt = lines[i + 1] if i + 1 < n else ""
        nxt_odds = bool(ODDS.match(nxt)) and _f(nxt) is not None and _f(nxt) >= 1.01
        if mode in ("ML", "DC", "DNB"):
            if nxt_odds and not ODDS.match(tok):
                rows.append({"market": MARKET_NAME[mode], "team": tok, "line": "", "odds": _f(nxt)})
                i += 2
                continue
            i += 1
            continue
        if mode == "BTTS":
            if nxt_odds and tok.lower() in ("yes", "no"):
                rows.append({"market": MARKET_NAME[mode], "team": tok, "line": "", "odds": _f(nxt)})
                i += 2
                continue
            i += 1
            continue
        if mode == "HCAP":
            if re.search(r'[a-zA-Z]', tok):
                side = tok
                i += 1
                continue
            if LINEV.match(tok) and nxt_odds:
                rows.append({"market": MARKET_NAME[mode], "team": side or "", "line": tok, "odds": _f(nxt)})
                i += 2
                continue
            i += 1
            continue
        if mode == "TOT":
            low = tok.lower()
            if low in ("over", "under"):
                side = tok
                i += 1
                continue
            if LINEV.match(tok) and nxt_odds:
                rows.append({"market": MARKET_NAME[mode], "team": side or "", "line": tok, "odds": _f(nxt)})
                i += 2
                continue
            i += 1
            continue
        i += 1
    return rows


# ------------------------------------------------------------------ self-test on a real copied page
SAMPLE = """1x2
Belgium
2.16
Draw
3.35
Senegal
3.65
To Qualify
Belgium
1.58
Senegal
2.39
1x2 (2UP) - Early Payout At 2 Goal Lead
Belgium
2.07
Draw
3.30
Senegal
3.35
Handicap
Belgium
+1.25
1.10
+1.0
1.11
+0.5
1.31
+0.25
1.40
0.0
1.53
-0.25
1.82
Senegal
-1.25
7.00
-1.0
6.60
-0.5
3.45
-0.25
3.00
0.0
2.55
+0.25
2.00
Show All
Total
Over
1.0
1.07
1.25
1.17
1.5
1.27
1.75
1.33
2.0
1.41
2.25
1.64
Under
1.0
8.60
1.25
5.00
1.5
3.80
1.75
3.35
2.0
2.90
2.25
2.27
Show All
Draw No Bet
Belgium
1.53
Senegal
2.55
Double Chance
Belgium Or Draw
1.33
Belgium Or Senegal
1.37
Draw Or Senegal
1.74
Both Teams To Score
Yes
1.75
No
2.05
1st Goalscorer
Lukaku, Romelu
5.80
Anytime Goalscorer
Lukaku, Romelu
2.70"""


def main():
    from collections import Counter
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            text = f.read()
    else:
        text = SAMPLE
    rows = parse_vertical(text)
    print("rows:", len(rows), "by market:", dict(Counter(x["market"] for x in rows)))
    for x in rows:
        print(f"  {x['market']:20} {x['team']:16} {x['line'] or '':6} {x['odds']}")
    if len(sys.argv) == 1:
        expected = {"1x2": 3, "Handicap": 12, "Total": 12, "Draw No Bet": 2, "Double Chance": 3, "Both Teams To Score": 2}
        got = dict(Counter(x["market"] for x in rows))
        assert got == expected, f"self-test failed: {got} != {expected}"
        print("self-test OK")


if __name__ == "__main__":
    main()
