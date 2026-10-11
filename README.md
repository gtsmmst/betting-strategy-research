# betting-strategy-research

Research notebook: football and Polymarket strategy ideas, backtested between June and September
2026. Most of them failed. That is the point of the repo: each folder is a
**hypothesis -> data -> result -> verdict** write-up with the real numbers kept and the script
that produced them, so the negative results are as reproducible as a positive one would have been.

The code and write-ups were produced together with an AI assistant; the hypotheses, the data
choices and the verdicts are mine. Nothing here is financial advice, and nothing here is a
working edge.

## Strategy index

| Strategy | Hypothesis | Data | n | Result | Verdict | Status |
|---|---|---|---|---|---|---|
| [`football_draw_70/`](football_draw_70/) Back the draw from a 1-goal lead at 70' | The draw is under-priced when the leading side is not the favourite | API-Football, 5 top leagues, 2021-23 (probabilities); Polymarket CLOB 1-minute prices, 2024-26 (prices) | 1928 setups for the probabilities; 652 priced setups (517 clean) | Conditional draw rates replicated (fav 15.3% / even 21.2% / underdog 29.7%), but the market priced the draw at 23.6c against a realised 20.1%: EV -7% to -15% | **No edge** | Closed 2026-07-08 |
| [`polymarket_yield/`](polymarket_yield/) Buy near-certain outcomes (90-99.5c) 72h before resolution | "Almost certain" is under-priced; a yield on idle capital | 893 Polymarket tickets from closed markets, Jul 2025 - Jul 2026 (soccer, esports, tennis, politics) | 893 | Hit rate 95.6% at an average entry of 95.7c: yield per $1 = -0.08% +/-1.41 before fees | **No edge** | Closed |
| [`semi_arb_sharp_reference/`](semi_arb_sharp_reference/) Buy on Polymarket where the ask is >= 2c below the sharp-book fair probability | Sell insurance above cost, no hedge; the flow wins | Paper forward test, tier-2/3 CS2 pre-match, 2026-08-07 .. 09-06, $25 tickets | 25 core (30 with flags) | Core rule ROI -19.4%; the only positive pocket is n = 5 | **Not working as specified** | Paper test closed 2026-09-06 |
| [`polymarket_scanners/`](polymarket_scanners/) neg-risk arb, resolution yield, liquidity-reward market making, cheap tails / tail lottery | Tools for four patterns | Live Gamma / CLOB APIs | - | Candidate lists only; the resolution-yield pattern is the one that got backtested (above) | **Idea only** (except resolution yield: no edge) | Tools |
| Comebacks after 70' (side result in `football_draw_70/`) | Trailing favourites come back more often than the market expects | Same 2021-23 sample | 1928 | ~8% comeback rate overall, higher when the favourite trails | **Idea only** (never priced) | Parked |

## Layout

```
football_draw_70/            step-1 backtest, step-2 price collection, offline analyzer, live scanner, 20-row sample
polymarket_yield/            backtest script + the full 893-row dataset
polymarket_scanners/         four stand-alone scanners (public APIs, no keys)
semi_arb_sharp_reference/    write-up only (mechanics, variance math, paper-test verdict)
tools/parse_vertical_odds.py parser for the "vertical" odds text layout that sportsbook pages produce on copy
```

Every script is standard-library Python 3.9+ (`requirements.txt` is empty on purpose), has a
`--help`, and compiles with `py_compile`.

## Data: what is shipped and what is not

| Dataset | Origin | Shipped? |
|---|---|---|
| `polymarket_yield/data/poly_yield_dataset.json` (893 rows) | Polymarket public APIs only | **Yes, in full.** `python polymarket_yield/poly_yield_backtest.py` reproduces the table in that README offline |
| Draw datasets, 1486 rows (`draw_poly_dataset_2024/2025.json`) | Per-match scores at 70' and full-time results from API-Football (paid provider) merged with Polymarket prices | **No.** A 20-row stratified sample is in `football_draw_70/data/samples/`; `draw_poly_backtest.py` rebuilds the full files from your own account |
| API-Football cache for the 2021-23 probabilities | API-Football | **No.** `draw_backtest.py` rebuilds it (cached locally after the first run) |

## Setup

```
cp .env.example .env         # only needed for the three API-Football scripts
export $(cat .env | xargs)
python football_draw_70/draw_poly_analyze.py          # offline, runs on the sample
python polymarket_yield/poly_yield_backtest.py        # offline, runs on the full dataset
python polymarket_scanners/poly_arb_scanner.py --help
```

## House rule that came out of this

A hypothesis is not a strategy until it has been run against the venue's real historical prices,
with confidence intervals, before any money is involved. The draw strategy looked like +30-50% EV
on conditional probabilities alone and turned out to be -7% to -15% once the actual Polymarket
prices were pulled. Checking cost nothing; not checking would have cost a bankroll.

## License

MIT, see [LICENSE](LICENSE).
